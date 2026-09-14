"""Bot profile setup: command menu and descriptions."""

from __future__ import annotations

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeDefault

SHORT_DESCRIPTION = "Manage wedding-card serial files: clean, validate, split, merge."

DESCRIPTION = (
    "Card File Bot — organise and validate wedding-card serial files "
    "(16-digit serial|date|time|invited). Reply to a .txt with a command."
)

COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="Start / main menu"),
    BotCommand(command="menu", description="Open the menu"),
    BotCommand(command="help", description="How to use the bot"),
    BotCommand(command="clean", description="Keep valid card records"),
    BotCommand(command="live", description="Keep Luhn-valid serials"),
    BotCommand(command="country", description="Keep card lines above a keyword"),
    BotCommand(command="split", description="Split a file into N parts"),
    BotCommand(command="dedup", description="Remove duplicate lines"),
    BotCommand(command="addfile", description="Add a file to the merge queue"),
    BotCommand(command="merge", description="Combine the queued files"),
    BotCommand(command="clearqueue", description="Clear the merge queue"),
    BotCommand(command="scrape", description="Import from a source (coming soon)"),
    BotCommand(command="findbin", description="Find BIN info (coming soon)"),
    BotCommand(command="settings", description="Button / text mode"),
    BotCommand(command="id", description="Your ID and access status"),
    BotCommand(command="mykey", description="Check your access"),
    BotCommand(command="redeem", description="Redeem an access key"),
    BotCommand(command="claimadmin", description="Become the first admin"),
    BotCommand(command="gen", description="Admin: generate keys"),
    BotCommand(command="keys", description="Admin: list unredeemed keys"),
    BotCommand(command="revoke", description="Admin: revoke a key"),
    BotCommand(command="grant", description="Admin: grant access"),
    BotCommand(command="ungrant", description="Admin: clear access"),
    BotCommand(command="addadmin", description="Admin: promote a user"),
    BotCommand(command="rmadmin", description="Admin: demote a user"),
    BotCommand(command="block", description="Admin: block a user"),
    BotCommand(command="unblock", description="Admin: unblock a user"),
    BotCommand(command="stats", description="Admin: statistics"),
]


async def configure_bot(bot: Bot) -> None:
    """Set the command menu and profile descriptions for the default scope."""
    await bot.set_my_commands(COMMANDS, scope=BotCommandScopeDefault())
    await bot.set_my_short_description(short_description=SHORT_DESCRIPTION[:120])
    await bot.set_my_description(description=DESCRIPTION[:512])
