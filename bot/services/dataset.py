"""Dataset search, grouping and export over authorized files.

Records are either CSV rows or delimiter-separated text lines. Everything is
streamed, and values shown in the UI are masked when they look like a PAN.
"""

from __future__ import annotations

import csv
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from bot.services.csv_tool import detect_encoding, inspect_csv
from bot.services.filetypes import is_csv
from bot.services.luhn import mask_pans

ProgressFn = Callable[[int], None]

SEARCH_MODES = {"contains", "prefix", "exact"}
JOIN_CSV = " | "


@dataclass(slots=True)
class DatasetInfo:
    kind: str  # "csv" | "text"
    delimiter: str | None
    header: list[str] | None
    has_header: bool
    columns: int = 0


@dataclass(slots=True)
class SearchResult:
    scanned: int = 0
    matches: int = 0
    samples: list[str] = field(default_factory=list)


def inspect_dataset(path: str | Path) -> DatasetInfo:
    source = Path(path)
    if is_csv(source.name):
        csv_info = inspect_csv(source)
        return DatasetInfo(
            kind="csv",
            delimiter=csv_info.delimiter,
            header=csv_info.header if csv_info.has_header else None,
            has_header=csv_info.has_header,
            columns=csv_info.columns,
        )

    with open(source, "r", encoding="utf-8-sig", errors="replace") as handle:
        first = handle.readline().rstrip("\r\n")
    if "|" in first:
        delimiter: str | None = "|"
    elif "\t" in first:
        delimiter = "\t"
    elif ";" in first:
        delimiter = ";"
    else:
        delimiter = None
    columns = len(first.split(delimiter)) if delimiter else 1
    return DatasetInfo("text", delimiter, None, False, columns)


def iter_records(path: str | Path, info: DatasetInfo) -> Iterator[list[str]]:
    source = Path(path)
    encoding = detect_encoding(source)
    if info.kind == "csv":
        with open(source, "r", encoding=encoding, errors="replace", newline="") as handle:
            reader = csv.reader(handle, delimiter=info.delimiter or ",")
            for index, row in enumerate(reader):
                if index == 0 and info.has_header:
                    continue
                yield row
    else:
        with open(source, "r", encoding=encoding, errors="replace", newline=None) as handle:
            for raw in handle:
                line = raw.rstrip("\r\n")
                if not line:
                    continue
                yield line.split(info.delimiter) if info.delimiter else [line]


def count_records(path: str | Path, info: DatasetInfo) -> int:
    return sum(1 for _ in iter_records(path, info))


def field_of(record: list[str], index: int | None) -> str:
    if index is None:
        return JOIN_CSV.join(record)
    if 0 <= index < len(record):
        return record[index]
    return ""


def record_to_line(record: list[str], info: DatasetInfo) -> str:
    if info.kind == "csv":
        return JOIN_CSV.join(record)
    return (info.delimiter or " ").join(record)


def detect_field(header: list[str] | None, candidates: set[str]) -> int | None:
    if not header:
        return None
    lowered = [name.strip().lower() for name in header]
    for candidate in candidates:
        if candidate in lowered:
            return lowered.index(candidate)
    return None


def search_to_file(
    src: str | Path,
    out: str | Path,
    *,
    info: DatasetInfo,
    query: str,
    mode: str = "contains",
    field_index: int | None = None,
    case_sensitive: bool = False,
    limit: int = 0,
    sample_size: int = 10,
    on_progress: ProgressFn | None = None,
) -> SearchResult:
    """Write matching records to ``out``. Returns scan/match statistics."""
    if mode not in SEARCH_MODES:
        raise ValueError(f"Unknown search mode: {mode}")

    destination = Path(out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    needle = query if case_sensitive else query.casefold()
    result = SearchResult()
    processed = 0

    with open(destination, "w", encoding="utf-8", newline="\n") as writer:
        for record in iter_records(src, info):
            processed += 1
            result.scanned += 1
            value = field_of(record, field_index)
            haystack = value if case_sensitive else value.casefold()
            if mode == "exact":
                matched = haystack == needle
            elif mode == "prefix":
                matched = haystack.startswith(needle)
            else:
                matched = needle in haystack

            if matched:
                line = record_to_line(record, info)
                writer.write(line + "\n")
                result.matches += 1
                if len(result.samples) < sample_size:
                    result.samples.append(mask_pans(line)[:120])
                if limit and result.matches >= limit:
                    break
            if on_progress:
                on_progress(processed)
    return result


def group_counts(
    src: str | Path,
    info: DatasetInfo,
    field_index: int | None,
    *,
    limit: int | None = None,
    on_progress: ProgressFn | None = None,
) -> list[tuple[str, int]]:
    """Count records per distinct field value, most common first."""
    counter: Counter[str] = Counter()
    processed = 0
    for record in iter_records(src, info):
        processed += 1
        value = field_of(record, field_index).strip()
        if value:
            counter[value] += 1
        if on_progress:
            on_progress(processed)
    return counter.most_common(limit) if limit else counter.most_common()


def export_group(
    src: str | Path,
    out: str | Path,
    *,
    info: DatasetInfo,
    field_index: int | None,
    value: str,
    case_sensitive: bool = False,
    on_progress: ProgressFn | None = None,
) -> int:
    """Write every record whose field equals ``value``. Returns the count."""
    destination = Path(out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    target = value if case_sensitive else value.casefold()
    written = 0
    processed = 0

    with open(destination, "w", encoding="utf-8", newline="\n") as writer:
        for record in iter_records(src, info):
            processed += 1
            current = field_of(record, field_index)
            if (current if case_sensitive else current.casefold()) == target:
                writer.write(record_to_line(record, info) + "\n")
                written += 1
            if on_progress:
                on_progress(processed)
    return written
