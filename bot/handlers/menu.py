"""Start / menu / help / settings for the Card File Bot."""

from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from bot.config import Settings
from bot.db.engine import session_scope
from bot.db.enums import UIMode
from bot.db.repositories import get_or_create_user, get_user_settings, update_user_settings
from bot.handlers.common import ensure_user
from bot.handlers.cards import _run_merge
from bot.security.access import is_admin
from bot.services.file_manager import FileManager
from bot.ui.emoji import Emoji
from bot.ui.i18n import markdown_to_html, tr
from bot.ui.keyboards import main_menu, settings_menu
from bot.ui.render import safe_edit

router = Router(name="menu")

HEADER = f"{Emoji.CARD} <b>Card File Bot</b>"
DIVIDER = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"

HELP_TEXT = (
    f"{HEADER}\n{DIVIDER}\n"
    "<b>Reply to a .txt</b>\n"
    f"{Emoji.CLEAN} <code>/clean</code>  valid records\n"
    f"{Emoji.LIVE_CHECK} <code>/live</code>  Luhn-valid\n"
    f"{Emoji.FIND} <code>/filter 123456</code>  a series\n"
    f"{Emoji.FIND} <code>/filter canada</code>  a keyword\n"
    f"{Emoji.SPLIT} <code>/split N</code>   {Emoji.RECYCLE} <code>/dedup</code>\n"
    f"{Emoji.PAGE} <code>/addfile</code> → {Emoji.STAR} <code>/merge</code>\n\n"
    f"{Emoji.SETTINGS} <code>/settings</code>   {Emoji.ADMIN} <code>/admin</code>\n\n"
    f"<i>Record:</i> <code>serial|date|time|count</code>"
)

TEXT_GUIDE = (
    f"{HEADER}\n{DIVIDER}\n"
    "<b>Commands</b>\n"
    f"{Emoji.CLEAN} <code>/clean</code> — clean card lines\n"
    f"{Emoji.LIVE_CHECK} <code>/live</code> — Luhn validation\n"
    f"{Emoji.FIND} <code>/filter 123456</code> — a series\n"
    f"<code>/filter canada</code> — a keyword\n"
    f"{Emoji.FIND} <code>/findbin 411111</code> — filter by BIN\n"
    f"{Emoji.SPLIT} <code>/split N</code> — split a file\n"
    f"{Emoji.RECYCLE} <code>/dedup</code> — remove duplicates\n"
    f"{Emoji.PAGE} <code>/addfile</code> — add to merge queue\n"
    f"{Emoji.MERGE} <code>/merge</code> — merge queued files\n"
    f"<code>/clearqueue</code> — clear merge queue\n\n"
    f"{Emoji.SCRAPE} <code>/scrape</code> — scrape a group/channel\n"
    f"{Emoji.LOGIN} <code>/plogin</code> — connect a private account\n"
    f"{Emoji.ACCOUNT} <code>/myaccounts</code> — list accounts\n\n"
    f"{Emoji.SETTINGS} <code>/settings</code> — change UI mode\n"
    f"{Emoji.ADMIN} <code>/admin</code> — admin panel\n\n"
    "⚠️ Reply to a .txt file when using file commands."
)

MENU_INSTRUCTIONS = {
    "clean": "Reply to a .txt with <code>/clean</code>.",
    "live": "Reply to a .txt with <code>/live</code>.",
    "dedup": "Reply to a .txt with <code>/dedup</code>.",
    "addfile": "Reply to a .txt with <code>/addfile</code>.",
    "filter": "Reply to a .txt with <code>/filter &lt;keyword&gt;</code>.",
    "findbin": "Reply to a .txt with <code>/findbin &lt;digits&gt;</code>.",
    "split": "Reply to a .txt with <code>/split N</code>.",
}

COMING_SOON = {
    "scrape": "Scrape",
}


def welcome_text(lang: str = "en") -> str:
    return (
        f"{HEADER}\n{DIVIDER}\n"
        f"<i>{markdown_to_html(tr(lang, 'tagline'))}</i>\n\n"
        f"{markdown_to_html(tr(lang, 'welcome'))}"
    )


def help_text(lang: str = "en") -> str:
    return (
        f"{HEADER}\n{DIVIDER}\n"
        f"<b>{tr(lang, 'help_title')}</b>\n"
        f"{markdown_to_html(tr(lang, 'help_lines'))}\n\n"
        f"{Emoji.SETTINGS} <code>/settings</code>"
    )


