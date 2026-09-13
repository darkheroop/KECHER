"""Country flag helpers (no external services)."""

from __future__ import annotations

import re

# Regional-indicator letters: A=0x1F1E6.
_INDICATOR_BASE = 0x1F1E6
_TWO_LETTERS = re.compile(r"^[A-Za-z]{2}$")


def flag_for(value: str) -> str:
    """Return a flag emoji for a 2-letter country code, else an empty string."""
    code = (value or "").strip()
    if not _TWO_LETTERS.match(code):
        return ""
    letters = code.upper()
    return "".join(chr(_INDICATOR_BASE + (ord(ch) - ord("A"))) for ch in letters)


def country_label(value: str) -> str:
    """Human-readable label: flag + code/name as present in the dataset."""
    flag = flag_for(value)
    return f"{flag} {value}".strip()
