"""Unified background scheduler for the cron container.

Runs three scheduled jobs in parallel asyncio tasks:

  - daily_jobs_sync      — every day 04:30 IST (23:00 UTC prior day)
  - weekly_jobs_digest   — every Monday 09:00 IST (03:30 UTC Monday)
  - quarterly_sync       — 1st of Jan/Apr/Jul/Oct at 02:00 UTC (unchanged)

Each job runs in its own task so one slow run can't delay another. Failures
are logged and the task waits for the next window — no auto-retry loop (that
belongs to operators, not the scheduler).

Kept dependency-free: no APScheduler, no cron daemon inside the image.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("scheduler")


# IST is UTC+05:30. All in-code times below are UTC; the NAME in the log line
# is IST for human clarity.

def _next_daily(utc_hour: int, utc_minute: int, now: datetime) -> datetime:
    """Next occurrence of <utc_hour>:<utc_minute> today or tomorrow."""
    candidate = now.replace(hour=utc_hour, minute=utc_minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def _next_weekly(weekday: int, utc_hour: int, utc_minute: int, now: datetime) -> datetime:
    """Next occurrence of <weekday> (0=Mon) at <utc_hour>:<utc_minute>."""
    days_ahead = (weekday - now.weekday()) % 7
    candidate = now.replace(hour=utc_hour, minute=utc_minute, second=0, microsecond=0) \
                + timedelta(days=days_ahead)
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


def _next_quarterly(now: datetime) -> datetime:
    candidates = []
    for year in (now.year, now.year + 1):
        for month in (1, 4, 7, 10):
            dt = datetime(year, month, 1, 2, 0, 0, tzinfo=timezone.utc)
            if dt > now:
                candidates.append(dt)
    return min(candidates)


async def _sleep_until(target: datetime, label: str) -> None:
    """Sleep in 1-hour chunks so SIGTERM / SIGINT are honored within a minute."""
    while True:
        now = datetime.now(timezone.utc)
        delta = (target - now).total_seconds()
        if delta <= 0:
            return
        logger.info("[%s] next run in %.1fh at %s", label, delta / 3600, target.isoformat())
        await asyncio.sleep(min(3600, delta))


async def _run_guarded(fn: Callable[[], Awaitable], label: str) -> None:
    try:
        await fn()
        logger.info("[%s] run complete", label)
    except Exception:
        logger.exception("[%s] run failed — will retry at next window", label)


# ---------- per-job loops ----------

async def daily_jobs_loop() -> None:
    # 04:30 IST = 23:00 UTC prior day
    while True:
        target = _next_daily(23, 0, datetime.now(timezone.utc))
        await _sleep_until(target, "daily_jobs_sync")
        from app.db import close_db, init_db
        from app.services.jobs_ingest import run_daily_ingest
        await init_db()
        try:
            await _run_guarded(run_daily_ingest, "daily_jobs_sync")
        finally:
            await close_db()


async def weekly_digest_loop() -> None:
    # Mon 09:00 IST = Mon 03:30 UTC (weekday 0)
    while True:
        target = _next_weekly(0, 3, 30, datetime.now(timezone.utc))
        await _sleep_until(target, "weekly_jobs_digest")
        from app.db import close_db, init_db
        from app.services.jobs_digest import run_weekly_digest
        await init_db()
        try:
            await _run_guarded(run_weekly_digest, "weekly_jobs_digest")
        finally:
            await close_db()


async def quarterly_sync_loop() -> None:
    from scripts.quarterly_sync import main as run_sync
    while True:
        target = _next_quarterly(datetime.now(timezone.utc))
        await _sleep_until(target, "quarterly_sync")
        await _run_guarded(run_sync, "quarterly_sync")
        await asyncio.sleep(60)  # guard against clock rewind


# ---------- test-mode override ----------
# Set JOBS_SCHEDULER_TEST=1 to run every job once on a 60-second cycle —
# useful for smoke-testing the container without waiting 24h.

async def _test_mode_loop() -> None:
    logger.warning("TEST MODE: running each job once every 60s")
    from app.db import close_db, init_db
    while True:
        await asyncio.sleep(60)
        await init_db()
        try:
            from app.services.jobs_ingest import run_daily_ingest
            from app.services.jobs_digest import run_weekly_digest
            await _run_guarded(run_daily_ingest, "TEST daily_jobs_sync")
            await _run_guarded(run_weekly_digest, "TEST weekly_jobs_digest")
        finally:
            await close_db()


async def main() -> None:
    logger.info("Scheduler starting (unified; daily jobs + weekly digest + quarterly sync)")
    if os.environ.get("JOBS_SCHEDULER_TEST"):
        await _test_mode_loop()
        return
    await asyncio.gather(
        daily_jobs_loop(),
        weekly_digest_loop(),
        quarterly_sync_loop(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by signal")
