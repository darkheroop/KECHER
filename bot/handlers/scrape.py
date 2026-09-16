"""Authorized per-user scraping from groups/channels (Telethon) with buttons."""

from __future__ import annotations

import asyncio
import contextlib
import html
from datetime import UTC, datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import Settings
from bot.db.engine import session_scope
from bot.db.repositories import (
    add_authorized_source,
    create_file,
    get_authorized_source,
    get_user_settings,
    list_authorized_sources,
    remove_authorized_source,
)
from bot.handlers.cards import _send_file
from bot.handlers.common import ensure_user
from bot.handlers.states import Flow
from bot.security.access import is_admin
from bot.services.cards import clean_cards
from bot.services.file_manager import FileManager
from bot.services.scraper import ScrapeOptions, is_scraper_available
from bot.ui.emoji import Emoji
from bot.ui.keyboards import account_help, api_setup, scrape_panel, scrape_sources
from bot.ui.render import safe_edit

router = Router(name="scrape")

DIVIDER = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"

HELP_INTRO = (
    f"{Emoji.SCRAPE} <b>Scrape</b>\n{DIVIDER}\n"
    "Collect messages from a group/channel you belong to, filter by keyword(s), "
    "export to a .txt and clean it — automatically.\n\n"
    "For this you connect <b>your own</b> Telegram account (a bot can't read history)."
)

HOW_IT_WORKS = (
    f"{Emoji.LOGIN} <b>Connecting your account</b>\n{DIVIDER}\n"
    "<b>1.</b> Get API credentials at <b>https://my.telegram.org</b> → "
    "API development tools (<i>api_id</i>, <i>api_hash</i>).\n"
    "<b>2.</b> The bot owner sets them once in the server environment.\n"
    "<b>3.</b> Tap <b>Connect my account</b> and send your phone number.\n"
    "<b>4.</b> Telegram sends you a login code — send it here, then your password "
    "if you have 2FA.\n"
    "<b>5.</b> Done — a session is stored on the server and used only for scraping.\n\n"
    f"{Emoji.WARNING} The code/password are used once to create the session and are "
    "never stored or logged. Delete those messages after connecting."
)

DEFAULT_STATE = {
    "limit": 100,
    "mode": "messages",
    "autoclean": True,
    "dates": "none",
    "keywords": [],
    "include_media": False,
}


def _api_ready(scraper, settings: Settings) -> bool:  # noqa: ANN001
    if not is_scraper_available() or scraper is None:
        return False
    try:
        return bool(scraper.available())
    except Exception:  # noqa: BLE001
        return False


async def _load_sc(state: FSMContext) -> dict:
    data = await state.get_data()
    sc = dict(data.get("sc") or {})
    for key, value in DEFAULT_STATE.items():
        sc.setdefault(key, value)
    return sc


async def _save_sc(state: FSMContext, sc: dict) -> None:
    await state.update_data(sc=sc)


def _panel_text(sc: dict, title: str) -> str:
    keywords = ", ".join(sc.get("keywords") or []) or "any"
    limit = sc.get("limit", 100)
    mode = "Cards" if sc.get("mode") == "cards" else "Messages"
    autoclean = "on" if sc.get("autoclean") else "off"
    media = "on" if sc.get("include_media") else "off"
    dates = {"none": "all", "7": "7d", "30": "30d", "custom": "custom"}.get(
        sc.get("dates", "none"), "all"
    )
    return (
        f"{Emoji.SCRAPE} <b>Scrape</b>\n{DIVIDER}\n"
        f"Source · <b>{html.escape(title)}</b>\n"
        f"Keywords · <b>{html.escape(keywords)}</b>\n"
        f"Limit · <b>{limit or 'All'}</b>   Mode · <b>{mode}</b>\n"
        f"Dates · <b>{dates}</b>   Media · <b>{media}</b>\n"
        f"Auto-clean · <b>{autoclean}</b>"
    )


