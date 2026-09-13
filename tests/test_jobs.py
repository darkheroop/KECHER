import asyncio

from bot.config import get_settings
from bot.db.engine import session_scope
from bot.db.enums import JobStatus
from bot.db.repositories import create_job, get_job, get_or_create_user
from bot.jobs.context import JobCancelled, JobResult
from bot.jobs.manager import JobManager
from bot.services.file_manager import FileManager


async def _make_job(telegram_id: int, kind: str, **kwargs) -> int:
    async with session_scope() as session:
        user, _ = await get_or_create_user(session, telegram_id)
        job = await create_job(session, user_id=user.id, kind=kind, **kwargs)
        return job.id


async def _job(job_id: int) -> tuple[str, int, str | None]:
    async with session_scope() as session:
        job = await get_job(session, job_id)
        assert job is not None
        return job.status, job.progress, job.error


def _manager(concurrency: int = 1) -> JobManager:
    return JobManager(files=FileManager(get_settings()), concurrency=concurrency)


async def test_job_completes(db) -> None:
    manager = _manager()

    async def handler(ctx) -> JobResult:
        ctx.raise_if_cancelled()
        return JobResult(message="done", stats={"rows": 3})

    manager.register("clean", handler)
    job_id = await _make_job(1, "clean")
    task = await manager.submit(job_id)
    await task

    status, progress, error = await _job(job_id)
    assert status == JobStatus.COMPLETED.value
    assert progress == 100
    assert error is None


async def test_job_failure_is_recorded(db) -> None:
    manager = _manager()

    async def handler(ctx) -> JobResult:
        raise ValueError("boom")

    manager.register("split", handler)
    job_id = await _make_job(2, "split")
    task = await manager.submit(job_id)
    await task

    status, _, error = await _job(job_id)
    assert status == JobStatus.FAILED.value
    assert error is not None and "boom" in error


async def test_missing_handler_fails_cleanly(db) -> None:
    manager = _manager()
    job_id = await _make_job(3, "dedup")
    task = await manager.submit(job_id)
    await task

    status, _, error = await _job(job_id)
    assert status == JobStatus.FAILED.value
    assert error is not None and "No handler" in error


async def test_running_job_can_be_cancelled(db) -> None:
    manager = _manager()

    async def handler(ctx) -> JobResult:
        while True:
            ctx.raise_if_cancelled()
            await asyncio.sleep(0.01)

    manager.register("clean", handler)
    job_id = await _make_job(4, "clean")
    task = await manager.submit(job_id)
    await asyncio.sleep(0.05)

    assert await manager.cancel(job_id) is True
    await asyncio.wait_for(task, timeout=5)

    status, _, _ = await _job(job_id)
    assert status == JobStatus.CANCELLED.value


async def test_queued_job_cancel(db) -> None:
    manager = _manager()
    job_id = await _make_job(5, "clean")

    assert await manager.cancel(job_id) is True
    status, _, _ = await _job(job_id)
    assert status == JobStatus.CANCELLED.value


async def test_cancelled_job_not_overwritten(db) -> None:
    manager = _manager()
    job_id = await _make_job(6, "clean")
    await manager.cancel(job_id)

    async def handler(ctx) -> JobResult:  # never runs
        return JobResult()

    manager.register("clean", handler)
    task = await manager.submit(job_id)
    await task

    status, _, _ = await _job(job_id)
    assert status == JobStatus.CANCELLED.value


async def test_handler_can_report_progress(db) -> None:
    manager = _manager()
    reported: list[int] = []

    async def handler(ctx) -> JobResult:
        for pct in (25, 50, 75):
            reported.append(pct)
        return JobResult()

    manager.register("csv", handler)
    job_id = await _make_job(7, "csv")
    task = await manager.submit(job_id)
    await task

    status, progress, _ = await _job(job_id)
    assert reported == [25, 50, 75]
    assert status == JobStatus.COMPLETED.value
    assert progress == 100
