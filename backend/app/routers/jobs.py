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

from app.auth.deps import get_current_user
from app.config import get_settings
from app.db import get_db
from app.models import Job
from app.models.user import User
from app.services.jobs_match import compute_match


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

_BRAND_HEAD = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:wght@400;500;700&family=IBM+Plex+Sans:wght@400;500&family=IBM+Plex+Mono:wght@400&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/nav.css">
"""

_BASE_CSS = """
<style>
  :root{color-scheme:dark}
  html,body{margin:0;background:#0f1419;color:#e8e4d8;font-family:'IBM Plex Sans',system-ui,sans-serif;line-height:1.6}
  main{max-width:1080px;margin:0 auto;padding:40px 24px 80px}
  h1.page-title{font-family:'Fraunces',Georgia,serif;font-size:clamp(28px,4vw,42px);line-height:1.15;color:#f5f1e8;margin:0 0 10px;font-weight:500}
  .page-eyebrow{font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:#e8a849;margin-bottom:8px}
  .page-lede{font-size:15px;color:#c0c4cc;max-width:640px;margin:0 0 32px}
  .meta{color:#94a3b8;font-size:13px}
  .chip{display:inline-block;padding:2px 10px;border-radius:3px;font-size:11px;font-family:'IBM Plex Mono',monospace;letter-spacing:.06em;text-transform:uppercase;background:#1a2029;color:#c0c4cc;border:1px solid #2a323d;margin:2px 4px 2px 0}
  .chip.verified{background:rgba(232,168,73,.12);color:#e8a849;border-color:rgba(232,168,73,.4)}
  .tldr{background:#1a2029;padding:14px 18px;border-left:3px solid #e8a849;margin:20px 0;border-radius:4px;color:#e8e4d8}
  .apply{display:inline-block;padding:10px 22px;background:#e8a849;color:#0f1419;border-radius:4px;text-decoration:none;font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.14em;text-transform:uppercase;font-weight:500;margin:10px 0;transition:background .2s}
  .apply:hover{background:#f0b968}
  .jd{border-top:1px solid #2a323d;margin-top:28px;padding-top:20px;color:#d0cbc2}
  .jd h2,.jd h3{font-family:'Fraunces',Georgia,serif;color:#f5f1e8;font-weight:500;margin-top:24px}
  .jd a{color:#e8a849}
  .card{background:#1a2029;border:1px solid #2a323d;border-radius:8px;padding:18px 22px;margin:12px 0;transition:all .2s ease;position:relative}
  .card:hover{border-color:#e8a849;background:#1d242e}
  .card a{color:inherit;text-decoration:none}
  .card h3{margin:0 0 6px 0;font-size:17px;font-family:'Fraunces',Georgia,serif;font-weight:500;color:#f5f1e8;line-height:1.25}
  .card p{color:#c0c4cc;font-size:14px;margin:8px 0 0}
  a{color:#e8a849}
  .breadcrumb{font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:#94a3b8;margin-bottom:16px}
  .breadcrumb a{color:#94a3b8;text-decoration:none}
  .breadcrumb a:hover{color:#e8a849}
</style>
"""


@router.get("/jobs", response_class=HTMLResponse)
@router.get("/jobs/", response_class=HTMLResponse)
async def jobs_index(db: AsyncSession = Depends(get_db)) -> HTMLResponse:
    # Server-render the first page so the crawler sees real content; the
    # client JS then hydrates with filters + match ring against /api/jobs.
    stmt = (select(Job).where(Job.status == "published")
            .order_by(Job.posted_on.desc(), Job.id.desc()).limit(50))
    rows = (await db.execute(stmt)).scalars().all()

    initial_cards = "\n".join(_card_html(r) for r in rows) or "<p>No jobs published yet.</p>"
    settings = get_settings()
    base = getattr(settings, "public_base_url", "") or ""

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI &amp; ML Jobs — AutomateEdge</title>
<meta name="description" content="Curated AI and ML job openings from verified companies. See your match %% against your AutomateEdge learning plan.">
<link rel="canonical" href="{esc(base)}/jobs">
<meta property="og:title" content="AI &amp; ML Jobs — AutomateEdge">
<meta property="og:description" content="Curated AI and ML job openings from verified companies.">
<meta property="og:type" content="website">
{_BRAND_HEAD}
{_BASE_CSS}
{_HUB_CSS}
</head><body>
<main>
<div class="page-eyebrow">AutomateEdge · Jobs</div>
<h1 class="page-title">AI &amp; ML Jobs</h1>
<p class="page-lede">Curated openings from verified AI-native companies. Daily scrape, AI-summarised, matched against your learning plan.</p>

<div class="layout">
  <aside class="filters">
    <details open><summary>Time</summary>
      <label><input type="radio" name="posted" value=""> Any time</label>
      <label><input type="radio" name="posted" value="1"> Last 24h</label>
      <label><input type="radio" name="posted" value="7" checked> Last 7 days</label>
      <label><input type="radio" name="posted" value="30"> Last 30 days</label>
    </details>
    <details open><summary>Role</summary>
      <select id="f-designation">
        <option value="">Any designation</option>
        <option>ML Engineer</option><option>Research Scientist</option>
        <option>Applied Scientist</option><option>Data Scientist</option>
        <option>Data Engineer</option><option>MLOps Engineer</option>
        <option>AI Product Manager</option><option>AI Engineer</option>
        <option>Prompt Engineer</option><option>Research Engineer</option>
        <option>Computer Vision Engineer</option><option>NLP Engineer</option>
        <option>AI Solutions Architect</option><option>AI Developer Advocate</option>
        <option>Other</option>
      </select>
      <select id="f-topic">
        <option value="">Any topic</option>
        <option>LLM</option><option>CV</option><option>NLP</option><option>RL</option>
        <option>MLOps</option><option>Data Eng</option><option>Research</option>
        <option>Applied ML</option><option>GenAI</option><option>Robotics</option>
        <option>Safety</option><option>Agents</option><option>RAG</option>
        <option>Fine-tuning</option><option>Evals</option>
      </select>
    </details>
    <details open><summary>Location</summary>
      <select id="f-remote">
        <option value="">Any workplace</option>
        <option>Remote</option><option>Hybrid</option><option>Onsite</option>
      </select>
      <input id="f-country" placeholder="Country (ISO-2, e.g. US, IN)" maxlength="2" style="text-transform:uppercase">
    </details>
    <details><summary>Company</summary>
      <input id="f-company" placeholder="Company slug (e.g. anthropic)">
    </details>
    <details><summary>Search</summary>
      <input id="f-q" placeholder="Keyword in title">
    </details>
    <button id="apply" class="apply-btn">Apply filters</button>
    <button id="clear" class="clear-btn">Clear</button>
  </aside>

  <div class="results">
    <div id="chips" class="chips-row"></div>
    <div id="list">{initial_cards}</div>
  </div>
</div>

{_HUB_JS}
</main>
<script src="/nav.js" defer></script>
</body></html>"""
    return HTMLResponse(html, headers={"Cache-Control": "public, max-age=600"})


def _card_html(j: Job) -> str:
    d = j.data or {}
    loc = d.get("location") or {}
    emp = d.get("employment") or {}
    yrs = emp.get("experience_years") or {}
    loc_str = " · ".join(filter(None, [loc.get("city"), loc.get("country"), loc.get("remote_policy")]))
    yrs_str = _yrs_label(yrs.get("min"), yrs.get("max"))
    verified_chip = '<span class="chip verified">✓ Verified</span>' if j.verified else ""
    loc_chip = f'<span class="chip">📍 {esc(loc_str)}</span>' if loc_str else ""
    yrs_chip = f'<span class="chip">{esc(yrs_str)}</span>' if yrs_str else ""
    tldr = esc((d.get("tldr") or "")[:200])
    return f"""<div class="card">
  <h3><a href="/jobs/{esc(j.slug)}">{esc(j.title)}</a></h3>
  <div class="meta">{esc((d.get('company') or {}).get('name') or j.company_slug)} · Posted {esc(j.posted_on.isoformat() if j.posted_on else '')}</div>
  <div><span class="chip">{esc(j.designation)}</span> {loc_chip} {yrs_chip} {verified_chip}</div>
  <p>{tldr}</p>
</div>"""


def _yrs_label(mn, mx) -> str:
    if isinstance(mn, int) and isinstance(mx, int):
        return f"{mn}–{mx} yrs" if mn != mx else f"{mn} yrs"
    if isinstance(mn, int):
        return f"{mn}+ yrs"
    if isinstance(mx, int):
        return f"≤{mx} yrs"
    return ""


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
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title_tag}</title>
<meta name="description" content="{desc_tag}">
<link rel="canonical" href="{esc(canonical)}">
{robots_tag}
<meta property="og:title" content="{title_tag}">
<meta property="og:description" content="{desc_tag}">
<meta property="og:type" content="article">
<meta property="og:url" content="{esc(canonical)}">
<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>
{_BRAND_HEAD}
{_BASE_CSS}
</head><body>
<main>
<div class="breadcrumb"><a href="/jobs">AI &amp; ML Jobs</a> / {esc(job.title)}</div>
<h1 class="page-title">{esc(job.title)}</h1>
<div class="meta" style="margin-bottom:14px">
  <strong style="color:#e8a849">{esc(company.get('name') or job.company_slug)}</strong> · {esc(loc_str or '—')} ·
  Posted {esc(job.posted_on.isoformat() if job.posted_on else '')}
</div>
<div style="margin-bottom:18px">
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
<div id="match-box" style="display:none;background:#1a2029;border:1px solid #2a323d;padding:16px 20px;border-radius:8px;margin:20px 0"></div>
<div class="jd">{d.get("description_html") or ""}</div>
<script>
(async () => {{
  try {{
    const r = await fetch("/api/jobs/{esc(job.slug)}/match", {{credentials:"include"}});
    if (!r.ok) return;
    const m = await r.json();
    const box = document.getElementById("match-box");
    const tone = m.score >= 70 ? "#6db585" : m.score >= 40 ? "#e8a849" : "#4a5560";
    const textColor = m.score >= 40 ? "#0f1419" : "#c0c4cc";
    const missing = (m.missing_skills||[]);
    const gap = missing.length
      ? `<p style="margin:12px 0 0"><b style="color:#e8a849;font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.12em;text-transform:uppercase">Close the gap:</b><br>${{missing.map(s => `<span class=\\"chip\\">${{s.replace(/[<>]/g,'')}}</span>`).join(" ")}}</p>`
      : `<p style="margin:12px 0 0;color:#6db585">You match every listed must-have skill. 👏</p>`;
    box.innerHTML = `
      <div style="display:flex;align-items:center;gap:16px">
        <div style="background:${{tone}};color:${{textColor}};padding:8px 16px;border-radius:4px;font-weight:600;font-size:18px;font-family:'IBM Plex Mono',monospace">${{m.score}}% match</div>
        <div style="color:#c0c4cc;font-size:14px">Based on your linked repos + experience level.</div>
      </div>
      ${{gap}}`;
    box.style.display = "block";
  }} catch(_) {{}}
}})();
</script>
</main>
<script src="/nav.js" defer></script>
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


@router.get("/sitemap_index.xml")
async def sitemap_index() -> Response:
    """Minimal sitemap-index referencing the jobs sitemap. Submit this URL to GSC."""
    settings = get_settings()
    base = (settings.public_base_url or "").rstrip("/")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>{esc(base)}/sitemap-jobs.xml</loc></sitemap>
</sitemapindex>"""
    return Response(content=xml, media_type="application/xml",
                    headers={"Cache-Control": "public, max-age=3600"})


@router.get("/{key}.txt")
async def indexnow_key_verify(key: str) -> Response:
    """IndexNow ownership verification file. Serves the key as plain text at
    /<key>.txt only when it matches INDEXNOW_KEY in config. 404 otherwise so
    this route doesn't shadow unrelated .txt paths."""
    settings = get_settings()
    configured = settings.indexnow_key
    if not configured or key != configured:
        raise HTTPException(404, "not found")
    return Response(content=configured, media_type="text/plain")


# ---- Match-% endpoint (logged-in only) --------------------------------------

@router.get("/api/jobs/{slug}/match")
async def job_match(
    slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = (await db.execute(select(Job).where(Job.slug == slug))).scalar_one_or_none()
    if not job or job.status != "published":
        raise HTTPException(404, "not found")
    return await compute_match(user, job, db)


# ---- Hub page CSS + JS (kept inline to avoid a new static file) ------------

_HUB_CSS = """
<style>
  .layout{display:grid;grid-template-columns:240px 1fr;gap:24px;margin-top:8px}
  .filters details{background:#1a2029;border:1px solid #2a323d;border-radius:6px;padding:10px 14px;margin-bottom:10px}
  .filters summary{cursor:pointer;font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:#e8a849;font-weight:500}
  .filters label{display:block;font-size:13px;padding:4px 0;color:#c0c4cc;cursor:pointer}
  .filters input[type=text],.filters input:not([type]),.filters select{
    width:100%;padding:7px 10px;margin-top:6px;font-size:13px;
    background:#0f1419;color:#e8e4d8;border:1px solid #2a323d;border-radius:4px;box-sizing:border-box;
    font-family:'IBM Plex Sans',sans-serif
  }
  .filters input:focus,.filters select:focus{outline:none;border-color:#e8a849}
  .apply-btn{width:100%;padding:10px;background:#e8a849;color:#0f1419;border:0;border-radius:4px;cursor:pointer;margin-top:10px;font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.14em;text-transform:uppercase;font-weight:500}
  .apply-btn:hover{background:#f0b968}
  .clear-btn{width:100%;padding:8px;background:transparent;color:#94a3b8;border:1px solid #2a323d;border-radius:4px;cursor:pointer;margin-top:6px;font-size:12px;font-family:'IBM Plex Mono',monospace;letter-spacing:.1em;text-transform:uppercase}
  .clear-btn:hover{color:#e8a849;border-color:#e8a849}
  .chips-row{margin-bottom:12px}
  .chips-row .filter-chip{background:#2a323d;color:#e8e4d8;padding:3px 10px;border-radius:3px;font-size:11px;font-family:'IBM Plex Mono',monospace;letter-spacing:.08em;margin-right:6px;cursor:pointer}
  .chips-row .filter-chip::after{content:" ×";opacity:.7;color:#e8a849}
  .chips-row .filter-chip:hover{background:#3a424d}
  .match-ring{position:absolute;top:16px;right:18px;width:48px;height:48px;border-radius:50%;
    display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:600;color:#0f1419;font-family:'IBM Plex Mono',monospace}
  .match-ring.high{background:#6db585}
  .match-ring.mid{background:#e8a849}
  .match-ring.low{background:#4a5560;color:#c0c4cc}
  .empty{padding:48px 24px;text-align:center;color:#94a3b8;background:#1a2029;border:1px dashed #2a323d;border-radius:8px}
  @media (max-width:720px){ .layout{grid-template-columns:1fr} }
</style>
"""

_HUB_JS = """
<script>
const FILTERS = ["designation","topic","remote","country","company","q"];
const $ = id => document.getElementById(id);

function currentFilters() {
  const posted = document.querySelector('input[name=posted]:checked');
  return {
    designation: $('f-designation').value.trim(),
    topic: $('f-topic').value.trim(),
    remote: $('f-remote').value.trim(),
    country: $('f-country').value.trim().toUpperCase(),
    company: $('f-company').value.trim().toLowerCase(),
    q: $('f-q').value.trim(),
    posted_within_days: posted ? posted.value : ""
  };
}

function esc(s){return (s||"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}[c]))}

async function loadJobs() {
  const f = currentFilters();
  const q = new URLSearchParams();
  for (const k of FILTERS) if (f[k]) q.set(k, f[k]);
  if (f.posted_within_days) q.set("posted_within_days", f.posted_within_days);
  q.set("limit", "100");

  const r = await fetch("/api/jobs?" + q.toString());
  if (!r.ok) { $('list').innerHTML = '<p class="empty">Load failed.</p>'; return; }
  const items = await r.json();
  renderChips(f);
  if (!items.length) {
    $('list').innerHTML = '<p class="empty">No matching jobs. Try removing a filter.</p>';
    return;
  }
  $('list').innerHTML = items.map(renderCard).join("");
  items.forEach(fetchMatch);
}

function renderChips(f) {
  const chips = [];
  for (const k of FILTERS) if (f[k]) chips.push([k, f[k]]);
  if (f.posted_within_days) chips.push(["posted", `≤${f.posted_within_days}d`]);
  $('chips').innerHTML = chips.map(([k,v]) =>
    `<span class="filter-chip" data-k="${k}">${esc(k)}: ${esc(v)}</span>`
  ).join("");
  document.querySelectorAll('.filter-chip').forEach(el => {
    el.onclick = () => {
      const k = el.dataset.k;
      if (k === 'posted') document.querySelectorAll('input[name=posted]').forEach(x=>x.checked = x.value === "");
      else if (k === 'designation') $('f-designation').value = "";
      else if (k === 'topic') $('f-topic').value = "";
      else if (k === 'remote') $('f-remote').value = "";
      else if (k === 'country') $('f-country').value = "";
      else if (k === 'company') $('f-company').value = "";
      else if (k === 'q') $('f-q').value = "";
      loadJobs();
    };
  });
}

function renderCard(j) {
  const co = j.company || {};
  const loc = j.location || {};
  const emp = j.employment || {};
  const yrs = emp.experience_years || {};
  const locStr = [loc.city, loc.country, loc.remote_policy].filter(Boolean).join(" · ");
  const yrsStr = (() => {
    const mn = yrs.min, mx = yrs.max;
    if (Number.isInteger(mn) && Number.isInteger(mx)) return mn === mx ? `${mn} yrs` : `${mn}–${mx} yrs`;
    if (Number.isInteger(mn)) return `${mn}+ yrs`;
    if (Number.isInteger(mx)) return `≤${mx} yrs`;
    return "";
  })();
  const verified = j.verified ? '<span class="chip verified">✓ Verified</span>' : '';
  const locChip = locStr ? `<span class="chip">📍 ${esc(locStr)}</span>` : '';
  const yrsChip = yrsStr ? `<span class="chip">${esc(yrsStr)}</span>` : '';
  return `<div class="card" data-slug="${esc(j.slug)}">
    <div class="match-ring" id="match-${esc(j.slug)}" style="display:none"></div>
    <h3><a href="/jobs/${esc(j.slug)}">${esc(j.title)}</a></h3>
    <div class="meta">${esc(co.name||j.company?.slug||'')} · Posted ${esc(j.posted_on||'')}</div>
    <div><span class="chip">${esc(j.designation||'')}</span> ${locChip} ${yrsChip} ${verified}</div>
    <p>${esc((j.tldr||'').slice(0,200))}</p>
  </div>`;
}

async function fetchMatch(j) {
  try {
    const r = await fetch(`/api/jobs/${encodeURIComponent(j.slug)}/match`, {credentials:"include"});
    if (r.status === 401) return; // anonymous — no ring
    if (!r.ok) return;
    const m = await r.json();
    const el = document.getElementById("match-" + j.slug);
    if (!el) return;
    const cls = m.score >= 70 ? 'high' : m.score >= 40 ? 'mid' : 'low';
    el.className = 'match-ring ' + cls;
    el.textContent = m.score + '%';
    el.title = `Matched ${m.matched_skills_count} of ${m.matched_skills_count + (m.missing_skills||[]).length} required skills`;
    el.style.display = 'flex';
  } catch(_) {}
}

$('apply').onclick = loadJobs;
$('clear').onclick = () => {
  FILTERS.forEach(k => { const el = $('f-' + k); if (el) el.value = ""; });
  document.querySelectorAll('input[name=posted]').forEach(x => x.checked = x.value === "");
  loadJobs();
};
// Enter-to-apply in text inputs.
['f-country','f-company','f-q'].forEach(id => {
  $(id).addEventListener('keydown', e => { if (e.key === 'Enter') loadJobs(); });
});
// Auto-apply on dropdown/radio change.
['f-designation','f-topic','f-remote'].forEach(id => $(id).addEventListener('change', loadJobs));
document.querySelectorAll('input[name=posted]').forEach(x => x.addEventListener('change', loadJobs));

loadJobs();
</script>
"""
