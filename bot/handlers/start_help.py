"""``/start`` and ``/help`` handlers, plus top-level menu navigation."""

from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.db.engine import session_scope
from bot.db.enums import AuditAction
from bot.db.repositories import get_or_create_user, get_user_settings, record_audit
from bot.handlers.file_ops import prompt_for_file
from bot.ui.emoji import Emoji
from bot.ui.keyboards import data_tools_menu, file_tools_menu, main_menu

router = Router(name="start_help")

_FILE_PROMPT_ACTIONS = {"doc2txt", "csv", "split", "clean", "dedup", "addfile", "find", "country", "bank", "live"}

HELP_TEXT = (
    f"{Emoji.HELP} <b>Commands</b>\n\n"
    f"{Emoji.FILE} <b>File tools</b>\n"
    "<code>/split</code> — split a TXT/CSV into smaller files\n"
    "<code>/clean</code> — clean &amp; validate a dataset\n"
    "<code>/dedup</code> — remove duplicate records\n"
    f"{Emoji.CONVERT} <code>/doc2txt</code> — DOC/DOCX \u2192 TXT\n"
    f"{Emoji.CSV} <code>/csv</code> — CSV \u2192 TXT\n"
    f"{Emoji.MERGE} <code>/addfile</code> \u00b7 <code>/merge</code> \u00b7 <code>/clearqueue</code>\n\n"
    f"{Emoji.SEARCH} <b>Data tools</b>\n"
    "<code>/find</code> \u00b7 <code>/country</code> \u00b7 <code>/pick</code> \u00b7 "
    "<code>/bank</code> \u00b7 <code>/pickbank</code>\n\n"
    f"{Emoji.SCRAPE} <b>Authorized sources</b>\n"
    "<code>/scrape</code> \u00b7 <code>/plogin</code> \u00b7 <code>/myaccounts</code> \u00b7 "
    "<code>/private_scrape</code>\n\n"
    f"{Emoji.SECURITY} <b>Security testing</b>\n"
    "<code>/live</code> — offline validation of authorized <b>test data only</b>\n\n"
    f"{Emoji.SETTINGS} <code>/settings</code> \u00b7 <code>/jobs</code> \u00b7 <code>/cancel</code>"
)

SECURITY_NOTE = (
    f"{Emoji.SECURITY} <b>Test mode only.</b> Payment features operate exclusively on "
    "synthetic/test data and never contact a payment network."
)

_TODO_SECTIONS = {
    "menu:file": ("File tools", "Document and dataset operations are available from the File Tools menu."),
    "menu:data": ("Data tools", "Use /find, /country, /pick, /bank or /pickbank."),
    "menu:security": ("Security testing", "Use /live for offline test-data validation."),
    "menu:sources": ("Authorized sources", "Use /scrape, /private_scrape, /myaccounts or /plogin."),
}


def welcome_text(name: str | None) -> str:
    greeting = f", {html.escape(name)}" if name else ""
    return (
        f"{Emoji.START} <b>Telegram File Processing Bot</b>\n\n"
        f"Welcome{greeting}! I process and organize files and datasets: "
        "convert, split, clean, deduplicate, merge and search.\n\n"
        f"{SECURITY_NOTE}"
    )


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    tg_user = message.from_user
    assert tg_user is not None

    async with session_scope() as session:
        user, created = await get_or_create_user(
            session,
            tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
        )
        await get_user_settings(session, user.id)
        await record_audit(
            session,
            user_id=user.id,
            action=AuditAction.USER_START,
            detail={"created": created},
        )

    await message.answer(welcome_text(tg_user.first_name), reply_markup=main_menu())


@router.message(Command("help"))
async def handle_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.callback_query(F.data == "menu:help")
async def menu_help(callback: CallbackQuery) -> None:
    if callback.message is not None:
        await callback.message.edit_text(HELP_TEXT, reply_markup=main_menu())
    await callback.answer()


@router.callback_query(F.data == "menu:back")
async def menu_back(callback: CallbackQuery) -> None:
    name = callback.from_user.first_name if callback.from_user else None
    if callback.message is not None:
        await callback.message.edit_text(welcome_text(name), reply_markup=main_menu())
    await callback.answer()


@router.callback_query(F.data == "menu:file")
async def menu_file(callback: CallbackQuery) -> None:
    if callback.message is not None:
        await callback.message.edit_text(
            f"{Emoji.FILE} <b>File Tools</b>\n\nChoose an operation:",
            reply_markup=file_tools_menu(),
        )
    await callback.answer()


@router.callback_query(F.data == "menu:data")
async def menu_data(callback: CallbackQuery) -> None:
    if callback.message is not None:
        await callback.message.edit_text(
            f"{Emoji.SEARCH} <b>Data Tools</b>\n\nChoose an operation:",
            reply_markup=data_tools_menu(),
        )
    await callback.answer()


@router.callback_query(F.data.in_(set(_TODO_SECTIONS)))
async def menu_todo_section(callback: CallbackQuery) -> None:
    title, note = _TODO_SECTIONS[callback.data]
    await callback.answer(f"{title}: {note}", show_alert=True)


@router.callback_query(F.data.startswith("menu:todo:"))
async def menu_todo_action(callback: CallbackQuery, state: FSMContext) -> None:
    action = (callback.data or "").rsplit(":", 1)[-1]

    if action == "merge":
        await callback.answer("Use /addfile to queue files, then /merge.", show_alert=True)
        return

    if action in _FILE_PROMPT_ACTIONS and callback.message is not None:
        await prompt_for_file(callback.message, state, action)
        await callback.answer()
        return

    await callback.answer(
        f"'{action}' will be available in an upcoming phase.", show_alert=True
    )
