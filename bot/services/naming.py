"""Output filename rendering.

Default names are operation based (``cleaned.txt``, ``part-1.txt`` …). Users can
override them with a template that supports placeholders, and the owner can set
a global suffix (e.g. ``@Lord_Jat``) from the admin panel.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

DEFAULT_SUFFIX = "@Lord_Jat"
DEFAULT_TEMPLATE = "{op}"

# Extensions we never want duplicated (``cleaned.txt.txt``).
_ext_re = re.compile(r"\{([a-zA-Z_]+)\}")
_unsafe_re = re.compile(r"[^A-Za-z0-9._@()\- ]+")

_suffix: str | None = None


def set_suffix(value: str | None) -> None:
    """Set the runtime suffix override (``None`` = use the default)."""
    global _suffix
    _suffix = None if value is None else str(value)


def suffix() -> str:
    return DEFAULT_SUFFIX if _suffix is None else _suffix


def sanitize_stem(value: str) -> str:
    """Keep filenames filesystem- and Telegram-safe."""
    cleaned = _unsafe_re.sub("", (value or "").strip())
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._-")
    return cleaned[:120] or "file"


def render(
    template: str | None,
    *,
    op: str,
    index: int | None = None,
    keyword: str | None = None,
    source: str | None = None,
    now: datetime | None = None,
    ext: str = "txt",
) -> str:
    """Render a template into a safe filename with an extension."""
    moment = now or datetime.now(UTC)
    values = {
        "op": op,
        "name": op,
        "index": "" if index is None else str(index),
        "keyword": keyword or "",
        "source": source or "",
        "date": moment.strftime("%Y-%m-%d"),
        "time": moment.strftime("%H%M"),
    }
    text = (template or DEFAULT_TEMPLATE).strip()
    text = _ext_re.sub(lambda m: values.get(m.group(1).lower(), m.group(0)), text)
    text = text.strip()
    if index is not None and "{index}" not in (template or DEFAULT_TEMPLATE):
        text = f"{text}-{index}"
    stem = sanitize_stem(text)
    if ext and not stem.lower().endswith(f".{ext.lower()}"):
        stem = f"{stem}.{ext}"
    return stem


async def _template_for(telegram_id: int) -> tuple[str, bool]:
    """Return ``(template, must_clear_one_shot)`` for the next output."""
    from bot.services import prefs

    try:
        data = await prefs.load_prefs(telegram_id)
    except Exception:  # noqa: BLE001 - naming must never break an operation
        return DEFAULT_TEMPLATE, False
    once = str(data.get("filename_once") or "").strip()
    saved = str(data.get("filename") or "").strip()
    return (once or saved or DEFAULT_TEMPLATE), bool(once)


async def _clear_one_shot(telegram_id: int) -> None:
    from bot.services import prefs

    try:
        data = await prefs.load_prefs(telegram_id)
        data["filename_once"] = ""
        await prefs.save_prefs(telegram_id, data)
    except Exception:  # noqa: BLE001
        pass


async def output_name(
    telegram_id: int,
    op: str,
    *,
    index: int | None = None,
    keyword: str | None = None,
    source: str | None = None,
    ext: str = "txt",
) -> str:
    """Resolve the user's saved template (or a one-shot override) for an output."""
    template, clear = await _template_for(telegram_id)
    name = render(
        template, op=op, index=index, keyword=keyword, source=source, ext=ext
    )
    if clear:
        await _clear_one_shot(telegram_id)
    return name


async def output_names(
    telegram_id: int,
    op: str,
    indices,
    *,
    keyword: str | None = None,
    source: str | None = None,
    ext: str = "txt",
) -> list[str]:
    """Render several indexed names (e.g. split parts) from a single template read."""
    template, clear = await _template_for(telegram_id)
    names = [
        render(template, op=op, index=index, keyword=keyword, source=source, ext=ext)
        for index in indices
    ]
    if clear:
        await _clear_one_shot(telegram_id)
    return names


def describe(template: str | None) -> str:
    """Human preview of the current template."""
    if not template:
        return "default (operation name)"
    return f"<code>{template}</code>"


__all__ = [
    "DEFAULT_SUFFIX",
    "DEFAULT_TEMPLATE",
    "describe",
    "output_name",
    "output_names",
    "render",
    "sanitize_stem",
    "set_suffix",
    "suffix",
]
