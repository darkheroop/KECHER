"""Tiny localization layer: English + Hinglish.

Only user-facing text is translated; emoji and values stay the same.
"""

from __future__ import annotations

SUPPORTED = {"en": "English", "hi-en": "Hinglish"}

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "welcome": (
            "Send a **.txt** — or reply to one with a command.\n\n"
            "/help   /settings"
        ),
        "help_title": "Reply to a .txt",
        "help_lines": (
            "`/clean`  valid records\n"
            "`/live`  Luhn-valid\n"
            "`/filter 123456`  a series\n"
            "`/filter canada`  a keyword\n"
            "`/split N`   `/dedup`\n"
            "`/addfile` → `/merge`"
        ),
        "settings_title": "Settings",
        "s_language": "Language",
        "s_mode": "Mode",
        "s_cleanup": "Cleanup",
        "scrape_title": "Scrape",
        "sc_source": "Source",
        "sc_keywords": "Keywords",
        "sc_exclude": "Exclude",
        "sc_sender": "Sender",
        "sc_minlen": "Min length",
        "sc_limit": "Limit",
        "sc_mode": "Mode",
        "sc_dates": "Dates",
        "sc_media": "Media",
        "sc_autoclean": "Auto-clean",
        "sc_channel": "Send to channel",
        "prompt_pick_sources": "Tap one or more sources, then Continue:",
    },
    "hi-en": {
        "welcome": (
            "Ek **.txt** bhejo — ya kisi msg pe reply karke command do.\n\n"
            "/help   /settings"
        ),
        "help_title": "Txt pe reply karo",
        "help_lines": (
            "`/clean`  sahi records\n"
            "`/live`  Luhn check\n"
            "`/filter 123456`  ek series\n"
            "`/filter canada`  keyword\n"
            "`/split N`   `/dedup`\n"
            "`/addfile` → `/merge`"
        ),
        "settings_title": "Settings",
        "s_language": "Bhasha",
        "s_mode": "Mode",
        "s_cleanup": "Cleanup",
        "scrape_title": "Scrape",
        "sc_source": "Source",
        "sc_keywords": "Keywords",
        "sc_exclude": "Hatao (exclude)",
        "sc_sender": "Sender",
        "sc_minlen": "Min length",
        "sc_limit": "Kitne",
        "sc_mode": "Mode",
        "sc_dates": "Dates",
        "sc_media": "Media",
        "sc_autoclean": "Auto-clean",
        "sc_channel": "Channel pe bhejo",
        "prompt_pick_sources": "Ek ya zyada source chuno, phir Continue:",
    },
}


def tr(lang: str, key: str, **kwargs: object) -> str:
    table = STRINGS.get(lang) or STRINGS["en"]
    text = table.get(key) or STRINGS["en"].get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text


def markdown_to_html(text: str) -> str:
    """Our i18n strings use **bold** and `code`; convert to Telegram HTML."""
    import html as _html
    import re

    text = _html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text
