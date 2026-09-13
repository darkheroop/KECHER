import io
import zipfile
from pathlib import Path

from docx import Document

from bot.db.engine import session_scope
from bot.db.repositories import (
    add_queue_item,
    create_file,
    create_job,
    get_job,
    get_or_create_user,
)
from bot.jobs.handlers import register_handlers
from bot.jobs.manager import JobManager
from bot.services.file_manager import FileManager


class RecordingSender:
    def __init__(self) -> None:
        self.documents: list[tuple[int, Path, str | None, str | None]] = []
        self.messages: list[tuple[int, str]] = []

    async def send_document(self, chat_id, path, *, caption=None, filename=None) -> None:
        self.documents.append((chat_id, Path(path), caption, filename))

    async def send_message(self, chat_id, text) -> None:
        self.messages.append((chat_id, text))


async def _user(telegram_id: int = 1) -> int:
    async with session_scope() as session:
        user, _ = await get_or_create_user(session, telegram_id)
        return user.id


async def _input(fm: FileManager, telegram_id: int, user_id: int, name: str, data: bytes) -> int:
    allocated = fm.allocate(telegram_id, name)
    allocated.path.write_bytes(data)
    stored = fm.finalize(allocated)
    async with session_scope() as session:
        record = await create_file(
            session,
            user_id=user_id,
            original_name=name,
            safe_name=stored.safe_name,
            rel_path=stored.rel_path,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
        )
        return record.id


async def _run(fm, manager, user_id, kind, *, file_id=None, params=None) -> tuple[str, str | None]:
    async with session_scope() as session:
        job = await create_job(
            session, user_id=user_id, kind=kind, input_file_id=file_id, chat_id=1, params=params
        )
        job_id = job.id
    task = await manager.submit(job_id)
    await task
    async with session_scope() as session:
        stored = await get_job(session, job_id)
        return stored.status, stored.error


def _setup(settings):
    sender = RecordingSender()
    fm = FileManager(settings)
    manager = JobManager(files=fm, concurrency=2, sender=sender, default_ttl_minutes=10)
    register_handlers(manager, settings)
    return fm, manager, sender


async def test_doc2txt_job(db) -> None:
    settings = db
    fm, manager, sender = _setup(settings)
    user_id = await _user()
    buffer = io.BytesIO()
    document = Document()
    document.add_paragraph("Report body")
    document.save(buffer)
    file_id = await _input(fm, 1, user_id, "report.docx", buffer.getvalue())

    status, error = await _run(fm, manager, user_id, "doc2txt", file_id=file_id)
    assert status == "completed", error
    assert sender.documents
    output = sender.documents[0][1]
    assert output.suffix == ".txt"
    assert "Report body" in output.read_text(encoding="utf-8")


async def test_csv_job_all_columns(db) -> None:
    fm, manager, sender = _setup(db)
    user_id = await _user()
    file_id = await _input(fm, 1, user_id, "data.csv", b"a,b\n1,2\n3,4\n")

    status, error = await _run(fm, manager, user_id, "csv", file_id=file_id)
    assert status == "completed", error
    output = sender.documents[0][1]
    assert output.read_text(encoding="utf-8") == "a | b\n1 | 2\n3 | 4\n"


async def test_split_job_creates_zip(db) -> None:
    fm, manager, sender = _setup(db)
    user_id = await _user()
    content = "".join(f"{i}\n" for i in range(10)).encode()
    file_id = await _input(fm, 1, user_id, "data.txt", content)

    status, error = await _run(
        fm, manager, user_id, "split", file_id=file_id, params={"mode": "lines", "value": 3}
    )
    assert status == "completed", error
    output = sender.documents[0][1]
    assert output.suffix == ".zip"
    with zipfile.ZipFile(output) as archive:
        assert len(archive.namelist()) == 4


async def test_clean_job_luhn(db) -> None:
    fm, manager, sender = _setup(db)
    user_id = await _user()
    data = b"4111111111111111|ok\n4242424242424241|bad\n"
    file_id = await _input(fm, 1, user_id, "cards.txt", data)

    status, error = await _run(
        fm,
        manager,
        user_id,
        "clean",
        file_id=file_id,
        params={
            "options": {
                "separator": "|",
                "luhn_field": 1,
                "remove_empty": True,
                "trim": True,
            }
        },
    )
    assert status == "completed", error
    output = sender.documents[0][1]
    assert output.read_text(encoding="utf-8").strip() == "4111111111111111|ok"


