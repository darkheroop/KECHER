"""Helpers for the join -> scrape -> leave flow."""

from __future__ import annotations

from bot.services.telegram_client import TelethonScraper


def test_invite_hash_parsing() -> None:
    assert TelethonScraper._invite_hash("https://t.me/+abCdEF123") == "abCdEF123"
    assert TelethonScraper._invite_hash("https://t.me/joinchat/abCdEF") == "abCdEF"
    assert TelethonScraper._invite_hash("+abCdEF") == "abCdEF"
    assert TelethonScraper._invite_hash("@channel") is None


def test_username_parsing() -> None:
    assert TelethonScraper._username("@mychannel") == "mychannel"
    assert TelethonScraper._username("https://t.me/mychannel") == "mychannel"
    assert TelethonScraper._username("https://t.me/+secret") is None
