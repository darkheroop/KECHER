import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from bot.services.scraper import (
    AccountRegistry,
    MessageDatum,
    ScrapeOptions,
    ScrapeResult,
    is_scraper_available,
    message_matches,
    scrape_to_file,
)
from bot.services.telegram_client import TelethonScraper, to_datum

DATE = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


def _text(text: str = "Hello World") -> MessageDatum:
    return MessageDatum(id=1, date=DATE, text=text, media_type=None)


def _media() -> MessageDatum:
    return MessageDatum(id=2, date=DATE, text="", media_type="document", file_name="a.pdf")


def test_date_filters() -> None:
    assert message_matches(_text(), ScrapeOptions())
    assert not message_matches(
        _text(), ScrapeOptions(date_from=datetime(2026, 2, 1, tzinfo=UTC))
    )
    assert message_matches(
        _text(),
        ScrapeOptions(
            date_from=datetime(2026, 1, 1, tzinfo=UTC),
            date_to=datetime(2026, 1, 31, tzinfo=UTC),
        ),
    )


def test_keyword_filter() -> None:
    assert message_matches(_text(), ScrapeOptions(keyword="hello"))
    assert not message_matches(_text(), ScrapeOptions(keyword="zzz"))


def test_type_and_media_filters() -> None:
    assert message_matches(_text(), ScrapeOptions(types={"text"}))
    assert not message_matches(_text(), ScrapeOptions(types={"photo"}))
    assert not message_matches(_media(), ScrapeOptions())
    assert message_matches(_media(), ScrapeOptions(include_media=True))
    assert message_matches(_media(), ScrapeOptions(types={"document"}))
    assert message_matches(_media(), ScrapeOptions(types={"media"}))


def test_export_txt(tmp_path: Path) -> None:
    out = tmp_path / "out.txt"
    result = scrape_to_file([_text(), _media()], out, options=ScrapeOptions(), fmt="txt")
    assert result.scanned == 2
    assert result.exported == 1
    assert "Hello World" in out.read_text(encoding="utf-8")


def test_export_csv(tmp_path: Path) -> None:
    out = tmp_path / "out.csv"
    scrape_to_file([_text()], out, options=ScrapeOptions(), fmt="csv")
    with out.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["text"] == "Hello World"


def test_export_json(tmp_path: Path) -> None:
    out = tmp_path / "out.json"
    scrape_to_file([_text(), _media()], out, options=ScrapeOptions(include_media=True), fmt="json")
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert len(payload) == 2
    assert payload[0]["text"] == "Hello World"


def test_export_unknown_format(tmp_path: Path) -> None:
    try:
        scrape_to_file([], tmp_path / "x", options=ScrapeOptions(), fmt="pdf")
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("unsupported format should raise")


def test_account_registry(tmp_path: Path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json", tmp_path / "sessions")
    assert registry.accounts() == []

    account = registry.upsert("main")
    assert account.label == "main"
    assert registry.status(account) == "Disconnected"

    session_file = registry.session_path(account)
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text("dummy")
    assert registry.status(registry.get("main")) == "Connected"

    reloaded = AccountRegistry(tmp_path / "accounts.json", tmp_path / "sessions")
    assert [a.label for a in reloaded.accounts()] == ["main"]


def test_to_datum_mapping() -> None:
    class FakeFile:
        name = "doc.pdf"
        size = 1234

    class FakeMessage:
        id = 7
        date = DATE
        raw_text = "hi"
        sender_id = 99
        photo = None
        video_note = None
        voice = None
        audio = None
        video = None
        document = object()
        file = FakeFile()

    datum = to_datum(FakeMessage())
    assert datum.id == 7
    assert datum.media_type == "document"
    assert datum.file_name == "doc.pdf"
    assert datum.file_size == 1234


def test_telethon_scraper_unavailable(settings) -> None:
    registry = AccountRegistry(settings.resolved_accounts_file(), settings.resolved_session_dir())
    scraper = TelethonScraper(settings, registry)
    assert isinstance(is_scraper_available(), bool)
    assert scraper.available() is False


async def test_scrape_job_with_fake_scraper(db) -> None:
    from bot.db.engine import session_scope
    from bot.db.repositories import create_job, get_job, get_or_create_user
    from bot.jobs.handlers import register_handlers
    from bot.jobs.manager import JobManager
    from bot.services.file_manager import FileManager
    from tests.test_job_handlers import RecordingSender

    class FakeScraper:
        def available(self) -> bool:
            return True

        async def scrape(self, *, label, peer_ref, out, options, fmt, on_progress=None):
            Path(out).write_text("collected\n", encoding="utf-8")
            return ScrapeResult(scanned=5, exported=3, path=Path(out))

    sender = RecordingSender()
    fm = FileManager(db)
    manager = JobManager(files=fm, concurrency=1, sender=sender, default_ttl_minutes=10)
    register_handlers(manager, db, scraper=FakeScraper())

    async with session_scope() as session:
        user, _ = await get_or_create_user(session, 1)
        job = await create_job(
            session,
            user_id=user.id,
            kind="scrape",
            chat_id=1,
            params={"account": "main", "peer": "@group", "limit": 50, "format": "txt"},
        )
        job_id = job.id

    task = await manager.submit(job_id)
    await task

    async with session_scope() as session:
        stored = await get_job(session, job_id)
        assert stored.status == "completed", stored.error
    assert sender.documents
    assert sender.documents[0][1].read_text(encoding="utf-8") == "collected\n"


async def test_scrape_job_without_scraper_fails(db) -> None:
    from bot.db.engine import session_scope
    from bot.db.repositories import create_job, get_job, get_or_create_user
    from bot.jobs.handlers import register_handlers
    from bot.jobs.manager import JobManager
    from bot.services.file_manager import FileManager
    from tests.test_job_handlers import RecordingSender

    sender = RecordingSender()
    fm = FileManager(db)
    manager = JobManager(files=fm, concurrency=1, sender=sender, default_ttl_minutes=10)
    register_handlers(manager, db, scraper=None)

    async with session_scope() as session:
        user, _ = await get_or_create_user(session, 2)
        job = await create_job(session, user_id=user.id, kind="scrape", chat_id=1, params={})
        job_id = job.id

    task = await manager.submit(job_id)
    await task

    async with session_scope() as session:
        stored = await get_job(session, job_id)
        assert stored.status == "failed"
        assert stored.error and "Telegram account" in stored.error
