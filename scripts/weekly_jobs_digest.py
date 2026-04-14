"""Weekly jobs digest — Monday 09:00 IST cron entrypoint.

Sends the top-5 match email to every user with email_notifications=True
who has at least one active UserPlan. See app/services/jobs_digest.py
and docs/JOBS.md §11.

Run manually:
  docker compose exec backend python -m scripts.weekly_jobs_digest
"""

from __future__ import annotations

import asyncio
import logging
import sys


async def _main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    from app.db import close_db, init_db
    from app.services.jobs_digest import run_weekly_digest
    await init_db()
    try:
        stats = await run_weekly_digest()
        print("digest stats:", stats)
    finally:
        await close_db()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
