"""Telegram handlers (aiogram routers) for the Card File Bot."""

from __future__ import annotations

from bot.handlers.cards import router as cards_router
from bot.handlers.keys import router as keys_router
from bot.handlers.menu import router as menu_router

# Order matters: admin/access first, then menu, then file actions.
routers = [
    keys_router,
    menu_router,
    cards_router,
]

__all__ = ["cards_router", "keys_router", "menu_router", "routers"]
