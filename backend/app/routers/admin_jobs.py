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
from app.db import get_db
from app.models import Job, JobCompany, JobSource
from app.models.user import User

router = APIRouter()

VALID_REJECT_REASONS = {"fake", "expired", "off_topic", "duplicate", "low_quality"}
VALID_STATUS_FILTER = {"draft", "published", "rejected", "expired", "all"}


def _check_origin(request: Request) -> None:
    origin = request.headers.get("origin") or request.headers.get("referer", "")
    host = request.headers.get("host", "")
    if origin and host and host not in origin:
        raise HTTPException(status_code=403, detail="Origin mismatch")


def _serialize(job: Job) -> dict[str, Any]:
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
        "data": job.data,
    }


# ---- JSON API ---------------------------------------------------------------

@router.get("/api/queue")
async def list_queue(
    status: str = Query("draft"),
    source: str | None = None,
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
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(func.lower(Job.title).like(like))
    stmt = stmt.order_by(Job.posted_on.desc(), Job.id.desc()).offset(offset).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    # Counters for the admin banner.
    counts_stmt = select(Job.status, func.count(Job.id)).group_by(Job.status)
    counts = {s: n for s, n in (await db.execute(counts_stmt)).all()}

    return {
        "items": [_serialize(j) for j in rows],
        "counts": counts,
    }


@router.get("/api/{job_id}")
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
<title>Jobs Review — Admin</title>
<link rel="stylesheet" href="/static/css/nav.css">
<style>
  body{font-family:system-ui,sans-serif;max-width:1200px;margin:0 auto;padding:1rem;color:#1a1a1a}
  .banner{padding:.75rem 1rem;background:#fffbea;border:1px solid #f0c040;border-radius:6px;margin-bottom:1rem}
  .tabs{display:flex;gap:.5rem;margin:1rem 0}
  .tabs button{padding:.4rem .8rem;border:1px solid #ccc;background:#fff;cursor:pointer;border-radius:4px}
  .tabs button.active{background:#1a1a1a;color:#fff}
  table{width:100%;border-collapse:collapse;font-size:.9rem}
  th,td{padding:.5rem;border-bottom:1px solid #eee;text-align:left;vertical-align:top}
  th{background:#f7f7f7}
  .btn{padding:.3rem .6rem;border:1px solid #888;background:#fff;cursor:pointer;border-radius:3px;font-size:.85rem}
  .btn.primary{background:#0a7;color:#fff;border-color:#0a7}
  .btn.danger{background:#c33;color:#fff;border-color:#c33}
  .chip{display:inline-block;padding:1px 6px;border-radius:3px;font-size:.75rem;background:#eee;margin-right:4px}
  .chip.verified{background:#dfd;color:#070}
  .tldr{color:#555;font-size:.85rem;max-width:420px}
  details{margin:.3rem 0}
  details summary{cursor:pointer;color:#06c}
  pre{background:#f5f5f5;padding:.5rem;border-radius:4px;max-height:300px;overflow:auto;font-size:.75rem}
</style>
</head><body>
<h1>Jobs Review Queue</h1>
<div id="banner" class="banner">Loading…</div>
<div class="tabs">
  <button data-status="draft" class="active">Draft</button>
  <button data-status="published">Published</button>
  <button data-status="rejected">Rejected</button>
  <button data-status="expired">Expired</button>
  <button data-status="all">All</button>
  <button id="run-ingest" style="margin-left:auto" class="btn primary">Run ingest now</button>
</div>
<div id="list">Loading…</div>

<script>
const REJECT_REASONS = ["fake","expired","off_topic","duplicate","low_quality"];
let currentStatus = "draft";

async function load() {
  const r = await fetch(`/admin/jobs/api/queue?status=${currentStatus}&limit=200`, {credentials:"include"});
  if (!r.ok) { document.getElementById("list").innerText = "Load failed: " + r.status; return; }
  const data = await r.json();
  const counts = data.counts || {};
  document.getElementById("banner").innerHTML =
    `<b>Queue:</b> ${counts.draft||0} draft · ${counts.published||0} published · ${counts.rejected||0} rejected · ${counts.expired||0} expired`;
  renderList(data.items);
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
      ? `<button class="btn primary" onclick="pub(${j.id})">Publish</button>
         <button class="btn danger" onclick="rej(${j.id})">Reject</button>`
      : `<span>${esc(j.status)}${j.reject_reason?" ("+esc(j.reject_reason)+")":""}</span>`;
    return `<tr>
      <td><input type="checkbox" class="sel" value="${j.id}" ${j.status==='draft'?'':'disabled'}></td>
      <td>
        <b>${esc(j.title)}</b> <span class="chip ${j.verified?'verified':''}">${esc(d.company?.name||j.company_slug)}</span><br>
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

async function pub(id) {
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
  const ids = [...document.querySelectorAll(".sel:checked")].map(x=>+x.value);
  if (!ids.length) { alert("Select some rows."); return; }
  if (!confirm(`Publish ${ids.length} jobs?`)) return;
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

document.getElementById("run-ingest").onclick = async () => {
  if (!confirm("Run ingest now? May take ~30s.")) return;
  const r = await fetch("/admin/jobs/api/ingest/run", {method:"POST", credentials:"include"});
  const data = await r.json();
  alert("Ingest: " + JSON.stringify(data.stats || data));
  load();
};

load();
</script>
</body></html>"""
