"""Official Telegram login helper.

Run this in your own terminal, never inside a bot chat::

    python -m bot.tools.plogin <label>

Telethon performs Telegram's official interactive login (phone number and
login code are entered here, in the terminal). The bot never receives, asks
for, or stores passwords, OTPs, or session strings -- only a label and the
path to the resulting ``*.session`` file.
"""

from __future__ import annotations

import asyncio
import sys

from bot.config import get_settings
from bot.services.scraper import AccountRegistry, is_scraper_available


async def _login(label: str) -> int:
    settings = get_settings()

    if not is_scraper_available():
        print("Telethon is not installed. Run: pip install telethon")
        return 1

    if settings.telegram_api_id <= 0 or not settings.telegram_api_hash.get_secret_value():
        print("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env first.")
        return 1

    from telethon import TelegramClient

    session_dir = settings.resolved_session_dir()
    session_dir.mkdir(parents=True, exist_ok=True)

    registry = AccountRegistry(settings.resolved_accounts_file(), session_dir)
    account = registry.get(label) or registry.upsert(label)
    session_path = registry.session_path(account)

    client = TelegramClient(
        str(session_path),
        settings.telegram_api_id,
        settings.telegram_api_hash.get_secret_value(),
    )
    async with client:
        await client.start()  # official interactive login
        me = await client.get_me()
        identifier = getattr(me, "username", None) or getattr(me, "id", "unknown")
        print(f"Logged in as {identifier}. Session saved for label '{label}'.")
    return 0


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python -m bot.tools.plogin <label>")
        return 2
    return asyncio.run(_login(sys.argv[1]))


if __name__ == "__main__":
    raise SystemExit(main())
