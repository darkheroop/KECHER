"""Fast-engine primitives: windowing, streaming sink, progress and ETA."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from bot.services.engine import (
    OutputSink,
    ScanProgress,
    ScanState,
    format_duration,
    plan_windows,
)
from bot.services.scraper import MessageDatum, ScrapeOptions

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _datum(msg_id: int, text: str, *, days: int = 0) -> MessageDatum:
    return MessageDatum(id=msg_id, date=BASE + timedelta(days=days), text=text)


def test_plan_windows_splits_into_contiguous_shards() -> None:
    lower, upper = BASE, BASE + timedelta(days=90)
    windows = plan_windows(lower, upper, 3)
    assert len(windows) == 3
    assert windows[0][0] == lower
    assert windows[-1][1] == upper
    for (_, hi), (lo, _) in zip(windows, windows[1:], strict=False):
        assert hi == lo


def test_plan_windows_single_when_no_lower_bound() -> None:
    assert plan_windows(None, BASE, 3) == [(None, BASE)]
    assert plan_windows(BASE, None, 3) == [(BASE, None)]


def test_scan_state_tracks_fraction() -> None:
    state = ScanState(BASE, BASE + timedelta(days=10))
    assert state.fraction() is None
    state.bump(BASE + timedelta(days=5))
    assert state.fraction() == pytest.approx(0.5)
    state.bump(BASE + timedelta(days=1))
    assert state.scanned == 2
    assert state.fraction() == pytest.approx(0.9)


def test_scan_progress_eta() -> None:
    progress = ScanProgress(scanned=500, matched=10, fraction=0.25)
    assert progress.eta_seconds(30) == pytest.approx(90)
    assert ScanProgress(fraction=None).eta_seconds(30) is None


def test_output_sink_filters_and_dedupes(tmp_path) -> None:
    out = tmp_path / "out.txt"
    sink = OutputSink(out, options=ScrapeOptions(keywords=["visa"], limit=0), fmt="txt")
    assert sink.consider(_datum(1, "visa 4111111111111111")) is True
    assert sink.consider(_datum(1, "visa duplicate id")) is False
    assert sink.consider(_datum(2, "no keyword here")) is False
    sink.close()

    assert out.read_text(encoding="utf-8").splitlines() == ["visa 4111111111111111"]
    assert sink.result.exported == 1
    assert sink.result.scanned == 3


def test_output_sink_writes_valid_json(tmp_path) -> None:
    out = tmp_path / "out.json"
    sink = OutputSink(out, options=ScrapeOptions(), fmt="json")
    sink.consider(_datum(1, "one"))
    sink.consider(_datum(2, "two"))
    sink.close()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert [row["text"] for row in payload] == ["one", "two"]


def test_output_sink_rejects_unknown_format(tmp_path) -> None:
    with pytest.raises(ValueError):
        OutputSink(tmp_path / "x.pdf", options=ScrapeOptions(), fmt="pdf")


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(5, "5s"), (65, "1m 05s"), (3700, "1h 01m"), (None, "—")],
)
def test_format_duration(seconds, expected) -> None:
    assert format_duration(seconds) == expected
