"""Clone a source chat into a destination channel (local CLI).

Usage:
    python -m bot.tools.clone <source> <destination> [limit]

* source / destination: ``@username`` or a numeric ``-100…`` id
* limit: how many recent messages to copy (default 200, max 5000)

Uses the first connected account in your account registry. Only chats that
account can already access are used; nothing is bypassed.
"""

from __future__ import annotations

import asyncio
import sys

from bot.config import get_settings
from bot.services.scraper import AccountRegistry
from bot.services.telegram_client import TelethonScraper, friendly_error


async def run(source: str, destination: str, limit: int) -> int:
    settings = get_settings()
    registry = AccountRegistry(
        settings.resolved_accounts_file(), settings.resolved_session_dir()
    )
    registry.sync_from_disk()
    accounts = registry.load()
    if not accounts:
        print("No accounts connected. Run: python -m bot.tools.plogin main")
        return 1

    scraper = TelethonScraper(settings, registry)
    if not scraper.available():
        print("Telegram API credentials missing (set TELEGRAM_API_ID / TELEGRAM_API_HASH).")
        return 1

    account = accounts[0]
    print(f"Account : {account.label} ({registry.status(account)})")
    print(f"Clone   : {source}  ->  {destination}   (limit {limit})")

    def on_progress(done: int) -> None:
        print(f"  copied {done} message(s)…")

    try:
        copied = await scraper.clone(
            label=account.label,
            src_ref=source,
            dest_ref=destination,
            limit=limit,
            on_progress=on_progress,
        )
    except Exception as exc:  # noqa: BLE001
        print("Failed:", friendly_error(exc))
        return 1

    print(f"Done. Copied {copied} message(s).")
    return 0


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    limit = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].isdigit() else 200
    return asyncio.run(run(sys.argv[1], sys.argv[2], max(1, min(limit, 5000))))


if __name__ == "__main__":
    raise SystemExit(main())
