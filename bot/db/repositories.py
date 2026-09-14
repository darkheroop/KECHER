"""Data-access helpers (repositories).

These functions keep SQLAlchemy session handling out of the Telegram handlers
and are safe to call from background workers. They never load file contents.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.db.enums import AuditAction, JobStatus, Language, UIMode
from bot.db.models import (
    AccessKey,
    AuditLog,
    AuthorizedSource,
    BotSetting,
    Job,
    MergeQueue,
    MergeQueueItem,
    User,
    UserFile,
    UserSettings,
)
from bot.security.access import ensure_aware
from bot.services.keys import generate_code, normalize_code

TERMINAL_JOB_STATUSES = {
    JobStatus.COMPLETED.value,
    JobStatus.FAILED.value,
    JobStatus.CANCELLED.value,
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- #
# Users & settings
# --------------------------------------------------------------------------- #
async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    *,
    username: str | None = None,
    first_name: str | None = None,
) -> tuple[User, bool]:
    """Fetch a user by Telegram id, creating it (and its settings) if needed.

    Returns ``(user, created)``.
    """
    user = await session.scalar(select(User).where(User.telegram_id == telegram_id))

    if user is None:
        user = User(telegram_id=telegram_id, username=username, first_name=first_name)
        session.add(user)
        await session.flush()

        defaults = get_settings()
        session.add(
            UserSettings(
                user_id=user.id,
                ui_mode=UIMode.BUTTONS.value,
                progress_messages=True,
                cleanup_minutes=defaults.cleanup_default_minutes,
                language=Language.ENGLISH.value,
            )
        )
        await session.flush()
        return user, True

    if username and user.username != username:
        user.username = username
    if first_name and user.first_name != first_name:
        user.first_name = first_name
    return user, False


async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
    return await session.scalar(select(User).where(User.telegram_id == telegram_id))


async def get_user_settings(session: AsyncSession, user_id: int) -> UserSettings:
    settings = await session.scalar(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    if settings is None:
        settings = UserSettings(
            user_id=user_id,
            ui_mode=UIMode.BUTTONS.value,
            cleanup_minutes=get_settings().cleanup_default_minutes,
            language=Language.ENGLISH.value,
        )
        session.add(settings)
        await session.flush()
    return settings


async def update_user_settings(
    session: AsyncSession, user_id: int, **fields: Any
) -> UserSettings:
    settings = await get_user_settings(session, user_id)
    allowed = {"ui_mode", "progress_messages", "cleanup_minutes", "language"}
    for key, value in fields.items():
        if key not in allowed:
            raise ValueError(f"Cannot update unknown setting: {key}")
        setattr(settings, key, value)
    await session.flush()
    return settings


# --------------------------------------------------------------------------- #
# Files
# --------------------------------------------------------------------------- #
async def create_file(
    session: AsyncSession,
    *,
    user_id: int,
    original_name: str,
    safe_name: str,
    rel_path: str,
    size_bytes: int,
    telegram_file_id: str | None = None,
    mime: str | None = None,
    sha256: str | None = None,
    expires_at: datetime | None = None,
) -> UserFile:
    record = UserFile(
        user_id=user_id,
        original_name=original_name,
        safe_name=safe_name,
        rel_path=rel_path,
        size_bytes=size_bytes,
        telegram_file_id=telegram_file_id,
        mime=mime,
        sha256=sha256,
        expires_at=expires_at,
    )
    session.add(record)
    await session.flush()
    return record


async def get_file(session: AsyncSession, file_id: int) -> UserFile | None:
    return await session.get(UserFile, file_id)


async def list_user_files(session: AsyncSession, user_id: int) -> list[UserFile]:
    result = await session.scalars(
        select(UserFile).where(UserFile.user_id == user_id).order_by(UserFile.id)
    )
    return list(result)


async def get_user_files_by_ids(
    session: AsyncSession, user_id: int, file_ids: list[int]
) -> list[UserFile]:
    """Fetch files by id, scoped to ``user_id`` to enforce per-user isolation."""
    if not file_ids:
        return []
    result = await session.scalars(
        select(UserFile).where(
            UserFile.user_id == user_id, UserFile.id.in_(file_ids)
        )
    )
    found = {record.id: record for record in result}
    return [found[fid] for fid in file_ids if fid in found]


async def list_expired_files(session: AsyncSession, now: datetime | None = None) -> list[UserFile]:
    moment = now or _utcnow()
    result = await session.scalars(
        select(UserFile).where(
            UserFile.expires_at.is_not(None), UserFile.expires_at <= moment
        )
    )
    return list(result)


async def delete_file_row(session: AsyncSession, file_id: int) -> None:
    record = await session.get(UserFile, file_id)
    if record is not None:
        await session.delete(record)


# --------------------------------------------------------------------------- #
# Jobs
# --------------------------------------------------------------------------- #
async def create_job(
    session: AsyncSession,
    *,
    user_id: int,
    kind: str,
    input_file_id: int | None = None,
    params: dict[str, Any] | None = None,
    chat_id: int | None = None,
    progress_message_id: int | None = None,
) -> Job:
    job = Job(
        user_id=user_id,
        kind=str(kind),
        status=JobStatus.QUEUED.value,
        progress=0,
        input_file_id=input_file_id,
        params=params or None,
        chat_id=chat_id,
        progress_message_id=progress_message_id,
    )
    session.add(job)
    await session.flush()
    return job


async def get_job(session: AsyncSession, job_id: int) -> Job | None:
    return await session.get(Job, job_id)


async def list_jobs(session: AsyncSession, user_id: int, limit: int = 10) -> list[Job]:
    result = await session.scalars(
        select(Job)
        .where(Job.user_id == user_id)
        .order_by(Job.id.desc())
        .limit(limit)
    )
    return list(result)


async def list_active_jobs(session: AsyncSession, user_id: int) -> list[Job]:
    result = await session.scalars(
        select(Job)
        .where(
            Job.user_id == user_id,
            Job.status.in_([JobStatus.QUEUED.value, JobStatus.PROCESSING.value]),
        )
        .order_by(Job.id)
    )
    return list(result)


async def set_job_status(
    session: AsyncSession,
    job: Job,
    status: JobStatus | str,
    *,
    error: str | None = None,
    progress: int | None = None,
) -> None:
    job.status = str(status)
    if error is not None:
        job.error = error
    if progress is not None:
        job.progress = progress
    if str(status) == JobStatus.PROCESSING.value and job.started_at is None:
        job.started_at = _utcnow()
    if str(status) in TERMINAL_JOB_STATUSES:
        job.finished_at = _utcnow()
    await session.flush()


async def set_job_progress(session: AsyncSession, job_id: int, progress: int) -> None:
    job = await session.get(Job, job_id)
    if job is not None and job.status == JobStatus.PROCESSING.value:
        job.progress = max(0, min(100, int(progress)))
        await session.flush()


# --------------------------------------------------------------------------- #
# Merge queues (per user)
# --------------------------------------------------------------------------- #
async def get_or_create_queue(session: AsyncSession, user_id: int) -> MergeQueue:
    queue = await session.scalar(select(MergeQueue).where(MergeQueue.user_id == user_id))
    if queue is None:
        queue = MergeQueue(user_id=user_id)
        session.add(queue)
        await session.flush()
    return queue


async def list_queue_items(session: AsyncSession, user_id: int) -> list[MergeQueueItem]:
    queue = await session.scalar(select(MergeQueue).where(MergeQueue.user_id == user_id))
    if queue is None:
        return []
    result = await session.scalars(
        select(MergeQueueItem)
        .where(MergeQueueItem.queue_id == queue.id)
        .order_by(MergeQueueItem.position)
    )
    return list(result)


async def add_queue_item(
    session: AsyncSession, user_id: int, file_id: int
) -> MergeQueueItem:
    queue = await get_or_create_queue(session, user_id)
    existing = await session.scalar(
        select(MergeQueueItem).where(
            MergeQueueItem.queue_id == queue.id,
            MergeQueueItem.file_id == file_id,
        )
    )
    if existing is not None:
        return existing

    max_pos = await session.scalar(
        select(MergeQueueItem.position)
        .where(MergeQueueItem.queue_id == queue.id)
        .order_by(MergeQueueItem.position.desc())
        .limit(1)
    )
    item = MergeQueueItem(
        queue_id=queue.id,
        file_id=file_id,
        position=(max_pos or 0) + 1,
    )
    session.add(item)
    await session.flush()
    return item


async def clear_queue(session: AsyncSession, user_id: int) -> int:
    queue = await session.scalar(select(MergeQueue).where(MergeQueue.user_id == user_id))
    if queue is None:
        return 0
    result = await session.execute(
        delete(MergeQueueItem).where(MergeQueueItem.queue_id == queue.id)
    )
    await session.flush()
    return result.rowcount or 0


# --------------------------------------------------------------------------- #
# Authorized sources
# --------------------------------------------------------------------------- #
async def add_authorized_source(
    session: AsyncSession,
    *,
    user_id: int,
    tg_peer_ref: str,
    title: str | None = None,
    kind: str = "group",
) -> AuthorizedSource:
    existing = await session.scalar(
        select(AuthorizedSource).where(
            AuthorizedSource.user_id == user_id,
            AuthorizedSource.tg_peer_ref == tg_peer_ref,
        )
    )
    if existing is not None:
        if title and existing.title != title:
            existing.title = title
        return existing

    source = AuthorizedSource(
        user_id=user_id, tg_peer_ref=tg_peer_ref, title=title, kind=kind
    )
    session.add(source)
    await session.flush()
    return source


async def list_authorized_sources(
    session: AsyncSession, user_id: int, *, kind: str | None = None
) -> list[AuthorizedSource]:
    stmt = select(AuthorizedSource).where(AuthorizedSource.user_id == user_id)
    if kind is not None:
        stmt = stmt.where(AuthorizedSource.kind == kind)
    result = await session.scalars(stmt.order_by(AuthorizedSource.id))
    return list(result)


async def get_authorized_source(
    session: AsyncSession, user_id: int, source_id: int
) -> AuthorizedSource | None:
    source = await session.get(AuthorizedSource, source_id)
    if source is None or source.user_id != user_id:
        return None
    return source


async def remove_authorized_source(
    session: AsyncSession, user_id: int, source_id: int
) -> bool:
    source = await get_authorized_source(session, user_id, source_id)
    if source is None:
        return False
    await session.delete(source)
    return True


# --------------------------------------------------------------------------- #
# Audit
# --------------------------------------------------------------------------- #
async def record_audit(
    session: AsyncSession,
    *,
    user_id: int | None,
    action: AuditAction | str,
    detail: dict[str, Any] | None = None,
) -> None:
    """Append an audit-log entry. ``detail`` must never contain secrets or PII."""
    session.add(
        AuditLog(
            user_id=user_id,
            action=str(action),
            detail=detail or None,
        )
    )
    await session.flush()


# --------------------------------------------------------------------------- #
# Access keys / licensing
# --------------------------------------------------------------------------- #
async def _unique_key_code(session: AsyncSession) -> str:
    for _ in range(20):
        code = generate_code()
        exists = await session.scalar(select(AccessKey.id).where(AccessKey.code == code))
        if exists is None:
            return code
    return generate_code(groups=4)  # pragma: no cover - astronomically unlikely


async def create_access_keys(
    session: AsyncSession,
    *,
    count: int,
    duration_minutes: int,
    created_by: int | None = None,
    batch: str | None = None,
    expires_at: datetime | None = None,
) -> list[AccessKey]:
    keys: list[AccessKey] = []
    for _ in range(max(1, count)):
        code = await _unique_key_code(session)
        key = AccessKey(
            code=code,
            duration_minutes=max(1, duration_minutes),
            created_by=created_by,
            batch=batch,
            expires_at=expires_at,
        )
        session.add(key)
        keys.append(key)
    await session.flush()
    return keys


async def get_access_key(session: AsyncSession, code: str) -> AccessKey | None:
    return await session.scalar(
        select(AccessKey).where(AccessKey.code == normalize_code(code))
    )


async def redeem_access_key(
    session: AsyncSession, code: str, user: User
) -> tuple[bool, str, datetime | None]:
    """Redeem a key for ``user``. Returns (ok, reason, new access_until)."""
    key = await get_access_key(session, code)
    if key is None:
        return False, "not_found", None
    if key.revoked:
        return False, "revoked", None
    if key.redeemed_by is not None:
        return False, "used", None

    now = datetime.now(UTC)
    deadline = ensure_aware(key.expires_at)
    if deadline is not None and deadline < now:
        return False, "expired", None

    base = ensure_aware(user.access_until) or now
    if base < now:
        base = now
    user.access_until = base + timedelta(minutes=key.duration_minutes)
    key.redeemed_by = user.id
    key.redeemed_at = now
    await session.flush()
    return True, "ok", user.access_until


async def list_access_keys(
    session: AsyncSession, *, limit: int = 20, unredeemed_only: bool = False
) -> list[AccessKey]:
    stmt = select(AccessKey).order_by(AccessKey.id.desc()).limit(limit)
    if unredeemed_only:
        stmt = stmt.where(
            AccessKey.redeemed_by.is_(None), AccessKey.revoked.is_(False)
        )
    return list(await session.scalars(stmt))


async def revoke_access_key(session: AsyncSession, code: str) -> bool:
    key = await get_access_key(session, code)
    if key is None:
        return False
    key.revoked = True
    await session.flush()
    return True


async def set_user_admin(
    session: AsyncSession, telegram_id: int, is_admin: bool
) -> User | None:
    user = await get_user_by_telegram_id(session, telegram_id)
    if user is None:
        return None
    user.is_admin = is_admin
    await session.flush()
    return user


async def grant_user_access(
    session: AsyncSession, user: User, *, minutes: int
) -> datetime:
    now = datetime.now(UTC)
    base = ensure_aware(user.access_until) or now
    if base < now:
        base = now
    user.access_until = base + timedelta(minutes=max(1, minutes))
    await session.flush()
    return user.access_until


async def clear_user_access(session: AsyncSession, user: User) -> None:
    user.access_until = None
    await session.flush()


async def count_rows(session: AsyncSession, model: Any) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def count_active_access(session: AsyncSession) -> int:
    now = datetime.now(UTC)
    return int(
        await session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.access_until.is_not(None), User.access_until > now)
        )
        or 0
    )


async def count_admins(session: AsyncSession) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(User).where(User.is_admin.is_(True))
        )
        or 0
    )


async def list_admins(session: AsyncSession) -> list[User]:
    result = await session.scalars(select(User).where(User.is_admin.is_(True)))
    return list(result)


# --------------------------------------------------------------------------- #
# Global bot settings (key/value)
# --------------------------------------------------------------------------- #
async def get_bot_setting(
    session: AsyncSession, key: str, default: str | None = None
) -> str | None:
    setting = await session.get(BotSetting, key)
    if setting is None:
        return default
    return setting.value


async def set_bot_setting(session: AsyncSession, key: str, value: str) -> None:
    setting = await session.get(BotSetting, key)
    if setting is None:
        session.add(BotSetting(key=key, value=value))
    else:
        setting.value = value
    await session.flush()


async def set_user_blocked(
    session: AsyncSession, telegram_id: int, blocked: bool
) -> User | None:
    user = await get_user_by_telegram_id(session, telegram_id)
    if user is None:
        return None
    user.is_blocked = blocked
    await session.flush()
    return user


async def list_users(
    session: AsyncSession, *, limit: int = 20, offset: int = 0
) -> list[User]:
    result = await session.scalars(
        select(User).order_by(User.id.desc()).limit(limit).offset(offset)
    )
    return list(result)
