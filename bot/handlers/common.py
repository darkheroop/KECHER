"""Shared helpers for Telegram handlers."""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, Message, User as TgUser
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.db.engine import session_scope
from bot.db.models import User, UserFile
from bot.db.repositories import (
    create_job,
    get_or_create_user,
    get_user_files_by_ids,
    list_admins,
    list_queue_items,
)
from bot.jobs.manager import JobManager
from bot.ui.emoji import Emoji

logger = logging.getLogger(__name__)


async def ensure_user(session: AsyncSession, tg_user: TgUser) -> User:
    user, _ = await get_or_create_user(
        session,
        tg_user.id,
        username=tg_user.username,
        first_name=tg_user.first_name,
    )
    return user


async def get_owned_file(
    session: AsyncSession, user_id: int, file_id: int
) -> UserFile | None:
    record = await session.get(UserFile, file_id)
    if record is None or record.user_id != user_id:
        return None
    return record


async def start_job(
    reply_to: Message,
    job_manager: JobManager,
    *,
    tg_user: TgUser,
    kind: str,
    input_file_id: int | None,
    params: dict | None = None,
    label: str,
) -> int:
    """Acknowledge, persist and schedule a job. Returns the job id."""
    async with session_scope() as session:
        user = await ensure_user(session, tg_user)
        user_id = user.id

    ack = await reply_to.answer(f"{Emoji.PROGRESS} {label}\u2026")

    async with session_scope() as session:
        job = await create_job(
            session,
            user_id=user_id,
            kind=str(kind),
            input_file_id=input_file_id,
            params=params,
            chat_id=ack.chat.id,
            progress_message_id=ack.message_id,
        )
        job_id = job.id

    await job_manager.submit(job_id)
    return job_id


async def queue_snapshot(session: AsyncSession, user_id: int) -> list[UserFile]:
    """Return the user's queued files in order."""
    items = await list_queue_items(session, user_id)
    return await get_user_files_by_ids(
        session, user_id, [item.file_id for item in items]
    )


def render_queue(records: list[UserFile]) -> str:
    if not records:
        return f"{Emoji.QUEUE} <b>Merge queue</b>\n\nQueue is empty."
    lines = [f"{Emoji.QUEUE} <b>Merge queue</b>", ""]
    for index, record in enumerate(records, start=1):
        lines.append(f"{index}. {record.safe_name}")
    lines.extend(["", f"Total files: {len(records)}", "", "Use /merge when ready."])
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Collection channel + admin notifications
# --------------------------------------------------------------------------- #
async def forward_to_channel(
    bot: Bot, settings: Settings, chat_id: int, message_id: int
) -> None:
    """Forward a message to the configured collection channel (if any)."""
    channel = (settings.forward_channel_id or "").strip()
    if not channel:
        return
    try:
        await bot.forward_message(
            chat_id=channel, from_chat_id=chat_id, message_id=message_id
        )
    except Exception:  # noqa: BLE001 - forwarding must never break the flow
        logger.exception("Failed to forward message to channel %s", channel)


async def admin_telegram_ids(session: AsyncSession, settings: Settings) -> set[int]:
    ids = set(settings.admin_ids)
    for admin in await list_admins(session):
        ids.add(admin.telegram_id)
    return ids


async def notify_admins(
    bot: Bot,
    settings: Settings,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    async with session_scope() as session:
        ids = await admin_telegram_ids(session, settings)
    for admin_id in ids:
        try:
            await bot.send_message(admin_id, text, reply_markup=reply_markup)
        except Exception:  # noqa: BLE001 - one bad admin must not stop the rest
            logger.exception("Failed to notify admin %s", admin_id)
