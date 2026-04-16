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
from app.services.jobs_sources.ashby import ASHBY_BOARDS, fetch_all as ash_fetch_all
from app.services.jobs_sources.greenhouse import GREENHOUSE_BOARDS, fetch_all as gh_fetch_all
from app.services.jobs_sources.lever import LEVER_BOARDS, fetch_all as lv_fetch_all

logger = logging.getLogger("roadmap.jobs.ingest")

# Default lifespan before a job auto-expires, per docs/JOBS.md §7.6.
VALID_FOR_DAYS = 45

# Max new jobs enriched per source per run. Anthropic + Databricks alone list
# 1200+ roles combined; enriching all in one run (~7s/Gemini call) would take
# hours. Capping means heavy boards take a few days to fully catch up, which
# is fine — newest-first ordering surfaces recent posts fast.
PER_SOURCE_NEW_CAP = 30

# Bounded parallelism for enrichment. Gemini Flash free tier allows ~15 RPM;
# 4 concurrent calls average 3-4s/call wall time and stay well under limits.
ENRICH_CONCURRENCY = 4

# Consecutive daily runs a published job may be absent from its source feed
# before auto-expiring. 2 = one grace day absorbs transient ATS API blips.
# See docs/JOBS.md §7.6 and docs/TASKS.md Phase 13.
MISSING_STREAK_THRESHOLD = 2

# ---------------------------------------------------------------- pre-filter

# Titles matching these patterns are almost certainly non-AI roles and should
# skip enrichment entirely. They still get staged as draft with admin_notes so
# admin can override manually. Patterns are case-insensitive substring matches
# against the raw title. Keep this list tight — false positives waste admin time;
# false negatives only waste a cheap Flash call.
_NON_AI_TITLE_PATTERNS: list[str] = [
    # Business / operations
    "sales manager", "sales director", "sales representative", "account executive",
    "account manager", "business development representative", "bdr ",
    "customer success", "customer support", "customer service",
    "office manager", "office coordinator", "executive assistant",
    "administrative assistant", "receptionist", "facilities",
    # Legal / finance / HR
    "legal counsel", "general counsel", "paralegal", "attorney",
    "legal manager", "manager, legal", "manager - legal", "manager-legal",
    "legal associate", "legal analyst", "legal specialist", "legal operations",
    "legal affairs", "corporate counsel", "contracts manager", "contract manager",
    "compliance manager", "compliance officer", "compliance analyst",
    "chief legal officer", "head of legal", "vp, legal", "vp legal",
    "tax manager", "tax analyst", "accountant", "accounting",
    "financial analyst", "fp&a", "controller", "accounts payable",
    "accounts receivable", "payroll", "compensation analyst",
    "recruiter", "recruiting coordinator", "talent acquisition",
    "human resources", " hr manager", " hr business partner",
    "benefits administration", "benefits manager", "benefits analyst",
    "merchant kyc", "kyc analyst", "kyc specialist", "merchant onboarding",
    # Marketing (non-technical)
    "content writer", "copywriter", "social media manager",
    "event manager", "event coordinator", "public relations",
    "communications manager", "brand manager",
    # Supply chain / logistics
    "supply chain", "logistics", "warehouse", "procurement",
    "inventory manager",
]

# Tier-2 boards: non-AI-native companies where most listings are non-AI roles.
# These get lightweight enrichment (no nice_to_have, no modules, no desc rewrite)
# to save ~40% tokens per call. Full enrichment runs on-demand when admin publishes.
# AI-native companies (Anthropic, Scale, xAI, Cohere, etc.) stay Tier-1 = full enrichment.
TIER2_SOURCES: set[str] = {
    "greenhouse:phonepe", "greenhouse:groww",
    "lever:cred", "lever:mindtickle",
    "ashby:notion", "ashby:replit",
}


def is_non_ai_title(title: str) -> bool:
    """Return True if the title matches a known non-AI pattern.

    Used to skip enrichment (saves ~$0.0004/job) on roles that would be
    rejected by admin anyway. The row is still staged so admin can override.
    """
    t = title.lower()
    return any(pat in t for pat in _NON_AI_TITLE_PATTERNS)