def onboarding_text(name: str | None) -> str:
    who = f", <b>{html.escape(name)}</b>" if name else ""
    return (
        f"{HEADER}\n{DIVIDER}\n"
        f"Welcome{who} 👋\n\n"
        f"{Emoji.PAGE} Send a <b>.txt</b> (or reply to one), then:\n\n"
        f"{Emoji.CLEAN} <code>/clean</code> — valid records\n"
        f"{Emoji.LIVE_CHECK} <code>/live</code> — Luhn-valid\n"
        f"{Emoji.FIND} <code>/filter 123456</code> — a series\n"
        f"{Emoji.FIND} <code>/filter canada</code> — a keyword\n"
        f"{Emoji.SPLIT} <code>/split 5</code>   {Emoji.RECYCLE} <code>/dedup</code>\n"
        f"{Emoji.PAGE} <code>/addfile</code> → {Emoji.STAR} <code>/merge</code>\n\n"
        f"{Emoji.KEY} <code>/redeem KEY</code> or /request\n"
        f"<i>Record:</i> <code>serial|date|time|count</code>"
    )


def _is_button_mode(ui_mode: str) -> bool:
    return ui_mode != UIMode.COMMANDS.value


async def _mode(callback_or_message) -> str:  # noqa: ANN001
    async with session_scope() as session:
        user = await ensure_user(session, callback_or_message.from_user)
        settings_row = await get_user_settings(session, user.id)
        return settings_row.ui_mode


async def _is_admin(obj, settings: Settings) -> bool:  # noqa: ANN001
    async with session_scope() as session:
        user = await ensure_user(session, obj.from_user)
        return is_admin(user, settings)


async def _language(obj) -> str:  # noqa: ANN001
    async with session_scope() as session:
        user = await ensure_user(session, obj.from_user)
        row = await get_user_settings(session, user.id)
        return row.language


@router.message(CommandStart())
async def handle_start(message: Message, settings: Settings) -> None:
    tg_user = message.from_user
    assert tg_user is not None
    async with session_scope() as session:
        user, created = await get_or_create_user(
            session,
            tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
        )
        settings_row = await get_user_settings(session, user.id)
        admin = is_admin(user, settings)

    first_time = (
        onboarding_text(tg_user.first_name)
        if created
        else welcome_text(settings_row.language)
    )
    if _is_button_mode(settings_row.ui_mode):
        await message.answer(first_time, reply_markup=main_menu())
    else:
        await message.answer(
            (onboarding_text(tg_user.first_name) + "\n\n" + TEXT_GUIDE) if created else TEXT_GUIDE
        )


@router.message(Command("emojis"))
async def handle_emojis(message: Message) -> None:
    from bot.ui import emoji as emoji_module

    available = emoji_module.names()
    custom = emoji_module.current_custom()
    lines = [
        f"{Emoji.SETTINGS} <b>Emoji customization</b>",
        "",
        "Tip: send a message containing your premium emoji together with "
        "<code>/emojiid</code> (admin) and the bot replies with its id.",
        "",
        "Set <code>CUSTOM_EMOJI_IDS</code> in your environment as JSON "
        "mapping a name to a Telegram custom-emoji id:",
        '<code>{"SUCCESS":"5368324170671202286","CLEAN":"5368324170671202286"}</code>',
        "",
        f"Currently customised: <b>{len(custom)}</b>",
        "",
        "<b>Available names</b>",
        " ".join(f"<code>{name}</code>" for name in available),
    ]
    await message.answer("\n".join(lines))


@router.message(Command("menu"))
async def handle_menu(message: Message, settings: Settings) -> None:
    lang = await _language(message)
    await message.answer(welcome_text(lang), reply_markup=main_menu())


@router.message(Command("help"))
async def handle_help(message: Message) -> None:
    lang = await _language(message)
    await message.answer(help_text(lang))


@router.callback_query(F.data == "menu:home")
async def menu_home(callback: CallbackQuery, settings: Settings) -> None:
    lang = await _language(callback)
    await safe_edit(callback.message, welcome_text(lang), reply_markup=main_menu())
    await callback.answer()


