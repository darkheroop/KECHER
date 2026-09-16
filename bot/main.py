"""Application entry point for the Card File Bot.

Run with::

    python -m bot.main
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import Settings, get_settings
from bot.db.engine import dispose_engine, init_db
from bot.handlers import routers
from bot.handlers.errors import register_error_handler
from bot.logging_setup import setup_logging
from bot.security.middleware import (
    AccessMiddleware,
    RateLimitMiddleware,
    SafeEditMiddleware,
)
from bot.security.ratelimit import SlidingWindowLimiter
from bot.services.file_manager import FileManager
from bot.services.forwarder import forward_pending_files
from bot.services.retention import reap_expired_files
from bot.services.scraper import AccountRegistry
from bot.services.telegram_client import TelethonScraper
from bot.ui.commands import configure_bot
from bot.ui.emoji import configure_custom

logger = logging.getLogger(__name__)

REAP_INTERVAL_SECONDS = 300


async def verify_custom_emoji(bot: Bot, settings: Settings) -> None:
    """Disable premium emoji if this bot isn't allowed to use them.

    Telegram only lets bots use custom emoji if they own a Fragment-collected
    username; otherwise messages with <tg-emoji> are rejected. We probe once
    against an admin chat and fall back to Unicode automatically.
    """
    if not settings.custom_emoji_ids:
        return
    target = settings.admin_ids[0] if settings.admin_ids else None
    if target is None:
        logger.info("No ADMIN_IDS set; skipping custom-emoji verification")
        return
    sample = next(iter(settings.custom_emoji_ids.values()))
    try:
        await bot.send_message(
            target, f'<tg-emoji emoji-id="{sample}">✅</tg-emoji> emoji check'
        )
    except Exception as exc:  # noqa: BLE001
        configure_custom(None)
        logger.warning(
            "Premium emoji not supported (%s); using Unicode fallback",
            type(exc).__name__,
        )


def build_bot(settings: Settings) -> Bot:
    token = settings.bot_token.get_secret_value()
    default = DefaultBotProperties(parse_mode=ParseMode.HTML)
    if settings.telegram_api_base:
        session = AiohttpSession(api=TelegramAPIServer.from_base(settings.telegram_api_base))
        return Bot(token=token, session=session, default=default)
    return Bot(token=token, default=default)


async def retention_loop(files: FileManager) -> None:
    while True:
        try:
            await reap_expired_files(files)
        except asyncio.CancelledError:  # pragma: no cover - shutdown
            raise
        except Exception:  # noqa: BLE001 - never let the reaper die
            logger.exception("Retention reaper iteration failed")
        await asyncio.sleep(REAP_INTERVAL_SECONDS)


async def forward_loop(bot: Bot, files: FileManager, settings: Settings) -> None:
    """Every N hours, forward any not-yet-forwarded files to the channel."""
    interval = max(1, settings.forward_interval_hours) * 3600
    while True:
        await asyncio.sleep(interval)
        try:
            from bot.db.engine import session_scope
            from bot.db.repositories import get_bot_setting

            async with session_scope() as session:
                enabled = (
                    await get_bot_setting(session, "forward_enabled", "false")
                ) == "true"
            if enabled and settings.forward_channel_id:
                await forward_pending_files(bot, files, settings)
        except asyncio.CancelledError:  # pragma: no cover - shutdown
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Forward sweep failed")


async def run() -> None:
    settings = get_settings()
    setup_logging(settings)
    configure_custom(settings.custom_emoji_ids)

    if not settings.bot_token.get_secret_value():
        raise SystemExit("BOT_TOKEN is not configured (see .env.example).")

    if not settings.is_production:
        settings.resolved_storage_root().mkdir(parents=True, exist_ok=True)
        await init_db(settings)
        logger.info("Database schema ensured (development mode)")

    bot = build_bot(settings)
    files = FileManager(settings)
    registry = AccountRegistry(
        settings.resolved_accounts_file(), settings.resolved_session_dir()
    )
    scraper = TelethonScraper(settings, registry)

    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_routers(*routers)
    register_error_handler(dispatcher)

    dispatcher.callback_query.outer_middleware(SafeEditMiddleware())
    if settings.rate_limit_per_minute > 0:
        limiter = SlidingWindowLimiter(settings.rate_limit_per_minute, window=60.0)
        rate_middleware = RateLimitMiddleware(limiter)
        dispatcher.message.outer_middleware(rate_middleware)
        dispatcher.callback_query.outer_middleware(rate_middleware)
        logger.info("Rate limiting enabled: %d req/min", settings.rate_limit_per_minute)

    access_middleware = AccessMiddleware(settings)
    dispatcher.message.outer_middleware(access_middleware)
    dispatcher.callback_query.outer_middleware(access_middleware)
    logger.info(
        "Access control: %s%s",
        "required" if settings.access_required else "open",
        f" (admins: {settings.admin_ids})" if settings.admin_ids else "",
    )

    reaper = asyncio.create_task(retention_loop(files), name="retention-reaper")
    forwarder = asyncio.create_task(
        forward_loop(bot, files, settings), name="forward-sweep"
    )

    try:
        await configure_bot(bot)
        logger.info("Bot command menu configured")
    except Exception:  # noqa: BLE001 - never block startup on profile setup
        logger.exception("Could not configure bot commands (continuing)")

    await verify_custom_emoji(bot, settings)

    logger.info("Starting bot (environment=%s)", settings.environment)
    try:
        await dispatcher.start_polling(
            bot, settings=settings, file_manager=files, scraper=scraper
        )
    finally:
        reaper.cancel()
        forwarder.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reaper
        with contextlib.suppress(asyncio.CancelledError):
            await forwarder
        await dispose_engine()
        await bot.session.close()
        logger.info("Shutdown complete")


async def main() -> None:
    await run()


if __name__ == "__main__":
    asyncio.run(main())
