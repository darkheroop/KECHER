"""Run blocking work in a thread, relaying byte/row progress to the reporter."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TypeVar

from bot.jobs.progress import ProgressReporter

T = TypeVar("T")


async def run_with_progress(
    func: Callable[..., T],
    *args,
    reporter: ProgressReporter | None = None,
    total: int | None = None,
    label: str = "Processing",
    detail: str | None = None,
    **kwargs,
) -> T:
    """Execute ``func`` in a worker thread, injecting an ``on_progress`` hook.

    ``total`` is the unit total (bytes, rows, paragraphs) used to compute a
    percentage. Coroutine updates are scheduled thread-safely on the loop.
    """
    loop = asyncio.get_running_loop()
    pending = []
    last_percent = -1

    def on_progress(done: int) -> None:
        nonlocal last_percent
        if reporter is None or not total:
            return
        percent = min(99.0, max(0.0, done * 100.0 / total))
        rounded = int(percent)
        if rounded <= last_percent:
            return
        last_percent = rounded
        pending.append(
            asyncio.run_coroutine_threadsafe(
                reporter.update(percent, label=label, detail=detail), loop
            )
        )

    def call() -> T:
        return func(*args, on_progress=on_progress, **kwargs)

    try:
        result = await asyncio.to_thread(call)
    finally:
        if pending:
            await asyncio.gather(
                *(asyncio.wrap_future(future) for future in pending),
                return_exceptions=True,
            )
    return result
