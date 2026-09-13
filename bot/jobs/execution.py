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
    **kwargs,
) -> T:
    """Execute ``func`` in a worker thread, injecting an ``on_progress`` hook.

    ``total`` is the unit total (bytes, rows, paragraphs) used to compute a
    percentage. Coroutine updates are scheduled thread-safely on the loop.
    """
    loop = asyncio.get_running_loop()

    def on_progress(done: int) -> None:
        if reporter is None or not total:
            return
        percent = min(99.0, max(0.0, done * 100.0 / total))
        asyncio.run_coroutine_threadsafe(reporter.update(percent, label=label), loop)

    def call() -> T:
        return func(*args, on_progress=on_progress, **kwargs)

    return await asyncio.to_thread(call)
