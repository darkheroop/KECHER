"""Inline keyboard builders."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.db.enums import UIMode
from bot.ui.emoji import Emoji

def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _mark(label: str, active: bool) -> str:
    return f"{Emoji.SUCCESS} {label}" if active else label


def main_menu() -> InlineKeyboardMarkup:
    """Clean 2-column grid; admin tools live under Settings."""
    from bot.config import get_settings

    contact = (get_settings().developer_contact or "").strip().lstrip("@")
    rows = [
        [_btn(f"{Emoji.SCRAPE} Scrape", "menu:scrape"), _btn(f"{Emoji.CLEAN} Clean", "menu:clean")],
        [_btn(f"{Emoji.LIVE_CHECK} Live Check", "menu:live"), _btn(f"{Emoji.COUNTRY} Country", "menu:filter")],
        [_btn(f"{Emoji.SPLIT} Split", "menu:split"), _btn(f"{Emoji.RECYCLE} Dedup", "menu:dedup")],
        [_btn(f"{Emoji.PAGE} Add File", "menu:addfile"), _btn(f"{Emoji.MERGE} Merge", "menu:merge")],
        [_btn(f"{Emoji.FIND} Find BIN", "menu:findbin")],
        [_btn(f"{Emoji.SETTINGS} Settings", "settings:open")],
    ]
    if contact:
        rows.append(
            [InlineKeyboardButton(text="💬 Developer", url=f"https://t.me/{contact}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_menu(
    ui_mode: str, is_admin: bool = False, cleanup_minutes: int = 10, language: str = "en"
) -> InlineKeyboardMarkup:
    button = ui_mode == UIMode.BUTTONS.value
    rows = [
        [
            _btn(_mark(f"{Emoji.BUTTON_MODE} Button", button), "set:mode:button"),
            _btn(_mark(f"{Emoji.TEXT_MODE} Text", not button), "set:mode:text"),
        ],
        [
            _btn(_mark("5 min", cleanup_minutes == 5), "set:clean:5"),
            _btn(_mark("10 min", cleanup_minutes == 10), "set:clean:10"),
            _btn(_mark("30 min", cleanup_minutes == 30), "set:clean:30"),
        ],
        [_btn(_mark("English", language == "en"), "set:lang:en")],
        [_btn(_mark("Hinglish", language == "hi-en"), "set:lang:hi-en")],
    ]
    if is_admin:
        rows.append([_btn(f"{Emoji.ADMIN} Admin Panel", "adm:panel:home")])
    rows.append([_btn(f"{Emoji.BACK} Back", "menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def card_actions(file_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(f"{Emoji.CLEAN} Clean", f"card:clean:{file_id}"), _btn(f"{Emoji.LIVE_CHECK} Live", f"card:live:{file_id}")],
            [_btn(f"{Emoji.FIND} Filter", f"card:filter:{file_id}"), _btn(f"{Emoji.SPLIT} Split", f"card:split:{file_id}")],
            [_btn(f"{Emoji.RECYCLE} Dedup", f"card:dedup:{file_id}"), _btn(f"{Emoji.PAGE} Add File", f"card:addfile:{file_id}")],
            [_btn(f"{Emoji.CANCEL} Cancel", f"card:cancel:{file_id}")],
        ]
    )


def split_choices(file_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("2 parts", f"card:splitn:2:{file_id}"), _btn("3 parts", f"card:splitn:3:{file_id}")],
            [_btn("5 parts", f"card:splitn:5:{file_id}"), _btn("10 parts", f"card:splitn:10:{file_id}")],
            [_btn(f"{Emoji.CANCEL} Cancel", f"card:cancel:{file_id}")],
        ]
    )


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_btn(f"{Emoji.BACK} Back", "menu:home")]]
    )


def scrape_panel(state: dict) -> InlineKeyboardMarkup:
    keywords = state.get("keywords") or []
    exclude = state.get("exclude") or []
    sender = state.get("sender") or "any"
    minlen = state.get("min_length") or 0
    limit = state.get("limit", 100)
    mode = state.get("mode", "messages")
    autoclean = state.get("autoclean", True)
    media = state.get("include_media", False)
    dates = state.get("dates", "none")
    to_channel = state.get("to_channel", True)

    kw_label = ", ".join(keywords) if keywords else "any"
    ex_label = ", ".join(exclude) if exclude else "none"
    kmode = state.get("keyword_mode", "contains")

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(f"{Emoji.FIND} Keywords: {kw_label}"[:60], "scr:kw")],
            [
                _btn(_mark("contains", kmode == "contains"), "scr:kmode:contains"),
                _btn(_mark("word", kmode == "word"), "scr:kmode:word"),
                _btn(_mark("regex", kmode == "regex"), "scr:kmode:regex"),
            ],
            [
                _btn(_mark("100", limit == 100), "scr:limit:100"),
                _btn(_mark("500", limit == 500), "scr:limit:500"),
                _btn(_mark("1k", limit == 1000), "scr:limit:1000"),
                _btn(_mark("All", not limit), "scr:limit:0"),
            ],
            [
                _btn(f"✏️ Limit: {limit or 'All'}"[:30], "scr:limitcustom"),
                _btn(_mark("Messages", mode == "messages"), "scr:mode:messages"),
                _btn(_mark("Cards", mode == "cards"), "scr:mode:cards"),
            ],
            [
                _btn(_mark("Auto-clean", autoclean), "scr:autoclean"),
                _btn(_mark("Media", media), "scr:media"),
                _btn(_mark(f"{Emoji.INBOX} Channel", to_channel), "scr:chan"),
            ],
            [
                _btn(_mark("All time", dates == "none"), "scr:dates:none"),
                _btn(_mark("7d", dates == "7"), "scr:dates:7"),
                _btn(_mark("30d", dates == "30"), "scr:dates:30"),
                _btn(_mark("90d", dates == "90"), "scr:dates:90"),
            ],
            [
                _btn("📅 This month", "scr:dates:month"),
                _btn("📅 Last month", "scr:dates:prevmonth"),
            ],
            [
                _btn("🗓 Custom range", "scr:dates:custom"),
                _btn("🧹 Clear dates", "scr:dates:clear"),
            ],
            [
                _btn(_mark("Dry-run", state.get("dry_run", False)), "scr:dry"),
                _btn(_mark("TXT", state.get("format", "txt") == "txt"), "scr:fmt:txt"),
                _btn(_mark("CSV", state.get("format") == "csv"), "scr:fmt:csv"),
                _btn(_mark("JSON", state.get("format") == "json"), "scr:fmt:json"),
            ],
            [
                _btn(f"🚫 Exclude: {ex_label}"[:34], "scr:exclude"),
                _btn(f"👤 Sender: {sender}"[:24], "scr:sender"),
            ],
            [
                _btn(f"📏 Min length: {minlen}"[:28], "scr:minlen"),
                _btn(f"{Emoji.SETTINGS} Defaults", "scr:defaults"),
            ],
            [_btn(f"{Emoji.SCRAPE} Run scrape", "scr:run")],
            [_btn(f"{Emoji.CANCEL} Cancel", "scr:cancel")],
        ]
    )


def accounts_menu(accounts: list[tuple[str, str, bool]]) -> InlineKeyboardMarkup:
    """Rows: (label, status, is_active) with Use/Logout controls."""
    rows = []
    for label, status, active in accounts:
        mark = "✅" if active else ("🟢" if status == "Connected" else "⚪")
        rows.append([_btn(f"{mark} {label} · {status}"[:60], f"scr:use:{label}")])
        if status == "Connected":
            rows.append([_btn(f"🔓 Log out {label}"[:60], f"scr:logout:{label}")])
    rows.append([_btn("➕ Add account", "scr:login")])
    rows.append([_btn(f"{Emoji.BACK} Back", "scr:acctback")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def scrape_sources(
    sources: list[tuple[int, str]],
    *,
    selected: set[int] | None = None,
    manage: bool = False,
) -> InlineKeyboardMarkup:
    selected = selected or set()
    rows = []
    for sid, title in sources:
        if manage:
            rows.append([_btn(f"🗑 Remove · {title}"[:60], f"scr:delsrc:{sid}")])
        else:
            box = "✅" if sid in selected else "☐"
            rows.append([_btn(f"{box} {title}"[:60], f"scr:toggle:{sid}")])
    if not manage and selected:
        rows.append([_btn(f"{Emoji.SCRAPE} Continue ({len(selected)})", "scr:continue")])
    rows.append([_btn("➕ Add source", "scr:add")])
    if not manage:
        rows.append([_btn(f"{Emoji.ACCOUNT} Accounts", "scr:acct")])
    if sources:
        rows.append(
            [
                _btn(
                    "🧰 Manage sources" if not manage else "✅ Done",
                    "scr:sources" if not manage else "scr:back",
                )
            ]
        )
    rows.append([_btn(f"{Emoji.BACK} Back", "menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def all_accounts_menu(accounts: list[tuple[str, str, str]]) -> InlineKeyboardMarkup:
    """Rows: (owner, label, status). Admin picks one to act as."""
    rows = []
    for owner, label, status in accounts:
        rows.append(
            [_btn(f"👤 {label} · {status} · owner {owner}"[:60], f"adm:useacct:{label}")]
        )
    rows.append([_btn("↩️ Use my own account", "adm:useacct:__self__")])
    rows.append([_btn(f"{Emoji.BACK} Back", "adm:panel:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def broadcast_confirm(target: str = "users") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn(_mark("Users", target == "users"), "adm:bc:to:users"),
                _btn(_mark("Channel", target == "channel"), "adm:bc:to:channel"),
                _btn(_mark("Both", target == "both"), "adm:bc:to:both"),
            ],
            [_btn("✅ Send broadcast", "adm:bc:send")],
            [_btn(f"{Emoji.CANCEL} Cancel", "adm:bc:cancel")],
        ]
    )


def defaults_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("♻️ Reset defaults", "scr:defaults:reset")],
            [_btn(f"{Emoji.BACK} Back", "scr:backpanel")],
        ]
    )


def clean_prompt() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("🧹 Clean & build .txt", "scr:doclean")],
            [_btn("✅ Keep raw", "scr:keepraw")],
        ]
    )


def combine_prompt(count: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(f"🔗 Combine into one .txt", "scr:combine:yes")],
            [_btn("✅ Keep separate", "scr:combine:no")],
        ]
    )


def api_setup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(f"{Emoji.LOCK} Set API credentials", "adm:panel:api")],
            [_btn("📖 How it works", "scr:helptext")],
            [_btn(f"{Emoji.BACK} Back", "menu:home")],
        ]
    )


def account_help() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(f"{Emoji.LOGIN} Connect my account", "scr:login")],
            [_btn("📖 How it works", "scr:helptext")],
            [_btn(f"{Emoji.BACK} Back", "menu:home")],
        ]
    )


def admin_panel(forward_on: bool, access_on: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn(_mark("📡 Forward", forward_on), "adm:panel:forward"),
                _btn(_mark("🔐 Access", access_on), "adm:panel:access"),
            ],
            [_btn("🧪 Forward test", "adm:panel:ftest")],
            [_btn("⏩ Forward pending now", "adm:panel:flush")],
            [
                _btn("📡 Forward channel", "adm:panel:fchan"),
                _btn("📨 Scrape channel", "adm:panel:schan"),
            ],
            [_btn("🔐 Telegram API credentials", "adm:panel:api")],
            [_btn("👥 All accounts", "adm:accts")],
            [
                _btn("📣 Broadcast", "adm:bcast"),
                _btn(f"{Emoji.STATS} Health", "adm:health"),
            ],
            [
                _btn("🔑 Gen 5 × 1d", "adm:panel:gen:5:1"),
                _btn("🔑 Gen 10 × 7d", "adm:panel:gen:10:7"),
            ],
            [
                _btn(f"{Emoji.KEY} Keys", "adm:panel:keys"),
                _btn(f"{Emoji.STATS} Stats", "adm:panel:stats"),
            ],
            [
                _btn(f"{Emoji.USER} Users", "adm:panel:users"),
                _btn(f"{Emoji.SETTINGS} Settings", "settings:open"),
            ],
            [_btn(f"{Emoji.BACK} Back", "menu:home")],
        ]
    )


def clear_queue_confirm(count: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(f"{Emoji.SUCCESS} Yes, clear {count}", "queue:clear:yes")],
            [_btn(f"{Emoji.CANCEL} Cancel", "menu:home")],
        ]
    )
