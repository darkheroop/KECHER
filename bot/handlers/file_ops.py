"""File-feature commands and their callbacks.

Commands without an attached file put the user into
:class:`~bot.handlers.states.Flow.awaiting_file`; the upload handler then
continues the flow once a document arrives.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.db.engine import session_scope
from bot.db.enums import AuditAction, JobKind
from bot.db.repositories import clear_queue, delete_file_row, record_audit
from bot.handlers.common import ensure_user, queue_snapshot, render_queue, start_job
from bot.handlers.states import Flow
from bot.jobs.manager import JobManager
from bot.services.file_manager import FileManager
from bot.ui.emoji import Emoji
from bot.ui.keyboards import clear_queue_confirm, merge_options_keyboard

router = Router(name="file_ops")

_PROMPTS = {
    "doc2txt": "Send a <b>.doc</b> or <b>.docx</b> file to convert.",
    "csv": "Send a <b>.csv</b> or <b>.tsv</b> file.",
    "split": "Send a <b>txt</b>/<b>csv</b> file to split.",
    "clean": "Send the dataset file to clean.",
    "dedup": "Send the file to deduplicate.",
    "addfile": "Send the file to add to the merge queue.",
    "find": "Send the dataset file to search.",
    "country": "Send the dataset file to group by country.",
    "bank": "Send the dataset file to group by bank.",
    "live": "Send the test dataset to validate (e.g. <code>pan|expiry</code> or CSV).",
}


async def prompt_for_file(message: Message, state: FSMContext, action: str) -> None:
    await state.set_state(Flow.awaiting_file)
    await state.update_data(action=action)
    await message.answer(f"{Emoji.FILE} {_PROMPTS.get(action, 'Send a file.')}")


@router.message(Command("doc2txt"))
async def cmd_doc2txt(message: Message, state: FSMContext) -> None:
    await prompt_for_file(message, state, "doc2txt")


@router.message(Command("csv"))
async def cmd_csv(message: Message, state: FSMContext) -> None:
    await prompt_for_file(message, state, "csv")


@router.message(Command("split"))
async def cmd_split(message: Message, state: FSMContext) -> None:
    await prompt_for_file(message, state, "split")


@router.message(Command("clean"))
async def cmd_clean(message: Message, state: FSMContext) -> None:
    await prompt_for_file(message, state, "clean")


@router.message(Command("dedup"))
async def cmd_dedup(message: Message, state: FSMContext) -> None:
    await prompt_for_file(message, state, "dedup")


@router.message(Command("addfile"))
async def cmd_addfile(message: Message, state: FSMContext) -> None:
    await prompt_for_file(message, state, "addfile")


@router.message(Command("merge"))
async def cmd_merge(message: Message) -> None:
    tg_user = message.from_user
    assert tg_user is not None
    async with session_scope() as session:
        user = await ensure_user(session, tg_user)
        records = await queue_snapshot(session, user.id)

    if not records:
        await message.answer(f"{Emoji.QUEUE} Merge queue is empty. Add files with /addfile.")
        return

    await message.answer(
        render_queue(records) + "\n\nChoose an option:",
        reply_markup=merge_options_keyboard(),
    )


@router.callback_query(F.data.startswith("merge:run:"))
async def on_merge_run(callback: CallbackQuery, job_manager: JobManager) -> None:
    option = (callback.data or "").rsplit(":", 1)[-1]
    if option not in {"plain", "dedup", "sort"}:
        await callback.answer("Invalid option", show_alert=True)
        return

    assert callback.message is not None
    await start_job(
        callback.message,
        job_manager,
        tg_user=callback.from_user,
        kind=JobKind.MERGE,
        input_file_id=None,
        params={"dedup": option == "dedup", "sort": option == "sort"},
        label="Merging files",
    )
    await callback.answer()


@router.message(Command("clearqueue"))
async def cmd_clearqueue(message: Message) -> None:
    tg_user = message.from_user
    assert tg_user is not None
    async with session_scope() as session:
        user = await ensure_user(session, tg_user)
        records = await queue_snapshot(session, user.id)

    if not records:
        await message.answer(f"{Emoji.QUEUE} Merge queue is already empty.")
        return

    await message.answer(
        f"{Emoji.WARNING} <b>Clear merge queue?</b>\n\n"
        f"{len(records)} file(s) will be removed.",
        reply_markup=clear_queue_confirm(),
    )


@router.callback_query(F.data == "queue:clear:yes")
async def on_clear_queue(callback: CallbackQuery, file_manager: FileManager) -> None:
    async with session_scope() as session:
        user = await ensure_user(session, callback.from_user)
        records = await queue_snapshot(session, user.id)
        telegram_id = user.telegram_id
        for record in records:
            await delete_file_row(session, record.id)
        await clear_queue(session, user.id)
        await record_audit(
            session,
            user_id=user.id,
            action=AuditAction.FILE_DELETED,
            detail={"count": len(records)},
        )

    for record in records:
        file_manager.delete(telegram_id, record.rel_path)

    if callback.message is not None:
        await callback.message.edit_text(
            f"{Emoji.SUCCESS} Merge queue cleared ({len(records)} file(s))."
        )
    await callback.answer("Cleared")
