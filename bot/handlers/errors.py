"""Global error handling.

Any unhandled exception in a handler is logged (with traceback) and the user
gets a friendly message instead of silence. This makes broken buttons/flows
diagnosable via ``var/logs/bot.log``.
"""

from __future__ import annotations

import logging

from aiogram import Dispatcher
from aiogram.types import ErrorEvent

logger = logging.getLogger(__name__)

ERROR_TEXT = (
    "⚠️ Something went wrong while handling that.\n"
    "Please try again, or send /start to reset."
)


async def on_error(event: ErrorEvent) -> None:
    logger.exception("Unhandled error processing update", exc_info=event.exception)

    update = event.update
    try:
        if update.callback_query is not None:
            await update.callback_query.answer(
                "Something went wrong. Try /start.", show_alert=True
            )
        elif update.message is not None and update.message.chat is not None:
            await update.message.answer(ERROR_TEXT)
    except Exception:  # noqa: BLE001 - never fail inside the error handler
        logger.exception("Could not notify user about the error")


def register_error_handler(dispatcher: Dispatcher) -> None:
    dispatcher.errors.register(on_error)
