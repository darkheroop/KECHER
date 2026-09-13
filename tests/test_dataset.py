from pathlib import Path

from bot.services.dataset import (
    count_records,
    detect_field,
    export_group,
    group_counts,
    inspect_dataset,
    search_to_file,
)
from bot.services.geo import country_label, flag_for
from bot.services.luhn import mask_pan, mask_pans

TEXT = (
    "4111111111111111|IN|HDFC Bank\n"
    "4242424242424242|US|Chase\n"
    "5555555555554444|IN|ICICI\n"
    "378282246310005|GB|Barclays\n"
)

CSV = "pan,country,bank\n4111111111111111,in,hdfc\n"


def _text(tmp_path: Path) -> Path:
    path = tmp_path / "data.txt"
    path.write_text(TEXT, encoding="utf-8")
    return path


def test_inspect_text_dataset(tmp_path: Path) -> None:
    info = inspect_dataset(_text(tmp_path))
    assert info.kind == "text"
    assert info.delimiter == "|"
    assert info.columns == 3
    assert info.header is None


def test_inspect_csv_dataset_detects_header(tmp_path: Path) -> None:
    path = tmp_path / "data.csv"
    path.write_text(CSV, encoding="utf-8")
    info = inspect_dataset(path)
    assert info.kind == "csv"
    assert info.header == ["pan", "country", "bank"]
    assert detect_field(info.header, {"country", "cc"}) == 1
    assert detect_field(info.header, {"bank"}) == 2
    assert detect_field(info.header, {"nope"}) is None


def test_count_and_search(tmp_path: Path) -> None:
    info = inspect_dataset(_text(tmp_path))
    assert count_records(_text(tmp_path), info) == 4


def test_search_contains_whole_record(tmp_path: Path) -> None:
    src = _text(tmp_path)
    info = inspect_dataset(src)
    out = tmp_path / "found.txt"
    result = search_to_file(src, out, info=info, query="4111")
    assert result.matches == 1
    assert "4111111111111111" in out.read_text(encoding="utf-8")
    assert result.samples and "*" in result.samples[0]


def test_search_field_modes(tmp_path: Path) -> None:
    src = _text(tmp_path)
    info = inspect_dataset(src)

    exact_out = tmp_path / "exact.txt"
    exact = search_to_file(src, exact_out, info=info, query="US", mode="exact", field_index=1)
    assert exact.matches == 1

    prefix_out = tmp_path / "prefix.txt"
    prefix = search_to_file(src, prefix_out, info=info, query="I", mode="prefix", field_index=1)
    assert prefix.matches == 2

    ci_out = tmp_path / "ci.txt"
    ci = search_to_file(src, ci_out, info=info, query="us", mode="exact", field_index=1)
    assert ci.matches == 1


def test_search_limit(tmp_path: Path) -> None:
    src = _text(tmp_path)
    info = inspect_dataset(src)
    result = search_to_file(
        src, tmp_path / "out.txt", info=info, query="", mode="contains", limit=2
    )
    assert result.matches == 2


def test_group_counts(tmp_path: Path) -> None:
    info = inspect_dataset(_text(tmp_path))
    groups = group_counts(_text(tmp_path), info, 1)
    assert dict(groups) == {"IN": 2, "US": 1, "GB": 1}
    assert groups[0] == ("IN", 2)


def test_export_group(tmp_path: Path) -> None:
    src = _text(tmp_path)
    info = inspect_dataset(src)
    out = tmp_path / "in.txt"
    written = export_group(src, out, info=info, field_index=1, value="in")
    assert written == 2
    lines = out.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2


def test_masking() -> None:
    assert mask_pan("4111111111111111") == "411111******1111"
    assert mask_pan("1234") == "****"
    masked = mask_pans("card 4111 1111 1111 1111 ok")
    assert "4111111111111111" not in masked
    assert "*" in masked


def test_country_flags() -> None:
    assert flag_for("IN") == "🇮🇳"
    assert flag_for("us") == "🇺🇸"
    assert flag_for("India") == ""
    assert country_label("GB") == "🇬🇧 GB"
