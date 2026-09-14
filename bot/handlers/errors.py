"""Global error handling.

Any unhandled exception in a handler is logged (with traceback) and the user
gets a message that includes a short description of the cause, so problems are
diagnosable without digging through logs.
"""

from __future__ import annotations

import html
import logging
import re

from aiogram import Dispatcher
from aiogram.types import ErrorEvent

logger = logging.getLogger(__name__)

MAX_DETAIL = 300

_URL_RE = re.compile(r"[a-z0-9+]+://\S+", re.IGNORECASE)
_SECRET_RE = re.compile(
    r"(?i)(password|pwd|token|api_hash|secret)\s*[=:]\s*\S+"
)


def _sanitize(text: str) -> str:
    text = _URL_RE.sub("<url>", text)
    text = _SECRET_RE.sub(r"\1=***", text)
    return text


def _detail(exc: BaseException) -> str:
    text = _sanitize(f"{type(exc).__name__}: {exc}".strip())
    return text[:MAX_DETAIL]


async def on_error(event: ErrorEvent) -> None:
    logger.exception("Unhandled error processing update", exc_info=event.exception)

    detail = html.escape(_detail(event.exception))
    text = (
        "⚠️ <b>Something went wrong</b>\n\n"
        f"<code>{detail}</code>\n\n"
        "Send /start to reset."
    )

    update = event.update
    try:
        if update.callback_query is not None:
            await update.callback_query.answer("Something went wrong. See the log.", show_alert=True)
            if update.callback_query.message is not None:
                await update.callback_query.message.answer(text)
        elif update.message is not None and update.message.chat is not None:
            await update.message.answer(text)
    except Exception:  # noqa: BLE001 - never fail inside the error handler
        logger.exception("Could not notify user about the error")


def register_error_handler(dispatcher: Dispatcher) -> None:
    dispatcher.errors.register(on_error)
