"""Offline Luhn check for authorized synthetic/test data.

This is a purely mathematical, local test. It never contacts a payment
processor and performs no authorization, balance lookup, or card validation
against any external service.

Algorithm (ISO/IEC 7812 check digit):
    1. Starting from the rightmost digit and moving left,
    2. double every second digit;
    3. if doubling yields a value > 9, subtract 9;
    4. sum all digits;
    5. the number is valid when ``sum % 10 == 0``.
"""

from __future__ import annotations

import re

MIN_PAN_DIGITS = 12
MAX_PAN_DIGITS = 19

_NON_DIGITS = re.compile(r"\D+")

# A PAN-like run: 12-19 digits, optionally grouped with spaces/dashes.
# Lookarounds prevent the run from starting/ending inside a word (e.g. the
# "1" of "row1" must not merge into the following card number).
_PAN_PATTERN = re.compile(
    r"(?<![0-9A-Za-z])(?:\d[ -]?){11,18}\d(?![0-9A-Za-z])"
)


def extract_pan(field: str) -> str:
    """Return the digit-only candidate from a field, or "" if implausible."""
    digits = _NON_DIGITS.sub("", field or "")
    if MIN_PAN_DIGITS <= len(digits) <= MAX_PAN_DIGITS:
        return digits
    return ""


def find_pan_candidates(text: str) -> list[str]:
    """Find every PAN-like number inside ``text``, regardless of position.

    Separators such as spaces or dashes inside a number are normalized away.
    Used by the cleaner's "check all" mode so a line is analysed as a whole
    instead of assuming a fixed field layout.
    """
    candidates: list[str] = []
    for match in _PAN_PATTERN.finditer(text or ""):
        digits = _NON_DIGITS.sub("", match.group())
        if MIN_PAN_DIGITS <= len(digits) <= MAX_PAN_DIGITS and digits not in candidates:
            candidates.append(digits)
    return candidates


def luhn_valid(number: str) -> bool:
    """Return True if ``number`` (digits, spaces allowed) passes the Luhn test."""
    digits = [int(ch) for ch in number if ch.isdigit()]
    if len(digits) < 2:
        return False

    total = 0
    for index, digit in enumerate(reversed(digits)):
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def mask_pan(number: str, *, reveal_first: int = 6, reveal_last: int = 4) -> str:
    """Mask the middle digits of a PAN-like number for safe display."""
    digits = _NON_DIGITS.sub("", number or "")
    if len(digits) <= reveal_first + reveal_last:
        return "*" * len(digits)
    hidden = len(digits) - reveal_first - reveal_last
    return digits[:reveal_first] + "*" * hidden + digits[-reveal_last:]


def mask_pans(text: str) -> str:
    """Replace every PAN-like number in ``text`` with a masked form."""
    return _PAN_PATTERN.sub(lambda m: mask_pan(m.group()), text or "")
