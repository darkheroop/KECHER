"""Access keys and admin: /id, /mykey, /redeem, /gen, /keys, /revoke,
/grant, /ungrant, /addadmin, /rmadmin, /stats."""

from __future__ import annotations

import html
from datetime import UTC, datetime
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    User as TgUser,
)

from bot.config import Settings
from bot.db.engine import session_scope
from bot.db.models import AccessKey, Job, User, UserFile
from bot.db.repositories import (
    clear_user_access,
    count_active_access,
    count_admins,
    count_rows,
    create_access_keys,
    get_or_create_user,
    get_user_by_telegram_id,
    grant_user_access,
    list_access_keys,
    record_audit,
    revoke_access_key,
    set_user_admin,
    set_user_blocked,
)
from bot.handlers.common import ensure_user, notify_admins
from bot.security.access import (
    access_state,
    ensure_aware,
    format_remaining,
    has_active_access,
    is_admin,
)
from bot.services.keys import (
    format_duration,
    normalize_code,
    parse_duration_minutes,
)
from bot.ui.emoji import Emoji
from bot.ui.keyboards import back_to_menu

router = Router(name="keys")

MAX_GEN = 10000
KEYS_PER_MESSAGE = 25
FILE_THRESHOLD = 25


def _duration_label(minutes: int) -> str:
    return format_duration(minutes)


def _access_lines(user: User, settings: Settings) -> str:
    state = access_state(user, settings)
    until = ensure_aware(user.access_until)
    if state == "admin":
        status = f"{Emoji.ADMIN} Administrator (unrestricted)"
    elif state == "active":
        status = f"{Emoji.CHECK} Active — {format_remaining(until)} left"
    elif state == "expired":
        status = f"{Emoji.DENIED} Expired"
    else:
        status = f"{Emoji.LOCK} No access"
    lines = [
        f"{Emoji.USER} <b>Your access</b>",
        "",
        f"<b>ID:</b> <code>{user.telegram_id}</code>",
        f"<b>Status:</b> {status}",
    ]
    if until is not None and state == "active":
        lines.append(f"<b>Until:</b> {until:%Y-%m-%d %H:%M} UTC")
    return "\n".join(lines)


async def _require_admin(
    reply: Message | CallbackQuery, session, user: User, settings: Settings
) -> bool:
    if is_admin(user, settings):
        return True
    text = f"{Emoji.DENIED} Admin only."
    if isinstance(reply, CallbackQuery):
        await reply.answer(text, show_alert=True)
    else:
        await reply.answer(text)
    return False


def _target_id(message: Message) -> int | None:
    parts = (message.text or "").split()
    for token in parts[1:]:
        if token.lstrip("-").isdigit():
            return int(token)
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id
    return None


# --------------------------------------------------------------------------- #
# Public commands
# --------------------------------------------------------------------------- #
@router.message(Command("id"))
async def cmd_id(message: Message, settings: Settings) -> None:
    tg_user = message.from_user
    assert tg_user is not None
    async with session_scope() as session:
        user = await ensure_user(session, tg_user)
        text = _access_lines(user, settings)
        if is_admin(user, settings):
            text += "\n\nSend /stats, /gen, /keys for admin tools."
    await message.answer(text, reply_markup=back_to_menu())


@router.message(Command("mykey"))
async def cmd_mykey(message: Message, settings: Settings) -> None:
    await cmd_id(message, settings)


@router.message(Command("claimadmin"))
async def cmd_claimadmin(message: Message, settings: Settings) -> None:
    """Bootstrap: the first user may claim admin when none exists yet."""
    tg_user = message.from_user
    assert tg_user is not None
    async with session_scope() as session:
        user = await ensure_user(session, tg_user)
        if settings.admin_ids or await count_admins(session) > 0:
            await message.answer(
                f"{Emoji.DENIED} An admin already exists. Ask them to /addadmin you."
            )
            return
        user.is_admin = True
        await session.flush()
    await message.answer(
        f"{Emoji.ADMIN} <b>You are now an admin.</b>\n\n"
        "Next steps:\n"
        "• <code>/gen 5 1</code> — 5 keys for 1 day\n"
        "• <code>/stats</code> — bot statistics"
    )


