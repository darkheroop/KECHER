"""Scrape UX: confirmation card, stop control and summary text."""

from __future__ import annotations

from types import SimpleNamespace

from bot.handlers.scrape import _confirm_text
from bot.ui.keyboards import (
    clone_method,
    clone_options,
    clone_picker,
    clone_progress,
    scrape_confirm,
    scrape_progress,
)


def test_confirm_keyboard_offers_start_adjust_cancel() -> None:
    data = {b.callback_data for row in scrape_confirm().inline_keyboard for b in row}
    assert data == {"scr:go", "scr:backpanel", "scr:cancel"}


def test_progress_keyboard_exposes_stop() -> None:
    data = {b.callback_data for row in scrape_progress().inline_keyboard for b in row}
    assert data == {"scr:stop"}


def test_confirm_text_lists_sources_and_settings() -> None:
    sc = {"keywords": ["canada"], "limit": 500, "mode": "messages", "dates": "7"}
    sources = [
        SimpleNamespace(title="VIP group", tg_peer_ref="@vip"),
        SimpleNamespace(title=None, tg_peer_ref="@other"),
    ]
    text = _confirm_text(sc, sources)
    assert "Sources · 2" in text
    assert "VIP group" in text
    assert "@other" in text
    assert "canada" in text
    assert "last 7d" in text


def test_confirm_text_handles_empty_keywords() -> None:
    text = _confirm_text({"keywords": [], "dates": "none"}, [SimpleNamespace(title="A", tg_peer_ref="a")])
    assert "any" in text
    assert "all time" in text


def test_clone_picker_lists_choices_and_paging() -> None:
    entries = [(i, f"Chat {i}", i % 2 == 0) for i in range(20)]
    first = clone_picker(entries, page=0, prefix="src")
    data = {b.callback_data for row in first.inline_keyboard for b in row}
    assert "clone:pick:src:0" in data
    assert "clone:page:src:1" in data
    assert "clone:pick:src:8" not in data
    assert "clone:no" in data

    last = {b.callback_data for row in clone_picker(entries, page=2, prefix="dst").inline_keyboard for b in row}
    assert "clone:page:dst:1" in last


def test_clone_method_and_options_keyboards() -> None:
    method = {b.callback_data for row in clone_method().inline_keyboard for b in row}
    assert {"clone:method:forward", "clone:method:copy", "clone:no"} <= method

    opts = {b.callback_data for row in clone_options({"limit": 500, "method": "copy"}).inline_keyboard for b in row}
    assert {"clone:opt:limit:500", "clone:opt:limit:0", "clone:opt:kw", "clone:go"} <= opts

    progress = {b.callback_data for row in clone_progress().inline_keyboard for b in row}
    assert progress == {"clone:stop"}
