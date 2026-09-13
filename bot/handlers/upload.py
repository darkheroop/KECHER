"""Upload ingestion and the post-upload action menu."""

from __future__ import annotations

import asyncio

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, User as TgUser
from aiogram.fsm.context import FSMContext

from bot.config import Settings
from bot.db.engine import session_scope
from bot.db.enums import AuditAction, JobKind
from bot.db.models import UserFile
from bot.db.repositories import (
    add_queue_item,
    delete_file_row,
    get_user_settings,
    record_audit,
)
from bot.handlers import data_tools, validators
from bot.handlers.common import (
    ensure_user,
    get_owned_file,
    queue_snapshot,
    render_queue,
    start_job,
)
from bot.handlers.states import Flow
from bot.jobs.manager import JobManager
from bot.security.limits import human_size
from bot.services.csv_tool import inspect_csv, parse_column_selection
from bot.services.filetypes import ext_of, is_csv, is_doc
from bot.services.ingest import IngestError, ingest_document
from bot.services.file_manager import FileManager
from bot.ui.emoji import Emoji
from bot.ui.keyboards import (
    clean_options_keyboard,
    csv_columns_keyboard,
    dedup_mode_keyboard,
    split_mode_keyboard,
    upload_actions,
)

router = Router(name="upload")

DEFAULT_CLEAN_OPTIONS = {
    "remove_empty": True,
    "trim": True,
    "dedup": False,
    "luhn": False,
    "sort": False,
}


def _file_card(record: UserFile) -> str:
    return (
        f"{Emoji.CONVERT} <b>File received</b>\n\n"
        f"<b>Name:</b>\n{record.safe_name}\n\n"
        f"<b>Size:</b>\n{human_size(record.size_bytes)}\n\n"
        "What would you like to do?"
    )


async def _ingest(message: Message, file_manager: FileManager, settings: Settings) -> UserFile | None:
    document = message.document
    tg_user = message.from_user
    if document is None or tg_user is None:
        return None

    async def download(file_id: str, path) -> None:
        await message.bot.download(file_id, destination=path)

    try:
        async with session_scope() as session:
            user = await ensure_user(session, tg_user)
            user_settings = await get_user_settings(session, user.id)
            record = await ingest_document(
                session,
                file_manager,
                settings,
                user=user,
                file_id=document.file_id,
                file_name=document.file_name or "file",
                file_size=document.file_size,
                download=download,
                ttl_minutes=user_settings.cleanup_minutes,
            )
            await record_audit(
                session,
                user_id=user.id,
                action=AuditAction.FILE_RECEIVED,
                detail={"size": record.size_bytes, "ext": ext_of(record.safe_name)},
            )
            return record
    except IngestError as exc:
        await message.answer(f"{Emoji.ERROR} {exc}")
        return None


async def _add_to_queue(reply: Message, tg_user: TgUser, record: UserFile) -> None:
    async with session_scope() as session:
        user = await ensure_user(session, tg_user)
        await add_queue_item(session, user.id, record.id)
        records = await queue_snapshot(session, user.id)
    await reply.answer(
        f"{Emoji.INBOX} <b>File added</b>\n\n" + render_queue(records).split("\n", 1)[1]
    )