@router.callback_query(F.data.in_({f"menu:{key}" for key in COMING_SOON}))
async def menu_coming_soon(callback: CallbackQuery) -> None:
    label = COMING_SOON[(callback.data or "").split(":", 1)[-1]]
    await callback.answer(f"{label} — coming soon.", show_alert=True)


@router.callback_query(F.data == "menu:merge")
async def menu_merge(callback: CallbackQuery, file_manager: FileManager) -> None:
    if callback.message is not None:
        await _run_merge(
            callback.message, file_manager, callback.from_user, callback.from_user.id
        )
    await callback.answer()


@router.callback_query(F.data.startswith("menu:"))
async def menu_instruction(callback: CallbackQuery) -> None:
    action = (callback.data or "").split(":", 1)[-1]
    if action not in MENU_INSTRUCTIONS:
        await callback.answer()
        return
    if callback.message is not None:
        await callback.message.answer(MENU_INSTRUCTIONS[action])
    await callback.answer()


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
def _settings_text(ui_mode: str, cleanup_minutes: int, language: str) -> str:
    current = "TEXT" if ui_mode == UIMode.COMMANDS.value else "BUTTON"
    lang_label = "Hinglish" if language == "hi-en" else "English"
    return (
        f"{Emoji.SETTINGS} <b>{tr(language, 'settings_title')}</b>\n{DIVIDER}\n"
        f"{tr(language, 's_mode')} · <b>{current}</b>\n"
        f"{tr(language, 's_cleanup')} · <b>{cleanup_minutes} min</b>\n"
        f"{tr(language, 's_language')} · <b>{lang_label}</b>"
    )


async def _settings_view(obj, settings: Settings):  # noqa: ANN001
    async with session_scope() as session:
        user = await ensure_user(session, obj.from_user)
        row = await get_user_settings(session, user.id)
        admin = is_admin(user, settings)
    return row, settings_menu(row.ui_mode, admin, row.cleanup_minutes, row.language)


@router.message(Command("settings"))
async def cmd_settings(message: Message, settings: Settings) -> None:
    row, keyboard = await _settings_view(message, settings)
    await message.answer(
        _settings_text(row.ui_mode, row.cleanup_minutes, row.language), reply_markup=keyboard
    )


@router.callback_query(F.data == "settings:open")
async def settings_open(callback: CallbackQuery, settings: Settings) -> None:
    row, keyboard = await _settings_view(callback, settings)
    await safe_edit(
        callback.message,
        _settings_text(row.ui_mode, row.cleanup_minutes, row.language),
        reply_markup=keyboard,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set:mode:"))
async def set_mode(callback: CallbackQuery, settings: Settings) -> None:
    value = (callback.data or "").rsplit(":", 1)[-1]
    ui_mode = UIMode.COMMANDS.value if value == "text" else UIMode.BUTTONS.value
    async with session_scope() as session:
        user = await ensure_user(session, callback.from_user)
        await update_user_settings(session, user.id, ui_mode=ui_mode)
    row, keyboard = await _settings_view(callback, settings)
    await safe_edit(
        callback.message,
        _settings_text(row.ui_mode, row.cleanup_minutes, row.language),
        reply_markup=keyboard,
    )
    await callback.answer("Saved")


@router.callback_query(F.data.startswith("set:clean:"))
async def set_cleanup(callback: CallbackQuery, settings: Settings) -> None:
    value = (callback.data or "").rsplit(":", 1)[-1]
    if value.isdigit():
        async with session_scope() as session:
            user = await ensure_user(session, callback.from_user)
            await update_user_settings(session, user.id, cleanup_minutes=int(value))
    row, keyboard = await _settings_view(callback, settings)
    await safe_edit(
        callback.message,
        _settings_text(row.ui_mode, row.cleanup_minutes, row.language),
        reply_markup=keyboard,
    )
    await callback.answer("Saved")


@router.callback_query(F.data.startswith("set:lang:"))
async def set_language(callback: CallbackQuery, settings: Settings) -> None:
    value = (callback.data or "").rsplit(":", 1)[-1]
    if value in {"en", "hi-en"}:
        async with session_scope() as session:
            user = await ensure_user(session, callback.from_user)
            await update_user_settings(session, user.id, language=value)
    row, keyboard = await _settings_view(callback, settings)
    await safe_edit(
        callback.message,
        _settings_text(row.ui_mode, row.cleanup_minutes, row.language),
        reply_markup=keyboard,
    )
    await callback.answer("Saved")
