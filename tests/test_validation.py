from datetime import UTC, datetime
from pathlib import Path

from bot.services.validation import (
    ValidationOptions,
    check_pan,
    detect_network,
    is_test_bin,
    parse_expiry,
    validate_file,
    validate_record,
)

NOW = datetime(2026, 1, 15, tzinfo=UTC)


def test_check_pan_test_bin() -> None:
    check = check_pan("4111 1111 1111 1111")
    assert check.network == "Visa"
    assert check.luhn_ok is True
    assert check.length_ok is True
    assert check.test_bin_label == "Visa test"


def test_check_pan_luhn_failure() -> None:
    assert check_pan("4242424242424241").luhn_ok is False


def test_networks() -> None:
    assert detect_network("378282246310005")[0] == "Amex"
    assert detect_network("5555555555554444")[0] == "Mastercard"
    assert detect_network("2223003122003222")[0] == "Mastercard"
    assert detect_network("6011111111111117")[0] == "Discover"


def test_length_rule() -> None:
    # Visa: valid lengths 13/16/19; 14 digits is a length failure.
    assert check_pan("41111111111111").length_ok is False


def test_is_test_bin() -> None:
    assert is_test_bin("4111111111111111") == (True, "Visa test")
    ok, label = is_test_bin("5555555555554444")
    assert ok and label == "Mastercard test"
    assert is_test_bin("4532015112830366")[0] is False


def test_parse_expiry() -> None:
    assert parse_expiry("12/30").normalized == "12/2030"
    assert parse_expiry("1230").normalized == "12/2030"
    assert parse_expiry("01-2027").normalized == "01/2027"
    assert parse_expiry("13/30").syntax_ok is False
    assert parse_expiry("").present is False


def test_validate_record_valid() -> None:
    finding = validate_record(
        ["4111111111111111", "12/30"], pan_index=0, expiry_index=1, now=NOW
    )
    assert finding.status == "valid"
    assert finding.reasons == []
    assert finding.luhn_ok is True


def test_validate_record_expired() -> None:
    finding = validate_record(
        ["4111111111111111", "01/20"], pan_index=0, expiry_index=1, now=NOW
    )
    assert finding.status == "invalid"
    assert "expired" in finding.reasons


def test_validate_record_expiry_syntax() -> None:
    finding = validate_record(
        ["4111111111111111", "13/30"], pan_index=0, expiry_index=1, now=NOW
    )
    assert "expiry-syntax" in finding.reasons


def test_validate_record_test_bin_check() -> None:
    options = ValidationOptions(check_test_bin=True)
    finding = validate_record(
        ["4532015112830366", "12/30"],
        pan_index=0,
        expiry_index=1,
        options=options,
        now=NOW,
    )
    assert "not-test-bin" in finding.reasons


def test_validate_file(tmp_path: Path) -> None:
    from bot.services.dataset import inspect_dataset

    src = tmp_path / "test.txt"
    src.write_text(
        "4111111111111111|12/30\n"
        "4242424242424241|12/30\n"
        "378282246310005|13/30\n",
        encoding="utf-8",
    )
    info = inspect_dataset(src)
    out = tmp_path / "report.csv"
    report = validate_file(src, out, info=info, pan_index=0, expiry_index=1)

    assert report.total == 3
    assert report.valid == 1
    assert report.invalid == 2
    assert report.luhn_failures == 1
    assert report.expiry_failures == 1
    assert report.test_bin_count == 3
    assert out.is_file()
    content = out.read_text(encoding="utf-8")
    assert "pan,network" in content.replace('"', "")
    assert "411111******1111" in content


def test_cvv_never_read(tmp_path: Path) -> None:
    """CVV/CVC values must never appear in the report."""
    from bot.services.dataset import inspect_dataset

    src = tmp_path / "with_cvv.txt"
    src.write_text("4111111111111111|12/30|999\n", encoding="utf-8")
    info = inspect_dataset(src)
    out = tmp_path / "report.csv"
    validate_file(src, out, info=info, pan_index=0, expiry_index=1)
    assert "999" not in out.read_text(encoding="utf-8")


def test_validation_module_has_no_networking() -> None:
    import ast

    import bot.services.validation as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    for forbidden in ("requests", "urllib", "http", "aiohttp", "telethon", "socket", "httpx"):
        assert forbidden not in imported, f"unexpected network import: {forbidden}"
