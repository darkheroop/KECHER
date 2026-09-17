"""Scrape engine primitives: date windowing, streaming output and progress.

The engine is deliberately free of Telegram networking so it can be unit
tested. :mod:`bot.services.telegram_client` wires these primitives to Telethon.
"""

from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from bot.services.scraper import (
    EXPORT_FORMATS,
    MessageDatum,
    ScrapeOptions,
    ScrapeResult,
    _datum_to_dict,
    _text_line,
    message_matches,
)

WORKERS = 3
SCAN_INTERVAL = 1.3


@dataclass(slots=True)
class ScanProgress:
    """Snapshot handed to the UI callback while a scrape runs."""

    scanned: int = 0
    matched: int = 0
    fraction: float | None = None

    def eta_seconds(self, elapsed: float) -> float | None:
        if not self.fraction or self.fraction <= 0:
            return None
        total = elapsed / self.fraction
        remaining = total - elapsed
        return max(0.0, remaining)


class ScanState:
    """Mutable counters shared by all workers of one source."""

    __slots__ = ("lower", "upper", "scanned", "matched", "_oldest")

    def __init__(self, lower: datetime | None, upper: datetime | None) -> None:
        self.lower = lower
        self.upper = upper
        self.scanned = 0
        self.matched = 0
        self._oldest: datetime | None = None

    def bump(self, date: datetime | None) -> None:
        self.scanned += 1
        if date is not None and (self._oldest is None or date < self._oldest):
            self._oldest = date

    def fraction(self) -> float | None:
        """How much of the requested date window has been walked (0..1)."""
        if not self.lower or not self.upper or self._oldest is None:
            return None
        total = (self.upper - self.lower).total_seconds()
        if total <= 0:
            return None
        done = (self.upper - self._oldest).total_seconds()
        return max(0.0, min(1.0, done / total))


def plan_windows(
    lower: datetime | None, upper: datetime | None, workers: int
) -> list[tuple[datetime | None, datetime | None]]:
    """Split a date range into ~equal windows so workers can run in parallel.

    Sharding only happens when both bounds are known: without a lower bound
    there is no safe way to divide history.
    """
    if lower is None or upper is None or workers <= 1:
        return [(lower, upper)]
    span = upper - lower
    if span <= timedelta(0):
        return [(lower, upper)]
    step = span / workers
    windows: list[tuple[datetime | None, datetime | None]] = []
    for index in range(workers):
        lo = lower + step * index
        hi = upper if index == workers - 1 else lower + step * (index + 1)
        windows.append((lo, hi))
    return windows


class OutputSink:
    """Filter ``MessageDatum`` records and stream them straight to disk.

    Streaming keeps memory flat on huge histories and de-duplicates by message
    id so parallel windows (or overlapping keyword searches) never double-write.
    """

    def __init__(self, out: str | Path, *, options: ScrapeOptions, fmt: str = "txt") -> None:
        if fmt not in EXPORT_FORMATS:
            raise ValueError(f"Unsupported export format: {fmt}")
        self.path = Path(out)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.options = options
        self.fmt = fmt
        self.scanned = 0
        self.exported = 0
        self._seen: set[int] = set()
        self._handle = None
        self._writer = None
        self._first_json = True
        self._open()

    def _open(self) -> None:
        if self.fmt == "csv":
            self._handle = self.path.open("w", encoding="utf-8", newline="")
            self._writer = csv.DictWriter(
                self._handle,
                fieldnames=[
                    "id",
                    "date",
                    "sender_id",
                    "text",
                    "media_type",
                    "file_name",
                    "file_size",
                ],
            )
            self._writer.writeheader()
        elif self.fmt == "txt":
            self._handle = self.path.open("w", encoding="utf-8", newline="\n")
        else:  # json array streamed incrementally
            self._handle = self.path.open("w", encoding="utf-8", newline="\n")
            self._handle.write("[\n")

    def consider(self, datum: MessageDatum) -> bool:
        """Count, de-duplicate, filter and write a single message."""
        self.scanned += 1
        if datum.id in self._seen:
            return False
        self._seen.add(datum.id)
        if not message_matches(datum, self.options):
            return False
        self._write(datum)
        self.exported += 1
        return True

    def _write(self, datum: MessageDatum) -> None:
        assert self._handle is not None
        if self.fmt == "txt":
            self._handle.write(_text_line(datum, text_only=self.options.text_only) + "\n")
        elif self.fmt == "csv":
            assert self._writer is not None
            self._writer.writerow(_datum_to_dict(datum))
        else:
            prefix = "" if self._first_json else ",\n"
            self._first_json = False
            self._handle.write(prefix + json.dumps(_datum_to_dict(datum), ensure_ascii=False))

    def close(self) -> None:
        if self._handle is None:
            return
        if self.fmt == "json":
            self._handle.write("\n]\n")
        self._handle.close()
        self._handle = None

    @property
    def result(self) -> ScrapeResult:
        return ScrapeResult(scanned=self.scanned, exported=self.exported, path=self.path)


class ScanNotifier:
    """Throttled bridge between the engine and an async UI callback."""

    def __init__(self, callback=None, *, interval: float = SCAN_INTERVAL) -> None:  # noqa: ANN001
        self._callback = callback
        self._interval = interval
        self._last = float("-inf")

    async def tick(self, state: ScanState, sink: OutputSink, *, force: bool = False) -> None:
        if self._callback is None:
            return
        now = time.monotonic()
        if not force and now - self._last < self._interval:
            return
        self._last = now
        progress = ScanProgress(
            scanned=state.scanned, matched=sink.exported, fraction=state.fraction()
        )
        result = self._callback(progress)
        if hasattr(result, "__await__"):
            await result


def format_duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "—"
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"
