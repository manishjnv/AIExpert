"""Public jobs board router.

- `/api/jobs` JSON list (powers the filter UI; vanilla JS client-side).
- `/jobs` SSR hub page (list, SEO-indexable).
- `/jobs/<slug>` SSR per-job page with JobPosting JSON-LD (Google Jobs).
- `/sitemap-jobs.xml` sitemap of published jobs.

See docs/JOBS.md §7 for SEO spec.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from html import escape as esc
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models import Job


router = APIRouter()


JOB_TYPE_MAP = {
    "Full-time": "FULL_TIME",
    "Part-time": "PART_TIME",
    "Contract": "CONTRACTOR",
    "Internship": "INTERN",
}


def _public_view(job: Job) -> dict[str, Any]:
    """Stripped-down projection for the public JSON API."""
    d = job.data or {}
    return {
        "slug": job.slug,
        "title": job.title,
        "posted_on": job.posted_on.isoformat() if job.posted_on else None,
        "valid_through": job.valid_through.isoformat() if job.valid_through else None,
        "designation": job.designation,
        "seniority": d.get("seniority"),
        "topic": d.get("topic") or [],
        "company": d.get("company") or {"slug": job.company_slug, "name": job.company_slug},
        "location": d.get("location") or {"country": job.country, "remote_policy": job.remote_policy},
        "employment": d.get("employment") or {},
        "tldr": d.get("tldr") or "",
        "must_have_skills": d.get("must_have_skills") or [],
        "roadmap_modules_matched": d.get("roadmap_modules_matched") or [],
        "verified": bool(job.verified),
        "url": f"/jobs/{job.slug}",
    }


@router.get("/api/jobs")
async def list_jobs(
    designation: str | None = None,
    country: str | None = None,
    remote: str | None = None,
    company: str | None = None,
    topic: str | None = None,
    posted_within_days: int | None = Query(None, ge=1, le=365),
    q: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Job).where(Job.status == "published")
    if designation:
        stmt = stmt.where(Job.designation == designation)
    if country:
        stmt = stmt.where(Job.country == country.upper())
    if remote:
        stmt = stmt.where(Job.remote_policy == remote)
    if company:
        stmt = stmt.where(Job.company_slug == company)
    if posted_within_days:
        from datetime import timedelta
        stmt = stmt.where(Job.posted_on >= date.today() - timedelta(days=posted_within_days))
    if q:
        from sqlalchemy import func
        like = f"%{q.lower()}%"
        stmt = stmt.where(func.lower(Job.title).like(like))
    stmt = stmt.order_by(Job.posted_on.desc(), Job.id.desc()).offset(offset).limit(limit)

    rows = (await db.execute(stmt)).scalars().all()
    items = [_public_view(r) for r in rows]
    # Topic filter applied post-query (stored in JSON).
    if topic:
        items = [it for it in items if topic in (it.get("topic") or [])]
    return JSONResponse(items, headers={"Cache-Control": "public, max-age=300"})


# ---- SSR pages --------------------------------------------------------------

_BASE_CSS = """
<style>
  body{font-family:system-ui,-apple-system,sans-serif;max-width:980px;margin:0 auto;padding:1rem;color:#1a1a1a;line-height:1.55}
  h1{font-size:1.6rem;margin-bottom:.25rem}
  .meta{color:#666;font-size:.9rem;margin-bottom:1rem}
  .chip{display:inline-block;padding:2px 8px;border-radius:3px;font-size:.8rem;background:#eee;margin:2px 4px 2px 0}
  .chip.verified{background:#e6f7ea;color:#0a7}
  .tldr{background:#f7f9fc;padding:.8rem 1rem;border-left:3px solid #0a7;margin:1rem 0}
  .apply{display:inline-block;padding:.6rem 1.2rem;background:#0a7;color:#fff;border-radius:4px;text-decoration:none;margin:.5rem 0}
  .apply:hover{background:#086}
  .jd{border-top:1px solid #eee;margin-top:1.5rem;padding-top:1rem}
  .card{border:1px solid #e4e4e4;border-radius:6px;padding:.8rem 1rem;margin:.6rem 0;background:#fff}
  .card a{color:#1a1a1a;text-decoration:none}
  .card h3{margin:0 0 .3rem 0;font-size:1.05rem}
  a{color:#06c}
  .breadcrumb{font-size:.85rem;color:#888;margin-bottom:1rem}
</style>
"""


@router.get("/jobs", response_class=HTMLResponse)
@router.get("/jobs/", response_class=HTMLResponse)
async def jobs_index(db: AsyncSession = Depends(get_db)) -> HTMLResponse:
    stmt = (select(Job).where(Job.status == "published")
            .order_by(Job.posted_on.desc(), Job.id.desc()).limit(50))
    rows = (await db.execute(stmt)).scalars().all()

    cards = "\n".join(_card_html(r) for r in rows) or "<p>No jobs published yet.</p>"
    settings = get_settings()
    base = getattr(settings, "public_base_url", "") or ""

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>AI &amp; ML Jobs — AutomateEdge</title>
<meta name="description" content="Curated AI and ML job openings from verified companies. Match them against your AutomateEdge learning plan.">
<link rel="canonical" href="{esc(base)}/jobs">
<meta property="og:title" content="AI &amp; ML Jobs — AutomateEdge">
<meta property="og:description" content="Curated AI and ML job openings from verified companies.">
<meta property="og:type" content="website">
{_BASE_CSS}
</head><body>
<h1>AI &amp; ML Jobs</h1>
<p class="meta">Curated from verified company career pages. Updated daily.</p>
{cards}
</body></html>"""
    return HTMLResponse(html, headers={"Cache-Control": "public, max-age=3600"})


def _card_html(j: Job) -> str:
    d = j.data or {}
    loc = d.get("location") or {}
    loc_str = " · ".join(filter(None, [loc.get("city"), loc.get("country"), loc.get("remote_policy")]))
    verified_chip = '<span class="chip verified">✓ Verified</span>' if j.verified else ""
    tldr = esc((d.get("tldr") or "")[:200])
    return f"""<div class="card">
  <h3><a href="/jobs/{esc(j.slug)}">{esc(j.title)}</a></h3>
  <div class="meta">{esc((d.get('company') or {}).get('name') or j.company_slug)} · {esc(loc_str or '—')} · {esc(j.posted_on.isoformat() if j.posted_on else '')}</div>
  <div><span class="chip">{esc(j.designation)}</span> {verified_chip}</div>
  <p>{tldr}</p>
</div>"""


@router.get("/jobs/{slug}", response_class=HTMLResponse)
@router.get("/jobs/{slug}/", response_class=HTMLResponse)
async def job_detail(slug: str, db: AsyncSession = Depends(get_db)) -> HTMLResponse:
    job = (await db.execute(select(Job).where(Job.slug == slug))).scalar_one_or_none()
    if not job or job.status not in ("published", "expired"):
        raise HTTPException(404, "Job not found")

    d = job.data or {}
    settings = get_settings()
    base = (getattr(settings, "public_base_url", "") or "").rstrip("/")
    canonical = f"{base}/jobs/{job.slug}"

    loc = d.get("location") or {}
    emp = d.get("employment") or {}
    salary = emp.get("salary") or {}
    company = d.get("company") or {"name": job.company_slug, "slug": job.company_slug}
    loc_str = " · ".join(filter(None, [loc.get("city"), loc.get("country"), loc.get("remote_policy")]))
    is_expired = job.status == "expired" or (job.valid_through and job.valid_through < date.today())

    # JobPosting JSON-LD (docs/JOBS.md §7.2).
    ld: dict[str, Any] = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": job.title,
        "description": d.get("description_html") or d.get("tldr") or "",
        "datePosted": job.posted_on.isoformat() if job.posted_on else None,
        "validThrough": job.valid_through.isoformat() if job.valid_through else None,
        "employmentType": JOB_TYPE_MAP.get(emp.get("job_type", ""), "FULL_TIME"),
        "hiringOrganization": {
            "@type": "Organization",
            "name": company.get("name"),
            "sameAs": company.get("website") or None,
        },
        "directApply": False,
    }
    if loc.get("city") or loc.get("country"):
        ld["jobLocation"] = {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": loc.get("city"),
                "addressCountry": loc.get("country"),
            },
        }
    if loc.get("remote_policy") == "Remote" and loc.get("regions_allowed"):
        ld["applicantLocationRequirements"] = [
            {"@type": "Country", "name": c} for c in loc.get("regions_allowed", [])
        ]
    if salary.get("disclosed") and salary.get("currency") and (salary.get("min") or salary.get("max")):
        ld["baseSalary"] = {
            "@type": "MonetaryAmount",
            "currency": salary.get("currency"),
            "value": {
                "@type": "QuantitativeValue",
                "minValue": salary.get("min"),
                "maxValue": salary.get("max"),
                "unitText": "YEAR",
            },
        }
    # Strip Nones from top-level for cleanliness.
    ld = {k: v for k, v in ld.items() if v is not None}

    title_tag = f"{esc(job.title)} at {esc(company.get('name') or '')} — {esc(loc_str or 'Remote')} | AutomateEdge Jobs"
    desc_tag = esc((d.get("tldr") or job.title)[:155])
    apply_url = d.get("apply_url") or job.source_url
    verified_chip = '<span class="chip verified">✓ Verified source</span>' if job.verified else ""

    expired_banner = ('<p style="background:#fee;padding:.6rem 1rem;border:1px solid #fbb">'
                      'This role has closed. Listed for reference only.</p>') if is_expired else ""
    robots_tag = '<meta name="robots" content="noindex">' if is_expired else ""

    skills = d.get("must_have_skills") or []
    skills_html = " ".join(f'<span class="chip">{esc(s)}</span>' for s in skills)

    modules = d.get("roadmap_modules_matched") or []
    modules_html = (
        f'<p class="meta">Matches roadmap modules: {", ".join(esc(m) for m in modules)}. '
        f'<a href="/login">Sign in</a> to see your match %.</p>' if modules else ""
    )

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{title_tag}</title>
<meta name="description" content="{desc_tag}">
<link rel="canonical" href="{esc(canonical)}">
{robots_tag}
<meta property="og:title" content="{title_tag}">
<meta property="og:description" content="{desc_tag}">
<meta property="og:type" content="article">
<meta property="og:url" content="{esc(canonical)}">
<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>
{_BASE_CSS}
</head><body>
<div class="breadcrumb"><a href="/jobs">AI &amp; ML Jobs</a> / {esc(job.title)}</div>
<h1>{esc(job.title)}</h1>
<div class="meta">
  <b>{esc(company.get('name') or job.company_slug)}</b> · {esc(loc_str or '—')} ·
  Posted {esc(job.posted_on.isoformat() if job.posted_on else '')}
</div>
<div>
  <span class="chip">{esc(job.designation)}</span>
  <span class="chip">{esc(d.get('seniority') or '')}</span>
  <span class="chip">{esc(emp.get('job_type') or '')}</span>
  {verified_chip}
</div>
{expired_banner}
{f'<div class="tldr">{esc(d.get("tldr") or "")}</div>' if d.get("tldr") else ""}
<p><a class="apply" href="{esc(apply_url)}" rel="nofollow sponsored" target="_blank">Apply on {esc(company.get('name') or 'company site')} →</a></p>
<div><b>Key skills:</b> {skills_html or "—"}</div>
{modules_html}
<div class="jd">{d.get("description_html") or ""}</div>
</body></html>"""
    headers = {"Cache-Control": "public, max-age=300" if not is_expired else "public, max-age=86400"}
    return HTMLResponse(html, headers=headers)


# ---- Sitemap ---------------------------------------------------------------

@router.get("/sitemap-jobs.xml")
async def sitemap_jobs(db: AsyncSession = Depends(get_db)) -> Response:
    settings = get_settings()
    base = (getattr(settings, "public_base_url", "") or "").rstrip("/")
    stmt = (select(Job).where(Job.status == "published")
            .order_by(Job.updated_at.desc()).limit(10000))
    rows = (await db.execute(stmt)).scalars().all()

    urls = []
    for r in rows:
        lastmod = (r.updated_at or datetime.utcnow()).date().isoformat()
        urls.append(
            f"<url><loc>{esc(f'{base}/jobs/{r.slug}')}</loc>"
            f"<lastmod>{lastmod}</lastmod><priority>0.8</priority></url>"
        )
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           + "".join(urls) + "</urlset>")
    return Response(content=xml, media_type="application/xml",
                    headers={"Cache-Control": "public, max-age=3600"})
