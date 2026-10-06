"""Telethon adapter for authorized sources.

The optional ``telethon`` dependency is imported lazily, so the bot runs with
no Telegram user-account configured. Every operation requires that the
authenticated account can already access the source: access is verified against
the account's own dialog list and never bypassed.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from collections.abc import Callable
from pathlib import Path

from bot.config import Settings
from bot.db.engine import session_scope
from bot.db.repositories import get_bot_setting, set_bot_setting
from bot.services.engine import (
    WORKERS,
    OutputSink,
    ScanNotifier,
    ScanState,
    plan_windows,
)
from bot.services.scraper import (
    AccountRegistry,
    MessageDatum,
    ScrapeOptions,
    ScrapeResult,
    is_scraper_available,
    message_matches,
)

logger = logging.getLogger(__name__)

ProgressFn = Callable[[int], None]


async def _stop_requested(should_stop) -> bool:  # noqa: ANN001
    """Evaluate a stop predicate that may be sync or async."""
    if should_stop is None:
        return False
    result = should_stop()
    if hasattr(result, "__await__"):
        result = await result
    return bool(result)


class ScraperUnavailable(RuntimeError):
    """Raised when Telethon or the API credentials are not configured."""


class SourceAccessDenied(PermissionError):
    """Raised when the account cannot access the requested source."""


def friendly_error(exc: BaseException) -> str:
    """Turn a Telethon/other exception into a clear, non-secret message."""
    name = type(exc).__name__
    text = str(exc)
    lowered = text.lower()
    if "floodwait" in name.lower() or "wait of" in lowered or "flood" in lowered:
        return "Telegram rate limit hit (FloodWait). Wait a little, then retry."
    if name in {
        "AuthKeyUnregisteredError",
        "AuthKeyDuplicatedError",
        "SessionRevokedError",
        "UserDeactivatedError",
        "UserDeactivatedBanError",
    }:
        return "This session is no longer valid — reconnect the account."
    if name in {"ChannelPrivateError", "ChatAdminRequiredError", "ChannelInvalidError"}:
        return "That chat is not accessible from this account."
    if name in {"UsernameNotOccupiedError", "UsernameInvalidError"}:
        return "No such username for this account."
    if name in {"PhoneCodeInvalidError", "PhoneCodeExpiredError"}:
        return "The login code was invalid or expired. Try again."
    if name in {"SessionPasswordNeededError"}:
        return "This account has 2FA enabled — a password is required."
    if name == "ScraperUnavailable":
        return text
    return f"{name}: {text[:180]}" if text else name


def _classify(message) -> str | None:  # noqa: ANN001 - Telethon message
    if getattr(message, "photo", None):
        return "photo"
    if getattr(message, "video_note", None):
        return "video"
    if getattr(message, "voice", None):
        return "voice"
    if getattr(message, "audio", None):
        return "audio"
    if getattr(message, "video", None):
        return "video"
    if getattr(message, "document", None):
        return "document"
    return None


def to_datum(message) -> MessageDatum:  # noqa: ANN001 - Telethon message
    """Convert a Telethon message into a normalized, non-secret datum."""
    file_name = None
    file_size = None
    file = getattr(message, "file", None)
    if file is not None:
        file_name = getattr(file, "name", None)
        file_size = getattr(file, "size", None)
    return MessageDatum(
        id=int(message.id),
        date=message.date,
        text=getattr(message, "raw_text", None) or getattr(message, "message", "") or "",
        sender_id=getattr(message, "sender_id", None),
        media_type=_classify(message),
        file_name=file_name,
        file_size=file_size,
    )


class TelethonScraper:
    """Reads only from sources the configured account can legitimately access."""

    def __init__(self, settings: Settings, registry: AccountRegistry) -> None:
        self._settings = settings
        self._registry = registry
        self._pending: dict[int, dict] = {}

    @property
    def registry(self) -> AccountRegistry:
        return self._registry

    def available(self) -> bool:
        return (
            is_scraper_available()
            and self._settings.telegram_api_id > 0
            and bool(self._settings.telegram_api_hash.get_secret_value())
        )

    # -- per-user accounts (multiple, persistent) --------------------------- #
    def new_label(self, owner: int) -> str:
        existing = {a.label for a in self._registry.accounts_for(owner)}
        base = f"account-{owner}"
        if base not in existing:
            return base
        index = 2
        while f"{base}-{index}" in existing:
            index += 1
        return f"{base}-{index}"

    def _active_key(self, owner: int) -> str:
        return f"active_account:{owner}"

    async def set_active(self, owner: int, label: str) -> None:
        async with session_scope() as session:
            await set_bot_setting(session, self._active_key(owner), label)

    async def active_label(self, owner: int) -> str | None:
        accounts = self._registry.accounts_for(owner)
        if not accounts:
            return None
        try:
            async with session_scope() as session:
                chosen = await get_bot_setting(session, self._active_key(owner))
        except Exception:  # noqa: BLE001
            chosen = None
        labels = {a.label for a in accounts}
        if chosen and chosen in labels:
            return chosen
        return accounts[0].label

    def accounts_for(self, owner: int) -> list:
        return self._registry.accounts_for(owner)

    def all_accounts(self) -> list:
        """Every account on the server (for admin/manager control)."""
        return self._registry.load()

    def _acting_key(self, owner: int) -> str:
        return f"acting_account:{owner}"

    async def acting_label(self, owner: int) -> str | None:
        """An account chosen by an admin to scrape on behalf of another owner."""
        try:
            async with session_scope() as session:
                label = await get_bot_setting(session, self._acting_key(owner))
        except Exception:  # noqa: BLE001
            return None
        if label and self._registry.get(label) is not None:
            return label
        return None

    async def set_acting(self, owner: int, label: str) -> None:
        async with session_scope() as session:
            await set_bot_setting(session, self._acting_key(owner), label)

    async def clear_acting(self, owner: int) -> None:
        await self.set_acting(owner, "")

    def user_account(self, owner: int):  # noqa: ANN201
        accounts = self._registry.accounts_for(owner)
        return accounts[0] if accounts else None

    def user_connected(self, owner: int) -> bool:
        return any(
            self._registry.status(a) == "Connected"
            for a in self._registry.accounts_for(owner)
        )

    async def start_login(self, *, owner: int, phone: str, label: str | None = None) -> str:
        """Send a login code to ``phone`` and remember the pending session."""
        if not self.available():
            raise ScraperUnavailable("Telegram API credentials are not configured.")
        from telethon import TelegramClient  # lazy

        label = label or self.new_label(owner)
        self._registry.session_dir.mkdir(parents=True, exist_ok=True)
        session_path = self._registry.session_dir / f"{owner}_{label}.session"
        client = TelegramClient(
            str(session_path),
            self._settings.telegram_api_id,
            self._settings.telegram_api_hash.get_secret_value(),
        )
        await client.connect()
        sent = await client.send_code_request(phone)
        self._pending[owner] = {
            "client": client,
            "phone": phone,
            "hash": sent.phone_code_hash,
            "label": label,
        }
        return label

    # -- session blobs: survive redeploys with no volume -------------------- #
    def _blob_key(self, label: str) -> str:
        return f"session_blob:{label}"

    async def _store_blob(self, label: str) -> None:
        account = self._registry.get(label)
        if account is None:
            return
        path = self._registry.session_path(account)
        if not path.is_file():
            return
        try:
            blob = base64.b64encode(path.read_bytes()).decode("ascii")
            async with session_scope() as session:
                await set_bot_setting(session, self._blob_key(label), blob)
        except Exception:  # noqa: BLE001 - persistence is best-effort
            logger.exception("Could not store session blob for %s", label)

    async def _restore_blob(self, label: str) -> None:
        account = self._registry.get(label)
        if account is None:
            return
        path = self._registry.session_path(account)
        if path.is_file():
            return
        try:
            async with session_scope() as session:
                blob = await get_bot_setting(session, self._blob_key(label))
        except Exception:  # noqa: BLE001
            return
        if not blob:
            return
        try:
            self._registry.session_dir.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(blob))
            logger.info("Restored session for %s from database", label)
        except Exception:  # noqa: BLE001
            logger.exception("Could not restore session for %s", label)

    async def _forget_blob(self, label: str) -> None:
        try:
            async with session_scope() as session:
                await set_bot_setting(session, self._blob_key(label), "")
        except Exception:  # noqa: BLE001
            pass

    async def confirm_code(self, *, owner: int, code: str) -> str:
        state = self._pending.get(owner)
        if not state:
            return "expired"
        from telethon.errors import SessionPasswordNeededError

        try:
            await state["client"].sign_in(
                state["phone"], code=code, phone_code_hash=state["hash"]
            )
        except SessionPasswordNeededError:
            return "password"
        except Exception as exc:  # noqa: BLE001
            return f"error:{type(exc).__name__}"
        await self._finish_login(owner)
        return "ok"

    async def confirm_password(self, *, owner: int, password: str) -> str:
        state = self._pending.get(owner)
        if not state:
            return "expired"
        try:
            await state["client"].sign_in(password=password)
        except Exception as exc:  # noqa: BLE001
            return f"error:{type(exc).__name__}"
        await self._finish_login(owner)
        return "ok"

    async def _finish_login(self, owner: int) -> None:
        state = self._pending.pop(owner, None)
        if state:
            try:
                await state["client"].disconnect()
            except Exception:  # noqa: BLE001
                pass
            label = state["label"]
            self._registry.upsert(label, owner=owner, session=label, enabled=True)
            await self.set_active(owner, label)
            await self._store_blob(label)

    async def logout(self, owner: int, label: str) -> None:
        self._registry.delete(label)
        await self._forget_blob(label)

    def _session_path(self, label: str) -> Path:
        account = self._registry.get(label)
        if account is None:
            raise ScraperUnavailable(f"Unknown account label: {label}")
        return self._registry.session_path(account)

    async def _make_client(self, label: str):  # noqa: ANN001
        if not self.available():
            raise ScraperUnavailable(
                "Telethon/API credentials are not configured (see /plogin)."
            )
        await self._restore_blob(label)
        from telethon import TelegramClient  # lazy, optional dependency

        return TelegramClient(
            str(self._session_path(label)),
            self._settings.telegram_api_id,
            self._settings.telegram_api_hash.get_secret_value(),
            # Ride out Telegram's throttling instead of dying mid-run.
            flood_sleep_threshold=600,
            connection_retries=5,
            request_retries=5,
            retry_delay=2,
        )

    async def _find_dialog_entity(self, client, peer_ref: str):  # noqa: ANN001, ANN201
        """Resolve a peer to a dialog entity the account can actually see.

        Works for public @usernames, numeric ids (including ``-100…``) and
        titles — this is what makes private groups/channels work reliably
        (their entities are not always resolvable via ``get_entity``).
        """
        ref = (peer_ref or "").strip()
        if not ref or "t.me/+" in ref or ref.startswith("+") or "/joinchat/" in ref:
            return None, None

        digits = ref.lstrip("-")
        want_id: int | None = int(digits) if digits.isdigit() else None
        if want_id is not None and str(abs(want_id)).startswith("100") and len(str(abs(want_id))) > 10:
            want_id = int(str(abs(want_id))[3:])  # -100XXXXXXXXXX -> XXXXX

        needle = ref.lower().lstrip("@")

        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            if entity is None:
                continue
            title = (
                getattr(entity, "title", None)
                or getattr(entity, "username", None)
                or getattr(entity, "first_name", None)
                or ""
            )
            if want_id is not None and getattr(entity, "id", None) == want_id:
                return entity, title
            username = (getattr(entity, "username", None) or "").lower()
            if username and username == needle:
                return entity, title
            if (title or "").lower() == needle:
                return entity, title
        return None, None

    async def verify_source(self, label: str, peer_ref: str) -> str | None:
        """Return the source title if the account can access it, else None."""
        client = await self._make_client(label)
        async with client:
            entity, title = await self._find_dialog_entity(client, peer_ref)
            return title if entity is not None else None

    async def scrape(
        self,
        *,
        label: str,
        peer_ref: str,
        out: str | Path,
        options: ScrapeOptions,
        fmt: str,
        on_progress: ProgressFn | None = None,
        on_scan=None,  # noqa: ANN001 - ScanProgress -> None (sync or async)
        should_stop=None,  # noqa: ANN001 - () -> bool (sync or async)
        workers: int = WORKERS,
    ) -> ScrapeResult:
        """Read authorised history into ``out`` using the fast engine.

        * keywords are pushed to Telegram's **server-side search** (big win);
        * plain history scans run in parallel **date windows**;
        * output is streamed to disk (flat memory) and de-duplicated by id;
        * ``should_stop`` aborts mid-source, keeping whatever matched so far;
        * if a server search finds nothing we fall back to a local full scan.
        """
        client = await self._make_client(label)
        sink = OutputSink(out, options=options, fmt=fmt)
        state = ScanState(options.date_from, options.date_to)
        notifier = ScanNotifier(on_scan)
        try:
            async with client:
                entity, _ = await self._find_dialog_entity(client, peer_ref)
                if entity is None:
                    raise SourceAccessDenied(
                        "The authenticated account can't access this source. It must be "
                        "your own, or one you're a member of (invite links aren't supported)."
                    )

                keywords = options.all_keywords()
                searchable = bool(keywords) and options.keyword_mode != "regex"
                if searchable:
                    await self._scan_search(
                        client, entity, sink, options, keywords, state, notifier,
                        should_stop, workers,
                    )
                if sink.exported == 0:
                    # No keyword search (or it found nothing): walk history instead.
                    await self._scan_history(
                        client, entity, sink, options, state, notifier, should_stop, workers
                    )
        finally:
            sink.close()

        await self._store_blob(label)
        await notifier.tick(state, sink, force=True)
        if on_progress:
            on_progress(sink.scanned)
        return sink.result

    async def _scan_search(
        self, client, entity, sink, options, keywords, state, notifier, should_stop, workers  # noqa: ANN001
    ) -> None:
        windows = plan_windows(
            options.date_from, options.date_to, 1 if options.limit else max(1, workers)
        )
        semaphore = asyncio.Semaphore(max(1, workers))
        limit = options.limit or 0
        first_error: list[Exception] = []
        matched_ids: list[int] = []

        async def task(term: str, lo, hi) -> None:  # noqa: ANN001
            async with semaphore:
                try:
                    async for message in client.iter_messages(
                        entity, search=term, offset_date=hi, wait_time=0
                    ):
                        if limit and sink.exported >= limit:
                            return
                        if lo is not None and message.date < lo:
                            break
                        if state.scanned % 50 == 0 and await _stop_requested(should_stop):
                            return
                        state.bump(message.date)
                        datum = to_datum(message)
                        if sink.consider(datum):
                            matched_ids.append(datum.id)
                        await notifier.tick(state, sink)
                except Exception as exc:  # noqa: BLE001 - one worker must not kill the run
                    if not first_error:
                        first_error.append(exc)
                    logger.warning("Search worker failed (%s)", friendly_error(exc))

        await asyncio.gather(
            *(task(term, lo, hi) for term in keywords for lo, hi in windows)
        )

        # Pull ±1 related messages around each match (bounded so huge hits don't explode).
        if options.context and matched_ids and len(matched_ids) <= 400:
            neighbor_ids: list[int] = []
            for mid in matched_ids:
                neighbor_ids.extend((mid - 1, mid + 1))
            try:
                async for message in client.iter_messages(entity, ids=neighbor_ids):
                    if message is None:
                        continue
                    if limit and sink.exported >= limit:
                        break
                    if await _stop_requested(should_stop):
                        break
                    state.bump(message.date)
                    sink.add_direct(to_datum(message))
                    await notifier.tick(state, sink)
            except Exception as exc:  # noqa: BLE001 - context is best-effort
                logger.warning("Context fetch failed (%s)", friendly_error(exc))

        if not sink.scanned and first_error:
            raise first_error[0]

    async def _scan_history(
        self, client, entity, sink, options, state, notifier, should_stop, workers  # noqa: ANN001
    ) -> None:
        windows = plan_windows(
            options.date_from, options.date_to, 1 if options.limit else max(1, workers)
        )
        semaphore = asyncio.Semaphore(max(1, workers))
        limit = options.limit or 0
        first_error: list[Exception] = []

        async def task(lo, hi) -> None:  # noqa: ANN001
            async with semaphore:
                prev_datum = None
                include_next = 0
                try:
                    async for message in client.iter_messages(
                        entity, limit=(limit or None), offset_date=hi, wait_time=0
                    ):
                        if limit and sink.exported >= limit:
                            return
                        if lo is not None and message.date < lo:
                            break
                        if state.scanned % 50 == 0 and await _stop_requested(should_stop):
                            return
                        state.bump(message.date)
                        datum = to_datum(message)
                        matched = sink.consider(datum)
                        if matched:
                            if options.context and prev_datum is not None:
                                sink.add_direct(prev_datum)
                            include_next = options.context
                        elif include_next > 0:
                            sink.add_direct(datum)
                            include_next -= 1
                        prev_datum = datum
                        await notifier.tick(state, sink)
                except Exception as exc:  # noqa: BLE001 - one worker must not kill the run
                    if not first_error:
                        first_error.append(exc)
                    logger.warning("History worker failed (%s)", friendly_error(exc))

        await asyncio.gather(*(task(lo, hi) for lo, hi in windows))
        if not sink.scanned and first_error:
            raise first_error[0]

    # -- dialogs ------------------------------------------------------------ #
    @staticmethod
    def _can_post(entity, is_channel: bool) -> bool:  # noqa: ANN001
        if getattr(entity, "creator", False):
            return True
        rights = getattr(entity, "admin_rights", None)
        if rights is not None and (
            getattr(rights, "post_messages", False) or getattr(rights, "send_messages", False)
        ):
            return True
        banned = getattr(entity, "default_banned_rights", None)
        if banned is not None and getattr(banned, "send_messages", False):
            return False
        return not is_channel

    async def list_dialogs(self, label: str, *, limit: int = 200) -> list[dict]:
        """Return the account's channels/groups so the user can pick one."""
        client = await self._make_client(label)
        found: list[dict] = []
        try:
            async with client:
                async for dialog in client.iter_dialogs(limit=limit):
                    if getattr(dialog, "is_user", False):
                        continue
                    entity = dialog.entity
                    if entity is None:
                        continue
                    is_channel = bool(getattr(dialog, "is_channel", False))
                    found.append(
                        {
                            "id": int(dialog.id),
                            "title": dialog.name or str(dialog.id),
                            "channel": is_channel,
                            "can_post": self._can_post(entity, is_channel),
                        }
                    )
        finally:
            await self._store_blob(label)
        return found

    async def leave_chat(self, label: str, peer_ref: str) -> None:
        """Leave a joined channel/group so the user's account is restored."""
        from telethon import functions  # lazy
        from telethon.tl.types import Channel, Chat

        client = await self._make_client(label)
        try:
            async with client:
                entity, _ = await self._find_dialog_entity(client, peer_ref)
                if entity is None:
                    raise SourceAccessDenied("That chat isn't in your dialogs.")
                if isinstance(entity, Channel):
                    await client(functions.channels.LeaveChannelRequest(entity))
                elif isinstance(entity, Chat):
                    me = await client.get_me()
                    await client(functions.messages.DeleteChatUserRequest(entity.id, me))
                else:
                    raise SourceAccessDenied("This chat type can't be left automatically.")
        finally:
            await self._store_blob(label)

    @staticmethod
    def _invite_hash(link: str) -> str | None:
        ref = (link or "").strip()
        for needle in ("t.me/+", "joinchat/", "t.me/joinchat/"):
            if needle in ref:
                return ref.split(needle, 1)[1].split("/")[0].split("?")[0]
        if ref.startswith("+"):
            return ref[1:].split("/")[0].split("?")[0]
        return None

    @staticmethod
    def _username(link: str) -> str | None:
        ref = (link or "").strip()
        if ref.startswith("@"):
            return ref[1:].split("/")[0].split("?")[0]
        if "t.me/" in ref and "+" not in ref and "joinchat" not in ref:
            return ref.split("t.me/", 1)[1].split("/")[0].split("?")[0]
        return None

    async def join_chat(self, label: str, link: str) -> tuple[int, str]:
        """Join a channel/group by invite link or @username. Returns (peer_id, title)."""
        from telethon import errors, functions  # lazy

        client = await self._make_client(label)
        ref = (link or "").strip()
        if not ref:
            raise SourceAccessDenied("Send a link or @username.")

        try:
            async with client:
                hash_part = self._invite_hash(ref)
                if hash_part:
                    try:
                        updates = await client(
                            functions.messages.ImportChatInviteRequest(hash_part)
                        )
                    except errors.UserAlreadyParticipantError as exc:
                        raise SourceAccessDenied(
                            "You're already a member of that chat. Use /scrape on it instead."
                        ) from exc
                    chats = getattr(updates, "chats", []) or []
                    if not chats:
                        raise SourceAccessDenied("Could not join that chat.")
                    chat = chats[0]
                    return int(chat.id), getattr(chat, "title", None) or "joined chat"

                username = self._username(ref)
                if username:
                    await client(functions.channels.JoinChannelRequest(username))
                    entity = await client.get_entity(username)
                    return int(entity.id), getattr(entity, "title", None) or username

                raise SourceAccessDenied(
                    "Unrecognised link. Use t.me/+…, t.me/joinchat/… or @username."
                )
        finally:
            await self._store_blob(label)

    async def _flush_batch(self, client, dest, batch, source, copy: bool) -> None:  # noqa: ANN001
        try:
            await client.forward_messages(dest, batch, source, drop_author=copy)
        except Exception as exc:  # noqa: BLE001
            name = type(exc).__name__
            if "FloodWait" in name:
                wait = int(getattr(exc, "seconds", 30)) + 2
                logger.warning("FloodWait: sleeping %ss during clone", wait)
                await asyncio.sleep(wait)
                await client.forward_messages(dest, batch, source, drop_author=copy)
                return
            raise

    async def clone(
        self,
        *,
        label: str,
        src_ref: str,
        dest_ref: str,
        limit: int = 1000,
        copy: bool = False,
        options: ScrapeOptions | None = None,
        on_progress: ProgressFn | None = None,
        should_stop=None,  # noqa: ANN001
    ) -> int:
        """Copy messages from a source chat into a destination channel.

        ``copy=True`` drops the original attribution (a copy rather than a
        forward). Filters (keyword/date) reuse the scrape options. Uses the
        account's own membership; nothing is bypassed.
        """
        client = await self._make_client(label)
        copied = 0
        batch: list = []
        try:
            async with client:
                source, _ = await self._find_dialog_entity(client, src_ref)
                if source is None:
                    raise SourceAccessDenied(f"Source not accessible: {src_ref}")
                destination, _ = await self._find_dialog_entity(client, dest_ref)
                if destination is None:
                    raise SourceAccessDenied(f"Destination not accessible: {dest_ref}")

                search = None
                if options is not None:
                    keywords = options.all_keywords()
                    if keywords and options.keyword_mode != "regex":
                        search = keywords[0]

                async for message in client.iter_messages(
                    source,
                    limit=limit or None,
                    offset_date=(options.date_to if options else None),
                    search=search,
                    wait_time=0,
                ):
                    if options is not None and options.date_from and message.date < options.date_from:
                        break
                    if options is not None and not message_matches(to_datum(message), options):
                        continue
                    batch.append(message)
                    if len(batch) >= 100:
                        await self._flush_batch(client, destination, batch, source, copy)
                        copied += len(batch)
                        batch = []
                        if on_progress:
                            on_progress(copied)
                        if await _stop_requested(should_stop):
                            break
                        await asyncio.sleep(0.4)
                if batch:
                    await self._flush_batch(client, destination, batch, source, copy)
                    copied += len(batch)
                    if on_progress:
                        on_progress(copied)
        finally:
            await self._store_blob(label)
        return copied

