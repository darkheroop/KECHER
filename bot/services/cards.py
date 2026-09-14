"""Wedding-card serial file operations.

Card line format (your custom format -- do not change):
    <16-digit serial>|<2-digit date>|<2 or 4 digit time>|<3 or 4 digit invited>

Examples:
    1234567891234567|02|2028|555
    1234567891234567|02|28|555

Fields are pipe-separated; surrounding spaces/tabs are tolerated. Only digit
counts are validated (no calendar/range checks).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from bot.services.luhn import luhn_valid

ProgressFn = Callable[[int], None]

# serial(16) | date(2) | time(2 or 4) | invited(3 or 4)
CARD_RE = re.compile(
    r"^\s*(\d{16})\s*\|\s*(\d{2})\s*\|\s*(\d{2}|\d{4})\s*\|\s*(\d{3}|\d{4})\s*$"
)
SERIAL_RE = re.compile(r"^\s*(\d{16})\s*$")

READ_ENCODING = "utf-8-sig"
WRITE_ENCODING = "utf-8"


@dataclass(slots=True)
class Card:
    serial: str
    date: str
    time: str
    invited: str


@dataclass(slots=True)
class CleanReport:
    total: int = 0
    valid: int = 0
    invalid: int = 0


@dataclass(slots=True)
class LiveReport:
    total: int = 0
    checked: int = 0
    valid: int = 0
    invalid: int = 0


@dataclass(slots=True)
class CountryReport:
    keyword: str = ""
    matches: int = 0
    lines: int = 0


@dataclass(slots=True)
class SplitReport:
    parts: list[Path] = None  # type: ignore[assignment]
    lines: int = 0

    def __post_init__(self) -> None:
        if self.parts is None:
            self.parts = []


@dataclass(slots=True)
class DedupReport:
    total: int = 0
    unique: int = 0
    removed: int = 0


@dataclass(slots=True)
class MergeReport:
    files: int = 0
    lines: int = 0


# --------------------------------------------------------------------------- #
# Parsing / formatting
# --------------------------------------------------------------------------- #
def parse_card(line: str) -> Card | None:
    match = CARD_RE.match(line or "")
    if not match:
        return None
    serial, date, time, invited = match.groups()
    return Card(serial=serial, date=date, time=time, invited=invited)


def format_card(card: Card) -> str:
    return f"{card.serial}|{card.date}|{card.time}|{card.invited}"


def extract_serial(line: str) -> str | None:
    """Return the 16-digit serial from a card line or a bare serial line."""
    card = parse_card(line)
    if card is not None:
        return card.serial
    match = SERIAL_RE.match(line or "")
    return match.group(1) if match else None


def iter_lines(path: str | Path) -> Iterator[str]:
    with open(path, "r", encoding=READ_ENCODING, errors="replace", newline=None) as fh:
        for raw in fh:
            yield raw.rstrip("\r\n")


def _open_write(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return open(path, "w", encoding=WRITE_ENCODING, newline="\n")


# --------------------------------------------------------------------------- #
# /clean  -- extract valid card records
# --------------------------------------------------------------------------- #
def clean_cards(
    src: str | Path, out: str | Path, *, on_progress: ProgressFn | None = None
) -> CleanReport:
    report = CleanReport()
    handle = _open_write(Path(out))
    try:
        for index, line in enumerate(iter_lines(src), start=1):
            report.total += 1
            card = parse_card(line)
            if card is None:
                report.invalid += 1
            else:
                report.valid += 1
                handle.write(format_card(card) + "\n")
            if on_progress:
                on_progress(index)
    finally:
        handle.close()
    return report


# --------------------------------------------------------------------------- #
# /live  -- Luhn check on the serials, keep the valid ones
# --------------------------------------------------------------------------- #
def live_cards(
    src: str | Path, out: str | Path, *, on_progress: ProgressFn | None = None
) -> LiveReport:
    """Keep the full card line for every serial that passes the Luhn check."""
    report = LiveReport()
    handle = _open_write(Path(out))
    try:
        for index, line in enumerate(iter_lines(src), start=1):
            report.total += 1
            serial = extract_serial(line)
            if serial is None:
                continue
            report.checked += 1
            if luhn_valid(serial):
                report.valid += 1
                handle.write(line.strip() + "\n")
            else:
                report.invalid += 1
            if on_progress:
                on_progress(index)
    finally:
        handle.close()
    return report


# --------------------------------------------------------------------------- #
# /country <keyword>  -- card lines directly above a keyword line
# --------------------------------------------------------------------------- #
def country_cards(
    src: str | Path, out: str | Path, keyword: str, *, on_progress: ProgressFn | None = None
) -> CountryReport:
    report = CountryReport(keyword=keyword)
    needle = (keyword or "").strip().casefold()
    lines = list(iter_lines(src))
    collected: list[str] = []

    for index, line in enumerate(lines):
        if needle and needle in line.casefold():
            report.matches += 1
            # Walk upward collecting the consecutive card lines.
            block: list[str] = []
            cursor = index - 1
            while cursor >= 0 and parse_card(lines[cursor]) is not None:
                block.append(lines[cursor])
                cursor -= 1
            collected.extend(reversed(block))
        if on_progress:
            on_progress(index + 1)

    handle = _open_write(Path(out))
    try:
        for line in collected:
            handle.write(line + "\n")
    finally:
        handle.close()
    report.lines = len(collected)
    return report


# --------------------------------------------------------------------------- #
# /split N  -- N files with (almost) equal line counts
# --------------------------------------------------------------------------- #
def split_cards(
    src: str | Path,
    out_dir: str | Path,
    parts: int,
    *,
    on_progress: ProgressFn | None = None,
) -> SplitReport:
    if parts < 1:
        raise ValueError("Parts must be >= 1")
    source = Path(src)
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stem = source.stem

    lines = list(iter_lines(source))
    report = SplitReport(lines=len(lines))
    if not lines:
        target = directory / f"{stem}_1.txt"
        target.write_text("", encoding=WRITE_ENCODING)
        report.parts.append(target)
        return report

    parts = min(parts, len(lines))
    base, remainder = divmod(len(lines), parts)

    cursor = 0
    for index in range(parts):
        size = base + (1 if index < remainder else 0)
        chunk = lines[cursor : cursor + size]
        cursor += size
        target = directory / f"{stem}_{index + 1}.txt"
        target.write_text("\n".join(chunk) + "\n", encoding=WRITE_ENCODING)
        report.parts.append(target)
        if on_progress:
            on_progress(cursor)
    return report


# --------------------------------------------------------------------------- #
# /dedup  -- remove exact duplicate lines (order preserved)
# --------------------------------------------------------------------------- #
def dedup_cards(
    src: str | Path, out: str | Path, *, on_progress: ProgressFn | None = None
) -> DedupReport:
    report = DedupReport()
    seen: set[str] = set()
    handle = _open_write(Path(out))
    try:
        for index, line in enumerate(iter_lines(src), start=1):
            report.total += 1
            if line in seen:
                report.removed += 1
            else:
                seen.add(line)
                report.unique += 1
                handle.write(line + "\n")
            if on_progress:
                on_progress(index)
    finally:
        handle.close()
    return report


# --------------------------------------------------------------------------- #
# /merge  -- concatenate queued TXT files in order
# --------------------------------------------------------------------------- #
def merge_files(
    paths: list[str | Path],
    out: str | Path,
    *,
    on_progress: ProgressFn | None = None,
) -> MergeReport:
    sources = [Path(p) for p in paths]
    report = MergeReport(files=len(sources))
    handle = _open_write(Path(out))
    try:
        for source in sources:
            for line in iter_lines(source):
                handle.write(line + "\n")
                report.lines += 1
                if on_progress:
                    on_progress(report.lines)
    finally:
        handle.close()
    return report
