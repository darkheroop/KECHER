"""Authorized per-user scraping from groups/channels (Telethon) with buttons."""

from __future__ import annotations

import asyncio
import contextlib
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
    remove_authorized_source,
)
from bot.handlers.cards import _send_file, _tag
from bot.handlers.common import ensure_user
from bot.handlers.states import Flow
from bot.jobs.execution import run_with_progress
from bot.jobs.progress import ProgressReporter, TelegramNotifier
from bot.security.access import is_admin
from bot.services import prefs
from bot.services.cards import clean_cards, merge_files
from bot.services.file_manager import FileManager
from bot.services.scraper import ScrapeOptions, is_scraper_available
from bot.ui.emoji import Emoji
from bot.ui.keyboards import (
    account_help,
    accounts_menu,
    api_setup,
    clean_prompt,
    combine_prompt,
    defaults_menu,
    scrape_panel,
    scrape_sources,
)
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
    "selected": [],
}


async def _animate(reporter: ProgressReporter, stop: asyncio.Event, label: str) -> None:
    """Indeterminate loading bar while a blocking network step runs."""
    percent = 5
    while not stop.is_set():
        await reporter.update(percent, label=label, force=True)
        percent = min(95, percent + 6)
        try:
            await asyncio.wait_for(stop.wait(), timeout=1.2)
        except asyncio.TimeoutError:
            continue


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
    await state.update_data(sc=await prefs.load_prefs(tg_user.id))
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
        f"{Emoji.SCRAPE} <b>Scrape</b>\n{DIVIDER}\n"
        "Connected ✅ — tap one or more sources, then Continue:",
        reply_markup=scrape_sources(
            [(s.id, s.title or s.tg_peer_ref) for s in sources], selected=set()
        ),
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
    accounts = scraper.accounts_for(message.from_user.id) if scraper else []
    if not accounts:
        await message.answer(
            f"{Emoji.ACCOUNT} No account connected.\n\nConnect one to start scraping.",
            reply_markup=account_help(),
        )
        return
    active = await scraper.active_label(message.from_user.id)
    lines = [f"{Emoji.ACCOUNT} <b>Your accounts</b>", DIVIDER]
    for account in accounts:
        status = scraper.registry.status(account)
        mark = "✅" if account.label == active else "•"
        lines.append(f"{mark} <b>{account.label}</b> · {status}")
    await message.answer("\n".join(lines))


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
# Accounts
# --------------------------------------------------------------------------- #
async def _accounts_menu(scraper, owner: int) -> object:  # noqa: ANN001
    accounts = scraper.accounts_for(owner)
    active = await scraper.active_label(owner)
    pairs = [
        (a.label, scraper.registry.status(a), a.label == active) for a in accounts
    ]
    return accounts_menu(pairs)


@router.callback_query(F.data == "scr:acct")
async def scr_accounts(callback: CallbackQuery, scraper) -> None:  # noqa: ANN001
    accounts = scraper.accounts_for(callback.from_user.id)
    if not accounts:
        await safe_edit(
            callback.message,
            f"{Emoji.ACCOUNT} No accounts yet. Add one — it stays logged in.",
            reply_markup=account_help(),
        )
        await callback.answer()
        return
    await safe_edit(
        callback.message,
        f"{Emoji.ACCOUNT} <b>Your accounts</b>\n{DIVIDER}\n"
        "Tap an account to make it active · 🔓 logs out.",
        reply_markup=await _accounts_menu(scraper, callback.from_user.id),
    )
    await callback.answer()


@router.callback_query(F.data == "scr:acctback")
async def scr_acct_back(callback: CallbackQuery, state: FSMContext, scraper) -> None:  # noqa: ANN001
    if scraper.user_connected(callback.from_user.id):
        await safe_edit(
            callback.message,
            "Tap one or more sources, then Continue:",
            reply_markup=await _sources_kb(callback.from_user, state),
        )
    else:
        await safe_edit(
            callback.message,
            f"{Emoji.LOGIN} Connect an account to start:",
            reply_markup=account_help(),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("scr:use:"))
