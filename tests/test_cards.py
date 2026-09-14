from pathlib import Path

from bot.services.cards import (
    Card,
    clean_cards,
    country_cards,
    dedup_cards,
    extract_serial,
    format_card,
    live_cards,
    merge_files,
    parse_card,
    split_cards,
)

VALID_A = "4111111111111111|02|2028|555"
VALID_B = "4242424242424242|02|28|555"
INVALID_SHORT = "123|02|2028|555"
INVALID_DATE = "4111111111111111|2|2028|555"
INVALID_TIME3 = "4111111111111111|02|202|555"
INVALID_INVITED2 = "4111111111111111|02|2028|55"


def test_parse_card_valid_examples() -> None:
    card = parse_card("1234567891234567|02|2028|555")
    assert card == Card("1234567891234567", "02", "2028", "555")
    card = parse_card("1234567891234567|02|28|555")
    assert card == Card("1234567891234567", "02", "28", "555")


def test_parse_card_tolerates_spaces() -> None:
    assert parse_card("  1234567891234567 | 02 | 2028 | 555  ") is not None


def test_parse_card_rejects_bad_digit_counts() -> None:
    for line in (INVALID_SHORT, INVALID_DATE, INVALID_TIME3, INVALID_INVITED2, "", "hello"):
        assert parse_card(line) is None


def test_format_card() -> None:
    assert format_card(Card("1234567891234567", "02", "28", "555")) == "1234567891234567|02|28|555"


def test_extract_serial() -> None:
    assert extract_serial(VALID_A) == "4111111111111111"
    assert extract_serial("4111111111111111") == "4111111111111111"
    assert extract_serial("not a serial") is None


def test_clean_cards(tmp_path: Path) -> None:
    src = tmp_path / "in.txt"
    src.write_text(
        "\n".join([VALID_A, "garbage", INVALID_SHORT, VALID_B, INVALID_DATE]) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.txt"
    report = clean_cards(src, out)
    assert report.total == 5
    assert report.valid == 2
    assert report.invalid == 3
    assert out.read_text(encoding="utf-8") == f"{VALID_A}\n{VALID_B}\n"


def test_live_cards_keeps_full_lines(tmp_path: Path) -> None:
    src = tmp_path / "in.txt"
    src.write_text(
        "4111111111111111|02|2028|555\n4242424242424241|02|2028|555\n",
        encoding="utf-8",
    )
    out = tmp_path / "live.txt"
    report = live_cards(src, out)
    assert report.checked == 2
    assert report.valid == 1
    assert report.invalid == 1
    assert out.read_text(encoding="utf-8") == "4111111111111111|02|2028|555\n"


def test_country_cards(tmp_path: Path) -> None:
    src = tmp_path / "in.txt"
    src.write_text(
        f"{VALID_A}\naustralia\n{VALID_B}\ncanada\n",
        encoding="utf-8",
    )
    out = tmp_path / "country.txt"
    report = country_cards(src, out, "canada")
    assert report.matches == 1
    assert report.lines == 1
    assert out.read_text(encoding="utf-8") == f"{VALID_B}\n"


def test_country_cards_case_insensitive_and_multiple_above(tmp_path: Path) -> None:
    src = tmp_path / "in.txt"
    src.write_text(f"{VALID_A}\n{VALID_B}\nCANADA\n", encoding="utf-8")
    out = tmp_path / "country.txt"
    report = country_cards(src, out, "canada")
    assert report.lines == 2
    assert out.read_text(encoding="utf-8") == f"{VALID_A}\n{VALID_B}\n"


def test_split_cards_equal_parts(tmp_path: Path) -> None:
    src = tmp_path / "in.txt"
    src.write_text("\n".join(f"{i:016d}|02|28|555" for i in range(10)) + "\n", encoding="utf-8")
    report = split_cards(src, tmp_path / "parts", 3)
    assert report.lines == 10
    assert len(report.parts) == 3
    sizes = [len(p.read_text(encoding="utf-8").splitlines()) for p in report.parts]
    assert sizes == [4, 3, 3]


def test_split_cards_more_parts_than_lines(tmp_path: Path) -> None:
    src = tmp_path / "in.txt"
    src.write_text(f"{VALID_A}\n", encoding="utf-8")
    report = split_cards(src, tmp_path / "parts", 5)
    assert len(report.parts) == 1


def test_dedup_cards(tmp_path: Path) -> None:
    src = tmp_path / "in.txt"
    src.write_text(f"{VALID_A}\n{VALID_A}\n{VALID_B}\n", encoding="utf-8")
    out = tmp_path / "out.txt"
    report = dedup_cards(src, out)
    assert (report.total, report.unique, report.removed) == (3, 2, 1)
    assert out.read_text(encoding="utf-8") == f"{VALID_A}\n{VALID_B}\n"


def test_merge_files(tmp_path: Path) -> None:
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text(f"{VALID_A}\n", encoding="utf-8")
    b.write_text(f"{VALID_B}\n", encoding="utf-8")
    out = tmp_path / "merged.txt"
    report = merge_files([a, b], out)
    assert report.files == 2
    assert report.lines == 2
    assert out.read_text(encoding="utf-8") == f"{VALID_A}\n{VALID_B}\n"
