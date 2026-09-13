"""Offline validation of authorized synthetic/test payment data.

THIS MODULE PERFORMS NO NETWORKING. It contains no HTTP client, no socket, and
no Telegram calls. It only applies local, mathematical and syntactic checks
(format, length, Luhn, local test-BIN metadata, expiry syntax, dataset
consistency). It never authorizes a card, checks a balance, or contacts any
payment network.

CVV/CVC, PINs and OTPs are explicitly out of scope: they are never read from
the input, stored, or reported.
"""

from __future__ import annotations

import csv
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from bot.services.dataset import DatasetInfo, field_of, iter_records
from bot.services.luhn import luhn_valid, mask_pan

ProgressFn = Callable[[int], None]

# --------------------------------------------------------------------------- #
# Local test-BIN metadata (no external lookups)
# --------------------------------------------------------------------------- #
# Curated prefixes of official provider *test* BINs used by their public
# sandboxes. This is static metadata, not a live BIN service.
TEST_BINS: dict[str, str] = {
    "411111": "Visa test",
    "424242": "Visa test",
    "400005": "Visa test",
    "401288": "Visa test",
    "555555": "Mastercard test",
    "510510": "Mastercard test",
    "222300": "Mastercard test",
    "378282": "Amex test",
    "371449": "Amex test",
    "601100": "Discover test",
    "601111": "Discover test",
    "305693": "Diners test",
    "356600": "JCB test",
}

# IIN prefix -> (network, valid lengths). Order matters (longest prefix first).
_IIN_RULES: list[tuple[tuple[str, ...], str, tuple[int, ...]]] = [
    (("34", "37"), "Amex", (15,)),
    (("51", "52", "53", "54", "55"), "Mastercard", (16,)),
    (("6011", "65", "644", "645", "646", "647", "648", "649"), "Discover", (16, 19)),
    (("35",), "JCB", (16, 19)),
    (("4",), "Visa", (13, 16, 19)),
]
_MIN_LENGTH, _MAX_LENGTH = 12, 19

_EXPIRY_PATTERNS = [
    re.compile(r"^(\d{2})/(\d{2}|\d{4})$"),
    re.compile(r"^(\d{2})-(\d{2}|\d{4})$"),
    re.compile(r"^(\d{4})$"),  # MMYY
]


@dataclass(slots=True)
class ValidationOptions:
    check_format: bool = True
    check_length: bool = True
    check_luhn: bool = True
    check_test_bin: bool = False
    check_expiry: bool = True
    flag_expired: bool = True


@dataclass(slots=True)
class PanCheck:
    digits: str
    format_ok: bool
    length_ok: bool
    luhn_ok: bool
    network: str
    test_bin_label: str | None = None


@dataclass(slots=True)
class ExpiryCheck:
    present: bool
    syntax_ok: bool
    expired: bool = False
    normalized: str = ""


@dataclass(slots=True)
class RecordFinding:
    index: int
    pan_masked: str
    status: str  # "valid" | "invalid"
    reasons: list[str] = field(default_factory=list)
    network: str = "Unknown"
    test_bin_label: str | None = None
    luhn_ok: bool | None = None
    length_ok: bool | None = None
    expiry_ok: bool | None = None


@dataclass(slots=True)
class ValidationReport:
    total: int = 0
    valid: int = 0
    invalid: int = 0
    luhn_failures: int = 0
    format_failures: int = 0
    length_failures: int = 0
    expiry_failures: int = 0
    duplicates: int = 0
    test_bin_count: int = 0
    networks: Counter = field(default_factory=Counter)
    samples: list[str] = field(default_factory=list)
    output_path: Path | None = None


# --------------------------------------------------------------------------- #
# Primitive checks
# --------------------------------------------------------------------------- #
def detect_network(pan: str) -> tuple[str, tuple[int, ...]]:
    digits = re.sub(r"\D", "", pan or "")
    if len(digits) >= 4 and 2221 <= int(digits[:4]) <= 2720:
        return "Mastercard", (16,)
    for prefixes, name, lengths in _IIN_RULES:
        if digits.startswith(prefixes):
            return name, lengths
    return "Unknown", tuple(range(_MIN_LENGTH, _MAX_LENGTH + 1))


def is_test_bin(pan: str) -> tuple[bool, str | None]:
    digits = re.sub(r"\D", "", pan or "")
    prefix = digits[:6]
    if prefix in TEST_BINS:
        return True, TEST_BINS[prefix]
    return False, None


def check_pan(pan: str) -> PanCheck:
    digits = re.sub(r"\D", "", pan or "")
    network, lengths = detect_network(digits)
    test_bin, label = is_test_bin(digits)
    return PanCheck(
        digits=digits,
        format_ok=bool(digits) and digits.isdigit(),
        length_ok=len(digits) in lengths,
        luhn_ok=luhn_valid(digits) if digits else False,
        network=network,
        test_bin_label=label if test_bin else None,
    )