@router.message(Command("request"))
async def cmd_request(message: Message, settings: Settings) -> None:
    tg_user = message.from_user
    assert tg_user is not None
    async with session_scope() as session:
        user = await ensure_user(session, tg_user)
        if is_admin(user, settings) or has_active_access(user):
            await message.answer(f"{Emoji.CHECK} You already have access.")
            return

    name = html.escape(tg_user.first_name or "user")
    username = f"@{tg_user.username}" if tg_user.username else "—"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Approve", callback_data=f"adm:approve:{tg_user.id}"),
                InlineKeyboardButton(text="⛔ Block", callback_data=f"adm:block:{tg_user.id}"),
            ]
        ]
    )
    await notify_admins(
        message.bot,
        settings,
        f"{Emoji.LOCK} <b>Access request</b>\n\n"
        f"{name} — <code>{tg_user.id}</code>\n{username}",
        keyboard,
    )
    await message.answer(
        f"{Emoji.CHECK} Request sent to the admins.\n"
        "You'll be notified once it's approved."
    )


@router.callback_query(F.data.startswith("adm:"))
async def adm_action(callback: CallbackQuery, settings: Settings) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or not parts[2].lstrip("-").isdigit():
        await callback.answer("Invalid", show_alert=True)
        return
    action, target_id = parts[1], int(parts[2])

    async with session_scope() as session:
        admin = await ensure_user(session, callback.from_user)
        if not is_admin(admin, settings):
            await callback.answer("Admins only", show_alert=True)
            return
        target = await get_user_by_telegram_id(session, target_id)
        if target is None:
            await callback.answer("User not found", show_alert=True)
            return
        if action == "approve":
            until = await grant_user_access(
                session, target, minutes=max(1, settings.approval_days) * 1440
            )
            summary = f"✅ Approved <code>{target_id}</code> until {until:%Y-%m-%d %H:%M} UTC"
            user_note = "✅ Your access was approved. Send /start to begin."
        else:
            await set_user_blocked(session, target_id, True)
            summary = f"⛔ Blocked <code>{target_id}</code>"
            user_note = "⛔ You have been blocked by an admin."

    try:
        await callback.bot.send_message(target_id, user_note)
    except Exception:  # noqa: BLE001 - user may have blocked the bot
        pass
    if callback.message is not None:
        await callback.message.edit_text(summary)
    await callback.answer("Done")


@router.message(Command("redeem"))
async def cmd_redeem(message: Message, settings: Settings) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(
            f"{Emoji.REDEEM} Send your key like this:\n"
            "<code>/redeem KECH-XXXX-XXXX-XXXX</code>\n\n"
            f"Tap a generated key to copy it, then paste it here."
        )
        return

    code = normalize_code(parts[1])
    tg_user = message.from_user
    assert tg_user is not None
    async with session_scope() as session:
        user, _ = await get_or_create_user(
            session, tg_user.id, username=tg_user.username, first_name=tg_user.first_name
        )
        ok, reason, until = await redeem_access_key(session, code, user)
        if ok:
            await record_audit(
                session, user_id=user.id, action="key_redeemed", detail={"batch": None}
            )

    if not ok:
        reasons = {
            "not_found": "That key was not found.",
            "used": "That key has already been used.",
            "revoked": "That key has been revoked.",
            "expired": "That key has expired.",
        }
        await message.answer(f"{Emoji.ERROR} {reasons.get(reason, 'Invalid key.')}")
        return

    await message.answer(
        f"{Emoji.SUCCESS} <b>Access granted!</b>\n\n"
        f"{Emoji.TIME} Remaining: <b>{format_remaining(until)}</b>\n\n"
        "You now have full access. Try /help."
    )


@router.callback_query(F.data == "access:open")
async def access_open(callback: CallbackQuery, settings: Settings) -> None:
    async with session_scope() as session:
        user = await ensure_user(session, callback.from_user)
        text = _access_lines(user, settings)
        admin = is_admin(user, settings)
    text += "\n\n" + (
        f"{Emoji.KEY} Redeem a key: <code>/redeem YOUR-KEY</code>"
    )
    if admin:
        text += f"\n\n{Emoji.ADMIN} Admin: /gen, /keys, /revoke, /grant, /stats"
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=back_to_menu())
    await callback.answer()


