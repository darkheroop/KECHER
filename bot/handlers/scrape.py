"""Authorized scraping from groups/channels (Telethon) with a button UI."""

from __future__ import annotations

import asyncio
import html
from datetime import UTC, datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from bot.config import Settings
from bot.db.engine import session_scope
from bot.db.repositories import (
    add_authorized_source,
    create_file,
    get_authorized_source,
    get_user_settings,
    list_authorized_sources,
)
from bot.handlers.cards import _send_file, _tag
from bot.handlers.common import ensure_user
from bot.handlers.states import Flow
from bot.security.access import is_admin
from bot.services.cards import clean_cards, count_lines
from bot.services.file_manager import FileManager
from bot.services.scraper import ScrapeOptions, is_scraper_available
from bot.ui.emoji import Emoji
from bot.ui.keyboards import account_help, scrape_panel, scrape_sources
from bot.ui.render import safe_edit

router = Router(name="scrape")

PLOGIN_GUIDE = (
    f"{Emoji.LOGIN} <b>Connect a private account</b>\n\n"
    "Scraping needs a Telegram <b>user account</b> (a bot can't read history). "
    "Do this once, in your own terminal — never send credentials here.\n\n"
    "<b>1.</b> Go to <b>https://my.telegram.org</b> → API development tools\n"
    "     and copy your <b>api_id</b> and <b>api_hash</b>.\n"
    "<b>2.</b> Put them in your environment:\n"
    "     <code>TELEGRAM_API_ID=…</code>\n"
    "     <code>TELEGRAM_API_HASH=…</code>\n"
    "<b>3.</b> In a terminal run:\n"
    "     <code>python -m bot.tools.plogin main</code>\n"
    "     Enter your phone number and the login code there.\n"
    "<b>4.</b> Come back and send /myaccounts — it should show <b>Connected</b>.\n\n"
    f"{Emoji.SECURITY} The account must already be a member of the source."
)

DEFAULT_STATE = {
    "limit": 100,
    "mode": "messages",
    "autoclean": True,
    "dates": "none",
    "keywords": [],
}


async def _accounts(scraper) -> list:  # noqa: ANN001
    return scraper.registry.accounts() if scraper and hasattr(scraper, "registry") else []


def _ready(scraper, settings: Settings) -> bool:  # noqa: ANN001
    if not is_scraper_available() or scraper is None:
        return False
    try:
        return bool(scraper.available())
    except Exception:  # noqa: BLE001
        return False


async def _source_list(user_id: int, kinds: set[str] | None = None) -> list:
    async with session_scope() as session:
        sources = await list_authorized_sources(session, user_id)
    if kinds is not None:
        sources = [s for s in sources if s.kind in kinds]
    return sources


async def _panel_text(sc, source_title: str) -> str:  # noqa: ANN001
    keywords = ", ".join(sc.get("keywords") or []) or "any"
    limit = sc.get("limit", 100)
    mode = "Cards" if sc.get("mode") == "cards" else "Messages"
    autoclean = "on" if sc.get("autoclean") else "off"
    dates = {"none": "all", "7": "last 7d", "30": "last 30d", "custom": "custom"}.get(
        sc.get("dates", "none"), "all"
    )
    return (
        f"{Emoji.SCRAPE} <b>Scrape</b>\n{DIVIDER}\n"
        f"Source · <b>{html.escape(source_title)}</b>\n"
        f"Keywords · <b>{html.escape(keywords)}</b>\n"
        f"Limit · <b>{limit if limit else 'All'}</b>   Mode · <b>{mode}</b>\n"
        f"Dates · <b>{dates}</b>   Auto-clean · <b>{autoclean}</b>"
    )


DIVIDER = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"


async def _load_sc(state: FSMContext) -> dict:
    data = await state.get_data()
    sc = dict(data.get("sc") or {})
    for key, value in DEFAULT_STATE.items():
        sc.setdefault(key, value)
    return sc


