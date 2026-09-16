"""Telegram API credentials (api_id/api_hash) for Telethon.

Values can come from the environment OR be set by an admin from the bot
(stored in ``bot_settings``). This keeps setup entirely in-app.
"""

from __future__ import annotations

from pydantic import SecretStr

from bot.config import Settings
from bot.db.engine import session_scope
from bot.db.repositories import get_bot_setting, set_bot_setting

API_ID_KEY = "telegram_api_id"
API_HASH_KEY = "telegram_api_hash"


def apply(settings: Settings, api_id: str | None, api_hash: str | None) -> None:
    if api_id:
        text = api_id.strip()
        if text.isdigit():
            settings.telegram_api_id = int(text)
    if api_hash:
        settings.telegram_api_hash = SecretStr(api_hash.strip())


def is_configured(settings: Settings) -> bool:
    return settings.telegram_api_id > 0 and bool(
        settings.telegram_api_hash.get_secret_value()
    )


async def load_into_settings(settings: Settings) -> None:
    """Load any DB-stored credentials over the environment values."""
    try:
        async with session_scope() as session:
            api_id = await get_bot_setting(session, API_ID_KEY)
            api_hash = await get_bot_setting(session, API_HASH_KEY)
    except Exception:  # noqa: BLE001 - table may not exist yet
        return
    apply(settings, api_id, api_hash)


async def save(settings: Settings, api_id: str, api_hash: str) -> None:
    async with session_scope() as session:
        await set_bot_setting(session, API_ID_KEY, api_id)
        await set_bot_setting(session, API_HASH_KEY, api_hash)
    apply(settings, api_id, api_hash)
