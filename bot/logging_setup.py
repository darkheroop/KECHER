"""Logging configuration.

Installs a redaction filter so bot tokens / database passwords can never leak
into log output, and configures a consistent formatter across the app.
"""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler

from bot.config import Settings

REDACTED = "***REDACTED***"

# Patterns that look like secrets regardless of configuration.
_PATTERNS = [
    # Telegram bot token: <digits>:<35+ chars>
    (re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b"), REDACTED),
    # Credentials embedded in URLs: scheme://user:password@host
    (re.compile(r"(?P<scheme>[a-z0-9+]+://[^:/@\s]+:)(?P<pw>[^@/\s]+)(?=@)"), r"\g<scheme>" + REDACTED),
]


class RedactionFilter(logging.Filter):
    """Scrub known secret values and secret-looking patterns from records."""

    def __init__(self, secrets: list[str] | None = None) -> None:
        super().__init__()
        self._secrets = [s for s in (secrets or []) if s]

    def _redact(self, text: str) -> str:
        for secret in self._secrets:
            if secret in text:
                text = text.replace(secret, REDACTED)
        for pattern, replacement in _PATTERNS:
            text = pattern.sub(replacement, text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: self._redact(v) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            else:
                record.args = tuple(
                    self._redact(a) if isinstance(a, str) else a for a in record.args
                )
        return True


def setup_logging(settings: Settings) -> None:
    """Configure root logging with redaction enabled (console + file)."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    redaction = RedactionFilter(settings.secret_values())

    handlers: list[logging.Handler] = []
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.addFilter(redaction)
    handlers.append(console)

    # File log so problems are diagnosable even when the console is closed.
    try:
        log_path = settings.resolved_log_file()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(redaction)
        handlers.append(file_handler)
    except OSError:  # pragma: no cover - filesystem guard
        logging.getLogger(__name__).warning("Could not open log file; console only")

    root = logging.getLogger()
    root.handlers.clear()
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(level)

    logging.getLogger("aiogram").setLevel(max(level, logging.INFO))
    logging.getLogger("sqlalchemy.engine").setLevel(max(level, logging.WARNING))
