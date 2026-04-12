"""
Admin pipeline router — auto-discovery, batch generation, content refresh, settings.

All endpoints under /admin/pipeline (prefix set in main.py). Protected by get_current_admin.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from html import escape as esc

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pydantic import BaseModel, Field
from typing import Optional

from app.auth.deps import get_current_admin
from app.db import get_db
from app.models.curriculum import AICostLimit, AIUsageLog, CurriculumSettings, DiscoveredTopic
from app.models.user import User


class PipelineSettingsUpdate(BaseModel):
    """Validated settings update body."""
    max_topics_per_discovery: Optional[int] = Field(None, ge=1, le=50)
    discovery_frequency: Optional[str] = Field(None, pattern=r"^(weekly|monthly|quarterly)$")
    auto_approve_topics: Optional[bool] = None
    auto_generate_variants: Optional[bool] = None
    ai_model_research: Optional[str] = Field(None, pattern=r"^(gemini|groq|cerebras|mistral|deepseek|sambanova)$")
    ai_model_formatting: Optional[str] = Field(None, pattern=r"^(gemini|groq|cerebras|mistral|deepseek|sambanova)$")
    max_tokens_per_run: Optional[int] = Field(None, ge=0, le=1000000)
    refresh_frequency: Optional[str] = Field(None, pattern=r"^(monthly|quarterly)$")

router = APIRouter()

ADMIN_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,400;9..144,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');
body { font-family: 'IBM Plex Sans', system-ui, sans-serif; background: #0f1419; color: #e0dbd2; margin: 0; padding: 0; -webkit-font-smoothing: antialiased; font-size: 14px; line-height: 1.6; }
.page { max-width: 100%; margin: 0; padding: 32px 48px; }
h1 { font-family: 'Fraunces', Georgia, serif; color: #e8a849; font-size: 28px; font-weight: 300; margin-bottom: 4px; }
h2 { font-family: 'Fraunces', Georgia, serif; color: #e8a849; font-size: 18px; margin-top: 24px; }
h3 { font-family: 'Fraunces', Georgia, serif; color: #e8a849; font-size: 15px; margin-top: 16px; }
p { color: #b0aaa0; line-height: 1.6; }
.subtitle { color: #6a7280; font-size: 13px; margin-bottom: 24px; font-family: 'IBM Plex Mono', monospace; letter-spacing: 0.03em; }
.stat { display: inline-block; background: #1d242e; padding: 16px 24px; border-radius: 6px; margin: 4px; text-align: center; }
.stat .num { font-family: 'Fraunces', Georgia, serif; font-size: 28px; font-weight: 400; color: #e8a849; }
.stat .lbl { font-family: 'IBM Plex Mono', monospace; font-size: 9px; text-transform: uppercase; letter-spacing: 0.12em; color: #6a7280; margin-top: 2px; }
table { width: 100%; border-collapse: collapse; margin-top: 12px; }
th { text-align: left; padding: 10px 8px; font-family: 'IBM Plex Mono', monospace; font-size: 10px; text-transform: uppercase; letter-spacing: 0.12em; color: #6a7280; border-bottom: 1px solid #2a323d; }
td { padding: 10px 8px; font-size: 13px; border-bottom: 1px solid #1d242e; color: #d0cbc2; }
.btn { font-family: 'IBM Plex Mono', monospace; font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; padding: 8px 14px; background: transparent; border: 1px solid #3a4452; color: #e8e2d3; cursor: pointer; transition: all 0.2s; border-radius: 2px; }
.btn:hover { border-color: #e8a849; color: #e8a849; }
.btn.success { border-color: #6db585; color: #6db585; }
.btn.success:hover { background: rgba(109,181,133,0.1); }
.btn.danger { border-color: #d97757; color: #d97757; }
.btn.danger:hover { background: rgba(217,119,87,0.1); }
.btn.primary { border-color: #e8a849; color: #e8a849; }
.btn.primary:hover { background: rgba(232,168,73,0.1); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.card { background: #1d242e; padding: 16px; border-radius: 6px; margin-bottom: 16px; }
.form-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; margin-bottom: 16px; }
@media (max-width: 900px) { .form-row { grid-template-columns: 1fr 1fr; } }
.form-group { display: flex; flex-direction: column; gap: 4px; }
.form-group label { font-family: 'IBM Plex Mono', monospace; font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #8a92a0; }
.form-group input, .form-group select { padding: 8px; background: #0f1419; border: 1px solid #2a323d; color: #f5f1e8; border-radius: 3px; font-family: 'IBM Plex Sans', system-ui, sans-serif; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
.badge.pending { background: #3d3520; color: #e8a849; }
.badge.approved { background: #1d3525; color: #6db585; }
.badge.generating { background: #1d2535; color: #5d9be8; }
.badge.generated { background: #1d3525; color: #6db585; }
.badge.rejected { background: #3d2020; color: #d97757; }
.status-msg { margin-top: 8px; font-size: 12px; }
.status-msg.ok { color: #6db585; }
.status-msg.error { color: #d97757; }
@media (max-width: 768px) { .page { padding: 20px 16px; } .stat { padding: 12px 14px; } .stat .num { font-size: 22px; } }
"""

NAV_HTML = '<link rel="stylesheet" href="/nav.css"><script src="/nav.js"></script>'


def _check_origin(request: Request) -> None:
    """Strict CSRF check: parsed hostname must match, reject if both headers absent."""
    from urllib.parse import urlparse
    origin = request.headers.get("origin") or request.headers.get("referer", "")
    host = request.headers.get("host", "")
    if not origin:
        raise HTTPException(status_code=403, detail="Missing Origin/Referer header")
    origin_host = urlparse(origin).hostname or ""
    expected_host = host.split(":")[0]  # strip port
    if origin_host != expected_host:
        raise HTTPException(status_code=403, detail="Origin mismatch")


def _topic_quality_cell(score_data: dict) -> str:
    """Render topic quality score as a colored number with tooltip."""
    s = score_data.get("composite_score", 0)
    if not s:
        return '<span style="color:#8a92a0">—</span>'
    color = "#6db585" if s >= 80 else "#e8a849" if s >= 60 else "#d97757"
    issues = score_data.get("issues", [])
    tooltip = " · ".join(issues[:3]) if issues else "No issues"
    return f'<span style="color:{color};font-weight:600;cursor:help" title="{esc(tooltip)}">{s}</span>'


async def _get_settings(db: AsyncSession) -> CurriculumSettings:
    result = await db.execute(select(CurriculumSettings).limit(1))
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = CurriculumSettings()
        db.add(settings)
        await db.flush()
    return settings


# ---- API Endpoints ----