async def dispatch_action(
    action: str,
    record: UserFile,
    reply: Message,
    tg_user: TgUser,
    state: FSMContext,
    job_manager: JobManager,
    file_manager: FileManager,
) -> None:
    """Route an upload action to a job or to a parameter prompt."""
    if action == "doc2txt":
        if not is_doc(record.safe_name):
            await reply.answer(f"{Emoji.ERROR} Not a DOC/DOCX file.")
            return
        await start_job(
            reply,
            job_manager,
            tg_user=tg_user,
            kind=JobKind.DOC2TXT,
            input_file_id=record.id,
            label="Converting document",
        )
    elif action == "csv":
        await reply.answer("Choose output:", reply_markup=csv_columns_keyboard(record.id))
    elif action == "split":
        await reply.answer("Split by:", reply_markup=split_mode_keyboard(record.id))
    elif action == "clean":
        await state.update_data(clean_options=dict(DEFAULT_CLEAN_OPTIONS))
        await reply.answer(
            "Cleaning options:",
            reply_markup=clean_options_keyboard(record.id, DEFAULT_CLEAN_OPTIONS),
        )
    elif action == "dedup":
        await reply.answer("Deduplicate by:", reply_markup=dedup_mode_keyboard(record.id))
    elif action == "addfile":
        await _add_to_queue(reply, tg_user, record)
    elif action == "find":
        await data_tools.start_find(reply, record, tg_user, state)
    elif action == "country":
        await data_tools.start_group(reply, record, tg_user, state, file_manager, "country")
    elif action == "bank":
        await data_tools.start_group(reply, record, tg_user, state, file_manager, "bank")
    elif action == "live":
        await validators.start_validation(reply, record, tg_user, state)
    else:
        await reply.answer(f"{Emoji.ERROR} Unknown action.")


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #
@router.message(F.document)
async def on_document(
    message: Message,
    state: FSMContext,
    job_manager: JobManager,
    file_manager: FileManager,
    settings: Settings,
) -> None:
    data = await state.get_data()
    action = data.get("action")
    await state.clear()

    record = await _ingest(message, file_manager, settings)
    if record is None:
        return

    tg_user = message.from_user
    assert tg_user is not None

    if action:
        await dispatch_action(
            action, record, message, tg_user, state, job_manager, file_manager
        )
    else:
        await message.answer(
            _file_card(record),
            reply_markup=upload_actions(
                is_doc=is_doc(record.safe_name),
                is_csv=is_csv(record.safe_name),
                file_id=record.id,
            ),
        )


@router.callback_query(F.data.startswith("op:"))
async def on_operation(
    callback: CallbackQuery,
    state: FSMContext,
    job_manager: JobManager,
    file_manager: FileManager,
) -> None:
    parts = (callback.data or "").split(":", 2)
    if len(parts) != 3 or not parts[2].isdigit():
        await callback.answer("Invalid action", show_alert=True)
        return
    action, file_id = parts[1], int(parts[2])
    tg_user = callback.from_user

    async with session_scope() as session:
        user = await ensure_user(session, tg_user)
        record = await get_owned_file(session, user.id, file_id)
        telegram_id = user.telegram_id

    if record is None:
        await callback.answer("File not found or expired", show_alert=True)
        return

    if action == "cancel":
        file_manager.delete(telegram_id, record.rel_path)
        async with session_scope() as session:
            await delete_file_row(session, file_id)
        if callback.message is not None:
            await callback.message.edit_text(f"{Emoji.CANCEL} Cancelled.")
        await callback.answer()
        return

    if callback.message is None:
        await callback.answer()
        return
    await dispatch_action(
        action, record, callback.message, tg_user, state, job_manager, file_manager
    )
    await callback.answer()


@router.callback_query(F.data.startswith("split:mode:"))
async def on_split_mode(callback: CallbackQuery, state: FSMContext) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 4 or not parts[3].isdigit():
        await callback.answer("Invalid option", show_alert=True)
        return
    mode = parts[2]
    units = {"lines": "lines per file", "parts": "number of parts", "size": "bytes per file"}
    if mode not in units:
        await callback.answer("Invalid mode", show_alert=True)
        return
    await state.set_state(Flow.awaiting_text)
    await state.update_data(prompt="split_value", mode=mode, file_id=int(parts[3]))
    if callback.message is not None:
        await callback.message.edit_text(f"Send the {units[mode]}:")
    await callback.answer()


@router.callback_query(F.data.startswith("csv:"))
async def on_csv_choice(
    callback: CallbackQuery, state: FSMContext, job_manager: JobManager, file_manager: FileManager
) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        await callback.answer("Invalid option", show_alert=True)
        return
    choice, file_id = parts[1], int(parts[2])

    if choice == "all":
        assert callback.message is not None
        await start_job(
            callback.message,
            job_manager,
            tg_user=callback.from_user,
            kind=JobKind.CSV,
            input_file_id=file_id,
            label="Converting CSV",
        )
        await callback.answer()
        return

    async with session_scope() as session:
        user = await ensure_user(session, callback.from_user)
        record = await get_owned_file(session, user.id, file_id)
        telegram_id = user.telegram_id

    if record is None:
        await callback.answer("File not found or expired", show_alert=True)
        return

    path = file_manager.resolve(telegram_id, record.rel_path, create_parent=False)
    info = await asyncio.to_thread(inspect_csv, path)
    await state.set_state(Flow.awaiting_text)
    await state.update_data(prompt="csv_columns", file_id=file_id, columns_total=info.columns)
    if callback.message is not None:
        await callback.message.edit_text(
            f"Send column numbers (1-{info.columns}), e.g. 1,3,5"
        )
    await callback.answer()


