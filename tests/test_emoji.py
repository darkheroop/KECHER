import pytest

from bot.ui import emoji
from bot.ui.emoji import Emoji, configure_custom, plain, render
from bot.ui.keyboards import card_actions, main_menu


@pytest.fixture(autouse=True)
def _reset_emoji():
    configure_custom(None)
    yield
    configure_custom(None)


def test_unicode_fallback() -> None:
    assert render("SUCCESS") == "✅"
    assert render("FILE") == "📁"


def test_token_renders_in_fstring() -> None:
    assert f"{Emoji.CONVERT} Convert" == "📄 Convert"


def test_custom_emoji_overrides_fallback() -> None:
    configure_custom({"SUCCESS": "5368324170671202286"})
    rendered = render("SUCCESS")
    assert rendered == '<tg-emoji emoji-id="5368324170671202286">✅</tg-emoji>'
    assert render("ERROR") == "❌"


def test_invalid_custom_id_falls_back() -> None:
    configure_custom({"SUCCESS": "not-a-number"})
    assert render("SUCCESS") == "✅"


def test_unknown_emoji_raises() -> None:
    with pytest.raises(KeyError):
        render("NOPE")


def test_plain_replaces_custom_emoji_markup_with_unicode() -> None:
    configure_custom({"SUCCESS": "5368324170671202286"})
    assert plain(f"{Emoji.SUCCESS} Ready") == "✅ Ready"


def test_keyboard_labels_never_contain_html_emoji_tags() -> None:
    configure_custom({"CLEAN": "5368324170671202286", "SUCCESS": "12345"})
    buttons = [button for row in card_actions(1).inline_keyboard for button in row]
    assert all("<tg-emoji" not in button.text for button in buttons)


def test_main_menu_has_easy_upload_and_help_actions() -> None:
    callbacks = {
        button.callback_data
        for row in main_menu().inline_keyboard
        for button in row
        if button.callback_data
    }
    assert {"menu:upload", "menu:help"} <= callbacks
