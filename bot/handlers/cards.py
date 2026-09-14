"""Card commands: /clean, /live, /country, /split, /dedup, /addfile, /merge.

Workflow: reply to a ``.txt`` file with the command. Uploading a ``.txt`` also
offers the same actions as buttons.
"""

from __future__ import annotations

import asyncio
import html
from datetime import UTC, datetime, timedelta
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, FSInputFile, Message

from bot.config import Settings
from bot.db.engine import session_scope
from bot.db.enums import JobKind
from bot.db.models import UserFile
from bot.db.repositories import (
    add_queue_item,
    clear_queue,
    create_file,
    delete_file_row,
    get_user_files_by_ids,
    get_user_settings,
)
from bot.handlers.common import ensure_user, get_owned_file, queue_snapshot, render_queue
from bot.services.cards import (
    clean_cards,
    country_cards,
    dedup_cards,
    live_cards,
    merge_files,
    split_cards,
)
from bot.services.file_manager import FileManager
from bot.services.filetypes import TEXT_EXTS, ext_of
from bot.services.ingest import IngestError, ingest_document
from bot.ui.emoji import Emoji
from bot.ui.keyboards import card_actions, clear_queue_confirm, split_choices
from bot.ui.render import safe_edit

router = Router(name="cards")

HELP_BY_COMMAND = {
    "clean": "🧹 Receive the valid card records only.",
    "live": "🕵️ Receive only the serial numbers that pass the Luhn check.",
    "country": "🌐 Receive the card lines that sit directly above your keyword.",
    "split": "✂️ Split the file into N equal parts.",
    "dedup": "♻️ Remove exact duplicate lines.",
    "addfile": "📄 Add the file to the merge queue.",
}