async def _scrape_entry(reply: Message, tg_user, state: FSMContext, scraper, settings: Settings) -> None:  # noqa: ANN001
    await state.update_data(sc={})
    if not is_scraper_available():
        await reply.answer(
            f"{Emoji.ERROR} Scraping isn't enabled on this server yet.", reply_markup=account_help()
        )
        return
    if not _api_ready(scraper, settings):
        async with session_scope() as session:
            user = await ensure_user(session, tg_user)
            admin = is_admin(user, settings)
        if admin:
            await reply.answer(
                f"{Emoji.LOCK} <b>Scraping setup</b>\n{DIVIDER}\n"
                "No Telegram API credentials yet. Set them here (no server access "
                "needed) — you only need <b>api_id</b> and <b>api_hash</b> from "
                "<b>https://my.telegram.org</b>.",
                reply_markup=api_setup(),
            )
        else:
            await reply.answer(
                f"{Emoji.LOCK} Scraping isn't available yet.\n\n"
                "Ask an admin to enable it.",
                reply_markup=account_help(),
            )
        return
    if not scraper.user_connected(tg_user.id):
        await reply.answer(
            f"{Emoji.LOGIN} <b>Connect your account to scrape</b>\n{DIVIDER}\n"
            "Tap below and follow the 3 steps (phone → code → password).",
            reply_markup=account_help(),
        )
        return
    async with session_scope() as session:
        user = await ensure_user(session, tg_user)
        sources = await list_authorized_sources(session, user.id)
    await reply.answer(
        f"{Emoji.SCRAPE} <b>Scrape</b>\n\nConnected ✅ — choose a source, or add one:",
        reply_markup=scrape_sources([(s.id, s.title or s.tg_peer_ref) for s in sources]),
    )


@router.message(Command("scrape"))
async def cmd_scrape(message: Message, state: FSMContext, scraper, settings: Settings) -> None:  # noqa: ANN001
    assert message.from_user is not None
    await _scrape_entry(message, message.from_user, state, scraper, settings)


@router.callback_query(F.data == "menu:scrape")
async def menu_scrape(callback: CallbackQuery, state: FSMContext, scraper, settings: Settings) -> None:  # noqa: ANN001
    if callback.message is not None:
        await _scrape_entry(callback.message, callback.from_user, state, scraper, settings)
    await callback.answer()


@router.message(Command("plogin"))
async def cmd_plogin(message: Message) -> None:
    await message.answer(HOW_IT_WORKS, reply_markup=account_help())


@router.message(Command("myaccounts"))
async def cmd_myaccounts(message: Message, scraper) -> None:  # noqa: ANN001
    assert message.from_user is not None
    account = scraper.user_account(message.from_user.id) if scraper else None
    if account is None:
        await message.answer(
            f"{Emoji.ACCOUNT} No account connected.\n\nConnect one to start scraping.",
            reply_markup=account_help(),
        )
        return
    status = scraper.registry.status(account)
    await message.answer(
        f"{Emoji.ACCOUNT} <b>Your account</b>\n{DIVIDER}\n"
        f"<b>{account.label}</b> · {status}",
        reply_markup=account_help() if status != "Connected" else None,
    )


@router.callback_query(F.data == "scr:helptext")
async def scr_help(callback: CallbackQuery) -> None:
    await safe_edit(callback.message, HOW_IT_WORKS, reply_markup=account_help())
    await callback.answer()


@router.callback_query(F.data == "scr:cancel")
async def scr_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_edit(callback.message, f"{Emoji.CANCEL} Cancelled.", reply_markup=None)
    await callback.answer()


# --------------------------------------------------------------------------- #
# Account login (per user)
# --------------------------------------------------------------------------- #
async def _delete_sensitive(message: Message) -> None:
    with contextlib.suppress(Exception):
        await message.delete()


@router.callback_query(F.data == "scr:login")
async def scr_login(callback: CallbackQuery, state: FSMContext, scraper, settings: Settings) -> None:  # noqa: ANN001
    if not _api_ready(scraper, settings):
        await callback.answer("Server API credentials are not set.", show_alert=True)
        return
    await state.set_state(Flow.awaiting_phone)
    await safe_edit(
        callback.message,
        f"{Emoji.LOGIN} Send your phone number in international format, e.g. "
        "<code>+919876543210</code>.\n\n"
        f"{Emoji.WARNING} Delete it after — it's used once to log you in.",
    )
    await callback.answer()


@router.message(Flow.awaiting_phone)
async def on_phone(message: Message, state: FSMContext, scraper) -> None:  # noqa: ANN001
    phone = (message.text or "").strip().replace(" ", "")
    await _delete_sensitive(message)
    assert message.from_user is not None
    if not phone.startswith("+") or not phone[1:].isdigit():
        await message.answer("Send it as <code>+countrycode…</code>, e.g. <code>+919876543210</code>.")
        return
    status = await message.answer(f"{Emoji.LOGIN} Sending a login code to Telegram…")
    try:
        await scraper.start_login(owner=message.from_user.id, phone=phone)
    except Exception as exc:  # noqa: BLE001
        await safe_edit(status, f"{Emoji.ERROR} Could not start login: <code>{type(exc).__name__}</code>")
        return
    await state.set_state(Flow.awaiting_code)
    await safe_edit(
        status,
        f"{Emoji.KEY} <b>Enter the login code</b> Telegram sent you.\n\n"
        f"{Emoji.WARNING} I use it once to create your session, then it's gone. "
        "Delete the message after.",
    )


