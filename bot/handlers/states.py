"""FSM states for multi-step upload flows."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class Flow(StatesGroup):
    """Waiting for the user to provide a file or a text parameter."""

    awaiting_file = State()
    awaiting_text = State()
    awaiting_dates = State()
    awaiting_source = State()
    awaiting_keywords = State()
    awaiting_scrape_dates = State()
    awaiting_phone = State()
    awaiting_code = State()
    awaiting_password = State()
    awaiting_limit = State()
    awaiting_api_id = State()
    awaiting_api_hash = State()
    awaiting_exclude = State()
    awaiting_sender = State()
    awaiting_minlen = State()
    awaiting_fieldidx = State()
    awaiting_forward_channel = State()
    awaiting_scrape_channel = State()
    awaiting_broadcast = State()
    collecting_specials = State()
    awaiting_filename = State()
    awaiting_suffix = State()
