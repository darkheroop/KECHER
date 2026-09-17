"""Runtime configuration stored in the DB (set from the admin panel).

Covers Telegram API credentials and the destination channel ids, so the owner
never has to edit server environment variables.
"""

from __future__ import annotations

from pydantic import SecretStr

from bot.config import Settings
from bot.db.engine import session_scope
from bot.db.repositories import get_bot_setting, set_bot_setting
from bot.services import naming

API_ID_KEY = "telegram_api_id"
API_HASH_KEY = "telegram_api_hash"
FORWARD_KEY = "forward_channel_id"
SCRAPE_KEY = "scrape_channel_id"
SUFFIX_KEY = "file_suffix"


def apply(settings: Settings, api_id: str | None, api_hash: str | None) -> None:
    if api_id:
        text = api_id.strip()
        if text.isdigit():
            settings.telegram_api_id = int(text)
    if api_hash:
        settings.telegram_api_hash = SecretStr(api_hash.strip())


def apply_channels(
    settings: Settings, forward: str | None, scrape: str | None
) -> None:
    if forward is not None:
        settings.forward_channel_id = forward.strip()
    if scrape is not None:
        settings.scrape_channel_id = scrape.strip()


def is_configured(settings: Settings) -> bool:
    return settings.telegram_api_id > 0 and bool(
        settings.telegram_api_hash.get_secret_value()
    )


async def load_into_settings(settings: Settings) -> None:
    """Load DB-stored credentials/channels over the environment values."""
    try:
        async with session_scope() as session:
            api_id = await get_bot_setting(session, API_ID_KEY)
            api_hash = await get_bot_setting(session, API_HASH_KEY)
            forward = await get_bot_setting(session, FORWARD_KEY)
            scrape = await get_bot_setting(session, SCRAPE_KEY)
            suffix_value = await get_bot_setting(session, SUFFIX_KEY)
    except Exception:  # noqa: BLE001 - table may not exist yet
        naming.set_suffix(settings.file_suffix)
        return
    apply(settings, api_id, api_hash)
    apply_channels(settings, forward, scrape)
    naming.set_suffix(suffix_value if suffix_value is not None else settings.file_suffix)


async def save_suffix(value: str) -> None:
    """Persist the global output filename suffix (admin panel)."""
    async with session_scope() as session:
        await set_bot_setting(session, SUFFIX_KEY, value.strip())
    naming.set_suffix(value.strip())


async def save(settings: Settings, api_id: str, api_hash: str) -> None:
    async with session_scope() as session:
        await set_bot_setting(session, API_ID_KEY, api_id)
        await set_bot_setting(session, API_HASH_KEY, api_hash)
    apply(settings, api_id, api_hash)


async def save_channel(settings: Settings, which: str, value: str) -> None:
    key = SCRAPE_KEY if which == "scrape" else FORWARD_KEY
    async with session_scope() as session:
        await set_bot_setting(session, key, value.strip())
    if which == "scrape":
        settings.scrape_channel_id = value.strip()
    else:
        settings.forward_channel_id = value.strip()
