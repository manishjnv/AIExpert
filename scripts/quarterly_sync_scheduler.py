"""
Scheduler loop for the quarterly curriculum sync.

Runs as a long-lived container. Sleeps until the next quarterly run time
(the 1st of Jan/Apr/Jul/Oct at 02:00 UTC), then invokes quarterly_sync.main().

This avoids adding a dedicated cron daemon to the image — one less dependency,
one less failure mode.

For local testing, set QUARTERLY_SYNC_INTERVAL_SECONDS to a small number in
the environment and the scheduler will run that often instead of quarterly.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from scripts.quarterly_sync import main as run_sync

logger = logging.getLogger("quarterly_sync_scheduler")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


def next_quarterly_run(now: datetime) -> datetime:
    """
    Return the next quarterly run time after `now`.
    Quarters start on the 1st of Jan, Apr, Jul, Oct at 02:00 UTC.
    """
    # Normalize to UTC
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    candidates = []
    for year in (now.year, now.year + 1):
        for month in (1, 4, 7, 10):
            dt = datetime(year, month, 1, 2, 0, 0, tzinfo=timezone.utc)
            if dt > now:
                candidates.append(dt)

    return min(candidates)


async def scheduler_loop() -> None:
    """Main scheduler loop. Runs forever."""
    logger.info("Quarterly sync scheduler starting")

    # Test-mode override: run on a short interval if env var is set
    test_interval = os.environ.get("QUARTERLY_SYNC_INTERVAL_SECONDS")
    if test_interval:
        try:
            interval = int(test_interval)
            logger.warning("TEST MODE: running every %d seconds", interval)
            while True:
                await asyncio.sleep(interval)
                logger.info("Triggering sync (test mode)")
                await run_sync()
        except ValueError:
            logger.error("Invalid QUARTERLY_SYNC_INTERVAL_SECONDS: %s", test_interval)

    # Production mode: compute next run, sleep, repeat
    while True:
        now = datetime.now(timezone.utc)
        next_run = next_quarterly_run(now)
        sleep_seconds = (next_run - now).total_seconds()
        logger.info(
            "Next sync scheduled for %s (in %.1f hours)",
            next_run.isoformat(),
            sleep_seconds / 3600,
        )

        # Sleep in chunks so Docker stop signals aren't ignored for months
        chunk = 3600  # 1 hour
        while sleep_seconds > 0:
            await asyncio.sleep(min(chunk, sleep_seconds))
            sleep_seconds -= chunk

        logger.info("Triggering quarterly sync")
        try:
            result = await run_sync()
            logger.info("Sync finished with result: %s", result)
        except Exception:
            logger.exception("Sync raised an exception; will retry next quarter")

        # Brief sleep to avoid tight loop if clock jumps backward
        await asyncio.sleep(60)


if __name__ == "__main__":
    try:
        asyncio.run(scheduler_loop())
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by signal")
