import pytest

from bot.jobs.progress import (
    NullNotifier,
    ProgressReporter,
    render_progress_bar,
    render_progress_text,
)


@pytest.mark.parametrize(
    ("percent", "expected"),
    [
        (0, "░" * 20),
        (100, "█" * 20),
        (50, "█" * 10 + "░" * 10),
        (-5, "░" * 20),
        (150, "█" * 20),
    ],
)
def test_render_progress_bar(percent: float, expected: str) -> None:
    assert render_progress_bar(percent) == expected


def test_render_progress_text_contains_values() -> None:
    text = render_progress_text(78, label="Processing", detail="Records: 78 / 100")
    assert "Processing" in text
    assert "78%" in text
    assert "Records: 78 / 100" in text


class _Recorder:
    def __init__(self) -> None:
        self.edits: list[tuple[int, int, str]] = []

    async def edit(self, chat_id: int, message_id: int, text: str) -> None:
        self.edits.append((chat_id, message_id, text))


async def test_reporter_throttles_edits() -> None:
    rec = _Recorder()
    reporter = ProgressReporter(rec, chat_id=1, message_id=2, min_interval=999)
    await reporter.update(0)
    await reporter.update(10)
    await reporter.update(20)
    assert len(rec.edits) == 1


async def test_reporter_force_bypasses_throttle() -> None:
    rec = _Recorder()
    reporter = ProgressReporter(rec, chat_id=1, message_id=2, min_interval=999)
    await reporter.update(0)
    await reporter.update(10, force=True)
    assert len(rec.edits) == 2


async def test_reporter_inactive_when_disabled() -> None:
    rec = _Recorder()
    reporter = ProgressReporter(rec, chat_id=1, message_id=2, enabled=False)
    await reporter.update(50)
    await reporter.finish("done")
    assert rec.edits == []
    assert reporter.active is False


async def test_reporter_inactive_without_message() -> None:
    reporter = ProgressReporter(NullNotifier(), chat_id=1, message_id=None)
    await reporter.update(50)
    assert reporter.active is False
