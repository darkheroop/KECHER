"""Per-user file storage.

Files live under ``<storage_root>/users/<telegram_id>/<subdir>/<name>``. The
database stores only a sandbox-relative path; absolute paths are always rebuilt
through :func:`bot.security.paths.safe_join`, so a hostile ``rel_path`` cannot
escape the sandbox.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from bot.config import Settings
from bot.security.limits import check_file_size, check_quota
from bot.security.paths import safe_join, sanitize_filename, user_workspace

_CHUNK = 1024 * 1024  # 1 MiB streaming chunk


@dataclass(frozen=True, slots=True)
class AllocatedPath:
    """A reserved destination for an upload, before data is written."""

    path: Path
    rel_path: str  # POSIX-style, relative to the user's sandbox root
    safe_name: str


@dataclass(frozen=True, slots=True)
class StoredFile:
    path: Path
    rel_path: str
    safe_name: str
    size_bytes: int
    sha256: str


class FileManager:
    """Filesystem operations scoped to per-user sandboxes."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.root = settings.resolved_storage_root()

    # -- paths -------------------------------------------------------------- #
    def user_root(self, telegram_id: int, *, create: bool = True) -> Path:
        return user_workspace(self.root, telegram_id, create=create)

    @staticmethod
    def _split_rel(rel_path: str) -> list[str]:
        normalized = rel_path.replace("\\", "/").strip("/")
        parts = [p for p in normalized.split("/") if p]
        if not parts:
            raise ValueError("Empty relative path")
        return parts

    def resolve(self, telegram_id: int, rel_path: str, *, create_parent: bool = True) -> Path:
        """Resolve a sandbox-relative path, refusing traversal."""
        root = self.user_root(telegram_id, create=create_parent)
        parts = self._split_rel(rel_path)
        target = safe_join(root, *parts)
        if create_parent:
            target.parent.mkdir(parents=True, exist_ok=True)
        return target

    # -- capacity ----------------------------------------------------------- #
    def usage_bytes(self, telegram_id: int) -> int:
        root = self.user_root(telegram_id, create=False)
        if not root.exists():
            return 0
        total = 0
        for entry in root.rglob("*"):
            if entry.is_file():
                try:
                    total += entry.stat().st_size
                except OSError:  # pragma: no cover - race with deletion
                    pass
        return total

    def check_capacity(self, telegram_id: int, incoming_bytes: int) -> None:
        check_file_size(incoming_bytes, self._settings)
        check_quota(self.usage_bytes(telegram_id), incoming_bytes, self._settings)

    # -- allocation --------------------------------------------------------- #
    def allocate(
        self, telegram_id: int, original_name: str, *, subdir: str = "inbox"
    ) -> AllocatedPath:
        """Reserve a unique destination path for an upload."""
        safe_name = sanitize_filename(original_name)
        root = self.user_root(telegram_id, create=True)
        directory = safe_join(root, subdir)
        directory.mkdir(parents=True, exist_ok=True)

        candidate = safe_name
        stem, dot, ext = safe_name.rpartition(".")
        if not dot:
            stem, ext = safe_name, ""
        counter = 2
        while safe_join(directory, candidate).exists():
            candidate = f"{stem}_{counter}{'.' + ext if dot else ''}"
            counter += 1

        path = safe_join(directory, candidate)
        rel_path = f"{subdir}/{candidate}"
        return AllocatedPath(path=path, rel_path=rel_path, safe_name=candidate)

    # -- finalize / hash ---------------------------------------------------- #
    @staticmethod
    def sha256_of(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(_CHUNK), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def finalize(self, allocated: AllocatedPath) -> StoredFile:
        """Stat + hash a written file, returning its immutable metadata."""
        if not allocated.path.is_file():
            raise FileNotFoundError(allocated.path)
        size = allocated.path.stat().st_size
        return StoredFile(
            path=allocated.path,
            rel_path=allocated.rel_path,
            safe_name=allocated.safe_name,
            size_bytes=size,
            sha256=self.sha256_of(allocated.path),
        )

    def finalize_path(self, telegram_id: int, path: Path) -> StoredFile:
        """Wrap an existing file inside the user's sandbox as a StoredFile."""
        if not path.is_file():
            raise FileNotFoundError(path)
        root = self.user_root(telegram_id, create=False)
        rel_path = path.resolve().relative_to(root.resolve()).as_posix()
        return StoredFile(
            path=path,
            rel_path=rel_path,
            safe_name=path.name,
            size_bytes=path.stat().st_size,
            sha256=self.sha256_of(path),
        )

    # -- deletion ----------------------------------------------------------- #
    def delete(self, telegram_id: int, rel_path: str) -> bool:
        """Delete a sandbox-relative file. Returns True if something was removed."""
        try:
            target = self.resolve(telegram_id, rel_path, create_parent=False)
        except (ValueError, OSError):
            return False
        try:
            if target.is_file():
                target.unlink()
                return True
        except OSError:  # pragma: no cover - best effort
            return False
        return False

    def delete_user_tree(self, telegram_id: int) -> None:
        """Remove an entire user sandbox (used on account deletion)."""
        root = self.user_root(telegram_id, create=False)
        if not root.exists():
            return
        for entry in sorted(root.rglob("*"), reverse=True):
            try:
                entry.unlink() if entry.is_file() else entry.rmdir()
            except OSError:  # pragma: no cover - best effort
                pass
        try:
            root.rmdir()
        except OSError:  # pragma: no cover
            pass
