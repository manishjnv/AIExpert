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

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, Response
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
    city: str | None = None,
    remote: str | None = None,
    company: str | None = None,
    topic: str | None = None,
    posted_within_days: int | None = Query(None, ge=1, le=365),
    q: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import func
    stmt = select(Job).where(Job.status == "published")
    if designation:
        stmt = stmt.where(Job.designation == designation)
    if country:
        stmt = stmt.where(Job.country == country.upper())
    if city:
        # City lives only in data.location.city — match case-insensitive.
        stmt = stmt.where(
            func.lower(func.json_extract(Job.data, "$.location.city")) == city.strip().lower()
        )
    if remote:
        stmt = stmt.where(Job.remote_policy == remote)
    if company:
        stmt = stmt.where(Job.company_slug == company)
    if posted_within_days:
        from datetime import timedelta
        stmt = stmt.where(Job.posted_on >= date.today() - timedelta(days=posted_within_days))
    if q:
        from sqlalchemy import func, or_
        like = f"%{q.lower()}%"
        # Search title + company slug. Skill search happens post-query against
        # the JSON payload below (SQLite can't cheaply index JSON arrays).
        stmt = stmt.where(or_(func.lower(Job.title).like(like),
                              func.lower(Job.company_slug).like(like)))
    stmt = stmt.order_by(Job.posted_on.desc(), Job.id.desc()).offset(offset).limit(limit)

    rows = (await db.execute(stmt)).scalars().all()
    items = [_public_view(r) for r in rows]
    # Topic filter applied post-query (stored in JSON).
    if topic:
        items = [it for it in items if topic in (it.get("topic") or [])]
    return JSONResponse(items, headers={"Cache-Control": "public, max-age=300"})


