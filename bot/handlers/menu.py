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
from bot.ui.keyboards import main_menu, settings_menu
from bot.ui.render import safe_edit

router = Router(name="menu")

HEADER = f"{Emoji.CARD} <b>Card File Bot</b>"

HELP_TEXT = (
    f"{HEADER}\n"
    "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
    "<b>Reply to a .txt file with:</b>\n\n"
    f"{Emoji.CLEAN} <code>/clean</code> — keep valid card records "
    "(<code>serial|date|time|invited</code>)\n"
    f"{Emoji.LIVE_CHECK} <code>/live</code> — keep serials that pass the Luhn check\n"
    f"{Emoji.FIND} <code>/filter 123456</code> — all serials starting with a series\n"
    f"{Emoji.FIND} <code>/filter canada</code> — card lines above a keyword\n"
    f"{Emoji.SPLIT} <code>/split N</code> — split into N equal parts\n"
    f"{Emoji.RECYCLE} <code>/dedup</code> — remove duplicate lines\n\n"
    f"{Emoji.PAGE} <code>/addfile</code> then {Emoji.STAR} <code>/merge</code> — combine files\n"
    f"{Emoji.SETTINGS} <code>/settings</code> — button / text mode\n"
)

MENU_INSTRUCTIONS = {
    "clean": "Reply to a .txt file with <code>/clean</code>.",
    "live": "Reply to a .txt file with <code>/live</code>.",
    "dedup": "Reply to a .txt file with <code>/dedup</code>.",
    "addfile": "Reply to a .txt file with <code>/addfile</code>.",
    "filter": "Reply to a .txt file with <code>/filter &lt;keyword&gt;</code>.",
    "split": "Reply to a .txt file with <code>/split N</code>.",
}

COMING_SOON = {
    "scrape": "Scrape",
    "findbin": "Find BIN",
}


def welcome_text() -> str:
    return (
        f"{HEADER}\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        "Organise, validate and extract card serial records.\n\n"
        f"{Emoji.PAGE} Send a <b>.txt</b> file, or reply to one with a command.\n"
        f"{Emoji.HELP} /help for the full guide."
    )


def onboarding_text(name: str | None) -> str:
    who = f", <b>{html.escape(name)}</b>" if name else ""
    return (
        f"{HEADER}\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        f"Welcome{who}! Here's how it works in 20 seconds 👇\n\n"
        f"{Emoji.PAGE} <b>1 · Send a .txt</b> — or reply to one you already sent.\n\n"
        f"{Emoji.CLEAN} <b>2 · Run a command</b>\n"
        f"   <code>/clean</code> — extract valid records\n"
        f"   <code>/live</code> — keep Luhn-valid records\n"
        f"   <code>/filter 123456</code> — every serial of a series\n"
        f"   <code>/filter canada</code> — lines above a keyword\n"
        f"   <code>/split 5</code> · <code>/dedup</code> · <code>/addfile</code>+<code>/merge</code>\n\n"
        f"{Emoji.KEY} <b>3 · Access</b> — a key is required.\n"
        "   Redeem one with <code>/redeem YOUR-KEY</code>, or ask with /request.\n\n"
        f"{Emoji.CARD} Record: <code>serial|date|time|count</code>\n"
        "   e.g. <code>1234567891234567|02|2028|555</code>"
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

    first_time = onboarding_text(tg_user.first_name) if created else welcome_text()
    if _is_button_mode(settings_row.ui_mode):
        await message.answer(first_time, reply_markup=main_menu(admin))
    else:
        await message.answer(first_time + "\n\n" + HELP_TEXT if created else HELP_TEXT)


@router.message(Command("emojis"))
async def handle_emojis(message: Message) -> None:
    from bot.ui import emoji as emoji_module

    available = emoji_module.names()
    custom = emoji_module.current_custom()
    lines = [
        f"{Emoji.SETTINGS} <b>Emoji customization</b>",
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
    admin = await _is_admin(message, settings)
    await message.answer(welcome_text(), reply_markup=main_menu(admin))


@router.message(Command("help"))
async def handle_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.callback_query(F.data == "menu:home")
async def menu_home(callback: CallbackQuery, settings: Settings) -> None:
    admin = await _is_admin(callback, settings)
    await safe_edit(callback.message, welcome_text(), reply_markup=main_menu(admin))
    await callback.answer()


@router.callback_query(F.data.in_({f"menu:{key}" for key in COMING_SOON}))
async def menu_coming_soon(callback: CallbackQuery) -> None:
    label = COMING_SOON[(callback.data or "").split(":", 1)[-1]]
    await callback.answer(f"{label} — coming soon.", show_alert=True)


@router.callback_query(F.data == "menu:merge")
async def menu_merge(callback: CallbackQuery, file_manager: FileManager) -> None:
    if callback.message is not None:
        await _run_merge(callback.message, file_manager)
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
def _settings_text(ui_mode: str) -> str:
    current = "TEXT" if ui_mode == UIMode.COMMANDS.value else "BUTTON"
    return (
        f"{Emoji.SETTINGS} <b>Settings</b>\n\n"
        f"Current: <b>{current}</b>\n\n"
        "Choose how the bot shows actions."
    )


@router.message(Command("settings"))
async def cmd_settings(message: Message, settings: Settings) -> None:
    ui_mode = await _mode(message)
    await message.answer(_settings_text(ui_mode), reply_markup=settings_menu(ui_mode))


@router.callback_query(F.data == "settings:open")
async def settings_open(callback: CallbackQuery, settings: Settings) -> None:
    ui_mode = await _mode(callback)
    await safe_edit(
        callback.message, _settings_text(ui_mode), reply_markup=settings_menu(ui_mode)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set:mode:"))
async def set_mode(callback: CallbackQuery, settings: Settings) -> None:
    value = (callback.data or "").rsplit(":", 1)[-1]
    ui_mode = UIMode.COMMANDS.value if value == "text" else UIMode.BUTTONS.value
    async with session_scope() as session:
        user = await ensure_user(session, callback.from_user)
        await update_user_settings(session, user.id, ui_mode=ui_mode)
    await safe_edit(
        callback.message, _settings_text(ui_mode), reply_markup=settings_menu(ui_mode)
    )
    await callback.answer("Saved")