@router.callback_query(F.data.startswith("dedup:"))
async def on_dedup_choice(callback: CallbackQuery, job_manager: JobManager) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        await callback.answer("Invalid option", show_alert=True)
        return
    normalize = parts[1] == "normalized"
    assert callback.message is not None
    await start_job(
        callback.message,
        job_manager,
        tg_user=callback.from_user,
        kind=JobKind.DEDUP,
        input_file_id=int(parts[2]),
        params={"normalize": normalize},
        label="Deduplicating",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("clean:"))
async def on_clean_choice(callback: CallbackQuery, state: FSMContext, job_manager: JobManager) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) < 3:
        await callback.answer("Invalid option", show_alert=True)
        return

    if parts[1] == "toggle" and len(parts) == 4 and parts[3].isdigit():
        key = parts[2]
        file_id = int(parts[3])
        data = await state.get_data()
        options = dict(data.get("clean_options") or DEFAULT_CLEAN_OPTIONS)
        if key in options:
            options[key] = not options[key]
        await state.update_data(clean_options=options)
        if callback.message is not None:
            await callback.message.edit_reply_markup(
                reply_markup=clean_options_keyboard(file_id, options)
            )
        await callback.answer()
        return

    if parts[1] == "run" and len(parts) == 3 and parts[2].isdigit():
        file_id = int(parts[2])
        data = await state.get_data()
        options = dict(data.get("clean_options") or DEFAULT_CLEAN_OPTIONS)
        await state.clear()
        params = {
            "options": {
                "remove_empty": bool(options.get("remove_empty")),
                "trim": bool(options.get("trim")),
                "dedup": bool(options.get("dedup")),
                "sort": bool(options.get("sort")),
                "luhn": bool(options.get("luhn")),
            }
        }
        assert callback.message is not None
        await start_job(
            callback.message,
            job_manager,
            tg_user=callback.from_user,
            kind=JobKind.CLEAN,
            input_file_id=file_id,
            params=params,
            label="Cleaning",
        )
        await callback.answer()
        return

    await callback.answer("Invalid option", show_alert=True)


@router.message(Flow.awaiting_text)
async def on_text_parameter(
    message: Message,
    state: FSMContext,
    job_manager: JobManager,
    file_manager: FileManager,
) -> None:
    data = await state.get_data()
    prompt = data.get("prompt")
    file_id = data.get("file_id")
    text = (message.text or "").strip()
    tg_user = message.from_user
    assert tg_user is not None

    if prompt == "split_value":
        if not text.isdigit() or int(text) < 1:
            await message.answer(f"{Emoji.ERROR} Send a positive whole number.")
            return
        mode = data.get("mode", "lines")
        await state.clear()
        await start_job(
            message,
            job_manager,
            tg_user=tg_user,
            kind=JobKind.SPLIT,
            input_file_id=int(file_id),
            params={"mode": mode, "value": int(text)},
            label=f"Splitting by {mode}",
        )
    elif prompt == "csv_columns":
        total = int(data.get("columns_total", 0))
        try:
            columns = parse_column_selection(text, total)
        except ValueError as exc:
            await message.answer(f"{Emoji.ERROR} {exc}")
            return
        await state.clear()
        await start_job(
            message,
            job_manager,
            tg_user=tg_user,
            kind=JobKind.CSV,
            input_file_id=int(file_id),
            params={"columns": columns},
            label="Converting CSV",
        )
    elif prompt == "find_query":
        if not text:
            await message.answer(f"{Emoji.ERROR} Send some text to search for.")
            return
        await state.clear()
        await start_job(
            message,
            job_manager,
            tg_user=tg_user,
            kind=JobKind.FIND,
            input_file_id=int(file_id),
            params={"query": text, "mode": "contains"},
            label="Searching",
        )
    elif prompt in {"country_field", "bank_field"}:
        if not text.isdigit() or int(text) < 1:
            await message.answer(f"{Emoji.ERROR} Send a valid column number.")
            return
        kind = prompt.split("_", 1)[0]
        await state.clear()
        await data_tools.finish_group_for_file(
            message,
            file_id=int(file_id),
            field_index=int(text) - 1,
            kind=kind,
            tg_user=tg_user,
            state=state,
            file_manager=file_manager,
        )
    else:
        await state.clear()
        await message.answer(f"{Emoji.ERROR} Nothing to do.")
