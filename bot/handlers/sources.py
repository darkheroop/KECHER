"""Authorized Telegram sources: /scrape, /private_scrape, /myaccounts, /plogin.

Security rules enforced here:
* The bot never asks for or accepts passwords, OTPs, or session strings.
* Login happens out-of-band through Telegram's official flow (see /plogin).
* A source can only be registered if the authenticated account can already
  access it; no access-control bypasses.
"""

from __future__ import annotations

import html
from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User as TgUser

from bot.db.engine import session_scope
from bot.db.enums import AuditAction, JobKind
from bot.db.repositories import (
    add_authorized_source,
    get_authorized_source,
    list_authorized_sources,
    record_audit,
)
from bot.handlers.common import ensure_user, start_job
from bot.handlers.states import Flow
from bot.jobs.manager import JobManager
from bot.services.scraper import is_scraper_available
from bot.ui.emoji import Emoji
from bot.ui.keyboards import scrape_options_keyboard, sources_keyboard

router = Router(name="sources")

PLOGIN_TEXT = (
    f"{Emoji.LOGIN} <b>Connecting an authorized account</b>\n\n"
    "For your security, the bot will <b>never</b> ask for your Telegram "
    "password, login code (OTP), or session string. Do not send them here.\n\n"
    "Authentication uses Telegram's official mechanism and happens in your "
    "own terminal:\n\n"
    "1. Create API credentials at https://my.telegram.org and put "
    "<code>TELEGRAM_API_ID</code> / <code>TELEGRAM_API_HASH</code> in your "
    "<code>.env</code>.\n"
    "2. Run: <code>python -m bot.tools.plogin &lt;label&gt;</code>\n"
    "3. Enter your phone number and the login code in the terminal.\n\n"
    f"{Emoji.SECURITY} Only groups/channels your account can already access "
    "can be scraped."
)

DEFAULT_LIMIT = 100
DEFAULT_FORMAT = "txt"


async def _accounts_text(scraper) -> str:  # noqa: ANN001
    if not is_scraper_available():
        return (
            f"{Emoji.ACCOUNT} <b>Authorized accounts</b>\n\n"
            "Telethon is not installed, so no user-account is configured.\n\n"
            "Install it and run <code>python -m bot.tools.plogin &lt;label&gt;</code>."
        )
    accounts = scraper.registry.accounts()
    if not accounts:
        return (
            f"{Emoji.ACCOUNT} <b>Authorized accounts</b>\n\n"
            "No accounts configured. See /plogin."
        )
    lines = [f"{Emoji.ACCOUNT} <b>Authorized accounts</b>", ""]
    for index, account in enumerate(accounts, start=1):
        lines.append(f"<b>Account {index}</b> — {account.label}")
        lines.append(f"Status: {scraper.registry.status(account)}")
        lines.append("")
    return "\n".join(lines).rstrip()


async def _list_sources(
    reply: Message,
    tg_user: TgUser,
    *,
    kinds: set[str],
    private: bool,
) -> None:
    async with session_scope() as session:
        user = await ensure_user(session, tg_user)
        sources = [
            source
            for source in await list_authorized_sources(session, user.id)
            if source.kind in kinds
        ]

    title = "Private sources" if private else "Authorized sources"
    if not sources:
        await reply.answer(
            f"{Emoji.SCRAPE} <b>{title}</b>\n\n"
            "No sources registered yet.\n\n"
            "Add one with its @username or link, e.g.\n"
            f"<code>{'/private_scrape' if private else '/scrape'} @mygroup</code>\n\n"
            f"{Emoji.SECURITY} Only sources your account can already access are allowed.",
        )
        return

    await reply.answer(
        f"{Emoji.SCRAPE} <b>{title}</b>\n\nSelect a source:",
        reply_markup=sources_keyboard(
            [(source.id, source.title or source.tg_peer_ref) for source in sources]
        ),
    )


