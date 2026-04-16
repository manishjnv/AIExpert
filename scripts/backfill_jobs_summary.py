"""Backfill data.summary on existing jobs via Gemini Flash.

Iterates every job missing data.summary, calls enrich_job with the stored
source fields (title/company/location/jd_html), and writes the new summary
object back to job.data. Idempotent — re-running picks up only jobs still
missing the field.

Use carefully on the live DB: one Gemini Flash call per job, one DB write
per job. Bounded concurrency + retry on SQLite write-locks (same pattern
as jobs_ingest).

Run manually:
  docker compose exec backend python -m scripts.backfill_jobs_summary
  docker compose exec backend python -m scripts.backfill_jobs_summary --limit 20
  docker compose exec backend python -m scripts.backfill_jobs_summary --status draft
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
import sys

logger = logging.getLogger("roadmap.jobs.backfill_summary")

CONCURRENCY = 3      # Gemini Flash free tier ~15 RPM; stay conservative.
MAX_RETRIES = 4      # SQLite write lock backoff.


async def _process_one(job_id: int, sem: asyncio.Semaphore) -> str:
    """Re-enrich one job and merge the new summary in. Returns outcome string."""
    import app.db as _db
    from sqlalchemy import select
    from sqlalchemy.exc import OperationalError
    from app.models import Job
    from app.services.jobs_enrich import enrich_job
    from app.services.jobs_sources import RawJob

    async with sem:
        # Snapshot the job in a short read txn so we're not holding the lock
        # during the Gemini call.
        async with _db.async_session_factory() as db:
            job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
            if not job:
                return "missing"
            data = dict(job.data or {})
            if isinstance(data.get("summary"), dict) and data["summary"]:
                return "already_had_summary"
            raw: RawJob = RawJob(
                external_id=job.external_id,
                source_url=job.source_url,
                title_raw=job.title,
                company=(data.get("company") or {}).get("name") or job.company_slug,
                company_slug=job.company_slug,
                location_raw=" ".join(filter(None, [
                    (data.get("location") or {}).get("city"),
                    (data.get("location") or {}).get("country"),
                ])),
                jd_html=data.get("description_html") or "",
                posted_on=job.posted_on.isoformat() if job.posted_on else "",
                extra={},
            )

        try:
            enriched = await enrich_job(raw)
        except Exception as exc:
            logger.warning("enrich failed for job %s: %s", job_id, exc)
            return "error"

        new_summary = enriched.get("summary")
        if not isinstance(new_summary, dict):
            return "no_summary_returned"

        # Merge + write with retry on SQLite lock.
        for attempt in range(MAX_RETRIES):
            try:
                async with _db.async_session_factory() as db:
                    j = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
                    if not j:
                        return "missing"
                    merged = dict(j.data or {})
                    merged["summary"] = new_summary
                    j.data = merged
                    await db.commit()
                return "updated"
            except OperationalError as exc:
                msg = str(exc).lower()
                if "database is locked" not in msg and "database table is locked" not in msg:
                    raise
                if attempt == MAX_RETRIES - 1:
                    logger.warning("db locked writing summary for job %s — giving up", job_id)
                    return "error"
                delay = 0.2 * (2 ** attempt) + random.uniform(0, 0.1)
                await asyncio.sleep(delay)
        return "error"


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="max jobs to process (0 = all)")
    parser.add_argument("--status", default="", help="filter by status (draft|published|...)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    from app.logging_redact import install_redacting_filter
    install_redacting_filter()

    import app.db as _db
    from sqlalchemy import select
    from app.db import close_db, init_db
    from app.models import Job

    await init_db()
    try:
        async with _db.async_session_factory() as db:
            stmt = select(Job.id, Job.data)
            if args.status:
                stmt = stmt.where(Job.status == args.status)
            rows = (await db.execute(stmt)).all()
        # Only process jobs lacking a usable summary.
        todo = [rid for rid, data in rows
                if not (isinstance(data, dict) and isinstance(data.get("summary"), dict)
                        and data["summary"])]
        if args.limit:
            todo = todo[: args.limit]
        logger.info("backfill summary: %d jobs to process", len(todo))

        sem = asyncio.Semaphore(CONCURRENCY)
        stats: dict[str, int] = {}
        for coro in asyncio.as_completed([_process_one(j, sem) for j in todo]):
            outcome = await coro
            stats[outcome] = stats.get(outcome, 0) + 1
            total = sum(stats.values())
            if total % 10 == 0 or total == len(todo):
                logger.info("progress %d/%d — %s", total, len(todo), stats)

        print("backfill summary stats:", stats)
    finally:
        await close_db()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
