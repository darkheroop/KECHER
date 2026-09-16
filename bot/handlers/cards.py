"""Card commands: /clean, /live, /filter, /split, /dedup, /addfile, /merge.

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

from bot.config import Settings, get_settings
from bot.db.engine import session_scope
from bot.db.enums import JobKind
from bot.db.models import UserFile
from bot.db.repositories import (
    add_queue_item,
    clear_queue,
    create_file,
    delete_file_row,
    get_bot_setting,
    get_user_files_by_ids,
    get_user_settings,
)
from bot.handlers.common import (
    ensure_user,
    forward_to_channel,
    get_owned_file,
    queue_snapshot,
    render_queue,
)
from bot.jobs.execution import run_with_progress
from bot.jobs.progress import ProgressReporter, TelegramNotifier
from bot.security.limits import human_size
from bot.services.cards import (
    clean_cards,
    count_lines,
    dedup_cards,
    filter_cards,
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
    "live": "🕵️ Receive only the records that pass the Luhn check.",
    "filter": "🎯 Receive the card lines that sit directly above your keyword.",
    "split": "✂️ Split the file into N equal parts.",
    "dedup": "♻️ Remove exact duplicate lines.",
    "addfile": "📄 Add the file to the merge queue.",
}

REPLY_PROMPT = {
    "clean": "🧹 Reply to a .txt file with /clean to extract valid records.",
    "live": "🕵️ Reply to a .txt file with /live to keep Luhn-valid records.",
    "filter": "🎯 Reply to a .txt with /filter 123456 (series) or /filter canada (keyword).",
    "findbin": "🎯 Reply to a .txt with /findbin 411111 (numbers only).",
    "split": "✂️ Reply to a .txt file with /split N to split it into N equal parts.",
    "dedup": "♻️ Reply to a .txt file with /dedup to remove duplicate lines.",
    "addfile": "📄 Reply to a .txt file with /addfile to add it to the merge queue.",
}


async def _forwarding_enabled() -> bool:
    async with session_scope() as session:
        return (await get_bot_setting(session, "forward_enabled", "false")) == "true"


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
        return None

    if settings.forward_uploads and await _forwarding_enabled():
        await forward_to_channel(message.bot, settings, reply.chat.id, reply.message_id)
    return record


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
    if not path.exists() or path.stat().st_size == 0:
        await message.answer(
            "ℹ️ No matching card data was found in that file, so there is nothing to send."
        )
        return
    sent = await message.answer_document(
        FSInputFile(path, filename=_tag(filename)), caption=caption
    )
    settings = get_settings()
    if settings.forward_results and await _forwarding_enabled():
        await forward_to_channel(message.bot, settings, sent.chat.id, sent.message_id)


def _tag(name: str) -> str:
    """Append the configured suffix before the file extension."""
    suffix = get_settings().file_suffix.strip()
    if not suffix:
        return name
    path = Path(name)
    return f"{path.stem}{suffix}{path.suffix}" if path.suffix else f"{name}{suffix}"


def _named(label: str, original: str, index: int = 1) -> str:
    """Name a result file after the operation, e.g. ``Cleaned-1.txt``."""
    return f"{label}-{index}.txt"


def _reporter(message: Message, status: Message) -> ProgressReporter:
    return ProgressReporter(
        TelegramNotifier(message.bot),
        message.chat.id,
        status.message_id,
        min_interval=1.0,
    )


def _details(*lines: str) -> str:
    return "\n".join(line for line in lines if line)


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
    await _run_clean(message, file_manager, settings, record, message.from_user.id)


@router.message(Command("live"))
async def cmd_live(message: Message, file_manager: FileManager, settings: Settings) -> None:
    record = await _ingest_reply(message, file_manager, settings)
    if record is None:
        await _prompt_reply(message, "live")
        return
    await _run_live(message, file_manager, settings, record, message.from_user.id)


@router.message(Command("dedup"))
async def cmd_dedup(message: Message, file_manager: FileManager, settings: Settings) -> None:
    record = await _ingest_reply(message, file_manager, settings)
    if record is None:
        await _prompt_reply(message, "dedup")
        return
    await _run_dedup(message, file_manager, settings, record, message.from_user.id)


@router.message(Command("addfile"))
async def cmd_addfile(message: Message, file_manager: FileManager, settings: Settings) -> None:
    record = await _ingest_reply(message, file_manager, settings)
    if record is None:
        await _prompt_reply(message, "addfile")
        return
    await _run_addfile(message, record, message.from_user)


async def _run_clean(
    message: Message, files: FileManager, settings: Settings, record: UserFile, telegram_id: int
) -> None:
    src = _resolve(record, files, telegram_id)
    total = count_lines(src)
    status = await message.answer(
        f"{Emoji.CLEAN} Cleaning <b>{total:,}</b> line(s)…"
    )
    out = files.allocate(telegram_id, _named("Cleaned", record.safe_name, 1), subdir="out")
    report = await run_with_progress(
        clean_cards,
        src,
        out.path,
        reporter=_reporter(message, status),
        total=max(1, total),
        label="Cleaning",
    )
    stored = files.finalize(out)
    async with session_scope() as session:
        user_settings = await get_user_settings(session, record.user_id)
    await _register_output(record, files, stored, user_settings.cleanup_minutes)
    await safe_edit(
        status,
        f"{Emoji.SUCCESS} <b>Cleaned</b> · {report.valid:,} valid · "
        f"{report.invalid:,} removed · {human_size(stored.size_bytes)}",
    )
    await _send_file(
        message,
        stored.path,
        stored.safe_name,
        f"🧹 {record.safe_name}\n{report.valid:,} valid · {report.invalid:,} removed · "
        f"{human_size(stored.size_bytes)}",
    )


async def _run_live(
    message: Message, files: FileManager, settings: Settings, record: UserFile, telegram_id: int
) -> None:
    src = _resolve(record, files, telegram_id)
    total = count_lines(src)
    status = await message.answer(
        f"{Emoji.LIVE_CHECK} Checking <b>{total:,}</b> line(s) with Luhn…"
    )
    out = files.allocate(telegram_id, _named("Luhn", record.safe_name, 1), subdir="out")
    report = await run_with_progress(
        live_cards,
        src,
        out.path,
        reporter=_reporter(message, status),
        total=max(1, total),
        label="Checking",
    )
    stored = files.finalize(out)
    async with session_scope() as session:
        user_settings = await get_user_settings(session, record.user_id)
    await _register_output(record, files, stored, user_settings.cleanup_minutes)
    await safe_edit(
        status,
        f"{Emoji.SUCCESS} <b>Luhn check</b> · {report.valid:,} valid · "
        f"{report.invalid:,} invalid · {human_size(stored.size_bytes)}",
    )
    await _send_file(
        message,
        stored.path,
        stored.safe_name,
        f"🕵️ {record.safe_name}\n{report.valid:,} valid · {report.invalid:,} invalid · "
        f"{human_size(stored.size_bytes)}",
    )


async def _run_dedup(
    message: Message, files: FileManager, settings: Settings, record: UserFile, telegram_id: int
) -> None:
    src = _resolve(record, files, telegram_id)
    total = count_lines(src)
    status = await message.answer(
        f"{Emoji.RECYCLE} Deduplicating <b>{total:,}</b> line(s)…"
    )
    out = files.allocate(telegram_id, _named("Deduped", record.safe_name, 1), subdir="out")
    report = await run_with_progress(
        dedup_cards,
        src,
        out.path,
        reporter=_reporter(message, status),
        total=max(1, total),
        label="Deduplicating",
    )
    stored = files.finalize(out)
    async with session_scope() as session:
        user_settings = await get_user_settings(session, record.user_id)
    await _register_output(record, files, stored, user_settings.cleanup_minutes)
    await safe_edit(
        status,
        f"{Emoji.SUCCESS} <b>Deduped</b> · {report.unique:,} unique · "
        f"{report.removed:,} removed · {human_size(stored.size_bytes)}",
    )
    await _send_file(
        message,
        stored.path,
        stored.safe_name,
        f"♻️ {record.safe_name}\n{report.unique:,} unique · {report.removed:,} removed · "
        f"{human_size(stored.size_bytes)}",
    )


async def _run_addfile(message: Message, record: UserFile, tg_user) -> None:  # noqa: ANN001
    async with session_scope() as session:
        user = await ensure_user(session, tg_user)
        await add_queue_item(session, user.id, record.id)
        records = await queue_snapshot(session, user.id)
    await message.answer(
        f"{Emoji.PAGE} <b>File added to the merge queue</b>\n\n{render_queue(records)}"
    )


# --------------------------------------------------------------------------- #
# /filter <keyword>
# --------------------------------------------------------------------------- #
@router.message(Command("filter"))
async def cmd_filter(message: Message, file_manager: FileManager, settings: Settings) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(
            f"{Emoji.FIND} <b>Filter</b>\n\n"
            "• By <b>series</b> (serial prefix): <code>/filter 123456</code>\n"
            "• By <b>keyword</b> (card lines above it): <code>/filter canada</code>\n\n"
            "You can also force it: <code>/filter num 123456</code> or "
            "<code>/filter name canada</code>."
        )
        return

    argument = parts[1].strip()
    mode = "prefix" if argument.isdigit() else "keyword"
    first, _, rest = argument.partition(" ")
    if first.lower() in {"num", "serial", "prefix", "bin"}:
        mode, argument = "prefix", rest.strip()
    elif first.lower() in {"name", "keyword", "text"}:
        mode, argument = "keyword", rest.strip()

    if not argument:
        await message.answer(
            f"{Emoji.ERROR} Give a series (e.g. <code>/filter 123456</code>) "
            "or a keyword (e.g. <code>/filter canada</code>)."
        )
        return

    record = await _ingest_reply(message, file_manager, settings)
    if record is None:
        await _prompt_reply(message, "filter")
        return
    await _run_filter(
        message, file_manager, settings, record, argument, mode, message.from_user.id
    )


async def _run_filter(
    message: Message,
    files: FileManager,
    settings: Settings,
    record: UserFile,
    value: str,
    mode: str,
    telegram_id: int,
) -> None:
    src = _resolve(record, files, telegram_id)
    total = count_lines(src)
    label = "Series" if mode == "prefix" else "Keyword"
    status = await message.answer(
        f"{Emoji.FIND} Filtering <b>{total:,}</b> line(s) by {label.lower()} "
        f"“{html.escape(value)}”…"
    )
    out = files.allocate(telegram_id, _named("Filter", record.safe_name, 1), subdir="out")
    report = await run_with_progress(
        filter_cards,
        src,
        out.path,
        value,
        reporter=_reporter(message, status),
        total=max(1, total),
        label="Filtering",
        mode=mode,
    )
    # filter_cards signature: (src, out, value, *, mode)
    stored = files.finalize(out)
    async with session_scope() as session:
        user_settings = await get_user_settings(session, record.user_id)
    await _register_output(record, files, stored, user_settings.cleanup_minutes)
    await safe_edit(
        status,
        f"{Emoji.SUCCESS} <b>{label} “{html.escape(value)}”</b> · "
        f"{report.lines:,} line(s) · {human_size(stored.size_bytes)}",
    )
    await _send_file(
        message,
        stored.path,
        stored.safe_name,
        f"🎯 {record.safe_name}\n{label} “{value}” · {report.lines:,} line(s) · "
        f"{human_size(stored.size_bytes)}",
    )


@router.message(Command("findbin"))
async def cmd_findbin(message: Message, file_manager: FileManager, settings: Settings) -> None:
    parts = (message.text or "").split(maxsplit=1)
    argument = parts[1].strip() if len(parts) > 1 else ""
    if not argument.isdigit():
        await message.answer(
            f"{Emoji.FIND} <b>Find BIN</b>\n\n"
            "Extract every record whose serial matches a numeric BIN/series.\n"
            "Numbers only, e.g. <code>/findbin 411111</code>\n\n"
            "(reply to a .txt file with that command)"
        )
        return
    record = await _ingest_reply(message, file_manager, settings)
    if record is None:
        await _prompt_reply(message, "findbin")
        return
    await _run_filter(
        message, file_manager, settings, record, argument, "prefix", message.from_user.id
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
    await _run_split(message, file_manager, settings, record, count, message.from_user.id)


async def _run_split(
    message: Message,
    files: FileManager,
    settings: Settings,
    record: UserFile,
    count: int,
    telegram_id: int,
) -> None:
    src = _resolve(record, files, telegram_id)
    total = count_lines(src)
    status = await message.answer(
        f"{Emoji.SPLIT} Splitting <b>{total:,}</b> line(s) into <b>{count}</b> part(s)…"
    )
    out_dir = files.user_root(telegram_id) / "out" / f"{Path(record.safe_name).stem}_parts"
    report = await run_with_progress(
        split_cards,
        src,
        out_dir,
        count,
        reporter=_reporter(message, status),
        total=max(1, total),
        label="Splitting",
    )
    parts = report.parts
    await safe_edit(
        status,
        f"{Emoji.SUCCESS} <b>Split</b> · {len(parts):,} parts · {report.lines:,} lines",
    )
    forward = get_settings().forward_results and await _forwarding_enabled()
    sent = 0
    for index, part in enumerate(parts, start=1):
        if not part.exists() or part.stat().st_size == 0:
            continue
        lines = count_lines(part)
        size = human_size(part.stat().st_size)
        delivered = await message.answer_document(
            FSInputFile(part, filename=_tag(f"Split-{index}-of-{len(parts)}.txt")),
            caption=f"✂️ Part {index} of {len(parts)} · {lines:,} lines · {size}",
        )
        if forward:
            await forward_to_channel(
                message.bot, get_settings(), delivered.chat.id, delivered.message_id
            )
        sent += 1
    if sent == 0:
        await message.answer("ℹ️ The file had no lines to split.")


# --------------------------------------------------------------------------- #
# /merge and queue
# --------------------------------------------------------------------------- #
@router.message(Command("merge"))
async def cmd_merge(message: Message, file_manager: FileManager, settings: Settings) -> None:
    await _run_merge(message, file_manager, message.from_user, message.from_user.id)


async def _run_merge(message: Message, files: FileManager, tg_user, telegram_id: int) -> None:  # noqa: ANN001
    async with session_scope() as session:
        user = await ensure_user(session, tg_user)
        records = await queue_snapshot(session, user.id)
        user_settings = await get_user_settings(session, user.id)

    if not records:
        await message.answer(f"{Emoji.STAR} Merge queue is empty. Add files with /addfile.")
        return

    paths = [files.resolve(telegram_id, r.rel_path, create_parent=False) for r in records]
    total = sum(count_lines(p) for p in paths if p.is_file())
    out = files.allocate(telegram_id, "Merged-1.txt", subdir="out")
    status = await message.answer(
        f"{Emoji.STAR} Merging <b>{len(records)}</b> file(s) · <b>{total:,}</b> line(s)…"
    )
    report = await run_with_progress(
        merge_files,
        paths,
        out.path,
        reporter=_reporter(message, status),
        total=max(1, total),
        label="Merging",
    )
    stored = files.finalize(out)

    async with session_scope() as session:
        for record in records:
            await delete_file_row(session, record.id)
        await clear_queue(session, user.id)

    await _register_output(records[0], files, stored, user_settings.cleanup_minutes)
    await safe_edit(
        status,
        f"{Emoji.SUCCESS} <b>Merged</b> · {report.files:,} files · "
        f"{report.lines:,} lines · {human_size(stored.size_bytes)}",
    )
    await _send_file(
        message,
        stored.path,
        stored.safe_name,
        f"⭐ {report.files:,} file(s)\n{report.lines:,} lines · {human_size(stored.size_bytes)}",
    )


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

    if settings.forward_uploads and await _forwarding_enabled():
        await forward_to_channel(message.bot, settings, message.chat.id, message.message_id)

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
        await _run_clean(callback.message, file_manager, settings, record, telegram_id)
    elif action == "live":
        await _run_live(callback.message, file_manager, settings, record, telegram_id)
    elif action == "dedup":
        await _run_dedup(callback.message, file_manager, settings, record, telegram_id)
    elif action == "addfile":
        await _run_addfile(callback.message, record, callback.from_user)
    elif action == "filter":
        await callback.message.answer(
            f"{Emoji.FIND} <b>Filter</b> — reply to the file with:\n"
            "• <code>/filter 123456</code> (series prefix)\n"
            "• <code>/filter canada</code> (keyword above)"
        )
    elif action == "split":
        await callback.message.answer(
            "Choose how many parts:", reply_markup=split_choices(record.id)
        )
    elif action == "splitn" and count is not None:
        await _run_split(callback.message, file_manager, settings, record, count, telegram_id)
    await callback.answer()


@router.callback_query()
async def unknown_callback(callback: CallbackQuery) -> None:
    """Gracefully handle buttons from an older menu version."""
    await callback.answer(
        "This button is from an older menu. Send /start to refresh.", show_alert=True
    )
