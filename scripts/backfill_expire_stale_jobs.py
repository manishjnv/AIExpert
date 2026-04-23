#!/usr/bin/env python3
"""Backfill expired-status on published jobs whose valid_through has elapsed.

Context: between 2026-04-15 and 2026-04-23 the daily_jobs_sync in the cron
container repeatedly failed with "unable to open database file" inside
_auto_expire_past_valid_through / _auto_expire_missing / the final stamp.
The underlying cause was aiosqlite's PRAGMA-on-connect racing with concurrent
WAL writes from the backend; retry logic only covered "database is locked".
That has been fixed, but 195 jobs already sat past valid_through with
status=published — still appearing in /api/jobs and the sitemap. This script
flips them once so we don't wait a full daily cycle.

Usage:
    python scripts/backfill_expire_stale_jobs.py --dry-run
    python scripts/backfill_expire_stale_jobs.py --apply

Per-row commit so one failure can't rollback the whole batch (feedback_sqlite_writer_sessions.md).
Idempotent: rows already status=expired are skipped.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date
from pathlib import Path

_script_dir = Path(__file__).resolve().parent
for candidate in [_script_dir.parent / "backend", _script_dir.parent]:
    if (candidate / "app").is_dir():
        sys.path.insert(0, str(candidate))
        break

from sqlalchemy import select

import app.db as db_module
from app.db import close_db, init_db
from app.models import Job

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger("backfill_expire")


async def run(apply: bool) -> None:
    today = date.today()
    async with db_module.async_session_factory() as db:
        stmt = select(Job).where(
            Job.status == "published",
            Job.valid_through.is_not(None),
            Job.valid_through < today,
        )
        rows = (await db.execute(stmt)).scalars().all()
    logger.info("found %d published rows with valid_through < %s", len(rows), today.isoformat())

    flipped = 0
    for job in rows:
        logger.info(
            "  %s %s/%s valid_through=%s",
            "WOULD-FLIP" if not apply else "FLIP",
            job.source, job.external_id, job.valid_through.isoformat(),
        )
        if not apply:
            continue
        async with db_module.async_session_factory() as db:
            fresh = await db.get(Job, job.id)
            if fresh is None or fresh.status != "published":
                continue
            fresh.status = "expired"
            data = dict(fresh.data or {})
            meta = dict(data.get("_meta") or {})
            meta.setdefault("expired_reason", "date_based_backfill")
            meta.setdefault("expired_on", today.isoformat())
            data["_meta"] = meta
            fresh.data = data
            await db.commit()
            flipped += 1

    if apply:
        logger.info("flipped %d rows to status=expired", flipped)
    else:
        logger.info("dry-run complete; pass --apply to execute")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="list matches, write nothing")
    group.add_argument("--apply", action="store_true", help="flip matches to status=expired")
    args = parser.parse_args()

    async def _main() -> None:
        await init_db()
        try:
            await run(apply=args.apply)
        finally:
            await close_db()

    asyncio.run(_main())


if __name__ == "__main__":
    main()
