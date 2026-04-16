#!/usr/bin/env python3
"""Backfill existing false-positive AI-jobs rows flagged by RCA-026.

Context: before RCA-026, the ingest pipeline stamped jobs like PhonePe
"Manager, Legal" with Topic=["Applied ML"] because the JD mentioned "LLB / LLM
from a recognized university" (LLM = Master of Laws degree, not Large Language
Model). The four-layer fix prevents new ingests, but existing rows need
cleanup.

This script re-applies the new filters (is_non_ai_title + has_non_ai_jd_signals)
to historical jobs and flags matches. Default action: clear `data.topic` to
[] and stamp admin_notes with "RCA-026 backfill: non-AI" so admin can review
and bulk-reject via the existing queue filters. Does NOT auto-reject —
safer to let admin confirm.

Usage:
    # Dry-run (lists matches, writes nothing):
    python scripts/backfill_rca026_non_ai.py --dry-run

    # Apply (clears topic, stamps admin_notes) — drafts only by default:
    python scripts/backfill_rca026_non_ai.py --apply

    # Include published rows too (rare — usually drafts):
    python scripts/backfill_rca026_non_ai.py --apply --all-statuses

    # Scope to a single source:
    python scripts/backfill_rca026_non_ai.py --apply --source greenhouse:phonepe

Idempotent: re-runs skip rows already stamped with "RCA-026 backfill".
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
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
from app.services.jobs_ingest import has_non_ai_jd_signals, is_non_ai_title

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger("backfill_rca026")

MARKER = "RCA-026 backfill: non-AI"


async def run(dry_run: bool, all_statuses: bool, source_filter: str | None) -> None:
    await init_db()
    try:
        stmt = select(Job)
        if not all_statuses:
            stmt = stmt.where(Job.status == "draft")
        if source_filter:
            stmt = stmt.where(Job.source == source_filter)

        async with db_module.async_session_factory() as db:
            jobs = (await db.execute(stmt)).scalars().all()
            logger.info("scanning %d jobs (status=%s, source=%s)",
                        len(jobs),
                        "any" if all_statuses else "draft",
                        source_filter or "any")

            title_hits = 0
            jd_hits = 0
            already_marked = 0
            updated = 0

            for job in jobs:
                if MARKER in (job.admin_notes or ""):
                    already_marked += 1
                    continue

                title_match = is_non_ai_title(job.title_raw or "")
                data = job.data or {}
                desc_html = data.get("description_html") or ""
                jd_match = has_non_ai_jd_signals(desc_html)

                if not (title_match or jd_match):
                    continue

                if title_match:
                    title_hits += 1
                if jd_match:
                    jd_hits += 1

                current_topic = data.get("topic") or []
                reason = "title" if title_match else "JD"
                logger.info(
                    "  [%s] %s | %s | topic=%s | %s",
                    job.source, job.external_id,
                    (job.title_raw or "")[:60],
                    current_topic,
                    f"match={reason}",
                )

                if not dry_run:
                    new_data = dict(data)
                    new_data["topic"] = []
                    job.data = new_data
                    existing_notes = (job.admin_notes or "").strip()
                    stamp = f"{MARKER} ({reason})"
                    job.admin_notes = f"{existing_notes} | {stamp}".lstrip(" |") if existing_notes else stamp
                    db.add(job)
                    updated += 1

            if not dry_run and updated:
                await db.commit()

            logger.info(
                "done — scanned=%d  title_hits=%d  jd_hits=%d  already_marked=%d  updated=%d  (dry_run=%s)",
                len(jobs), title_hits, jd_hits, already_marked, updated, dry_run,
            )
    finally:
        await close_db()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="scan only; no DB writes")
    ap.add_argument("--apply", action="store_true", help="apply changes (required unless --dry-run)")
    ap.add_argument("--all-statuses", action="store_true", help="include published/rejected rows (default: draft only)")
    ap.add_argument("--source", default=None, help="limit to one source key (e.g. greenhouse:phonepe)")
    args = ap.parse_args()

    if not args.dry_run and not args.apply:
        ap.error("must pass --dry-run or --apply")

    asyncio.run(run(dry_run=args.dry_run, all_statuses=args.all_statuses, source_filter=args.source))


if __name__ == "__main__":
    main()