async def _add_source(
    reply: Message,
    tg_user: TgUser,
    scraper,  # noqa: ANN001
    peer_ref: str,
    *,
    kind: str,
) -> None:
    if not is_scraper_available() or scraper is None or not scraper.available():
        await reply.answer(
            f"{Emoji.ERROR} No Telegram account is configured, so access cannot "
            "be verified. See /plogin.",
        )
        return

    accounts = scraper.registry.accounts()
    label = next((a.label for a in accounts if a.enabled), None)
    if label is None:
        await reply.answer(f"{Emoji.ERROR} No enabled account. See /plogin.")
        return

    try:
        title = await scraper.verify_source(label, peer_ref)
    except Exception as exc:  # noqa: BLE001 - surface a clean message
        await reply.answer(f"{Emoji.ERROR} Could not verify access: {exc}")
        return

    if not title:
        await reply.answer(
            f"{Emoji.SECURITY} The account cannot access <code>{peer_ref}</code>. "
            "Joining or bypassing access restrictions is not supported.",
        )
        return

    async with session_scope() as session:
        user = await ensure_user(session, tg_user)
        source = await add_authorized_source(
            session, user_id=user.id, tg_peer_ref=peer_ref, title=title, kind=kind
        )
        await record_audit(
            session,
            user_id=user.id,
            action=AuditAction.SOURCE_ADDED,
            detail={"kind": kind, "title": title},
        )
        source_id = source.id

    await reply.answer(
        f"{Emoji.SUCCESS} Source added: <b>{title}</b>\n\nUse it now:",
        reply_markup=sources_keyboard([(source_id, title)]),
    )


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
@router.message(Command("plogin"))
async def cmd_plogin(message: Message) -> None:
    await message.answer(PLOGIN_TEXT)


@router.message(Command("myaccounts"))
async def cmd_myaccounts(message: Message, scraper) -> None:  # noqa: ANN001
    await message.answer(await _accounts_text(scraper))


@router.message(Command("scrape"))
async def cmd_scrape(message: Message, scraper) -> None:  # noqa: ANN001
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) == 2 and parts[1].strip():
        assert message.from_user is not None
        await _add_source(message, message.from_user, scraper, parts[1].strip(), kind="group")
        return
    assert message.from_user is not None
    await _list_sources(
        message, message.from_user, kinds={"group", "channel"}, private=False
    )


@router.message(Command("private_scrape"))
async def cmd_private_scrape(message: Message, scraper) -> None:  # noqa: ANN001
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) == 2 and parts[1].strip():
        assert message.from_user is not None
        await _add_source(
            message, message.from_user, scraper, parts[1].strip(), kind="private"
        )
        return
    assert message.from_user is not None
    await _list_sources(message, message.from_user, kinds={"private"}, private=True)


# --------------------------------------------------------------------------- #
# Source selection & options
# --------------------------------------------------------------------------- #
def _render_options(data: dict, title: str) -> str:
    dates = "not set"
    if data.get("date_from") or data.get("date_to"):
        dates = f"{data.get('date_from') or '…'} → {data.get('date_to') or '…'}"
    media = "included" if data.get("include_media") else "excluded"
    return (
        f"{Emoji.SCRAPE} <b>Scrape options</b>\n\n"
        f"Source: <b>{html.escape(title)}</b>\n"
        f"Limit: {data.get('limit', DEFAULT_LIMIT)}\n"
        f"Format: {str(data.get('format', DEFAULT_FORMAT)).upper()}\n"
        f"Media: {media}\n"
        f"Dates: {dates}"
    )


def _options_keyboard(data: dict):
    return scrape_options_keyboard(
        limit=int(data.get("limit", DEFAULT_LIMIT)),
        fmt=str(data.get("format", DEFAULT_FORMAT)),
        include_media=bool(data.get("include_media", False)),
        has_dates=bool(data.get("date_from") or data.get("date_to")),
    )


@router.callback_query(F.data.startswith("scr:src:"))
async def on_source_selected(callback: CallbackQuery, state: FSMContext) -> None:
    raw = (callback.data or "").rsplit(":", 1)[-1]
    if not raw.isdigit():
        await callback.answer("Invalid source", show_alert=True)
        return

    async with session_scope() as session:
        user = await ensure_user(session, callback.from_user)
        source = await get_authorized_source(session, user.id, int(raw))
        title = (source.title or source.tg_peer_ref) if source else None

    if source is None:
        await callback.answer("Source not found", show_alert=True)
        return

    await state.update_data(
        scr_source=int(raw),
        limit=DEFAULT_LIMIT,
        format=DEFAULT_FORMAT,
        include_media=False,
        date_from=None,
        date_to=None,
    )
    data = await state.get_data()
    if callback.message is not None:
        await callback.message.edit_text(
            _render_options(data, title), reply_markup=_options_keyboard(data)
        )
    await callback.answer()


