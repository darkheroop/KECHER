"""Startup schema self-heal: tables must exist even if Alembic never ran."""

from __future__ import annotations

from bot.db.models import Base
from bot.main import _db_target, _missing_tables, ensure_schema


def test_db_target_hides_credentials() -> None:
    shown = _db_target("postgresql+asyncpg://user:secret@db.railway:5432/railway")
    assert "secret" not in shown
    assert "railway" in shown


async def test_missing_tables_lists_everything_on_an_empty_db(settings) -> None:
    missing = await _missing_tables(settings)
    assert "users" in missing
    assert set(missing) == set(Base.metadata.tables)


async def test_ensure_schema_creates_tables(settings) -> None:
    assert await _missing_tables(settings)
    await ensure_schema(settings)
    assert await _missing_tables(settings) == []
