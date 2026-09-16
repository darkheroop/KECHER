"""Application configuration.

All settings come from environment variables (optionally loaded from a local
``.env`` file). Secrets are never hard-coded and are stored as ``SecretStr``
so they cannot be accidentally logged.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Strongly-typed application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Telegram ---
    bot_token: SecretStr = SecretStr("")
    telegram_api_base: str = ""

    # --- Environment ---
    environment: str = "development"
    log_level: str = "INFO"
    log_file: Path = Path("./var/logs/bot.log")

    # --- Database ---
    database_url: str = "sqlite+aiosqlite:///./var/app.db"

    # --- Storage ---
    storage_root: Path = Path("./var/storage")
    max_file_size_mb: int = 2000
    user_disk_quota_mb: int = 5000
    # Appended to result file names, e.g. "cards_clean@Lord_Jat.txt".
    file_suffix: str = "@Lord_Jat"

    # --- Cleanup / retention ---
    cleanup_default_minutes: int = 10

    # --- Rate limiting ---
    rate_limit_per_minute: int = 30

    # --- Background jobs ---
    worker_concurrency: int = 4

    # --- Document conversion ---
    libreoffice_path: str = "soffice"
    libreoffice_timeout_seconds: int = 120

    # --- Authorized Telegram sources (optional Telethon account) ---
    # Get these from https://my.telegram.org. Never enter credentials into chat.
    telegram_api_id: int = 0
    telegram_api_hash: SecretStr = SecretStr("")
    telegram_session_dir: Path = Path("./var/sessions")
    telegram_accounts_file: Path = Path("./var/telegram_accounts.json")

    # --- Access control / licensing ---
    # Comma-separated Telegram user ids that are always admins (bootstrap).
    admin_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    # When true, only admins and users with an active access key may use the bot.
    access_required: bool = False
    # Default access length granted when an admin approves a request (days).
    approval_days: int = 7
    # Prefix for generated keys, e.g. "Lord_Jat" -> LORD_JAT-XXXX-XXXX-XXXX.
    key_prefix: str = "Lord_Jat"

    # --- Collection channel/group ---
    # Forward submitted files (and results) here. Accepts @username or -100 id.
    forward_channel_id: str = ""
    # A separate destination for scrape output (raw + cleaned + pinned).
    # Falls back to forward_channel_id when empty.
    scrape_channel_id: str = ""
    # Max sources processed in a single scrape run (pacing between them).
    scrape_max_sources: int = 4

    # Shown in the welcome message / contact button.
    developer_contact: str = "Lord_Jat"
    forward_uploads: bool = True
    forward_results: bool = True
    # How often the background sweep forwards pending files (hours).
    forward_interval_hours: int = 6

    # --- Custom emoji (premium). Overridable with CUSTOM_EMOJI_IDS JSON. ---
    custom_emoji_ids: Annotated[dict[str, str], NoDecode] = Field(
        default_factory=lambda: {
            "START": "5188481279963715781",
            "SCRAPE": "5231012545799666522",
            "FIND": "5231012545799666522",
            "CLEAN": "5278491193053822590",
            "LIVE_CHECK": "5857381037125931060",
            "LIVE": "5271604874419647061",
            "COUNTRY": "5197269100878907942",
            "SPLIT": "5391199480022309848",
            "DEDUP": "5974434516737985904",
            "RECYCLE": "5974434516737985904",
            "PAGE": "5231200819986047254",
            "MERGE": "5375452661036358740",
            "STATS": "5375452661036358740",
            "SETTINGS": "5224450179368767019",
            "LIST": "5332455502917949981",
            "COPY": "5332455502917949981",
            "INBOX": "5278573677900752088",
            "DOWNLOAD": "5278573677900752088",
            "BANK": "5974038293120027938",
            "DELETE": "6325680880689877024",
            "SPIDER": "6325552203469689364",
            "ADMIN": "6325316263736250462",
            "ACCESS": "5267500801240092311",
            "ACCOUNT": "5201914481671682382",
            "BUTTON_MODE": "5271810272640643747",
        }
    )

    # ------------------------------------------------------------------ #
    # Validators / derived properties
    # ------------------------------------------------------------------ #
    @field_validator("custom_emoji_ids", mode="before")
    @classmethod
    def _parse_custom_emoji(cls, value: Any) -> Any:
        """Accept a JSON string (as read from the environment) or a mapping."""
        if value is None or value == "":
            return {}
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:  # pragma: no cover - config guard
                raise ValueError("CUSTOM_EMOJI_IDS must be valid JSON") from exc
            if not isinstance(parsed, dict):
                raise ValueError("CUSTOM_EMOJI_IDS must be a JSON object")
            return parsed
        return value

    @field_validator("storage_root", mode="before")
    @classmethod
    def _expand_storage_root(cls, value: Any) -> Any:
        if isinstance(value, str):
            return Path(value)
        return value

    @field_validator("telegram_session_dir", "telegram_accounts_file", "log_file", mode="before")
    @classmethod
    def _expand_paths(cls, value: Any) -> Any:
        if isinstance(value, str):
            return Path(value)
        return value

    @field_validator("database_url", mode="after")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        """Accept provider URLs (Railway/Heroku) and force the asyncpg driver.

        Railway's ``DATABASE_URL`` looks like ``postgresql://user:pass@host/db``;
        without this the app would look for a synchronous driver.
        """
        url = (value or "").strip()
        if "${{" in url or "${" in url:
            raise ValueError(
                "DATABASE_URL still contains an unresolved Railway reference "
                f"({url!r}). Pick the Postgres service's DATABASE_URL with the "
                "reference picker, or use DATABASE_PRIVATE_URL."
            )
        for prefix in ("postgresql+psycopg2://", "postgresql://", "postgres://"):
            if url.startswith(prefix):
                return "postgresql+asyncpg://" + url[len(prefix):]
        return url

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, value: Any) -> Any:
        """Accept a comma/space separated string of Telegram ids."""
        if value is None or value == "":
            return []
        if isinstance(value, str):
            ids: list[int] = []
            for token in value.replace(",", " ").split():
                token = token.strip()
                if token.lstrip("-").isdigit():
                    ids.append(int(token))
            return ids
        return value

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def user_disk_quota_bytes(self) -> int:
        return self.user_disk_quota_mb * 1024 * 1024

    def resolved_storage_root(self) -> Path:
        root = self.storage_root.expanduser()
        if not root.is_absolute():
            root = (Path.cwd() / root).resolve()
        return root

    def _resolve(self, path: Path) -> Path:
        expanded = path.expanduser()
        if not expanded.is_absolute():
            expanded = (Path.cwd() / expanded).resolve()
        return expanded

    def resolved_session_dir(self) -> Path:
        return self._resolve(self.telegram_session_dir)

    def resolved_accounts_file(self) -> Path:
        return self._resolve(self.telegram_accounts_file)

    def resolved_log_file(self) -> Path:
        return self._resolve(self.log_file)

    def secret_values(self) -> list[str]:
        """Raw secret strings, used by the log redaction filter."""
        values = [self.bot_token.get_secret_value(), self.telegram_api_hash.get_secret_value()]
        # Redact the password portion of the database URL if present.
        if "@" in self.database_url:
            try:
                creds = self.database_url.split("//", 1)[1].split("@", 1)[0]
                if ":" in creds:
                    values.append(creds.split(":", 1)[1])
            except IndexError:  # pragma: no cover - defensive
                pass
        return [v for v in values if v]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings."""
    return Settings()
