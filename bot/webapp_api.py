"""JSON API for the Mini App.

Authentication uses Telegram Web App ``initData`` (HMAC-SHA256 signed with the
bot token). Read-only endpoints expose the caller's own real data; admins get
aggregate stats. Nothing here performs Telegram network calls.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import urllib.parse

from aiohttp import web

from bot.config import Settings
from bot.db.engine import session_scope
from bot.db.models import AccessKey, User, UserFile
from bot.db.repositories import (
    count_active_access,
    count_admins,
    count_rows,
    get_bot_setting,
    get_or_create_user,
    get_user_settings,
    list_authorized_sources,
)
from bot.security.access import access_state, format_remaining, is_admin
from bot.services.scraper import AccountRegistry

logger = logging.getLogger(__name__)

MAX_AUTH_AGE = 86400  # 24h


def validate_init_data(
    init_data: str, bot_token: str, *, max_age: int = MAX_AUTH_AGE
) -> dict | None:
    """Verify Telegram Web App initData and return the embedded user."""
    if not init_data or not bot_token:
        return None
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        return None

    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None

    data_check = "\n".join(f"{key}={value}" for key, value in sorted(parsed.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, received_hash):
        return None

    auth_date = parsed.get("auth_date")
    if auth_date and max_age:
        try:
            if time.time() - int(auth_date) > max_age:
                return None
        except ValueError:
            return None

    raw_user = parsed.get("user")
    if not raw_user:
        return None
    try:
        return json.loads(raw_user)
    except json.JSONDecodeError:
        return None


async def _require_user(request: web.Request) -> tuple[Settings, dict]:
    settings: Settings = request.app["settings"]
    init_data = (
        request.headers.get("X-Init-Data")
        or request.query.get("initData")
        or ""
    )
    user = validate_init_data(init_data, settings.bot_token.get_secret_value())
    if not user:
        raise web.HTTPUnauthorized(
            text=json.dumps({"error": "unauthorized"}),
            content_type="application/json",
        )
    return settings, user


def _ok(payload: dict) -> web.Response:
    return web.json_response(payload)


async def api_me(request: web.Request) -> web.Response:
    settings, tg_user = await _require_user(request)
    async with session_scope() as session:
        user, _ = await get_or_create_user(
            session,
            int(tg_user["id"]),
            username=tg_user.get("username"),
            first_name=tg_user.get("first_name"),
        )
        row = await get_user_settings(session, user.id)
        state = access_state(user, settings)
        return _ok(
            {
                "id": user.telegram_id,
                "name": tg_user.get("first_name") or "",
                "username": tg_user.get("username") or "",
                "access": state,
                "remaining": format_remaining(user.access_until),
                "admin": is_admin(user, settings),
                "ui_mode": row.ui_mode,
                "language": row.language,
            }
        )


async def api_accounts(request: web.Request) -> web.Response:
    settings, tg_user = await _require_user(request)
    registry = AccountRegistry(
        settings.resolved_accounts_file(), settings.resolved_session_dir()
    )
    owner = int(tg_user["id"])
    async with session_scope() as session:
        user, _ = await get_or_create_user(session, owner)
        admin = is_admin(user, settings)

    accounts = registry.load() if admin else registry.accounts_for(owner)
    active = None
    try:
        async with session_scope() as session:
            active = await get_bot_setting(session, f"acting_account:{owner}") or await get_bot_setting(
                session, f"active_account:{owner}"
            )
    except Exception:  # noqa: BLE001
        active = None

    return _ok(
        {
            "admin": admin,
            "active": active,
            "accounts": [
                {
                    "label": account.label,
                    "status": registry.status(account),
                    "owner": account.owner,
                    "active": account.label == active,
                }
                for account in accounts
            ],
        }
    )


async def api_sources(request: web.Request) -> web.Response:
    _settings, tg_user = await _require_user(request)
    async with session_scope() as session:
        user, _ = await get_or_create_user(session, int(tg_user["id"]))
        sources = await list_authorized_sources(session, user.id)
        return _ok(
            {
                "sources": [
                    {"id": s.id, "title": s.title or s.tg_peer_ref, "kind": s.kind}
                    for s in sources
                ]
            }
        )


async def api_history(request: web.Request) -> web.Response:
    _settings, tg_user = await _require_user(request)
    async with session_scope() as session:
        raw = await get_bot_setting(session, f"scrape_hist:{int(tg_user['id'])}")
    items: list = []
    if raw:
        try:
            items = json.loads(raw)
        except json.JSONDecodeError:
            items = []
    return _ok({"history": items[:10]})


async def api_stats(request: web.Request) -> web.Response:
    settings, tg_user = await _require_user(request)
    async with session_scope() as session:
        user, _ = await get_or_create_user(session, int(tg_user["id"]))
        if not is_admin(user, settings):
            raise web.HTTPForbidden(
                text=json.dumps({"error": "forbidden"}), content_type="application/json"
            )
        stats = {
            "users": await count_rows(session, User),
            "admins": await count_admins(session),
            "active": await count_active_access(session),
            "keys": await count_rows(session, AccessKey),
            "files": await count_rows(session, UserFile),
        }
    return _ok(stats)


async def api_scrape(request: web.Request) -> web.Response:
    """Accept a scrape configuration from the Mini App.

    Execution stays in the chat (``/scrape``) so all limits, accounts and
    channel delivery continue to work; this endpoint validates and echoes it.
    """
    _settings, tg_user = await _require_user(request)
    try:
        payload = await request.json()
    except (json.JSONDecodeError, ValueError):
        payload = {}
    return _ok(
        {
            "ok": True,
            "user": tg_user.get("first_name") or "",
            "config": payload,
            "message": "Open /scrape in the chat to run this with your saved sources.",
        }
    )