def parse_expiry(value: str) -> ExpiryCheck:
    text = (value or "").strip()
    if not text:
        return ExpiryCheck(present=False, syntax_ok=False)
    for pattern in _EXPIRY_PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        groups = match.groups()
        if len(groups) == 2:
            month = int(groups[0])
            year_part = groups[1]
        else:  # MMYY
            month = int(groups[0][:2])
            year_part = groups[0][2:]
        if not 1 <= month <= 12:
            return ExpiryCheck(present=True, syntax_ok=False)
        year = int(year_part)
        if year < 100:
            year += 2000
        return ExpiryCheck(
            present=True,
            syntax_ok=True,
            expired=False,
            normalized=f"{month:02d}/{year}",
        )
    return ExpiryCheck(present=True, syntax_ok=False)


def _expired(normalized: str, now: datetime) -> bool:
    month, year = normalized.split("/")
    return (int(year), int(month)) < (now.year, now.month)


# --------------------------------------------------------------------------- #
# Record + file validation
# --------------------------------------------------------------------------- #
def validate_record(
    record: list[str],
    *,
    pan_index: int | None = 0,
    expiry_index: int | None = 1,
    options: ValidationOptions | None = None,
    now: datetime | None = None,
    index: int = 0,
) -> RecordFinding:
    options = options or ValidationOptions()
    now = now or datetime.now(UTC)

    pan_raw = field_of(record, pan_index)
    finding = RecordFinding(index=index, pan_masked=mask_pan(pan_raw), status="valid")
    pan = check_pan(pan_raw)
    finding.network = pan.network
    finding.test_bin_label = pan.test_bin_label
    finding.length_ok = pan.length_ok
    finding.luhn_ok = pan.luhn_ok

    if options.check_format and not pan.format_ok:
        finding.reasons.append("format")
    if options.check_length and pan.format_ok and not pan.length_ok:
        finding.reasons.append("length")
    if options.check_luhn and pan.format_ok and not pan.luhn_ok:
        finding.reasons.append("luhn")
    if options.check_test_bin and pan.format_ok and pan.test_bin_label is None:
        finding.reasons.append("not-test-bin")

    if expiry_index is not None:
        expiry = parse_expiry(field_of(record, expiry_index))
        finding.expiry_ok = expiry.present and expiry.syntax_ok and not expiry.expired
        if options.check_expiry:
            if not expiry.present:
                finding.reasons.append("expiry-missing")
            elif not expiry.syntax_ok:
                finding.reasons.append("expiry-syntax")
            elif options.flag_expired and _expired(expiry.normalized, now):
                finding.reasons.append("expired")
                finding.expiry_ok = False

    finding.status = "valid" if not finding.reasons else "invalid"
    return finding


_REPORT_FIELDS = [
    "row",
    "pan",
    "network",
    "test_bin",
    "luhn",
    "length",
    "expiry",
    "status",
    "reasons",
]


def validate_file(
    src: str | Path,
    out: str | Path,
    *,
    info: DatasetInfo,
    pan_index: int | None = 0,
    expiry_index: int | None = 1,
    options: ValidationOptions | None = None,
    sample_size: int = 10,
    on_progress: ProgressFn | None = None,
) -> ValidationReport:
    """Validate every record and write a CSV report. Performs no networking."""
    options = options or ValidationOptions()
    now = datetime.now(UTC)
    destination = Path(out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    report = ValidationReport()
    seen: set[str] = set()
    processed = 0

    with open(destination, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_REPORT_FIELDS)
        writer.writeheader()

        for record in iter_records(src, info):
            processed += 1
            report.total += 1
            finding = validate_record(
                record,
                pan_index=pan_index,
                expiry_index=expiry_index,
                options=options,
                now=now,
                index=processed,
            )

            pan_digits = check_pan(field_of(record, pan_index)).digits
            if pan_digits:
                if pan_digits in seen:
                    report.duplicates += 1
                seen.add(pan_digits)

            report.networks[finding.network] += 1
            if finding.test_bin_label:
                report.test_bin_count += 1

            if finding.status == "valid":
                report.valid += 1
            else:
                report.invalid += 1
                if len(report.samples) < sample_size:
                    report.samples.append(
                        f"{finding.pan_masked} — {', '.join(finding.reasons)}"
                    )

            for reason in finding.reasons:
                if reason == "luhn":
                    report.luhn_failures += 1
                elif reason == "format":
                    report.format_failures += 1
                elif reason == "length":
                    report.length_failures += 1
                elif reason in {"expiry-missing", "expiry-syntax", "expired"}:
                    report.expiry_failures += 1

            writer.writerow(
                {
                    "row": processed,
                    "pan": finding.pan_masked,
                    "network": finding.network,
                    "test_bin": finding.test_bin_label or "",
                    "luhn": _fmt_bool(finding.luhn_ok),
                    "length": _fmt_bool(finding.length_ok),
                    "expiry": _fmt_bool(finding.expiry_ok),
                    "status": finding.status,
                    "reasons": ",".join(finding.reasons),
                }
            )

            if on_progress:
                on_progress(processed)

    report.output_path = destination
    return report


def _fmt_bool(value: bool | None) -> str:
    if value is None:
        return ""
    return "ok" if value else "fail"
