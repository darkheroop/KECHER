from pathlib import Path

import pytest

from bot.services.luhn import find_pan_candidates
from bot.services.telegram_export import (
    extract_to_txt,
    parse_html_export,
    parse_json_export,
)

HTML = """<!DOCTYPE html>
<html><body>
<div class="page_body chat_page"><div class="history">
<div class="message default clearfix">
 <div class="text">4111 1111 1111 1111<br>second line</div>
</div>
<div class="message service">
 <div class="body details">Group created</div>
</div>
<div class="message default clearfix">
 <div class="text"><strong>card</strong>: 4242&nbsp;4242&nbsp;4242&nbsp;4241</div>
</div>
</div></div>
</body></html>"""

JSON = (
    '{"messages": ['
    '{"text": "hello world"},'
    '{"text": ["part one", " part two"]},'
    '{"text": [{"type": "link", "text": "http://x"}, {"type": "plain", "text": " more"}]},'
    '{"text": ""}'
    ']}'
)


def test_parse_html_export(tmp_path: Path) -> None:
    path = tmp_path / "messages.html"
    path.write_text(HTML, encoding="utf-8")
    messages = parse_html_export(path)
    assert len(messages) == 2
    assert "4111 1111 1111 1111" in messages[0]
    assert "second line" in messages[0]
    assert "4242" in messages[1]


def test_parse_json_export(tmp_path: Path) -> None:
    path = tmp_path / "result.json"
    path.write_text(JSON, encoding="utf-8")
    messages = parse_json_export(path)
    assert messages == ["hello world", "part one part two", "http://x more"]


def test_extract_to_txt_html(tmp_path: Path) -> None:
    src = tmp_path / "messages.html"
    src.write_text(HTML, encoding="utf-8")
    out = tmp_path / "out.txt"
    count = extract_to_txt(src, out)
    assert count == 2
    text = out.read_text(encoding="utf-8")
    assert "4111 1111 1111 1111" in text


def test_extract_to_txt_unsupported(tmp_path: Path) -> None:
    src = tmp_path / "data.xlsx"
    src.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        extract_to_txt(src, tmp_path / "out.txt")


def test_extracted_lines_luhn_filterable(tmp_path: Path) -> None:
    """Extracted export text can then be filtered by Luhn."""
    src = tmp_path / "messages.html"
    src.write_text(HTML, encoding="utf-8")
    out = tmp_path / "out.txt"
    extract_to_txt(src, out)

    lines = out.read_text(encoding="utf-8").splitlines()
    valid = [line for line in lines if any(map(_luhn, find_pan_candidates(line)))]
    assert any("4111 1111 1111 1111" in line for line in valid)
    assert not any("4242 4242 4242 4241" in line for line in valid)


def _luhn(number: str) -> bool:
    from bot.services.luhn import luhn_valid

    return luhn_valid(number)
