"""Streaming text operations: split, clean, deduplicate, merge.

All functions read line-by-line so multi-gigabyte files do not have to fit in
RAM. The only exception is optional sorting, which necessarily buffers the
result (documented on :func:`clean_file` / :func:`merge_files`).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from bot.services.luhn import extract_pan, find_pan_candidates, luhn_valid

ProgressFn = Callable[[int], None]

DEFAULT_ENCODING = "utf-8-sig"
WRITE_ENCODING = "utf-8"
BATCH_SIZE = 2048


@dataclass(slots=True)
class SplitResult:
    files: list[Path] = field(default_factory=list)
    lines: int = 0


@dataclass(slots=True)
class CleanOptions:
    remove_empty: bool = True
    trim: bool = True
    separator: str | None = None
    remove_malformed: bool = False
    min_fields: int = 1
    sort: bool = False
    dedup: bool = False
    normalize_dupes: bool = False
    # Offline Luhn check. ``luhn=True`` scans every PAN-like number in the line
    # ("check all"); ``luhn_field`` restricts the check to one field.
    luhn: bool = False
    luhn_field: int | None = None  # 1-based field index, requires separator/pool


@dataclass(slots=True)
class CleanResult:
    total: int = 0
    passed: int = 0
    rejected: int = 0
    duplicates: int = 0
    empty: int = 0
    # Offline Luhn verification counters (synthetic/test data only).
    luhn_checked: int = 0
    luhn_valid: int = 0
    luhn_invalid: int = 0

    @property
    def removed(self) -> int:
        return self.rejected + self.duplicates + self.empty


@dataclass(slots=True)
class DedupResult:
    original: int = 0
    unique: int = 0
    removed: int = 0


@dataclass(slots=True)
class MergeResult:
    files: int = 0
    total: int = 0
    written: int = 0
    duplicates: int = 0


# --------------------------------------------------------------------------- #
# Low-level helpers
# --------------------------------------------------------------------------- #
def iter_lines(path: str | Path, *, encoding: str = DEFAULT_ENCODING) -> Iterator[str]:
    """Yield raw lines (with line endings) from ``path``."""
    with open(path, "r", encoding=encoding, errors="replace", newline=None) as handle:
        yield from handle


def count_lines(path: str | Path, *, encoding: str = DEFAULT_ENCODING) -> int:
    return sum(1 for _ in iter_lines(path, encoding=encoding))


def _normalize_key(text: str) -> str:
    return " ".join(text.split()).casefold()


def _open_write(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return open(path, "w", encoding=WRITE_ENCODING, newline="\n")


# --------------------------------------------------------------------------- #
# Split
# --------------------------------------------------------------------------- #
def split_file(
    src: str | Path,
    out_dir: str | Path,
    *,
    mode: str,
    value: int,
    on_progress: ProgressFn | None = None,
) -> SplitResult:
    """Split ``src`` into numbered files.

    ``mode`` is one of ``lines`` (N lines/file), ``parts`` (N files) or
    ``size`` (approx. N bytes/file).
    """
    if value < 1:
        raise ValueError("Split value must be >= 1")
    if mode not in {"lines", "parts", "size"}:
        raise ValueError(f"Unknown split mode: {mode}")

    source = Path(src)
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stem, ext = source.stem, source.suffix or ".txt"

    per_lines: int | None = None
    if mode == "parts":
        total_lines = count_lines(source)
        per_lines = max(1, math.ceil(total_lines / value)) if total_lines else 1

    result = SplitResult()
    handle = None

    def roll() -> None:
        nonlocal handle
        if handle is not None:
            handle.close()
        index = len(result.files) + 1
        target = directory / f"{stem}_{index:03d}{ext}"
        result.files.append(target)
        handle = _open_write(target)

    def filled(count: int, size: int) -> bool:
        if mode == "lines":
            return count >= value
        if mode == "parts":
            return count >= (per_lines or 1)
        return size >= value

    processed = 0
    count = 0
    size = 0
    roll()
    try:
        for line in iter_lines(source):
            encoded = len(line.encode(WRITE_ENCODING))
            processed += encoded
            if filled(count, size):
                roll()
                count = 0
                size = 0
            assert handle is not None
            handle.write(line)
            count += 1
            size += encoded
            result.lines += 1
            if on_progress:
                on_progress(processed)
    finally:
        if handle is not None:
            handle.close()
    return result


# --------------------------------------------------------------------------- #
# Clean
# --------------------------------------------------------------------------- #
def _luhn_candidates(
    text: str, fields: list[str] | None, options: CleanOptions
) -> list[str]:
    """Return the number(s) to Luhn-check for a line.

    With ``luhn_field`` set, only that field is checked; otherwise every
    PAN-like number in the line is checked ("check all").
    """
    if options.luhn_field is not None:
        pool = fields if fields is not None else text.split()
        index = options.luhn_field - 1
        if index < 0 or index >= len(pool):
            return []
        pan = extract_pan(pool[index])
        return [pan] if pan else []
    return find_pan_candidates(text)


def clean_file(
    src: str | Path,
    out: str | Path,
    options: CleanOptions,
    *,
    on_progress: ProgressFn | None = None,
) -> CleanResult:
    """Apply modular cleaning rules and write the result to ``out``.

    When ``options.luhn`` is enabled, every PAN-like number in each line is
    checked locally ("check all"); a line passes if at least one candidate is
    Luhn-valid and is rejected when it contains numbers but none are valid.
    This is a purely mathematical test and contacts no payment service.

    Note: when ``options.sort`` is set the surviving lines are buffered in
    memory before sorting, since a line-by-line sort is not possible.
    """
    source = Path(src)
    destination = Path(out)
    result = CleanResult()
    seen: set[str] = set()
    buffer: list[str] = []
    processed = 0
    luhn_enabled = options.luhn or options.luhn_field is not None

    handle = _open_write(destination)
    try:
        for raw in iter_lines(source):
            processed += len(raw.encode(WRITE_ENCODING))
            result.total += 1
            text = raw.rstrip("\r\n")
            if options.trim:
                text = text.strip()

            fields: list[str] | None = None
            if options.separator is not None:
                fields = [
                    f.strip() if options.trim else f
                    for f in text.split(options.separator)
                ]
                if not text and options.remove_empty:
                    result.empty += 1
                    continue
                if options.remove_malformed and len(fields) < options.min_fields:
                    result.rejected += 1
                    continue
                text = options.separator.join(fields)
            else:
                if not text:
                    if options.remove_empty:
                        result.empty += 1
                        continue
                    if options.remove_malformed:
                        result.rejected += 1
                        continue

            if luhn_enabled:
                candidates = _luhn_candidates(text, fields, options)
                result.luhn_checked += 1
                if not candidates or not any(luhn_valid(c) for c in candidates):
                    result.luhn_invalid += 1
                    result.rejected += 1
                    continue
                result.luhn_valid += 1

            if options.dedup or options.normalize_dupes:
                key = _normalize_key(text) if options.normalize_dupes else text
                if key in seen:
                    result.duplicates += 1
                    continue
                seen.add(key)

            result.passed += 1
            buffer.append(text)
            if not options.sort and len(buffer) >= BATCH_SIZE:
                handle.write("\n".join(buffer) + "\n")
                buffer.clear()
            if on_progress:
                on_progress(processed)

        if options.sort:
            buffer.sort()
        if buffer:
            handle.write("\n".join(buffer) + "\n")
    finally:
        handle.close()
    return result


# --------------------------------------------------------------------------- #
# Deduplicate
# --------------------------------------------------------------------------- #
def dedup_file(
    src: str | Path,
    out: str | Path,
    *,
    normalize: bool = False,
    on_progress: ProgressFn | None = None,
) -> DedupResult:
    """Write ``src`` to ``out`` without duplicate lines, preserving order."""
    source = Path(src)
    destination = Path(out)
    result = DedupResult()
    seen: set[str] = set()
    buffer: list[str] = []
    processed = 0

    handle = _open_write(destination)
    try:
        for raw in iter_lines(source):
            processed += len(raw.encode(WRITE_ENCODING))
            result.original += 1
            text = raw.rstrip("\r\n")
            key = _normalize_key(text) if normalize else text
            if key in seen:
                result.removed += 1
            else:
                seen.add(key)
                buffer.append(text)
                result.unique += 1
                if len(buffer) >= BATCH_SIZE:
                    handle.write("\n".join(buffer) + "\n")
                    buffer.clear()
            if on_progress:
                on_progress(processed)
        if buffer:
            handle.write("\n".join(buffer) + "\n")
    finally:
        handle.close()
    return result


# --------------------------------------------------------------------------- #
# Merge
# --------------------------------------------------------------------------- #
def merge_files(
    paths: list[str | Path],
    out: str | Path,
    *,
    dedup: bool = False,
    normalize: bool = False,
    sort: bool = False,
    on_progress: ProgressFn | None = None,
) -> MergeResult:
    """Concatenate files, optionally de-duplicating and/or sorting."""
    sources = [Path(p) for p in paths]
    destination = Path(out)
    result = MergeResult(files=len(sources))

    total_bytes = 0
    for source in sources:
        try:
            total_bytes += source.stat().st_size
        except OSError:
            pass

    seen: set[str] = set()
    buffer: list[str] = []
    processed = 0

    handle = _open_write(destination)
    try:
        for source in sources:
            for raw in iter_lines(source):
                processed += len(raw.encode(WRITE_ENCODING))
                result.total += 1
                text = raw.rstrip("\r\n")
                if dedup or normalize:
                    key = _normalize_key(text) if normalize else text
                    if key in seen:
                        result.duplicates += 1
                        continue
                    seen.add(key)
                buffer.append(text)
                result.written += 1
                if not sort and len(buffer) >= BATCH_SIZE:
                    handle.write("\n".join(buffer) + "\n")
                    buffer.clear()
                if on_progress:
                    on_progress(processed)
        if sort:
            buffer.sort()
        if buffer:
            handle.write("\n".join(buffer) + "\n")
    finally:
        handle.close()
    return result