# --------------------------------------------------------------------------- #
# Admin commands
# --------------------------------------------------------------------------- #
@router.message(Command("gen"))
async def cmd_gen(message: Message, settings: Settings) -> None:
    tg_user = message.from_user
    assert tg_user is not None
    parts = (message.text or "").split()[1:]

    usage = (
        f"{Emoji.KEY} <b>Generate access keys</b>\n\n"
        f"Usage: <code>/gen &lt;count&gt; &lt;validity&gt;</code>\n\n"
        "Examples:\n"
        "<code>/gen 5 1</code> — 5 keys, 1 day each\n"
        "<code>/gen 50 12h</code> — 50 keys, 12 hours each\n"
        "<code>/gen 200 1d12h</code> — 200 keys, 1 day 12 hours each\n"
        "<code>/gen 10 2w</code> — 10 keys, 2 weeks each\n\n"
        f"{Emoji.INFO} Validity units: <code>m</code> minutes, <code>h</code> hours, "
        "<code>d</code> days, <code>w</code> weeks, <code>mo</code> months, "
        "<code>y</code> years. Combine them: <code>1d12h</code>, <code>2w3d</code>."
    )
    if not parts or not parts[0].isdigit():
        await message.answer(usage)
        return

    count = max(1, min(MAX_GEN, int(parts[0])))
    duration_token = " ".join(parts[1:]) if len(parts) > 1 else "1"
    minutes = parse_duration_minutes(duration_token)
    if minutes is None:
        await message.answer(
            f"{Emoji.ERROR} Invalid validity <code>{duration_token}</code>.\n\n{usage}"
        )
        return

    async with session_scope() as session:
        admin = await ensure_user(session, tg_user)
        if not await _require_admin(message, session, admin, settings):
            return
        keys = await create_access_keys(
            session,
            count=count,
            duration_minutes=minutes,
            created_by=admin.id,
        )
        batch = f"B{keys[0].id}"
        for key in keys:
            key.batch = batch
        await session.flush()
        codes = [key.code for key in keys]
        await record_audit(
            session,
            user_id=admin.id,
            action="keys_generated",
            detail={"count": count, "minutes": minutes, "batch": batch},
        )

    duration_label = format_duration(minutes)
    header = (
        f"{Emoji.GENERATE} <b>Generated {count:,} key(s)</b>\n"
        f"{Emoji.CLOCK} Validity: <b>{duration_label}</b> each\n"
        f"{Emoji.COPY} Tap a key to copy it."
    )

    if count <= FILE_THRESHOLD:
        for start in range(0, len(codes), KEYS_PER_MESSAGE):
            chunk = codes[start : start + KEYS_PER_MESSAGE]
            body = "\n".join(f"<code>{code}</code>" for code in chunk)
            await message.answer(f"{header}\n\n{body}" if start == 0 else body)
        return

    # Large batch: attach the full list as a file and show a preview.
    tmp_dir = Path(settings.resolved_storage_root()).parent / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    file_path = tmp_dir / f"{batch}.txt"
    file_path.write_text("\n".join(codes) + "\n", encoding="utf-8")
    preview = "\n".join(f"<code>{code}</code>" for code in codes[:10])
    try:
        await message.answer_document(
            FSInputFile(file_path, filename=f"keys_{count}_{minutes}min.txt"),
            caption=(
                f"{Emoji.GENERATE} <b>{count:,} keys</b>\n"
                f"{Emoji.CLOCK} Validity: {duration_label} each\n"
                f"{Emoji.COPY} Full list attached. Preview:\n{preview}"
            ),
        )
    finally:
        file_path.unlink(missing_ok=True)


@router.message(Command("keys"))
async def cmd_keys(message: Message, settings: Settings) -> None:
    tg_user = message.from_user
    assert tg_user is not None
    async with session_scope() as session:
        admin = await ensure_user(session, tg_user)
        if not await _require_admin(message, session, admin, settings):
            return
        keys = await list_access_keys(session, limit=20, unredeemed_only=True)

    if not keys:
        await message.answer(f"{Emoji.KEY} No unredeemed keys.")
        return
    lines = [f"{Emoji.KEY} <b>Unredeemed keys</b>", ""]
    for key in keys:
        lines.append(f"<code>{key.code}</code> — {_duration_label(key.duration_minutes)}")
    await message.answer("\n".join(lines))


@router.message(Command("revoke"))
async def cmd_revoke(message: Message, settings: Settings) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Usage: <code>/revoke KEY</code>")
        return
    tg_user = message.from_user
    assert tg_user is not None
    async with session_scope() as session:
        admin = await ensure_user(session, tg_user)
        if not await _require_admin(message, session, admin, settings):
            return
        ok = await revoke_access_key(session, parts[1])
    await message.answer(
        f"{Emoji.SUCCESS} Key revoked." if ok else f"{Emoji.ERROR} Key not found."
    )


@router.message(Command("grant"))
async def cmd_grant(message: Message, settings: Settings) -> None:
    tg_user = message.from_user
    assert tg_user is not None
    target_id = _target_id(message)
    if target_id is None:
        await message.answer("Usage: <code>/grant &lt;user_id&gt; [duration]</code>")
        return
    parts = (message.text or "").split()
    duration_token = next((p for p in parts[1:] if not p.lstrip("-").isdigit()), "1")
    minutes = parse_duration_minutes(duration_token) or 1440

    async with session_scope() as session:
        admin = await ensure_user(session, tg_user)
        if not await _require_admin(message, session, admin, settings):
            return
        target = await get_user_by_telegram_id(session, target_id)
        if target is None:
            await message.answer(
                f"{Emoji.ERROR} That user has not started the bot yet."
            )
            return
        until = await grant_user_access(session, target, minutes=minutes)

    await message.answer(
        f"{Emoji.GRANT} Granted <b>{_duration_label(minutes)}</b> to "
        f"<code>{target_id}</code>.\n{Emoji.TIME} Until {until:%Y-%m-%d %H:%M} UTC"
    )