# JD-body cluster of terms that strongly indicate non-AI domains (law, HR,
# procurement, finance). A job hitting >=2 of these AND zero AI signals is
# almost certainly a false positive like PhonePe "Manager, Legal" where
# "LLB / LLM from a recognized university" tricked the enricher into
# tagging it as "Applied ML". See RCA-026.
_NON_AI_JD_SIGNALS: tuple[str, ...] = (
    # Legal
    "llb", "ll.b", "ll.m", "pqe", "post-qualification experience",
    "bar council", "indian contract act", "indian penal code",
    "law firm", "law school", "master of laws", "advocate",
    "procurement contracts", "commercial contracts", "contract drafting",
    "contract negotiation", "legal counsel", "legal advisory",
    "redlining", "msa ", "nda ", "sla ",
    # HR / benefits / KYC / finance
    "payroll processing", "benefits administration", "kyc verification",
    "kyc analyst", "merchant onboarding", "onboarding specialist",
    "bookkeeping", "gst filing", "tds ",
)

# Strong AI-signal words in JD body. If ANY hit, we do NOT suppress by JD
# signals — keeps legit AI roles that happen to mention contracts/NDAs safe.
# Keep tight and high-precision — false positives here cost us accuracy.
_AI_JD_SIGNALS: tuple[str, ...] = (
    "machine learning", "deep learning", "neural network", "transformer",
    "pytorch", "tensorflow", "jax ", "hugging face", "huggingface",
    "large language model", "large-language model", "llm-based",
    "fine-tuning", "fine tuning", "prompt engineering", "rag pipeline",
    "retrieval augmented", "retrieval-augmented",
    "computer vision", "nlp model", "natural language processing",
    "reinforcement learning", "mlops", "ml ops", "ml platform",
    "model training", "model inference", "model evaluation", "embedding model",
    "vector database", "langchain", "llamaindex",
    "openai", "anthropic", "claude api", "gemini api", "gpt-4", "gpt-5",
    "generative ai", "gen ai ", "genai ",
    "data scientist", "ml engineer", "ai engineer", "research scientist",
)


def has_non_ai_jd_signals(jd_html: str) -> bool:
    """Return True if the JD body looks like a non-AI role (legal/HR/finance).

    Uses a conservative two-gate rule: (a) >=2 distinct legal/HR/finance
    cluster hits, AND (b) zero strong AI-signal terms. This catches PhonePe
    "Manager, Legal" (with LLB, PQE, procurement contracts, MSA/NDA, Indian
    Contract Act) while keeping safe an AI Solutions Architect who happens
    to mention commercial contracts in passing.
    """
    text = jd_html.lower()
    non_ai_hits = sum(1 for sig in _NON_AI_JD_SIGNALS if sig in text)
    if non_ai_hits < 2:
        return False
    if any(sig in text for sig in _AI_JD_SIGNALS):
        return False
    return True


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
    """Upsert JobSource rows for every hardcoded source. Idempotent.

    Sources in TIER2_SOURCES (non-AI-native companies) get tier=2, bulk_approve=0,
    and their JobCompany.verified=0. Bulk-publish and the green T1 chip are both
    gated on verified/tier=1, so this keeps mixed-role boards (PhonePe, Groww, …)
    out of the fast path — they require per-row review regardless of the
    lite-enrichment path already taken in _stage_one.
    """
    registry: list[tuple[str, str, list[tuple[str, str]]]] = [
        ("greenhouse", "Greenhouse", GREENHOUSE_BOARDS),
        ("lever", "Lever", LEVER_BOARDS),
        ("ashby", "Ashby", ASHBY_BOARDS),
    ]
    async with _db.async_session_factory() as db:
        for kind, label_suffix, boards in registry:
            for board_slug, company_name in boards:
                key = f"{kind}:{board_slug}"
                is_tier2 = key in TIER2_SOURCES
                existing = (await db.execute(select(JobSource).where(JobSource.key == key))).scalar_one_or_none()
                if not existing:
                    db.add(JobSource(
                        key=key, kind=kind,
                        label=f"{company_name} ({label_suffix})",
                        tier=2 if is_tier2 else 1,
                        enabled=1,
                        bulk_approve=0 if is_tier2 else 1,
                    ))
                has_co = (await db.execute(select(JobCompany).where(JobCompany.slug == board_slug))).scalar_one_or_none()
                if not has_co:
                    db.add(JobCompany(slug=board_slug, name=company_name, verified=0 if is_tier2 else 1))
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

    # Pre-filter: skip enrichment for titles that are obviously non-AI.
    # Row is still staged (admin can override), but no Gemini call is made.
    if is_non_ai_title(raw["title_raw"]):
        enriched = _minimal_enrichment(raw)
        enrich_error = "auto-skipped: non-AI title"
        logger.debug("pre-filtered non-AI title: %s (%s)", raw["title_raw"], source_key)
    elif has_non_ai_jd_signals(raw["jd_html"]):
        # JD body is saturated with non-AI cluster terms (legal/HR/finance) and
        # has no AI signals. Title alone wouldn't have caught it. See RCA-026.
        enriched = _minimal_enrichment(raw)
        enrich_error = "auto-skipped: non-AI JD content (legal/HR/finance cluster)"
        logger.debug("pre-filtered non-AI JD: %s (%s)", raw["title_raw"], source_key)
    elif source_key in TIER2_SOURCES:
        # Tier-2 boards get lightweight enrichment — fewer fields, shorter JD,
        # smaller prompt. Full enrichment deferred to publish time.
        try:
            from app.services.jobs_enrich import enrich_job_lite
            enriched = await enrich_job_lite(raw, db=db)
            enrich_error = "tier2-lite: full enrichment on publish"
        except Exception as exc:
            logger.exception("lite enrichment failed for %s/%s: %s", source_key, raw["external_id"], exc)
            enriched = _minimal_enrichment(raw)
            enrich_error = f"lite enrichment failed: {exc}"
    else:
        # Enrich (best-effort; see jobs_enrich). Minimal fallback keeps row stageable.
        try:
            from app.services.jobs_enrich import enrich_job
            enriched = await enrich_job(raw, source_key=source_key, db=db)
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


