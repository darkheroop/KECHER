"""Offline readiness check for local setup.

Performs NO Telegram network calls and needs no valid token. Verifies config,
storage, database schema, router loading, and job-handler registration.

Usage:
    python -m bot.tools.selfcheck
"""

from __future__ import annotations

import asyncio

from sqlalchemy import func, select

from bot.config import get_settings
from bot.db.engine import dispose_engine, init_db, session_scope
from bot.db.models import User

PLACEHOLDER = "PASTE_YOUR_TOKEN_HERE"


async def main() -> int:
    print("Telegram File Bot - self check")
    print("-" * 34)

    settings = get_settings()
    print(f"[config]  environment : {settings.environment}")
    print(f"[config]  database    : {settings.database_url}")

    token = settings.bot_token.get_secret_value()
    token_ready = bool(token) and token != PLACEHOLDER and ":" in token
    print(f"[config]  bot token   : {'set' if token_ready else 'MISSING'}")

    root = settings.resolved_storage_root()
    root.mkdir(parents=True, exist_ok=True)
    print(f"[storage] {root}")

    try:
        await init_db(settings)
        async with session_scope() as session:
            users = await session.scalar(select(func.count()).select_from(User))
        print(f"[db]      ok ({users} user rows)")
    except Exception as exc:  # noqa: BLE001
        print(f"[db]      FAILED: {exc}")
        return 1

    try:
        from aiogram import Dispatcher
        from aiogram.fsm.storage.memory import MemoryStorage

        from bot.handlers import routers

        dispatcher = Dispatcher(storage=MemoryStorage())
        dispatcher.include_routers(*routers)
        print(f"[handlers] {len(routers)} routers loaded")
    except Exception as exc:  # noqa: BLE001
        print(f"[handlers] FAILED: {exc}")
        return 1

    try:
        from bot.jobs.handlers import register_handlers
        from bot.jobs.manager import JobManager
        from bot.services.file_manager import FileManager

        manager = JobManager(files=FileManager(settings), concurrency=1)
        register_handlers(manager, settings)
        print(f"[jobs]    handlers: {', '.join(manager.registered_kinds())}")
    except Exception as exc:  # noqa: BLE001
        print(f"[jobs]    FAILED: {exc}")
        return 1

    await dispose_engine()

    print("-" * 34)
    if token_ready:
        print("RESULT: READY - start the bot with  .\\run.ps1  (or run.bat)")
        return 0
    print("RESULT: NEEDS BOT_TOKEN")
    print("Add your @BotFather token to the BOT_TOKEN line in .env, then run run.bat.")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
