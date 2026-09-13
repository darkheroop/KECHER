"""Inline keyboard builders.

Kept free of handler logic so they can be reused by any router.
"""

from __future__ import annotations

import math

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.db.enums import UIMode
from bot.services.geo import country_label
from bot.ui.emoji import Emoji


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn(f"{Emoji.FILE} File Tools", "menu:file"),
                _btn(f"{Emoji.SEARCH} Data Tools", "menu:data"),
            ],
            [
                _btn(f"{Emoji.SECURITY} Security", "menu:security"),
                _btn(f"{Emoji.SCRAPE} Sources", "menu:sources"),
            ],
            [
                _btn(f"{Emoji.SETTINGS} Settings", "settings:open"),
                _btn(f"{Emoji.JOBS} Jobs", "jobs:open"),
            ],
            [
                _btn(f"{Emoji.KEY} Access", "access:open"),
                _btn(f"{Emoji.HELP} Help", "menu:help"),
            ],
        ]
    )


def file_tools_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn(f"{Emoji.SPLIT} Split", "menu:todo:split"),
                _btn(f"{Emoji.CLEAN} Clean", "menu:todo:clean"),
            ],
            [
                _btn(f"{Emoji.CONVERT} DOC \u2192 TXT", "menu:todo:doc2txt"),
                _btn(f"{Emoji.CSV} CSV \u2192 TXT", "menu:todo:csv"),
            ],
            [
                _btn(f"{Emoji.MERGE} Merge", "menu:todo:merge"),
                _btn(f"{Emoji.DEDUP} Deduplicate", "menu:todo:dedup"),
            ],
            [_btn(f"{Emoji.SUCCESS} Back", "menu:back")],
        ]
    )


def data_tools_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn(f"{Emoji.SEARCH} Find", "menu:todo:find"),
                _btn(f"{Emoji.COUNTRY} Country", "menu:todo:country"),
            ],
            [
                _btn(f"{Emoji.BANK} Bank", "menu:todo:bank"),
                _btn(f"{Emoji.SUCCESS} Back", "menu:back"),
            ],
        ]
    )


def jobs_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(f"{Emoji.JOBS} Refresh", "jobs:refresh")],
            [_btn(f"{Emoji.SUCCESS} Back", "menu:back")],
        ]
    )


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_btn(f"{Emoji.SUCCESS} Back", "menu:back")]]
    )


def _mark(label: str, active: bool) -> str:
    return f"{Emoji.SUCCESS} {label}" if active else label


def upload_actions(*, is_doc: bool, is_csv: bool, file_id: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if is_doc:
        rows.append([_btn(f"{Emoji.CONVERT} Convert to TXT", f"op:doc2txt:{file_id}")])
    if is_csv:
        rows.append([_btn(f"{Emoji.CSV} CSV \u2192 TXT", f"op:csv:{file_id}")])
    rows.append(
        [
            _btn(f"{Emoji.SPLIT} Split", f"op:split:{file_id}"),
            _btn(f"{Emoji.CLEAN} Clean", f"op:clean:{file_id}"),
        ]
    )
    rows.append(
        [
            _btn(f"{Emoji.DEDUP} Deduplicate", f"op:dedup:{file_id}"),
            _btn(f"{Emoji.INBOX} Add to queue", f"op:addfile:{file_id}"),
        ]
    )
    rows.append([_btn(f"{Emoji.CANCEL} Cancel", f"op:cancel:{file_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def split_mode_keyboard(file_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("By lines", f"split:mode:lines:{file_id}")],
            [_btn("By parts", f"split:mode:parts:{file_id}")],
            [_btn("By size (bytes)", f"split:mode:size:{file_id}")],
            [_btn(f"{Emoji.CANCEL} Cancel", f"op:cancel:{file_id}")],
        ]
    )


def csv_columns_keyboard(file_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("All columns", f"csv:all:{file_id}")],
            [_btn("Select columns", f"csv:select:{file_id}")],
            [_btn(f"{Emoji.CANCEL} Cancel", f"op:cancel:{file_id}")],
        ]
    )


def dedup_mode_keyboard(file_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("Exact duplicates", f"dedup:exact:{file_id}")],
            [_btn("Normalized duplicates", f"dedup:normalized:{file_id}")],
            [_btn(f"{Emoji.CANCEL} Cancel", f"op:cancel:{file_id}")],
        ]
    )


def clean_options_keyboard(file_id: int, options: dict) -> InlineKeyboardMarkup:
    def flag(key: str, label: str) -> InlineKeyboardButton:
        return _btn(_mark(label, bool(options.get(key))), f"clean:toggle:{key}:{file_id}")

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [flag("remove_empty", "Remove empty lines"), flag("dedup", "Remove duplicates")],
            [flag("luhn", "Luhn check all (offline)"), flag("sort", "Sort")],
            [_btn(f"{Emoji.CLEAN} Run cleaning", f"clean:run:{file_id}")],
            [_btn(f"{Emoji.CANCEL} Cancel", f"op:cancel:{file_id}")],
        ]
    )


