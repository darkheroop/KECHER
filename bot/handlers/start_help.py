"""``/start``, ``/menu`` and ``/help`` handlers, plus top-level navigation."""

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
from bot.ui.render import safe_edit

router = Router(name="start_help")

_FILE_PROMPT_ACTIONS = {
    "doc2txt", "csv", "split", "clean", "dedup", "addfile", "find", "country", "bank",
    "live", "luhn", "extract",
}

HELP_TEXT = (
    f"{Emoji.HELP} <b>Command reference</b>\n\n"
    f"{Emoji.FILE} <b>File tools</b>\n"
    "<code>/split</code> — split a TXT/CSV into smaller files\n"
    "<code>/clean</code> — clean &amp; validate a dataset\n"
    "<code>/dedup</code> — remove duplicate records\n"
    f"{Emoji.CONVERT} <code>/doc2txt</code> — DOC/DOCX → TXT\n"
    f"{Emoji.CSV} <code>/csv</code> — CSV → TXT\n"
    f"{Emoji.MERGE} <code>/addfile</code> · <code>/merge</code> · <code>/clearqueue</code>\n\n"
    f"{Emoji.SEARCH} <b>Data tools</b>\n"
    "<code>/find</code> · <code>/country</code> · <code>/pick</code> · "
    "<code>/bank</code> · <code>/pickbank</code>\n\n"
    f"{Emoji.SECURITY} <b>Security testing</b>\n"
    "<code>/live</code> — offline validation of authorized <b>test data only</b>\n\n"
    f"{Emoji.KEY} <b>Access</b>\n"
    "<code>/mykey</code> · <code>/redeem</code> · <code>/id</code>\n\n"
    f"{Emoji.SCRAPE} <b>Authorized sources</b>\n"
    "<code>/scrape</code> · <code>/private_scrape</code> · <code>/myaccounts</code> · "
    "<code>/plogin</code>\n\n"
    f"{Emoji.SETTINGS} <code>/settings</code> · <code>/jobs</code> · <code>/cancel</code>"
)

SECURITY_NOTE = (
    f"{Emoji.SECURITY} <b>Test mode only.</b> Payment features operate exclusively on "
    "synthetic/test data and never contact a payment network."
)

_TODO_SECTIONS = {
    "menu:file": ("File tools", "Choose a file operation from the File Tools menu."),
    "menu:data": ("Data tools", "Use /find, /country, /pick, /bank or /pickbank."),
    "menu:security": ("Security testing", "Use /live for offline test-data validation."),
    "menu:sources": ("Authorized sources", "Use /scrape, /private_scrape, /myaccounts or /plogin."),
}


def welcome_text(name: str | None) -> str:
    greeting = f", <b>{html.escape(name)}</b>" if name else ""
    return (
        f"{Emoji.START} <b>Telegram File Processing Bot</b>\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        f"Welcome{greeting}! Process, organise and search your files and datasets.\n\n"
        f"{Emoji.FILE} <b>File tools</b> — convert, split, clean, dedup, merge\n"
        f"{Emoji.SEARCH} <b>Data tools</b> — search, group by country/bank, export\n"
        f"{Emoji.SECURITY} <b>Security</b> — offline validation of test data\n\n"
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


@router.message(Command("menu"))
async def handle_menu(message: Message) -> None:
    await message.answer(
        f"{Emoji.FILE} <b>Main menu</b>\n\nChoose a section:",
        reply_markup=main_menu(),
    )


@router.message(Command("help"))
async def handle_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.callback_query(F.data == "menu:help")
async def menu_help(callback: CallbackQuery) -> None:
    await safe_edit(callback.message, HELP_TEXT, reply_markup=main_menu())
    await callback.answer()


@router.callback_query(F.data == "menu:back")
async def menu_back(callback: CallbackQuery) -> None:
    name = callback.from_user.first_name if callback.from_user else None
    await safe_edit(callback.message, welcome_text(name), reply_markup=main_menu())
    await callback.answer()


@router.callback_query(F.data == "menu:file")
async def menu_file(callback: CallbackQuery) -> None:
    await safe_edit(
        callback.message,
        f"{Emoji.FILE} <b>File Tools</b>\n\nChoose an operation:",
        reply_markup=file_tools_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "menu:data")
async def menu_data(callback: CallbackQuery) -> None:
    await safe_edit(
        callback.message,
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
