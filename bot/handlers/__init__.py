"""Telegram handlers (aiogram routers) for the Card File Bot."""

from __future__ import annotations

from bot.handlers.cards import router as cards_router
from bot.handlers.keys import router as keys_router
from bot.handlers.menu import router as menu_router
from bot.handlers.scrape import router as scrape_router

# Order matters: scrape before menu (for menu:scrape); cards catch-all last.
routers = [
    keys_router,
    scrape_router,
    menu_router,
    cards_router,
]

__all__ = ["cards_router", "keys_router", "menu_router", "routers", "scrape_router"]
