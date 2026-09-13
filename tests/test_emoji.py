import pytest

from bot.ui import emoji
from bot.ui.emoji import Emoji, configure_custom, render


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
