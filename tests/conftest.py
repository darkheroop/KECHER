"""Shared pytest fixtures.

Every test runs against an isolated in-memory SQLite database and a temporary
storage root so nothing touches the real filesystem or a real database.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from bot.config import get_settings
from bot.db.engine import dispose_engine, init_db


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("BOT_TOKEN", "123456:TESTTOKEN_ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("MAX_FILE_SIZE_MB", "100")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def settings():
    s = get_settings()
    yield s
    await dispose_engine()


@pytest_asyncio.fixture
async def db(settings):
    await init_db(settings)
    yield settings
    await dispose_engine()
