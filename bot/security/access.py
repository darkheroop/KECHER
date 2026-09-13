"""Access-control helpers (admin checks and key-based access state)."""

from __future__ import annotations

from datetime import UTC, datetime

from bot.config import Settings
from bot.db.models import User


def ensure_aware(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; treat stored values as UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def is_admin(user: User, settings: Settings) -> bool:
    """Admin if flagged in the DB or listed in ``ADMIN_IDS``."""
    return bool(user.is_admin) or user.telegram_id in set(settings.admin_ids)


def has_active_access(user: User, now: datetime | None = None) -> bool:
    until = ensure_aware(user.access_until)
    if until is None:
        return False
    return until > (now or datetime.now(UTC))


def access_state(user: User, settings: Settings, now: datetime | None = None) -> str:
    if is_admin(user, settings):
        return "admin"
    if has_active_access(user, now):
        return "active"
    return "expired" if ensure_aware(user.access_until) is not None else "none"


def format_remaining(until: datetime | None, now: datetime | None = None) -> str:
    """Human-readable remaining time, e.g. ``2d 4h 15m``."""
    target = ensure_aware(until)
    if target is None:
        return "—"
    moment = now or datetime.now(UTC)
    seconds = int((target - moment).total_seconds())
    if seconds <= 0:
        return "expired"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return " ".join(parts)
