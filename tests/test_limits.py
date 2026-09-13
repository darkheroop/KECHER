import pytest

from bot.security.limits import LimitExceeded, check_file_size, check_quota, human_size


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, "0 B"), (500, "500 B"), (1536, "1.5 KB"), (5 * 1024 * 1024, "5.0 MB")],
)
def test_human_size(value: int, expected: str) -> None:
    assert human_size(value) == expected


def test_check_file_size_ok(settings) -> None:
    check_file_size(1024, settings)


def test_check_file_size_exceeds(settings) -> None:
    with pytest.raises(LimitExceeded):
        check_file_size(settings.max_file_size_bytes + 1, settings)


def test_check_file_size_negative(settings) -> None:
    with pytest.raises(LimitExceeded):
        check_file_size(-1, settings)


def test_check_quota(settings) -> None:
    with pytest.raises(LimitExceeded):
        check_quota(settings.user_disk_quota_bytes, 1, settings)
