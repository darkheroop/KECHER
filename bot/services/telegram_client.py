"""Telethon adapter for authorized sources.

The optional ``telethon`` dependency is imported lazily, so the bot runs with
no Telegram user-account configured. Every operation requires that the
authenticated account can already access the source: access is verified against
the account's own dialog list and never bypassed.
"""

from __future__ import annotations

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

    def logout(self, owner: int, label: str) -> None:
        self._registry.delete(label)

    def _session_path(self, label: str) -> Path:
        account = self._registry.get(label)
        if account is None:
            raise ScraperUnavailable(f"Unknown account label: {label}")
        return self._registry.session_path(account)

    def _make_client(self, label: str):  # noqa: ANN001
        if not self.available():
            raise ScraperUnavailable(
                "Telethon/API credentials are not configured (see /plogin)."
            )
        from telethon import TelegramClient  # lazy, optional dependency

        return TelegramClient(
            str(self._session_path(label)),
            self._settings.telegram_api_id,
            self._settings.telegram_api_hash.get_secret_value(),
        )

    async def verify_source(self, label: str, peer_ref: str) -> str | None:
        """Return the source title if the account can access it, else None."""
        client = self._make_client(label)
        async with client:
            entity = await client.get_entity(peer_ref)
            async for dialog in client.iter_dialogs():
                if dialog.entity is not None and dialog.entity.id == entity.id:
                    return (
                        getattr(entity, "title", None)
                        or getattr(entity, "username", None)
                        or peer_ref
                    )
        return None

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
        client = self._make_client(label)
        async with client:
            entity = await client.get_entity(peer_ref)

            allowed = False
            async for dialog in client.iter_dialogs():
                if dialog.entity is not None and dialog.entity.id == entity.id:
                    allowed = True
                    break
            if not allowed:
                raise SourceAccessDenied(
                    "The authenticated account is not a member of this source."
                )

            collected: list[MessageDatum] = []
            async for message in client.iter_messages(entity, limit=options.limit):
                collected.append(to_datum(message))

        return scrape_to_file(
            collected, out, options=options, fmt=fmt, on_progress=on_progress
        )
