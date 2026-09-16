"""Per-user scrape preferences (remembered defaults)."""

from __future__ import annotations

import json

from bot.config import get_settings
from bot.db.engine import session_scope
from bot.db.repositories import get_bot_setting, set_bot_setting

_PREFIX = "scrape_def:"

DEFAULTS = {
    "limit": 100,
    "mode": "messages",
    "autoclean": True,
    "dates": "none",
    "keywords": [],
    "include_media": False,
}


def _key(telegram_id: int) -> str:
    return f"{_PREFIX}{telegram_id}"


async def load_prefs(telegram_id: int) -> dict:
    values = dict(DEFAULTS)
    # Environment default for media can be handy; keep False otherwise.
    _ = get_settings()
    try:
        async with session_scope() as session:
            raw = await get_bot_setting(session, _key(telegram_id))
    except Exception:  # noqa: BLE001
        return values
    if not raw:
        return values
    try:
        stored = json.loads(raw)
    except json.JSONDecodeError:
        return values
    for key in DEFAULTS:
        if key in stored:
            values[key] = stored[key]
    return values


async def save_prefs(telegram_id: int, values: dict) -> None:
    payload = {key: values.get(key, DEFAULTS[key]) for key in DEFAULTS}
    async with session_scope() as session:
        await set_bot_setting(session, _key(telegram_id), json.dumps(payload))
