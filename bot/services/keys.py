"""Access-key code generation and duration parsing."""

from __future__ import annotations

import math
import re
import secrets

# No 0/O/1/I to avoid transcription errors.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
DEFAULT_PREFIX = "KECH"

_SECONDS = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 604800,
    "mo": 2592000,   # 30 days
    "y": 31536000,   # 365 days
}
_TOKEN = re.compile(r"(\d+(?:\.\d+)?)\s*(mo|[smhdwy])", re.IGNORECASE)


def generate_code(*, prefix: str = DEFAULT_PREFIX, groups: int = 3, size: int = 4) -> str:
    """Return a human-friendly code like ``KECH-7F3K-9QX2-M2PL``."""
    parts = [
        "".join(secrets.choice(ALPHABET) for _ in range(size)) for _ in range(groups)
    ]
    head = f"{prefix.upper()}-" if prefix else ""
    return head + "-".join(parts)


def normalize_code(text: str) -> str:
    """Uppercase and strip whitespace so users can paste loosely."""
    return "".join((text or "").split()).upper()


def parse_duration_minutes(text: str) -> int | None:
    """Parse a duration into whole minutes.

    Accepts a bare number (days) or compound unit expressions::

        1         -> 1 day
        30m       -> 30 minutes
        12h       -> 12 hours
        2w        -> 2 weeks
        1mo       -> 30 days
        1y        -> 365 days
        1d12h     -> 1 day 12 hours
        2w 3d 4h  -> 2 weeks, 3 days, 4 hours
    """
    raw = (text or "").strip().lower()
    if not raw:
        return None

    total_seconds = 0.0
    matched = False
    for number, unit in _TOKEN.findall(raw):
        matched = True
        total_seconds += float(number) * _SECONDS[unit.lower()]

    if not matched:
        try:
            days = float(raw)
        except ValueError:
            return None
        if days <= 0:
            return None
        return max(1, math.ceil(days * 1440))

    if total_seconds <= 0:
        return None
    return max(1, math.ceil(total_seconds / 60))


def format_duration(minutes: int) -> str:
    """Human label for a minute count, e.g. ``1 day 12 hours``."""
    minutes = max(1, int(minutes))
    if minutes % 10080 == 0:
        weeks = minutes // 10080
        return f"{weeks} week" + ("s" if weeks != 1 else "")
    days, rem = divmod(minutes, 1440)
    hours, mins = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days} day" + ("s" if days != 1 else ""))
    if hours:
        parts.append(f"{hours} hour" + ("s" if hours != 1 else ""))
    if mins or not parts:
        parts.append(f"{mins} min" + ("s" if mins != 1 else ""))
    return " ".join(parts)
