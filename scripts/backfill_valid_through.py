"""One-time backfill after raising VALID_FOR_DAYS (45 → 90).

Two phases, both idempotent, both commit-per-row (SQLite-WAL writer rule —
runs while the live backend may hold the writer slot):

  Phase 1 — EXTEND valid_through on draft + published rows to
    posted_on + VALID_FOR_DAYS, but ONLY when that extends the current value
    (never shortens an admin's manual extension). This revives published jobs
    that auto-closed under the old 45d window and pushes out the imminent
    expiry wave.

  Phase 2 — REJECT drafts that are STILL stale after the extension
    (valid_through <= today, i.e. posted more than VALID_FOR_DAYS ago). These
    can't usefully go live, so they're rejected with reason 'expired' to clear
    the review queue.

Does NOT touch status='expired' or 'rejected' rows (avoid reviving roles that
genuinely disappeared from the ATS / were hand-rejected).

Usage:
  python -m scripts.backfill_valid_through              # dry-run (no writes)
  python -m scripts.backfill_valid_through --apply
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, timedelta


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = parser.parse_args()
    dry = not args.apply

    import app.db as _db
    from sqlalchemy import select
    from app.db import close_db, init_db
    from app.models import Job, JobSource
    from app.services.jobs_ingest import VALID_FOR_DAYS

    today = date.today()
    extended = revived = rejected = 0

    await init_db()
    try:
        # ---- Phase 1: extend valid_through on draft + published -------------
        async with _db.async_session_factory() as db:
            rows = (await db.execute(
                select(Job).where(Job.status.in_(["draft", "published"]))
            )).scalars().all()
            print(f"phase1: scanning {len(rows)} draft+published rows (VALID_FOR_DAYS={VALID_FOR_DAYS})")
            for j in rows:
                new_vt = j.posted_on + timedelta(days=VALID_FOR_DAYS)
                if new_vt > j.valid_through:
                    was_past = j.valid_through <= today
                    now_future = new_vt > today
                    if j.status == "published" and was_past and now_future:
                        revived += 1
                    if not dry:
                        j.valid_through = new_vt
                        await db.commit()   # commit-per-row: release WAL writer
                    extended += 1
        print(f"phase1: {'WOULD extend' if dry else 'extended'} {extended} rows "
              f"({revived} published revived from closed → live)")

        # ---- Phase 2: reject drafts still stale after the extension ---------
        async with _db.async_session_factory() as db:
            drafts = (await db.execute(
                select(Job).where(Job.status == "draft")
            )).scalars().all()
            for j in drafts:
                # valid_through already reflects the extension when --apply ran;
                # in dry-run, recompute the prospective value to count correctly.
                vt = j.valid_through if not dry else max(
                    j.valid_through, j.posted_on + timedelta(days=VALID_FOR_DAYS))
                if vt <= today:
                    rejected += 1
                    if not dry:
                        j.status = "rejected"
                        j.reject_reason = "expired"
                        j.last_reviewed_on = today
                        j.last_reviewed_by = "system:backfill_valid_through"
                        src = (await db.execute(
                            select(JobSource).where(JobSource.key == j.source)
                        )).scalar_one_or_none()
                        if src:
                            src.total_rejected = (src.total_rejected or 0) + 1
                        await db.commit()
        print(f"phase2: {'WOULD reject' if dry else 'rejected'} {rejected} still-stale drafts "
              f"(posted >{VALID_FOR_DAYS}d ago) as 'expired'")
    finally:
        await close_db()

    print(f"DONE ({'DRY-RUN — no writes' if dry else 'APPLIED'}): "
          f"extended={extended} revived={revived} rejected={rejected}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