@router.get("/api/jobs/locations")
async def list_locations(db: AsyncSession = Depends(get_db)):
    """Distinct countries + cities from published jobs, sorted by count.
    Feeds the public + admin location filter dropdowns."""
    from sqlalchemy import func
    # Countries from the denormalized column.
    country_rows = (await db.execute(
        select(Job.country, func.count(Job.id))
        .where(Job.status == "published", Job.country.is_not(None))
        .group_by(Job.country).order_by(func.count(Job.id).desc())
    )).all()
    # Cities live in the JSON payload.
    city_expr = func.json_extract(Job.data, "$.location.city")
    city_rows = (await db.execute(
        select(city_expr, Job.country, func.count(Job.id))
        .where(Job.status == "published", city_expr.is_not(None), city_expr != "")
        .group_by(city_expr, Job.country).order_by(func.count(Job.id).desc())
    )).all()
    return JSONResponse(
        {
            "countries": [{"code": c, "count": n} for c, n in country_rows],
            "cities": [{"name": c, "country": co, "count": n} for c, co, n in city_rows],
        },
        headers={"Cache-Control": "public, max-age=600"},
    )


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
  main{max-width:1440px;margin:0 auto;padding:40px 32px 80px}
  h1.page-title{font-family:'Fraunces',Georgia,serif;font-size:clamp(28px,4vw,42px);line-height:1.15;color:#f5f1e8;margin:0 0 10px;font-weight:500}
  .page-eyebrow{font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:#e8a849;margin-bottom:8px}
  .page-lede{font-size:15px;color:#c0c4cc;max-width:640px;margin:0 0 32px}
  .meta{color:#94a3b8;font-size:13px}
  .chip{display:inline-block;padding:2px 10px;border-radius:3px;font-size:11px;font-family:'IBM Plex Mono',monospace;letter-spacing:.06em;text-transform:uppercase;background:#1a2029;color:#c0c4cc;border:1px solid #2a323d;margin:2px 4px 2px 0}
  .chip.verified{background:rgba(232,168,73,.12);color:#e8a849;border-color:rgba(232,168,73,.4)}
  .tldr{background:#1a2029;padding:14px 18px;border-left:3px solid #e8a849;margin:20px 0;border-radius:4px;color:#e8e4d8}
  .apply{display:inline-block;padding:10px 22px;background:#e8a849;color:#0f1419;border-radius:4px;text-decoration:none;font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.14em;text-transform:uppercase;font-weight:500;margin:10px 0;transition:background .2s}
  .apply:hover{background:#f0b968}
  .jd{color:#d0cbc2;max-width:760px;font-size:15px;line-height:1.75}
  .jd p{margin:0 0 1em}
  .jd h1,.jd h2,.jd h3,.jd h4{font-family:'Fraunces',Georgia,serif;color:#f5f1e8;font-weight:500;margin:1.6em 0 .6em;line-height:1.3}
  .jd h2{font-size:22px}.jd h3{font-size:18px}.jd h4{font-size:16px}
  .jd ul,.jd ol{padding-left:22px;margin:0 0 1em}
  .jd li{margin:.35em 0}
  .jd a{color:#e8a849}
  .jd-wrap{border-top:1px solid #2a323d;margin-top:28px;padding-top:8px}
  .jd-wrap>summary{cursor:pointer;list-style:none;padding:14px 0;font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:#e8a849}
  .jd-wrap>summary::-webkit-details-marker{display:none}
  .jd-wrap>summary::before{content:"▸ ";display:inline-block;transition:transform .2s;margin-right:4px}
  .jd-wrap[open]>summary::before{transform:rotate(90deg)}
  .hl-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1px;background:#2a323d;border:1px solid #2a323d;border-radius:6px;overflow:hidden;margin:22px 0}
  .hl-cell{background:#141a21;padding:10px 14px}
  .hl-k{font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:#94a3b8;margin-bottom:2px}
  .hl-v{color:#e8e4d8;font-size:14px;font-weight:500}
  .skills-block{margin:18px 0;display:flex;flex-direction:column;gap:10px}
  .skills-row{display:flex;align-items:flex-start;gap:14px;flex-wrap:wrap}
  .skills-label{font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:#94a3b8;padding-top:4px;min-width:110px}
  .skills-row em{color:#94a3b8;font-style:normal;font-size:13px}
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
    <div class="search-box">
      <label for="f-q">Search</label>
      <input id="f-q" type="search" placeholder="Title, company, or skill…" autocomplete="off">
    </div>
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
      <select id="f-country">
        <option value="">Any country</option>
      </select>
      <input id="f-city" list="city-options" placeholder="City (e.g. Bengaluru)" autocomplete="off">
      <datalist id="city-options"></datalist>
    </details>
    <details><summary>Company</summary>
      <input id="f-company" placeholder="Company slug (e.g. anthropic)">
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
async def job_detail(
    slug: str,
    preview: int = 0,
    auth_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    job = (await db.execute(select(Job).where(Job.slug == slug))).scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Job not found")

    # Admin preview bypass: draft/rejected jobs viewable with ?preview=1 when
    # the caller has an admin session cookie. Published/expired stay public.
    is_preview = False
    if job.status not in ("published", "expired"):
        if preview and auth_token:
            from app.auth.jwt import verify_token
            u = await verify_token(auth_token, db)
            if u and u.is_admin:
                is_preview = True
        if not is_preview:
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
    preview_banner = (
        '<p style="background:#2a1f08;border:1px solid rgba(232,168,73,.5);color:#e8a849;'
        'padding:10px 16px;border-radius:4px;margin:0 0 18px;font-family:\'IBM Plex Mono\',monospace;'
        'font-size:12px;letter-spacing:.08em">'
        '⚠ ADMIN PREVIEW · status=' + esc(job.status) + ' · not visible to public</p>'
    ) if is_preview else ""
    robots_tag = '<meta name="robots" content="noindex">' if (is_expired or is_preview) else ""

    skills = d.get("must_have_skills") or []
    nice_skills = d.get("nice_to_have_skills") or []
    topics = d.get("topic") or []
    skills_html = " ".join(f'<span class="chip">{esc(s)}</span>' for s in skills)
    nice_skills_html = " ".join(f'<span class="chip">{esc(s)}</span>' for s in nice_skills)
    topics_html = " ".join(f'<span class="chip">{esc(t)}</span>' for t in topics)

    # Highlights grid — above-the-fold, scannable summary so readers don't have
    # to parse the raw JD for basics. Pulled from enriched fields.
    yrs = emp.get("experience_years") or {}
    yrs_label = _yrs_label(yrs.get("min"), yrs.get("max"))
    salary_label = ""
    if salary.get("disclosed") and salary.get("currency"):
        mn, mx = salary.get("min"), salary.get("max")
        cur = salary.get("currency")
        if mn and mx:
            salary_label = f"{cur} {mn:,}–{mx:,}"
        elif mn:
            salary_label = f"{cur} {mn:,}+"
        elif mx:
            salary_label = f"up to {cur} {mx:,}"
    highlights = [
        ("Role", job.designation),
        ("Seniority", d.get("seniority") or ""),
        ("Experience", yrs_label),
        ("Workplace", loc.get("remote_policy") or ""),
        ("Location", loc_str),
        ("Type", emp.get("job_type") or ""),
        ("Shift", emp.get("shift") or ""),
        ("Salary", salary_label),
    ]
    highlights_html = "".join(
        f'<div class="hl-cell"><div class="hl-k">{esc(k)}</div>'
        f'<div class="hl-v">{esc(v) if v else "—"}</div></div>'
        for k, v in highlights
    )

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
{preview_banner}
{expired_banner}
{f'<div class="tldr">{esc(d.get("tldr") or "")}</div>' if d.get("tldr") else ""}
<p><a class="apply" href="{esc(apply_url)}" rel="nofollow sponsored" target="_blank">Apply on {esc(company.get('name') or 'company site')} →</a></p>

<div class="hl-grid">{highlights_html}</div>

<div class="skills-block">
  <div class="skills-row"><span class="skills-label">Must-have skills</span><div>{skills_html or "<em>Not specified</em>"}</div></div>
  {f'<div class="skills-row"><span class="skills-label">Nice to have</span><div>{nice_skills_html}</div></div>' if nice_skills else ""}
  {f'<div class="skills-row"><span class="skills-label">Topics</span><div>{topics_html}</div></div>' if topics else ""}
</div>
{modules_html}
<div id="match-box" style="display:none;background:#1a2029;border:1px solid #2a323d;padding:16px 20px;border-radius:8px;margin:20px 0"></div>

<details class="jd-wrap" open>
  <summary>Full job description</summary>
  <div class="jd" id="jd-body">{d.get("description_html") or ""}</div>
</details>
<script>
// Break up wall-of-text JDs: if the rendered JD has fewer than 2 block-level
// children, sentence-split the plain text into readable paragraphs client-side.
(function enhanceJD(){{
  const el = document.getElementById('jd-body'); if (!el) return;
  const blocks = el.querySelectorAll('p, h1, h2, h3, h4, ul, ol, li, div');
  if (blocks.length >= 3) return;
  const text = el.innerText || el.textContent || '';
  if (text.length < 400) return;
  const chunks = text.split(/\\n{{2,}}|(?<=[.!?])\\s+(?=[A-Z])/).map(s => s.trim()).filter(s => s.length > 0);
  if (chunks.length < 2) return;
  // Group into paragraphs ~3-4 sentences each for readability.
  const paras = [];
  let buf = [];
  for (const s of chunks) {{
    buf.push(s);
    if (buf.join(' ').length > 280) {{ paras.push(buf.join(' ')); buf = []; }}
  }}
  if (buf.length) paras.push(buf.join(' '));
  el.innerHTML = paras.map(p => '<p>' + p.replace(/[<>]/g, c => c === '<' ? '&lt;' : '&gt;') + '</p>').join('');
}})();
</script>
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
    const gapWeeks = (m.gap_weeks||[]);
    const noCurr = (m.skills_without_curriculum||[]);
    let gap = '';
    if (!missing.length) {{
      gap = `<p style="margin:12px 0 0;color:#6db585">You match every listed must-have skill. 👏</p>`;
    }} else {{
      gap = `<p style="margin:14px 0 6px"><b style="color:#e8a849;font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.12em;text-transform:uppercase">Close the gap</b></p>`;
      gap += `<p style="margin:0 0 10px;font-size:13px;color:#c0c4cc">Missing: ${{missing.map(s => `<span class=\\"chip\\">${{s.replace(/[<>]/g,'')}}</span>`).join(" ")}}</p>`;
      if (gapWeeks.length) {{
        gap += `<p style="margin:10px 0 4px;font-size:12px;color:#94a3b8">Our curriculum teaches these in:</p><ul style="margin:0 0 8px 0;padding-left:20px;color:#e8e4d8;font-size:13px">`;
        for (const w of gapWeeks) {{
          const safeTitle = (w.title||'').replace(/[<>]/g,'');
          gap += `<li style="margin:3px 0"><a href="/account" style="color:#e8a849">${{safeTitle}}</a> <span style="color:#94a3b8;font-size:11px;font-family:'IBM Plex Mono',monospace">· Month ${{w.month}}, Week ${{w.week_num}}</span></li>`;
        }}
        gap += `</ul><a href="/" style="display:inline-block;margin-top:8px;padding:7px 14px;background:#e8a849;color:#0f1419;text-decoration:none;border-radius:4px;font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.12em;text-transform:uppercase;font-weight:500">Enroll in a plan →</a>`;
      }}
      if (noCurr.length) {{
        gap += `<p style="margin:10px 0 0;font-size:12px;color:#94a3b8">Not yet covered by our curriculum: ${{noCurr.map(s => `<span class=\\"chip\\" style=\\"opacity:.7\\">${{s.replace(/[<>]/g,'')}}</span>`).join(" ")}}</p>`;
      }}
    }}
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
  .layout{display:grid;grid-template-columns:260px 1fr;gap:32px;margin-top:8px;align-items:start}
  .filters{position:sticky;top:80px;max-height:calc(100vh - 100px);overflow-y:auto;padding-right:4px}
  .search-box{background:#1a2029;border:1px solid #2a323d;border-radius:6px;padding:12px 14px;margin-bottom:12px}
  .search-box label{display:block;font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:#e8a849;font-weight:500;margin-bottom:8px}
  .search-box input{width:100%;padding:9px 12px;font-size:14px;background:#0f1419;color:#e8e4d8;border:1px solid #2a323d;border-radius:4px;box-sizing:border-box;font-family:'IBM Plex Sans',sans-serif}
  .search-box input:focus{outline:none;border-color:#e8a849}
  .filters details{background:#1a2029;border:1px solid #2a323d;border-radius:6px;padding:10px 14px;margin-bottom:10px}
  .filters summary{cursor:pointer;font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:#e8a849;font-weight:500}
  .filters label{display:block;font-size:13px;padding:4px 0;color:#c0c4cc;cursor:pointer}
  .filters input[type=text],.filters input:not([type]),.filters select{
    width:100%;padding:7px 10px;margin-top:6px;font-size:13px;
    background:#0f1419;color:#e8e4d8;border:1px solid #2a323d;border-radius:4px;box-sizing:border-box;
    font-family:'IBM Plex Sans',sans-serif
  }
  /* Scrollbar polish on sticky sidebar */
  .filters::-webkit-scrollbar{width:6px}
  .filters::-webkit-scrollbar-track{background:transparent}
  .filters::-webkit-scrollbar-thumb{background:#2a323d;border-radius:3px}
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
const FILTERS = ["designation","topic","remote","country","city","company","q"];
const $ = id => document.getElementById(id);

function currentFilters() {
  const posted = document.querySelector('input[name=posted]:checked');
  return {
    designation: $('f-designation').value.trim(),
    topic: $('f-topic').value.trim(),
    remote: $('f-remote').value.trim(),
    country: $('f-country').value.trim().toUpperCase(),
    city: $('f-city').value.trim(),
    company: $('f-company').value.trim().toLowerCase(),
    q: $('f-q').value.trim(),
    posted_within_days: posted ? posted.value : ""
  };
}

async function loadLocations() {
  try {
    const r = await fetch("/api/jobs/locations");
    if (!r.ok) return;
    const d = await r.json();
    const cSel = $('f-country');
    for (const c of (d.countries || [])) {
      const o = document.createElement('option');
      o.value = c.code; o.textContent = `${c.code} (${c.count})`;
      cSel.appendChild(o);
    }
    const dl = $('city-options');
    for (const c of (d.cities || [])) {
      const o = document.createElement('option');
      o.value = c.name;
      o.label = c.country ? `${c.name}, ${c.country} (${c.count})` : `${c.name} (${c.count})`;
      dl.appendChild(o);
    }
  } catch(_) {}
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
      else if (k === 'city') $('f-city').value = "";
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
['f-city','f-company'].forEach(id => {
  $(id).addEventListener('keydown', e => { if (e.key === 'Enter') loadJobs(); });
  $(id).addEventListener('change', loadJobs);
});
// Prominent search: live filter with a 250ms debounce after the user stops typing.
let _searchTimer = null;
$('f-q').addEventListener('input', () => {
  clearTimeout(_searchTimer);
  _searchTimer = setTimeout(loadJobs, 250);
});
// Auto-apply on dropdown/radio change.
['f-designation','f-topic','f-remote','f-country'].forEach(id => $(id).addEventListener('change', loadJobs));
document.querySelectorAll('input[name=posted]').forEach(x => x.addEventListener('change', loadJobs));

loadLocations();
loadJobs();
</script>
"""
