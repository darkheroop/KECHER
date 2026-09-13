"""Data tools: /find, /country, /pick, /bank, /pickbank."""

from __future__ import annotations

import asyncio
import html

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User as TgUser

from bot.db.engine import session_scope
from bot.db.enums import JobKind
from bot.handlers.common import ensure_user, get_owned_file, start_job
from bot.handlers.states import Flow
from bot.jobs.manager import JobManager
from bot.services.dataset import (
    DatasetInfo,
    detect_field,
    group_counts,
    inspect_dataset,
)
from bot.services.file_manager import FileManager
from bot.services.geo import country_label
from bot.ui.emoji import Emoji
from bot.ui.keyboards import picker_keyboard

router = Router(name="data_tools")

COUNTRY_FIELDS = {
    "country",
    "country_code",
    "country_name",
    "countrycode",
    "cc",
    "iso",
    "iso2",
    "nation",
}
BANK_FIELDS = {
    "bank",
    "bank_name",
    "bankname",
    "issuer",
    "issuer_bank",
    "bank_code",
    "bin_bank",
}

PAGE_SIZE = 8
PREVIEW_LIMIT = 30


def _candidates(kind: str) -> set[str]:
    return COUNTRY_FIELDS if kind == "country" else BANK_FIELDS


def _render_groups(kind: str, groups: list[tuple[str, int] | list]) -> str:
    title = "Countries" if kind == "country" else "Banks"
    icon = Emoji.COUNTRY if kind == "country" else Emoji.BANK
    lines = [f"{icon} <b>{title}</b>", ""]
    for entry in groups[:PREVIEW_LIMIT]:
        value, count = entry[0], entry[1]
        label = country_label(value) if kind == "country" else value
        lines.append(f"{html.escape(str(label))} — {count:,}")
    if len(groups) > PREVIEW_LIMIT:
        lines.append(f"…and {len(groups) - PREVIEW_LIMIT} more")
    hint = "/pick" if kind == "country" else "/pickbank"
    lines.extend(["", f"Tap a group below to export it, or use {hint}."])
    return "\n".join(lines)


async def start_find(reply: Message, record, tg_user: TgUser, state: FSMContext) -> None:
    await state.set_state(Flow.awaiting_text)
    await state.update_data(prompt="find_query", file_id=record.id)
    await reply.answer(f"{Emoji.SEARCH} Send the text to search for.")


async def start_group(
    reply: Message,
    record,
    tg_user: TgUser,
    state: FSMContext,
    file_manager: FileManager,
    kind: str,
) -> None:
    async with session_scope() as session:
        user = await ensure_user(session, tg_user)
        telegram_id = user.telegram_id

    path = file_manager.resolve(telegram_id, record.rel_path, create_parent=False)
    info = await asyncio.to_thread(inspect_dataset, path)

    field = detect_field(info.header, _candidates(kind))
    if field is None:
        await state.set_state(Flow.awaiting_text)
        await state.update_data(prompt=f"{kind}_field", file_id=record.id)
        await reply.answer(
            f"Which column holds the {kind}? "
            f"Send a number (1-{max(1, info.columns)})."
        )
        return

    await _finish_group(reply, path, info, field, record, state, kind)


async def finish_group_for_file(
    reply: Message,
    *,
    file_id: int,
    field_index: int,
    kind: str,
    tg_user: TgUser,
    state: FSMContext,
    file_manager: FileManager,
) -> None:
    async with session_scope() as session:
        user = await ensure_user(session, tg_user)
        record = await get_owned_file(session, user.id, file_id)
        telegram_id = user.telegram_id

    if record is None:
        await reply.answer(f"{Emoji.ERROR} File not found or expired.")
        return

    path = file_manager.resolve(telegram_id, record.rel_path, create_parent=False)
    info = await asyncio.to_thread(inspect_dataset, path)
    if field_index < 0 or field_index >= max(1, info.columns):
        await reply.answer(f"{Emoji.ERROR} Column out of range (1-{max(1, info.columns)}).")
        return

    await _finish_group(reply, path, info, field_index, record, state, kind)


