"""Daily per-company job-alert digest — cron entrypoint (Phase 1, email).

Reads a watermark (last-run UTC datetime) from a state file, emails each
subscriber the jobs published since then via app.services.job_alerts_digest,
then advances the watermark to the run start (only on success — a failed run
leaves the watermark so the next run retries the same window).

First run / missing state → last-24h window. State file:
$JOB_ALERTS_STATE or /data/job_alerts_state.json (atomic write; /data is the
mounted volume inside the backend container). Calls init_db/close_db explicitly
(standalone scripts start with async_session_factory=None).

Run:
  docker compose exec -T backend python -m scripts.send_job_alerts
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("roadmap.jobs.send_alerts")

STATE_PATH = os.environ.get("JOB_ALERTS_STATE", "/data/job_alerts_state.json")


def _read_watermark() -> datetime:
    try:
        data = json.loads(Path(STATE_PATH).read_text(encoding="utf-8"))
        return datetime.fromisoformat(data["last_run"])
    except Exception:
        # tz-aware UTC to match TimestampMixin.updated_at (avoids SQLite
        # datetime-format mismatches in the digest's `updated_at >= since`).
        return datetime.now(timezone.utc) - timedelta(hours=24)


def _write_watermark(ts: datetime) -> None:
    try:
        p = Path(STATE_PATH)
        if not p.parent.exists():
            logger.warning("state dir %s missing — watermark not persisted", p.parent)
            return
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"last_run": ts.isoformat()}), encoding="utf-8")
        os.replace(tmp, p)  # atomic — no torn reads on crash
    except Exception as exc:
        logger.warning("failed to persist watermark: %s", exc)


async def _main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    from app.db import close_db, init_db
    from app.services.job_alerts_digest import run_job_alerts_digest

    run_start = datetime.now(timezone.utc)
    since = _read_watermark()
    logger.info("job-alerts digest: window since %s", since.isoformat())

    await init_db()
    try:
        stats = await run_job_alerts_digest(since)
        print("job-alerts digest:", json.dumps(stats))
    finally:
        await close_db()

    # Only reached on success — advance the watermark so we don't re-send.
    _write_watermark(run_start)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
