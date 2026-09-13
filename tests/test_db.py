from sqlalchemy import select

from bot.db.engine import session_scope
from bot.db.enums import AuditAction
from bot.db.models import AuditLog, User, UserSettings
from bot.db.repositories import (
    get_or_create_user,
    get_user_settings,
    record_audit,
    update_user_settings,
)


async def test_get_or_create_user_is_idempotent(db) -> None:
    async with session_scope() as session:
        user, created = await get_or_create_user(session, 555, username="alice")
        assert created is True

    async with session_scope() as session:
        user2, created2 = await get_or_create_user(session, 555, username="alice")
        assert created2 is False
        assert user2.id == user.id

    async with session_scope() as session:
        count = len((await session.scalars(select(User))).all())
        assert count == 1


async def test_default_settings_created(db) -> None:
    async with session_scope() as session:
        user, _ = await get_or_create_user(session, 777)
        settings = await get_user_settings(session, user.id)
        assert settings.ui_mode == "buttons"
        assert settings.progress_messages is True
        assert settings.language == "en"


async def test_update_settings(db) -> None:
    async with session_scope() as session:
        user, _ = await get_or_create_user(session, 888)
        await update_user_settings(session, user.id, ui_mode="hybrid", cleanup_minutes=30)

    async with session_scope() as session:
        settings = await get_user_settings(session, user.id)
        assert settings.ui_mode == "hybrid"
        assert settings.cleanup_minutes == 30


async def test_update_settings_rejects_unknown(db) -> None:
    async with session_scope() as session:
        user, _ = await get_or_create_user(session, 999)
        try:
            await update_user_settings(session, user.id, is_admin=True)
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError("unknown setting should be rejected")


async def test_audit_log_written(db) -> None:
    async with session_scope() as session:
        user, _ = await get_or_create_user(session, 111)
        await record_audit(session, user_id=user.id, action=AuditAction.FILE_RECEIVED)

    async with session_scope() as session:
        logs = (await session.scalars(select(AuditLog))).all()
        assert any(log.action == "file_received" for log in logs)


async def test_settings_cascade_delete(db) -> None:
    async with session_scope() as session:
        user, _ = await get_or_create_user(session, 222)
        await session.delete(user)

    async with session_scope() as session:
        assert (await session.scalars(select(UserSettings))).all() == []
