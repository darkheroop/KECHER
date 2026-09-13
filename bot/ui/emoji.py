"""Emoji abstraction layer.

Custom/premium Telegram emoji ids must never be hard-coded inside handlers.
Reference emoji symbolically (``Emoji.SUCCESS``) and let this module decide
whether to emit a premium ``<tg-emoji>`` tag or the Unicode fallback.

Usage (requires HTML parse mode)::

    from bot.ui.emoji import Emoji

    text = f"{Emoji.SUCCESS} Done"

Premium ids are injected from configuration at startup::

    configure_custom({"SUCCESS": "5368324170671202286"})

Without configuration, every token renders as its Unicode fallback, so the UI
works identically with or without Telegram Premium.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class EmojiSpec:
    unicode: str
    default_custom_id: str | None = None


# Canonical registry: abstract name -> spec. Add new emoji here only.
_SPECS: dict[str, EmojiSpec] = {
    "FILE": EmojiSpec("📁"),
    "SUCCESS": EmojiSpec("✅"),
    "ERROR": EmojiSpec("❌"),
    "WARNING": EmojiSpec("⚠️"),
    "SETTINGS": EmojiSpec("⚙️"),
    "SECURITY": EmojiSpec("🛡️"),
    "CONVERT": EmojiSpec("📄"),
    "DOC": EmojiSpec("📝"),
    "CSV": EmojiSpec("📑"),
    "SPLIT": EmojiSpec("✂️"),
    "CLEAN": EmojiSpec("🧹"),
    "DEDUP": EmojiSpec("🧩"),
    "SEARCH": EmojiSpec("🔎"),
    "COUNTRY": EmojiSpec("🌍"),
    "BANK": EmojiSpec("🏦"),
    "MERGE": EmojiSpec("🔗"),
    "INBOX": EmojiSpec("📥"),
    "SCRAPE": EmojiSpec("🧲"),
    "LOGIN": EmojiSpec("🔐"),
    "ACCOUNT": EmojiSpec("👤"),
    "PRIVATE": EmojiSpec("🔒"),
    "LIVE": EmojiSpec("🛡️"),
    "JOBS": EmojiSpec("🗂️"),
    "CANCEL": EmojiSpec("🚫"),
    "QUEUE": EmojiSpec("📚"),
    "DOWNLOAD": EmojiSpec("📥"),
    "PROGRESS": EmojiSpec("🔄"),
    "INFO": EmojiSpec("ℹ️"),
    "LANGUAGE": EmojiSpec("🌐"),
    "START": EmojiSpec("🚀"),
    "HELP": EmojiSpec("❓"),
    # --- access / admin ---
    "KEY": EmojiSpec("🔑"),
    "ADMIN": EmojiSpec("👑"),
    "GENERATE": EmojiSpec("✨"),
    "REDEEM": EmojiSpec("🎟️"),
    "LOCK": EmojiSpec("🔒"),
    "UNLOCK": EmojiSpec("🔓"),
    "ACCESS": EmojiSpec("🔐"),
    "USER": EmojiSpec("🧑"),
    "TIME": EmojiSpec("⏳"),
    "CLOCK": EmojiSpec("🕒"),
    "CALENDAR": EmojiSpec("📅"),
    "LIST": EmojiSpec("📋"),
    "DELETE": EmojiSpec("🗑️"),
    "ADD": EmojiSpec("➕"),
    "GRANT": EmojiSpec("🎁"),
    "CHECK": EmojiSpec("✔️"),
    "DENIED": EmojiSpec("⛔"),
    "ID": EmojiSpec("🪪"),
    "STATS": EmojiSpec("📊"),
    "COPY": EmojiSpec("📋"),
    "BACK": EmojiSpec("◀️"),
    "NEXT": EmojiSpec("▶️"),
}

_custom_ids: dict[str, str] = {}


def configure_custom(ids: Mapping[str, str] | None) -> None:
    """Register custom emoji ids (name -> Telegram custom emoji id)."""
    _custom_ids.clear()
    if ids:
        for key, value in ids.items():
            name = str(key).upper()
            if name in _SPECS and value:
                _custom_ids[name] = str(value)


def render(name: str) -> str:
    """Render an emoji token, preferring a configured custom emoji."""
    key = name.upper()
    spec = _SPECS.get(key)
    if spec is None:
        raise KeyError(f"Unknown emoji: {name}")

    custom_id = _custom_ids.get(key) or spec.default_custom_id
    if custom_id and str(custom_id).isdigit():
        return f'<tg-emoji emoji-id="{custom_id}">{spec.unicode}</tg-emoji>'
    return spec.unicode


class _Token:
    """Symbolic emoji placeholder that renders lazily via f-strings."""

    __slots__ = ("_name",)

    def __init__(self, name: str) -> None:
        self._name = name

    def __str__(self) -> str:
        return render(self._name)

    def __format__(self, format_spec: str) -> str:
        return format(str(self), format_spec)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Emoji.{self._name}"


class Emoji:
    """Symbolic emoji namespace. Access members as ``Emoji.FILE`` etc."""

    FILE = _Token("FILE")
    SUCCESS = _Token("SUCCESS")
    ERROR = _Token("ERROR")
    WARNING = _Token("WARNING")
    SETTINGS = _Token("SETTINGS")
    SECURITY = _Token("SECURITY")
    CONVERT = _Token("CONVERT")
    DOC = _Token("DOC")
    CSV = _Token("CSV")
    SPLIT = _Token("SPLIT")
    CLEAN = _Token("CLEAN")
    DEDUP = _Token("DEDUP")
    SEARCH = _Token("SEARCH")
    COUNTRY = _Token("COUNTRY")
    BANK = _Token("BANK")
    MERGE = _Token("MERGE")
    INBOX = _Token("INBOX")
    SCRAPE = _Token("SCRAPE")
    LOGIN = _Token("LOGIN")
    ACCOUNT = _Token("ACCOUNT")
    PRIVATE = _Token("PRIVATE")
    LIVE = _Token("LIVE")
    JOBS = _Token("JOBS")
    CANCEL = _Token("CANCEL")
    QUEUE = _Token("QUEUE")
    DOWNLOAD = _Token("DOWNLOAD")
    PROGRESS = _Token("PROGRESS")
    INFO = _Token("INFO")
    LANGUAGE = _Token("LANGUAGE")
    START = _Token("START")
    HELP = _Token("HELP")
    KEY = _Token("KEY")
    ADMIN = _Token("ADMIN")
    GENERATE = _Token("GENERATE")
    REDEEM = _Token("REDEEM")
    LOCK = _Token("LOCK")
    UNLOCK = _Token("UNLOCK")
    ACCESS = _Token("ACCESS")
    USER = _Token("USER")
    TIME = _Token("TIME")
    CLOCK = _Token("CLOCK")
    CALENDAR = _Token("CALENDAR")
    LIST = _Token("LIST")
    DELETE = _Token("DELETE")
    ADD = _Token("ADD")
    GRANT = _Token("GRANT")
    CHECK = _Token("CHECK")
    DENIED = _Token("DENIED")
    ID = _Token("ID")
    STATS = _Token("STATS")
    COPY = _Token("COPY")
    BACK = _Token("BACK")
    NEXT = _Token("NEXT")


def _spec_names() -> list[str]:  # pragma: no cover - introspection helper
    return sorted(_SPECS)


__all__ = ["Emoji", "EmojiSpec", "configure_custom", "render"]