@router.message(Command("ungrant"))
async def cmd_ungrant(message: Message, settings: Settings) -> None:
    tg_user = message.from_user
    assert tg_user is not None
    target_id = _target_id(message)
    if target_id is None:
        await message.answer("Usage: <code>/ungrant &lt;user_id&gt;</code>")
        return
    async with session_scope() as session:
        admin = await ensure_user(session, tg_user)
        if not await _require_admin(message, session, admin, settings):
            return
        target = await get_user_by_telegram_id(session, target_id)
        if target is None:
            await message.answer(f"{Emoji.ERROR} User not found.")
            return
        await clear_user_access(session, target)
    await message.answer(f"{Emoji.SUCCESS} Access cleared for <code>{target_id}</code>.")


@router.message(Command("addadmin"))
async def cmd_addadmin(message: Message, settings: Settings) -> None:
    tg_user = message.from_user
    assert tg_user is not None
    target_id = _target_id(message)
    if target_id is None:
        await message.answer("Usage: <code>/addadmin &lt;user_id&gt;</code>")
        return
    async with session_scope() as session:
        admin = await ensure_user(session, tg_user)
        if not await _require_admin(message, session, admin, settings):
            return
        target = await set_user_admin(session, target_id, True)
    await message.answer(
        f"{Emoji.ADMIN} <code>{target_id}</code> is now an admin."
        if target
        else f"{Emoji.ERROR} User not found."
    )


@router.message(Command("rmadmin"))
async def cmd_rmadmin(message: Message, settings: Settings) -> None:
    tg_user = message.from_user
    assert tg_user is not None
    target_id = _target_id(message)
    if target_id is None:
        await message.answer("Usage: <code>/rmadmin &lt;user_id&gt;</code>")
        return
    async with session_scope() as session:
        admin = await ensure_user(session, tg_user)
        if not await _require_admin(message, session, admin, settings):
            return
        target = await set_user_admin(session, target_id, False)
    await message.answer(
        f"{Emoji.SUCCESS} Admin removed from <code>{target_id}</code>."
        if target
        else f"{Emoji.ERROR} User not found."
    )


@router.message(Command("block"))
async def cmd_block(message: Message, settings: Settings) -> None:
    await _set_blocked(message, settings, True)


@router.message(Command("unblock"))
async def cmd_unblock(message: Message, settings: Settings) -> None:
    await _set_blocked(message, settings, False)


async def _set_blocked(message: Message, settings: Settings, blocked: bool) -> None:
    tg_user = message.from_user
    assert tg_user is not None
    target_id = _target_id(message)
    if target_id is None:
        action = "block" if blocked else "unblock"
        await message.answer(f"Usage: <code>/{action} &lt;user_id&gt;</code>")
        return
    async with session_scope() as session:
        admin = await ensure_user(session, tg_user)
        if not await _require_admin(message, session, admin, settings):
            return
        target = await set_user_blocked(session, target_id, blocked)
    if target is None:
        await message.answer(f"{Emoji.ERROR} User not found.")
        return
    if blocked:
        await message.answer(f"{Emoji.DENIED} <code>{target_id}</code> is now <b>blocked</b>.")
    else:
        await message.answer(f"{Emoji.SUCCESS} <code>{target_id}</code> is now <b>unblocked</b>.")


@router.message(Command("stats"))
async def cmd_stats(message: Message, settings: Settings) -> None:
    tg_user = message.from_user
    assert tg_user is not None
    async with session_scope() as session:
        admin = await ensure_user(session, tg_user)
        if not await _require_admin(message, session, admin, settings):
            return
        users = await count_rows(session, User)
        active = await count_active_access(session)
        admins = await count_admins(session)
        keys = await count_rows(session, AccessKey)
        files = await count_rows(session, UserFile)

    await message.answer(
        f"{Emoji.STATS} <b>Statistics</b>\n\n"
        f"{Emoji.USER} Users: {users:,}\n"
        f"{Emoji.CHECK} Active access: {active:,}\n"
        f"{Emoji.ADMIN} Admins: {admins:,}\n"
        f"{Emoji.KEY} Keys: {keys:,}\n"
        f"{Emoji.FILE} Files: {files:,}"
    )
