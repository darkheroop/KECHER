"""``/settings`` — per-user preferences (UI mode, progress, cleanup, language)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.engine import session_scope
from bot.db.enums import AuditAction, UIMode
from bot.db.models import UserSettings
from bot.db.repositories import (
    get_or_create_user,
    get_user_settings,
    record_audit,
    update_user_settings,
)
from bot.ui.emoji import Emoji
from bot.ui.keyboards import settings_keyboard

router = Router(name="settings")

_VALID_UI_MODES = {m.value for m in UIMode}
_VALID_CLEANUP = {5, 10, 30}
_VALID_LANGUAGES = {"en"}

_UI_LABELS = {
    UIMode.BUTTONS.value: "Buttons",
    UIMode.COMMANDS.value: "Commands",
    UIMode.HYBRID.value: "Hybrid",
}


def render_settings(settings: UserSettings) -> str:
    progress = "On" if settings.progress_messages else "Off"
    return (
        f"{Emoji.SETTINGS} <b>Settings</b>\n\n"
        f"<b>UI Mode:</b> {_UI_LABELS.get(settings.ui_mode, settings.ui_mode)}\n"
        f"<b>Progress messages:</b> {progress}\n"
        f"<b>Auto cleanup:</b> {settings.cleanup_minutes} min\n"
        f"<b>Language:</b> English"
    )


def _keyboard(settings: UserSettings):
    return settings_keyboard(
        ui_mode=settings.ui_mode,
        progress_messages=settings.progress_messages,
        cleanup_minutes=settings.cleanup_minutes,
        language=settings.language,
    )


async def _load(session: AsyncSession, callback_or_message) -> tuple[object, UserSettings]:  # noqa: ANN001
    tg_user = callback_or_message.from_user
    user, _ = await get_or_create_user(
        session, tg_user.id, username=tg_user.username, first_name=tg_user.first_name
    )
    settings = await get_user_settings(session, user.id)
    return user, settings


@router.message(Command("settings"))
async def cmd_settings(message: Message) -> None:
    async with session_scope() as session:
        _, settings = await _load(session, message)
        text, keyboard = render_settings(settings), _keyboard(settings)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data == "settings:open")
async def open_settings(callback: CallbackQuery) -> None:
    async with session_scope() as session:
        _, settings = await _load(session, callback)
        text, keyboard = render_settings(settings), _keyboard(settings)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("set:"))
async def change_setting(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer("Invalid option", show_alert=True)
        return
    _, field, value = parts

    if field == "ui" and value in _VALID_UI_MODES:
        update = {"ui_mode": value}
    elif field == "prog" and value in {"0", "1"}:
        update = {"progress_messages": value == "1"}
    elif field == "clean" and value.isdigit() and int(value) in _VALID_CLEANUP:
        update = {"cleanup_minutes": int(value)}
    elif field == "lang" and value in _VALID_LANGUAGES:
        update = {"language": value}
    else:
        await callback.answer("Unknown setting", show_alert=True)
        return

    async with session_scope() as session:
        user, _ = await _load(session, callback)
        settings = await update_user_settings(session, user.id, **update)  # type: ignore[arg-type]
        await record_audit(
            session,
            user_id=user.id,
            action=AuditAction.SETTINGS_CHANGED,
            detail={"field": field, "value": value},
        )
        text, keyboard = render_settings(settings), _keyboard(settings)

    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer("Saved")
