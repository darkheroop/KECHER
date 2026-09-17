from pathlib import Path

import pytest

from bot.config import Settings
from bot.security.limits import LimitExceeded
from bot.security.paths import PathSecurityError
from bot.services.file_manager import FileManager


def test_allocate_sanitizes_and_creates_dirs(settings) -> None:
    fm = FileManager(settings)
    allocated = fm.allocate(123, "../evil name.csv")
    assert allocated.path.name == "evil name.csv"
    assert allocated.rel_path == "inbox/evil name.csv"
    assert allocated.path.parent.is_dir()
    assert allocated.path.is_relative_to(fm.user_root(123))


def test_allocate_is_unique(settings) -> None:
    fm = FileManager(settings)
    first = fm.allocate(1, "data.txt")
    first.path.write_text("a")
    second = fm.allocate(1, "data.txt")
    assert second.safe_name == "data_2.txt"
    assert second.path != first.path


def test_finalize_hashes_and_sizes(settings) -> None:
    fm = FileManager(settings)
    allocated = fm.allocate(1, "a.txt")
    allocated.path.write_bytes(b"hello world")
    stored = fm.finalize(allocated)
    assert stored.size_bytes == 11
    assert stored.sha256 == FileManager.sha256_of(allocated.path)
    assert len(stored.sha256) == 64


def test_usage_counts_all_files(settings) -> None:
    fm = FileManager(settings)
    a = fm.allocate(9, "a.bin")
    a.path.write_bytes(b"x" * 10)
    b = fm.allocate(9, "b.bin")
    b.path.write_bytes(b"y" * 5)
    assert fm.usage_bytes(9) == 15
    assert fm.usage_bytes(10) == 0


def test_check_capacity_enforces_quota() -> None:
    fm = FileManager(Settings(user_disk_quota_mb=0))
    with pytest.raises(LimitExceeded):
        fm.check_capacity(1, 1)


def test_check_capacity_enforces_max_size() -> None:
    fm = FileManager(Settings(max_file_size_mb=1))
    with pytest.raises(LimitExceeded):
        fm.check_capacity(1, 2 * 1024 * 1024)


def test_resolve_blocks_traversal(settings) -> None:
    fm = FileManager(settings)
    with pytest.raises(PathSecurityError):
        fm.resolve(1, "../escape.txt")


def test_delete_removes_file(settings) -> None:
    fm = FileManager(settings)
    allocated = fm.allocate(5, "a.txt")
    allocated.path.write_text("data")
    assert fm.delete(5, allocated.rel_path) is True
    assert not allocated.path.exists()
    assert fm.delete(5, allocated.rel_path) is False


def test_delete_user_tree(settings) -> None:
    fm = FileManager(settings)
    root = fm.user_root(7)
    (root / "inbox").mkdir(parents=True, exist_ok=True)
    (root / "inbox" / "a.txt").write_text("a")
    fm.delete_user_tree(7)
    assert not root.exists()
