"""Periodic forwarding of collected files to the channel.

Files are sent as documents (so they survive even when the original Telegram
message is gone). A high-water mark in ``bot_settings`` ensures each file is
forwarded at most once.
"""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import FSInputFile

from bot.config import Settings
from bot.db.engine import session_scope
from bot.db.models import User
from bot.db.repositories import (
    get_bot_setting,
    list_files_after,
    set_bot_setting,
)
from bot.services.file_manager import FileManager

logger = logging.getLogger(__name__)

LAST_KEY = "last_forwarded_file_id"
BATCH = 50


async def forward_pending_files(
    bot: Bot, files: FileManager, settings: Settings, *, limit: int = BATCH
) -> int:
    """Send not-yet-forwarded files to the channel. Returns how many were sent."""
    channel = (settings.forward_channel_id or "").strip()
    if not channel:
        return 0

    async with session_scope() as session:
        last_raw = await get_bot_setting(session, LAST_KEY, "0") or "0"
        pending = await list_files_after(session, int(last_raw), limit=limit)
        if not pending:
            return 0
        users = {
            record.user_id: (await session.get(User, record.user_id))
            for record in pending
        }

    sent = 0
    highest = int(last_raw)
    for record in pending:
        highest = max(highest, record.id)
        user = users.get(record.user_id)
        if user is None:
            continue
        try:
            path = files.resolve(user.telegram_id, record.rel_path, create_parent=False)
        except (ValueError, OSError):
            continue
        if not path.is_file():
            continue
        try:
            await bot.send_document(
                channel, FSInputFile(path, filename=record.safe_name)
            )
            sent += 1
        except Exception:  # noqa: BLE001 - keep going on a single failure
            logger.exception("Failed to forward file %s to %s", record.id, channel)

    async with session_scope() as session:
        await set_bot_setting(session, LAST_KEY, str(highest))
    if sent:
        logger.info("Forwarded %d file(s) to %s", sent, channel)
    return sent
