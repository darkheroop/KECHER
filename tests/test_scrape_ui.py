"""Scrape UX: confirmation card, stop control and summary text."""

from __future__ import annotations

from types import SimpleNamespace

from bot.handlers.scrape import _confirm_text
from bot.ui.keyboards import scrape_confirm, scrape_progress


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
