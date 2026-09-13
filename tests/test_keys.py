from datetime import UTC, datetime, timedelta

from aiogram.types import Chat, Message, User as TgUser

from bot.db.engine import session_scope
from bot.db.repositories import (
    count_active_access,
    count_admins,
    create_access_keys,
    get_access_key,
    get_or_create_user,
    grant_user_access,
    redeem_access_key,
    revoke_access_key,
    set_user_admin,
)
from bot.security.access import (
    access_state,
    format_remaining,
    has_active_access,
    is_admin,
)
from bot.security.middleware import AccessMiddleware
from bot.services.keys import (
    format_duration,
    generate_code,
    normalize_code,
    parse_duration_minutes,
)


# --------------------------------------------------------------------------- #
# Code generation / parsing
# --------------------------------------------------------------------------- #
def test_generate_code_format() -> None:
    code = generate_code()
    parts = code.split("-")
    assert parts[0] == "KECH"
    assert len(parts) == 4
    assert all(len(p) == 4 for p in parts[1:])
    assert code.isupper()
    assert "O" not in code and "0" not in code and "I" not in code


def test_generate_codes_are_unique() -> None:
    codes = {generate_code() for _ in range(200)}
    assert len(codes) == 200


def test_normalize_code() -> None:
    assert normalize_code(" kech-abc1-def2 ") == "KECH-ABC1-DEF2"


def test_parse_duration_minutes() -> None:
    assert parse_duration_minutes("1") == 1440
    assert parse_duration_minutes("2d") == 2880
    assert parse_duration_minutes("12h") == 720
    assert parse_duration_minutes("30m") == 30
    assert parse_duration_minutes("0") is None
    assert parse_duration_minutes("abc") is None


def test_parse_duration_compound_and_units() -> None:
    assert parse_duration_minutes("1d12h") == 2160
    assert parse_duration_minutes("2w3d") == (2 * 7 + 3) * 1440
    assert parse_duration_minutes("2w 3d 4h") == (2 * 7 + 3) * 1440 + 240
    assert parse_duration_minutes("90m") == 90
    assert parse_duration_minutes("1mo") == 43200
    assert parse_duration_minutes("1y") == 525600
    assert parse_duration_minutes("0.5d") == 720
    assert parse_duration_minutes("30s") == 1


def test_format_duration() -> None:
    assert format_duration(1440) == "1 day"
    assert format_duration(2880) == "2 days"
    assert format_duration(2160) == "1 day 12 hours"
    assert format_duration(60) == "1 hour"
    assert format_duration(30) == "30 mins"
    assert format_duration(10080) == "1 week"
    assert format_duration(15120) == "10 days 12 hours"  # not exact weeks


# --------------------------------------------------------------------------- #
# Access helpers
# --------------------------------------------------------------------------- #
def test_is_admin(settings) -> None:
    user = TgUser.model_construct(id=5, is_bot=False, first_name="A")
    from bot.db.models import User

    db_user = User(telegram_id=5)
    assert is_admin(db_user, settings) is False
    db_user.is_admin = True
    assert is_admin(db_user, settings) is True

    settings.admin_ids = [5]
    plain = User(telegram_id=5)
    assert is_admin(plain, settings) is True
    settings.admin_ids = []


def test_access_state_and_remaining(settings) -> None:
    from bot.db.models import User

    user = User(telegram_id=1)
    assert access_state(user, settings) == "none"
    user.access_until = datetime.now(UTC) + timedelta(hours=2)
    assert access_state(user, settings) == "active"
    assert has_active_access(user) is True
    assert "h" in format_remaining(user.access_until)
    user.access_until = datetime.now(UTC) - timedelta(minutes=1)
    assert access_state(user, settings) == "expired"
    assert has_active_access(user) is False


# --------------------------------------------------------------------------- #
# Repositories
# --------------------------------------------------------------------------- #
async def test_create_and_redeem_key(db) -> None:
    async with session_scope() as session:
        admin, _ = await get_or_create_user(session, 1000)
        keys = await create_access_keys(
            session, count=3, duration_minutes=60, created_by=admin.id
        )
        assert len(keys) == 3
        code = keys[0].code

    async with session_scope() as session:
        user, _ = await get_or_create_user(session, 2000)
        ok, reason, until = await redeem_access_key(session, code, user)
        assert ok and reason == "ok"
        assert until is not None

    async with session_scope() as session:
        user, _ = await get_or_create_user(session, 3000)
        ok, reason, _ = await redeem_access_key(session, code, user)
        assert (ok, reason) == (False, "used")


