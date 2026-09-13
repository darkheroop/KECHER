"""FSM states for multi-step upload flows."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class Flow(StatesGroup):
    """Waiting for the user to provide a file or a text parameter."""

    awaiting_file = State()
    awaiting_text = State()
    awaiting_dates = State()
