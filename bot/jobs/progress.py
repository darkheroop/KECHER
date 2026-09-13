"""Progress reporting.

A job card is a single Telegram message that the worker edits in place.
Edits are throttled to respect Telegram rate limits; a notifier abstraction
keeps the worker testable without a real bot.
"""

from __future__ import annotations

import logging
import time
from typing import Protocol

from bot.ui.emoji import Emoji

logger = logging.getLogger(__name__)

BAR_WIDTH = 20
BAR_FILLED = "█"
BAR_EMPTY = "░"


def render_progress_bar(percent: float, width: int = BAR_WIDTH) -> str:
    """Render an ASCII progress bar, e.g. ``████████░░░░``."""
    clamped = max(0.0, min(100.0, float(percent)))
    filled = int(round(width * clamped / 100.0))
    return BAR_FILLED * filled + BAR_EMPTY * (width - filled)


def render_progress_text(
    percent: float,
    *,
    label: str = "Processing",
    detail: str | None = None,
) -> str:
    lines = [
        f"{Emoji.PROGRESS} <b>{label}</b>",
        "",
        f"<code>{render_progress_bar(percent)}</code> {int(round(percent))}%",
    ]
    if detail:
        lines.extend(["", detail])
    return "\n".join(lines)


class Notifier(Protocol):
    """Minimal interface used by :class:`ProgressReporter`."""

    async def edit(self, chat_id: int, message_id: int, text: str) -> None: ...


class NullNotifier:
    """No-op notifier used in tests and when progress messages are disabled."""

    async def edit(self, chat_id: int, message_id: int, text: str) -> None:  # noqa: D401
        return None


class TelegramNotifier:
    """Notifier backed by an aiogram ``Bot``."""

    def __init__(self, bot) -> None:  # noqa: ANN001 - avoid aiogram import here
        self._bot = bot

    async def edit(self, chat_id: int, message_id: int, text: str) -> None:
        from aiogram.exceptions import TelegramBadRequest

        try:
            await self._bot.edit_message_text(
                chat_id=chat_id, message_id=message_id, text=text
            )
        except TelegramBadRequest as exc:
            # "message is not modified" and similar are harmless.
            logger.debug("Progress edit skipped: %s", exc)


class ProgressReporter:
    """Throttled wrapper around a job card message."""

    def __init__(
        self,
        notifier: Notifier | None,
        chat_id: int | None,
        message_id: int | None,
        *,
        enabled: bool = True,
        min_interval: float = 1.5,
    ) -> None:
        self._notifier = notifier
        self._chat_id = chat_id
        self._message_id = message_id
        self._enabled = enabled and notifier is not None and chat_id is not None
        self._min_interval = min_interval
        self._last_sent = 0.0
        self._last_percent = -1

    @property
    def active(self) -> bool:
        return bool(self._enabled and self._message_id is not None)

    async def update(
        self,
        percent: float,
        *,
        label: str = "Processing",
        detail: str | None = None,
        force: bool = False,
    ) -> None:
        if not self.active:
            return
        now = time.monotonic()
        clamped = int(round(max(0.0, min(100.0, float(percent)))))
        if not force:
            if now - self._last_sent < self._min_interval:
                return
            if clamped == self._last_percent:
                return
        self._last_sent = now
        self._last_percent = clamped
        assert self._notifier is not None and self._chat_id is not None
        await self._notifier.edit(
            self._chat_id,
            self._message_id,  # type: ignore[arg-type]
            render_progress_text(percent, label=label, detail=detail),
        )

    async def finish(self, text: str) -> None:
        if not self.active:
            return
        assert self._notifier is not None and self._chat_id is not None
        await self._notifier.edit(self._chat_id, self._message_id, text)  # type: ignore[arg-type]