async def test_redeem_unknown_and_revoked(db) -> None:
    async with session_scope() as session:
        user, _ = await get_or_create_user(session, 1)
        ok, reason, _ = await redeem_access_key(session, "KECH-AAAA-BBBB-CCCC", user)
        assert (ok, reason) == (False, "not_found")

    async with session_scope() as session:
        admin, _ = await get_or_create_user(session, 1001)
        keys = await create_access_keys(
            session, count=1, duration_minutes=60, created_by=admin.id
        )
        await revoke_access_key(session, keys[0].code)
        user, _ = await get_or_create_user(session, 2)
        ok, reason, _ = await redeem_access_key(session, keys[0].code, user)
        assert (ok, reason) == (False, "revoked")


async def test_redeem_extends_existing_access(db) -> None:
    async with session_scope() as session:
        admin, _ = await get_or_create_user(session, 1)
        keys = await create_access_keys(
            session, count=2, duration_minutes=60, created_by=admin.id
        )
        user, _ = await get_or_create_user(session, 2)
        await redeem_access_key(session, keys[0].code, user)
        first = user.access_until
        await redeem_access_key(session, keys[1].code, user)
        assert user.access_until > first


async def test_grant_and_clear_access(db) -> None:
    async with session_scope() as session:
        user, _ = await get_or_create_user(session, 1)
        await grant_user_access(session, user, minutes=60)
        assert has_active_access(user) is True
        assert await count_active_access(session) >= 1


async def test_admin_flags_and_counts(db) -> None:
    async with session_scope() as session:
        await get_or_create_user(session, 1)
        assert await count_admins(session) == 0
        promoted = await set_user_admin(session, 1, True)
        assert promoted is not None and promoted.is_admin is True
        assert await count_admins(session) == 1


async def test_get_access_key_normalizes(db) -> None:
    async with session_scope() as session:
        admin, _ = await get_or_create_user(session, 1)
        keys = await create_access_keys(
            session, count=1, duration_minutes=60, created_by=admin.id
        )
        code = keys[0].code
    async with session_scope() as session:
        found = await get_access_key(session, f"  {code.lower()}  ")
        assert found is not None and found.code == code


# --------------------------------------------------------------------------- #
# Middleware gating
# --------------------------------------------------------------------------- #
def _message(text: str, user_id: int = 123) -> Message:
    return Message.model_construct(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat.model_construct(id=user_id, type="private"),
        from_user=TgUser.model_construct(id=user_id, is_bot=False, first_name="T"),
        text=text,
    )


async def test_middleware_allows_when_open(db, settings) -> None:
    settings.access_required = False
    called: list[int] = []

    async def handler(event, data):  # noqa: ANN001
        called.append(1)
        return "ok"

    message = _message("/split")
    result = await AccessMiddleware(settings)(handler, message, {"event_from_user": message.from_user})
    assert result == "ok" and called == [1]


async def test_middleware_allows_public_command(db, settings) -> None:
    settings.access_required = True
    settings.admin_ids = []
    called: list[int] = []

    async def handler(event, data):  # noqa: ANN001
        called.append(1)
        return "ok"

    message = _message("/help")
    await AccessMiddleware(settings)(handler, message, {"event_from_user": message.from_user})
    assert called == [1]


async def test_middleware_blocks_without_access(db, settings, monkeypatch) -> None:
    settings.access_required = True
    settings.admin_ids = []
    called: list[int] = []
    replies: list[str] = []

    async def handler(event, data):  # noqa: ANN001
        called.append(1)
        return "ok"

    async def fake_answer(self, text, **kwargs):  # noqa: ANN001
        replies.append(text)

    monkeypatch.setattr(Message, "answer", fake_answer)
    message = _message("/split", user_id=999)
    await AccessMiddleware(settings)(handler, message, {"event_from_user": message.from_user})
    assert called == []
    assert replies


async def test_middleware_allows_admin(db, settings) -> None:
    settings.access_required = True
    settings.admin_ids = [555]
    called: list[int] = []

    async def handler(event, data):  # noqa: ANN001
        called.append(1)
        return "ok"

    message = _message("/split", user_id=555)
    await AccessMiddleware(settings)(handler, message, {"event_from_user": message.from_user})
    assert called == [1]
    settings.admin_ids = []