@router.message(Flow.awaiting_code)
async def on_code(message: Message, state: FSMContext, scraper) -> None:  # noqa: ANN001
    code = (message.text or "").strip()
    await _delete_sensitive(message)
    assert message.from_user is not None
    status = await message.answer(f"{Emoji.PROGRESS} Checking the code…")
    result = await scraper.confirm_code(owner=message.from_user.id, code=code)
    if result == "password":
        await state.set_state(Flow.awaiting_password)
        await safe_edit(status, f"{Emoji.KEY} Two-step password enabled — send your <b>password</b>.")
        return
    if result == "ok":
        await state.clear()
        await safe_edit(status, f"{Emoji.SUCCESS} Account connected ✅ — now open /scrape.")
        return
    if result == "expired":
        await state.clear()
        await safe_edit(status, f"{Emoji.ERROR} Login expired. Tap Connect again.")
        return
    await safe_edit(status, f"{Emoji.ERROR} Login failed: <code>{html.escape(result)}</code>")


@router.message(Flow.awaiting_password)
async def on_password(message: Message, state: FSMContext, scraper) -> None:  # noqa: ANN001
    password = (message.text or "").strip()
    await _delete_sensitive(message)
    assert message.from_user is not None
    status = await message.answer(f"{Emoji.PROGRESS} Verifying…")
    result = await scraper.confirm_password(owner=message.from_user.id, password=password)
    await state.clear()
    if result == "ok":
        await safe_edit(status, f"{Emoji.SUCCESS} Account connected ✅ — now open /scrape.")
    else:
        await safe_edit(status, f"{Emoji.ERROR} Failed: <code>{html.escape(result)}</code>")


# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "scr:add")
async def scr_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Flow.awaiting_source)
    await safe_edit(
        callback.message,
        f"{Emoji.SCRAPE} Send the source as <code>@username</code> or a numeric "
        "<code>-100…</code> id (public, or a group/channel you belong to).",
    )
    await callback.answer()


@router.message(Flow.awaiting_source)
async def on_source_text(message: Message, state: FSMContext, scraper) -> None:  # noqa: ANN001
    peer = (message.text or "").strip()
    tg_user = message.from_user
    assert tg_user is not None
    if not peer:
        await message.answer("Send <code>@username</code> or <code>-100…</code>.")
        return
    if not scraper.user_connected(tg_user.id):
        await message.answer(f"{Emoji.ERROR} Connect your account first (/scrape).")
        return
    label = scraper.label_for(tg_user.id)
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
# Options
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
    await safe_edit(callback.message, _panel_text(sc, title), reply_markup=scrape_panel(sc))
    await callback.answer()


@router.callback_query(F.data == "scr:kw")
async def scr_keywords(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Flow.awaiting_keywords)
    await safe_edit(
        callback.message,
        f"{Emoji.FIND} Send keyword(s), comma-separated (case-insensitive).\n"
        "Example: <code>invoice, promo, 411111</code>",
    )
    await callback.answer()


@router.message(Flow.awaiting_keywords)
async def on_keywords_text(message: Message, state: FSMContext) -> None:
    words = [w.strip() for w in (message.text or "").replace(";", ",").split(",")]
    sc = await _load_sc(state)
    sc["keywords"] = [w for w in words if w]
    await _save_sc(state, sc)
    await state.set_state(None)
    await message.answer(_panel_text(sc, sc.get("source_title", "")), reply_markup=scrape_panel(sc))


@router.callback_query(F.data.startswith("scr:limit:"))
async def scr_limit(callback: CallbackQuery, state: FSMContext) -> None:
    sc = await _load_sc(state)
    sc["limit"] = int((callback.data or "").rsplit(":", 1)[-1])
    await _save_sc(state, sc)
    await safe_edit(callback.message, _panel_text(sc, sc.get("source_title", "")), reply_markup=scrape_panel(sc))
    await callback.answer()


@router.callback_query(F.data.startswith("scr:mode:"))
async def scr_mode(callback: CallbackQuery, state: FSMContext) -> None:
    sc = await _load_sc(state)
    sc["mode"] = "cards" if (callback.data or "").endswith("cards") else "messages"
    await _save_sc(state, sc)
    await safe_edit(callback.message, _panel_text(sc, sc.get("source_title", "")), reply_markup=scrape_panel(sc))
    await callback.answer()


@router.callback_query(F.data == "scr:autoclean")
async def scr_autoclean(callback: CallbackQuery, state: FSMContext) -> None:
    sc = await _load_sc(state)
    sc["autoclean"] = not sc.get("autoclean", True)
    await _save_sc(state, sc)
    await safe_edit(callback.message, _panel_text(sc, sc.get("source_title", "")), reply_markup=scrape_panel(sc))
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
    await safe_edit(callback.message, _panel_text(sc, sc.get("source_title", "")), reply_markup=scrape_panel(sc))
    await callback.answer()