REPLY_PROMPT = {
    "clean": "🧹 Reply to a .txt file with /clean to extract valid cards.",
    "live": "🕵️ Reply to a .txt file with /live to keep Luhn-valid serials.",
    "country": "🌐 Reply to a .txt file with /country &lt;keyword&gt; to extract the lines above that keyword.",
    "split": "✂️ Reply to a .txt file with /split N to split it into N equal parts.",
    "dedup": "♻️ Reply to a .txt file with /dedup to remove duplicate lines.",
    "addfile": "📄 Reply to a .txt file with /addfile to add it to the merge queue.",
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _is_txt(name: str | None) -> bool:
    return bool(name) and ext_of(name) in TEXT_EXTS


async def _ingest_reply(
    message: Message, file_manager: FileManager, settings: Settings
) -> UserFile | None:
    reply = message.reply_to_message
    if reply is None or reply.document is None:
        return None
    document = reply.document
    if not _is_txt(document.file_name):
        await message.answer(f"{Emoji.ERROR} Please reply to a <b>.txt</b> file.")
        return None

    async def download(file_id: str, path: Path) -> None:
        await message.bot.download(file_id, destination=path)

    try:
        async with session_scope() as session:
            user = await ensure_user(session, message.from_user)
            user_settings = await get_user_settings(session, user.id)
            return await ingest_document(
                session,
                file_manager,
                settings,
                user=user,
                file_id=document.file_id,
                file_name=document.file_name or "cards.txt",
                file_size=document.file_size,
                download=download,
                ttl_minutes=user_settings.cleanup_minutes,
            )
    except IngestError as exc:
        await message.answer(f"{Emoji.ERROR} {exc}")
        return None


async def _register_output(
    record: UserFile, files: FileManager, stored, ttl_minutes: int
) -> None:
    async with session_scope() as session:
        await create_file(
            session,
            user_id=record.user_id,
            original_name=stored.safe_name,
            safe_name=stored.safe_name,
            rel_path=stored.rel_path,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
            expires_at=datetime.now(UTC) + timedelta(minutes=max(1, ttl_minutes)),
        )


def _resolve(record: UserFile, files: FileManager, telegram_id: int) -> Path:
    return files.resolve(telegram_id, record.rel_path, create_parent=False)


async def _send_file(message: Message, path: Path, filename: str, caption: str) -> None:
    await message.answer_document(FSInputFile(path, filename=filename), caption=caption)


async def _prompt_reply(message: Message, key: str) -> None:
    await message.answer(REPLY_PROMPT[key])


# --------------------------------------------------------------------------- #
# Simple commands
# --------------------------------------------------------------------------- #
@router.message(Command("clean"))
async def cmd_clean(message: Message, file_manager: FileManager, settings: Settings) -> None:
    record = await _ingest_reply(message, file_manager, settings)
    if record is None:
        await _prompt_reply(message, "clean")
        return
    await _run_clean(message, file_manager, settings, record)


@router.message(Command("live"))
async def cmd_live(message: Message, file_manager: FileManager, settings: Settings) -> None:
    record = await _ingest_reply(message, file_manager, settings)
    if record is None:
        await _prompt_reply(message, "live")
        return
    await _run_live(message, file_manager, settings, record)


@router.message(Command("dedup"))
async def cmd_dedup(message: Message, file_manager: FileManager, settings: Settings) -> None:
    record = await _ingest_reply(message, file_manager, settings)
    if record is None:
        await _prompt_reply(message, "dedup")
        return
    await _run_dedup(message, file_manager, settings, record)


@router.message(Command("addfile"))
async def cmd_addfile(message: Message, file_manager: FileManager, settings: Settings) -> None:
    record = await _ingest_reply(message, file_manager, settings)
    if record is None:
        await _prompt_reply(message, "addfile")
        return
    await _run_addfile(message, record)


async def _run_clean(
    message: Message, files: FileManager, settings: Settings, record: UserFile
) -> None:
    telegram_id = message.from_user.id
    src = _resolve(record, files, telegram_id)
    out = files.allocate(telegram_id, f"{Path(record.safe_name).stem}_clean.txt", subdir="out")
    status = await message.answer(f"{Emoji.CLEAN} Cleaning…")
    report = await asyncio.to_thread(clean_cards, src, out.path)
    stored = files.finalize(out)
    async with session_scope() as session:
        user_settings = await get_user_settings(session, record.user_id)
    await _register_output(record, files, stored, user_settings.cleanup_minutes)
    await safe_edit(
        status,
        f"{Emoji.SUCCESS} <b>Clean complete</b>\n\n"
        f"Total lines: {report.total:,}\n"
        f"Valid cards: {report.valid:,}\n"
        f"Removed: {report.invalid:,}",
    )
    await _send_file(message, stored.path, stored.safe_name, f"🧹 {report.valid:,} valid card(s)")


async def _run_live(
    message: Message, files: FileManager, settings: Settings, record: UserFile
) -> None:
    telegram_id = message.from_user.id
    src = _resolve(record, files, telegram_id)
    out = files.allocate(telegram_id, f"{Path(record.safe_name).stem}_live.txt", subdir="out")
    status = await message.answer(f"{Emoji.LIVE_CHECK} Checking cards…")
    report = await asyncio.to_thread(live_cards, src, out.path)
    stored = files.finalize(out)
    async with session_scope() as session:
        user_settings = await get_user_settings(session, record.user_id)
    await _register_output(record, files, stored, user_settings.cleanup_minutes)
    await safe_edit(
        status,
        f"{Emoji.SUCCESS} <b>Live check complete</b>\n\n"
        f"Checked: {report.checked:,}\n"
        f"Valid (Luhn): {report.valid:,}\n"
        f"Invalid: {report.invalid:,}",
    )
    await _send_file(message, stored.path, stored.safe_name, f"🕵️ {report.valid:,} valid card(s)")


async def _run_dedup(
    message: Message, files: FileManager, settings: Settings, record: UserFile
) -> None:
    telegram_id = message.from_user.id
    src = _resolve(record, files, telegram_id)
    out = files.allocate(telegram_id, f"{Path(record.safe_name).stem}_dedup.txt", subdir="out")
    status = await message.answer(f"{Emoji.RECYCLE} Deduplicating…")
    report = await asyncio.to_thread(dedup_cards, src, out.path)
    stored = files.finalize(out)
    async with session_scope() as session:
        user_settings = await get_user_settings(session, record.user_id)
    await _register_output(record, files, stored, user_settings.cleanup_minutes)
    await safe_edit(
        status,
        f"{Emoji.SUCCESS} <b>Dedup complete</b>\n\n"
        f"Lines: {report.total:,}\n"
        f"Unique: {report.unique:,}\n"
        f"Removed: {report.removed:,}",
    )
    await _send_file(message, stored.path, stored.safe_name, f"♻️ {report.unique:,} unique line(s)")


async def _run_addfile(message: Message, record: UserFile) -> None:
    async with session_scope() as session:
        user = await ensure_user(session, message.from_user)
        await add_queue_item(session, user.id, record.id)
        records = await queue_snapshot(session, user.id)
    await message.answer(
        f"{Emoji.PAGE} <b>File added to the merge queue</b>\n\n{render_queue(records)}"
    )


# --------------------------------------------------------------------------- #
# /country <keyword>
# --------------------------------------------------------------------------- #
@router.message(Command("country"))
async def cmd_country(message: Message, file_manager: FileManager, settings: Settings) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(
            f"{Emoji.COUNTRY} <b>Country</b>\n\n"
            "Define a custom keyword:\n"
            "<code>/country &lt;keyword&gt;</code>\n\n"
            "I will return every card line that sits directly above that keyword."
        )
        return
    keyword = parts[1].strip()
    record = await _ingest_reply(message, file_manager, settings)
    if record is None:
        await _prompt_reply(message, "country")
        return

    telegram_id = message.from_user.id
    src = _resolve(record, file_manager, telegram_id)
    safe = "".join(ch if ch.isalnum() else "_" for ch in keyword)[:40] or "keyword"
    out = file_manager.allocate(
        telegram_id, f"{Path(record.safe_name).stem}_{safe}.txt", subdir="out"
    )
    status = await message.answer(f"{Emoji.COUNTRY} Filtering “{html.escape(keyword)}”…")
    report = await asyncio.to_thread(country_cards, src, out.path, keyword)
    stored = file_manager.finalize(out)
    async with session_scope() as session:
        user_settings = await get_user_settings(session, record.user_id)
    await _register_output(record, file_manager, stored, user_settings.cleanup_minutes)
    await safe_edit(
        status,
        f"{Emoji.SUCCESS} <b>Country filter complete</b>\n\n"
        f"Keyword: <b>{html.escape(keyword)}</b>\n"
        f"Matches: {report.matches:,}\n"
        f"Card lines: {report.lines:,}",
    )
    await _send_file(
        message, stored.path, stored.safe_name, f"🌐 {report.lines:,} line(s) above “{keyword}”"
    )


# --------------------------------------------------------------------------- #
# /split N
# --------------------------------------------------------------------------- #
@router.message(Command("split"))
async def cmd_split(message: Message, file_manager: FileManager, settings: Settings) -> None:
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit() or int(parts[1]) < 1:
        record = await _ingest_reply(message, file_manager, settings) if message.reply_to_message else None
        if record is not None:
            await message.answer("Choose how many parts:", reply_markup=split_choices(record.id))
            return
        await message.answer(
            f"{Emoji.SPLIT} <b>Split</b>\n\n"
            "Reply to a .txt and send:\n<code>/split N</code> (e.g. <code>/split 5</code>)"
        )
        return

    count = int(parts[1])
    record = await _ingest_reply(message, file_manager, settings)
    if record is None:
        await _prompt_reply(message, "split")
        return
    await _run_split(message, file_manager, settings, record, count)


async def _run_split(
    message: Message, files: FileManager, settings: Settings, record: UserFile, count: int
) -> None:
    telegram_id = message.from_user.id
    src = _resolve(record, files, telegram_id)
    out_dir = files.user_root(telegram_id) / "out" / f"{Path(record.safe_name).stem}_parts"
    status = await message.answer(f"{Emoji.SPLIT} Splitting into {count} parts…")
    report = await asyncio.to_thread(split_cards, src, out_dir, count)
    await safe_edit(
        status,
        f"{Emoji.SUCCESS} <b>Split complete</b>\n\n"
        f"Parts: {len(report.parts):,}\n"
        f"Total lines: {report.lines:,}",
    )
    for part in report.parts:
        await message.answer_document(FSInputFile(part, filename=part.name))


# --------------------------------------------------------------------------- #
# /merge and queue
# --------------------------------------------------------------------------- #
@router.message(Command("merge"))
async def cmd_merge(message: Message, file_manager: FileManager, settings: Settings) -> None:
    await _run_merge(message, file_manager)


async def _run_merge(message: Message, files: FileManager) -> None:
    telegram_id = message.from_user.id
    async with session_scope() as session:
        user = await ensure_user(session, message.from_user)
        records = await queue_snapshot(session, user.id)
        user_settings = await get_user_settings(session, user.id)

    if not records:
        await message.answer(f"{Emoji.STAR} Merge queue is empty. Add files with /addfile.")
        return

    paths = [files.resolve(telegram_id, r.rel_path, create_parent=False) for r in records]
    out = files.allocate(telegram_id, "merged.txt", subdir="out")
    status = await message.answer(f"{Emoji.STAR} Merging {len(records)} file(s)…")
    report = await asyncio.to_thread(merge_files, paths, out.path)
    stored = files.finalize(out)

    async with session_scope() as session:
        for record in records:
            await delete_file_row(session, record.id)
        await clear_queue(session, user.id)

    await _register_output(records[0], files, stored, user_settings.cleanup_minutes)
    await safe_edit(
        status,
        f"{Emoji.SUCCESS} <b>Merge complete</b>\n\n"
        f"Files: {report.files:,}\n"
        f"Lines: {report.lines:,}",
    )
    await _send_file(message, stored.path, stored.safe_name, f"⭐ Merged {report.files} file(s)")


@router.message(Command("clearqueue"))
async def cmd_clearqueue(message: Message, file_manager: FileManager, settings: Settings) -> None:
    async with session_scope() as session:
        user = await ensure_user(session, message.from_user)
        records = await queue_snapshot(session, user.id)
    if not records:
        await message.answer(f"{Emoji.STAR} Merge queue is already empty.")
        return
    await message.answer(
        f"{Emoji.WARNING} Clear the merge queue?\n\n{len(records)} file(s) will be removed.",
        reply_markup=clear_queue_confirm(len(records)),
    )


@router.callback_query(F.data == "queue:clear:yes")
async def on_clear_queue(callback: CallbackQuery, file_manager: FileManager) -> None:
    telegram_id = callback.from_user.id
    async with session_scope() as session:
        user = await ensure_user(session, callback.from_user)
        records = await queue_snapshot(session, user.id)
        for record in records:
            await delete_file_row(session, record.id)
        await clear_queue(session, user.id)
    for record in records:
        file_manager.delete(telegram_id, record.rel_path)
    await safe_edit(callback.message, f"{Emoji.SUCCESS} Merge queue cleared.")
    await callback.answer("Cleared")


# --------------------------------------------------------------------------- #
# Upload a .txt  ->  action buttons
# --------------------------------------------------------------------------- #
@router.message(F.document)
async def on_document(message: Message, file_manager: FileManager, settings: Settings) -> None:
    document = message.document
    if not _is_txt(document.file_name):
        await message.answer(f"{Emoji.ERROR} Please send a <b>.txt</b> file.")
        return

    async def download(file_id: str, path: Path) -> None:
        await message.bot.download(file_id, destination=path)

    try:
        async with session_scope() as session:
            user = await ensure_user(session, message.from_user)
            user_settings = await get_user_settings(session, user.id)
            record = await ingest_document(
                session,
                file_manager,
                settings,
                user=user,
                file_id=document.file_id,
                file_name=document.file_name or "cards.txt",
                file_size=document.file_size,
                download=download,
                ttl_minutes=user_settings.cleanup_minutes,
            )
    except IngestError as exc:
        await message.answer(f"{Emoji.ERROR} {exc}")
        return

    await message.answer(
        f"{Emoji.CARD} <b>File received</b>\n\n"
        f"Name: <code>{html.escape(record.safe_name)}</code>\n"
        f"Size: {record.size_bytes:,} bytes\n\n"
        "What would you like to do?",
        reply_markup=card_actions(record.id),
    )


# --------------------------------------------------------------------------- #
# Card action callbacks
# --------------------------------------------------------------------------- #
async def _load_record(callback: CallbackQuery, file_id: int) -> UserFile | None:
    async with session_scope() as session:
        user = await ensure_user(session, callback.from_user)
        return await get_owned_file(session, user.id, file_id)


@router.callback_query(F.data.startswith("card:"))
async def on_card_action(
    callback: CallbackQuery, file_manager: FileManager, settings: Settings
) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) < 3:
        await callback.answer("Invalid action", show_alert=True)
        return

    action = parts[1]
    count: int | None = None
    if action == "splitn":
        if len(parts) != 4 or not parts[2].isdigit() or not parts[3].isdigit():
            await callback.answer("Invalid action", show_alert=True)
            return
        count, file_id = int(parts[2]), int(parts[3])
    else:
        if not parts[2].isdigit():
            await callback.answer("Invalid action", show_alert=True)
            return
        file_id = int(parts[2])

    telegram_id = callback.from_user.id
    record = await _load_record(callback, file_id)
    if record is None:
        await callback.answer("File not found or expired", show_alert=True)
        return
    if callback.message is None:
        await callback.answer()
        return

    if action == "cancel":
        file_manager.delete(telegram_id, record.rel_path)
        async with session_scope() as session:
            await delete_file_row(session, record.id)
        await safe_edit(callback.message, f"{Emoji.CANCEL} Cancelled.")
        await callback.answer()
        return

    if action == "clean":
        await _run_clean(callback.message, file_manager, settings, record)
    elif action == "live":
        await _run_live(callback.message, file_manager, settings, record)
    elif action == "dedup":
        await _run_dedup(callback.message, file_manager, settings, record)
    elif action == "addfile":
        await _run_addfile(callback.message, record)
    elif action == "country":
        await callback.message.answer(
            f"{Emoji.COUNTRY} Send the keyword like this:\n"
            f"<code>/country &lt;keyword&gt;</code>\n\n"
            "(reply to the file message with that command)"
        )
    elif action == "split":
        await callback.message.answer(
            "Choose how many parts:", reply_markup=split_choices(record.id)
        )
    elif action == "splitn" and count is not None:
        await _run_split(callback.message, file_manager, settings, record, count)
    await callback.answer()
