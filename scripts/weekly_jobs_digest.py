"""Weekly combined digest — Monday cron entrypoint (manual fallback).

Sends one combined email per opted-in user with sections per opt-in
channel (jobs / roadmap / blog). The canonical cron is
[scripts/scheduler.py](./scheduler.py)::weekly_digest_loop; this script
is the manual run fallback for ops.

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
    from app.services.weekly_digest import run_weekly_combined_digest
    await init_db()
    try:
        stats = await run_weekly_combined_digest()
        print("digest stats:", stats)
    finally:
        await close_db()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
