"""Mini App data handler: buttons inside the Web App talk back to the bot."""

from __future__ import annotations

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

GUIDE = {
    "clean": "🧹 Reply to a .txt with <code>/clean</code> to keep valid records.",
    "live": "🕵️ Reply to a .txt with <code>/live</code> for the Luhn check.",
    "filter": "🌐 Reply to a .txt with <code>/filter &lt;keyword&gt;</code>.",
    "findbin": "🔍 Reply to a .txt with <code>/findbin &lt;digits&gt;</code>.",
    "split": "✂️ Reply to a .txt with <code>/split N</code>.",
    "dedup": "♻️ Reply to a .txt with <code>/dedup</code>.",
    "accounts": "👤 Open /scrape → 👤 Accounts to add or switch accounts.",
    "history": "🗂 Current jobs and recent activity: /jobs and /myaccounts.",
    "scrape": "🔍 Opening the scrape panel…",
}


@router.message(F.web_app_data)
async def on_web_app(
    message: Message, settings: Settings, state: FSMContext, scraper, file_manager: FileManager  # noqa: ANN001
) -> None:
    raw = message.web_app_data.data if message.web_app_data else ""
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        payload = {"action": (raw or "").strip()}
    action = str(payload.get("action", "menu"))

    if action == "menu":
        await message.answer(welcome_text("en"), reply_markup=main_menu())
        return
    if action == "help":
        await message.answer(help_text("en"))
        return
    if action == "settings":
        await message.answer("⚙️ Open /settings to change mode, cleanup and language.")
        return
    if action == "scrape":
        from bot.handlers.scrape import _scrape_entry

        assert message.from_user is not None
        await _scrape_entry(message, message.from_user, state, scraper, settings)
        return

    await message.answer(GUIDE.get(action, "Use /help to see everything."))
