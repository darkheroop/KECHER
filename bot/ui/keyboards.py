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
    """The 2-column grid shown in the design (plus full-width rows)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(f"{Emoji.FIND} Scrape", "menu:scrape"), _btn(f"{Emoji.CLEAN} Clean", "menu:clean")],
            [_btn(f"{Emoji.LIVE_CHECK} Live Check", "menu:live"), _btn(f"{Emoji.FIND} Filter", "menu:filter")],
            [_btn(f"{Emoji.SPLIT} Split", "menu:split"), _btn(f"{Emoji.RECYCLE} Dedup", "menu:dedup")],
            [_btn(f"{Emoji.PAGE} Add File", "menu:addfile"), _btn(f"{Emoji.STAR} Merge", "menu:merge")],
            [_btn(f"{Emoji.FIND} Find BIN", "menu:findbin")],
            [_btn(f"{Emoji.ADMIN} Admin Panel", "adm:panel:home")],
            [_btn(f"{Emoji.SETTINGS} Settings", "settings:open")],
        ]
    )


def settings_menu(ui_mode: str) -> InlineKeyboardMarkup:
    button = ui_mode == UIMode.BUTTONS.value
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn(_mark(f"{Emoji.BUTTON_MODE} Button", button), "set:mode:button"),
                _btn(_mark(f"{Emoji.TEXT_MODE} Text", not button), "set:mode:text"),
            ],
            [_btn(f"{Emoji.BACK} Back", "menu:home")],
        ]
    )


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


def admin_panel(forward_on: bool, access_on: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn(_mark("📡 Forward", forward_on), "adm:panel:forward"),
                _btn(_mark("🔐 Access", access_on), "adm:panel:access"),
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