# ---------------------------------------------------------------- auto-expire

async def _auto_expire_past_valid_through(stats: dict) -> None:
    """Flip published jobs whose valid_through has elapsed to expired.

    Without this, a job whose `posted_on + 45d` has passed remained
    status=published forever and only rendered the "closed" banner via the
    is_expired check at render time — but it kept appearing in /api/jobs
    and the sitemap. This pass fixes the underlying status.
    """
    try:
        async with _db.async_session_factory() as db:
            today = date.today()
            stmt = select(Job).where(
                Job.status == "published",
                Job.valid_through.is_not(None),
                Job.valid_through < today,
            )
            rows = (await db.execute(stmt)).scalars().all()
            for job in rows:
                job.status = "expired"
                data = dict(job.data or {})
                meta = dict(data.get("_meta") or {})
                meta.setdefault("expired_reason", "date_based")
                meta.setdefault("expired_on", today.isoformat())
                data["_meta"] = meta
                job.data = data
                stats["auto_expired"] = stats.get("auto_expired", 0) + 1
            if rows:
                logger.info("date-expired %d jobs (valid_through past)", len(rows))
            await db.commit()
    except Exception as exc:
        logger.exception("date-based auto-expire failed: %s", exc)


async def _auto_expire_missing(by_source: dict[str, list[RawJob]], stats: dict) -> None:
    """Flip `published` jobs to `expired` when their ATS listing disappears.

    Greenhouse/Lever give no explicit "role filled" signal — a closed posting
    simply drops from the feed. We track `data._meta.missing_streak` per job
    and flip once the streak hits MISSING_STREAK_THRESHOLD. One grace day
    absorbs transient API blips without falsely expiring live roles.

    Only runs against boards that returned ≥1 row this pass — a source that
    yielded zero rows is treated as an outage, not a mass fill.
    """
    for source_key, rows in by_source.items():
        if not rows:
            logger.warning("source %s returned 0 rows — skipping auto-expire", source_key)
            continue
        seen_ids = {r["external_id"] for r in rows}
        try:
            async with _db.async_session_factory() as db:
                stmt = select(Job).where(Job.source == source_key, Job.status == "published")
                published = (await db.execute(stmt)).scalars().all()
                for job in published:
                    data = dict(job.data or {})
                    meta = dict(data.get("_meta") or {})
                    if job.external_id in seen_ids:
                        if meta.get("missing_streak"):
                            meta["missing_streak"] = 0
                            data["_meta"] = meta
                            job.data = data
                        continue
                    streak = int(meta.get("missing_streak", 0)) + 1
                    meta["missing_streak"] = streak
                    if streak >= MISSING_STREAK_THRESHOLD:
                        job.status = "expired"
                        meta["expired_reason"] = "source_removed"
                        meta["expired_on"] = date.today().isoformat()
                        stats["auto_expired"] = stats.get("auto_expired", 0) + 1
                        logger.info("auto-expired %s/%s after %d missed runs",
                                    source_key, job.external_id, streak)
                    data["_meta"] = meta
                    job.data = data
                await db.commit()
        except Exception as exc:
            logger.exception("auto-expire failed for %s: %s", source_key, exc)


