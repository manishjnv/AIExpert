"""Admin router for AI Jobs review queue.

Mounted at /admin/jobs. Requires get_current_admin. See docs/JOBS.md §10.

Actions:
  - list / filter the queue (draft / published / rejected / expired)
  - read one job detail
  - publish, reject (with reason), bulk-publish (Tier-1 only)
  - trigger ingest on-demand
  - edit core fields (valid_through, designation, slug) for admin corrections
"""

from __future__ import annotations

from datetime import date
from html import escape as esc
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_admin
from app.config import get_settings
from app.db import get_db
from app.models import Job, JobCompany, JobSource
from app.models.user import User
from app.services.indexnow import ping_async

router = APIRouter()

VALID_REJECT_REASONS = {"fake", "expired", "off_topic", "duplicate", "low_quality"}
VALID_STATUS_FILTER = {"draft", "published", "rejected", "expired", "all"}


def _ping_indexnow(slugs: list[str]) -> None:
    settings = get_settings()
    base = (settings.public_base_url or "").rstrip("/")
    if not base or not slugs:
        return
    ping_async([f"{base}/jobs/{s}" for s in slugs])


def _check_origin(request: Request) -> None:
    origin = request.headers.get("origin") or request.headers.get("referer", "")
    host = request.headers.get("host", "")
    if origin and host and host not in origin:
        raise HTTPException(status_code=403, detail="Origin mismatch")


def _serialize(job: Job) -> dict[str, Any]:
    # Derive "has_summary" + "summary_version" so the queue row can show a
    # Missing-summary chip and a prompt-version stamp without the frontend
    # having to peek into job.data.summary._meta itself.
    summary = (job.data or {}).get("summary") or {}
    has_summary = bool(
        summary.get("headline_chips") or summary.get("responsibilities")
        or summary.get("must_haves") or summary.get("benefits")
    )
    summary_version = None
    if has_summary and isinstance(summary.get("_meta"), dict):
        summary_version = summary["_meta"].get("prompt_version")
    return {
        "id": job.id,
        "slug": job.slug,
        "source": job.source,
        "external_id": job.external_id,
        "source_url": job.source_url,
        "status": job.status,
        "reject_reason": job.reject_reason,
        "posted_on": job.posted_on.isoformat() if job.posted_on else None,
        "valid_through": job.valid_through.isoformat() if job.valid_through else None,
        "last_reviewed_on": job.last_reviewed_on.isoformat() if job.last_reviewed_on else None,
        "last_reviewed_by": job.last_reviewed_by,
        "title": job.title,
        "company_slug": job.company_slug,
        "designation": job.designation,
        "country": job.country,
        "remote_policy": job.remote_policy,
        "verified": bool(job.verified),
        "admin_notes": job.admin_notes,
        "hash": job.hash,
        "has_summary": has_summary,
        "summary_version": summary_version,
        "data": job.data,
    }


# ---- JSON API ---------------------------------------------------------------

@router.get("/api/queue")
async def list_queue(
    status: str = Query("draft"),
    source: str | None = None,
    company: str | None = None,
    designation: str | None = None,
    country: str | None = None,
    city: str | None = None,
    remote: str | None = None,
    verified_only: bool = False,
    expired_reason: str | None = None,
    flag: str | None = None,
    q: str | None = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    if status not in VALID_STATUS_FILTER:
        raise HTTPException(400, "invalid status")
    stmt = select(Job)
    if status != "all":
        stmt = stmt.where(Job.status == status)
    if source:
        stmt = stmt.where(Job.source == source)
    if company:
        stmt = stmt.where(Job.company_slug == company.lower())
    if designation:
        stmt = stmt.where(Job.designation == designation)
    if country:
        stmt = stmt.where(Job.country == country.upper())
    if city:
        stmt = stmt.where(
            func.lower(func.json_extract(Job.data, "$.location.city")) == city.strip().lower()
        )
    if remote:
        stmt = stmt.where(Job.remote_policy == remote)
    if verified_only:
        stmt = stmt.where(Job.verified == 1)
    # Quick-filters on admin_notes surface flag.
    if flag == "non_ai":
        stmt = stmt.where(Job.admin_notes.like("auto-skipped%"))
    elif flag == "tier2_lite":
        stmt = stmt.where(Job.admin_notes.like("tier2-lite%"))
    elif flag == "enrichment_failed":
        stmt = stmt.where(Job.admin_notes.like("enrichment failed%"))
    elif flag == "no_summary":
        # json_extract returns SQL NULL for a missing path, so IS NULL
        # catches both "no summary key" and "summary: null".
        stmt = stmt.where(func.json_extract(Job.data, "$.summary.headline_chips").is_(None))
    # Sub-filter on Expired tab: distinguish auto-expired (source_removed) from
    # date-based (posted_on+45d) and admin-rejected-as-expired.
    if expired_reason:
        reason_expr = func.json_extract(Job.data, "$._meta.expired_reason")
        if expired_reason == "source_removed":
            stmt = stmt.where(reason_expr == "source_removed")
        elif expired_reason == "date_based":
            stmt = stmt.where(reason_expr.is_(None))
    if q:
        from sqlalchemy import or_
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Job.title).like(like),
                              func.lower(Job.company_slug).like(like)))
    stmt = stmt.order_by(Job.posted_on.desc(), Job.id.desc()).offset(offset).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    # Counters for the admin banner.
    counts_stmt = select(Job.status, func.count(Job.id)).group_by(Job.status)
    counts = {s: n for s, n in (await db.execute(counts_stmt)).all()}

    # Auto-expired in last 24h — feeds the "auto-expired: N" chip on the stats strip.
    from datetime import datetime, timedelta
    cutoff = datetime.utcnow() - timedelta(hours=24)
    auto_expired_24h = (await db.execute(
        select(func.count(Job.id)).where(
            Job.status == "expired",
            Job.updated_at >= cutoff,
            func.json_extract(Job.data, "$._meta.expired_reason") == "source_removed",
        )
    )).scalar() or 0

    # Missing-streak counters: published jobs at risk of auto-expiry.
    streak_expr = func.json_extract(Job.data, "$._meta.missing_streak")
    missing_streak_1 = (await db.execute(
        select(func.count(Job.id)).where(
            Job.status == "published",
            streak_expr == 1,
        )
    )).scalar() or 0
    missing_streak_2 = (await db.execute(
        select(func.count(Job.id)).where(
            Job.status == "published",
            streak_expr >= 2,
        )
    )).scalar() or 0

    # Duplicate detection — hashes that appear in multiple Job rows.
    # Surfaces near-identical postings (same title+company+JD) across sources
    # or re-ingested rows. Query is cheap because `hash` is indexed.
    dup_hashes: set[str] = set()
    hashes = [r.hash for r in rows if r.hash]
    if hashes:
        dup_stmt = (
            select(Job.hash, func.count(Job.id))
            .where(Job.hash.in_(hashes))
            .group_by(Job.hash)
            .having(func.count(Job.id) > 1)
        )
        dup_hashes = {h for h, _ in (await db.execute(dup_stmt)).all()}

    return {
        "items": [_serialize(j) for j in rows],
        "counts": counts,
        "auto_expired_24h": auto_expired_24h,
        "missing_streak_1": missing_streak_1,
        "missing_streak_2": missing_streak_2,
        "duplicate_hashes": list(dup_hashes),
    }


