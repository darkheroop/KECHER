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
from bot.security.access import is_admin
from bot.services.cards import dedup_cards
from bot.services.file_manager import FileManager
from bot.ui.emoji import Emoji
from bot.ui.keyboards import back_to_menu, card_actions, specials_collect, specials_menu
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


async def _is_admin_user(tg_user, settings: Settings) -> bool:  # noqa: ANN001
    async with session_scope() as session:
        user = await ensure_user(session, tg_user)
        return is_admin(user, settings)


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
async def spec_clone(callback: CallbackQuery, settings: Settings) -> None:
    if not await _is_admin_user(callback.from_user, settings):
        await callback.answer("Admins only", show_alert=True)
        return
    if callback.message is not None:
        await safe_edit(callback.message, CLONE_TEXT, reply_markup=back_to_menu())
    await callback.answer()


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
