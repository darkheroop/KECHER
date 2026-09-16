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
from bot.services.scraper import (
    AccountRegistry,
    MessageDatum,
    ScrapeOptions,
    ScrapeResult,
    is_scraper_available,
    scrape_to_file,
)

logger = logging.getLogger(__name__)

ProgressFn = Callable[[int], None]


class ScraperUnavailable(RuntimeError):
    """Raised when Telethon or the API credentials are not configured."""


class SourceAccessDenied(PermissionError):
    """Raised when the account cannot access the requested source."""


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
        text=getattr(message, "raw_text", None) or "",
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
    ) -> ScrapeResult:
        client = await self._make_client(label)
        async with client:
            entity, _ = await self._find_dialog_entity(client, peer_ref)
            if entity is None:
                raise SourceAccessDenied(
                    "The authenticated account can't access this source. It must be "
                    "your own, or one you're a member of (invite links aren't supported)."
                )

            collected: list[MessageDatum] = []
            async for message in client.iter_messages(entity, limit=options.limit):
                collected.append(to_datum(message))

        await self._store_blob(label)
        return await asyncio.to_thread(
            scrape_to_file, collected, out, options=options, fmt=fmt, on_progress=on_progress
        )
