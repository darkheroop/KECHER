"""SPECIALS: advanced tools.

* **Clone a channel** — copy messages from a chat you can access into your own.
* **Messages → .txt** — forward (or type) any messages and turn them into a
  single ``.txt`` you can then run every card operation on.
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import time
from datetime import UTC, datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from bot.config import Settings
from bot.db.engine import session_scope
from bot.db.repositories import create_file, get_user_settings
from bot.handlers.cards import _tag
from bot.handlers.common import ensure_user
from bot.handlers.states import Flow
from bot.services import prefs
from bot.services.cards import dedup_cards
from bot.services.engine import format_duration
from bot.services.file_manager import FileManager
from bot.services.scraper import ScrapeOptions
from bot.services.telegram_client import friendly_error
from bot.ui.emoji import Emoji
from bot.ui.keyboards import (
    account_help,
    back_to_menu,
    card_actions,
    clone_confirm,
    clone_method,
    clone_options,
    clone_picker,
    clone_progress,
    specials_collect,
    specials_menu,
)
from bot.ui.render import safe_edit

router = Router(name="specials")

DIVIDER = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
DRAFT_STEM = "Msgs"
_EDIT_INTERVAL = 1.2

MENU_TEXT = (
    f"{Emoji.SPECIALS} <b>SPECIALS</b>\n{DIVIDER}\n"
    f"{Emoji.CLONE} <b>Clone a channel</b> — copy messages from a chat you can "
    "access into a channel you own.\n\n"
    f"{Emoji.FORWARD} <b>Messages → .txt</b> — forward me any messages (or just "
    "type them) and I'll pack them into one <b>.txt</b>. Then every card tool "
    "(clean, live, filter, split, dedup, merge) works on it."
)

START_TEXT = (
    f"{Emoji.FORWARD} <b>Messages → .txt</b>\n{DIVIDER}\n"
    "Forward the messages you want (or type them one by one) and tap "
    f"<b>{Emoji.SUCCESS} Done</b> when finished.\n\n"
    "• text and photo/video captions are collected\n"
    "• each message becomes one line\n"
    "• the file goes straight to the normal card menu"
)

CLONE_TEXT = (
    f"{Emoji.CLONE} <b>Clone a channel</b>\n{DIVIDER}\n"
    "Copies messages from a chat you can access into a channel you own.\n\n"
    "Usage:\n<code>/clone &lt;source&gt; &lt;destination&gt; [limit]</code>\n\n"
    "Example:\n<code>/clone @source @mychannel 500</code>\n"
    "<code>/clone -1001234567890 @mychannel</code>\n\n"
    "• source/destination: <code>@username</code> or <code>-100…</code>\n"
    "• limit: how many recent messages (default 200)\n\n"
    f"{Emoji.SECURITY} Only sources your account can access are used. "
    "Nothing is bypassed."
)


def _progress_text(count: int, lines: int, skipped: int, dedupe: bool = False) -> str:
    mode = "♻️ Dedupe & build" if dedupe else "✅ Done"
    tail = f"\n{Emoji.WARNING} Skipped {skipped} message(s) with no text." if skipped else ""
    return (
        f"{Emoji.FORWARD} <b>Collecting…</b>\n{DIVIDER}\n"
        f"{Emoji.MESSAGE} Messages: <b>{count}</b>\n"
        f"{Emoji.PAGE} Lines: <b>{lines}</b>{tail}\n\n"
        f"Forward more, or tap <b>{mode}</b>."
    )


def _dialog_title(dialogs, entry_id) -> str:  # noqa: ANN001
    for row in dialogs:
        if int(row[0]) == int(entry_id):
            return str(row[1])
    return str(entry_id)


async def _account_label(scraper, owner: int):  # noqa: ANN001
    return (await scraper.acting_label(owner)) or (await scraper.active_label(owner))


def _date_from(value: str, now: datetime) -> datetime | None:
    return {
        "7": now - timedelta(days=7),
        "30": now - timedelta(days=30),
        "90": now - timedelta(days=90),
    }.get(value)


async def _show_clone_picker(
    callback: CallbackQuery, state: FSMContext, prefix: str, page: int
) -> None:
    data = await state.get_data()
    dialogs = [tuple(row) for row in (data.get("clone_dialogs") or [])]
    if prefix == "dst":
        src = data.get("clone_src") or [None]
        dialogs = [row for row in dialogs if int(row[0]) != int(src[0])]
        header = f"{Emoji.CLONE} <b>Clone · destination</b>"
        hint = "Where should the messages go?   🟢 = you can post there"
    else:
        header = f"{Emoji.CLONE} <b>Clone · source</b>"
        hint = "Which chat should be copied?   🟢 = you can also post there"
    await safe_edit(
        callback.message,
        f"{header}\n{DIVIDER}\n{hint}",
        reply_markup=clone_picker(dialogs, page=page, prefix=prefix),
    )


async def _stash_job(state: FSMContext, tg_user) -> dict:  # noqa: ANN001
    data = await state.get_data()
    opts = data.get("clone_opts") or {}
    src = data.get("clone_src") or [None, "source"]
    dst = data.get("clone_dst") or [None, "destination"]
    saved = await prefs.load_prefs(tg_user.id)
    use_keywords = bool(opts.get("use_keywords", True))
    keywords = [w for w in (saved.get("keywords") or []) if w] if use_keywords else []
    dates = opts.get("dates", "none")
    limit = int(opts.get("limit", 1000))
    options = ScrapeOptions(
        limit=limit or 1_000_000,
        keywords=keywords,
        keyword_mode=saved.get("keyword_mode", "contains"),
        include_media=True,
        text_only=False,
        date_from=_date_from(dates, datetime.now(UTC)),
    )
    job = {
        "src_ref": str(src[0]),
        "dest_ref": str(dst[0]),
        "src_title": src[1],
        "dest_title": dst[1],
        "limit": limit,
        "copy": opts.get("method") == "copy",
        "options": options,
        "keywords": keywords,
        "dates": dates,
        "method": opts.get("method", "forward"),
    }
    await state.update_data(clone_job=job, clone_stop=False)
    return job


def _clone_confirm_text(job: dict) -> str:
    method = "📋 Copy (no attribution)" if job.get("copy") else "➡️ Forward (keeps source)"
    limit = f"{job['limit']:,}" if job.get("limit") else "All"
    filters = ", ".join(job.get("keywords") or []) or "none"
    return (
        f"{Emoji.CLONE} <b>Confirm clone</b>\n{DIVIDER}\n"
        f"{Emoji.INBOX} From · <b>{html.escape(str(job['src_title']))}</b>\n"
        f"{Emoji.INBOX} To · <b>{html.escape(str(job['dest_title']))}</b>\n"
        f"🎚 Method · <b>{method}</b>\n"
        f"{Emoji.FIND} Keywords · <b>{html.escape(filters)}</b>\n"
        f"{Emoji.CALENDAR} Dates · <b>{job.get('dates', 'none')}</b>   Limit · <b>{limit}</b>\n\n"
        "<i>You can stop the clone at any time.</i>"
    )


def _clone_run_text(job: dict, copied: int, elapsed: float, eta: float | None) -> str:
    limit = int(job.get("limit") or 0)
    body = f"{Emoji.DOWNLOAD} Copied · <b>{copied:,}</b>"
    if limit:
        body += f" / {limit:,}  ({min(100, int(copied * 100 / max(1, limit)))}%)"
    return (
        f"{Emoji.CLONE} <b>Cloning</b> · {html.escape(str(job['dest_title']))}\n{DIVIDER}\n"
        f"{body}\n"
        f"{Emoji.TIME} Elapsed · <b>{format_duration(elapsed)}</b>\n"
        f"{Emoji.CLOCK} ETA · <b>{format_duration(eta)}</b>"
    )


async def _clone_stop_requested(state: FSMContext) -> bool:
    return bool((await state.get_data()).get("clone_stop"))


async def _edit_clone_status(
    bot, chat_id: int, message_id: int, job: dict, copied: int, elapsed: float, eta  # noqa: ANN001
) -> None:
    with contextlib.suppress(Exception):
        await bot.edit_message_text(
            _clone_run_text(job, copied, elapsed, eta),
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=clone_progress(),
        )


async def _show_clone_options(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    opts = data.get("clone_opts") or {}
    src = data.get("clone_src") or [None, "source"]
    dst = data.get("clone_dst") or [None, "destination"]
    method = "📋 Copy" if opts.get("method") == "copy" else "➡️ Forward"
    limit = opts.get("limit", 1000)
    text = (
        f"{Emoji.CLONE} <b>Clone · options</b>\n{DIVIDER}\n"
        f"{Emoji.INBOX} <b>{html.escape(str(src[1]))}</b> → "
        f"<b>{html.escape(str(dst[1]))}</b>\n"
        f"🎚 {method} · Limit <b>{limit or 'All'}</b>\n"
        f"{Emoji.FIND} Keywords · "
        f"<b>{'my saved keywords' if opts.get('use_keywords', True) else 'none'}</b>\n"
        f"{Emoji.CALENDAR} Dates · <b>{opts.get('dates', 'none')}</b>"
    )
    await safe_edit(callback.message, text, reply_markup=clone_options(opts))


async def _push_status(message: Message, state: FSMContext, force: bool = False) -> None:
    data = await state.get_data()
    count = int(data.get("spec_count", 0))
    lines = int(data.get("spec_lines", 0))
    skipped = int(data.get("spec_skipped", 0))
    text = _progress_text(count, lines, skipped)
    keyboard = specials_collect(count, lines)

    status_id = data.get("spec_status")
    now = time.monotonic()
    last = float(data.get("spec_edit", 0.0) or 0.0)
    if status_id and not force and now - last < _EDIT_INTERVAL:
        return
    if status_id:
        with contextlib.suppress(Exception):
            await message.bot.edit_message_text(
                text, chat_id=message.chat.id, message_id=status_id, reply_markup=keyboard
            )
            await state.update_data(spec_edit=now)
            return
    sent = await message.answer(text, reply_markup=keyboard)
    await state.update_data(spec_status=sent.message_id, spec_edit=now)


async def _start_collect(
    message: Message, tg_user, state: FSMContext, file_manager: FileManager
) -> None:  # noqa: ANN001
    await state.clear()
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H%M")
    draft = file_manager.allocate(tg_user.id, f"{DRAFT_STEM} {stamp}.txt", subdir="out")
    try:
        draft.path.write_text("", encoding="utf-8")
    except OSError:
        await message.answer(f"{Emoji.ERROR} Could not create the draft file.")
        return
    await state.set_state(Flow.collecting_specials)
    await state.update_data(
        spec_draft=draft.rel_path,
        spec_count=0,
        spec_lines=0,
        spec_skipped=0,
    )
    await message.answer(START_TEXT)
    await _push_status(message, state, force=True)


async def _build(
    message: Message | None,
    event,  # noqa: ANN001
    state: FSMContext,
    file_manager: FileManager,
    *,
    dedupe: bool,
) -> None:
    data = await state.get_data()
    rel = data.get("spec_draft")
    count = int(data.get("spec_count", 0))
    lines = int(data.get("spec_lines", 0))
    skipped = int(data.get("spec_skipped", 0))
    is_callback = isinstance(event, CallbackQuery)

    if not rel or not count or not lines:
        if is_callback:
            await event.answer("Nothing collected yet.", show_alert=True)
        else:
            await event.answer(f"{Emoji.INFO} Nothing collected yet.")
        return

    telegram_id = event.from_user.id
    try:
        draft_path = file_manager.resolve(telegram_id, rel, create_parent=False)
    except (ValueError, OSError):
        await state.clear()
        if is_callback:
            await event.answer("Draft expired.", show_alert=True)
        else:
            await event.answer(f"{Emoji.ERROR} Draft expired.")
        return

    await state.clear()
    if message is None or not draft_path.exists():
        return

    status = await message.answer(f"{Emoji.PAGE} Building your .txt…")
    removed = 0
    try:
        if dedupe:
            out = file_manager.allocate(
                telegram_id, f"{draft_path.stem} deduped.txt", subdir="out"
            )
            report = await asyncio.to_thread(dedup_cards, draft_path, out.path)
            if report.unique == 0:
                out.path.unlink(missing_ok=True)
                raise ValueError("empty")
            stored = file_manager.finalize(out)
            removed = report.removed
            draft_path.unlink(missing_ok=True)
        else:
            stored = file_manager.finalize_path(telegram_id, draft_path)
    except Exception:  # noqa: BLE001
        await status.edit_text(f"{Emoji.ERROR} Nothing to build — no text was collected.")
        return

    async with session_scope() as session:
        user = await ensure_user(session, event.from_user)
        row = await get_user_settings(session, user.id)
        record = await create_file(
            session,
            user_id=user.id,
            original_name=stored.safe_name,
            safe_name=stored.safe_name,
            rel_path=stored.rel_path,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
            expires_at=datetime.now(UTC) + timedelta(minutes=max(1, row.cleanup_minutes)),
        )

    detail = f" · ♻️ {removed:,} duplicate line(s) removed" if dedupe else ""
    await status.edit_text(
        f"{Emoji.SUCCESS} <b>File built</b>\n{DIVIDER}\n"
        f"{Emoji.MESSAGE} Messages: <b>{count:,}</b>\n"
        f"{Emoji.PAGE} Lines: <b>{lines:,}</b>{detail}"
    )
    await message.answer_document(
        FSInputFile(stored.path, filename=_tag(stored.safe_name)),
        caption=(
            f"{Emoji.PAGE} <b>{html.escape(stored.safe_name)}</b>\n"
            f"{Emoji.MESSAGE} {count:,} message(s) · {lines:,} line(s)"
            + (f"\n♻️ {removed:,} duplicate line(s) removed" if dedupe else "")
            + (f"\n{Emoji.WARNING} {skipped} skipped (no text)" if skipped else "")
        ),
    )
    await message.answer(
        f"{Emoji.CARD} <b>File ready</b>\n{DIVIDER}\n"
        "Run any card tool on it:",
        reply_markup=card_actions(record.id),
    )
    if is_callback:
        await safe_edit(
            event.message,
            _progress_text(count, lines, skipped, dedupe),
            reply_markup=back_to_menu(),
        )
        await event.answer("Built ✅")


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #
@router.message(Command("specials"))
async def cmd_specials(message: Message) -> None:
    await message.answer(MENU_TEXT, reply_markup=specials_menu())


@router.message(Command("totxt"))
async def cmd_totxt(
    message: Message, state: FSMContext, file_manager: FileManager
) -> None:
    assert message.from_user is not None
    await _start_collect(message, message.from_user, state, file_manager)


@router.callback_query(F.data.in_({"spec:open", "spec:menu"}))
async def spec_open(callback: CallbackQuery) -> None:
    if callback.message is not None:
        await safe_edit(callback.message, MENU_TEXT, reply_markup=specials_menu())
    await callback.answer()


@router.callback_query(F.data == "spec:clone")
async def spec_clone(
    callback: CallbackQuery, state: FSMContext, scraper, settings: Settings  # noqa: ANN001
) -> None:
    tg_user = callback.from_user
    if not scraper.user_connected(tg_user.id):
        await callback.answer("Connect an account first (/scrape).", show_alert=True)
        return
    label = await _account_label(scraper, tg_user.id)
    if callback.message is not None:
        await safe_edit(callback.message, f"{Emoji.CLONE} Loading your chats…")
    try:
        dialogs = await scraper.list_dialogs(label, limit=settings.clone_max_dialogs)
    except Exception as exc:  # noqa: BLE001
        if callback.message is not None:
            await safe_edit(
                callback.message,
                f"{Emoji.ERROR} {html.escape(friendly_error(exc))}",
                reply_markup=back_to_menu(),
            )
        await callback.answer()
        return
    if not dialogs:
        if callback.message is not None:
            await safe_edit(
                callback.message,
                f"{Emoji.INFO} No groups or channels found for this account.",
                reply_markup=back_to_menu(),
            )
        await callback.answer()
        return
    await state.update_data(
        clone_dialogs=[[int(d["id"]), str(d["title"]), bool(d["can_post"])] for d in dialogs],
        clone_src=None,
        clone_dst=None,
        clone_job=None,
        clone_stop=False,
        clone_opts={"limit": 1000, "use_keywords": True, "dates": "none", "method": "forward"},
    )
    await _show_clone_picker(callback, state, "src", 0)
    await callback.answer()


@router.message(Command("clone"))
async def cmd_clone(
    message: Message, state: FSMContext, scraper, settings: Settings  # noqa: ANN001
) -> None:
    tg_user = message.from_user
    assert tg_user is not None
    if not scraper.user_connected(tg_user.id):
        await message.answer(
            f"{Emoji.LOGIN} Connect an account first, then try again.",
            reply_markup=account_help(),
        )
        return
    parts = (message.text or "").split(maxsplit=3)
    if len(parts) < 3:
        await message.answer(CLONE_TEXT, reply_markup=specials_menu())
        return
    limit = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 200
    job = {
        "src_ref": parts[1],
        "dest_ref": parts[2],
        "src_title": parts[1],
        "dest_title": parts[2],
        "limit": max(1, min(limit, 5000)),
        "copy": False,
        "options": None,
        "keywords": [],
        "dates": "none",
        "method": "forward",
    }
    await state.update_data(clone_job=job, clone_stop=False)
    await message.answer(_clone_confirm_text(job), reply_markup=clone_confirm())


@router.callback_query(F.data == "clone:noop")
async def clone_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data.startswith("clone:page:"))
async def clone_page(callback: CallbackQuery, state: FSMContext) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 4 or not parts[3].lstrip("-").isdigit():
        await callback.answer()
        return
    await _show_clone_picker(callback, state, parts[2], int(parts[3]))
    await callback.answer()


@router.callback_query(F.data.startswith("clone:pick:src:"))
async def clone_pick_src(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    dialogs = data.get("clone_dialogs") or []
    entry_id = int((callback.data or "").rsplit(":", 1)[-1])
    await state.update_data(clone_src=[entry_id, _dialog_title(dialogs, entry_id)])
    await _show_clone_picker(callback, state, "dst", 0)
    await callback.answer()


@router.callback_query(F.data.startswith("clone:pick:dst:"))
async def clone_pick_dst(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    dialogs = data.get("clone_dialogs") or []
    entry_id = int((callback.data or "").rsplit(":", 1)[-1])
    src = data.get("clone_src") or [None, "source"]
    await state.update_data(clone_dst=[entry_id, _dialog_title(dialogs, entry_id)])
    if callback.message is not None:
        await safe_edit(
            callback.message,
            f"{Emoji.CLONE} <b>Clone · method</b>\n{DIVIDER}\n"
            f"{Emoji.INBOX} <b>{html.escape(str(src[1]))}</b> → "
            f"<b>{html.escape(_dialog_title(dialogs, entry_id))}</b>\n\n"
            "How should the messages be sent?",
            reply_markup=clone_method(),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("clone:method:"))
async def clone_set_method(callback: CallbackQuery, state: FSMContext) -> None:
    method = (callback.data or "").rsplit(":", 1)[-1]
    data = await state.get_data()
    opts = dict(data.get("clone_opts") or {})
    opts["method"] = method if method in {"forward", "copy"} else "forward"
    opts.setdefault("limit", 1000)
    opts.setdefault("use_keywords", True)
    opts.setdefault("dates", "none")
    await state.update_data(clone_opts=opts, clone_job=None)
    await _show_clone_options(callback, state)
    await callback.answer()


@router.callback_query(F.data.startswith("clone:opt:"))
async def clone_set_option(callback: CallbackQuery, state: FSMContext) -> None:
    parts = (callback.data or "").split(":")
    data = await state.get_data()
    opts = dict(data.get("clone_opts") or {})
    opts.setdefault("limit", 1000)
    opts.setdefault("use_keywords", True)
    opts.setdefault("dates", "none")
    opts.setdefault("method", "forward")
    if len(parts) >= 4 and parts[2] == "limit" and parts[3].isdigit():
        opts["limit"] = int(parts[3])
    elif len(parts) >= 4 and parts[2] == "dates":
        opts["dates"] = parts[3]
    elif len(parts) >= 3 and parts[2] == "kw":
        opts["use_keywords"] = not opts.get("use_keywords", True)
    await state.update_data(clone_opts=opts, clone_job=None)
    await _show_clone_options(callback, state)
    await callback.answer()


@router.callback_query(F.data == "clone:stop")
async def clone_stop(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(clone_stop=True)
    await callback.answer("Stopping after this batch…")


@router.callback_query(F.data == "clone:no")
async def clone_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_edit(
        callback.message,
        f"{Emoji.CANCEL} Clone cancelled.",
        reply_markup=specials_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "clone:go")
async def clone_go(
    callback: CallbackQuery, state: FSMContext, scraper, settings: Settings  # noqa: ANN001
) -> None:
    tg_user = callback.from_user
    data = await state.get_data()
    if data.get("clone_src") and data.get("clone_dst"):
        job = await _stash_job(state, tg_user)
    else:
        job = data.get("clone_job")
    if not job:
        await callback.answer("Pick a source and destination first.", show_alert=True)
        return

    label = await _account_label(scraper, tg_user.id)
    if label is None:
        await callback.answer("No connected account.", show_alert=True)
        return
    if callback.message is None:
        await callback.answer()
        return

    await state.update_data(clone_stop=False)
    status = await callback.message.answer(
        _clone_run_text(job, 0, 0.0, None), reply_markup=clone_progress()
    )
    await callback.answer()

    started = time.monotonic()
    throttle = {"t": 0.0}

    def on_progress(done: int) -> None:
        now = time.monotonic()
        if now - throttle["t"] < 1.5:
            return
        throttle["t"] = now
        elapsed = now - started
        limit = int(job.get("limit") or 0)
        eta = max(0.0, elapsed * (limit - done) / done) if limit and done else None
        asyncio.create_task(
            _edit_clone_status(
                callback.bot, callback.message.chat.id, status.message_id, job, done, elapsed, eta
            )
        )

    try:
        copied = await scraper.clone(
            label=label,
            src_ref=job["src_ref"],
            dest_ref=job["dest_ref"],
            limit=int(job.get("limit") or 0),
            copy=bool(job.get("copy")),
            options=job.get("options"),
            on_progress=on_progress,
            should_stop=lambda: _clone_stop_requested(state),
        )
    except Exception as exc:  # noqa: BLE001
        await safe_edit(
            status,
            f"{Emoji.ERROR} {html.escape(friendly_error(exc))}",
            reply_markup=back_to_menu(),
        )
        return

    await safe_edit(
        status,
        f"{Emoji.SUCCESS} <b>Clone complete</b>\n{DIVIDER}\n"
        f"{Emoji.INBOX} To · <b>{html.escape(str(job['dest_title']))}</b>\n"
        f"{Emoji.DOWNLOAD} Copied · <b>{copied:,}</b> message(s)\n"
        f"{Emoji.TIME} Time · <b>{format_duration(time.monotonic() - started)}</b>",
        reply_markup=back_to_menu(),
    )
    await state.clear()


@router.callback_query(F.data == "spec:txt")
async def spec_txt(
    callback: CallbackQuery, state: FSMContext, file_manager: FileManager
) -> None:
    if callback.message is not None:
        await _start_collect(callback.message, callback.from_user, state, file_manager)
    await callback.answer("Forward your messages now")


# --------------------------------------------------------------------------- #
# Build / cancel
# --------------------------------------------------------------------------- #
@router.message(Flow.collecting_specials, Command("done"))
async def spec_done_cmd(message: Message, state: FSMContext, file_manager: FileManager) -> None:
    await _build(message, message, state, file_manager, dedupe=False)


@router.callback_query(F.data == "spec:done")
async def spec_done(callback: CallbackQuery, state: FSMContext, file_manager: FileManager) -> None:
    await _build(callback.message, callback, state, file_manager, dedupe=False)


@router.callback_query(F.data == "spec:build:dedup")
async def spec_build_dedup(
    callback: CallbackQuery, state: FSMContext, file_manager: FileManager
) -> None:
    await _build(callback.message, callback, state, file_manager, dedupe=True)


@router.callback_query(F.data == "spec:cancel")
async def spec_cancel(
    callback: CallbackQuery, state: FSMContext, file_manager: FileManager
) -> None:
    data = await state.get_data()
    rel = data.get("spec_draft")
    await state.clear()
    if rel:
        file_manager.delete(callback.from_user.id, rel)
    await safe_edit(
        callback.message,
        f"{Emoji.CANCEL} Specials cancelled. Draft discarded.",
        reply_markup=specials_menu(),
    )
    await callback.answer()


# --------------------------------------------------------------------------- #
# Collector (must stay last: catches every non-command message in the flow)
# --------------------------------------------------------------------------- #
@router.message(Flow.collecting_specials, ~F.text.startswith("/"))
async def spec_collect(
    message: Message, state: FSMContext, file_manager: FileManager
) -> None:
    tg_user = message.from_user
    assert tg_user is not None
    data = await state.get_data()
    rel = data.get("spec_draft")
    if not rel:
        await state.clear()
        return

    text = (message.text or message.caption or "").strip()
    count = int(data.get("spec_count", 0))
    lines = int(data.get("spec_lines", 0))
    skipped = int(data.get("spec_skipped", 0))

    if not text:
        skipped += 1
    else:
        try:
            path = file_manager.resolve(tg_user.id, rel, create_parent=True)
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                for line in text.splitlines():
                    if line.strip():
                        handle.write(line.rstrip() + "\n")
                        lines += 1
        except OSError:
            await message.answer(f"{Emoji.ERROR} Could not write the draft file.")
            return
        count += 1

    await state.update_data(spec_count=count, spec_lines=lines, spec_skipped=skipped)
    await _push_status(message, state)
