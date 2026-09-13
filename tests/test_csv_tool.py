from pathlib import Path

import pytest

from bot.services.csv_tool import (
    csv_to_txt,
    inspect_csv,
    parse_column_selection,
)

CSV = "name;age\nAlice;30\nBob;25\n"


def _csv(tmp_path: Path) -> Path:
    path = tmp_path / "people.csv"
    path.write_text(CSV, encoding="utf-8")
    return path


def test_inspect_csv(tmp_path: Path) -> None:
    info = inspect_csv(_csv(tmp_path))
    assert info.rows == 3
    assert info.columns == 2
    assert info.delimiter == ";"
    assert info.has_header is True
    assert info.header == ["name", "age"]


def test_csv_to_txt_all_columns(tmp_path: Path) -> None:
    out = tmp_path / "out.txt"
    written = csv_to_txt(_csv(tmp_path), out)
    assert written == 3
    assert out.read_text(encoding="utf-8") == "name | age\nAlice | 30\nBob | 25\n"


def test_csv_to_txt_selected_columns(tmp_path: Path) -> None:
    out = tmp_path / "out.txt"
    csv_to_txt(_csv(tmp_path), out, columns=[1])
    assert out.read_text(encoding="utf-8") == "age\n30\n25\n"


def test_csv_to_txt_skip_header(tmp_path: Path) -> None:
    out = tmp_path / "out.txt"
    written = csv_to_txt(_csv(tmp_path), out, include_header=False)
    assert written == 2
    assert "name" not in out.read_text(encoding="utf-8")


def test_parse_column_selection() -> None:
    assert parse_column_selection("1,3,3", 5) == [0, 2]
    assert parse_column_selection(" 2 ", 2) == [1]


@pytest.mark.parametrize("text", ["0", "9", "x", "", "1,x"])
def test_parse_column_selection_invalid(text: str) -> None:
    with pytest.raises(ValueError):
        parse_column_selection(text, 3)