async def _save_sc(state: FSMContext, sc: dict) -> None:
    await state.update_data(sc=sc)


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #
@router.message(Command("scrape"))
async def cmd_scrape(message: Message, state: FSMContext, scraper, settings: Settings) -> None:  # noqa: ANN001
    if not _ready(scraper, settings):
        await message.answer(PLOGIN_GUIDE, reply_markup=account_help())
        return
    tg_user = message.from_user
    assert tg_user is not None
    async with session_scope() as session:
        user = await ensure_user(session, tg_user)
        user_id = user.id
    sources = await _source_list(user_id)
    await state.update_data(sc={})
    await message.answer(
        f"{Emoji.SCRAPE} <b>Scrape</b>\n\nChoose a source, or add one:",
        reply_markup=scrape_sources([(s.id, s.title or s.tg_peer_ref) for s in sources]),
    )


@router.message(Command("plogin"))
async def cmd_plogin(message: Message) -> None:
    await message.answer(PLOGIN_GUIDE, reply_markup=account_help())


@router.message(Command("myaccounts"))
async def cmd_myaccounts(message: Message, scraper) -> None:  # noqa: ANN001
    accounts = await _accounts(scraper)
    if not accounts:
        await message.answer(
            f"{Emoji.ACCOUNT} No account connected.\n\nSee /plogin.",
            reply_markup=account_help(),
        )
        return
    lines = [f"{Emoji.ACCOUNT} <b>Authorized accounts</b>", ""]
    for index, account in enumerate(accounts, start=1):
        status = scraper.registry.status(account)
        lines.append(f"{index}. <b>{account.label}</b> · {status}")
    await message.answer("\n".join(lines))


@router.callback_query(F.data == "scr:help")
async def scr_help(callback: CallbackQuery) -> None:
    await safe_edit(callback.message, PLOGIN_GUIDE, reply_markup=account_help())
    await callback.answer()


@router.callback_query(F.data == "scr:cancel")
async def scr_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_edit(callback.message, f"{Emoji.CANCEL} Cancelled.", reply_markup=None)
    await callback.answer()


# --------------------------------------------------------------------------- #
# Add source
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "scr:add")
async def scr_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Flow.awaiting_source)
    await safe_edit(
        callback.message,
        f"{Emoji.SCRAPE} Send the source as <code>@username</code> or a numeric "
        "<code>-100…</code> id.\n\nIt must be a public channel or a group/channel "
        "you already belong to.",
    )
    await callback.answer()


@router.message(Flow.awaiting_source)
async def on_source_text(message: Message, state: FSMContext, scraper, settings: Settings) -> None:  # noqa: ANN001
    peer = (message.text or "").strip()
    tg_user = message.from_user
    assert tg_user is not None
    if not peer:
        await message.answer("Send <code>@username</code> or <code>-100…</code>.")
        return
    accounts = await _accounts(scraper)
    label = next((a.label for a in accounts if a.enabled), None)
    if label is None:
        await message.answer(f"{Emoji.ERROR} No connected account. See /plogin.")
        return
    status = await message.answer(f"{Emoji.SCRAPE} Verifying access to {html.escape(peer)}…")
    try:
        title = await scraper.verify_source(label, peer)
    except Exception as exc:  # noqa: BLE001
        await safe_edit(status, f"{Emoji.ERROR} Could not verify: <code>{type(exc).__name__}</code>")
        return
    if not title:
        await safe_edit(
            status,
            f"{Emoji.DENIED} The account can't access that source. "
            "Joining/bypassing access controls isn't supported.",
        )
        return
    async with session_scope() as session:
        user = await ensure_user(session, tg_user)
        source = await add_authorized_source(
            session, user_id=user.id, tg_peer_ref=peer, title=title
        )
        source_id = source.id
    await state.set_state(None)
    await safe_edit(
        status,
        f"{Emoji.SUCCESS} Source added · <b>{html.escape(title)}</b>",
        reply_markup=scrape_sources([(source_id, title)]),
    )