async def scr_use_account(callback: CallbackQuery, scraper) -> None:  # noqa: ANN001
    label = (callback.data or "").split(":", 2)[2]
    await scraper.set_active(callback.from_user.id, label)
    await safe_edit(
        callback.message,
        f"{Emoji.ACCOUNT} <b>Your accounts</b>\n{DIVIDER}\nActive: <b>{html.escape(label)}</b>",
        reply_markup=await _accounts_menu(scraper, callback.from_user.id),
    )
    await callback.answer("Active account set")


@router.callback_query(F.data.startswith("scr:logout:"))
async def scr_logout(callback: CallbackQuery, scraper) -> None:  # noqa: ANN001
    label = (callback.data or "").split(":", 2)[2]
    scraper.logout(callback.from_user.id, label)
    accounts = scraper.accounts_for(callback.from_user.id)
    if accounts:
        await safe_edit(
            callback.message,
            f"{Emoji.SUCCESS} Logged out <b>{html.escape(label)}</b>.",
            reply_markup=await _accounts_menu(scraper, callback.from_user.id),
        )
    else:
        await safe_edit(
            callback.message,
            f"{Emoji.SUCCESS} All accounts removed. Add one to scrape:",
            reply_markup=account_help(),
        )
    await callback.answer("Logged out")


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
    label = (await scraper.acting_label(tg_user.id)) or (await scraper.active_label(tg_user.id))
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
async def _sources_kb(tg_user, state: FSMContext, *, manage: bool = False):  # noqa: ANN001
    async with session_scope() as session:
        user = await ensure_user(session, tg_user)
        sources = await list_authorized_sources(session, user.id)
    sc = await _load_sc(state)
    pairs = [(s.id, s.title or s.tg_peer_ref) for s in sources]
    return scrape_sources(pairs, selected=set(sc.get("selected") or []), manage=manage)


@router.callback_query(F.data.startswith("scr:toggle:"))
async def scr_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    raw = (callback.data or "").rsplit(":", 1)[-1]
    if not raw.isdigit():
        await callback.answer("Invalid", show_alert=True)
        return
    sc = await _load_sc(state)
    selected = [int(x) for x in (sc.get("selected") or [])]
    sid = int(raw)
    if sid in selected:
        selected.remove(sid)
    else:
        selected.append(sid)
    sc["selected"] = selected
    await _save_sc(state, sc)
    if callback.message is not None:
        await callback.message.edit_reply_markup(
            reply_markup=await _sources_kb(callback.from_user, state)
        )
    await callback.answer()


@router.callback_query(F.data == "scr:continue")
async def scr_continue(callback: CallbackQuery, state: FSMContext) -> None:
    sc = await _load_sc(state)
    ids = sc.get("selected") or []
    if not ids:
        await callback.answer("Pick at least one source", show_alert=True)
        return
    if len(ids) == 1:
        async with session_scope() as session:
            user = await ensure_user(session, callback.from_user)
            source = await get_authorized_source(session, user.id, int(ids[0]))
            title = (source.title or source.tg_peer_ref) if source else "source"
    else:
        title = f"{len(ids)} sources"
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
        await safe_edit(
            callback.message,
            "Send the range as <code>YYYY-MM-DD..YYYY-MM-DD</code>\n"
            "Example: <code>2026-01-01..2026-03-31</code>",
        )
        await callback.answer()
        return
    if value == "clear":
        sc["dates"] = "none"
        sc["date_from"] = None
        sc["date_to"] = None
    else:
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
    await safe_edit(
        callback.message,
        f"{Emoji.SCRAPE} <b>Your sources</b>\n\nTap a source to remove it:",
        reply_markup=await _sources_kb(callback.from_user, state, manage=True),
    )
    await callback.answer()


@router.callback_query(F.data == "scr:back")
async def scr_sources_back(callback: CallbackQuery, state: FSMContext) -> None:
    await safe_edit(
        callback.message,
        f"{Emoji.SCRAPE} Tap one or more sources, then Continue:",
        reply_markup=await _sources_kb(callback.from_user, state),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("scr:delsrc:"))
