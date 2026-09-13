"""Background job manager.

Heavy work runs here, never inside a Telegram update handler. Each submitted
job gets its own asyncio task, bounded by a semaphore; cancellation is
cooperative via an :class:`asyncio.Event` that handlers observe through
:meth:`JobContext.raise_if_cancelled`. On success the manager persists and
delivers any produced files.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from bot.db.engine import session_scope
from bot.db.enums import JobStatus
from bot.db.models import User, UserFile
from bot.db.repositories import (
    TERMINAL_JOB_STATUSES,
    create_file,
    get_job,
    get_user_settings,
    set_job_status,
)
from bot.jobs.context import JobCancelled, JobContext, JobHandler, JobResult
from bot.jobs.progress import Notifier, ProgressReporter
from bot.jobs.sender import DocumentSender
from bot.services.file_manager import FileManager
from bot.ui.emoji import Emoji

logger = logging.getLogger(__name__)

MAX_ERROR_LENGTH = 500


def _safe_error(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}"
    return text[:MAX_ERROR_LENGTH]


class JobManager:
    """Registry + executor for background jobs."""

    def __init__(
        self,
        *,
        files: FileManager,
        concurrency: int = 4,
        notifier: Notifier | None = None,
        sender: DocumentSender | None = None,
        default_ttl_minutes: int = 10,
    ) -> None:
        self._files = files
        self._concurrency = max(1, concurrency)
        self._notifier = notifier
        self._sender = sender
        self._default_ttl_minutes = default_ttl_minutes
        self._semaphore = asyncio.Semaphore(self._concurrency)
        self._handlers: dict[str, JobHandler] = {}
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self._cancel_events: dict[int, asyncio.Event] = {}

    # -- registry ----------------------------------------------------------- #
    def register(self, kind: str, handler: JobHandler) -> None:
        self._handlers[str(kind)] = handler

    def handler_for(self, kind: str) -> JobHandler | None:
        return self._handlers.get(str(kind))

    def registered_kinds(self) -> list[str]:
        return sorted(self._handlers)

    # -- lifecycle ---------------------------------------------------------- #
    async def submit(self, job_id: int) -> asyncio.Task[None]:
        """Schedule a queued job. Returns its task (useful for tests/awaiting)."""
        existing = self._tasks.get(job_id)
        if existing is not None and not existing.done():
            return existing

        self._cancel_events.setdefault(job_id, asyncio.Event())
        task: asyncio.Task[None] = asyncio.create_task(
            self._run(job_id), name=f"job-{job_id}"
        )
        self._tasks[job_id] = task

        def _cleanup(_: asyncio.Task[None]) -> None:
            self._tasks.pop(job_id, None)

        task.add_done_callback(_cleanup)
        return task

    async def cancel(self, job_id: int) -> bool:
        """Request cancellation. Returns True if a live job was affected."""
        event = self._cancel_events.get(job_id)
        if event is not None:
            event.set()

        async with session_scope() as session:
            job = await get_job(session, job_id)
            if job is None:
                return False
            if job.status == JobStatus.QUEUED.value:
                await set_job_status(session, job, JobStatus.CANCELLED)
                return True
            if job.status == JobStatus.PROCESSING.value:
                return True
            return False

    async def shutdown(self, timeout: float = 5.0) -> None:
        """Signal cancellation and wait briefly for running jobs to stop."""
        for job_id, event in self._cancel_events.items():
            event.set()
            logger.debug("Cancelling job %s on shutdown", job_id)

        tasks = [t for t in self._tasks.values() if not t.done()]
        if not tasks:
            return
        _, pending = await asyncio.wait(tasks, timeout=timeout)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    def active_count(self) -> int:
        return sum(1 for task in self._tasks.values() if not task.done())

    # -- execution ---------------------------------------------------------- #
    async def _run(self, job_id: int) -> None:
        async with self._semaphore:
            event = self._cancel_events.setdefault(job_id, asyncio.Event())
            context = await self._build_context(job_id, event)
            if context is None:
                return

            handler = self._handlers.get(context.kind)
            try:
                if handler is None:
                    raise RuntimeError(
                        f"No handler registered for job kind '{context.kind}'"
                    )
                result = await handler(context)
                if event.is_set():
                    raise JobCancelled()
            except JobCancelled:
                await self._finalize(job_id, JobStatus.CANCELLED)
                await self._notify(context, f"{Emoji.CANCEL} Job cancelled.")
            except asyncio.CancelledError:
                await self._finalize(job_id, JobStatus.CANCELLED)
                raise
            except Exception as exc:  # noqa: BLE001 - job boundary must not leak
                logger.exception("Job %s failed", job_id)
                await self._finalize(
                    job_id, JobStatus.FAILED, error=_safe_error(exc)
                )
                await self._notify(
                    context, f"{Emoji.ERROR} <b>Job failed</b>\n\n{_safe_error(exc)}"
                )
            else:
                await self._finalize(job_id, JobStatus.COMPLETED)
                await self._deliver(context, result)

    async def _build_context(
        self, job_id: int, event: asyncio.Event
    ) -> JobContext | None:
        async with session_scope() as session:
            job = await get_job(session, job_id)
            if job is None or job.status in TERMINAL_JOB_STATUSES:
                return None
            if job.status == JobStatus.CANCELLED.value:
                return None

            user = await session.get(User, job.user_id)
            if user is None:
                await set_job_status(session, job, JobStatus.FAILED, error="User not found")
                return None

            settings = await get_user_settings(session, job.user_id)
            input_record = (
                await session.get(UserFile, job.input_file_id)
                if job.input_file_id is not None
                else None
            )

            await set_job_status(session, job, JobStatus.PROCESSING)

            telegram_id = user.telegram_id
            chat_id = job.chat_id
            message_id = job.progress_message_id
            kind = job.kind
            params = dict(job.params or {})
            input_rel = input_record.rel_path if input_record else None
            progress_enabled = bool(settings.progress_messages)

        workspace = self._files.user_root(telegram_id)
        input_path = None
        if input_rel is not None:
            try:
                input_path = self._files.resolve(
                    telegram_id, input_rel, create_parent=False
                )
            except (ValueError, OSError):  # pragma: no cover - defensive
                input_path = None

        reporter = ProgressReporter(
            self._notifier,
            chat_id,
            message_id,
            enabled=progress_enabled,
        )
        return JobContext(
            job_id=job_id,
            user_id=user.id,
            telegram_id=telegram_id,
            kind=kind,
            params=params,
            workspace=workspace,
            files=self._files,
            progress=reporter,
            cancel_event=event,
            chat_id=chat_id,
            input_path=input_path,
            sender=self._sender,
        )

    async def _finalize(
        self, job_id: int, status: JobStatus, *, error: str | None = None
    ) -> None:
        async with session_scope() as session:
            job = await get_job(session, job_id)
            if job is None:
                return
            if job.status == JobStatus.CANCELLED.value and status != JobStatus.CANCELLED:
                return
            progress = 100 if status == JobStatus.COMPLETED else None
            await set_job_status(session, job, status, error=error, progress=progress)

        if status == JobStatus.COMPLETED:
            logger.info("Job %s completed", job_id)
        elif status == JobStatus.FAILED:
            logger.warning("Job %s failed: %s", job_id, error)
        elif status == JobStatus.CANCELLED:
            logger.info("Job %s cancelled", job_id)

    async def _deliver(self, context: JobContext, result: JobResult | None) -> None:
        result = result or JobResult()
        text = result.message or "Completed"
        outputs = result.outputs

        if context.chat_id is None or self._sender is None:
            return

        final_text = f"{Emoji.SUCCESS} <b>{text}</b>"
        if outputs and context.progress.active:
            await context.progress.finish(final_text)
        else:
            await self._sender.send_message(context.chat_id, final_text)

        if not outputs:
            return

        expires_at = datetime.now(UTC) + timedelta(minutes=max(1, self._default_ttl_minutes))
        async with session_scope() as session:
            for output in outputs:
                await create_file(
                    session,
                    user_id=context.user_id,
                    original_name=output.stored.safe_name,
                    safe_name=output.stored.safe_name,
                    rel_path=output.stored.rel_path,
                    size_bytes=output.stored.size_bytes,
                    sha256=output.stored.sha256,
                    expires_at=expires_at,
                )

        for output in outputs:
            await self._sender.send_document(
                context.chat_id,
                output.stored.path,
                caption=output.caption or text,
                filename=output.stored.safe_name,
            )

    async def _notify(self, context: JobContext, text: str) -> None:
        if context.chat_id is None or self._sender is None:
            return
        try:
            if context.progress.active:
                await context.progress.finish(text)
            else:
                await self._sender.send_message(context.chat_id, text)
        except Exception:  # noqa: BLE001 - notifications must never crash a job
            logger.exception("Failed to notify chat %s", context.chat_id)