# --------------------------------------------------------------------------- #
# Options panel
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("scr:src:"))
async def scr_pick_source(callback: CallbackQuery, state: FSMContext) -> None:
    raw = (callback.data or "").rsplit(":", 1)[-1]
    if not raw.isdigit():
        await callback.answer("Invalid", show_alert=True)
        return
    async with session_scope() as session:
        user = await ensure_user(session, callback.from_user)
        source = await get_authorized_source(session, user.id, int(raw))
        title = (source.title or source.tg_peer_ref) if source else None
    if source is None:
        await callback.answer("Source not found", show_alert=True)
        return
    sc = await _load_sc(state)
    sc["source_id"] = int(raw)
    sc["source_title"] = title
    await _save_sc(state, sc)
    await safe_edit(callback.message, await _panel_text(sc, title), reply_markup=scrape_panel(sc))
    await callback.answer()


@router.callback_query(F.data == "scr:kw")
async def scr_keywords(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Flow.awaiting_keywords)
    await safe_edit(
        callback.message,
        f"{Emoji.FIND} Send the keyword(s), separated by commas.\n"
        "Matching is case-insensitive. Example: <code>invoice, promo, 411111</code>",
    )
    await callback.answer()


@router.message(Flow.awaiting_keywords)
async def on_keywords_text(message: Message, state: FSMContext) -> None:
    words = [w.strip() for w in (message.text or "").replace(";", ",").split(",")]
    sc = await _load_sc(state)
    sc["keywords"] = [w for w in words if w]
    await _save_sc(state, sc)
    await state.set_state(None)
    await message.answer(
        await _panel_text(sc, sc.get("source_title", "")),
        reply_markup=scrape_panel(sc),
    )


@router.callback_query(F.data.startswith("scr:limit:"))
async def scr_limit(callback: CallbackQuery, state: FSMContext) -> None:
    value = int((callback.data or "").rsplit(":", 1)[-1])
    sc = await _load_sc(state)
    sc["limit"] = value
    await _save_sc(state, sc)
    await safe_edit(callback.message, await _panel_text(sc, sc.get("source_title", "")), reply_markup=scrape_panel(sc))
    await callback.answer()


@router.callback_query(F.data.startswith("scr:mode:"))
async def scr_mode(callback: CallbackQuery, state: FSMContext) -> None:
    sc = await _load_sc(state)
    sc["mode"] = "cards" if (callback.data or "").endswith("cards") else "messages"
    await _save_sc(state, sc)
    await safe_edit(callback.message, await _panel_text(sc, sc.get("source_title", "")), reply_markup=scrape_panel(sc))
    await callback.answer()


@router.callback_query(F.data == "scr:autoclean")
async def scr_autoclean(callback: CallbackQuery, state: FSMContext) -> None:
    sc = await _load_sc(state)
    sc["autoclean"] = not sc.get("autoclean", True)
    await _save_sc(state, sc)
    await safe_edit(callback.message, await _panel_text(sc, sc.get("source_title", "")), reply_markup=scrape_panel(sc))
    await callback.answer()


@router.callback_query(F.data.startswith("scr:dates:"))
async def scr_dates(callback: CallbackQuery, state: FSMContext) -> None:
    value = (callback.data or "").rsplit(":", 1)[-1]
    sc = await _load_sc(state)
    if value == "custom":
        await state.set_state(Flow.awaiting_scrape_dates)
        await safe_edit(callback.message, "Send the range as <code>YYYY-MM-DD..YYYY-MM-DD</code>.")
        await callback.answer()
        return
    sc["dates"] = value
    await _save_sc(state, sc)
    await safe_edit(callback.message, await _panel_text(sc, sc.get("source_title", "")), reply_markup=scrape_panel(sc))
    await callback.answer()


