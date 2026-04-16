#!/usr/bin/env python3
"""Backfill roadmap_modules_matched on existing jobs.

Session 13 fixed _get_module_slugs() (was returning []), so all historical
enrichments have roadmap_modules_matched: []. This script re-derives the
field from each job's must_have_skills + topic using the local skill→weeks
index — zero AI calls, zero cost.

Usage:
    # Dry-run (shows what would change, writes nothing):
    python scripts/backfill_modules_matched.py --dry-run

    # Backfill all jobs (any status):
    python scripts/backfill_modules_matched.py

    # Backfill only published jobs:
    python scripts/backfill_modules_matched.py --status published

Idempotent: safe to run multiple times. Only overwrites roadmap_modules_matched;
all other data fields preserved.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Ensure backend is importable when running from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import select

import app.db as db_module
from app.db import close_db, init_db
from app.models import Job
from app.services.jobs_modules import find_weeks_for_skill

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger("backfill_modules")


def derive_modules(data: dict) -> list[str]:
    """Derive roadmap_modules_matched from a job's skills + topics.

    Uses the same skill→weeks index that jobs_match uses. Collects unique
    template keys across all must_have_skills, capped at 6 (matching the
    enrichment validator cap).
    """
    skills = data.get("must_have_skills") or []
    topics = data.get("topic") or []

    template_keys: set[str] = set()
    for skill in skills:
        for ref in find_weeks_for_skill(skill, limit=3):
            template_keys.add(ref.template_key)
    # Also check topic names as skills (e.g. "LLM", "NLP", "MLOps")
    for topic in topics:
        for ref in find_weeks_for_skill(topic, limit=2):
            template_keys.add(ref.template_key)

    return sorted(template_keys)[:6]


async def run(*, dry_run: bool = False, status_filter: str | None = None) -> dict:
    await init_db()

    stats = {"scanned": 0, "updated": 0, "already_populated": 0, "no_match": 0}

    async with db_module.async_session_factory() as db:
        stmt = select(Job)
        if status_filter:
            stmt = stmt.where(Job.status == status_filter)

        jobs = (await db.execute(stmt)).scalars().all()
        stats["scanned"] = len(jobs)

        for job in jobs:
            data = dict(job.data or {})
            existing = data.get("roadmap_modules_matched") or []

            if existing:
                stats["already_populated"] += 1
                continue

            modules = derive_modules(data)
            if not modules:
                stats["no_match"] += 1
                logger.debug("no match: %s (%s)", job.title, job.slug)
                continue

            if dry_run:
                logger.info("[DRY-RUN] %s → %s", job.title[:60], modules)
                stats["updated"] += 1
                continue

            data["roadmap_modules_matched"] = modules
            job.data = data
            stats["updated"] += 1
            logger.info("updated: %s → %s", job.title[:60], modules)

        if not dry_run:
            await db.commit()
            logger.info("committed %d updates", stats["updated"])

    await close_db()
    return stats


def main():
    parser = argparse.ArgumentParser(description="Backfill roadmap_modules_matched on jobs")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    parser.add_argument("--status", type=str, default=None, help="Filter by status (published, draft, etc.)")
    args = parser.parse_args()

    stats = asyncio.run(run(dry_run=args.dry_run, status_filter=args.status))

    print(f"\n{'[DRY-RUN] ' if args.dry_run else ''}Results:")
    print(f"  Scanned:           {stats['scanned']}")
    print(f"  Updated:           {stats['updated']}")
    print(f"  Already populated: {stats['already_populated']}")
    print(f"  No match found:    {stats['no_match']}")


if __name__ == "__main__":
    main()
