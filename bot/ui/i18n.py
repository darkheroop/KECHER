"""Tiny localization layer: English + Hinglish.

Only user-facing text is translated; emoji and values stay the same.
"""

from __future__ import annotations

SUPPORTED = {"en": "English", "hi-en": "Hinglish"}

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "tagline": "Extract, validate & organise card serial files.",
        "developer": "Developer: @{name} — contact for any issue.",
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
        "scrape_guide": (
            "**Scrape — how it works**\n"
            "1 · **Account** — connect your Telegram account (phone → code → 2FA). "
            "Saved until you log out.\n"
            "2 · **Sources** — ➕ Add source, send `@username` or `-100…` "
            "(a chat you're already in). Tap ☐ to pick one or many.\n"
            "3 · **Keywords** — comma separated. Match modes:\n"
            "   • contains — anywhere in the text\n"
            "   • word — whole word only\n"
            "   • exact — whole message equals it\n"
            "   • regex — advanced pattern\n"
            "   • field — one card field only (1 serial · 2 date · 3 time · 4 count)\n"
            "4 · **Range** — All / 7d / 30d / 90d / This month / Last month / Custom\n"
            "5 · **Limit** — how many recent messages to scan (100 / 500 / 1k / All / ✏️ custom)\n"
            "6 · **Mode** — Messages (full text) or Cards (records only)\n"
            "7 · **Refine** — Auto-clean · Media · Exclude · Sender · Min length\n"
            "8 · **Dry-run** — count matches, save nothing\n"
            "9 · **Format** — TXT / CSV / JSON\n"
            "10 · **Channel** — also post results to your channel\n"
            "11 · **Run** — you get the RAW file first, then choose Clean.\n\n"
            "👤 You only see your own accounts. The **owner/admin** can see and use "
            "every connected account."
        ),
        "sg_start": "Start scraping",
        "sg_guide": "Full guide",
    },
    "hi-en": {
        "tagline": "Card serial files ko extract, validate aur organise karo.",
        "developer": "Developer: @{name} — kisi bhi issue ke liye contact karo.",
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
        "scrape_guide": (
            "**Scrape — kaise kaam karta hai**\n"
            "1 · **Account** — apna Telegram account jodo (phone → code → 2FA). "
            "Jab tak log out na karo, saved rehta hai.\n"
            "2 · **Sources** — ➕ Add source, `@username` ya `-100…` bhejo "
            "(jis chat me tum already ho). ☐ tap karke ek ya zyada chuno.\n"
            "3 · **Keywords** — comma se alag karo. Match modes:\n"
            "   • contains — text me kahin bhi\n"
            "   • word — pura word hi\n"
            "   • exact — pura message barabar ho\n"
            "   • regex — advanced pattern\n"
            "   • field — sirf ek card field (1 serial · 2 date · 3 time · 4 count)\n"
            "4 · **Range** — All / 7d / 30d / 90d / This month / Last month / Custom\n"
            "5 · **Limit** — kitne recent messages scan karne hain (100 / 500 / 1k / All / ✏️ custom)\n"
            "6 · **Mode** — Messages (pura text) ya Cards (sirf records)\n"
            "7 · **Refine** — Auto-clean · Media · Exclude · Sender · Min length\n"
            "8 · **Dry-run** — sirf count karega, kuch save nahi\n"
            "9 · **Format** — TXT / CSV / JSON\n"
            "10 · **Channel** — results channel pe bhi bhejo\n"
            "11 · **Run** — pehle RAW file milegi, phir Clean chuno.\n\n"
            "👤 Tum sirf apne accounts dekh sakte ho. **Owner/admin** sab connected "
            "accounts dekh aur use kar sakte hain."
        ),
        "sg_start": "Scrape shuru karo",
        "sg_guide": "Poori guide",
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
