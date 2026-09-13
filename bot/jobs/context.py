"""Job execution context and result types."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bot.jobs.progress import ProgressReporter
from bot.jobs.sender import DocumentSender
from bot.services.file_manager import FileManager, StoredFile


class JobCancelled(Exception):
    """Raised by a handler (or :meth:`JobContext.raise_if_cancelled`) to abort."""


@dataclass(slots=True)
class JobOutput:
    """A produced file to be delivered to the user."""

    stored: StoredFile
    caption: str | None = None


@dataclass(slots=True)
class JobContext:
    """Everything a handler needs, assembled by the JobManager."""

    job_id: int
    user_id: int
    telegram_id: int
    kind: str
    params: dict[str, Any]
    workspace: Path
    files: FileManager
    progress: ProgressReporter
    cancel_event: asyncio.Event
    chat_id: int | None = None
    input_path: Path | None = None
    sender: DocumentSender | None = None

    def raise_if_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise JobCancelled(f"Job {self.job_id} cancelled")


@dataclass(slots=True)
class JobResult:
    """Returned by a successful handler."""

    message: str = ""
    outputs: list[JobOutput] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


JobHandler = Callable[[JobContext], Awaitable[JobResult]]
