"""Telegram Desktop chat-export importer (offline).

Supports the HTML export (``messages.html``) and the JSON export
(``result.json``) and extracts just the message text into a TXT file, so the
result can be processed by /clean, /find, etc.

No networking: this only reads files you already have.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from html.parser import HTMLParser
from pathlib import Path

ProgressFn = Callable[[int], None]

_VOID_TAGS = {"br", "img", "hr", "meta", "link", "input", "source"}


def _normalize(text: str) -> str:
    return text.replace("\xa0", " ").strip()


class _MessageTextParser(HTMLParser):
    """Collect the contents of every ``<div class="text">`` block."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.messages: list[str] = []
        self._in_text = False
        self._depth = 0
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if not self._in_text:
            if tag == "div" and "text" in (dict(attrs).get("class") or "").split():
                self._in_text = True
                self._depth = 1
                self._buffer = []
            return
        if tag in _VOID_TAGS:
            if tag == "br":
                self._buffer.append("\n")
            return
        self._depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._in_text and tag == "br":
            self._buffer.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if not self._in_text or tag in _VOID_TAGS:
            return
        self._depth -= 1
        if self._depth <= 0:
            text = _normalize("".join(self._buffer))
            if text:
                self.messages.append(text)
            self._in_text = False
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._in_text:
            self._buffer.append(data)


def parse_html_export(path: str | Path) -> list[str]:
    parser = _MessageTextParser()
    parser.feed(Path(path).read_text(encoding="utf-8", errors="replace"))
    parser.close()
    return parser.messages


def parse_json_export(path: str | Path) -> list[str]:
    data = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    messages: list[str] = []
    for entry in data.get("messages", []):
        if not isinstance(entry, dict):
            continue
        text = entry.get("text")
        if isinstance(text, str):
            message = text
        elif isinstance(text, list):
            parts = []
            for part in text:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict):
                    parts.append(str(part.get("text", "")))
            message = "".join(parts)
        else:
            continue
        message = _normalize(message)
        if message:
            messages.append(message)
    return messages


def extract_to_txt(
    src: str | Path, out: str | Path, *, on_progress: ProgressFn | None = None
) -> int:
    """Extract message text from a Telegram export into ``out``.

    Returns the number of messages written. Raises ValueError for unsupported
    extensions.
    """
    source = Path(src)
    extension = source.suffix.lower()
    if extension in {".html", ".htm"}:
        messages = parse_html_export(source)
    elif extension in {".json"}:
        messages = parse_json_export(source)
    else:
        raise ValueError(f"Unsupported Telegram export format: {extension or '(none)'}")

    destination = Path(out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with open(destination, "w", encoding="utf-8", newline="\n") as handle:
        for index, message in enumerate(messages, start=1):
            handle.write(message.replace("\r\n", "\n").replace("\r", "\n") + "\n")
            if on_progress:
                on_progress(index)
    return len(messages)
