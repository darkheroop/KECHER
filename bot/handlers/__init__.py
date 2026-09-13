"""Telegram handlers (aiogram routers)."""

from __future__ import annotations

from bot.handlers.data_tools import router as data_tools_router
from bot.handlers.file_ops import router as file_ops_router
from bot.handlers.jobs import router as jobs_router
from bot.handlers.keys import router as keys_router
from bot.handlers.settings import router as settings_router
from bot.handlers.sources import router as sources_router
from bot.handlers.start_help import router as start_help_router
from bot.handlers.upload import router as upload_router
from bot.handlers.validators import router as validators_router

# Order matters: more specific routers should be included first.
routers = [
    keys_router,
    settings_router,
    jobs_router,
    file_ops_router,
    data_tools_router,
    sources_router,
    validators_router,
    upload_router,
    start_help_router,
]

__all__ = [
    "data_tools_router",
    "file_ops_router",
    "jobs_router",
    "keys_router",
    "routers",
    "settings_router",
    "sources_router",
    "start_help_router",
    "upload_router",
    "validators_router",
]
