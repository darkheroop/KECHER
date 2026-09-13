"""``/jobs`` and ``/cancel`` — inspect and cancel background jobs."""

from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.db.engine import session_scope
from bot.db.enums import JobStatus
from bot.db.models import Job
from bot.db.repositories import get_or_create_user, list_active_jobs, list_jobs
from bot.jobs.manager import JobManager
from bot.ui.emoji import Emoji
from bot.ui.keyboards import back_to_menu

router = Router(name="jobs")

_STATUS_ICONS = {
    JobStatus.QUEUED.value: "⏳",
    JobStatus.PROCESSING.value: f"{Emoji.PROGRESS}",
    JobStatus.COMPLETED.value: f"{Emoji.SUCCESS}",
    JobStatus.FAILED.value: f"{Emoji.ERROR}",
    JobStatus.CANCELLED.value: f"{Emoji.CANCEL}",
}


def _icon(status: str) -> str:
    return _STATUS_ICONS.get(status, "•")


def render_jobs(jobs: list[Job]) -> str:
    if not jobs:
        return f"{Emoji.JOBS} <b>Jobs</b>\n\nNo jobs yet."
    lines = [f"{Emoji.JOBS} <b>Recent jobs</b>", ""]
    for job in jobs:
        pct = f" — {job.progress}%" if job.status == JobStatus.PROCESSING.value else ""
        lines.append(f"{_icon(job.status)} <code>#{job.id}</code> {html.escape(job.kind)}{pct}")
        if job.error:
            lines.append(f"    <i>{html.escape(job.error[:140])}</i>")
    return "\n".join(lines)


def _cancel_keyboard(jobs: list[Job]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{Emoji.CANCEL} #{job.id} {job.kind}",
                callback_data=f"job:cancel:{job.id}",
            )
        ]
        for job in jobs
    ]
    rows.append([InlineKeyboardButton(text=f"{Emoji.SUCCESS} Back", callback_data="menu:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _fetch(user_id: int, *, limit: int | None) -> list[Job]:
    async with session_scope() as session:
        if limit is None:
            return await list_active_jobs(session, user_id)
        return await list_jobs(session, user_id, limit=limit)


async def _user_id(callback_or_message) -> int:  # noqa: ANN001
    async with session_scope() as session:
        tg_user = callback_or_message.from_user
        user, _ = await get_or_create_user(
            session, tg_user.id, username=tg_user.username, first_name=tg_user.first_name
        )
        return user.id


@router.message(Command("jobs"))
async def cmd_jobs(message: Message) -> None:
    user_id = await _user_id(message)
    jobs = await _fetch(user_id, limit=10)
    await message.answer(render_jobs(jobs), reply_markup=back_to_menu())


@router.callback_query(F.data == "jobs:open")
async def open_jobs(callback: CallbackQuery) -> None:
    user_id = await _user_id(callback)
    jobs = await _fetch(user_id, limit=10)
    if callback.message is not None:
        await callback.message.edit_text(render_jobs(jobs), reply_markup=back_to_menu())
    await callback.answer()


@router.callback_query(F.data == "jobs:refresh")
async def refresh_jobs(callback: CallbackQuery) -> None:
    user_id = await _user_id(callback)
    jobs = await _fetch(user_id, limit=10)
    if callback.message is not None:
        await callback.message.edit_text(render_jobs(jobs), reply_markup=back_to_menu())
    await callback.answer("Refreshed")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message) -> None:
    user_id = await _user_id(message)
    active = await _fetch(user_id, limit=None)
    if not active:
        await message.answer(f"{Emoji.INFO} No active jobs to cancel.")
        return
    await message.answer(
        f"{Emoji.CANCEL} <b>Active jobs</b>\n\nSelect a job to cancel:",
        reply_markup=_cancel_keyboard(active),
    )


@router.callback_query(F.data.startswith("job:cancel:"))
async def cancel_job(callback: CallbackQuery, job_manager: JobManager) -> None:
    raw = (callback.data or "").rsplit(":", 1)[-1]
    if not raw.isdigit():
        await callback.answer("Invalid job", show_alert=True)
        return

    cancelled = await job_manager.cancel(int(raw))
    if cancelled:
        await callback.answer("Cancellation requested")
    else:
        await callback.answer("Job is no longer active", show_alert=True)

    user_id = await _user_id(callback)
    active = await _fetch(user_id, limit=None)
    text = (
        f"{Emoji.CANCEL} <b>Active jobs</b>\n\nSelect a job to cancel:"
        if active
        else f"{Emoji.SUCCESS} No active jobs."
    )
    if callback.message is not None:
        await callback.message.edit_text(
            text, reply_markup=_cancel_keyboard(active) if active else back_to_menu()
        )