@router.callback_query(F.data.startswith("scr:limit:"))
async def on_limit(callback: CallbackQuery, state: FSMContext) -> None:
    value = (callback.data or "").rsplit(":", 1)[-1]
    if not value.isdigit():
        await callback.answer("Invalid limit", show_alert=True)
        return
    await state.update_data(limit=int(value))
    data = await state.get_data()
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=_options_keyboard(data))
    await callback.answer()


@router.callback_query(F.data.startswith("scr:fmt:"))
async def on_format(callback: CallbackQuery, state: FSMContext) -> None:
    value = (callback.data or "").rsplit(":", 1)[-1]
    if value not in {"txt", "csv", "json"}:
        await callback.answer("Invalid format", show_alert=True)
        return
    await state.update_data(format=value)
    data = await state.get_data()
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=_options_keyboard(data))
    await callback.answer()


@router.callback_query(F.data.startswith("scr:media:"))
async def on_media(callback: CallbackQuery, state: FSMContext) -> None:
    value = (callback.data or "").rsplit(":", 1)[-1]
    await state.update_data(include_media=value == "1")
    data = await state.get_data()
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=_options_keyboard(data))
    await callback.answer()


@router.callback_query(F.data == "scr:dates")
async def on_dates_button(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Flow.awaiting_dates)
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            "Send a date range as <code>YYYY-MM-DD..YYYY-MM-DD</code> "
            "or send <code>clear</code> to remove it."
        )


@router.message(Flow.awaiting_dates)
async def on_dates_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if text.lower() in {"clear", "none", "-", ""}:
        await state.set_state(None)
        await state.update_data(date_from=None, date_to=None)
        await message.answer(f"{Emoji.SUCCESS} Date range cleared.")
        return

    try:
        start_text, _, end_text = text.partition("..")
        date_from = _parse_date(start_text)
        date_to = _parse_date(end_text) if end_text else None
        if date_from is None and date_to is None:
            raise ValueError("no dates")
    except ValueError:
        await message.answer(f"{Emoji.ERROR} Use <code>YYYY-MM-DD..YYYY-MM-DD</code>.")
        return

    await state.set_state(None)
    await state.update_data(
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
    )
    await message.answer(f"{Emoji.SUCCESS} Date range saved.")


def _parse_date(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(value) from exc
    return parsed.replace(tzinfo=UTC)


@router.callback_query(F.data == "scr:run")
async def on_run(callback: CallbackQuery, state: FSMContext, job_manager: JobManager, scraper) -> None:  # noqa: ANN001
    data = await state.get_data()
    source_id = data.get("scr_source")
    if not source_id:
        await callback.answer("Select a source first", show_alert=True)
        return

    async with session_scope() as session:
        user = await ensure_user(session, callback.from_user)
        source = await get_authorized_source(session, user.id, int(source_id))
        if source is None:
            await callback.answer("Source not found", show_alert=True)
            return
        peer = source.tg_peer_ref

    label = ""
    if scraper is not None and hasattr(scraper, "registry"):
        account = next(
            (a for a in scraper.registry.accounts() if a.enabled), None
        )
        label = account.label if account else ""

    params = {
        "account": label,
        "peer": peer,
        "limit": int(data.get("limit", DEFAULT_LIMIT)),
        "format": str(data.get("format", DEFAULT_FORMAT)),
        "include_media": bool(data.get("include_media", False)),
        "date_from": data.get("date_from"),
        "date_to": data.get("date_to"),
    }

    await state.update_data(scr_source=None)
    if callback.message is not None:
        await start_job(
            callback.message,
            job_manager,
            tg_user=callback.from_user,
            kind=JobKind.SCRAPE,
            input_file_id=None,
            params=params,
            label="Collecting messages",
        )
    await callback.answer()
