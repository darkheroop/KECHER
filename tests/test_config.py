from pathlib import Path

import pytest

from bot.config import Settings


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("postgresql://u:p@h:5432/db", "postgresql+asyncpg://u:p@h:5432/db"),
        ("postgres://u:p@h:5432/db", "postgresql+asyncpg://u:p@h:5432/db"),
        ("postgresql+psycopg2://u:p@h/db", "postgresql+asyncpg://u:p@h/db"),
        ("sqlite+aiosqlite:///./var/app.db", "sqlite+aiosqlite:///./var/app.db"),
    ],
)
def test_database_url_normalized(raw: str, expected: str) -> None:
    assert Settings(database_url=raw).database_url == expected


def test_custom_emoji_parsed_from_env(monkeypatch) -> None:
    monkeypatch.setenv("CUSTOM_EMOJI_IDS", '{"SUCCESS": "12345"}')
    settings = Settings()
    assert settings.custom_emoji_ids == {"SUCCESS": "12345"}


def test_custom_emoji_invalid_json(monkeypatch) -> None:
    monkeypatch.setenv("CUSTOM_EMOJI_IDS", "not-json")
    try:
        Settings()
    except Exception as exc:  # pydantic-settings SettingsError / ValidationError
        assert "custom_emoji_ids" in str(exc).lower()
    else:  # pragma: no cover
        raise AssertionError("invalid JSON should fail validation")


def test_max_file_size_bytes() -> None:
    settings = Settings(max_file_size_mb=100)
    assert settings.max_file_size_bytes == 100 * 1024 * 1024


def test_secret_values_redacts_db_password() -> None:
    settings = Settings(
        bot_token="123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
        database_url="postgresql+asyncpg://bot:s3cr3t@localhost:5432/db",
    )
    values = settings.secret_values()
    assert "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi" in values
    assert "s3cr3t" in values


def test_resolved_storage_root_is_absolute(tmp_path: Path) -> None:
    settings = Settings(storage_root=str(tmp_path / "x"))
    assert settings.resolved_storage_root().is_absolute()