def merge_options_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(f"{Emoji.MERGE} Merge", "merge:run:plain")],
            [_btn(f"{Emoji.MERGE} Merge + Dedup", "merge:run:dedup")],
            [_btn(f"{Emoji.MERGE} Merge + Sort", "merge:run:sort")],
            [_btn(f"{Emoji.CANCEL} Cancel", "menu:back")],
        ]
    )


def clear_queue_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(f"{Emoji.SUCCESS} Yes, clear", "queue:clear:yes")],
            [_btn(f"{Emoji.CANCEL} Cancel", "menu:back")],
        ]
    )


def settings_keyboard(
    *,
    ui_mode: str,
    progress_messages: bool,
    cleanup_minutes: int,
    language: str,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn(_mark("Buttons", ui_mode == UIMode.BUTTONS.value), "set:ui:buttons"),
                _btn(_mark("Commands", ui_mode == UIMode.COMMANDS.value), "set:ui:commands"),
                _btn(_mark("Hybrid", ui_mode == UIMode.HYBRID.value), "set:ui:hybrid"),
            ],
            [
                _btn(_mark("On", progress_messages), "set:prog:1"),
                _btn(_mark("Off", not progress_messages), "set:prog:0"),
            ],
            [
                _btn(_mark("5 min", cleanup_minutes == 5), "set:clean:5"),
                _btn(_mark("10 min", cleanup_minutes == 10), "set:clean:10"),
                _btn(_mark("30 min", cleanup_minutes == 30), "set:clean:30"),
            ],
            [_btn(_mark("English", language == "en"), "set:lang:en")],
            [_btn(f"{Emoji.SUCCESS} Back", "menu:back")],
        ]
    )


def sources_keyboard(sources: list[tuple[int, str]], *, prefix: str = "scr:src") -> InlineKeyboardMarkup:
    rows = [[_btn(title, f"{prefix}:{source_id}")] for source_id, title in sources]
    rows.append([_btn(f"{Emoji.SUCCESS} Back", "menu:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def scrape_options_keyboard(
    *,
    limit: int,
    fmt: str,
    include_media: bool,
    has_dates: bool,
) -> InlineKeyboardMarkup:
    def lim(value: int) -> InlineKeyboardButton:
        return _btn(_mark(str(value), limit == value), f"scr:limit:{value}")

    def form(value: str) -> InlineKeyboardButton:
        return _btn(_mark(value.upper(), fmt == value), f"scr:fmt:{value}")

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [lim(50), lim(100), lim(500)],
            [form("txt"), form("csv"), form("json")],
            [
                _btn(_mark("Include media", include_media), f"scr:media:{0 if include_media else 1}"),
                _btn(_mark("Dates set", has_dates), "scr:dates"),
            ],
            [_btn(f"{Emoji.SCRAPE} Run", "scr:run")],
            [_btn(f"{Emoji.CANCEL} Cancel", "menu:back")],
        ]
    )


def validate_options_keyboard(file_id: int, options: dict) -> InlineKeyboardMarkup:
    def flag(key: str, label: str) -> InlineKeyboardButton:
        return _btn(_mark(label, bool(options.get(key))), f"val:toggle:{key}:{file_id}")

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [flag("luhn", "Luhn"), flag("expiry", "Expiry syntax")],
            [flag("length", "Length"), flag("test_bin", "Official test BINs only")],
            [_btn(f"{Emoji.SECURITY} Run validation", f"val:run:{file_id}")],
            [_btn(f"{Emoji.CANCEL} Cancel", f"op:cancel:{file_id}")],
        ]
    )


def picker_keyboard(
    *,
    kind: str,
    groups: list[tuple[str, int]],
    page: int,
    page_size: int = 8,
) -> InlineKeyboardMarkup:
    """Paginated selector for country/bank groups (callback ``pick:<kind>:<i>``)."""
    start = page * page_size
    end = min(start + page_size, len(groups))
    rows: list[list[InlineKeyboardButton]] = []

    for index in range(start, end):
        value, count = groups[index]
        label = country_label(value) if kind == "country" else value
        rows.append([_btn(f"{label} — {count:,}", f"pick:{kind}:{index}")])

    pages = max(1, math.ceil(len(groups) / page_size))
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(_btn("\u2b05\ufe0f", f"picknav:{kind}:{page - 1}"))
    nav.append(_btn(f"{page + 1}/{pages}", "noop"))
    if page < pages - 1:
        nav.append(_btn("\u27a1\ufe0f", f"picknav:{kind}:{page + 1}"))
    rows.append(nav)
    rows.append([_btn(f"{Emoji.SUCCESS} Back", "menu:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
