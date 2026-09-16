"""Bot profile: command menus (public vs admin scopes) and descriptions."""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
)

logger = logging.getLogger(__name__)

SHORT_DESCRIPTION = "Extract, validate, filter and organise card serial files."

DESCRIPTION = (
    "Card File Bot — a professional toolkit for card serial files. "
    "Reply to a .txt with a command to clean, validate, filter, split, "
    "deduplicate or merge records."
)

PUBLIC_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="Start / main menu"),
    BotCommand(command="menu", description="Open the menu"),
    BotCommand(command="help", description="How to use the bot"),
    BotCommand(command="clean", description="Extract valid card records"),
    BotCommand(command="live", description="Keep records that pass the Luhn check"),
    BotCommand(command="filter", description="Filter by series prefix or keyword"),
    BotCommand(command="split", description="Split a file into N parts"),
    BotCommand(command="dedup", description="Remove duplicate lines"),
    BotCommand(command="addfile", description="Add a file to the merge queue"),
    BotCommand(command="merge", description="Combine the queued files"),
    BotCommand(command="clearqueue", description="Clear the merge queue"),
    BotCommand(command="scrape", description="Scrape a group/channel by keyword"),
    BotCommand(command="plogin", description="Connect a private account (guide)"),
    BotCommand(command="myaccounts", description="List connected accounts"),
    BotCommand(command="findbin", description="Extract records for a numeric BIN"),
    BotCommand(command="settings", description="Button / text mode"),
    BotCommand(command="emojis", description="How to customise the emojis"),
    BotCommand(command="id", description="Your ID and access status"),
    BotCommand(command="mykey", description="Check your access"),
    BotCommand(command="redeem", description="Redeem an access key"),
    BotCommand(command="request", description="Request access from an admin"),
    BotCommand(command="claimadmin", description="Become the first admin"),
]

ADMIN_COMMANDS: list[BotCommand] = PUBLIC_COMMANDS + [
    BotCommand(command="admin", description="Admin panel"),
    BotCommand(command="gen", description="Generate access keys"),
    BotCommand(command="keys", description="List unredeemed keys"),
    BotCommand(command="revoke", description="Revoke a key"),
    BotCommand(command="grant", description="Grant access to a user"),
    BotCommand(command="ungrant", description="Clear a user's access"),
    BotCommand(command="addadmin", description="Promote a user"),
    BotCommand(command="rmadmin", description="Demote a user"),
    BotCommand(command="block", description="Block a user"),
    BotCommand(command="unblock", description="Unblock a user"),
    BotCommand(command="emojiid", description="Get custom emoji IDs"),
    BotCommand(command="forward", description="Toggle forwarding to the channel"),
    BotCommand(command="stats", description="Bot statistics"),
]


async def set_public_commands(bot: Bot) -> None:
    await bot.set_my_commands(PUBLIC_COMMANDS, scope=BotCommandScopeDefault())


async def set_admin_commands(bot: Bot, chat_id: int) -> None:
    """Give a specific admin chat the extra admin commands."""
    await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=chat_id))


async def set_public_commands_for(bot: Bot, chat_id: int) -> None:
    await bot.set_my_commands(PUBLIC_COMMANDS, scope=BotCommandScopeChat(chat_id=chat_id))


async def configure_bot(bot: Bot, admin_ids: list[int] | None = None) -> None:
    """Set public commands for everyone and admin commands for known admins."""
    await set_public_commands(bot)
    await bot.set_my_short_description(short_description=SHORT_DESCRIPTION[:120])
    await bot.set_my_description(description=DESCRIPTION[:512])

    ids = set(admin_ids or [])
    try:
        from bot.config import get_settings
        from bot.db.engine import session_scope
        from bot.db.repositories import list_admins

        settings = get_settings()
        ids.update(settings.admin_ids)
        async with session_scope() as session:
            for user in await list_admins(session):
                ids.add(user.telegram_id)
    except Exception:  # noqa: BLE001 - profile setup must not block startup
        logger.exception("Could not load admin list for command scopes")

    for admin_id in ids:
        try:
            await set_admin_commands(bot, admin_id)
        except Exception:  # noqa: BLE001
            logger.debug("Could not set admin commands for %s", admin_id)
