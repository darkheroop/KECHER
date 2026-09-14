from bot.db.engine import session_scope
from bot.db.enums import JobStatus
from bot.db.repositories import (
    add_queue_item,
    clear_queue,
    create_file,
    create_job,
    delete_file_row,
    get_file,
    get_or_create_user,
    list_active_jobs,
    list_jobs,
    list_queue_items,
    list_user_files,
    set_job_status,
)


async def test_file_create_get_list(db) -> None:
    async with session_scope() as session:
        user, _ = await get_or_create_user(session, 100)
        record = await create_file(
            session,
            user_id=user.id,
            original_name="a.csv",
            safe_name="a.csv",
            rel_path="inbox/a.csv",
            size_bytes=10,
        )
        file_id = record.id

    async with session_scope() as session:
        fetched = await get_file(session, file_id)
        assert fetched is not None and fetched.original_name == "a.csv"
        assert len(await list_user_files(session, user.id)) == 1


async def test_delete_file_row(db) -> None:
    async with session_scope() as session:
        user, _ = await get_or_create_user(session, 101)
        record = await create_file(
            session,
            user_id=user.id,
            original_name="b.txt",
            safe_name="b.txt",
            rel_path="inbox/b.txt",
            size_bytes=3,
        )
        file_id = record.id

    async with session_scope() as session:
        await delete_file_row(session, file_id)

    async with session_scope() as session:
        assert await get_file(session, file_id) is None


async def test_merge_queue_lifecycle(db) -> None:
    async with session_scope() as session:
        user, _ = await get_or_create_user(session, 200)
        f1 = await create_file(
            session, user_id=user.id, original_name="1.txt", safe_name="1.txt",
            rel_path="inbox/1.txt", size_bytes=1,
        )
        f2 = await create_file(
            session, user_id=user.id, original_name="2.txt", safe_name="2.txt",
            rel_path="inbox/2.txt", size_bytes=1,
        )
        await add_queue_item(session, user.id, f1.id)
        await add_queue_item(session, user.id, f2.id)
        await add_queue_item(session, user.id, f1.id)  # duplicate ignored
        items = await list_queue_items(session, user.id)
        assert [item.file_id for item in items] == [f1.id, f2.id]

    async with session_scope() as session:
        assert await clear_queue(session, user.id) == 2
        assert await list_queue_items(session, user.id) == []


async def test_bot_setting_roundtrip(db) -> None:
    from bot.db.repositories import get_bot_setting, set_bot_setting

    async with session_scope() as session:
        assert await get_bot_setting(session, "forward_enabled", "false") == "false"
        await set_bot_setting(session, "forward_enabled", "true")
    async with session_scope() as session:
        assert await get_bot_setting(session, "forward_enabled") == "true"
        await set_bot_setting(session, "forward_enabled", "false")


async def test_active_jobs_filter(db) -> None:
    async with session_scope() as session:
        user, _ = await get_or_create_user(session, 300)
        running = await create_job(session, user_id=user.id, kind="clean")
        done = await create_job(session, user_id=user.id, kind="split")
        await set_job_status(session, running, JobStatus.PROCESSING)
        await set_job_status(session, done, JobStatus.COMPLETED)

    async with session_scope() as session:
        active = await list_active_jobs(session, user.id)
        assert [job.kind for job in active] == ["clean"]
        assert len(await list_jobs(session, user.id)) == 2