@router.get("/api/settings")
async def get_pipeline_settings(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get current pipeline settings."""
    s = await _get_settings(db)
    return {
        "max_topics_per_discovery": s.max_topics_per_discovery,
        "discovery_frequency": s.discovery_frequency,
        "auto_approve_topics": s.auto_approve_topics,
        "auto_generate_variants": s.auto_generate_variants,
        "ai_model_research": s.ai_model_research,
        "ai_model_formatting": s.ai_model_formatting,
        "max_tokens_per_run": s.max_tokens_per_run,
        "tokens_used_this_month": s.tokens_used_this_month,
        "budget_month": s.budget_month,
        "refresh_frequency": s.refresh_frequency,
        "last_discovery_run": s.last_discovery_run.isoformat() if s.last_discovery_run else None,
        "last_generation_run": s.last_generation_run.isoformat() if s.last_generation_run else None,
        "last_refresh_run": s.last_refresh_run.isoformat() if s.last_refresh_run else None,
    }


@router.post("/api/settings")
async def update_pipeline_settings(
    request: Request,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update pipeline settings."""
    _check_origin(request)
    body = await request.json()
    validated = PipelineSettingsUpdate(**body)
    s = await _get_settings(db)

    for field, value in validated.model_dump(exclude_none=True).items():
        setattr(s, field, value)

    await db.flush()
    return {"ok": True}


@router.post("/api/run-discovery")
async def trigger_discovery(
    request: Request,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger topic discovery."""
    _check_origin(request)
    from app.services.topic_discovery import run_discovery
    result = await run_discovery(db)
    return result


@router.post("/api/run-generation")
async def trigger_generation(
    request: Request,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger batch generation for approved topics."""
    _check_origin(request)
    from app.services.batch_generator import run_batch_generation
    result = await run_batch_generation(db)
    return result


@router.post("/api/run-refine")
async def trigger_refine(
    request: Request,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Refine existing templates via AI quality pipeline to push scores toward 90+."""
    _check_origin(request)
    from app.services.quality_pipeline import refine_existing_templates
    result = await refine_existing_templates(db)
    return result


@router.post("/api/run-refresh")
async def trigger_refresh(
    request: Request,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger content refresh (link checks + currency review)."""
    _check_origin(request)
    from app.services.content_refresh import run_content_refresh
    result = await run_content_refresh(db)
    return result


@router.get("/api/topics")
async def list_topics(
    status: str = Query("", description="Filter by status"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List discovered topics (paginated)."""
    query = select(DiscoveredTopic).order_by(DiscoveredTopic.created_at.desc())
    if status:
        query = query.where(DiscoveredTopic.status == status)

    rows = (await db.execute(query.offset((page - 1) * per_page).limit(per_page))).scalars().all()
    return [
        {
            "id": t.id,
            "topic_name": t.topic_name,
            "category": t.category,
            "subcategory": t.subcategory,
            "justification": t.justification,
            "evidence_sources": json.loads(t.evidence_sources) if t.evidence_sources else [],
            "confidence_score": t.confidence_score,
            "status": t.status,
            "discovery_run": t.discovery_run,
            "ai_model_used": t.ai_model_used,
            "templates_generated": t.templates_generated,
            "generation_error": t.generation_error,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in rows
    ]


@router.get("/api/topics/quality")
async def get_topic_quality_scores(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Score all topics on 7 quality dimensions."""
    from app.services.quality_scorer import score_topic
    result = await db.execute(select(DiscoveredTopic).order_by(DiscoveredTopic.created_at.desc()))
    topics = result.scalars().all()
    return [score_topic(t) for t in topics]


@router.get("/api/topics/{topic_id}")
async def get_topic_detail(
    topic_id: int,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get full topic detail."""
    result = await db.execute(
        select(DiscoveredTopic).where(DiscoveredTopic.id == topic_id)
    )
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Topic not found")
    return {
        "id": t.id,
        "topic_name": t.topic_name,
        "category": t.category,
        "subcategory": t.subcategory,
        "justification": t.justification,
        "evidence_sources": json.loads(t.evidence_sources) if t.evidence_sources else [],
        "confidence_score": t.confidence_score,
        "status": t.status,
        "discovery_run": t.discovery_run,
        "ai_model_used": t.ai_model_used,
        "templates_generated": t.templates_generated,
        "generation_error": t.generation_error,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


@router.post("/api/topics/{topic_id}/approve")
async def approve_topic(
    topic_id: int,
    request: Request,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Approve a discovered topic for curriculum generation."""
    _check_origin(request)
    topic = await db.get(DiscoveredTopic, topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    if topic.status not in ("pending", "rejected"):
        raise HTTPException(status_code=400, detail=f"Cannot approve topic in '{topic.status}' state")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    topic.status = "approved"
    topic.reviewer_id = user.id
    topic.reviewed_at = now
    await db.flush()
    return {"ok": True, "status": "approved"}


@router.post("/api/topics/{topic_id}/reject")
async def reject_topic(
    topic_id: int,
    request: Request,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Reject a discovered topic."""
    _check_origin(request)
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    topic = await db.get(DiscoveredTopic, topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    if topic.status not in ("pending", "approved"):
        raise HTTPException(status_code=400, detail=f"Cannot reject topic in '{topic.status}' state")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    topic.status = "rejected"
    topic.reviewer_id = user.id
    topic.reviewed_at = now
    topic.reviewer_notes = body.get("notes", "")
    await db.flush()
    return {"ok": True, "status": "rejected"}


@router.get("/api/quality")
async def get_quality_scores(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Score all templates on structure, resources, checklist, progression, links."""
    from app.services.quality_scorer import score_all_templates
    return await score_all_templates(db)


@router.get("/api/quality/{template_key}")
async def get_template_quality(
    template_key: str,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Score a single template."""
    from app.services.quality_scorer import score_template
    from app.curriculum.loader import load_template
    try:
        tpl = load_template(template_key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Template not found")
    return await score_template(tpl, db)


@router.post("/api/quality/{template_key}/publish")
async def publish_template_endpoint(
    template_key: str,
    request: Request,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Publish a template if it meets the quality threshold (>= 90)."""
    _check_origin(request)
    from app.services.quality_scorer import score_template
    from app.curriculum.loader import load_template, publish_template, PUBLISH_THRESHOLD
    try:
        tpl = load_template(template_key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Template not found")

    result = await score_template(tpl, db)
    score = result["composite_score"]

    if publish_template(template_key, score):
        return {"ok": True, "status": "published", "score": score}
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Score {score} is below publish threshold ({PUBLISH_THRESHOLD}). Fix quality issues first.",
        )


@router.post("/api/quality/{template_key}/unpublish")
async def unpublish_template_endpoint(
    template_key: str,
    request: Request,
    _user: User = Depends(get_current_admin),
):
    """Unpublish a template (move back to draft)."""
    _check_origin(request)
    from app.curriculum.loader import unpublish_template
    unpublish_template(template_key)
    return {"ok": True, "status": "draft"}


@router.delete("/api/topics/{topic_id}")
async def delete_topic(
    topic_id: int,
    request: Request,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a discovered topic."""
    _check_origin(request)
    topic = await db.get(DiscoveredTopic, topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    await db.delete(topic)
    await db.flush()
    return {"ok": True}


# ---- HTML Pages ----

@router.get("/", response_class=HTMLResponse)
async def pipeline_dashboard_page(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Pipeline actions page — run discovery, generation, refresh."""
    s = await _get_settings(db)

    approved = await db.scalar(
        select(func.count()).select_from(DiscoveredTopic).where(DiscoveredTopic.status == "approved")
    ) or 0

    from app.curriculum.loader import list_templates
    template_count = len(list_templates())

    last_discovery = s.last_discovery_run.strftime("%b %d, %H:%M") if s.last_discovery_run else "Never"
    last_generation = s.last_generation_run.strftime("%b %d, %H:%M") if s.last_generation_run else "Never"
    last_refresh = s.last_refresh_run.strftime("%b %d, %H:%M") if s.last_refresh_run else "Never"

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Pipeline</title>
<style>{ADMIN_CSS}</style></head><body>
{NAV_HTML}
<div class="page">
<h1>Pipeline Actions</h1>
<div class="subtitle">Run tasks, review pipeline status · Provider health on <a href="/admin/pipeline/ai-usage" style="color:#e8a849">AI Usage</a></div>

<div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:16px;margin-bottom:24px">

<div class="card">
  <h3>1. Discover Topics</h3>
  <p style="font-size:12px;color:#8a92a0">AI finds trending AI/ML topics from universities, papers, and industry.</p>
  <p style="font-size:12px">Last run: {esc(last_discovery)}</p>
  <p style="font-size:12px">Discovers: {s.max_topics_per_discovery} topic(s) per run</p>
  <button class="btn primary" onclick="runAction('run-discovery', this)">Run Discovery Now</button>
  <div id="status-discovery" class="status-msg"></div>
</div>

<div class="card">
  <h3>2. Generate Curricula</h3>
  <p style="font-size:12px;color:#8a92a0">Creates study plans (3mo/6mo, beginner/intermediate/advanced) for approved topics.</p>
  <p style="font-size:12px">Last run: {esc(last_generation)}</p>
  <p style="font-size:12px">Ready to generate: <strong>{approved}</strong> approved topic(s)</p>
  <button class="btn primary" onclick="runAction('run-generation', this)" {'disabled' if approved == 0 else ''}>Generate Curricula</button>
  <div id="status-generation" class="status-msg"></div>
</div>

<div class="card">
  <h3>3. Refine Quality</h3>
  <p style="font-size:12px;color:#8a92a0">AI reviews templates below 90 and surgically fixes weak dimensions.</p>
  <p style="font-size:12px">Templates to refine: <strong>{template_count}</strong></p>
  <p style="font-size:12px">Pipeline: Score → Review → Refine → Validate</p>
  <button class="btn primary" onclick="runAction('run-refine', this)">Refine Now</button>
  <div id="status-refine" class="status-msg"></div>
</div>

<div class="card">
  <h3>4. Refresh Content</h3>
  <p style="font-size:12px;color:#8a92a0">Checks resource links and reviews if content is still current.</p>
  <p style="font-size:12px">Last run: {esc(last_refresh)}</p>
  <p style="font-size:12px">Templates to check: <strong>{template_count}</strong></p>
  <button class="btn primary" onclick="runAction('run-refresh', this)">Run Refresh Now</button>
  <div id="status-refresh" class="status-msg"></div>
</div>

</div>

<h2>Pipeline Status</h2>
<div id="norm-data"><em style="color:#8a92a0">Loading pipeline stats...</em></div>

<h2>Template Quality Scores</h2>
<div id="quality-data"><em style="color:#8a92a0">Scoring templates...</em></div>

<script>
// Load normalization stats inline
(async function() {{
  try {{
    const resp = await fetch('/admin/pipeline/api/normalization', {{credentials: 'same-origin'}});
    const d = await resp.json();
    const disc = d.discovery, gen = d.generation, ref = d.refresh, cache = d.cache;

    const linkPct = ref.total_links > 0 ? Math.round(ref.ok_links / ref.total_links * 100) : 100;
    const catHtml = disc.categories.map(c =>
      `<span style="display:inline-block;background:#0f1419;padding:2px 8px;border-radius:10px;font-size:12px;margin:2px">${{c.category}} <strong>${{c.count}}</strong></span>`
    ).join('');

    let topicRows = '';
    for (const t of gen.per_topic) {{
      const cls = t.status === 'generated' ? 'approved' : t.status === 'approved' ? 'pending' : 'rejected';
      topicRows += `<tr>
        <td style="max-width:250px;overflow:hidden;text-overflow:ellipsis">${{t.topic}}</td>
        <td>${{t.variants}}/5</td>
        <td><span class="badge ${{cls}}">${{t.status}}</span></td>
        <td style="font-size:12px;color:#d97757;max-width:250px;overflow:hidden;text-overflow:ellipsis">${{t.error}}</td>
      </tr>`;
    }}

    document.getElementById('norm-data').innerHTML = `
      <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px">
        <div class="stat"><div class="num">${{disc.total_topics}}</div><div class="lbl">Topics</div></div>
        <div class="stat"><div class="num">${{disc.status_counts.pending}}</div><div class="lbl">Pending</div></div>
        <div class="stat"><div class="num">${{disc.status_counts.generated}}</div><div class="lbl">Generated</div></div>
        <div class="stat"><div class="num">${{disc.status_counts.rejected}}</div><div class="lbl">Rejected</div></div>
        <div class="stat"><div class="num">${{gen.templates_on_disk}}</div><div class="lbl">Templates</div></div>
        <div class="stat"><div class="num">${{disc.avg_confidence}}</div><div class="lbl">Avg Score</div></div>
        <div class="stat"><div class="num" style="color:${{linkPct < 80 ? '#d97757' : '#6db585'}}">${{linkPct}}%</div><div class="lbl">Link Health</div></div>
        <div class="stat"><div class="num">${{cache.total_files}}</div><div class="lbl">Cached</div></div>
      </div>
      <div style="margin-bottom:16px">${{catHtml || ''}}</div>
      ${{topicRows ? '<h3 style="margin-top:8px">Generation by Topic</h3><div style="max-height:300px;overflow-y:auto"><table><tr><th>Topic</th><th>Variants</th><th>Status</th><th>Errors</th></tr>' + topicRows + '</table></div>' : ''}}

      <h2 style="margin-top:32px;font-family:Fraunces,Georgia,serif;color:#e8a849;font-size:18px">Pipeline Stages</h2>
      <p style="font-size:12px;color:#8a92a0;margin-bottom:4px">Every topic goes through these stages before becoming a course. Stages marked with <span style="color:#e8a849">AI</span> use AI providers and consume budget.</p>
      <p style="font-size:12px;color:#6a7280;margin-bottom:14px"><span style="color:#e8a849">■</span> Data cleanup · <span style="color:#5d9be8">■</span> AI enrichment · <span style="color:#6db585">■</span> Process control · <span style="color:#d97757">■</span> Maintenance</p>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
        <div style="background:#1d242e;padding:16px 18px;border-radius:6px;border-left:3px solid #e8a849">
          <div style="font-size:14px;font-weight:600;margin-bottom:6px">1. Name Normalization</div>
          <div style="font-size:12px;color:#8a92a0;line-height:1.5">Cleans topic names — lowercased, special characters removed, creates a unique key. Prevents "LLMs" and "llms" from creating duplicates.</div>
        </div>
        <div style="background:#1d242e;padding:16px 18px;border-radius:6px;border-left:3px solid #e8a849">
          <div style="font-size:14px;font-weight:600;margin-bottom:6px">2. Deduplication</div>
          <div style="font-size:12px;color:#8a92a0;line-height:1.5">Checks if a topic already exists by its normalized name. Duplicates are skipped silently. Safe to re-run discovery.</div>
        </div>
        <div style="background:#1d242e;padding:16px 18px;border-radius:6px;border-left:3px solid #5d9be8">
          <div style="font-size:14px;font-weight:600;margin-bottom:6px"><span style="color:#e8a849">AI</span> 3. Topic Discovery</div>
          <div style="font-size:12px;color:#8a92a0;line-height:1.5">AI researches trending topics from universities, papers, and industry. Uses the research model (Gemini/Groq/Mistral) from the fallback chain. Costs ~3,000 tokens per run.</div>
        </div>
        <div style="background:#1d242e;padding:16px 18px;border-radius:6px;border-left:3px solid #5d9be8">
          <div style="font-size:14px;font-weight:600;margin-bottom:6px"><span style="color:#e8a849">AI</span> 4. Triage Classifier</div>
          <div style="font-size:12px;color:#8a92a0;line-height:1.5">A cheap, fast AI classifier filters each topic: "Worth generating a course?" Uses the cheapest available model (Groq). Costs ~200 tokens per topic. Filters ~80% of low-value topics.</div>
        </div>
        <div style="background:#1d242e;padding:16px 18px;border-radius:6px;border-left:3px solid #5d9be8">
          <div style="font-size:14px;font-weight:600;margin-bottom:6px"><span style="color:#e8a849">AI</span> 5. Curriculum Generation</div>
          <div style="font-size:12px;color:#8a92a0;line-height:1.5">AI creates full study plans — weeks, resources, checklists, deliverables. Generates up to 5 variants per topic (3mo/6mo × levels). Costs ~5,000 tokens per variant. The most expensive stage.</div>
        </div>
        <div style="background:#1d242e;padding:16px 18px;border-radius:6px;border-left:3px solid #5d9be8">
          <div style="font-size:14px;font-weight:600;margin-bottom:6px"><span style="color:#e8a849">AI</span> 6. Currency Review</div>
          <div style="font-size:12px;color:#8a92a0;line-height:1.5">During content refresh, AI reviews each template: "Is this content still current?" Checks if topics, frameworks, or best practices have changed. Flags stale content for update.</div>
        </div>
        <div style="background:#1d242e;padding:16px 18px;border-radius:6px;border-left:3px solid #6db585">
          <div style="font-size:14px;font-weight:600;margin-bottom:6px">7. Schema Validation</div>
          <div style="font-size:12px;color:#8a92a0;line-height:1.5">Every AI response is validated against a strict schema — required fields, value ranges, correct types. Malformed data is rejected and the next provider is tried.</div>
        </div>
        <div style="background:#1d242e;padding:16px 18px;border-radius:6px;border-left:3px solid #6db585">
          <div style="font-size:14px;font-weight:600;margin-bottom:6px">8. Lifecycle State Machine</div>
          <div style="font-size:12px;color:#8a92a0;line-height:1.5"><strong>Pending</strong> → <strong>Approved</strong> → <strong>Generating</strong> → <strong>Generated</strong>. Each transition is tracked. Topics can be <strong>Rejected</strong> and later re-approved.</div>
        </div>
        <div style="background:#1d242e;padding:16px 18px;border-radius:6px;border-left:3px solid #d97757">
          <div style="font-size:14px;font-weight:600;margin-bottom:6px">9. Budget Gating</div>
          <div style="font-size:12px;color:#8a92a0;line-height:1.5">&lt;80%: normal · 80-90%: warning · 90-100%: fallback to cheaper models · &gt;100%: hard stop. Checked before every AI call.</div>
        </div>
        <div style="background:#1d242e;padding:16px 18px;border-radius:6px;border-left:3px solid #d97757">
          <div style="font-size:14px;font-weight:600;margin-bottom:6px">10. Cache &amp; Link Health</div>
          <div style="font-size:12px;color:#8a92a0;line-height:1.5">AI responses cached (24h–30d TTL). Resource URLs checked periodically — broken links flagged, private IPs blocked (SSRF protection).</div>
        </div>
      </div>
    `;
  }} catch(e) {{
    document.getElementById('norm-data').innerHTML = '<p style="color:#d97757">Failed to load stats</p>';
  }}
}})();

// Load quality scores
(async function() {{
  try {{
    const resp = await fetch('/admin/pipeline/api/quality', {{credentials: 'same-origin'}});
    const data = await resp.json();
    if (!data.length) {{
      document.getElementById('quality-data').innerHTML = '<p style="color:#8a92a0">No templates to score yet.</p>';
      return;
    }}

    // Summary stats
    const avg = Math.round(data.reduce((s, t) => s + t.composite_score, 0) / data.length);
    const lowest = data[0];
    const highest = data[data.length - 1];
    const issueCount = data.reduce((s, t) => s + (t.issues || []).length, 0);

    function scoreColor(s) {{ return s >= 70 ? '#6db585' : s >= 40 ? '#e8a849' : '#d97757'; }}
    function bar(score, label) {{
      return `<div style="display:flex;align-items:center;gap:6px;margin:2px 0">
        <span style="font-size:12px;color:#8a92a0;width:70px">${{label}}</span>
        <div style="flex:1;background:#0f1419;border-radius:2px;height:8px;max-width:120px">
          <div style="width:${{score}}%;height:100%;background:${{scoreColor(score)}};border-radius:2px"></div>
        </div>
        <span style="font-size:12px;color:${{scoreColor(score)}}">${{score}}</span>
      </div>`;
    }}

    let rows = '';
    for (const t of data) {{
      const c = t.composite_score;
      const s = t.scores || {{}};
      const d = t.details || {{}};
      const issueList = (t.issues || []).slice(0, 3).map(i =>
        `<div style="font-size:12px;color:#d97757">• ${{i}}</div>`
      ).join('');
      const pub = t.publish_status === 'published';
      const canPublish = t.publishable;
      const statusBadge = pub
        ? '<span style="background:#1d3525;color:#6db585;padding:2px 8px;border-radius:10px;font-size:11px">Published</span>'
        : '<span style="background:#2a2520;color:#e8a849;padding:2px 8px;border-radius:10px;font-size:11px">Draft</span>';
      const pubBtn = pub
        ? `<button class="btn" style="font-size:11px;padding:4px 10px;margin-top:4px" onclick="togglePublish('${{t.key}}','unpublish',this)">Unpublish</button>`
        : (canPublish
          ? `<button class="btn primary" style="font-size:11px;padding:4px 10px;margin-top:4px" onclick="togglePublish('${{t.key}}','publish',this)">Publish</button>`
          : `<div style="font-size:11px;color:#8a92a0;margin-top:4px">Score &lt; ${{t.publish_threshold}} — fix issues first</div>`);
      rows += `<tr>
        <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis">
          <strong><a href="/admin/templates/${{t.key}}" style="color:#e8a849">${{t.title || t.key}}</a></strong>
          <div style="font-size:12px;color:#8a92a0">${{t.level}} · ${{t.duration_months}}mo · ${{d.total_weeks || 0}} weeks</div>
          <div style="margin-top:4px">${{statusBadge}}</div>
          ${{pubBtn}}
        </td>
        <td style="text-align:center"><span style="font-size:20px;font-family:'Fraunces',serif;color:${{scoreColor(c)}}">${{c}}</span></td>
        <td style="min-width:200px">
          ${{bar(s.blooms_progression || 0, "Bloom's")}}
          ${{bar(s.theory_practice || 0, 'Theory/Practice')}}
          ${{bar(s.project_density || 0, 'Projects')}}
          ${{bar(s.assessment_quality || 0, 'Assessment')}}
          ${{bar(s.completeness || 0, 'Completeness')}}
          ${{bar(s.difficulty_calibration || 0, 'Difficulty')}}
          ${{bar(s.industry_alignment || 0, 'Industry')}}
          ${{bar(s.freshness || 0, 'Freshness')}}
          ${{bar(s.prerequisites_clarity || 0, 'Prerequisites')}}
          ${{bar(s.real_world_readiness || 0, 'Readiness')}}
          <div style="border-top:1px solid #333;margin:4px 0;padding-top:4px">
          ${{bar(s.structure || 0, 'Structure')}}
          ${{bar(s.resources || 0, 'Resources')}}
          ${{bar(s.checklist || 0, 'Checklist')}}
          ${{bar(s.progression || 0, 'Progression')}}
          ${{bar(s.links || 0, 'Links')}}
          </div>
        </td>
        <td style="font-size:12px">
          ${{d.practice_pct || 0}}% practice · ${{d.project_density_pct || 0}}% projects
          <div style="color:#8a92a0">${{d.total_resources || 0}} resources · ${{d.unique_domains || 0}} domains · ${{d.reputable_pct || 0}}% reputable</div>
          <div style="color:#8a92a0">${{d.completeness_pct || 0}}% topics · ${{d.measurable_pct || 0}}% measurable</div>
          <div style="color:#6db585;font-size:11px">${{(d.industry_tools || []).slice(0,5).join(', ')}}</div>
        </td>
        <td style="max-width:250px">${{issueList || '<span style="color:#6db585;font-size:12px">No issues</span>'}}</td>
      </tr>`;
    }}

    document.getElementById('quality-data').innerHTML = `
      <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px">
        <div class="stat"><div class="num" style="color:${{scoreColor(avg)}}">${{avg}}</div><div class="lbl">Avg Score</div></div>
        <div class="stat"><div class="num">${{data.length}}</div><div class="lbl">Templates</div></div>
        <div class="stat"><div class="num" style="color:#d97757">${{issueCount}}</div><div class="lbl">Total Issues</div></div>
        <div class="stat"><div class="num" style="color:${{scoreColor(lowest.composite_score)}}">${{lowest.composite_score}}</div><div class="lbl">Lowest</div></div>
        <div class="stat"><div class="num" style="color:${{scoreColor(highest.composite_score)}}">${{highest.composite_score}}</div><div class="lbl">Highest</div></div>
      </div>
      <div style="max-height:500px;overflow-y:auto">
      <table>
        <tr><th>Template</th><th>Score</th><th>Breakdown</th><th>Details</th><th>Issues</th></tr>
        ${{rows}}
      </table>
      </div>
    `;
  }} catch(e) {{
    document.getElementById('quality-data').innerHTML = '<p style="color:#d97757">Failed to load: ' + e.message + '</p>';
  }}
}})();


async function runAction(action, btn) {{
  btn.disabled = true;
  const origText = btn.textContent;
  btn.textContent = 'Running...';
  const statusEl = document.getElementById('status-' + action.replace('run-', ''));
  statusEl.textContent = 'Processing... this may take 30-60 seconds.';
  statusEl.className = 'status-msg';
  try {{
    const resp = await fetch('/admin/pipeline/api/' + action, {{
      method: 'POST', credentials: 'same-origin'
    }});
    const data = await resp.json();
    if (resp.ok && data.status !== 'ai_error' && data.status !== 'budget_exceeded') {{
      let msg = '';
      if (data.total_discovered !== undefined) msg = data.total_discovered + ' topic(s) discovered, ' + data.saved + ' saved';
      else if (data.generated !== undefined) msg = data.generated + ' curricula generated, ' + data.errors + ' failed';
      else if (data.improved !== undefined) msg = data.improved + ' improved, ' + data.skipped + ' skipped, ' + data.failed + ' failed';
      else msg = JSON.stringify(data).substring(0, 150);
      statusEl.textContent = '✓ ' + msg;
      statusEl.className = 'status-msg ok';
      setTimeout(() => window.location.reload(), 2000);
    }} else {{
      statusEl.textContent = '✗ ' + (data.error || data.detail || 'Failed');
      statusEl.className = 'status-msg error';
    }}
  }} catch(e) {{
    statusEl.textContent = '✗ ' + e.message;
    statusEl.className = 'status-msg error';
  }}
  btn.disabled = false;
  btn.textContent = origText;
}}

async function togglePublish(key, action, btn) {{
  btn.disabled = true;
  btn.textContent = 'Working...';
  try {{
    const resp = await fetch('/admin/pipeline/api/quality/' + key + '/' + action, {{
      method: 'POST', credentials: 'same-origin'
    }});
    const data = await resp.json();
    if (resp.ok) {{
      window.location.reload();
    }} else {{
      alert(data.detail || 'Failed: ' + JSON.stringify(data));
      btn.disabled = false;
      btn.textContent = action === 'publish' ? 'Publish' : 'Unpublish';
    }}
  }} catch(e) {{
    alert('Error: ' + e.message);
    btn.disabled = false;
    btn.textContent = action === 'publish' ? 'Publish' : 'Unpublish';
  }}
}}
</script>
</div>
</body></html>"""


@router.get("/topics", response_class=HTMLResponse)
async def pipeline_topics_page(
    status: str = Query("", description="Filter by status"),
    page: int = Query(1, ge=1),
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Discovered topics management page (paginated)."""
    query = select(DiscoveredTopic).order_by(DiscoveredTopic.created_at.desc())
    if status:
        query = query.where(DiscoveredTopic.status == status)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (await db.execute(query.offset((page - 1) * 50).limit(50))).scalars().all()

    # Compute quality scores for each topic
    from app.services.quality_scorer import score_topic
    topic_scores = {score_topic(t)["id"]: score_topic(t) for t in rows}

    # Status filter links
    statuses = ["", "pending", "approved", "generating", "generated", "rejected"]
    filter_html = " ".join(
        f'<a href="/admin/pipeline/topics?status={s}" class="btn {"primary" if s == status else ""}">{s or "All"}</a>'
        for s in statuses
    )

    rows_html = ""
    for t in rows:
        sources = []
        try:
            sources = json.loads(t.evidence_sources) if t.evidence_sources else []
        except Exception:
            pass
        sources_str = ", ".join(sources[:3])

        actions = ""
        if t.status == "pending":
            actions = f'''<button class="btn success" onclick="topicAction({t.id},'approve')">Approve</button>
                         <button class="btn danger" onclick="topicAction({t.id},'reject')">Reject</button>'''
        elif t.status == "approved":
            actions = f'<button class="btn danger" onclick="topicAction({t.id},\'reject\')">Reject</button>'
        elif t.status == "rejected":
            actions = f'<button class="btn success" onclick="topicAction({t.id},\'approve\')">Re-approve</button>'

        actions += f' <button class="btn" onclick="deleteTopic({t.id})" title="Delete">×</button>'

        error_html = ""
        if t.generation_error:
            error_html = f'<div style="color:#d97757;font-size:12px;margin-top:2px">{esc(t.generation_error[:100])}</div>'

        rows_html += f"""<tr>
<td>{t.id}</td>
<td><strong><a href="#" onclick="viewTopic({t.id});return false" style="color:#e8a849">{esc(t.topic_name)}</a></strong><div style="font-size:12px;color:#8a92a0">{esc(t.category)}{(' / ' + esc(t.subcategory)) if t.subcategory else ''}</div></td>
<td style="font-size:12px;max-width:300px">{esc(t.justification[:150])}{'...' if len(t.justification) > 150 else ''}</td>
<td>{t.confidence_score}</td>
<td style="text-align:center">{_topic_quality_cell(topic_scores.get(t.id, {}))}</td>
<td><span class="badge {t.status}">{t.status}</span>{error_html}</td>
<td>{t.templates_generated}</td>
<td style="font-size:12px">{t.created_at.strftime('%Y-%m-%d') if t.created_at else ''}</td>
<td>{actions}</td>
</tr>"""

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Topics</title>
<style>{ADMIN_CSS}</style></head><body>
{NAV_HTML}
<div class="page">
<h1>Discovered Topics ({len(rows)})</h1>
<div class="subtitle">AI-discovered trending topics for curriculum generation</div>
<div style="background:#1d242e;padding:12px 16px;border-radius:6px;margin-bottom:16px;font-size:13px;color:#8a92a0;line-height:1.6">
    <strong style="color:#d0cbc2">Workflow:</strong>
    Discover topics (Pipeline page) &rarr; <strong style="color:#6db585">Approve</strong> here &rarr; Generate Curricula (Pipeline page) &rarr; AI creates 5 template variants per approved topic &rarr; Review &amp; Publish
</div>
<div style="margin-bottom:16px">{filter_html}</div>

<table>
<tr><th>ID</th><th>Topic</th><th>Justification</th><th>Confidence</th><th>Quality</th><th>Status</th><th>Templates</th><th>Discovered</th><th>Actions</th></tr>
{rows_html}
</table>

<script>
async function topicAction(id, action) {{
  const resp = await fetch('/admin/pipeline/api/topics/' + id + '/' + action, {{
    method: 'POST', credentials: 'same-origin',
    headers: {{'Content-Type': 'application/json'}},
    body: '{{}}'
  }});
  if (resp.ok) window.location.reload();
  else alert('Failed: ' + (await resp.json()).detail);
}}

async function deleteTopic(id) {{
  if (!confirm('Delete this topic?')) return;
  const resp = await fetch('/admin/pipeline/api/topics/' + id, {{
    method: 'DELETE', credentials: 'same-origin'
  }});
  if (resp.ok) window.location.reload();
  else alert('Failed');
}}

async function viewTopic(id) {{
  const modal = document.getElementById('topicModal');
  const content = document.getElementById('topicContent');
  content.innerHTML = 'Loading...';
  modal.style.display = 'flex';
  try {{
    const resp = await fetch('/admin/pipeline/api/topics/' + id, {{credentials: 'same-origin'}});
    const t = await resp.json();
    const sources = (t.evidence_sources || []).map(s => '<li>' + s + '</li>').join('');
    content.innerHTML = `
      <h2 style="color:#e8a849;margin:0 0 12px">${{t.topic_name}}</h2>
      <div style="margin-bottom:12px">
        <span class="badge ${{t.status}}">${{t.status}}</span>
        <span style="color:#8a92a0;margin-left:8px">Confidence: ${{t.confidence_score}}%</span>
        <span style="color:#8a92a0;margin-left:8px">Model: ${{t.ai_model_used || '—'}}</span>
      </div>
      <div style="margin-bottom:12px"><strong style="color:#d0cbc2">Category:</strong> ${{t.category}}${{t.subcategory ? ' / ' + t.subcategory : ''}}</div>
      <div style="margin-bottom:16px"><strong style="color:#d0cbc2">Justification:</strong><p style="color:#b0aaa0;line-height:1.6">${{t.justification}}</p></div>
      ${{sources ? '<div style="margin-bottom:16px"><strong style="color:#d0cbc2">Evidence Sources:</strong><ul style="color:#b0aaa0;padding-left:20px;line-height:1.8">' + sources + '</ul></div>' : ''}}
      <div style="color:#8a92a0;font-size:12px">Discovered: ${{t.created_at ? t.created_at.substring(0,10) : '—'}} · Templates generated: ${{t.templates_generated}}</div>
      ${{t.generation_error ? '<div style="color:#d97757;font-size:12px;margin-top:8px">Error: ' + t.generation_error.substring(0,200) + '</div>' : ''}}
      <div style="margin-top:16px;padding-top:12px;border-top:1px solid #2a323d">
        ${{t.status === 'pending' ? '<button class="btn success" onclick="topicAction('+t.id+',\\'approve\\');document.getElementById(\\'topicModal\\').style.display=\\'none\\'">Approve</button> <button class="btn danger" onclick="topicAction('+t.id+',\\'reject\\');document.getElementById(\\'topicModal\\').style.display=\\'none\\'">Reject</button>' : ''}}
        ${{t.status === 'approved' ? '<span style="color:#6db585;font-weight:600">✓ Approved</span> — go to Pipeline page and click "Generate Curricula" to create templates' : ''}}
        ${{t.status === 'generated' ? '<span style="color:#6db585;font-weight:600">✓ Generated</span> — ' + t.templates_generated + ' templates created. Review them in Templates page.' : ''}}
        ${{t.status === 'rejected' ? '<button class="btn success" onclick="topicAction('+t.id+',\\'approve\\');document.getElementById(\\'topicModal\\').style.display=\\'none\\'">Re-approve</button>' : ''}}
      </div>
    `;
  }} catch(e) {{
    content.innerHTML = 'Error: ' + e.message;
  }}
}}

document.getElementById('topicModal').addEventListener('click', function(e) {{
  if (e.target === this) this.style.display = 'none';
}});

</script>

<div id="topicModal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.7);z-index:100;align-items:center;justify-content:center">
  <div style="background:#1d242e;border-radius:8px;padding:24px;max-width:700px;width:90%;max-height:80vh;overflow-y:auto">
    <button onclick="document.getElementById('topicModal').style.display='none'" style="float:right;cursor:pointer;font-size:20px;color:#8a92a0;background:none;border:none">&times;</button>
    <div id="topicContent">Loading...</div>
  </div>
</div>
<div style="margin-top:12px">{'<a href="/admin/pipeline/topics?page='+str(page-1)+'&status='+esc(status)+'" class="btn">Prev</a> ' if page>1 else ''}{'<a href="/admin/pipeline/topics?page='+str(page+1)+'&status='+esc(status)+'" class="btn">Next</a>' if page*50<total else ''} <span style="font-size:12px;color:#8a92a0">{total} total</span></div>
</div>
</body></html>"""


@router.get("/settings", response_class=HTMLResponse)
async def pipeline_settings_page(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Pipeline settings configuration page."""
    s = await _get_settings(db)

    def _sel(field_val: str, option: str) -> str:
        return "selected" if field_val == option else ""

    def _chk(val: bool) -> str:
        return "checked" if val else ""

    budget_pct = 0
    if s.max_tokens_per_run > 0:
        budget_pct = int((s.tokens_used_this_month / s.max_tokens_per_run) * 100)

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Pipeline Settings</title>
<style>{ADMIN_CSS}</style></head><body>
{NAV_HTML}
<div class="page">
<h1>Pipeline Settings</h1>
<div class="subtitle">Configure auto-discovery, AI models, budget, and refresh schedule</div>

<form id="settingsForm" class="card">

<h3>Discovery</h3>
<div class="form-row">
  <div class="form-group">
    <label>Max Topics Per Discovery</label>
    <input type="number" name="max_topics_per_discovery" value="{s.max_topics_per_discovery}" min="1" max="50">
  </div>
  <div class="form-group">
    <label>Discovery Frequency</label>
    <select name="discovery_frequency">
      <option value="weekly" {_sel(s.discovery_frequency, 'weekly')}>Weekly</option>
      <option value="monthly" {_sel(s.discovery_frequency, 'monthly')}>Monthly</option>
      <option value="quarterly" {_sel(s.discovery_frequency, 'quarterly')}>Quarterly</option>
    </select>
  </div>
</div>
<div class="form-row">
  <div class="form-group">
    <label><input type="checkbox" name="auto_approve_topics" {_chk(s.auto_approve_topics)}> Auto-approve discovered topics</label>
  </div>
  <div class="form-group">
    <label><input type="checkbox" name="auto_generate_variants" {_chk(s.auto_generate_variants)}> Auto-generate variants after approval</label>
  </div>
</div>

<h3>AI Models</h3>
<div class="form-row">
  <div class="form-group">
    <label>Research Model (deep)</label>
    <select name="ai_model_research">
      <option value="gemini" {_sel(s.ai_model_research, 'gemini')}>Gemini</option>
      <option value="groq" {_sel(s.ai_model_research, 'groq')}>Groq</option>
      <option value="cerebras" {_sel(s.ai_model_research, 'cerebras')}>Cerebras</option>
      <option value="mistral" {_sel(s.ai_model_research, 'mistral')}>Mistral</option>
      <option value="deepseek" {_sel(s.ai_model_research, 'deepseek')}>DeepSeek</option>
      <option value="sambanova" {_sel(s.ai_model_research, 'sambanova')}>Sambanova</option>
    </select>
  </div>
  <div class="form-group">
    <label>Formatting Model (cheap)</label>
    <select name="ai_model_formatting">
      <option value="groq" {_sel(s.ai_model_formatting, 'groq')}>Groq</option>
      <option value="gemini" {_sel(s.ai_model_formatting, 'gemini')}>Gemini</option>
      <option value="cerebras" {_sel(s.ai_model_formatting, 'cerebras')}>Cerebras</option>
      <option value="mistral" {_sel(s.ai_model_formatting, 'mistral')}>Mistral</option>
      <option value="deepseek" {_sel(s.ai_model_formatting, 'deepseek')}>DeepSeek</option>
      <option value="sambanova" {_sel(s.ai_model_formatting, 'sambanova')}>Sambanova</option>
    </select>
  </div>
</div>

<h3>Budget</h3>
<div class="form-row">
  <div class="form-group">
    <label>Max Tokens Per Month</label>
    <input type="number" name="max_tokens_per_run" value="{s.max_tokens_per_run}" min="0" step="1000">
  </div>
  <div class="form-group">
    <label>Current Usage</label>
    <div style="padding:8px;font-size:14px">{s.tokens_used_this_month:,} / {s.max_tokens_per_run:,} ({budget_pct}%)</div>
  </div>
</div>

<h3>Content Refresh</h3>
<div class="form-row">
  <div class="form-group">
    <label>Refresh Frequency</label>
    <select name="refresh_frequency">
      <option value="monthly" {_sel(s.refresh_frequency, 'monthly')}>Monthly</option>
      <option value="quarterly" {_sel(s.refresh_frequency, 'quarterly')}>Quarterly</option>
    </select>
  </div>
</div>

<div style="margin-top:16px">
  <button type="submit" class="btn success" style="padding:10px 24px;font-size:14px">Save Settings</button>
  <span id="saveStatus" class="status-msg" style="margin-left:12px"></span>
</div>

</form>

<script>
document.getElementById('settingsForm').addEventListener('submit', async function(e) {{
  e.preventDefault();
  const form = e.target;
  const data = {{}};
  for (const input of form.querySelectorAll('input, select')) {{
    if (!input.name) continue;
    if (input.type === 'checkbox') data[input.name] = input.checked;
    else if (input.type === 'number') data[input.name] = parseInt(input.value);
    else data[input.name] = input.value;
  }}
  const status = document.getElementById('saveStatus');
  try {{
    const resp = await fetch('/admin/pipeline/api/settings', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      credentials: 'same-origin',
      body: JSON.stringify(data)
    }});
    if (resp.ok) {{
      status.textContent = '✓ Saved';
      status.className = 'status-msg ok';
    }} else {{
      const d = await resp.json();
      status.textContent = '✗ ' + (d.detail || 'Failed');
      status.className = 'status-msg error';
    }}
  }} catch(e) {{
    status.textContent = '✗ ' + e.message;
    status.className = 'status-msg error';
  }}
}});
</script>
</div>
</body></html>"""


# ---- AI Usage API + Page ----

@router.get("/api/ai-usage")
async def get_ai_usage(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get AI usage stats for admin dashboard."""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    from sqlalchemy import case, cast, Float as SAFloat
    from app.ai.health import get_all_health
    from app.ai.pricing import compute_cost, get_price

    now_utc = _dt.now(_tz.utc).replace(tzinfo=None)
    today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    seven_days_ago = now_utc - _td(days=7)
    thirty_days_ago = now_utc - _td(days=30)

    async def _sum_cost(since: _dt) -> float:
        rows = (await db.execute(
            select(
                AIUsageLog.provider, AIUsageLog.model,
                func.sum(AIUsageLog.tokens_estimated).label("tok"),
            ).where(
                AIUsageLog.called_at >= since,
                AIUsageLog.status == "ok",
            ).group_by(AIUsageLog.provider, AIUsageLog.model)
        )).all()
        total = 0.0
        for r in rows:
            in_price, _ = get_price(r.provider, r.model)
            total += ((r.tok or 0) / 1_000_000.0) * in_price
        return total

    cost_today = await _sum_cost(today_start)
    cost_7d = await _sum_cost(seven_days_ago)
    cost_30d = await _sum_cost(thirty_days_ago)

    # Per-provider stats
    provider_stats = (await db.execute(
        select(
            AIUsageLog.provider,
            func.count().label("total_calls"),
            func.sum(case((AIUsageLog.status == "ok", 1), else_=0)).label("success"),
            func.sum(case((AIUsageLog.status == "rate_limited", 1), else_=0)).label("rate_limited"),
            func.sum(case((AIUsageLog.status == "error", 1), else_=0)).label("errors"),
            func.sum(AIUsageLog.tokens_estimated).label("total_tokens"),
            func.avg(AIUsageLog.latency_ms).label("avg_latency_ms"),
        ).group_by(AIUsageLog.provider)
    )).all()

    # Per-task stats
    task_stats = (await db.execute(
        select(
            AIUsageLog.task,
            AIUsageLog.subtask,
            func.count().label("total_calls"),
            func.sum(case((AIUsageLog.status == "ok", 1), else_=0)).label("success"),
            func.sum(case((AIUsageLog.status != "ok", 1), else_=0)).label("failures"),
            func.sum(AIUsageLog.tokens_estimated).label("total_tokens"),
        ).group_by(AIUsageLog.task, AIUsageLog.subtask)
        .order_by(AIUsageLog.task, AIUsageLog.subtask)
    )).all()

    # Recent calls (last 50)
    recent = (await db.execute(
        select(AIUsageLog)
        .order_by(AIUsageLog.called_at.desc())
        .limit(50)
    )).scalars().all()

    # Health state
    health = get_all_health()

    # Cost rollup per provider (all-time, approximate using input price)
    provider_cost_rows = (await db.execute(
        select(
            AIUsageLog.provider, AIUsageLog.model,
            func.sum(AIUsageLog.tokens_estimated).label("tok"),
        ).where(AIUsageLog.status == "ok")
        .group_by(AIUsageLog.provider, AIUsageLog.model)
    )).all()
    provider_cost_map: dict[str, float] = {}
    for r in provider_cost_rows:
        in_price, _ = get_price(r.provider, r.model)
        provider_cost_map[r.provider] = provider_cost_map.get(r.provider, 0.0) + \
            ((r.tok or 0) / 1_000_000.0) * in_price

    # Per-provider reference info (balances, recommended caps, primary models)
    from app.ai.pricing import PROVIDER_INFO
    provider_info = [
        {"provider": name, **info} for name, info in PROVIDER_INFO.items()
    ]

    # Spend-so-far for each paid provider (today, UTC) — used to show progress bars
    spend_today_map: dict[str, float] = {}
    spend_rows_today = (await db.execute(
        select(
            AIUsageLog.provider, AIUsageLog.model,
            func.sum(AIUsageLog.tokens_estimated).label("tok"),
        ).where(
            AIUsageLog.called_at >= today_start,
            AIUsageLog.status == "ok",
        ).group_by(AIUsageLog.provider, AIUsageLog.model)
    )).all()
    for r in spend_rows_today:
        in_price, _ = get_price(r.provider, r.model)
        spend_today_map[r.provider] = spend_today_map.get(r.provider, 0.0) + \
            ((r.tok or 0) / 1_000_000.0) * in_price

    # Daily cost caps
    limit_rows = (await db.execute(select(AICostLimit))).scalars().all()
    limits_list = [
        {
            "id": lim.id,
            "provider": lim.provider,
            "model": lim.model,
            "daily_cost_usd": lim.daily_cost_usd,
            "daily_token_limit": lim.daily_token_limit,
            "notes": lim.notes or "",
        }
        for lim in limit_rows
    ]

    return {
        "cost_summary": {
            "today": round(cost_today, 6),
            "last_7d": round(cost_7d, 6),
            "last_30d": round(cost_30d, 6),
        },
        "limits": limits_list,
        "provider_info": provider_info,
        "spend_today": {k: round(v, 6) for k, v in spend_today_map.items()},
        "provider_stats": [
            {
                "provider": r.provider,
                "total_calls": r.total_calls,
                "success": r.success or 0,
                "rate_limited": r.rate_limited or 0,
                "errors": r.errors or 0,
                "total_tokens": r.total_tokens or 0,
                "avg_latency_ms": int(r.avg_latency_ms or 0),
                "cost_usd": round(provider_cost_map.get(r.provider, 0.0), 6),
            }
            for r in provider_stats
        ],
        "task_stats": [
            {
                "task": r.task,
                "subtask": r.subtask or "",
                "total_calls": r.total_calls,
                "success": r.success or 0,
                "failures": r.failures or 0,
                "total_tokens": r.total_tokens or 0,
            }
            for r in task_stats
        ],
        "recent": [
            {
                "id": r.id,
                "called_at": r.called_at.strftime("%Y-%m-%d %H:%M:%S") if r.called_at else "",
                "provider": r.provider,
                "model": r.model,
                "task": r.task,
                "subtask": r.subtask or "",
                "status": r.status,
                "error_message": r.error_message or "",
                "tokens_estimated": r.tokens_estimated,
                "latency_ms": r.latency_ms,
                "cost_usd": round(compute_cost(r.provider, r.model, r.tokens_estimated), 6),
            }
            for r in recent
        ],
        "health": {
            name: {
                "available": s.get("available", True),
                "permanent_error": s.get("permanent_error", False),
                "success_count": s.get("success_count", 0),
                "error_count": s.get("error_count", 0),
                "rate_limit_count": s.get("rate_limit_count", 0),
                "last_error_msg": s.get("last_error_msg", ""),
            }
            for name, s in health.items()
        },
    }


@router.post("/api/ai-usage/set-limit")
async def set_cost_limit(
    request: Request,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Upsert a daily cost/token cap for a provider+model. model='*' = provider-wide."""
    _check_origin(request)
    body = await request.json()
    provider = (body.get("provider") or "").strip().lower()
    model = (body.get("model") or "*").strip()
    try:
        daily_cost = float(body.get("daily_cost_usd", 0))
        daily_tokens = int(body.get("daily_token_limit", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid numeric values")
    if not provider:
        raise HTTPException(status_code=400, detail="provider required")
    if daily_cost < 0 or daily_tokens < 0:
        raise HTTPException(status_code=400, detail="limits cannot be negative")

    existing = (await db.execute(
        select(AICostLimit).where(
            AICostLimit.provider == provider, AICostLimit.model == model,
        )
    )).scalar_one_or_none()

    if existing is None:
        lim = AICostLimit(
            provider=provider, model=model,
            daily_cost_usd=daily_cost, daily_token_limit=daily_tokens,
            notes=body.get("notes"),
        )
        db.add(lim)
    else:
        existing.daily_cost_usd = daily_cost
        existing.daily_token_limit = daily_tokens
        if "notes" in body:
            existing.notes = body.get("notes")
    await db.commit()
    return {"ok": True}


@router.post("/api/ai-usage/delete-limit")
async def delete_cost_limit(
    request: Request,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    _check_origin(request)
    body = await request.json()
    lim_id = body.get("id")
    if not lim_id:
        raise HTTPException(status_code=400, detail="id required")
    lim = await db.get(AICostLimit, int(lim_id))
    if lim is not None:
        await db.delete(lim)
        await db.commit()
    return {"ok": True}


@router.post("/api/ai-usage/reset-provider")
async def reset_provider_health(
    request: Request,
    _user: User = Depends(get_current_admin),
):
    """Reset a provider's circuit breaker state."""
    _check_origin(request)
    body = await request.json()
    provider = body.get("provider", "")
    if not provider:
        raise HTTPException(status_code=400, detail="provider required")
    from app.ai.health import reset_provider
    reset_provider(provider)
    return {"ok": True, "provider": provider}


@router.get("/ai-usage", response_class=HTMLResponse)
async def ai_usage_page(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """AI Usage dashboard — per-provider stats, per-task breakdown, health status."""
    from app.ai.health import get_all_health

    s = await _get_settings(db)
    budget_pct = 0
    if s.max_tokens_per_run > 0:
        budget_pct = int((s.tokens_used_this_month / s.max_tokens_per_run) * 100)

    # Provider health for status indicators
    health = get_all_health()

    # All known providers
    all_providers = ["gemini", "groq", "cerebras", "mistral", "deepseek", "sambanova"]
    from app.config import get_settings as get_app_settings
    app_settings = get_app_settings()

    provider_cards = ""
    for p in all_providers:
        api_key = getattr(app_settings, f"{p}_api_key", "")
        has_key = bool(api_key)
        h = health.get(p, {})
        available = h.get("available", True) if h else True
        permanent = h.get("permanent_error", False) if h else False
        successes = h.get("success_count", 0) if h else 0
        errors = h.get("error_count", 0) if h else 0
        rl_count = h.get("rate_limit_count", 0) if h else 0
        last_err_raw = h.get("last_error_msg", "") or "" if h else ""
        model = getattr(app_settings, f"{p}_model", "")

        # Human-readable status + reason
        if not has_key:
            dot = "🔴"
            status_text = "Not configured"
            reason = "No API key set"
        elif permanent:
            dot = "🔴"
            status_text = "Down"
            if "402" in last_err_raw or "Insufficient" in last_err_raw:
                reason = "Out of credits — needs top-up"
            elif "404" in last_err_raw or "not found" in last_err_raw:
                reason = "Model retired or invalid"
            else:
                reason = "Permanent error"
        elif not available:
            dot = "🟡"
            status_text = "Cooling down"
            reason = "Hit rate limit — auto-retries in 60s"
        elif successes > 0:
            dot = "🟢"
            status_text = "Working"
            reason = f"{successes} successful calls"
        elif rl_count > 0:
            dot = "🟡"
            status_text = "Rate limited"
            reason = f"Hit limit {rl_count} times — will retry"
        else:
            dot = "🟢"
            status_text = "Ready"
            reason = "No calls yet"

        reset_btn = ""
        if permanent or not available:
            reset_btn = f'<button class="btn" style="margin-top:6px;font-size:12px" onclick="resetProvider(\'{p}\')">Retry This Provider</button>'

        provider_cards += f"""<div class="card" style="flex:1;min-width:170px">
  <div style="display:flex;justify-content:space-between;align-items:center">
    <strong style="color:#e8a849;text-transform:capitalize">{esc(p)}</strong>
    <span style="font-size:13px">{dot}</span>
  </div>
  <div style="font-size:13px;margin:6px 0;color:#f5f1e8">{status_text}</div>
  <div style="font-size:12px;color:#8a92a0">{esc(reason)}</div>
  <div style="font-size:12px;color:#8a92a0;margin-top:4px">Model: {esc(model)}</div>
  {reset_btn}
</div>"""

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>AI Usage</title>
<style>{ADMIN_CSS}</style></head><body>
{NAV_HTML}
<div class="page">
<h1>AI Usage Dashboard</h1>
<div class="subtitle">Provider health, usage per task, token budget</div>

<h2>Cost (USD)</h2>
<div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap">
<div class="stat"><div class="num" id="cost-today" style="color:#6db585">$0.0000</div><div class="lbl">Today</div></div>
<div class="stat"><div class="num" id="cost-7d" style="color:#e8a849">$0.0000</div><div class="lbl">Last 7 days</div></div>
<div class="stat"><div class="num" id="cost-30d" style="color:#d97757">$0.0000</div><div class="lbl">Last 30 days</div></div>
<div class="stat"><div class="num">{s.tokens_used_this_month:,}</div><div class="lbl">Tokens / month</div></div>
<div class="stat"><div class="num">{budget_pct}%</div><div class="lbl">Budget used</div></div>
</div>
<div style="font-size:12px;color:#8a92a0;margin-bottom:24px">
Free-tier providers (Gemini / Groq / Cerebras / Mistral / Sambanova) contribute $0.00.
Paid spend comes from Anthropic (refinement) + OpenAI (embeddings).
</div>

<h2>Daily Cost Caps</h2>
<div style="font-size:13px;color:#8a92a0;margin-bottom:8px">
Block further calls once today's spend or token count hits the cap. Use <code>*</code> as model for a provider-wide cap.
</div>

<div id="provider-info" style="margin-bottom:12px"><em style="color:#8a92a0">Loading provider info...</em></div>
<form id="limit-form" style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;align-items:end">
  <div><label style="font-size:12px;color:#8a92a0">Provider</label><br>
    <select id="lim-provider" style="padding:6px">
      <option value="openai">openai</option>
      <option value="anthropic">anthropic</option>
      <option value="gemini">gemini</option>
      <option value="groq">groq</option>
      <option value="cerebras">cerebras</option>
      <option value="mistral">mistral</option>
      <option value="sambanova">sambanova</option>
      <option value="deepseek">deepseek</option>
    </select></div>
  <div><label style="font-size:12px;color:#8a92a0">Model (or *)</label><br>
    <input id="lim-model" value="*" style="padding:6px;width:180px"></div>
  <div><label style="font-size:12px;color:#8a92a0">Daily $ cap</label><br>
    <input id="lim-cost" type="number" step="0.01" min="0" value="1.00" style="padding:6px;width:100px"></div>
  <div><label style="font-size:12px;color:#8a92a0">Daily token cap</label><br>
    <input id="lim-tokens" type="number" min="0" value="0" style="padding:6px;width:120px"></div>
  <button type="button" class="btn" onclick="saveLimit()">Save cap</button>
</form>
<div id="limits-table" style="margin-bottom:24px"><em style="color:#8a92a0">Loading...</em></div>

<h2>Provider Health</h2>
<div style="display:flex;flex-wrap:wrap;gap:12px;margin-bottom:24px">
{provider_cards}
</div>

<h2>Usage by Provider</h2>
<div id="provider-stats"><em style="color:#8a92a0">Loading...</em></div>

<h2>Usage by Task</h2>
<div id="task-stats"><em style="color:#8a92a0">Loading...</em></div>

<h2>Recent Calls (last 50)</h2>
<div id="recent-calls" style="max-height:400px;overflow-y:auto"><em style="color:#8a92a0">Loading...</em></div>

<script>
async function resetProvider(name) {{
  await fetch('/admin/pipeline/api/ai-usage/reset-provider', {{
    method: 'POST', credentials: 'same-origin',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{provider: name}})
  }});
  window.location.reload();
}}

function fmtCost(usd) {{
  if (usd === 0) return '<span style="color:#8a92a0">$0.00</span>';
  if (usd < 0.01) return '$' + usd.toFixed(6);
  if (usd < 1) return '$' + usd.toFixed(4);
  return '$' + usd.toFixed(2);
}}

async function saveLimit() {{
  const body = {{
    provider: document.getElementById('lim-provider').value,
    model: document.getElementById('lim-model').value || '*',
    daily_cost_usd: parseFloat(document.getElementById('lim-cost').value) || 0,
    daily_token_limit: parseInt(document.getElementById('lim-tokens').value) || 0,
  }};
  const resp = await fetch('/admin/pipeline/api/ai-usage/set-limit', {{
    method: 'POST', credentials: 'same-origin',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(body),
  }});
  if (!resp.ok) {{ alert('Failed to save limit'); return; }}
  loadUsageData();
}}

async function deleteLimit(id) {{
  if (!confirm('Remove this cap?')) return;
  await fetch('/admin/pipeline/api/ai-usage/delete-limit', {{
    method: 'POST', credentials: 'same-origin',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{id}}),
  }});
  loadUsageData();
}}

async function loadUsageData() {{
  try {{
    const resp = await fetch('/admin/pipeline/api/ai-usage', {{credentials: 'same-origin'}});
    const data = await resp.json();

    // Cost cards
    if (data.cost_summary) {{
      document.getElementById('cost-today').textContent = '$' + data.cost_summary.today.toFixed(4);
      document.getElementById('cost-7d').textContent = '$' + data.cost_summary.last_7d.toFixed(4);
      document.getElementById('cost-30d').textContent = '$' + data.cost_summary.last_30d.toFixed(4);
    }}

    // Provider info table (balance, recommended cap, primary model, spend today)
    if (data.provider_info) {{
      const limitsByProvider = {{}};
      (data.limits || []).forEach(l => {{
        if (l.model === '*') limitsByProvider[l.provider] = l.daily_cost_usd;
      }});
      const spend = data.spend_today || {{}};
      let ihtml = '<table style="font-size:13px"><tr>' +
        '<th>Provider</th><th>Balance</th><th>Rec. $ cap</th><th>Current $ cap</th>' +
        '<th>Today spend</th><th>Primary model</th><th>Price</th><th>Used for</th></tr>';
      for (const p of data.provider_info) {{
        const paidBadge = p.paid
          ? '<span style="color:#e8a849;font-weight:600;text-transform:capitalize">' + p.provider + '</span>'
          : '<span style="color:#6db585;text-transform:capitalize">' + p.provider + '</span>';
        const bal = p.balance_usd > 0 ? '$' + p.balance_usd.toFixed(2) : '<span style="color:#8a92a0">free</span>';
        const rec = p.recommended_cap_usd > 0 ? '$' + p.recommended_cap_usd.toFixed(2) : '—';
        const curCap = limitsByProvider[p.provider] != null
          ? '$' + limitsByProvider[p.provider].toFixed(2)
          : '<span style="color:#d97757">unset</span>';
        const sp = spend[p.provider] || 0;
        const spStr = p.paid
          ? (sp > 0 ? '$' + sp.toFixed(4) : '<span style="color:#8a92a0">$0</span>')
          : '<span style="color:#8a92a0">—</span>';
        ihtml += '<tr>' +
          '<td>' + paidBadge + '</td>' +
          '<td>' + bal + '</td>' +
          '<td>' + rec + '</td>' +
          '<td>' + curCap + '</td>' +
          '<td>' + spStr + '</td>' +
          '<td style="font-family:monospace;font-size:12px">' + p.primary_model + '</td>' +
          '<td style="font-size:12px;color:#8a92a0">' + p.price_note + '</td>' +
          '<td style="font-size:12px;color:#8a92a0">' + p.use + '</td>' +
          '</tr>';
      }}
      ihtml += '</table>';
      document.getElementById('provider-info').innerHTML = ihtml;
    }}

    // Limits table
    if (data.limits && data.limits.length > 0) {{
      let lhtml = '<table><tr><th>Provider</th><th>Model</th><th>Daily $ cap</th><th>Daily token cap</th><th></th></tr>';
      for (const l of data.limits) {{
        lhtml += `<tr>
          <td style="text-transform:capitalize">${{l.provider}}</td>
          <td><code>${{l.model}}</code></td>
          <td>$${{l.daily_cost_usd.toFixed(2)}}</td>
          <td>${{l.daily_token_limit ? l.daily_token_limit.toLocaleString() : '—'}}</td>
          <td><button class="btn" style="font-size:12px" onclick="deleteLimit(${{l.id}})">Remove</button></td>
        </tr>`;
      }}
      lhtml += '</table>';
      document.getElementById('limits-table').innerHTML = lhtml;
    }} else {{
      document.getElementById('limits-table').innerHTML = '<p style="color:#8a92a0">No caps configured — paid providers can run unrestricted.</p>';
    }}

    // Provider stats table
    if (data.provider_stats.length > 0) {{
      let html = '<table><tr><th>Provider</th><th>Total Calls</th><th>Succeeded</th><th>Rate Limited</th><th>Failed</th><th>Avg Speed</th><th>Cost</th></tr>';
      for (const p of data.provider_stats) {{
        const successRate = p.total_calls > 0 ? Math.round(p.success / p.total_calls * 100) : 0;
        const speedLabel = p.avg_latency_ms < 1000 ? p.avg_latency_ms + 'ms' : (p.avg_latency_ms / 1000).toFixed(1) + 's';
        html += `<tr>
          <td style="text-transform:capitalize"><strong>${{p.provider}}</strong></td>
          <td>${{p.total_calls}}</td>
          <td style="color:#6db585">${{p.success}} (${{successRate}}%)</td>
          <td style="color:#e8a849">${{p.rate_limited}}</td>
          <td style="color:#d97757">${{p.errors}}</td>
          <td>${{speedLabel}}</td>
          <td>${{fmtCost(p.cost_usd || 0)}}</td>
        </tr>`;
      }}
      html += '</table>';
      document.getElementById('provider-stats').innerHTML = html;
    }} else {{
      document.getElementById('provider-stats').innerHTML = '<p style="color:#8a92a0">No usage data yet. Run a pipeline task to generate data.</p>';
    }}

    // Task stats table
    if (data.task_stats.length > 0) {{
      let html = '<table><tr><th>Task</th><th>Subtask</th><th>Calls</th><th>Success</th><th>Failures</th><th>Tokens</th></tr>';
      for (const t of data.task_stats) {{
        html += `<tr>
          <td>${{t.task}}</td>
          <td style="font-size:12px;color:#8a92a0;max-width:200px;overflow:hidden;text-overflow:ellipsis">${{t.subtask}}</td>
          <td>${{t.total_calls}}</td>
          <td style="color:#6db585">${{t.success}}</td>
          <td style="color:#d97757">${{t.failures}}</td>
          <td>${{t.total_tokens.toLocaleString()}}</td>
        </tr>`;
      }}
      html += '</table>';
      document.getElementById('task-stats').innerHTML = html;
    }} else {{
      document.getElementById('task-stats').innerHTML = '<p style="color:#8a92a0">No task data yet.</p>';
    }}

    // Recent calls
    if (data.recent.length > 0) {{
      // Human-readable status labels
      function friendlyStatus(status, err) {{
        if (status === 'ok') return '<span class="badge approved">Success</span>';
        if (status === 'rate_limited') return '<span class="badge pending">Rate Limited</span>';
        if (err && (err.includes('402') || err.includes('Insufficient'))) return '<span class="badge rejected">No Credits</span>';
        if (err && (err.includes('404') || err.includes('not found'))) return '<span class="badge rejected">Bad Model</span>';
        if (err && err.includes('non-JSON')) return '<span class="badge rejected">Bad Response</span>';
        return '<span class="badge rejected">Error</span>';
      }}
      function friendlyTime(ms) {{ return ms < 1000 ? ms + 'ms' : (ms/1000).toFixed(1) + 's'; }}

      let html = '<table><tr><th>Time</th><th>Provider</th><th>Task</th><th>Result</th><th>Speed</th><th>Cost</th></tr>';
      for (const r of data.recent) {{
        html += `<tr>
          <td style="font-size:12px;white-space:nowrap">${{r.called_at.slice(11)}}</td>
          <td style="text-transform:capitalize">${{r.provider}}</td>
          <td>${{r.task}}${{r.subtask ? ' <span style="color:#8a92a0;font-size:12px">(' + r.subtask.slice(0,30) + ')</span>' : ''}}</td>
          <td>${{friendlyStatus(r.status, r.error_message)}}</td>
          <td>${{friendlyTime(r.latency_ms)}}</td>
          <td>${{fmtCost(r.cost_usd || 0)}}</td>
        </tr>`;
      }}
      html += '</table>';
      document.getElementById('recent-calls').innerHTML = html;
    }} else {{
      document.getElementById('recent-calls').innerHTML = '<p style="color:#8a92a0">No recent calls.</p>';
    }}
  }} catch(e) {{
    document.getElementById('provider-stats').innerHTML = '<p style="color:#d97757">Failed to load: ' + e.message + '</p>';
  }}
}}

loadUsageData();
</script>
</div>
</body></html>"""


# ---- Normalization Dashboard API + Page ----

@router.get("/api/normalization")
async def get_normalization_stats(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get normalization pipeline stats for admin dashboard."""
    from sqlalchemy import case
    from app.models.curriculum import LinkHealth
    from app.curriculum.loader import list_templates

    # ---- Stage A: Discovery stats ----
    status_counts = {}
    for status_val in ["pending", "approved", "generating", "generated", "rejected"]:
        count = await db.scalar(
            select(func.count()).select_from(DiscoveredTopic)
            .where(DiscoveredTopic.status == status_val)
        ) or 0
        status_counts[status_val] = count
    total_topics = sum(status_counts.values())

    avg_confidence = await db.scalar(
        select(func.avg(DiscoveredTopic.confidence_score))
    ) or 0

    # Category distribution
    cat_rows = (await db.execute(
        select(
            DiscoveredTopic.category,
            func.count().label("cnt"),
        ).group_by(DiscoveredTopic.category)
        .order_by(func.count().desc())
    )).all()

    # Discovery runs
    run_rows = (await db.execute(
        select(
            DiscoveredTopic.discovery_run,
            DiscoveredTopic.ai_model_used,
            func.count().label("topics_found"),
        ).group_by(DiscoveredTopic.discovery_run, DiscoveredTopic.ai_model_used)
        .order_by(DiscoveredTopic.discovery_run.desc())
        .limit(10)
    )).all()

    # ---- Stage B: Generation stats ----
    total_templates_on_disk = len(list_templates())

    gen_topics = (await db.execute(
        select(
            DiscoveredTopic.topic_name,
            DiscoveredTopic.templates_generated,
            DiscoveredTopic.generation_error,
            DiscoveredTopic.status,
        ).where(DiscoveredTopic.templates_generated > 0)
        .order_by(DiscoveredTopic.templates_generated.desc())
    )).all()

    total_variants_generated = sum(t.templates_generated for t in gen_topics)
    topics_with_errors = sum(1 for t in gen_topics if t.generation_error)

    # ---- Stage C: Content Refresh stats ----
    total_links = await db.scalar(
        select(func.count()).select_from(LinkHealth)
    ) or 0
    broken_links = await db.scalar(
        select(func.count()).select_from(LinkHealth)
        .where(LinkHealth.consecutive_failures >= 2)
    ) or 0
    ok_links = await db.scalar(
        select(func.count()).select_from(LinkHealth)
        .where(LinkHealth.consecutive_failures == 0)
    ) or 0

    # Broken links by template
    broken_by_template = (await db.execute(
        select(
            LinkHealth.template_key,
            func.count().label("broken_count"),
        ).where(LinkHealth.consecutive_failures >= 2)
        .group_by(LinkHealth.template_key)
        .order_by(func.count().desc())
        .limit(10)
    )).all()

    # ---- Cache stats ----
    cache_stats = _get_cache_stats()

    # ---- Settings ----
    s = await _get_settings(db)

    return {
        "discovery": {
            "total_topics": total_topics,
            "status_counts": status_counts,
            "avg_confidence": round(avg_confidence, 1),
            "categories": [{"category": r.category, "count": r.cnt} for r in cat_rows],
            "recent_runs": [
                {
                    "run_id": r.discovery_run[:19] if r.discovery_run else "",
                    "model": r.ai_model_used,
                    "topics_found": r.topics_found,
                }
                for r in run_rows
            ],
        },
        "generation": {
            "templates_on_disk": total_templates_on_disk,
            "total_variants_generated": total_variants_generated,
            "topics_with_templates": len(gen_topics),
            "topics_with_errors": topics_with_errors,
            "per_topic": [
                {
                    "topic": t.topic_name,
                    "variants": t.templates_generated,
                    "status": t.status,
                    "has_error": bool(t.generation_error),
                    "error": (t.generation_error or "")[:100],
                }
                for t in gen_topics
            ],
        },
        "refresh": {
            "total_links": total_links,
            "ok_links": ok_links,
            "broken_links": broken_links,
            "broken_by_template": [
                {"template": r.template_key, "count": r.broken_count}
                for r in broken_by_template
            ],
            "last_refresh": s.last_refresh_run.isoformat() if s.last_refresh_run else None,
        },
        "cache": cache_stats,
        "config": {
            "max_topics_per_discovery": s.max_topics_per_discovery,
            "discovery_frequency": s.discovery_frequency,
            "auto_approve": s.auto_approve_topics,
            "auto_generate": s.auto_generate_variants,
            "refresh_frequency": s.refresh_frequency,
        },
    }


def _get_cache_stats() -> dict:
    """Get cache file stats by type."""
    from app.services.ai_cache import CACHE_DIR
    import time as _time

    stats = {"discovery": 0, "triage": 0, "generation": 0, "currency_review": 0, "other": 0, "expired": 0, "total_files": 0}
    if not CACHE_DIR.exists():
        return stats

    for path in CACHE_DIR.glob("*.json"):
        stats["total_files"] += 1
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            ptype = data.get("prompt_type", "other")
            if _time.time() > data.get("expires_at", 0):
                stats["expired"] += 1
            elif ptype in stats:
                stats[ptype] += 1
            else:
                stats["other"] += 1
        except Exception:
            stats["other"] += 1

    return stats


@router.get("/normalization")
async def normalization_redirect():
    """Redirect old normalization URL to pipeline page."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/admin/pipeline/", status_code=301)


# ---- Proposals page ----

@router.get("/api/proposals")
async def list_proposals(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all curriculum proposals."""
    from app.models.curriculum import CurriculumProposal
    result = await db.execute(
        select(CurriculumProposal).order_by(CurriculumProposal.created_at.desc())
    )
    proposals = result.scalars().all()
    return [{
        "id": p.id,
        "source_run": p.source_run,
        "status": p.status,
        "created_at": str(p.created_at),
        "reviewed_at": str(p.reviewed_at) if p.reviewed_at else None,
        "notes": p.notes,
        "proposal_md": p.proposal_md[:500],
    } for p in proposals]


@router.get("/api/proposals/{proposal_id}")
async def get_proposal(
    proposal_id: int,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get full proposal content."""
    from app.models.curriculum import CurriculumProposal
    result = await db.execute(
        select(CurriculumProposal).where(CurriculumProposal.id == proposal_id)
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return {
        "id": p.id,
        "source_run": p.source_run,
        "status": p.status,
        "created_at": str(p.created_at),
        "reviewed_at": str(p.reviewed_at) if p.reviewed_at else None,
        "notes": p.notes,
        "proposal_md": p.proposal_md,
    }


@router.post("/api/proposals/{proposal_id}/approve")
async def approve_proposal(
    proposal_id: int,
    request: Request,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Mark a proposal as approved/applied."""
    _check_origin(request)
    from app.models.curriculum import CurriculumProposal
    from datetime import datetime, timezone
    result = await db.execute(
        select(CurriculumProposal).where(CurriculumProposal.id == proposal_id)
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Proposal not found")
    p.status = "applied"
    p.reviewer_id = user.id
    p.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.flush()
    return {"ok": True, "status": "applied"}


@router.post("/api/proposals/{proposal_id}/reject")
async def reject_proposal(
    proposal_id: int,
    request: Request,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Mark a proposal as rejected."""
    _check_origin(request)
    from app.models.curriculum import CurriculumProposal
    from datetime import datetime, timezone
    result = await db.execute(
        select(CurriculumProposal).where(CurriculumProposal.id == proposal_id)
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Proposal not found")
    p.status = "rejected"
    p.reviewer_id = user.id
    p.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.flush()
    return {"ok": True, "status": "rejected"}


@router.get("/proposals", response_class=HTMLResponse)
async def proposals_page(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin proposals review page."""
    from app.models.curriculum import CurriculumProposal

    result = await db.execute(
        select(CurriculumProposal).order_by(CurriculumProposal.created_at.desc())
    )
    proposals = result.scalars().all()

    pending_count = sum(1 for p in proposals if p.status == "pending")

    rows = ""
    for p in proposals:
        status_color = {"pending": "#e8a849", "applied": "#6db585", "rejected": "#d97757"}.get(p.status, "#8a92a0")
        status_badge = f'<span style="color:{status_color};font-weight:600">{p.status.title()}</span>'
        created = str(p.created_at)[:10] if p.created_at else "—"
        reviewed = str(p.reviewed_at)[:10] if p.reviewed_at else "—"
        preview = esc(p.proposal_md[:200]).replace("\\n", " ")

        actions = ""
        if p.status == "pending":
            actions = f"""
                <button class="btn success" style="font-size:11px;padding:4px 8px" onclick="proposalAction({p.id},'approve',this)">Approve</button>
                <button class="btn danger" style="font-size:11px;padding:4px 8px" onclick="proposalAction({p.id},'reject',this)">Reject</button>
            """

        rows += f"""<tr>
            <td>{p.id}</td>
            <td>{esc(p.source_run)}</td>
            <td>{created}</td>
            <td>{status_badge}</td>
            <td>{reviewed}</td>
            <td style="max-width:300px;font-size:12px;color:#8a92a0;overflow:hidden;text-overflow:ellipsis">{preview}</td>
            <td>
                <button class="btn" style="font-size:11px;padding:4px 8px" onclick="viewProposal({p.id})">View</button>
                {actions}
            </td>
        </tr>"""

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Proposals</title>
<style>{ADMIN_CSS}
.modal {{ display:none; position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.7); z-index:100; align-items:center; justify-content:center; }}
.modal-content {{ background:#1d242e; border-radius:8px; padding:24px; max-width:800px; width:90%; max-height:80vh; overflow-y:auto; color:#d0cbc2; white-space:pre-wrap; font-size:13px; line-height:1.7; }}
.modal-close {{ float:right; cursor:pointer; font-size:20px; color:#8a92a0; background:none; border:none; }}
</style></head><body>
{NAV_HTML}
<div class="page">
<h1>Curriculum Proposals</h1>
<p style="color:#8a92a0;font-size:13px;margin-bottom:16px">
    Quarterly sync generates proposals to update, add, or retire topics. Review and approve/reject below.
    {f'<span style="color:#e8a849;font-weight:600">{pending_count} pending</span>' if pending_count else '<span style="color:#6db585">All reviewed</span>'}
</p>

{'<p style="color:#8a92a0;font-size:13px">No proposals yet. The quarterly sync runs on Jan/Apr/Jul/Oct 1st, or trigger it manually from the Pipeline page.</p>' if not proposals else f"""
<table>
<tr><th>ID</th><th>Run</th><th>Created</th><th>Status</th><th>Reviewed</th><th>Preview</th><th>Actions</th></tr>
{rows}
</table>
"""}

<div class="modal" id="proposalModal">
    <div class="modal-content">
        <button class="modal-close" onclick="document.getElementById('proposalModal').style.display='none'">&times;</button>
        <div id="proposalContent">Loading...</div>
    </div>
</div>

<script>
async function viewProposal(id) {{
    const modal = document.getElementById('proposalModal');
    const content = document.getElementById('proposalContent');
    content.textContent = 'Loading...';
    modal.style.display = 'flex';
    try {{
        const resp = await fetch('/admin/pipeline/api/proposals/' + id, {{credentials: 'same-origin'}});
        const data = await resp.json();
        content.textContent = data.proposal_md;
    }} catch(e) {{
        content.textContent = 'Error: ' + e.message;
    }}
}}

async function proposalAction(id, action, btn) {{
    btn.disabled = true;
    try {{
        const resp = await fetch('/admin/pipeline/api/proposals/' + id + '/' + action, {{
            method: 'POST', credentials: 'same-origin'
        }});
        if (resp.ok) window.location.reload();
        else alert('Failed: ' + (await resp.json()).detail);
    }} catch(e) {{
        alert('Error: ' + e.message);
    }}
    btn.disabled = false;
}}

document.getElementById('proposalModal').addEventListener('click', function(e) {{
    if (e.target === this) this.style.display = 'none';
}});
</script>
</div></body></html>"""
