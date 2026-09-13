"""Retention: delete expired temporary files from disk and database."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select

from bot.db.engine import session_scope
from bot.db.models import User, UserFile
from bot.db.repositories import list_expired_files
from bot.services.file_manager import FileManager

logger = logging.getLogger(__name__)


async def reap_expired_files(
    files: FileManager, *, now: datetime | None = None
) -> int:
    """Delete every file whose ``expires_at`` has passed. Returns the count."""
    removed = 0
    async with session_scope() as session:
        expired = await list_expired_files(session, now)
        for record in expired:
            user = await session.get(User, record.user_id)
            if user is not None:
                files.delete(user.telegram_id, record.rel_path)
            await session.delete(record)
            removed += 1
    if removed:
        logger.info("Reaped %d expired file(s)", removed)
    return removed


async def reap_user_files(files: FileManager, telegram_id: int) -> int:
    """Delete all files owned by a single user (used for manual cleanup)."""
    removed = 0
    async with session_scope() as session:
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if user is None:
            return 0
        records = (await session.scalars(
            select(UserFile).where(UserFile.user_id == user.id)
        )).all()
        for record in records:
            files.delete(telegram_id, record.rel_path)
            await session.delete(record)
            removed += 1
    if removed:
        logger.info("Manually cleaned %d file(s) for user %s", removed, telegram_id)
    return removed


def now_utc() -> datetime:
    return datetime.now(UTC)