async def scr_del_source(callback: CallbackQuery, state: FSMContext) -> None:
    raw = (callback.data or "").rsplit(":", 1)[-1]
    if raw.isdigit():
        async with session_scope() as session:
            user = await ensure_user(session, callback.from_user)
            await remove_authorized_source(session, user.id, int(raw))
    await safe_edit(
        callback.message,
        f"{Emoji.SCRAPE} <b>Your sources</b>\n\nRemove another, or add a new one:",
        reply_markup=await _sources_kb(callback.from_user, state, manage=True),
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


@router.callback_query(F.data == "scr:exclude")
async def scr_exclude(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Flow.awaiting_exclude)
    await safe_edit(
        callback.message,
        "🚫 Send words to <b>exclude</b> (comma-separated). Messages containing any "
        "of them are dropped. Send <code>-</code> to clear.",
    )
    await callback.answer()


@router.message(Flow.awaiting_exclude)
async def on_exclude_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    sc = await _load_sc(state)
    sc["exclude"] = [] if text in {"", "-"} else [w.strip() for w in text.split(",") if w.strip()]
    await _save_sc(state, sc)
    await state.set_state(None)
    await message.answer(_panel_text(sc, sc.get("source_title", "")), reply_markup=scrape_panel(sc))


@router.callback_query(F.data == "scr:sender")
async def scr_sender(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Flow.awaiting_sender)
    await safe_edit(
        callback.message,
        "👤 Send a numeric <b>sender id</b> to keep only that sender. "
        "Send <code>-</code> to clear.",
    )
    await callback.answer()


@router.message(Flow.awaiting_sender)
async def on_sender_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    sc = await _load_sc(state)
    sc["sender"] = "" if text in {"", "-"} else text
    await _save_sc(state, sc)
    await state.set_state(None)
    await message.answer(_panel_text(sc, sc.get("source_title", "")), reply_markup=scrape_panel(sc))


@router.callback_query(F.data.startswith("scr:kmode:"))
async def scr_kmode(callback: CallbackQuery, state: FSMContext) -> None:
    mode = (callback.data or "").rsplit(":", 1)[-1]
    if mode not in {"contains", "word", "regex"}:
        await callback.answer("Invalid", show_alert=True)
        return
    sc = await _load_sc(state)
    sc["keyword_mode"] = mode
    await _save_sc(state, sc)
    await safe_edit(callback.message, _panel_text(sc, sc.get("source_title", "")), reply_markup=scrape_panel(sc))
    await callback.answer(f"Keyword mode: {mode}")


@router.callback_query(F.data == "scr:minlen")
async def scr_minlen(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Flow.awaiting_minlen)
    await safe_edit(
        callback.message,
        "📏 Send the minimum message length to keep (e.g. <b>20</b>). Send <code>0</code> to clear.",
    )
    await callback.answer()


@router.message(Flow.awaiting_minlen)
async def on_minlen_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    sc = await _load_sc(state)
    sc["min_length"] = int(text) if text.isdigit() else 0
    await _save_sc(state, sc)
    await state.set_state(None)
    await message.answer(_panel_text(sc, sc.get("source_title", "")), reply_markup=scrape_panel(sc))


@router.callback_query(F.data == "scr:chan")
async def scr_channel_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    sc = await _load_sc(state)
    sc["to_channel"] = not sc.get("to_channel", True)
    await _save_sc(state, sc)
    await safe_edit(callback.message, _panel_text(sc, sc.get("source_title", "")), reply_markup=scrape_panel(sc))
    await callback.answer("Channel " + ("on" if sc["to_channel"] else "off"))


@router.callback_query(F.data.startswith("scr:defaults"))
async def scr_defaults(callback: CallbackQuery, state: FSMContext) -> None:
    if (callback.data or "").endswith(":reset"):
        await prefs.save_prefs(callback.from_user.id, dict(prefs.DEFAULTS))
        sc = dict(prefs.DEFAULTS)
        sc["source_title"] = ""
        await _save_sc(state, sc)
        await safe_edit(
            callback.message,
            f"{Emoji.SUCCESS} Defaults reset.",
            reply_markup=scrape_panel(sc),
        )
        await callback.answer("Reset")
        return
    sc = await _load_sc(state)
    text = (
        f"{Emoji.SETTINGS} <b>Scrape defaults</b>\n{DIVIDER}\n"
        f"Keywords · <b>{', '.join(sc.get('keywords') or []) or 'any'}</b>\n"
        f"Exclude · <b>{', '.join(sc.get('exclude') or []) or 'none'}</b>\n"
        f"Limit · <b>{sc.get('limit') or 'All'}</b>\n"
        f"Mode · <b>{sc.get('mode')}</b>   Dates · <b>{sc.get('dates')}</b>\n"
        f"Auto-clean · <b>{sc.get('autoclean')}</b>   Media · <b>{sc.get('include_media')}</b>\n"
        f"Channel · <b>{sc.get('to_channel')}</b>"
    )
    await safe_edit(callback.message, text, reply_markup=defaults_menu())
    await callback.answer()


@router.callback_query(F.data == "scr:backpanel")
async def scr_back_panel(callback: CallbackQuery, state: FSMContext) -> None:
    sc = await _load_sc(state)
    await safe_edit(
        callback.message,
        _panel_text(sc, sc.get("source_title", "")),
        reply_markup=scrape_panel(sc),
    )
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
    selected = [int(x) for x in (sc.get("selected") or [])]
    if not selected:
        await callback.answer("Pick at least one source", show_alert=True)
        return
    if not scraper.user_connected(tg_user.id):
        await callback.answer("Connect your account first.", show_alert=True)
        return

    label = (await scraper.acting_label(tg_user.id)) or (await scraper.active_label(tg_user.id))
    now = datetime.now(UTC)
    async with session_scope() as session:
        user = await ensure_user(session, tg_user)
        user_settings = await get_user_settings(session, user.id)
        admin = is_admin(user, settings)
        sources = []
        for sid in selected:
            src = await get_authorized_source(session, user.id, sid)
            if src is not None:
                sources.append(src)
    if not sources:
        await callback.answer("Sources not found", show_alert=True)
        return

    keywords = sc.get("keywords") or []
    limit = int(sc.get("limit") or 0)
    dates = sc.get("dates", "none")
    date_from = _parse_dt(sc.get("date_from"))
    date_to = _parse_dt(sc.get("date_to"))
    if dates == "7":
        date_from = now - timedelta(days=7)
    elif dates == "30":
        date_from = now - timedelta(days=30)
    elif dates == "90":
        date_from = now - timedelta(days=90)

    options = ScrapeOptions(
        limit=limit or 1_000_000,
        keywords=keywords,
        exclude=[w for w in (sc.get("exclude") or []) if w],
        sender=(sc.get("sender") or "").strip() or None,
        min_length=int(sc.get("min_length") or 0),
        keyword_mode=sc.get("keyword_mode", "contains"),
        date_from=date_from,
        date_to=date_to,
        text_only=True,
        include_media=bool(sc.get("include_media")),
    )
    base = "Scrape " + ("+".join(keywords) if keywords else "all")
    telegram_id = tg_user.id
    channel = (settings.scrape_channel_id or settings.forward_channel_id or "").strip()
    post_channel = bool(channel) and bool(sc.get("to_channel", True))
    who = (
        f"{tg_user.first_name or 'user'}"
        + (f" (@{tg_user.username})" if tg_user.username else "")
        + f" · id {tg_user.id}"
    )
    await prefs.save_prefs(
        tg_user.id,
        {
            "keywords": keywords,
            "limit": limit,
            "mode": sc.get("mode", "messages"),
            "autoclean": sc.get("autoclean", True),
            "dates": dates,
            "exclude": [w for w in (sc.get("exclude") or []) if w],
            "sender": (sc.get("sender") or "").strip(),
            "min_length": int(sc.get("min_length") or 0),
            "keyword_mode": sc.get("keyword_mode", "contains"),
            "include_media": bool(sc.get("include_media")),
            "to_channel": bool(sc.get("to_channel", True)),
        },
    )
    await callback.answer()

    sources = sources[: max(1, settings.scrape_max_sources)]
    results: list[tuple[str, object]] = []
    for index, source in enumerate(sources, start=1):
        title = source.title or source.tg_peer_ref
        raw = file_manager.allocate(telegram_id, f"Raw-{index}.txt", subdir="out")
        status = await callback.message.answer(
            f"{Emoji.SCRAPE} Scraping <b>{html.escape(title)}</b>"
            f"  ·  {index}/{len(sources)}…"
        )
        reporter = ProgressReporter(
            TelegramNotifier(callback.bot),
            callback.message.chat.id,
            status.message_id,
            min_interval=1.2,
        )
        stop = asyncio.Event()
        animation = asyncio.create_task(_animate(reporter, stop, f"Scraping {title}"))
        try:
            result = await scraper.scrape(
                label=label,
                peer_ref=source.tg_peer_ref,
                out=raw.path,
                options=options,
                fmt="txt",
            )
        except Exception as exc:  # noqa: BLE001
            stop.set()
            await animation
            await safe_edit(status, f"{Emoji.ERROR} {html.escape(title)}: <code>{type(exc).__name__}</code>")
            continue
        stop.set()
        await animation

        cleaned_alloc = file_manager.allocate(
            telegram_id, f"Cleaned-{index}.txt", subdir="out"
        )
        report = await asyncio.to_thread(clean_cards, raw.path, cleaned_alloc.path)
        raw_stored = file_manager.finalize(raw)
        cleaned = file_manager.finalize(cleaned_alloc)

        await safe_edit(
            status,
            f"{Emoji.SUCCESS} <b>{html.escape(title)}</b>\n"
            f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
            f"📨 <b>Matched</b>  ·  {result.exported:,}\n"
            f"🧹 <b>Valid records</b>  ·  {report.valid:,}\n"
            f"⛔ <b>Removed</b>  ·  {report.invalid:,}\n"
            f"💾 <b>Size</b>  ·  {cleaned.size_bytes:,} bytes",
        )
        async with session_scope() as session:
            for stored in (raw_stored, cleaned):
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

        # User receives the RAW file and decides what to do next (full control).
        await callback.message.answer_document(
            FSInputFile(raw_stored.path, filename=_tag(raw_stored.safe_name)),
            caption=(
                f"📄 <b>{html.escape(title)}</b>\n"
                f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
                f"📨 Matches  ·  {result.exported:,}\n"
                f"📄 Size  ·  {raw_stored.size_bytes:,} bytes\n\n"
                f"<i>Clean it to keep only card records.</i>"
            ),
        )
        await state.update_data(last_raw=raw_stored.rel_path, last_title=title)
        await callback.message.answer(
            f"{Emoji.CLEAN} <b>Clean this file?</b>\n"
            f"Keeps only <code>serial|date|time|count</code> records.",
            reply_markup=clean_prompt(),
        )
        results.append((title, raw_stored.rel_path))

        if admin and post_channel:
            try:
                await callback.bot.send_document(
                    channel,
                    FSInputFile(raw_stored.path, filename=_tag(raw_stored.safe_name)),
                    caption=f"📥 <b>Raw</b> · {html.escape(title)}\n👤 {html.escape(who)}",
                )
                sent = await callback.bot.send_document(
                    channel,
                    FSInputFile(cleaned.path, filename=_tag(cleaned.safe_name)),
                    caption=(
                        f"🧹 <b>Cleaned</b> · {html.escape(title)}\n"
                        f"👤 {html.escape(who)}\n"
                        f"✅ {report.valid:,} valid · ⛔ {report.invalid:,} removed"
                    ),
                )
                await callback.bot.pin_chat_message(
                    chat_id=channel, message_id=sent.message_id, disable_notification=True
                )
            except Exception:  # noqa: BLE001 - channel delivery is best-effort
                pass

        if source is not sources[-1]:
            await asyncio.sleep(2)  # gentle pacing between sources (account safety)

    if len(results) > 1:
        await state.update_data(combine_paths=results)
        await callback.message.answer(
            f"{Emoji.MERGE} <b>Combine the {len(results)} files?</b>",
            reply_markup=combine_prompt(len(results)),
        )
    else:
        await state.clear()


@router.callback_query(F.data == "scr:doclean")
async def scr_do_clean(
    callback: CallbackQuery, state: FSMContext, file_manager: FileManager, settings: Settings
) -> None:
    data = await state.get_data()
    rel = data.get("last_raw")
    title = data.get("last_title", "scrape")
    if not rel:
        await callback.answer("Nothing to clean.", show_alert=True)
        return
    telegram_id = callback.from_user.id
    try:
        raw_path = file_manager.resolve(telegram_id, rel, create_parent=False)
    except (ValueError, OSError):
        await callback.answer("File expired.", show_alert=True)
        return
    out = file_manager.allocate(telegram_id, f"{title} Cleaned.txt", subdir="out")
    status = await callback.message.answer(f"{Emoji.CLEAN} Cleaning {title}…")
    reporter = ProgressReporter(
        TelegramNotifier(callback.bot),
        callback.message.chat.id,
        status.message_id,
        min_interval=1.0,
    )
    total = raw_path.stat().st_size or 1
    report = await run_with_progress(
        clean_cards, raw_path, out.path, reporter=reporter, total=total, label="Cleaning"
    )
    stored = file_manager.finalize(out)
    await safe_edit(
        status,
        f"{Emoji.SUCCESS} <b>Clean complete</b>\n"
        f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        f"✅ <b>Valid</b> · {report.valid:,}\n"
        f"⛔ <b>Removed</b> · {report.invalid:,}\n"
        f"💾 <b>Size</b> · {stored.size_bytes:,} bytes",
    )
    await callback.message.answer_document(
        FSInputFile(stored.path, filename=_tag(stored.safe_name)),
        caption=f"🧹 {title} · {report.valid:,} record(s) · {stored.size_bytes:,} bytes",
    )
    await callback.answer()


@router.callback_query(F.data == "scr:keepraw")
async def scr_keep_raw(callback: CallbackQuery) -> None:
    await callback.answer("Kept as-is ✅", show_alert=False)


@router.callback_query(F.data.startswith("scr:combine:"))
async def scr_combine(
    callback: CallbackQuery, state: FSMContext, file_manager: FileManager, settings: Settings
) -> None:
    choice = (callback.data or "").rsplit(":", 1)[-1]
    data = await state.get_data()
    results = data.get("combine_paths") or []
    await state.clear()
    if choice != "yes" or len(results) < 2:
        await safe_edit(callback.message, f"{Emoji.SUCCESS} Done.", reply_markup=None)
        await callback.answer()
        return

    telegram_id = callback.from_user.id
    paths = [
        file_manager.resolve(telegram_id, rel, create_parent=False) for _, rel in results
    ]
    out = file_manager.allocate(telegram_id, "Scrape combined.txt", subdir="out")
    status = await callback.message.answer(f"{Emoji.MERGE} Combining {len(paths)} file(s)…")
    report = await asyncio.to_thread(merge_files, paths, out.path)
    stored = file_manager.finalize(out)
    await safe_edit(
        status,
        f"{Emoji.SUCCESS} <b>Combined</b> · {report.lines:,} line(s) · {stored.size_bytes:,} bytes",
    )
    await callback.message.answer_document(
        FSInputFile(stored.path, filename=_tag(stored.safe_name)),
        caption=f"🔗 Combined · {report.lines:,} line(s)",
    )
    channel = (settings.scrape_channel_id or settings.forward_channel_id or "").strip()
    if channel:
        try:
            sent = await callback.bot.send_document(
                channel,
                FSInputFile(stored.path, filename=_tag(stored.safe_name)),
                caption=f"🔗 Combined · {report.lines:,} line(s)",
            )
            await callback.bot.pin_chat_message(
                chat_id=channel, message_id=sent.message_id, disable_notification=True
            )
        except Exception:  # noqa: BLE001
            pass
    await callback.answer()
