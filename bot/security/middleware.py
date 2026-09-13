"""Cross-cutting aiogram middlewares: rate limiting and access control."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.config import Settings
from bot.db.engine import session_scope
from bot.db.repositories import get_or_create_user
from bot.security.access import has_active_access, is_admin
from bot.security.ratelimit import SlidingWindowLimiter
from bot.ui.emoji import Emoji

logger = logging.getLogger(__name__)

SLOW_DOWN_TEXT = f"{Emoji.WARNING} Too many requests. Please slow down."

# Commands always allowed, even without an active key (needed to gain access).
PUBLIC_COMMANDS = {"start", "help", "redeem", "mykey", "plogin", "id", "claimadmin"}

NO_ACCESS_TEXT = (
    f"{Emoji.LOCK} <b>Access required</b>\n\n"
    "You need an access key to use this bot.\n"
    "Redeem one with <code>/redeem YOUR-KEY</code>.\n\n"
    f"{Emoji.INFO} Already have access? Check it with /mykey."
)


def _command_of(event: TelegramObject) -> str | None:
    text = getattr(event, "text", None)
    if not text or not text.startswith("/"):
        return None
    token = text[1:].split()[0].split("@")[0]
    return token.lower()


class AccessMiddleware(BaseMiddleware):
    """Gate the bot behind admin status or an active access key.

    No effect unless ``ACCESS_REQUIRED=true``. Admins (``ADMIN_IDS`` or the
    ``is_admin`` flag) always pass. Public commands remain reachable.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not self._settings.access_required:
            return await handler(event, data)

        user = data.get("event_from_user") or getattr(event, "from_user", None)
        if user is None or getattr(user, "is_bot", False):
            return await handler(event, data)

        command = _command_of(event)
        if command in PUBLIC_COMMANDS:
            return await handler(event, data)

        async with session_scope() as session:
            db_user, _ = await get_or_create_user(
                session,
                user.id,
                username=getattr(user, "username", None),
                first_name=getattr(user, "first_name", None),
            )
            allowed = is_admin(db_user, self._settings) or has_active_access(db_user)

        if allowed:
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            await event.answer(
                "Access required. Redeem a key with /redeem.", show_alert=True
            )
        elif isinstance(event, Message):
            await event.answer(NO_ACCESS_TEXT)
        return None


class RateLimitMiddleware(BaseMiddleware):
    """Per-user sliding-window limiter applied to messages and callbacks."""

    def __init__(self, limiter: SlidingWindowLimiter) -> None:
        self._limiter = limiter

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is not None and not self._limiter.allow(user.id):
            retry_after = self._limiter.retry_after(user.id)
            logger.info("Rate limited user %s (retry in %.1fs)", user.id, retry_after)
            if isinstance(event, CallbackQuery):
                await event.answer(SLOW_DOWN_TEXT, show_alert=True)
            elif isinstance(event, Message):
                await event.answer(SLOW_DOWN_TEXT)
            return None
        return await handler(event, data)