# ---------------------------------------------------------------- entry point

async def run_daily_ingest() -> dict[str, int]:
    """Run the full daily ingest. Returns stats dict (for admin banner + logs).

    Uses a fresh session per job so: (a) SQLite WAL writes stay short and
    don't collide with the live backend, (b) one failed row can't rollback
    the whole batch. Per-source fetch remains inside one transaction is OK
    because fetch is read-only HTTP.
    """
    await ensure_source_rows()
    # Probe every board first; auto-disable degraded ones so the fetch loop
    # doesn't waste a slot on a known-dead slug. Probe is cheap (parallel
    # GETs, ~1s wall time for ~30 boards) and writes JobSource.last_run_error.
    from app.services.jobs_sources.probe import probe_all
    probe_results = {}
    try:
        probe_results = await probe_all()
    except Exception as exc:
        logger.warning("probe pass failed (continuing with fetch): %s", exc)
    disabled_keys = {k for k, v in probe_results.items() if not v.get("enabled", True)}
    if disabled_keys:
        logger.info("skipping %d disabled boards: %s", len(disabled_keys), sorted(disabled_keys))

    stats = {"fetched": 0, "new": 0, "changed": 0, "unchanged": 0,
             "skipped": 0, "errors": 0, "disabled_skipped": len(disabled_keys)}

    fetchers = [
        ("greenhouse", GREENHOUSE_BOARDS, gh_fetch_all),
        ("lever", LEVER_BOARDS, lv_fetch_all),
        ("ashby", ASHBY_BOARDS, ash_fetch_all),
    ]
    sem = asyncio.Semaphore(ENRICH_CONCURRENCY)

    # Group fetched jobs per source so we can apply the cap to genuinely NEW
    # rows only (unchanged/existing rows are cheap — no enrichment call).
    by_source: dict[str, list[RawJob]] = {}
    for _kind, _boards, fetch in fetchers:
        async for source_key, raw in fetch():
            if source_key in disabled_keys:
                continue
            stats["fetched"] += 1
            by_source.setdefault(source_key, []).append(raw)

    async def _process(raw: RawJob, source_key: str, new_budget: list[int]) -> str | None:
        # Skip enrichment entirely if this row already exists unchanged.
        async with _db.async_session_factory() as db:
            job_hash = compute_hash(raw)
            existing = (await db.execute(
                select(Job).where(Job.source == source_key, Job.external_id == raw["external_id"])
            )).scalar_one_or_none()
            if existing and existing.hash == job_hash:
                return "unchanged"

        # Genuinely new or changed — respect the per-source budget.
        if new_budget[0] <= 0:
            return "deferred"
        new_budget[0] -= 1
        async with sem:
            return await _stage_with_retry(raw, source_key)

    stats["deferred"] = 0
    for source_key, rows in by_source.items():
        budget = [PER_SOURCE_NEW_CAP]
        # Process serially by source so cap logic stays deterministic, but
        # enrichment itself is parallel via the semaphore inside _stage.
        tasks = [asyncio.create_task(_process(r, source_key, budget)) for r in rows]
        for t in asyncio.as_completed(tasks):
            try:
                result = await t
                if result is None:
                    continue
                key = "skipped" if result == "skipped_blocked" else result
                stats[key] = stats.get(key, 0) + 1
            except Exception as exc:
                logger.exception("ingest error in %s: %s", source_key, exc)
                stats["errors"] += 1

    # Auto-expire pass: published jobs whose external_id vanished from the
    # source feed for N consecutive runs. Guards against mass-expire on a
    # transient source outage by only inspecting boards that returned ≥1 row.
    stats["auto_expired"] = 0
    await _auto_expire_missing(by_source, stats)
    # Date-based: flip published rows whose valid_through has elapsed.
    await _auto_expire_past_valid_through(stats)

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
