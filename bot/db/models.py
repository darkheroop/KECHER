"""SQLAlchemy ORM models.

Store only the minimum information required for operation. File contents are
never stored in the database -- only metadata and sandbox-relative paths.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base for all models."""


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # --- access control ---
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    access_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    settings: Mapped[UserSettings] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    files: Mapped[list[UserFile]] = relationship(back_populates="user", cascade="all, delete-orphan")
    jobs: Mapped[list[Job]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserSettings(TimestampMixin, Base):
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    ui_mode: Mapped[str] = mapped_column(String(16), default="buttons", nullable=False)
    progress_messages: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    cleanup_minutes: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    language: Mapped[str] = mapped_column(String(8), default="en", nullable=False)

    user: Mapped[User] = relationship(back_populates="settings")


class UserFile(TimestampMixin, Base):
    __tablename__ = "files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    telegram_file_id: Mapped[str | None] = mapped_column(String(256))
    original_name: Mapped[str] = mapped_column(String(512), nullable=False)
    safe_name: Mapped[str] = mapped_column(String(512), nullable=False)
    # Path relative to the user's sandbox root -- never an absolute path.
    rel_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime: Mapped[str | None] = mapped_column(String(128))
    sha256: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="files")


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True, nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Telegram location for progress edits (chat id + message id of the job card).
    chat_id: Mapped[int | None] = mapped_column(BigInteger)
    progress_message_id: Mapped[int | None] = mapped_column(BigInteger)
    input_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("files.id", ondelete="SET NULL")
    )
    result_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("files.id", ondelete="SET NULL")
    )
    error: Mapped[str | None] = mapped_column(Text)
    # Structured, non-sensitive job parameters (e.g. delimiter, columns).
    params: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="jobs")


class MergeQueue(TimestampMixin, Base):
    __tablename__ = "merge_queues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    items: Mapped[list[MergeQueueItem]] = relationship(
        back_populates="queue", cascade="all, delete-orphan", order_by="MergeQueueItem.position"
    )


class MergeQueueItem(TimestampMixin, Base):
    __tablename__ = "merge_queue_items"
    __table_args__ = (UniqueConstraint("queue_id", "position", name="uq_queue_position"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    queue_id: Mapped[int] = mapped_column(
        ForeignKey("merge_queues.id", ondelete="CASCADE"), index=True, nullable=False
    )
    file_id: Mapped[int] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    queue: Mapped[MergeQueue] = relationship(back_populates="items")


class AuthorizedSource(TimestampMixin, Base):
    """A Telegram source the authenticated account is legitimately allowed to read."""

    __tablename__ = "authorized_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), default="group", nullable=False)
    tg_peer_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    title: Mapped[str | None] = mapped_column(String(256))


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )


class BotSetting(Base):
    """Simple key/value store for global bot flags (e.g. forwarding)."""

    __tablename__ = "bot_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="", nullable=False)


class AccessKey(Base):
    """A redeemable access key granting a fixed duration of bot access."""

    __tablename__ = "access_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    batch: Mapped[str | None] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    # Optional deadline by which the key must be redeemed (None = no deadline).
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    redeemed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
