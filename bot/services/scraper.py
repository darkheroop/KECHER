"""Authorized-source scraping: filtering, export and account metadata.

This module contains no Telegram networking. It operates on ``MessageDatum``
records produced by an account that is already legitimately authenticated, and
only ever reads sources the account can access. The Telethon adapter lives in
:mod:`bot.services.telegram_client`.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ProgressFn = Callable[[int], None]

EXPORT_FORMATS = {"txt", "csv", "json"}
MEDIA_TYPES = {"text", "photo", "video", "document", "audio", "voice", "media"}


@dataclass(slots=True)
class MessageDatum:
    """Normalized, non-secret view of a single Telegram message."""

    id: int
    date: datetime
    text: str = ""
    sender_id: int | None = None
    media_type: str | None = None
    file_name: str | None = None
    file_size: int | None = None

    @property
    def has_media(self) -> bool:
        return self.media_type is not None


@dataclass(slots=True)
class ScrapeOptions:
    limit: int = 100
    date_from: datetime | None = None
    date_to: datetime | None = None
    keyword: str | None = None
    keywords: list[str] | None = None  # any-of, case-insensitive
    types: set[str] | None = None  # e.g. {"text"} or {"photo", "document"}
    include_media: bool = False
    text_only: bool = True  # plain-text output (no [date] prefix) for cleaning

    def all_keywords(self) -> list[str]:
        found = [k.strip() for k in (self.keywords or []) if k and k.strip()]
        if self.keyword and self.keyword.strip():
            found.append(self.keyword.strip())
        return found


@dataclass(slots=True)
class ScrapeResult:
    scanned: int = 0
    exported: int = 0
    path: Path | None = None


def message_matches(datum: MessageDatum, options: ScrapeOptions) -> bool:
    """Apply the date / type / keyword filters to one message."""
    if options.date_from is not None and datum.date < options.date_from:
        return False
    if options.date_to is not None and datum.date > options.date_to:
        return False

    words = options.all_keywords()
    if words:
        haystack = (datum.text or "").casefold()
        if not any(word.casefold() in haystack for word in words):
            return False

    if options.types:
        kind = datum.media_type or "text"
        if kind not in options.types and not (
            datum.has_media and "media" in options.types
        ):
            return False
    elif datum.has_media and not options.include_media:
        return False
    return True


def _datum_to_dict(datum: MessageDatum) -> dict:
    return {
        "id": datum.id,
        "date": datum.date.isoformat(),
        "sender_id": datum.sender_id,
        "text": datum.text,
        "media_type": datum.media_type,
        "file_name": datum.file_name,
        "file_size": datum.file_size,
    }


def _text_line(datum: MessageDatum, *, text_only: bool = False) -> str:
    if text_only:
        return (datum.text or "").strip()
    text = (datum.text or "").replace("\r", " ").replace("\n", " ").strip()
    prefix = f"[{datum.date.isoformat()}]"
    if datum.sender_id is not None:
        prefix += f" {datum.sender_id}:"
    media = f" [{datum.media_type}: {datum.file_name or ''}]" if datum.has_media else ""
    return f"{prefix}{media} {text}".rstrip()


def scrape_to_file(
    messages: Iterable[MessageDatum],
    out: str | Path,
    *,
    options: ScrapeOptions,
    fmt: str = "txt",
    on_progress: ProgressFn | None = None,
) -> ScrapeResult:
    """Filter ``messages`` and write them to ``out`` in TXT, CSV or JSON."""
    if fmt not in EXPORT_FORMATS:
        raise ValueError(f"Unsupported export format: {fmt}")

    destination = Path(out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = ScrapeResult(path=destination)
    scanned = 0
    rows: list[dict] = []

    handle = None
    writer = None
    if fmt == "csv":
        handle = open(destination, "w", encoding="utf-8", newline="")
        writer = csv.DictWriter(
            handle,
            fieldnames=["id", "date", "sender_id", "text", "media_type", "file_name", "file_size"],
        )
        writer.writeheader()
    elif fmt == "txt":
        handle = open(destination, "w", encoding="utf-8", newline="\n")

    try:
        for datum in messages:
            scanned += 1
            if message_matches(datum, options):
                if fmt == "txt":
                    assert handle is not None
                    handle.write(_text_line(datum, text_only=options.text_only) + "\n")
                elif fmt == "csv":
                    assert writer is not None
                    writer.writerow(_datum_to_dict(datum))
                else:
                    rows.append(_datum_to_dict(datum))
                result.exported += 1
            if on_progress:
                on_progress(scanned)
    finally:
        if handle is not None:
            handle.close()

    if fmt == "json":
        destination.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    result.scanned = scanned
    return result


# --------------------------------------------------------------------------- #
# Account registry (metadata only -- never credentials or session contents)
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class AccountInfo:
    label: str
    session: str
    enabled: bool = True
    last_used: str | None = None
    owner: int | None = None  # Telegram user id that owns this session


class AccountRegistry:
    """Reads/writes a JSON list of account *labels*; no secrets are stored."""

    def __init__(self, path: str | Path, session_dir: str | Path) -> None:
        self.path = Path(path)
        self.session_dir = Path(session_dir)

    def load(self) -> list[AccountInfo]:
        if not self.path.is_file():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        accounts = []
        for entry in raw.get("accounts", []):
            if not isinstance(entry, dict) or not entry.get("label"):
                continue
            accounts.append(
                AccountInfo(
                    label=str(entry["label"]),
                    session=str(entry.get("session") or entry["label"]),
                    enabled=bool(entry.get("enabled", True)),
                    last_used=entry.get("last_used"),
                    owner=int(entry["owner"]) if entry.get("owner") is not None else None,
                )
            )
        return accounts

    def accounts(self) -> list[AccountInfo]:
        return self.load()

    def accounts_for(self, owner: int) -> list[AccountInfo]:
        return [account for account in self.load() if account.owner == owner]

    def get(self, label: str) -> AccountInfo | None:
        for account in self.load():
            if account.label == label:
                return account
        return None

    def session_path(self, account: AccountInfo) -> Path:
        name = f"{account.owner}_{account.session}" if account.owner else account.session
        return self.session_dir / f"{name}.session"

    def status(self, account: AccountInfo) -> str:
        if not account.enabled:
            return "Disconnected"
        return "Connected" if self.session_path(account).is_file() else "Disconnected"

    def upsert(
        self,
        label: str,
        *,
        session: str | None = None,
        enabled: bool = True,
        owner: int | None = None,
    ) -> AccountInfo:
        """Add or update an account entry (label/session only; no secrets)."""
        accounts = self.load()
        target: AccountInfo | None = None
        for account in accounts:
            if account.label == label:
                account.session = session or account.session
                account.enabled = enabled
                if owner is not None:
                    account.owner = owner
                target = account
                break
        if target is None:
            target = AccountInfo(
                label=label, session=session or label, enabled=enabled, owner=owner
            )
            accounts.append(target)
        self._save(accounts)
        return target

    def delete(self, label: str) -> None:
        """Remove an account entry (and its session file, if present)."""
        accounts = self.load()
        keep = []
        for account in accounts:
            if account.label == label:
                session = self.session_path(account)
                try:
                    session.unlink(missing_ok=True)
                except OSError:  # pragma: no cover
                    pass
                continue
            keep.append(account)
        self._save(keep)

    def _save(self, accounts: list[AccountInfo]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "accounts": [
                {
                    "label": account.label,
                    "session": account.session,
                    "enabled": account.enabled,
                    "last_used": account.last_used,
                    "owner": account.owner,
                }
                for account in accounts
            ]
        }
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self.path)


def is_scraper_available() -> bool:
    """True when the optional Telethon dependency is installed."""
    try:
        import telethon  # noqa: F401
    except ImportError:
        return False
    return True
