import pytest

from bot.services.luhn import extract_pan, find_pan_candidates, luhn_valid


@pytest.mark.parametrize(
    "number",
    ["4242424242424242", "4111111111111111", "5555555555554444", "378282246310005"],
)
def test_luhn_valid_numbers(number: str) -> None:
    assert luhn_valid(number) is True


@pytest.mark.parametrize(
    "number",
    ["4242424242424241", "1234567812345678", "4111111111111112"],
)
def test_luhn_invalid_numbers(number: str) -> None:
    assert luhn_valid(number) is False


def test_luhn_too_short() -> None:
    assert luhn_valid("4") is False


def test_extract_pan_strips_separators() -> None:
    assert extract_pan("4111 1111 1111 1111") == "4111111111111111"
    assert extract_pan("4111-1111-1111-1111") == "4111111111111111"


def test_extract_pan_rejects_implausible() -> None:
    assert extract_pan("12345") == ""
    assert extract_pan("") == ""


def test_find_pan_candidates_separators() -> None:
    text = "id 4111 1111 1111 1111 and 4242-4242-4242-4241"
    assert find_pan_candidates(text) == ["4111111111111111", "4242424242424241"]


def test_find_pan_candidates_none() -> None:
    assert find_pan_candidates("no numbers here") == []
    assert find_pan_candidates("short 1234 only") == []
