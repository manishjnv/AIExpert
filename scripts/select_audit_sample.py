#!/usr/bin/env python3
"""Mark 1% of Tier-1 published jobs as audit-pending for human review.

Wave 4 #16a — slow-drift detector. Runs weekly (Mondays 04:30 UTC) via
the unified scheduler. Selects a random 1% sample (min 1, max 20) of
Tier-1 published jobs not audited in the last 90 days, and stamps:

    Job.data["audit"] = {
        "selected_at": "<UTC ISO>",
        "status": "pending"
    }

Admin sees a "N pending Opus audit" badge in /admin/jobs and copies
a generated Claude Code prompt into VS Code (Claude Max — no API
spend). Audit results submitted via /admin/jobs/api/audit-submit
populate `audit.reviewed_at`, `audit.agreed`, `audit.notes`.

Usage:
    # Dry-run (no DB writes):
    python scripts/select_audit_sample.py --dry-run

    # Apply (default sample = 1%, capped at 20):
    python scripts/select_audit_sample.py --apply

    # Custom sample size:
    python scripts/select_audit_sample.py --apply --sample 5

    # Override the 90-day re-audit cooldown:
    python scripts/select_audit_sample.py --apply --cooldown-days 30
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

_script_dir = Path(__file__).resolve().parent
for candidate in [_script_dir.parent / "backend", _script_dir.parent]:
    if (candidate / "app").is_dir():
        sys.path.insert(0, str(candidate))
        break

from sqlalchemy import select

import app.db as db_module
from app.db import close_db, init_db
from app.models import Job, JobSource

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger("audit_sampler")

DEFAULT_SAMPLE_PCT = 0.01  # 1%
MIN_SAMPLE = 1
MAX_SAMPLE = 20
DEFAULT_COOLDOWN_DAYS = 90


def _seconds_since(iso: str) -> float:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).replace(tzinfo=None)
        return (datetime.utcnow() - dt).total_seconds()
    except Exception:
        return float("inf")


async def select_sample(
    sample_size: int | None,
    cooldown_days: int,
    dry_run: bool,
) -> list[int]:
    await init_db()
    try:
        async with db_module.async_session_factory() as db:
            # Find Tier-1 sources
            tier1_keys = {
                k for k, in (await db.execute(
                    select(JobSource.key).where(JobSource.tier == 1)
                )).all()
            }
            if not tier1_keys:
                logger.info("no tier-1 sources found — nothing to audit")
                return []

            # Pull all published jobs from tier-1 sources
            all_pub = (await db.execute(
                select(Job).where(
                    Job.status == "published",
                    Job.source.in_(tier1_keys),
                )
            )).scalars().all()

            cooldown_secs = cooldown_days * 86400
            eligible = []
            already_pending = 0
            for j in all_pub:
                audit = (j.data or {}).get("audit") or {}
                status = audit.get("status")
                if status == "pending":
                    already_pending += 1
                    continue
                reviewed_at = audit.get("reviewed_at")
                if reviewed_at and _seconds_since(reviewed_at) < cooldown_secs:
                    continue
                eligible.append(j)

            if not eligible:
                logger.info(
                    "no eligible jobs (tier1_published=%d, already_pending=%d, "
                    "rest within cooldown)",
                    len(all_pub), already_pending,
                )
                return []

            # Default sample = 1% of eligible (or pool — same for first run).
            # Clamped to [MIN_SAMPLE, MAX_SAMPLE].
            if sample_size is None:
                sample_size = max(MIN_SAMPLE, int(len(eligible) * DEFAULT_SAMPLE_PCT))
            sample_size = min(MAX_SAMPLE, sample_size, len(eligible))

            picked = random.sample(eligible, sample_size)
            logger.info(
                "selected %d jobs from pool of %d eligible "
                "(tier1_published=%d, already_pending=%d, cooldown=%dd)",
                len(picked), len(eligible), len(all_pub), already_pending, cooldown_days,
            )

            now_iso = datetime.utcnow().isoformat(timespec="seconds")
            picked_ids = []
            for j in picked:
                logger.info("  [%d] %s — %s | topic=%s | designation=%s",
                            j.id, j.source, j.title[:50], j.data.get("topic"), j.designation)
                picked_ids.append(j.id)
                if not dry_run:
                    new_data = dict(j.data or {})
                    new_data["audit"] = {
                        "selected_at": now_iso,
                        "status": "pending",
                    }
                    j.data = new_data

            if not dry_run:
                await db.commit()
                logger.info("committed %d audit-pending stamps", len(picked))
            else:
                logger.info("dry-run — no DB writes")

            return picked_ids
    finally:
        await close_db()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="scan + report only")
    ap.add_argument("--apply", action="store_true", help="commit audit stamps")
    ap.add_argument("--sample", type=int, default=None, help="override sample size")
    ap.add_argument("--cooldown-days", type=int, default=DEFAULT_COOLDOWN_DAYS,
                    help="skip jobs reviewed within N days")
    args = ap.parse_args()

    if not args.dry_run and not args.apply:
        ap.error("must pass --dry-run or --apply")

    asyncio.run(select_sample(
        sample_size=args.sample,
        cooldown_days=args.cooldown_days,
        dry_run=args.dry_run,
    ))


if __name__ == "__main__":
    main()
