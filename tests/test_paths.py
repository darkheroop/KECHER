from pathlib import Path

import pytest

from bot.security.paths import (
    PathSecurityError,
    safe_join,
    sanitize_filename,
    user_workspace,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("..\\..\\windows\\system32\\cmd.exe", "cmd.exe"),
        ("a<b>c.txt", "abc.txt"),
        ("  spaced  out .txt ", "spaced out.txt"),
        ("", "file"),
        ("...", "file"),
        ("CON.txt", "_CON.txt"),
        ("normal_csv.csv", "normal_csv.csv"),
    ],
)
def test_sanitize_filename(raw: str, expected: str) -> None:
    assert sanitize_filename(raw) == expected


def test_sanitize_filename_truncates_preserving_extension() -> None:
    result = sanitize_filename("x" * 500 + ".txt")
    assert result.endswith(".txt")
    assert len(result) <= 200


def test_safe_join_blocks_traversal(tmp_path: Path) -> None:
    base = tmp_path / "sandbox"
    base.mkdir()
    with pytest.raises(PathSecurityError):
        safe_join(base, "..", "outside.txt")
    with pytest.raises(PathSecurityError):
        safe_join(base, "sub/../../outside.txt")


def test_safe_join_blocks_absolute(tmp_path: Path) -> None:
    base = tmp_path / "sandbox"
    base.mkdir()
    with pytest.raises(PathSecurityError):
        safe_join(base, "C:\\Windows\\evil.txt")


def test_safe_join_allows_nested(tmp_path: Path) -> None:
    base = tmp_path / "sandbox"
    base.mkdir()
    assert safe_join(base, "a", "b.txt") == (base / "a" / "b.txt").resolve()


def test_user_workspace_is_isolated(tmp_path: Path) -> None:
    ws = user_workspace(tmp_path, 12345, "inbox")
    assert ws.is_dir()
    assert ws.is_relative_to(tmp_path.resolve())
    assert ws.name == "inbox"


def test_user_workspace_rejects_non_int(tmp_path: Path) -> None:
    with pytest.raises(PathSecurityError):
        user_workspace(tmp_path, "../../evil")  # type: ignore[arg-type]
