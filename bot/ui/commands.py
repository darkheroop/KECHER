"""Bot profile setup: command menu and descriptions.

Applied automatically on startup and runnable standalone:
``python -m bot.tools.setup_bot``
"""

from __future__ import annotations

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeDefault

SHORT_DESCRIPTION = (
    "File processing & authorized security testing on your own test data."
)

DESCRIPTION = (
    "Process and organize files and datasets: convert, split, clean, deduplicate, "
    "merge and search. Includes offline validation of authorized synthetic/test "
    "payment data (no live authorizations, no payment networks contacted)."
)

COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="Start the bot"),
    BotCommand(command="menu", description="Open the main menu"),
    BotCommand(command="help", description="Show all commands"),
    BotCommand(command="settings", description="Preferences: UI mode, cleanup, language"),
    BotCommand(command="jobs", description="View background jobs"),
    BotCommand(command="cancel", description="Cancel a running job"),
    BotCommand(command="split", description="Split a TXT/CSV file"),
    BotCommand(command="clean", description="Clean & validate a dataset"),
    BotCommand(command="dedup", description="Remove duplicate records"),
    BotCommand(command="merge", description="Merge queued files"),
    BotCommand(command="addfile", description="Add a file to the merge queue"),
    BotCommand(command="clearqueue", description="Clear your merge queue"),
    BotCommand(command="doc2txt", description="Convert DOC/DOCX to TXT"),
    BotCommand(command="csv", description="Convert CSV/TSV to TXT"),
    BotCommand(command="find", description="Search an authorized dataset"),
    BotCommand(command="country", description="Group records by country"),
    BotCommand(command="pick", description="Export a country group"),
    BotCommand(command="bank", description="Group records by bank"),
    BotCommand(command="pickbank", description="Export a bank group"),
    BotCommand(command="live", description="Offline test-data validation (TEST MODE)"),
    BotCommand(command="validate", description="Alias for /live"),
    BotCommand(command="scrape", description="Import from an authorized source"),
    BotCommand(command="private_scrape", description="Import from an authorized private source"),
    BotCommand(command="myaccounts", description="Show authorized accounts"),
    BotCommand(command="plogin", description="How to connect an authorized account"),
    BotCommand(command="id", description="Show your ID and access status"),
    BotCommand(command="mykey", description="Check your access"),
    BotCommand(command="redeem", description="Redeem an access key"),
    BotCommand(command="claimadmin", description="Become the first admin (one-time)"),
    BotCommand(command="gen", description="Admin: generate keys (count + validity)"),
    BotCommand(command="keys", description="Admin: list unredeemed keys"),
    BotCommand(command="revoke", description="Admin: revoke a key"),
    BotCommand(command="grant", description="Admin: grant a user access"),
    BotCommand(command="ungrant", description="Admin: clear a user's access"),
    BotCommand(command="addadmin", description="Admin: promote a user"),
    BotCommand(command="rmadmin", description="Admin: demote a user"),
    BotCommand(command="stats", description="Admin: bot statistics"),
]


async def configure_bot(bot: Bot) -> None:
    """Set the command menu and profile descriptions for the default scope."""
    await bot.set_my_commands(COMMANDS, scope=BotCommandScopeDefault())
    await bot.set_my_short_description(short_description=SHORT_DESCRIPTION[:120])
    await bot.set_my_description(description=DESCRIPTION[:512])
