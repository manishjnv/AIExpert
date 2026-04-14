"""Jobs ingest orchestrator.

Pipeline: fetch → normalize → hash → dedup → enrich → stage as draft.
Always stages as `status='draft'`. Only admin actions can flip to published.
See docs/JOBS.md §4.

Enrichment (Step 3) is called via `enrich_job()` — if it fails, the row is
still staged with a minimal payload and flagged via admin_notes for review.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import re
import secrets
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

import app.db as _db
from app.models import Job, JobCompany, JobSource
from app.services.jobs_sources import RawJob
from app.services.jobs_sources.greenhouse import GREENHOUSE_BOARDS, fetch_all as gh_fetch_all
from app.services.jobs_sources.lever import LEVER_BOARDS, fetch_all as lv_fetch_all

logger = logging.getLogger("roadmap.jobs.ingest")

# Default lifespan before a job auto-expires, per docs/JOBS.md §7.6.
VALID_FOR_DAYS = 45


# ---------------------------------------------------------------- helpers

def compute_hash(raw: RawJob) -> str:
    """Stable hash for change detection + cross-source dedup."""
    parts = [
        raw["title_raw"].strip().lower(),
        raw["company_slug"].strip().lower(),
        raw["location_raw"].strip().lower(),
        raw["jd_html"].strip(),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def slugify(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.lower()).strip("-")
    return re.sub(r"-+", "-", s)[:80]


def build_slug(title: str, company_slug: str) -> str:
    short = secrets.token_hex(2)  # 4-char stable-ish suffix; uniqueness enforced below
    return f"{slugify(title)}-at-{slugify(company_slug)}-{short}"


# ---------------------------------------------------------------- source registry

async def ensure_source_rows() -> None:
    """Upsert JobSource rows for every hardcoded source. Idempotent."""
    registry: list[tuple[str, str, list[tuple[str, str]]]] = [
        ("greenhouse", "Greenhouse", GREENHOUSE_BOARDS),
        ("lever", "Lever", LEVER_BOARDS),
    ]
    async with _db.async_session_factory() as db:
        for kind, label_suffix, boards in registry:
            for board_slug, company_name in boards:
                key = f"{kind}:{board_slug}"
                existing = (await db.execute(select(JobSource).where(JobSource.key == key))).scalar_one_or_none()
                if not existing:
                    db.add(JobSource(
                        key=key, kind=kind,
                        label=f"{company_name} ({label_suffix})",
                        tier=1, enabled=1, bulk_approve=1,
                    ))
                has_co = (await db.execute(select(JobCompany).where(JobCompany.slug == board_slug))).scalar_one_or_none()
                if not has_co:
                    db.add(JobCompany(slug=board_slug, name=company_name, verified=1))
        await db.commit()


# ---------------------------------------------------------------- core ingest

async def _stage_one(raw: RawJob, source_key: str, db) -> str:
    """Stage one RawJob. Returns one of: 'new', 'unchanged', 'changed', 'skipped_blocked'."""
    job_hash = compute_hash(raw)

    # Blocklist check.
    co = (await db.execute(select(JobCompany).where(JobCompany.slug == raw["company_slug"]))).scalar_one_or_none()
    if co and co.blocklisted:
        return "skipped_blocked"

    existing = (await db.execute(
        select(Job).where(Job.source == source_key, Job.external_id == raw["external_id"])
    )).scalar_one_or_none()

    if existing and existing.hash == job_hash:
        return "unchanged"

    # Enrich (best-effort; see jobs_enrich). Minimal fallback keeps row stageable.
    try:
        from app.services.jobs_enrich import enrich_job
        enriched = await enrich_job(raw)
        enrich_error = None
    except Exception as exc:  # never break ingest on enrichment failure
        logger.exception("enrichment failed for %s/%s: %s", source_key, raw["external_id"], exc)
        enriched = _minimal_enrichment(raw)
        enrich_error = f"enrichment failed: {exc}"

    posted_on = _parse_date(raw["posted_on"])
    valid_through = posted_on + timedelta(days=VALID_FOR_DAYS)

    # Build denormalized columns from enriched payload.
    country = (enriched.get("location") or {}).get("country")
    remote_policy = (enriched.get("location") or {}).get("remote_policy")
    designation = enriched.get("designation") or "Other"
    verified = 1 if (co and co.verified) else 0

    if existing:
        existing.hash = job_hash
        existing.status = "draft"          # back to draft on any change — re-review
        existing.posted_on = posted_on
        existing.valid_through = valid_through
        existing.title = raw["title_raw"]
        existing.designation = designation
        existing.country = country
        existing.remote_policy = remote_policy
        existing.verified = verified
        existing.data = enriched
        existing.source_url = raw["source_url"]
        existing.admin_notes = enrich_error
        return "changed"

    job = Job(
        source=source_key,
        external_id=raw["external_id"],
        source_url=raw["source_url"],
        hash=job_hash,
        status="draft",
        posted_on=posted_on,
        valid_through=valid_through,
        slug=build_slug(raw["title_raw"], raw["company_slug"]),
        title=raw["title_raw"],
        company_slug=raw["company_slug"],
        designation=designation,
        country=country,
        remote_policy=remote_policy,
        verified=verified,
        data=enriched,
        admin_notes=enrich_error,
    )
    db.add(job)
    return "new"


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except Exception:
        return date.today()


def _minimal_enrichment(raw: RawJob) -> dict[str, Any]:
    """Fallback payload when the AI enricher is unavailable. Admin sees a flag
    in admin_notes and can fix fields manually before publishing."""
    return {
        "title_raw": raw["title_raw"],
        "designation": "Other",
        "seniority": "Unknown",
        "topic": [],
        "company": {"name": raw["company"], "slug": raw["company_slug"]},
        "location": {"country": None, "city": None, "remote_policy": None, "regions_allowed": []},
        "employment": {"job_type": "Full-time", "shift": "Unknown"},
        "description_html": raw["jd_html"][:20000],
        "tldr": "",
        "must_have_skills": [],
        "nice_to_have_skills": [],
        "roadmap_modules_matched": [],
        "apply_url": raw["source_url"],
    }


async def _stage_with_retry(raw: RawJob, source_key: str, max_attempts: int = 4) -> str:
    """Stage one row with retry+backoff on SQLite 'database is locked'.

    SQLite WAL allows concurrent reads but only one writer at a time. The live
    backend writing session cookies / progress can briefly hold the lock. A
    short exponential backoff (0.2s, 0.4s, 0.8s) clears almost all real-world
    cases without needing server-side locking.
    """
    for attempt in range(max_attempts):
        try:
            async with _db.async_session_factory() as db:
                result = await _stage_one(raw, source_key, db)
                await db.commit()
                return result
        except OperationalError as exc:
            msg = str(exc).lower()
            if "database is locked" not in msg and "database table is locked" not in msg:
                raise
            if attempt == max_attempts - 1:
                logger.warning("db locked after %d attempts for %s/%s — giving up",
                               max_attempts, source_key, raw.get("external_id"))
                raise
            delay = 0.2 * (2 ** attempt) + random.uniform(0, 0.1)
            logger.info("db locked, retrying %s/%s in %.2fs (attempt %d/%d)",
                        source_key, raw.get("external_id"), delay, attempt + 1, max_attempts)
            await asyncio.sleep(delay)
    return "errors"  # unreachable — raised above


# ---------------------------------------------------------------- entry point

async def run_daily_ingest() -> dict[str, int]:
    """Run the full daily ingest. Returns stats dict (for admin banner + logs).

    Uses a fresh session per job so: (a) SQLite WAL writes stay short and
    don't collide with the live backend, (b) one failed row can't rollback
    the whole batch. Per-source fetch remains inside one transaction is OK
    because fetch is read-only HTTP.
    """
    await ensure_source_rows()
    stats = {"fetched": 0, "new": 0, "changed": 0, "unchanged": 0, "skipped": 0, "errors": 0}

    fetchers = [("greenhouse", GREENHOUSE_BOARDS, gh_fetch_all), ("lever", LEVER_BOARDS, lv_fetch_all)]

    for _kind, _boards, fetch in fetchers:
        async for source_key, raw in fetch():
            stats["fetched"] += 1
            try:
                result = await _stage_with_retry(raw, source_key)
                key = "skipped" if result == "skipped_blocked" else result
                stats[key] = stats.get(key, 0) + 1
            except Exception as exc:
                logger.exception("ingest error for %s/%s: %s", source_key, raw.get("external_id"), exc)
                stats["errors"] += 1

    # Stamp JobSource.last_run_* in a short final transaction.
    try:
        async with _db.async_session_factory() as db:
            now = datetime.utcnow()
            for kind, boards, _ in fetchers:
                for board_slug, _ in boards:
                    key = f"{kind}:{board_slug}"
                    src = (await db.execute(select(JobSource).where(JobSource.key == key))).scalar_one_or_none()
                    if src:
                        src.last_run_at = now
            await db.commit()
    except Exception as exc:
        logger.warning("failed to stamp JobSource.last_run_at: %s", exc)

    logger.info("jobs ingest complete: %s", stats)
    return stats
