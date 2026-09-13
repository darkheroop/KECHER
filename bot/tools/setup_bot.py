"""Apply the bot command menu and profile descriptions.

Usage:
    python -m bot.tools.setup_bot
"""

from __future__ import annotations

import asyncio

from bot.config import get_settings
from bot.logging_setup import setup_logging
from bot.main import build_bot
from bot.ui.commands import configure_bot


async def _run() -> int:
    settings = get_settings()
    setup_logging(settings)
    if not settings.bot_token.get_secret_value():
        print("BOT_TOKEN is not configured (see .env).")
        return 1

    bot = build_bot(settings)
    try:
        await configure_bot(bot)
        me = await bot.get_me()
        print(f"Configured command menu and descriptions for @{me.username}.")
    finally:
        await bot.session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
