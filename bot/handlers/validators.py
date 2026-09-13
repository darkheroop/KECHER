"""``/live`` and ``/validate`` — offline test-data validation.

Local, mathematical checks only. No payment network is ever contacted.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User as TgUser

from bot.db.enums import JobKind
from bot.handlers.common import start_job
from bot.jobs.manager import JobManager
from bot.ui.emoji import Emoji
from bot.ui.keyboards import validate_options_keyboard

router = Router(name="validators")

DEFAULT_OPTIONS = {
    "luhn": True,
    "expiry": True,
    "length": True,
    "test_bin": False,
}

BANNER = (
    f"{Emoji.SECURITY} <b>TEST MODE</b>\n\n"
    "Local validation only.\n"
    "No payment network was contacted."
)


async def start_validation(reply: Message, record, tg_user: TgUser, state: FSMContext) -> None:
    options = dict(DEFAULT_OPTIONS)
    await state.update_data(val_options=options)
    await reply.answer(
        f"{BANNER}\n\nChoose checks for <b>{record.safe_name}</b>:",
        reply_markup=validate_options_keyboard(record.id, options),
    )


@router.message(Command("live"))
async def cmd_live(message: Message, state: FSMContext) -> None:
    from bot.handlers.file_ops import prompt_for_file

    await prompt_for_file(message, state, "live")


@router.message(Command("validate"))
async def cmd_validate(message: Message, state: FSMContext) -> None:
    from bot.handlers.file_ops import prompt_for_file

    await prompt_for_file(message, state, "live")


@router.callback_query(F.data.startswith("val:toggle:"))
async def on_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 4 or not parts[3].isdigit():
        await callback.answer("Invalid option", show_alert=True)
        return
    key, file_id = parts[2], int(parts[3])
    data = await state.get_data()
    options = dict(data.get("val_options") or DEFAULT_OPTIONS)
    if key in options:
        options[key] = not options[key]
    await state.update_data(val_options=options)
    if callback.message is not None:
        await callback.message.edit_reply_markup(
            reply_markup=validate_options_keyboard(file_id, options)
        )
    await callback.answer()


@router.callback_query(F.data.startswith("val:run:"))
async def on_run(callback: CallbackQuery, state: FSMContext, job_manager: JobManager) -> None:
    raw = (callback.data or "").rsplit(":", 1)[-1]
    if not raw.isdigit():
        await callback.answer("Invalid file", show_alert=True)
        return
    data = await state.get_data()
    options = dict(data.get("val_options") or DEFAULT_OPTIONS)
    await state.clear()
    if callback.message is not None:
        await start_job(
            callback.message,
            job_manager,
            tg_user=callback.from_user,
            kind=JobKind.VALIDATE,
            input_file_id=int(raw),
            params={"options": options},
            label="Validating test data",
        )
    await callback.answer()
