"""Filesystem safety: filename sanitization and path-traversal protection.

Every path derived from untrusted input (file names, user-provided strings)
must be constructed with :func:`safe_join` and validated with
:func:`sanitize_filename`.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path, PurePosixPath, PureWindowsPath

MAX_FILENAME_LENGTH = 200

# Windows-reserved device names (case-insensitive, also reserved with an extension).
_RESERVED_NAMES = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}

_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_WHITESPACE = re.compile(r"\s+")


class PathSecurityError(ValueError):
    """Raised when a path would escape its sandbox or is otherwise unsafe."""


def sanitize_filename(name: str, *, fallback: str = "file") -> str:
    """Return a safe, single-component filename.

    Strips directory components, normalizes Unicode, removes control and
    reserved characters, guards against Windows device names, and truncates
    while preserving the extension.
    """
    if not name:
        return fallback

    # Drop any directory component from either platform's separators.
    name = PureWindowsPath(PurePosixPath(name.replace("\\", "/")).name).name
    name = unicodedata.normalize("NFKC", name)

    # Keep letters, digits, dots, dashes, underscores, spaces, parentheses.
    cleaned = _UNSAFE_CHARS.sub("", name)
    cleaned = _WHITESPACE.sub(" ", cleaned).strip().strip(".")
    # Remove spaces immediately preceding a dot ("file .txt" -> "file.txt").
    cleaned = re.sub(r"\s+\.", ".", cleaned).strip().strip(".")

    if not cleaned or cleaned in {".", ".."}:
        return fallback

    stem = cleaned.rsplit(".", 1)[0].lower() if "." in cleaned else cleaned.lower()
    if stem in _RESERVED_NAMES:
        cleaned = f"_{cleaned}"

    if len(cleaned) > MAX_FILENAME_LENGTH:
        if "." in cleaned:
            base, ext = cleaned.rsplit(".", 1)
            ext = f".{ext[:16]}"
            cleaned = base[: MAX_FILENAME_LENGTH - len(ext)] + ext
        else:
            cleaned = cleaned[:MAX_FILENAME_LENGTH]

    return cleaned or fallback


def safe_join(base: Path, *parts: str | Path) -> Path:
    """Join ``parts`` onto ``base`` and guarantee the result stays inside ``base``.

    Raises :class:`PathSecurityError` on absolute components, ``..`` traversal,
    or any result that resolves outside ``base``.
    """
    base_resolved = base.resolve()

    for part in parts:
        part_str = str(part)
        if PurePosixPath(part_str).is_absolute() or PureWindowsPath(part_str).is_absolute():
            raise PathSecurityError(f"Absolute path component rejected: {part_str!r}")
        if part_str in {"", ".", ".."} or ".." in PurePosixPath(part_str).parts:
            raise PathSecurityError(f"Traversal component rejected: {part_str!r}")

    candidate = (base_resolved / Path(*[str(p) for p in parts])).resolve()
    if candidate != base_resolved and base_resolved not in candidate.parents:
        raise PathSecurityError("Resolved path escapes the sandbox")
    return candidate


def user_workspace(storage_root: Path, telegram_id: int, *subdirs: str, create: bool = True) -> Path:
    """Return (and optionally create) an isolated workspace for a user.

    The directory is keyed by the numeric Telegram id, so it contains no
    user-controlled characters.
    """
    if not isinstance(telegram_id, int):
        raise PathSecurityError("telegram_id must be an integer")

    workspace = safe_join(storage_root, "users", str(telegram_id))
    if subdirs:
        workspace = safe_join(workspace, *subdirs)
    if create:
        workspace.mkdir(parents=True, exist_ok=True)
    return workspace
