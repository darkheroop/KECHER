from datetime import UTC, datetime, timedelta

from bot.config import get_settings
from bot.db.engine import session_scope
from bot.db.repositories import create_file, get_or_create_user, list_user_files
from bot.services.file_manager import FileManager
from bot.services.retention import reap_expired_files, reap_user_files


async def _make_file(telegram_id: int, name: str, *, expires_at) -> None:
    fm = FileManager(get_settings())
    allocated = fm.allocate(telegram_id, name)
    allocated.path.write_bytes(b"payload")
    async with session_scope() as session:
        user, _ = await get_or_create_user(session, telegram_id)
        await create_file(
            session,
            user_id=user.id,
            original_name=name,
            safe_name=allocated.safe_name,
            rel_path=allocated.rel_path,
            size_bytes=7,
            expires_at=expires_at,
        )


async def test_reaper_removes_expired(db) -> None:
    past = datetime.now(UTC) - timedelta(minutes=5)
    future = datetime.now(UTC) + timedelta(minutes=5)
    await _make_file(1, "old.txt", expires_at=past)
    await _make_file(1, "new.txt", expires_at=future)

    fm = FileManager(get_settings())
    removed = await reap_expired_files(fm)
    assert removed == 1

    async with session_scope() as session:
        user, _ = await get_or_create_user(session, 1)
        remaining = await list_user_files(session, user.id)
        assert [f.original_name for f in remaining] == ["new.txt"]

    assert not (fm.user_root(1) / "inbox" / "old.txt").exists()


async def test_reap_user_files(db) -> None:
    future = datetime.now(UTC) + timedelta(minutes=5)
    await _make_file(2, "a.txt", expires_at=future)
    await _make_file(2, "b.txt", expires_at=future)

    fm = FileManager(get_settings())
    assert await reap_user_files(fm, 2) == 2
    async with session_scope() as session:
        user, _ = await get_or_create_user(session, 2)
        assert await list_user_files(session, user.id) == []