async def test_clean_job_luhn_check_all(db) -> None:
    fm, manager, sender = _setup(db)
    user_id = await _user()
    data = (
        b"row1 4111 1111 1111 1111\n"
        b"row2 4242 4242 4242 4241\n"
        b"row3 nothing numeric\n"
    )
    file_id = await _input(fm, 1, user_id, "mixed.txt", data)

    status, error = await _run(
        fm,
        manager,
        user_id,
        "clean",
        file_id=file_id,
        params={"options": {"luhn": True, "remove_empty": True, "trim": True}},
    )
    assert status == "completed", error
    output = sender.documents[0][1]
    assert output.read_text(encoding="utf-8") == "row1 4111 1111 1111 1111\n"


async def test_dedup_job(db) -> None:
    fm, manager, sender = _setup(db)
    user_id = await _user()
    file_id = await _input(fm, 1, user_id, "dupes.txt", b"x\ny\nx\n")

    status, error = await _run(
        fm, manager, user_id, "dedup", file_id=file_id, params={"normalize": False}
    )
    assert status == "completed", error
    output = sender.documents[0][1]
    assert output.read_text(encoding="utf-8") == "x\ny\n"


async def test_merge_job_uses_queue(db) -> None:
    fm, manager, sender = _setup(db)
    user_id = await _user()
    first = await _input(fm, 1, user_id, "a.txt", b"1\n2\n")
    second = await _input(fm, 1, user_id, "b.txt", b"2\n3\n")

    async with session_scope() as session:
        await add_queue_item(session, user_id, first)
        await add_queue_item(session, user_id, second)

    status, error = await _run(
        fm, manager, user_id, "merge", params={"dedup": True, "sort": False}
    )
    assert status == "completed", error
    output = sender.documents[0][1]
    assert output.read_text(encoding="utf-8") == "1\n2\n3\n"


DATASET = b"4111111111111111|IN|HDFC\n4242424242424242|US|Chase\n5555555555554444|IN|ICICI\n"


async def test_find_job(db) -> None:
    fm, manager, sender = _setup(db)
    user_id = await _user()
    file_id = await _input(fm, 1, user_id, "ds.txt", DATASET)

    status, error = await _run(
        fm, manager, user_id, "find", file_id=file_id, params={"query": "HDFC"}
    )
    assert status == "completed", error
    output = sender.documents[0][1]
    text = output.read_text(encoding="utf-8")
    assert "HDFC" in text
    assert "Chase" not in text


async def test_pick_job(db) -> None:
    fm, manager, sender = _setup(db)
    user_id = await _user()
    file_id = await _input(fm, 1, user_id, "ds.txt", DATASET)

    status, error = await _run(
        fm, manager, user_id, "pick", file_id=file_id, params={"field": 1, "value": "IN"}
    )
    assert status == "completed", error
    output = sender.documents[0][1]
    lines = output.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    assert all("|IN|" in line for line in lines)


async def test_pick_job_unknown_value(db) -> None:
    fm, manager, sender = _setup(db)
    user_id = await _user()
    file_id = await _input(fm, 1, user_id, "ds.txt", DATASET)

    status, error = await _run(
        fm, manager, user_id, "pickbank", file_id=file_id, params={"field": 1, "value": "ZZ"}
    )
    assert status == "completed", error
    assert sender.documents == []


async def test_validate_job(db) -> None:
    fm, manager, sender = _setup(db)
    user_id = await _user()
    data = b"4111111111111111|12/30\n4242424242424241|12/30\n"
    file_id = await _input(fm, 1, user_id, "t.txt", data)

    status, error = await _run(
        fm,
        manager,
        user_id,
        "validate",
        file_id=file_id,
        params={"options": {"luhn": True, "expiry": True}},
    )
    assert status == "completed", error
    output = sender.documents[0][1]
    text = output.read_text(encoding="utf-8")
    assert "411111******1111" in text
