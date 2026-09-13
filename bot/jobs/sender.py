"""Outbound delivery abstraction for job results."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class DocumentSender(Protocol):
    """Interface used by :class:`~bot.jobs.manager.JobManager` to deliver results."""

    async def send_document(
        self,
        chat_id: int,
        path: Path,
        *,
        caption: str | None = None,
        filename: str | None = None,
    ) -> None: ...

    async def send_message(self, chat_id: int, text: str) -> None: ...


class TelegramSender:
    """DocumentSender backed by an aiogram ``Bot``."""

    def __init__(self, bot) -> None:  # noqa: ANN001 - avoid aiogram import here
        self._bot = bot

    async def send_document(
        self,
        chat_id: int,
        path: Path,
        *,
        caption: str | None = None,
        filename: str | None = None,
    ) -> None:
        from aiogram.types import FSInputFile

        await self._bot.send_document(
            chat_id=chat_id,
            document=FSInputFile(path, filename=filename or path.name),
            caption=caption,
        )

    async def send_message(self, chat_id: int, text: str) -> None:
        await self._bot.send_message(chat_id=chat_id, text=text)
