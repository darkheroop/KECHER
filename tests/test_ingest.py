from pathlib import Path

import pytest

from bot.config import Settings
from bot.db.engine import session_scope
from bot.db.repositories import get_or_create_user
from bot.services.file_manager import FileManager
from bot.services.ingest import IngestError, ingest_document


async def test_declared_cloud_oversize_is_rejected_before_download(db) -> None:
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        storage_root=db.resolved_storage_root(),
        max_file_size_mb=60,
        telegram_api_base="",
    )
    files = FileManager(settings)
    called = False

    async def download(file_id: str, path: Path) -> None:
        nonlocal called
        called = True

    async with session_scope() as session:
        user, _ = await get_or_create_user(session, 100)
        with pytest.raises(IngestError, match="cloud mode"):
            await ingest_document(
                session,
                files,
                settings,
                user=user,
                file_id="file",
                file_name="large.txt",
                file_size=20 * 1024 * 1024 + 1,
                download=download,
                ttl_minutes=10,
            )

    assert called is False


async def test_actual_oversize_is_removed_when_reported_size_is_missing(
    db, tmp_path: Path
) -> None:
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        storage_root=tmp_path / "storage",
        max_file_size_mb=1,
        telegram_api_base="http://local:8081",
    )
    files = FileManager(settings)

    async def download(file_id: str, path: Path) -> None:
        path.write_bytes(b"x" * (1024 * 1024 + 1))

    async with session_scope() as session:
        user, _ = await get_or_create_user(session, 101)
        with pytest.raises(IngestError, match="1 MB limit"):
            await ingest_document(
                session,
                files,
                settings,
                user=user,
                file_id="file",
                file_name="large.txt",
                file_size=None,
                download=download,
                ttl_minutes=10,
            )

    assert list((tmp_path / "storage").rglob("large.txt")) == []