@router.message(Flow.awaiting_scrape_dates)
async def on_scrape_dates(message: Message, state: FSMContext) -> None:
    start, _, end = (message.text or "").strip().partition("..")
    sc = await _load_sc(state)
    sc["dates"] = "custom"
    sc["date_from"] = start.strip() or None
    sc["date_to"] = end.strip() or None
    await _save_sc(state, sc)
    await state.set_state(None)
    await message.answer(_panel_text(sc, sc.get("source_title", "")), reply_markup=scrape_panel(sc))


@router.callback_query(F.data == "scr:sources")
async def scr_sources_manage(callback: CallbackQuery, state: FSMContext) -> None:
    async with session_scope() as session:
        user = await ensure_user(session, callback.from_user)
        sources = await list_authorized_sources(session, user.id)
    await safe_edit(
        callback.message,
        f"{Emoji.SCRAPE} <b>Your sources</b>\n\nTap a source to remove it:",
        reply_markup=scrape_sources(
            [(s.id, s.title or s.tg_peer_ref) for s in sources], manage=True
        ),
    )
    await callback.answer()


@router.callback_query(F.data == "scr:back")
async def scr_sources_back(callback: CallbackQuery, state: FSMContext) -> None:
    async with session_scope() as session:
        user = await ensure_user(session, callback.from_user)
        sources = await list_authorized_sources(session, user.id)
    await safe_edit(
        callback.message,
        f"{Emoji.SCRAPE} Choose a source, or add one:",
        reply_markup=scrape_sources(
            [(s.id, s.title or s.tg_peer_ref) for s in sources]
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("scr:delsrc:"))
async def scr_del_source(callback: CallbackQuery, state: FSMContext) -> None:
    raw = (callback.data or "").rsplit(":", 1)[-1]
    if raw.isdigit():
        async with session_scope() as session:
            user = await ensure_user(session, callback.from_user)
            await remove_authorized_source(session, user.id, int(raw))
            sources = await list_authorized_sources(session, user.id)
    else:
        sources = []
    await safe_edit(
        callback.message,
        f"{Emoji.SCRAPE} <b>Your sources</b>\n\nRemove another, or add a new one:",
        reply_markup=scrape_sources(
            [(s.id, s.title or s.tg_peer_ref) for s in sources], manage=True
        ),
    )
    await callback.answer("Removed")


@router.callback_query(F.data == "scr:limitcustom")
async def scr_limit_custom(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Flow.awaiting_limit)
    await safe_edit(
        callback.message, "Send the maximum number of messages to scan (e.g. <b>2000</b>)."
    )
    await callback.answer()


@router.message(Flow.awaiting_limit)
async def on_limit_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("Send a whole number.")
        return
    sc = await _load_sc(state)
    sc["limit"] = int(text)
    await _save_sc(state, sc)
    await state.set_state(None)
    await message.answer(_panel_text(sc, sc.get("source_title", "")), reply_markup=scrape_panel(sc))


@router.callback_query(F.data == "scr:media")
async def scr_media(callback: CallbackQuery, state: FSMContext) -> None:
    sc = await _load_sc(state)
    sc["include_media"] = not sc.get("include_media", False)
    await _save_sc(state, sc)
    await safe_edit(callback.message, _panel_text(sc, sc.get("source_title", "")), reply_markup=scrape_panel(sc))
    await callback.answer()


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
    tg_user = callback.from_user
    if not sc.get("source_id"):
        await callback.answer("Pick a source first", show_alert=True)
        return
    if not scraper.user_connected(tg_user.id):
        await callback.answer("Connect your account first.", show_alert=True)
        return

    label = scraper.label_for(tg_user.id)
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
        include_media=bool(sc.get("include_media")),
    )
    try:
        result = await scraper.scrape(
            label=label, peer_ref=source.tg_peer_ref, out=raw.path, options=options, fmt="txt"
        )
    except Exception as exc:  # noqa: BLE001
        await safe_edit(status, f"{Emoji.ERROR} Scrape failed: <code>{type(exc).__name__}</code>")
        return

    final_path = raw.path
    extra = ""
    if sc.get("mode") == "cards" or sc.get("autoclean", True):
        cleaned = file_manager.allocate(telegram_id, f"{label_name} Cleaned.txt", subdir="out")
        report = await asyncio.to_thread(clean_cards, raw.path, cleaned.path)
        final_path = cleaned.path
        extra = f"\n✅ {report.valid:,} valid records"

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
        f"Scanned {result.scanned:,} · matched {result.exported:,}{extra}",
    )
    await _send_file(
        callback.message,
        stored.path,
        stored.safe_name,
        f"{Emoji.SCRAPE} {label_name}\n{result.exported:,} message(s)",
    )
    await state.clear()
