"""Daily jobs ingest — scrapes Tier-1 sources, enriches via AI, stages as draft.

Runs 04:30 IST daily via the scheduler container. Never publishes — admin must
approve via /admin/jobs. See docs/JOBS.md §4, §10.

Run manually:
  docker compose exec backend python -m scripts.daily_jobs_sync
"""

from __future__ import annotations

import asyncio
import logging
import sys


async def _main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    from app.services.jobs_ingest import run_daily_ingest
    stats = await run_daily_ingest()
    print("jobs ingest stats:", stats)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
