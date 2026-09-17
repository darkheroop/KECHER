"""Mini App data handler: buttons inside the Web App talk back to the bot."""

from __future__ import annotations

import html
import json
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from bot.config import Settings
from bot.db.engine import session_scope
from bot.db.repositories import get_or_create_user
from bot.handlers.menu import help_text, welcome_text
from bot.security.access import is_admin
from bot.services.file_manager import FileManager
from bot.ui.emoji import Emoji
from bot.ui.keyboards import main_menu
from bot.webapp import DIST_DIR, webapp_url

logger = logging.getLogger(__name__)
router = Router(name="webapp")

# action -> short instruction posted back into the chat
GUIDE = {
    "clean": "🧹 Reply to a .txt with <code>/clean</code> to keep valid records.",
    "live": "🕵️ Reply to a .txt with <code>/live</code> for the Luhn check.",
    "filter": "🎯 Reply to a .txt with <code>/filter &lt;keyword&gt;</code> (series or keyword).",
    "findbin": "🔍 Reply to a .txt with <code>/findbin &lt;digits&gt;</code> (numbers only).",
    "split": "✂️ Reply to a .txt with <code>/split N</code>.",
    "dedup": "♻️ Reply to a .txt with <code>/dedup</code>.",
    "add_account": "👤 Open (or run) <code>/scrape</code> → 👤 Accounts → ➕ Add account.",
    "logout": "👤 Open <code>/scrape</code> → 👤 Accounts to log an account out.",
    "accounts": "👤 Your connected accounts: /myaccounts",
    "history": "🗂 Your recent scrapes: /history",
    "settings": "⚙️ Open <code>/settings</code> for mode, cleanup and language.",
    "help": "❓ Full guide: /help",
}


def _scrape_summary(payload: dict) -> str:
    sources = ", ".join(payload.get("sources") or []) or "—"
    return (
        "🔍 <b>Scrape request received</b>\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        f"Sources: <b>{html.escape(sources)}</b>\n"
        f"Keyword: <b>{html.escape(str(payload.get('keyword') or 'any'))}</b>\n"
        f"Range: <b>{html.escape(str(payload.get('range') or 'all'))}</b>\n"
        f"Match: <b>{html.escape(str(payload.get('matchMode') or 'contains'))}</b>\n"
        f"Limit: <b>{payload.get('limit', 100)}</b>\n"
        f"Format: <b>{html.escape(str(payload.get('format') or 'txt').upper())}</b>\n"
        f"Dry-run: <b>{'on' if payload.get('dryRun') else 'off'}</b>\n\n"
        "Run the real scrape from <code>/scrape</code> (pick your saved sources)."
    )


@router.message(Command("app"))
async def cmd_app(message: Message, settings: Settings) -> None:
    url = webapp_url(settings)
    if not url:
        await message.answer(
            "📱 The Mini App isn't configured yet.\n\n"
            "Set <code>PUBLIC_BASE_URL</code> to this service's public HTTPS URL "
            "and redeploy.",
        )
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Open Card File Bot", web_app=WebAppInfo(url=url))]
        ]
    )
    await message.answer("📱 Tap to open the app:", reply_markup=keyboard)


@router.message(Command("apptest"))
async def cmd_apptest(message: Message, settings: Settings) -> None:
    """Admin diagnostic: is the public Mini App URL actually reachable?"""
    tg_user = message.from_user
    assert tg_user is not None
    async with session_scope() as session:
        user, _ = await get_or_create_user(session, tg_user.id)
        if not is_admin(user, settings):
            await message.answer(f"{Emoji.DENIED} Admins only.")
            return

    url = webapp_url(settings)
    lines = [f"{Emoji.STATS} <b>Mini App diagnostic</b>", "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"]
    lines.append(f"PUBLIC_BASE_URL: <code>{settings.public_base_url or '(empty)'}</code>")
    lines.append(f"Built app present: <b>{'yes' if DIST_DIR.is_dir() else 'no'}</b>")
    if not url:
        lines.append("❌ No public URL configured -> set PUBLIC_BASE_URL and redeploy.")
        await message.answer("\n".join(lines))
        return

    lines.append(f"URL: <code>{url}</code>")
    try:
        import aiohttp

        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as client:
            async with client.get(url) as response:
                body = await response.text()
                lines.append(f"HTTP: <b>{response.status}</b>")
                lines.append(f"Contains app: <b>{'yes' if 'Card File Bot' in body else 'no'}</b>")
                if response.status != 200:
                    lines.append("❌ The domain does not reach this bot service.")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"❌ Request failed: <code>{type(exc).__name__}</code>")
        lines.append("The domain is not pointing at this service (or is not HTTPS).")

    await message.answer("\n".join(lines))


@router.message(F.web_app_data)
async def on_web_app(
    message: Message, settings: Settings, state: FSMContext, scraper, file_manager: FileManager  # noqa: ANN001
) -> None:
    raw = message.web_app_data.data if message.web_app_data else ""
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            payload = {"action": str(payload)}
    except (json.JSONDecodeError, TypeError):
        payload = {"action": (raw or "").strip()}

    action = str(payload.get("action", "menu"))

    if action == "menu":
        await message.answer(welcome_text("en"), reply_markup=main_menu())
        return
    if action == "help":
        await message.answer(help_text("en"))
        return
    if action == "scrape":
        await message.answer(_scrape_summary(payload))
        return

    await message.answer(GUIDE.get(action, "Use /help to see everything."))
