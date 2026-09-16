"""Mini App data handler: buttons inside the Web App talk back to the bot."""

from __future__ import annotations

import html
import json
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.config import Settings
from bot.handlers.menu import help_text, welcome_text
from bot.services.file_manager import FileManager
from bot.ui.keyboards import main_menu

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
