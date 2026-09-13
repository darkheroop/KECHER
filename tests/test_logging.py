import logging

from bot.config import Settings
from bot.logging_setup import REDACTED, RedactionFilter


def test_redacts_known_secret() -> None:
    flt = RedactionFilter(["supersecretvalue"])
    record = logging.LogRecord(
        "t", logging.INFO, __file__, 1, "token=%s", ("supersecretvalue",), None
    )
    flt.filter(record)
    assert record.args == (REDACTED,)


def test_redacts_bot_token_pattern() -> None:
    flt = RedactionFilter([])
    record = logging.LogRecord(
        "t",
        logging.INFO,
        __file__,
        1,
        "using 123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi now",
        (),
        None,
    )
    flt.filter(record)
    assert "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi" not in record.msg
    assert REDACTED in record.msg


def test_redacts_credentials_in_url() -> None:
    flt = RedactionFilter([])
    record = logging.LogRecord(
        "t",
        logging.INFO,
        __file__,
        1,
        "db at postgresql://bot:passw0rd@host/db",
        (),
        None,
    )
    flt.filter(record)
    assert "passw0rd" not in record.msg


def test_secret_values_from_settings() -> None:
    settings = Settings(
        bot_token="123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
        database_url="postgresql+asyncpg://bot:topsecret@host/db",
    )
    values = settings.secret_values()
    assert "topsecret" in values
    assert "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi" in values
