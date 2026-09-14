"""File-type helpers.

Detection is extension-based (no native libmagic dependency), which is
sufficient because we only ever act on explicit, whitelisted formats.
"""

from __future__ import annotations

from pathlib import Path

DOC_EXTS = {".doc", ".docx"}
CSV_EXTS = {".csv", ".tsv"}
TEXT_EXTS = {".txt", ".text", ".log", ".dat", ".list", ".lst", ".csv", ".tsv"}
# Telegram Desktop chat exports (imported offline via /extract).
EXPORT_EXTS = {".html", ".htm", ".json"}

# Everything the bot may ingest at all.
ALLOWED_EXTS = DOC_EXTS | TEXT_EXTS | EXPORT_EXTS


def ext_of(name: str) -> str:
    return Path(name).suffix.lower()


def is_doc(name: str) -> bool:
    return ext_of(name) in DOC_EXTS


def is_csv(name: str) -> bool:
    return ext_of(name) in CSV_EXTS


def is_text(name: str) -> bool:
    return ext_of(name) in TEXT_EXTS


def is_export(name: str) -> bool:
    return ext_of(name) in EXPORT_EXTS


def is_ingestible(name: str) -> bool:
    return ext_of(name) in ALLOWED_EXTS


def as_txt_name(name: str) -> str:
    """Return a ``.txt`` output name derived from ``name``."""
    stem = Path(name).stem or "output"
    return f"{stem}.txt"
