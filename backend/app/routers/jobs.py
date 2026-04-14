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
<title>AI &amp; ML Jobs — AutomateEdge</title>
<meta name="description" content="Curated AI and ML job openings from verified companies. See your match %% against your AutomateEdge learning plan.">
<link rel="canonical" href="{esc(base)}/jobs">
<meta property="og:title" content="AI &amp; ML Jobs — AutomateEdge">
<meta property="og:description" content="Curated AI and ML job openings from verified companies.">
<meta property="og:type" content="website">
{_BASE_CSS}
{_HUB_CSS}
</head><body>
<h1>AI &amp; ML Jobs</h1>
<p class="meta">Curated from verified company career pages. Updated daily.</p>

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
</body></html>"""
    return HTMLResponse(html, headers={"Cache-Control": "public, max-age=600"})


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
<div id="match-box" style="display:none;background:#f7f9fc;border:1px solid #d0dce8;padding:.8rem 1rem;border-radius:6px;margin:1rem 0"></div>
<div class="jd">{d.get("description_html") or ""}</div>
<script>
(async () => {{
  try {{
    const r = await fetch("/api/jobs/{esc(job.slug)}/match", {{credentials:"include"}});
    if (!r.ok) return;
    const m = await r.json();
    const box = document.getElementById("match-box");
    const tone = m.score >= 70 ? "#0a7" : m.score >= 40 ? "#d88600" : "#888";
    const missing = (m.missing_skills||[]);
    const gap = missing.length
      ? `<p><b>Close the gap:</b> ${{missing.map(s => `<span class=\\"chip\\">${{s.replace(/[<>]/g,'')}}</span>`).join(" ")}}</p>`
      : `<p>You match every listed must-have skill. 👏</p>`;
    box.innerHTML = `
      <div style="display:flex;align-items:center;gap:1rem">
        <div style="background:${{tone}};color:#fff;padding:.4rem .8rem;border-radius:4px;font-weight:700;font-size:1.2rem">${{m.score}}% match</div>
        <div>Based on your linked repos + experience level.</div>
      </div>
      ${{gap}}`;
    box.style.display = "block";
  }} catch(_) {{}}
}})();
</script>
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
  .layout{display:grid;grid-template-columns:240px 1fr;gap:1.5rem;margin-top:1rem}
  .filters details{border:1px solid #e4e4e4;border-radius:4px;padding:.4rem .7rem;margin-bottom:.5rem;background:#fafafa}
  .filters summary{cursor:pointer;font-weight:600;font-size:.9rem}
  .filters label{display:block;font-size:.85rem;padding:.2rem 0}
  .filters input[type=text],.filters input:not([type]),.filters select{
    width:100%;padding:.35rem;margin-top:.3rem;font-size:.85rem;
    border:1px solid #ccc;border-radius:3px;box-sizing:border-box
  }
  .apply-btn{width:100%;padding:.5rem;background:#0a7;color:#fff;border:0;border-radius:4px;cursor:pointer;margin-top:.5rem}
  .clear-btn{width:100%;padding:.4rem;background:#fff;color:#555;border:1px solid #ccc;border-radius:4px;cursor:pointer;margin-top:.3rem;font-size:.85rem}
  .chips-row{margin-bottom:.5rem}
  .chips-row .filter-chip{background:#1a1a1a;color:#fff;padding:2px 8px;border-radius:3px;font-size:.75rem;margin-right:4px;cursor:pointer}
  .chips-row .filter-chip::after{content:" ×";opacity:.7}
  .card{position:relative}
  .match-ring{position:absolute;top:.8rem;right:1rem;width:44px;height:44px;border-radius:50%;
    display:flex;align-items:center;justify-content:center;font-size:.8rem;font-weight:700;color:#fff}
  .match-ring.high{background:#0a7}
  .match-ring.mid{background:#d88600}
  .match-ring.low{background:#888}
  .empty{padding:2rem;text-align:center;color:#888}
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
  const locStr = [loc.city, loc.country, loc.remote_policy].filter(Boolean).join(" · ");
  const verified = j.verified ? '<span class="chip verified">✓ Verified</span>' : '';
  return `<div class="card" data-slug="${esc(j.slug)}">
    <div class="match-ring" id="match-${esc(j.slug)}" style="display:none"></div>
    <h3><a href="/jobs/${esc(j.slug)}">${esc(j.title)}</a></h3>
    <div class="meta">${esc(co.name||j.company?.slug||'')} · ${esc(locStr||'—')} · ${esc(j.posted_on||'')}</div>
    <div><span class="chip">${esc(j.designation||'')}</span> ${verified}</div>
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