@router.get("/api/{job_id:int}")
async def get_one(
    job_id: int,
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
    if not job:
        raise HTTPException(404, "not found")
    return _serialize(job)


@router.post("/api/{job_id}/publish")
async def publish(
    job_id: int,
    request: Request,
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    _check_origin(request)
    job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
    if not job:
        raise HTTPException(404, "not found")
    job.status = "published"
    job.reject_reason = None
    job.last_reviewed_on = date.today()
    job.last_reviewed_by = _admin.name or _admin.email
    # Source stats.
    src = (await db.execute(select(JobSource).where(JobSource.key == job.source))).scalar_one_or_none()
    if src:
        src.total_published = (src.total_published or 0) + 1
    await db.commit()
    _ping_indexnow([job.slug])
    return {"ok": True, "status": job.status}


@router.post("/api/{job_id}/reject")
async def reject(
    job_id: int,
    payload: dict,
    request: Request,
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    _check_origin(request)
    reason = (payload or {}).get("reason")
    if reason not in VALID_REJECT_REASONS:
        raise HTTPException(400, f"reason must be one of {sorted(VALID_REJECT_REASONS)}")
    job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
    if not job:
        raise HTTPException(404, "not found")
    job.status = "rejected"
    job.reject_reason = reason
    job.last_reviewed_on = date.today()
    job.last_reviewed_by = _admin.name or _admin.email
    src = (await db.execute(select(JobSource).where(JobSource.key == job.source))).scalar_one_or_none()
    if src:
        src.total_rejected = (src.total_rejected or 0) + 1
    await db.commit()
    return {"ok": True, "status": job.status, "reason": reason}


@router.post("/api/bulk-publish")
async def bulk_publish(
    payload: dict,
    request: Request,
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    _check_origin(request)
    ids = (payload or {}).get("ids") or []
    if not isinstance(ids, list) or not ids or not all(isinstance(i, int) for i in ids):
        raise HTTPException(400, "ids must be a non-empty int list")
    if len(ids) > 100:
        raise HTTPException(400, "max 100 per bulk action (see docs/JOBS.md §10.7)")

    rows = (await db.execute(select(Job).where(Job.id.in_(ids)))).scalars().all()
    by_source = {r.source for r in rows}
    sources = {s.key: s for s in (await db.execute(select(JobSource).where(JobSource.key.in_(by_source)))).scalars().all()}

    # Enforce bulk-approve only on Tier-1 sources with bulk_approve=1.
    blocked = [r.id for r in rows if not (sources.get(r.source) and sources[r.source].tier == 1 and sources[r.source].bulk_approve)]
    if blocked:
        raise HTTPException(400, f"bulk_approve not permitted for jobs: {blocked}")

    reviewer = _admin.name or _admin.email
    today = date.today()
    for r in rows:
        r.status = "published"
        r.reject_reason = None
        r.last_reviewed_on = today
        r.last_reviewed_by = reviewer
        src = sources.get(r.source)
        if src:
            src.total_published = (src.total_published or 0) + 1
    await db.commit()
    _ping_indexnow([r.slug for r in rows])
    return {"ok": True, "published": len(rows)}


@router.post("/api/ingest/run")
async def run_ingest_now(
    request: Request,
    _admin: User = Depends(get_current_admin),
):
    _check_origin(request)
    from app.services.jobs_ingest import run_daily_ingest
    stats = await run_daily_ingest()
    return {"ok": True, "stats": stats}


@router.get("/api/stats")
async def stats(
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Per-source stats: last 24h + 45d publish_rate + top reject reasons."""
    from datetime import datetime, timedelta
    cutoff_24h = datetime.utcnow() - timedelta(hours=24)
    cutoff_45d = datetime.utcnow() - timedelta(days=45)

    srcs = (await db.execute(select(JobSource).order_by(JobSource.tier, JobSource.key))).scalars().all()

    # 24h rolling bucket per status.
    recent_stmt = (
        select(Job.source, Job.status, func.count(Job.id))
        .where(Job.updated_at >= cutoff_24h)
        .group_by(Job.source, Job.status)
    )
    recent: dict[str, dict[str, int]] = {}
    for src, status, n in (await db.execute(recent_stmt)).all():
        recent.setdefault(src, {})[status] = n

    # 45d publish-rate bucket — quality signal (#6). Low rate = extractor is
    # emitting roles reviewers consistently reject. Publish_rate = pub / (pub + rej).
    quality_stmt = (
        select(Job.source, Job.status, func.count(Job.id))
        .where(Job.updated_at >= cutoff_45d,
               Job.status.in_(["published", "rejected"]))
        .group_by(Job.source, Job.status)
    )
    quality: dict[str, dict[str, int]] = {}
    for src, status, n in (await db.execute(quality_stmt)).all():
        quality.setdefault(src, {})[status] = n

    # Top 3 reject reasons per source over the same 45d window — feeds the
    # admin "why is this source noisy" diagnosis without opening the DB.
    reasons_stmt = (
        select(Job.source, Job.reject_reason, func.count(Job.id))
        .where(Job.updated_at >= cutoff_45d,
               Job.status == "rejected",
               Job.reject_reason.is_not(None))
        .group_by(Job.source, Job.reject_reason)
    )
    reasons_raw: dict[str, list[tuple[str, int]]] = {}
    for src, reason, n in (await db.execute(reasons_stmt)).all():
        reasons_raw.setdefault(src, []).append((reason, n))
    top_reasons: dict[str, list[dict]] = {
        src: [{"reason": r, "count": n}
              for r, n in sorted(rs, key=lambda x: -x[1])[:3]]
        for src, rs in reasons_raw.items()
    }

    out = []
    for s in srcs:
        r = recent.get(s.key, {})
        q = quality.get(s.key, {})
        pub_45 = q.get("published", 0)
        rej_45 = q.get("rejected", 0)
        total_45 = pub_45 + rej_45
        publish_rate = round(pub_45 / total_45, 2) if total_45 else None
        out.append({
            "key": s.key, "label": s.label, "tier": s.tier,
            "enabled": bool(s.enabled),
            "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
            "recent_draft": r.get("draft", 0),
            "recent_published": r.get("published", 0),
            "recent_rejected": r.get("rejected", 0),
            "publish_rate_45d": publish_rate,     # null when no reviewed rows yet
            "published_45d": pub_45,
            "rejected_45d": rej_45,
            "top_reject_reasons_45d": top_reasons.get(s.key, []),
            "total_published": s.total_published,
            "total_rejected": s.total_rejected,
            "error": s.last_run_error,
        })
    return {"sources": out}


@router.get("/api/summary-stats")
async def summary_stats(
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Observability for the /summarize-jobs pipeline.
    Reports per-status coverage, prompt-version distribution, and 7-day
    generation rate so admins can spot drift before publishing.
    """
    summary_expr = func.json_extract(Job.data, "$.summary.headline_chips")
    version_expr = func.json_extract(Job.data, "$.summary._meta.prompt_version")
    generated_expr = func.json_extract(Job.data, "$.summary._meta.generated_at")

    # Coverage by status: total vs has-summary.
    total_by_status = {
        s: n for s, n in (await db.execute(
            select(Job.status, func.count(Job.id)).group_by(Job.status)
        )).all()
    }
    with_summary_by_status = {
        s: n for s, n in (await db.execute(
            select(Job.status, func.count(Job.id))
            .where(summary_expr.is_not(None))
            .group_by(Job.status)
        )).all()
    }
    coverage = []
    for s in ("draft", "published", "rejected", "expired"):
        total = total_by_status.get(s, 0)
        with_s = with_summary_by_status.get(s, 0)
        coverage.append({
            "status": s,
            "total": total,
            "with_summary": with_s,
            "missing": max(0, total - with_s),
            "coverage_pct": round(100 * with_s / total) if total else None,
        })

    # Prompt-version distribution across every summarized job.
    versions = [
        {"version": v or "unknown", "count": n}
        for v, n in (await db.execute(
            select(version_expr, func.count(Job.id))
            .where(summary_expr.is_not(None))
            .group_by(version_expr)
            .order_by(func.count(Job.id).desc())
        )).all()
    ]

    # Generation rate: count summaries whose generated_at falls in the last 7d.
    from datetime import datetime, timedelta
    cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat(timespec="seconds")
    generated_last_7d = (await db.execute(
        select(func.count(Job.id)).where(
            summary_expr.is_not(None),
            generated_expr >= cutoff,
        )
    )).scalar() or 0

    return {
        "coverage": coverage,
        "versions": versions,
        "generated_last_7d": generated_last_7d,
    }


@router.post("/api/sources/probe")
async def probe_sources(
    request: Request,
    _admin: User = Depends(get_current_admin),
):
    """Run an on-demand liveness probe across every configured source board.
    Auto-disables boards failing 3+ runs in a row (see services/jobs_sources/probe.py)."""
    _check_origin(request)
    from app.services.jobs_sources.probe import probe_all
    results = await probe_all()
    summary = {
        "total": len(results),
        "ok": sum(1 for v in results.values() if v.get("ok")),
        "failing": sum(1 for v in results.values() if not v.get("ok")),
        "disabled": sum(1 for v in results.values() if not v.get("enabled", True)),
    }
    return {"summary": summary, "results": results}


@router.get("/api/sources")
async def list_sources(
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(select(JobSource).order_by(JobSource.tier, JobSource.key))).scalars().all()
    return {"items": [
        {
            "key": s.key, "kind": s.kind, "label": s.label,
            "tier": s.tier, "enabled": bool(s.enabled), "bulk_approve": bool(s.bulk_approve),
            "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
            "last_run_fetched": s.last_run_fetched, "last_run_new": s.last_run_new,
            "last_run_error": s.last_run_error,
            "total_published": s.total_published, "total_rejected": s.total_rejected,
        } for s in rows
    ]}


@router.post("/api/companies/{slug}/blocklist")
async def blocklist_company(
    slug: str,
    payload: dict,
    request: Request,
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    _check_origin(request)
    co = (await db.execute(select(JobCompany).where(JobCompany.slug == slug))).scalar_one_or_none()
    if not co:
        raise HTTPException(404, "company not found")
    co.blocklisted = 1 if (payload or {}).get("blocked", True) else 0
    co.blocklist_reason = (payload or {}).get("reason")
    await db.commit()
    return {"ok": True, "slug": slug, "blocklisted": bool(co.blocklisted)}


# ---- HTML review page -------------------------------------------------------

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def review_page(_admin: User = Depends(get_current_admin)) -> HTMLResponse:
    # Minimal shell — all data loaded via /admin/jobs/api/queue. Keeps this file
    # small; heavy UI can move to a static template later.
    return HTMLResponse(_ADMIN_HTML)


_ADMIN_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Jobs Review — Admin</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:wght@400;500;700&family=IBM+Plex+Sans:wght@400;500&family=IBM+Plex+Mono:wght@400&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/nav.css">
<style>
  :root{color-scheme:dark}
  html,body{margin:0;background:#0f1419;color:#e8e4d8;font-family:'IBM Plex Sans',system-ui,sans-serif;line-height:1.6}
  main{max-width:1280px;margin:0 auto;padding:32px 24px 80px}
  .page-eyebrow{font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:#e8a849;margin-bottom:8px}
  h1.page-title{font-family:'Fraunces',Georgia,serif;font-size:clamp(26px,3.5vw,36px);line-height:1.15;color:#f5f1e8;margin:0 0 14px;font-weight:500}
  .banner{padding:12px 18px;background:#1a2029;border:1px solid rgba(232,168,73,.35);border-radius:6px;margin-bottom:16px;color:#e8e4d8;font-size:14px}
  .banner b{color:#e8a849;font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.12em;text-transform:uppercase;margin-right:8px}
  .tabs{display:flex;gap:8px;margin:16px 0;flex-wrap:wrap}
  .tabs button{padding:7px 14px;border:1px solid #2a323d;background:transparent;color:#c0c4cc;cursor:pointer;border-radius:4px;font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.1em;text-transform:uppercase}
  .tabs button:hover{border-color:#e8a849;color:#e8a849}
  .tabs button.active{background:#e8a849;color:#0f1419;border-color:#e8a849;font-weight:500}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th,td{padding:10px 12px;border-bottom:1px solid #2a323d;text-align:left;vertical-align:top}
  th{background:#1a2029;font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:#94a3b8;font-weight:500}
  td{color:#e8e4d8}
  td b{color:#f5f1e8;font-family:'Fraunces',Georgia,serif;font-weight:500;font-size:15px}
  .btn{padding:6px 12px;border:1px solid #2a323d;background:transparent;color:#c0c4cc;cursor:pointer;border-radius:3px;font-size:12px;font-family:'IBM Plex Mono',monospace;letter-spacing:.08em}
  .btn:hover{border-color:#e8a849;color:#e8a849}
  .btn.primary{background:#e8a849;color:#0f1419;border-color:#e8a849;font-weight:500}
  .btn.primary:hover{background:#f0b968;color:#0f1419}
  .btn.danger{background:transparent;color:#d97757;border-color:#d97757}
  .btn.danger:hover{background:rgba(217,119,87,.1)}
  .chip{display:inline-block;padding:2px 8px;border-radius:3px;font-size:10px;font-family:'IBM Plex Mono',monospace;letter-spacing:.06em;text-transform:uppercase;background:#1a2029;color:#c0c4cc;border:1px solid #2a323d;margin-right:4px}
  .chip.verified{background:rgba(232,168,73,.12);color:#e8a849;border-color:rgba(232,168,73,.4)}
  .chip.tier1{background:rgba(109,181,133,.12);color:#6db585;border-color:rgba(109,181,133,.4);font-weight:600}
  .chip.tier2{background:rgba(148,163,184,.08);color:#94a3b8;border-color:rgba(148,163,184,.3)}
  .chip.flag-nonai{background:rgba(217,119,87,.15);color:#d97757;border-color:rgba(217,119,87,.5);font-weight:600}
  .chip.flag-lite{background:rgba(232,168,73,.1);color:#e8a849;border-color:rgba(232,168,73,.3)}
  .chip.flag-dup{background:rgba(217,119,87,.15);color:#d97757;border-color:rgba(217,119,87,.5);font-weight:600}
  .chip.flag-fail{background:rgba(195,51,51,.15);color:#d97757;border-color:rgba(195,51,51,.5)}
  .chip.flag-nosummary{background:rgba(217,119,87,.15);color:#d97757;border-color:rgba(217,119,87,.5);font-weight:600}
  .chip.version{background:transparent;color:#6a7280;border-color:#2a323d;font-size:9px;letter-spacing:.04em}
  .qtoggles{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0 0}
  .qtoggle{padding:5px 10px;border:1px solid #2a323d;background:transparent;color:#c0c4cc;cursor:pointer;border-radius:3px;font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:.08em;text-transform:uppercase}
  .qtoggle:hover{border-color:#e8a849;color:#e8a849}
  .qtoggle.active{background:#e8a849;color:#0f1419;border-color:#e8a849;font-weight:600}
  .tldr{color:#94a3b8;font-size:13px;max-width:480px;margin-top:6px}
  .stats{margin:16px 0;background:#1a2029;border:1px solid #2a323d;border-radius:6px;padding:10px 16px;font-size:12px}
  .stats summary{cursor:pointer;font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:#e8a849}
  .stats table{margin-top:10px}
  .stats .err{color:#d97757;font-weight:600;font-size:10px;font-family:'IBM Plex Mono',monospace;letter-spacing:.06em}
  details{margin:6px 0}
  details summary{cursor:pointer;color:#e8a849;font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.08em}
  pre{background:#0f1419;border:1px solid #2a323d;color:#c0c4cc;padding:12px;border-radius:4px;max-height:320px;overflow:auto;font-size:11px;font-family:'IBM Plex Mono',monospace}
  a{color:#e8a849}
  input[type=checkbox]{accent-color:#e8a849}
  .qfilters{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:12px 0;padding:12px 16px;background:#1a2029;border:1px solid #2a323d;border-radius:6px}
  .qfilters input,.qfilters select{padding:6px 10px;font-size:12px;background:#0f1419;color:#e8e4d8;border:1px solid #2a323d;border-radius:3px;font-family:'IBM Plex Sans',sans-serif}
  .qfilters input:focus,.qfilters select:focus{outline:none;border-color:#e8a849}
  .qfilters label{font-size:11px;font-family:'IBM Plex Mono',monospace;letter-spacing:.08em;color:#94a3b8;text-transform:uppercase;display:flex;align-items:center;gap:6px;cursor:pointer}
  .qfilters .pill-count{margin-left:auto;font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.08em;color:#e8a849}
</style>
</head><body>
<main>
<div class="page-eyebrow">AutomateEdge · Admin</div>
<h1 class="page-title">Jobs Review Queue</h1>
<div id="banner" class="banner">Loading…</div>
<details class="stats" id="stats"><summary>Source stats (last 24h)</summary><div id="stats-body">Loading…</div></details>
<details class="stats" id="sumstats"><summary>Summary-card pipeline (coverage · versions · 7d rate)</summary><div id="sumstats-body">Loading…</div></details>
<div class="tabs">
  <button data-status="draft" class="active">Draft</button>
  <button data-status="published">Published</button>
  <button data-status="rejected">Rejected</button>
  <button data-status="expired">Expired</button>
  <button data-status="all">All</button>
  <button id="run-ingest" style="margin-left:auto" class="btn primary">Run ingest now</button>
</div>

<div class="qfilters">
  <input id="qf-q" type="search" placeholder="Search title or company…" style="min-width:220px">
  <select id="qf-company"><option value="">Any company</option></select>
  <select id="qf-designation">
    <option value="">Any designation</option>
    <option>ML Engineer</option><option>Research Scientist</option>
    <option>Applied Scientist</option><option>Data Scientist</option>
    <option>Data Engineer</option><option>MLOps Engineer</option>
    <option>AI Engineer</option><option>AI Product Manager</option>
    <option>Research Engineer</option><option>Computer Vision Engineer</option>
    <option>NLP Engineer</option><option>Prompt Engineer</option>
    <option>AI Solutions Architect</option><option>AI Developer Advocate</option>
    <option>Other</option>
  </select>
  <select id="qf-remote">
    <option value="">Any workplace</option>
    <option>Remote</option><option>Hybrid</option><option>Onsite</option>
  </select>
  <select id="qf-country" style="min-width:140px"><option value="">Any country</option></select>
  <select id="qf-city" style="min-width:160px"><option value="">Any city</option></select>
  <label><input id="qf-verified" type="checkbox"> Verified only</label>
  <select id="qf-expired-reason" style="display:none">
    <option value="">Any expiry reason</option>
    <option value="source_removed">Auto-expired (source removed)</option>
    <option value="date_based">Date-based (45d)</option>
  </select>
  <button class="btn" id="qf-clear">Clear</button>
  <span class="pill-count" id="qf-count"></span>
  <div class="qtoggles" style="flex-basis:100%">
    <button class="qtoggle" data-flag="" data-verified="1">Tier-1 only</button>
    <button class="qtoggle" data-flag="non_ai">⚠ Non-AI (auto-skipped)</button>
    <button class="qtoggle" data-flag="tier2_lite">Tier-2 lite</button>
    <button class="qtoggle" data-flag="enrichment_failed">Enrichment failed</button>
    <button class="qtoggle" data-flag="no_summary">⚠ Missing summary</button>
  </div>
</div>

<div id="list">Loading…</div>

<script>
const REJECT_REASONS = ["fake","expired","off_topic","duplicate","low_quality"];
let currentStatus = "draft";
let currentFlag = "";           // quick-filter: "", "non_ai", "tier2_lite", "enrichment_failed"
let duplicateHashes = new Set(); // hashes appearing in 2+ jobs — flagged with a dup chip

function qfilterParams() {
  const p = new URLSearchParams();
  p.set("status", currentStatus);
  p.set("limit", "200");
  const q = document.getElementById("qf-q").value.trim();
  const co = document.getElementById("qf-company").value.trim();
  const des = document.getElementById("qf-designation").value.trim();
  const rem = document.getElementById("qf-remote").value.trim();
  const ctry = document.getElementById("qf-country").value.trim();
  const city = document.getElementById("qf-city").value.trim();
  const ver = document.getElementById("qf-verified").checked;
  if (q) p.set("q", q);
  if (co) p.set("company", co);
  if (des) p.set("designation", des);
  if (rem) p.set("remote", rem);
  if (ctry) p.set("country", ctry);
  if (city) p.set("city", city);
  if (ver) p.set("verified_only", "true");
  const expReason = document.getElementById("qf-expired-reason").value.trim();
  if (expReason && currentStatus === "expired") p.set("expired_reason", expReason);
  if (currentFlag) p.set("flag", currentFlag);
  return p.toString();
}

async function load() {
  const r = await fetch(`/admin/jobs/api/queue?${qfilterParams()}`, {credentials:"include"});
  if (!r.ok) { document.getElementById("list").innerText = "Load failed: " + r.status; return; }
  const data = await r.json();
  const counts = data.counts || {};
  const autoExp = data.auto_expired_24h || 0;
  const streak1 = data.missing_streak_1 || 0;
  const streak2 = data.missing_streak_2 || 0;
  const autoChip = autoExp ? ` · <span style="color:#e8a849">auto-expired 24h: ${autoExp}</span>` : "";
  const streakChip = (streak1 || streak2) ? ` · <span style="color:#e07a5f" title="Published jobs missing from source feed. Streak 1 = missed 1 run (at risk). Streak 2+ = will expire next run.">⚠ streak-1: ${streak1} · streak-2+: ${streak2}</span>` : "";
  document.getElementById("banner").innerHTML =
    `<b>Queue:</b> ${counts.draft||0} draft · ${counts.published||0} published · ${counts.rejected||0} rejected · ${counts.expired||0} expired${autoChip}${streakChip}`;
  document.getElementById("qf-expired-reason").style.display = (currentStatus === "expired") ? "" : "none";
  document.getElementById("qf-count").textContent = `${data.items.length} shown`;
  duplicateHashes = new Set(data.duplicate_hashes || []);
  populateCompanyDropdown(data.items);
  populateLocationDropdowns(data.items);
  renderList(data.items);
  loadStats();
  loadSummaryStats();
}

function populateCompanyDropdown(items) {
  const sel = document.getElementById("qf-company");
  if (sel.options.length > 1) return;   // only seed once from the first load
  const slugs = [...new Set(items.map(j => j.company_slug).filter(Boolean))].sort();
  for (const s of slugs) {
    const opt = document.createElement("option");
    opt.value = s; opt.textContent = s;
    sel.appendChild(opt);
  }
}

// ISO-2 → friendly name. Extend as new source boards are added.
const COUNTRY_NAMES = {
  IN:"India", US:"United States", GB:"United Kingdom", CA:"Canada",
  DE:"Germany", FR:"France", NL:"Netherlands", IE:"Ireland",
  SG:"Singapore", AU:"Australia", JP:"Japan", CH:"Switzerland",
  IL:"Israel", ES:"Spain", IT:"Italy", SE:"Sweden", PL:"Poland",
  BR:"Brazil", MX:"Mexico", AE:"UAE", KR:"South Korea", HK:"Hong Kong",
};

function populateLocationDropdowns(items) {
  const selCountry = document.getElementById("qf-country");
  const selCity = document.getElementById("qf-city");
  if (selCountry.options.length <= 1) {
    const codes = [...new Set(items.map(j => j.country).filter(Boolean))].sort();
    for (const c of codes) {
      const opt = document.createElement("option");
      opt.value = c;
      opt.textContent = COUNTRY_NAMES[c] ? `${COUNTRY_NAMES[c]} (${c})` : c;
      selCountry.appendChild(opt);
    }
  }
  if (selCity.options.length <= 1) {
    const cities = [...new Set(items.map(j => (j.data && j.data.location && j.data.location.city) || null).filter(Boolean))].sort();
    for (const c of cities) {
      const opt = document.createElement("option");
      opt.value = c; opt.textContent = c;
      selCity.appendChild(opt);
    }
  }
}

async function loadSummaryStats() {
  try {
    const r = await fetch("/admin/jobs/api/summary-stats", {credentials:"include"});
    if (!r.ok) return;
    const data = await r.json();
    const covRows = (data.coverage || []).map(c => {
      const pct = c.coverage_pct;
      const color = pct === null ? '#94a3b8' : pct >= 95 ? '#6db585' : pct >= 70 ? '#e8a849' : '#d97757';
      const pctTxt = pct === null ? '—' : `${pct}%`;
      return `<tr><td>${esc(c.status)}</td><td>${c.total}</td><td>${c.with_summary}</td>
        <td style="color:${color};font-weight:600">${c.missing}</td>
        <td style="color:${color};font-family:'IBM Plex Mono',monospace">${pctTxt}</td></tr>`;
    }).join("");
    const verRows = (data.versions || []).map(v =>
      `<tr><td style="font-family:'IBM Plex Mono',monospace">${esc(v.version)}</td><td>${v.count}</td></tr>`
    ).join("");
    document.getElementById("sumstats-body").innerHTML = `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:8px">
        <div>
          <div style="color:#94a3b8;font-size:11px;font-family:'IBM Plex Mono',monospace;letter-spacing:.08em;margin-bottom:6px">COVERAGE BY STATUS</div>
          <table><thead><tr><th>Status</th><th>Total</th><th>With</th><th>Missing</th><th>%</th></tr></thead><tbody>${covRows}</tbody></table>
        </div>
        <div>
          <div style="color:#94a3b8;font-size:11px;font-family:'IBM Plex Mono',monospace;letter-spacing:.08em;margin-bottom:6px">PROMPT VERSION DISTRIBUTION</div>
          <table><thead><tr><th>Version</th><th>Count</th></tr></thead><tbody>${verRows || '<tr><td colspan=2>—</td></tr>'}</tbody></table>
          <div style="margin-top:12px;color:#94a3b8;font-size:12px">Generated last 7 days: <b style="color:#e8a849;font-family:'IBM Plex Mono',monospace">${data.generated_last_7d || 0}</b></div>
        </div>
      </div>`;
  } catch(_) {}
}

async function loadStats() {
  try {
    const r = await fetch("/admin/jobs/api/stats", {credentials:"include"});
    if (!r.ok) return;
    const data = await r.json();
    const rows = (data.sources || []).map(s => {
      const tot = s.recent_draft + s.recent_published + s.recent_rejected;
      const err = s.error ? `<span class="err">ERR</span>` : "";
      const stale = !s.last_run_at || (Date.now() - new Date(s.last_run_at).getTime() > 36*3600*1000);
      const staleTag = stale ? `<span class="err">stale</span>` : "";
      // 45d publish-rate signal — green >=0.5, amber 0.2-0.5, red <0.2, grey if no data.
      const pr = s.publish_rate_45d;
      let prChip = '<span style="color:#94a3b8">—</span>';
      if (pr !== null && pr !== undefined) {
        const color = pr >= 0.5 ? '#6db585' : pr >= 0.2 ? '#e8a849' : '#d27d6e';
        prChip = `<span style="color:${color};font-family:'IBM Plex Mono',monospace;font-size:11px" title="${s.published_45d} published / ${s.rejected_45d} rejected · top: ${(s.top_reject_reasons_45d||[]).map(r=>r.reason+'('+r.count+')').join(', ')||'none'}">${Math.round(pr*100)}%</span>`;
      }
      return `<tr>
        <td>${esc(s.label)}</td><td>T${s.tier}</td>
        <td>${tot}</td><td>${s.recent_draft}</td><td>${s.recent_published}</td><td>${s.recent_rejected}</td>
        <td>${prChip}</td>
        <td>${s.last_run_at ? esc(s.last_run_at.slice(0,16).replace('T',' ')) : '—'} ${staleTag}</td>
        <td>${err}</td>
      </tr>`;
    }).join("");
    document.getElementById("stats-body").innerHTML = rows
      ? `<table><thead><tr><th>Source</th><th>Tier</th><th>24h</th><th>Draft</th><th>Pub</th><th>Rej</th><th title="Published / (Published+Rejected) over last 45d — low = extractor emitting noise">Publish-rate 45d</th><th>Last run (UTC)</th><th></th></tr></thead><tbody>${rows}</tbody></table>`
      : "<p>No sources configured yet.</p>";
  } catch(_) {}
}

function esc(s){return (s||"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}[c]))}

function renderList(items) {
  if (!items.length) { document.getElementById("list").innerHTML = "<p>Empty.</p>"; return; }
  const rows = items.map(j => {
    const d = j.data || {};
    const loc = d.location || {};
    const emp = d.employment || {};
    const locStr = [loc.city, loc.country, loc.remote_policy].filter(Boolean).join(" · ");
    const actions = j.status === "draft"
      ? `<button class="btn primary" onclick="pub(${j.id}, ${j.has_summary?1:0})">Publish</button>
         <button class="btn danger" onclick="rej(${j.id})">Reject</button>`
      : `<span>${esc(j.status)}${j.reject_reason?" ("+esc(j.reject_reason)+")":""}</span>`;
    const previewUrl = `/jobs/${encodeURIComponent(j.slug)}?preview=1`;
    // Derive surface flags (were previously buried inside Details).
    const notes = j.admin_notes || "";
    const isNonAI = notes.startsWith("auto-skipped");
    const isTier2Lite = notes.startsWith("tier2-lite");
    const isFailed = notes.startsWith("enrichment failed");
    const isDup = j.hash && duplicateHashes.has(j.hash);
    const tierChip = j.verified
      ? `<span class="chip tier1" title="Tier-1 verified AI-native company — bulk-approve eligible">T1</span>`
      : `<span class="chip tier2" title="Tier-2 aggregated source — individual review required">T2</span>`;
    const noSummary = !j.has_summary;
    const versionStamp = j.summary_version;
    const flagChips = [
      isNonAI ? `<span class="chip flag-nonai" title="Auto-skipped: title matched non-AI list (Sales/HR/Legal/etc). Reject off_topic unless false positive.">⚠ non-AI</span>` : "",
      isTier2Lite ? `<span class="chip flag-lite" title="Lightweight extraction — missing nice_to_have, modules, summary. Run /summarize-jobs --id ${j.id} before publish.">tier2-lite</span>` : "",
      isFailed ? `<span class="chip flag-fail" title="AI enrichment errored — minimal data only. Retry or reject low_quality.">enrich-failed</span>` : "",
      isDup ? `<span class="chip flag-dup" title="Another job has the same content hash (title+company+JD). Candidate for reject duplicate.">⚠ dup</span>` : "",
      noSummary ? `<span class="chip flag-nosummary" title="No Opus summary card yet — public page will render degraded. Run /summarize-jobs --id ${j.id} before publishing.">⚠ no-summary</span>` : "",
      versionStamp ? `<span class="chip version" title="Summary prompt version. Out-of-date summaries auto-surface when the prompt template is bumped.">v${esc(versionStamp)}</span>` : "",
    ].filter(Boolean).join("");
    return `<tr>
      <td><input type="checkbox" class="sel" value="${j.id}" ${j.status==='draft'?'':'disabled'}></td>
      <td>
        <a href="${previewUrl}" target="_blank" rel="noopener" style="color:#e8a849;text-decoration:none"><b>${esc(j.title)}</b></a>
        <a href="${previewUrl}" target="_blank" rel="noopener" class="btn" style="margin-left:8px;font-size:10px;padding:2px 8px">Preview ↗</a>
        ${tierChip}
        <span class="chip ${j.verified?'verified':''}">${esc(d.company?.name||j.company_slug)}</span>
        ${flagChips}<br>
        <span class="chip">${esc(j.designation)}</span>
        <span class="chip">${esc(locStr||'—')}</span>
        <span class="chip">${esc(emp.job_type||'—')}</span>
        <div class="tldr">${esc(d.tldr||'(no tldr — flag)')}</div>
        <details><summary>Details</summary>
          <div><b>Skills:</b> ${esc((d.must_have_skills||[]).join(", "))}</div>
          <div><b>Modules:</b> ${esc((d.roadmap_modules_matched||[]).join(", "))}</div>
          <div><b>Source:</b> ${esc(j.source)} · <a href="${esc(j.source_url)}" target="_blank" rel="noopener">Test apply link</a></div>
          ${j.admin_notes?`<div style="color:#c33"><b>Flag:</b> ${esc(j.admin_notes)}</div>`:""}
          <pre>${esc(JSON.stringify(d, null, 2))}</pre>
        </details>
      </td>
      <td>${esc(j.posted_on||'')}</td>
      <td>${actions}</td>
    </tr>`;
  }).join("");
  document.getElementById("list").innerHTML = `
    <div style="margin:.5rem 0">
      <button class="btn primary" onclick="bulkPub()">Bulk publish selected (Tier-1 only)</button>
    </div>
    <table>
      <thead><tr><th><input type="checkbox" onchange="toggleAll(this)"></th><th>Job</th><th>Posted</th><th></th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

async function pub(id, hasSummary) {
  // Guardrail: publishing without a summary renders a degraded public page
  // (tldr + skills fallback, no card). Warn before proceeding.
  if (!hasSummary && !confirm(
    "This job has no Opus summary card yet.\\n\\n" +
    "Publishing now will render a degraded public page (tldr + skills only, no summary card).\\n\\n" +
    "Recommended: run /summarize-jobs --id " + id + " first.\\n\\n" +
    "Publish anyway?"
  )) return;
  const r = await fetch(`/admin/jobs/api/${id}/publish`, {method:"POST", credentials:"include"});
  if (!r.ok) { alert("Failed: " + r.status); return; }
  load();
}

async function rej(id) {
  const reason = prompt("Reject reason (" + REJECT_REASONS.join(" / ") + "):");
  if (!reason || !REJECT_REASONS.includes(reason)) { alert("Invalid reason."); return; }
  const r = await fetch(`/admin/jobs/api/${id}/reject`, {
    method:"POST", credentials:"include",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({reason}),
  });
  if (!r.ok) { alert("Failed: " + r.status); return; }
  load();
}

async function bulkPub() {
  const selected = [...document.querySelectorAll(".sel:checked")];
  const ids = selected.map(x => +x.value);
  if (!ids.length) { alert("Select some rows."); return; }
  // Count how many of the selected drafts are missing a summary. We read
  // this off the row by walking up to the <tr> and looking for the
  // no-summary chip we emitted during render.
  const missing = selected.filter(cb =>
    cb.closest("tr").querySelector(".chip.flag-nosummary")
  ).length;
  const warn = missing
    ? `\n\n⚠  ${missing} of ${ids.length} jobs have no Opus summary — their public pages will render degraded.`
    : "";
  if (!confirm(`Publish ${ids.length} jobs?${warn}`)) return;
  const r = await fetch(`/admin/jobs/api/bulk-publish`, {
    method:"POST", credentials:"include",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({ids}),
  });
  if (!r.ok) { const msg = await r.text(); alert("Failed: " + msg); return; }
  load();
}

function toggleAll(el) { document.querySelectorAll(".sel:not(:disabled)").forEach(x=>x.checked=el.checked); }

document.querySelectorAll(".tabs button[data-status]").forEach(b => {
  b.onclick = () => {
    document.querySelectorAll(".tabs button[data-status]").forEach(x=>x.classList.remove("active"));
    b.classList.add("active");
    currentStatus = b.dataset.status;
    load();
  };
});

// Wire up the filter bar.
(function initQFilters() {
  const live = ["qf-designation","qf-remote","qf-company","qf-country","qf-city","qf-verified","qf-expired-reason"];
  live.forEach(id => document.getElementById(id).addEventListener("change", load));
  let tm = null;
  ["qf-q"].forEach(id => {
    document.getElementById(id).addEventListener("input", () => {
      clearTimeout(tm); tm = setTimeout(load, 250);
    });
  });
  document.getElementById("qf-clear").addEventListener("click", () => {
    document.getElementById("qf-q").value = "";
    ["qf-company","qf-designation","qf-remote","qf-country","qf-city","qf-expired-reason"].forEach(id => document.getElementById(id).value = "");
    document.getElementById("qf-verified").checked = false;
    currentFlag = "";
    document.querySelectorAll(".qtoggle").forEach(b => b.classList.remove("active"));
    load();
  });

  // Quick-filter toggle buttons: Tier-1 / non-AI / tier2-lite / enrich-failed.
  // Click to apply, click again (or Clear) to turn off. Only one active at a time.
  document.querySelectorAll(".qtoggle").forEach(b => {
    b.addEventListener("click", () => {
      const wasActive = b.classList.contains("active");
      document.querySelectorAll(".qtoggle").forEach(x => x.classList.remove("active"));
      if (wasActive) {
        currentFlag = "";
        document.getElementById("qf-verified").checked = false;
      } else {
        b.classList.add("active");
        currentFlag = b.dataset.flag || "";
        document.getElementById("qf-verified").checked = b.dataset.verified === "1";
      }
      load();
    });
  });
})();

document.getElementById("run-ingest").onclick = async () => {
  if (!confirm("Run ingest now? May take ~30s.")) return;
  const r = await fetch("/admin/jobs/api/ingest/run", {method:"POST", credentials:"include"});
  const data = await r.json();
  alert("Ingest: " + JSON.stringify(data.stats || data));
  load();
};

load();
</script>
</main>
<script src="/nav.js" defer></script>
</body></html>"""
