"""Safe UI helpers for editing Telegram messages.

Telegram rejects edits that do not change the message ("message is not
modified") and edits of non-text messages. Silently ignoring those keeps
buttons responsive instead of appearing dead.
"""

from __future__ import annotations

import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, Message

logger = logging.getLogger(__name__)


async def safe_edit(
    message: Message | None,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Edit ``message``'s text, tolerating benign Telegram errors."""
    if message is None:
        return
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            return
        # e.g. editing a photo caption message; fall back to a new message.
        logger.debug("edit_text failed (%s); sending a new message", exc)
        try:
            await message.answer(text, reply_markup=reply_markup)
        except TelegramBadRequest:  # pragma: no cover - best effort
            logger.debug("fallback send also failed")


async def safe_edit_markup(
    message: Message | None,
    reply_markup: InlineKeyboardMarkup | None,
) -> None:
    """Edit only the reply markup, tolerating benign Telegram errors."""
    if message is None:
        return
    try:
        await message.edit_reply_markup(reply_markup=reply_markup)
    except TelegramBadRequest:
        logger.debug("edit_reply_markup failed; ignoring")