async def _finish_group(
    reply: Message,
    path,
    info: DatasetInfo,
    field: int,
    record,
    state: FSMContext,
    kind: str,
) -> None:
    groups = await asyncio.to_thread(group_counts, path, info, field)
    if not groups:
        await reply.answer(f"{Emoji.ERROR} No {kind} values found in that column.")
        return

    await state.update_data(
        **{
            f"{kind}_file_id": record.id,
            f"{kind}_field": field,
            f"{kind}_groups": [list(entry) for entry in groups],
        }
    )
    await reply.answer(
        _render_groups(kind, groups),
        reply_markup=picker_keyboard(kind=kind, groups=groups, page=0, page_size=PAGE_SIZE),
    )


async def show_picker(reply: Message, state: FSMContext, kind: str) -> None:
    data = await state.get_data()
    groups = data.get(f"{kind}_groups")
    if not groups:
        command = "/country" if kind == "country" else "/bank"
        await reply.answer(
            f"{Emoji.INFO} Upload a dataset with {command} first."
        )
        return
    await reply.answer(
        _render_groups(kind, groups),
        reply_markup=picker_keyboard(kind=kind, groups=groups, page=0, page_size=PAGE_SIZE),
    )


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
@router.message(Command("find"))
async def cmd_find(message: Message, state: FSMContext) -> None:
    from bot.handlers.file_ops import prompt_for_file

    await prompt_for_file(message, state, "find")


@router.message(Command("country"))
async def cmd_country(message: Message, state: FSMContext) -> None:
    from bot.handlers.file_ops import prompt_for_file

    await prompt_for_file(message, state, "country")


@router.message(Command("bank"))
async def cmd_bank(message: Message, state: FSMContext) -> None:
    from bot.handlers.file_ops import prompt_for_file

    await prompt_for_file(message, state, "bank")


@router.message(Command("pick"))
async def cmd_pick(message: Message, state: FSMContext) -> None:
    await show_picker(message, state, "country")


@router.message(Command("pickbank"))
async def cmd_pickbank(message: Message, state: FSMContext) -> None:
    await show_picker(message, state, "bank")


# --------------------------------------------------------------------------- #
# Callbacks
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "noop")
async def on_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data.startswith("picknav:"))
async def on_pick_nav(callback: CallbackQuery, state: FSMContext) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        await callback.answer("Invalid page", show_alert=True)
        return
    kind, page = parts[1], int(parts[2])
    data = await state.get_data()
    groups = data.get(f"{kind}_groups") or []
    if callback.message is not None:
        await callback.message.edit_reply_markup(
            reply_markup=picker_keyboard(
                kind=kind, groups=groups, page=page, page_size=PAGE_SIZE
            )
        )
    await callback.answer()


@router.callback_query(F.data.startswith("pick:"))
async def on_pick(callback: CallbackQuery, state: FSMContext, job_manager: JobManager) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        await callback.answer("Invalid selection", show_alert=True)
        return
    kind, index = parts[1], int(parts[2])
    data = await state.get_data()
    groups = data.get(f"{kind}_groups") or []
    file_id = data.get(f"{kind}_file_id")
    field = data.get(f"{kind}_field")

    if not groups or file_id is None or not (0 <= index < len(groups)):
        await callback.answer("Selection expired. Run the command again.", show_alert=True)
        return

    value = groups[index][0]
    job_kind = JobKind.PICK if kind == "country" else JobKind.PICKBANK
    if callback.message is not None:
        await start_job(
            callback.message,
            job_manager,
            tg_user=callback.from_user,
            kind=job_kind,
            input_file_id=int(file_id),
            params={"field": field, "value": value},
            label=f"Exporting {value}",
        )
    await callback.answer()
