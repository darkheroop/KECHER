"""SPECIALS: keyboard wiring and the messages -> .txt collector."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bot.handlers.specials import (
    _build,
    _start_collect,
    spec_collect,
)
from bot.handlers.states import Flow
from bot.services.file_manager import FileManager
from bot.ui.emoji import Emoji
from bot.ui.keyboards import main_menu, specials_collect, specials_menu


class FakeSent:
    def __init__(self, message_id: int) -> None:
        self.message_id = message_id
        self.edits: list[str] = []

    async def edit_text(self, text: str, **kwargs) -> None:  # noqa: ANN003
        self.edits.append(text)


class FakeBot:
    def __init__(self) -> None:
        self.edited: list[str] = []

    async def edit_message_text(self, text: str, **kwargs) -> None:  # noqa: ANN003
        self.edited.append(text)


class FakeMessage:
    def __init__(self, text=None, caption=None, user_id: int = 1) -> None:
        self.text = text
        self.caption = caption
        self.from_user = SimpleNamespace(id=user_id, username="tester", first_name="T")
        self.bot = FakeBot()
        self.chat = SimpleNamespace(id=user_id)
        self.answers: list = []
        self.sent: list = []
        self.documents: list = []
        self._seq = 0

    async def answer(self, text: str, **kwargs):  # noqa: ANN003, ANN201
        self._seq += 1
        self.answers.append(text)
        sent = FakeSent(self._seq)
        self.sent.append(sent)
        return sent

    async def answer_document(self, document, **kwargs) -> None:  # noqa: ANN001, ANN003
        self.documents.append(kwargs)


def _state(user_id: int = 1) -> FSMContext:
    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=user_id, user_id=user_id),
    )


def test_specials_button_is_in_the_main_menu() -> None:
    flat = [button.callback_data for row in main_menu().inline_keyboard for button in row]
    assert "spec:open" in flat


def test_specials_menu_and_collect_keyboards() -> None:
    menu = {b.callback_data for row in specials_menu().inline_keyboard for b in row}
    assert {"spec:clone", "spec:txt"} <= menu
    collect = {b.callback_data for row in specials_collect(3, 5).inline_keyboard for b in row}
    assert {"spec:done", "spec:build:dedup", "spec:cancel"} <= collect


def test_specials_emoji_render() -> None:
    assert str(Emoji.SPECIALS) == "✨"
    assert str(Emoji.CLONE) == "🧬"
    assert str(Emoji.FORWARD) == "📨"


async def test_collector_writes_one_line_per_message(settings) -> None:
    files = FileManager(settings)
    state = _state()
    msg = FakeMessage(text="ignored")
    await _start_collect(msg, msg.from_user, state, files)

    for text in ("4111111111111111|02|2028|555", "hello\nworld"):
        await spec_collect(FakeMessage(text=text), state, files)
    await spec_collect(FakeMessage(caption="a caption"), state, files)
    await spec_collect(FakeMessage(), state, files)  # media without text -> skipped

    data = await state.get_data()
    assert data["spec_count"] == 3
    assert data["spec_lines"] == 4
    assert data["spec_skipped"] == 1

    draft = files.resolve(msg.from_user.id, data["spec_draft"])
    assert draft.read_text(encoding="utf-8").splitlines() == [
        "4111111111111111|02|2028|555",
        "hello",
        "world",
        "a caption",
    ]


async def test_build_creates_a_record_and_offers_card_actions(db) -> None:
    settings, files = db, FileManager(db)
    state = _state()
    msg = FakeMessage(text="seed")
    await _start_collect(msg, msg.from_user, state, files)
    await spec_collect(FakeMessage(text="4111111111111111|02|2028|555"), state, files)

    await _build(msg, msg, state, files, dedupe=False)

    assert len(msg.documents) == 1
    assert await state.get_state() is None
    actions = msg.answers[-1]
    assert "File ready" in actions


async def test_build_with_dedupe_removes_duplicate_lines(db) -> None:
    settings, files = db, FileManager(db)
    state = _state()
    msg = FakeMessage(text="seed")
    await _start_collect(msg, msg.from_user, state, files)
    for _ in range(2):
        await spec_collect(FakeMessage(text="same line"), state, files)

    await _build(msg, msg, state, files, dedupe=True)

    assert len(msg.documents) == 1
    assert any("duplicate" in text for sent in msg.sent for text in sent.edits)
    assert any("duplicate" in cap.get("caption", "") for cap in msg.documents)


async def test_cancel_discards_the_draft(settings) -> None:
    files = FileManager(settings)
    state = _state()
    msg = FakeMessage(text="seed")
    await _start_collect(msg, msg.from_user, state, files)
    rel = (await state.get_data())["spec_draft"]
    draft = files.resolve(msg.from_user.id, rel)
    assert draft.exists()
    assert await state.get_state() == Flow.collecting_specials.state
    await state.clear()
    files.delete(msg.from_user.id, rel)
    assert not draft.exists()


@pytest.mark.parametrize("state_name", ["collecting_specials"])
def test_flow_state_exists(state_name: str) -> None:
    assert hasattr(Flow, state_name)
