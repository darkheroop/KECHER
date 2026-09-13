"""Security primitives: size limits and quotas."""

from __future__ import annotations

from bot.config import Settings


class LimitExceeded(ValueError):
    """Raised when an upload or workspace violates a configured limit."""


def human_size(num_bytes: int) -> str:
    """Format a byte count as a compact human-readable string."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"  # pragma: no cover - unreachable


def check_file_size(size_bytes: int, settings: Settings) -> None:
    """Raise :class:`LimitExceeded` if a single upload is too large."""
    if size_bytes < 0:
        raise LimitExceeded("File size cannot be negative")
    if size_bytes > settings.max_file_size_bytes:
        raise LimitExceeded(
            f"File exceeds the {settings.max_file_size_mb} MB limit "
            f"(got {human_size(size_bytes)})"
        )


def check_quota(current_usage_bytes: int, incoming_bytes: int, settings: Settings) -> None:
    """Raise :class:`LimitExceeded` if writing ``incoming_bytes`` would exceed quota."""
    projected = current_usage_bytes + incoming_bytes
    if projected > settings.user_disk_quota_bytes:
        raise LimitExceeded(
            f"Storage quota exceeded: {human_size(projected)} of "
            f"{settings.user_disk_quota_mb} MB allowed"
        )
