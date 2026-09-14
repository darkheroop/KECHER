"""Canonical enums shared across the persistence and domain layers.

Stored as plain strings so the schema stays portable between PostgreSQL and
SQLite (used for tests).
"""

from __future__ import annotations

from enum import StrEnum


class UIMode(StrEnum):
    BUTTONS = "buttons"
    COMMANDS = "commands"
    HYBRID = "hybrid"


class Language(StrEnum):
    ENGLISH = "en"


class JobKind(StrEnum):
    DOC2TXT = "doc2txt"
    EXTRACT = "extract"
    CSV = "csv"
    SPLIT = "split"
    CLEAN = "clean"
    DEDUP = "dedup"
    MERGE = "merge"
    FIND = "find"
    COUNTRY = "country"
    BANK = "bank"
    PICK = "pick"
    PICKBANK = "pickbank"
    SCRAPE = "scrape"
    VALIDATE = "validate"


class JobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AuditAction(StrEnum):
    USER_START = "user_start"
    FILE_RECEIVED = "file_received"
    FILE_DELETED = "file_deleted"
    JOB_CREATED = "job_created"
    JOB_CANCELLED = "job_cancelled"
    SETTINGS_CHANGED = "settings_changed"
    SOURCE_ADDED = "source_added"
    SOURCE_REMOVED = "source_removed"
    VALIDATION_RUN = "validation_run"