@router.message(Flow.awaiting_scrape_dates)
async def on_scrape_dates(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    start, _, end = text.partition("..")
    sc = await _load_sc(state)
    sc["dates"] = "custom"
    sc["date_from"] = start.strip() or None
    sc["date_to"] = end.strip() or None
    await _save_sc(state, sc)
    await state.set_state(None)
    await message.answer(
        await _panel_text(sc, sc.get("source_title", "")),
        reply_markup=scrape_panel(sc),
    )


# --------------------------------------------------------------------------- #
# Run
# --------------------------------------------------------------------------- #
def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@router.callback_query(F.data == "scr:run")
async def scr_run(
    callback: CallbackQuery,
    state: FSMContext,
    scraper,  # noqa: ANN001
    file_manager: FileManager,
    settings: Settings,
) -> None:
    sc = await _load_sc(state)
    if not sc.get("source_id"):
        await callback.answer("Pick a source first", show_alert=True)
        return
    if not _ready(scraper, settings):
        await callback.answer("No account connected. See /plogin.", show_alert=True)
        return

    accounts = await _accounts(scraper)
    label = next((a.label for a in accounts if a.enabled), None)
    tg_user = callback.from_user
    async with session_scope() as session:
        user = await ensure_user(session, tg_user)
        source = await get_authorized_source(session, user.id, int(sc["source_id"]))
        user_settings = await get_user_settings(session, user.id)
    if source is None:
        await callback.answer("Source not found", show_alert=True)
        return

    keywords = sc.get("keywords") or []
    limit = int(sc.get("limit") or 0)
    dates = sc.get("dates", "none")
    now = datetime.now(UTC)
    date_from = _parse_dt(sc.get("date_from"))
    date_to = _parse_dt(sc.get("date_to"))
    if dates == "7":
        date_from = now - timedelta(days=7)
    elif dates == "30":
        date_from = now - timedelta(days=30)

    label_name = "Scrape " + ("+".join(keywords) if keywords else "all")
    telegram_id = tg_user.id
    raw = file_manager.allocate(telegram_id, f"{label_name}.txt", subdir="out")
    status = await callback.message.answer(
        f"{Emoji.SCRAPE} Scraping <b>{html.escape(source.title or source.tg_peer_ref)}</b>…"
    )
    await callback.answer()

    options = ScrapeOptions(
        limit=limit or 1_000_000,
        keywords=keywords,
        date_from=date_from,
        date_to=date_to,
        text_only=True,
    )
    try:
        result = await scraper.scrape(
            label=label,
            peer_ref=source.tg_peer_ref,
            out=raw.path,
            options=options,
            fmt="txt",
        )
    except Exception as exc:  # noqa: BLE001
        await safe_edit(status, f"{Emoji.ERROR} Scrape failed: <code>{type(exc).__name__}</code>")
        return

    final_path = raw.path
    summary_extra = ""
    if sc.get("mode") == "cards" or sc.get("autoclean", True):
        cleaned = file_manager.allocate(telegram_id, f"{label_name} Cleaned.txt", subdir="out")
        report = await asyncio.to_thread(clean_cards, raw.path, cleaned.path)
        final_path = cleaned.path
        summary_extra = f"\n✅ {report.valid:,} valid records"

    stored = file_manager.finalize_path(telegram_id, final_path)

    async with session_scope() as session:
        await create_file(
            session,
            user_id=user.id,
            original_name=stored.safe_name,
            safe_name=stored.safe_name,
            rel_path=stored.rel_path,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
            expires_at=now + timedelta(minutes=max(1, user_settings.cleanup_minutes)),
        )

    await safe_edit(
        status,
        f"{Emoji.SUCCESS} <b>Scrape complete</b>\n"
        f"Scanned {result.scanned:,} · matched {result.exported:,}{summary_extra}",
    )
    await _send_file(
        callback.message,
        stored.path,
        stored.safe_name,
        f"{Emoji.SCRAPE} {label_name}\n{result.exported:,} message(s) · {stored.size_bytes:,} bytes",
    )
    await state.clear()
