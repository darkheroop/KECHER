"""CSV inspection and CSV -> TXT conversion (streaming)."""

from __future__ import annotations

import csv
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

ProgressFn = Callable[[int], None]

SAMPLE_BYTES = 65536
CANDIDATE_DELIMITERS = ",;\t|"


@dataclass(slots=True)
class CsvInfo:
    rows: int
    columns: int
    delimiter: str
    has_header: bool
    header: list[str] = field(default_factory=list)
    encoding: str = "utf-8-sig"


def detect_encoding(path: str | Path) -> str:
    raw = Path(path).read_bytes()[:SAMPLE_BYTES]
    try:
        raw.decode("utf-8-sig")
        return "utf-8-sig"
    except UnicodeDecodeError:
        pass
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(raw).best()
        if best is not None and best.encoding:
            return best.encoding
    except Exception:  # noqa: BLE001 - detection must never break ingestion
        pass
    return "latin-1"


def sniff_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=CANDIDATE_DELIMITERS).delimiter
    except csv.Error:
        return ","


def sniff_has_header(sample: str, delimiter: str) -> bool:
    try:
        return bool(csv.Sniffer().has_header(sample))
    except csv.Error:
        return True


def inspect_csv(path: str | Path) -> CsvInfo:
    """Return row/column counts, delimiter and header without loading the file."""
    source = Path(path)
    encoding = detect_encoding(source)
    with open(source, "r", encoding=encoding, errors="replace", newline="") as handle:
        sample = handle.read(SAMPLE_BYTES)
        handle.seek(0)
        delimiter = sniff_delimiter(sample)
        has_header = sniff_has_header(sample, delimiter)

        reader = csv.reader(handle, delimiter=delimiter)
        rows = 0
        columns = 0
        header: list[str] = []
        for row in reader:
            if rows == 0:
                header = list(row)
            rows += 1
            columns = max(columns, len(row))

    return CsvInfo(
        rows=rows,
        columns=columns,
        delimiter=delimiter,
        has_header=has_header,
        header=header,
        encoding=encoding,
    )


def parse_column_selection(text: str, columns: int) -> list[int]:
    """Parse a 1-based selection like ``"1,3,5"`` into 0-based indices."""
    indices: list[int] = []
    for token in text.replace(" ", "").split(","):
        if not token:
            continue
        if not token.isdigit():
            raise ValueError(f"Invalid column: {token!r}")
        value = int(token)
        if value < 1 or value > columns:
            raise ValueError(f"Column {value} out of range (1-{columns})")
        zero_based = value - 1
        if zero_based not in indices:
            indices.append(zero_based)
    if not indices:
        raise ValueError("No columns selected")
    return indices


def csv_to_txt(
    src: str | Path,
    out: str | Path,
    *,
    columns: list[int] | None = None,
    delimiter: str | None = None,
    join_with: str = " | ",
    include_header: bool = True,
    on_progress: ProgressFn | None = None,
) -> int:
    """Convert a CSV file to delimited TXT. Returns the number of rows written."""
    source = Path(src)
    destination = Path(out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoding = detect_encoding(source)
    written = 0

    with open(source, "r", encoding=encoding, errors="replace", newline="") as handle:
        sample = handle.read(SAMPLE_BYTES)
        handle.seek(0)
        sep = delimiter or sniff_delimiter(sample)
        reader = csv.reader(handle, delimiter=sep)

        with open(destination, "w", encoding="utf-8", newline="\n") as writer:
            for index, row in enumerate(reader):
                if index == 0 and not include_header:
                    continue
                if columns is not None:
                    selected = [row[c] for c in columns if 0 <= c < len(row)]
                else:
                    selected = list(row)
                writer.write(join_with.join(selected) + "\n")
                written += 1
                if on_progress:
                    on_progress(written)
    return written
