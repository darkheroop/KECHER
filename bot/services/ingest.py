"""Upload ingestion: capacity checks, download, hashing, DB registration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.db.models import User, UserFile
from bot.db.repositories import create_file
from bot.security.limits import LimitExceeded
from bot.services.file_manager import FileManager
from bot.services.filetypes import is_ingestible

# download(telegram_file_id, destination_path) -> None
DownloadFn = Callable[[str, Path], Awaitable[None]]


class IngestError(RuntimeError):
    """Raised when an upload cannot be accepted or stored."""


async def ingest_document(
    session: AsyncSession,
    files: FileManager,
    settings: Settings,
    *,
    user: User,
    file_id: str,
    file_name: str,
    file_size: int | None,
    download: DownloadFn,
    ttl_minutes: int,
) -> UserFile:
    """Download an uploaded Telegram document into the user's sandbox.

    Rejects unsupported extensions and files that exceed the size / quota
    limits, cleans up partial downloads on failure, and stores only metadata.
    """
    if not is_ingestible(file_name):
        raise IngestError(f"Unsupported file type: {Path(file_name).suffix or '(none)'}")

    try:
        files.check_capacity(user.telegram_id, file_size or 0)
    except LimitExceeded as exc:
        raise IngestError(str(exc)) from exc

    allocated = files.allocate(user.telegram_id, file_name)
    try:
        await download(file_id, allocated.path)
    except Exception as exc:  # noqa: BLE001 - surface a clean error to the user
        try:
            allocated.path.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - best effort
            pass
        raise IngestError("Could not download the file from Telegram") from exc

    stored = files.finalize(allocated)
    expires_at = datetime.now(UTC) + timedelta(minutes=max(1, ttl_minutes))

    return await create_file(
        session,
        user_id=user.id,
        original_name=file_name,
        safe_name=stored.safe_name,
        rel_path=stored.rel_path,
        size_bytes=stored.size_bytes,
        telegram_file_id=file_id,
        sha256=stored.sha256,
        expires_at=expires_at,
    )
