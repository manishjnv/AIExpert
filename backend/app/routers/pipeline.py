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
from app.models.curriculum import AIUsageLog, CurriculumSettings, DiscoveredTopic
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
body { font-family: 'IBM Plex Sans', system-ui, sans-serif; background: #0f1419; color: #f5f1e8; margin: 0; padding: 0; -webkit-font-smoothing: antialiased; }
.page { max-width: 100%; margin: 0; padding: 32px 48px; }
h1 { font-family: 'Fraunces', Georgia, serif; color: #e8a849; font-size: 28px; font-weight: 300; margin-bottom: 4px; }
h2 { font-family: 'Fraunces', Georgia, serif; color: #e8a849; font-size: 18px; margin-top: 24px; }
h3 { font-family: 'Fraunces', Georgia, serif; color: #e8a849; font-size: 15px; margin-top: 16px; }
.subtitle { color: #4a5260; font-size: 13px; margin-bottom: 24px; font-family: 'IBM Plex Mono', monospace; letter-spacing: 0.03em; }
.stat { display: inline-block; background: #1d242e; padding: 16px 24px; border-radius: 6px; margin: 4px; text-align: center; }
.stat .num { font-family: 'Fraunces', Georgia, serif; font-size: 28px; font-weight: 400; color: #e8a849; }
.stat .lbl { font-family: 'IBM Plex Mono', monospace; font-size: 9px; text-transform: uppercase; letter-spacing: 0.12em; color: #4a5260; margin-top: 2px; }
table { width: 100%; border-collapse: collapse; margin-top: 12px; }
th { text-align: left; padding: 10px 8px; font-family: 'IBM Plex Mono', monospace; font-size: 10px; text-transform: uppercase; letter-spacing: 0.12em; color: #4a5260; border-bottom: 1px solid #2a323d; }
td { padding: 10px 8px; font-size: 13px; border-bottom: 1px solid #1d242e; }
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
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; }
.form-group { display: flex; flex-direction: column; gap: 4px; }
.form-group label { font-family: 'IBM Plex Mono', monospace; font-size: 10px; text-transform: uppercase; letter-spacing: 0.1em; color: #4a5260; }
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
    """Pipeline overview dashboard."""
    s = await _get_settings(db)

    # Topic counts by status
    pending = await db.scalar(
        select(func.count()).select_from(DiscoveredTopic).where(DiscoveredTopic.status == "pending")
    ) or 0
    approved = await db.scalar(
        select(func.count()).select_from(DiscoveredTopic).where(DiscoveredTopic.status == "approved")
    ) or 0
    generated = await db.scalar(
        select(func.count()).select_from(DiscoveredTopic).where(DiscoveredTopic.status == "generated")
    ) or 0
    total_topics = await db.scalar(
        select(func.count()).select_from(DiscoveredTopic)
    ) or 0

    # Template count
    from app.curriculum.loader import list_templates
    template_count = len(list_templates())

    budget_pct = 0
    if s.max_tokens_per_run > 0:
        budget_pct = int((s.tokens_used_this_month / s.max_tokens_per_run) * 100)

    last_discovery = s.last_discovery_run.strftime("%Y-%m-%d %H:%M") if s.last_discovery_run else "Never"
    last_generation = s.last_generation_run.strftime("%Y-%m-%d %H:%M") if s.last_generation_run else "Never"
    last_refresh = s.last_refresh_run.strftime("%Y-%m-%d %H:%M") if s.last_refresh_run else "Never"

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Pipeline</title>
<style>{ADMIN_CSS}</style></head><body>
{NAV_HTML}
<div class="page">
<h1>Auto Curriculum Pipeline</h1>
<div class="subtitle">AI-powered topic discovery, curriculum generation, and content refresh</div>

<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:24px">
<div class="stat"><div class="num">{total_topics}</div><div class="lbl">Total Topics</div></div>
<div class="stat"><div class="num">{pending}</div><div class="lbl">Pending Review</div></div>
<div class="stat"><div class="num">{approved}</div><div class="lbl">Approved</div></div>
<div class="stat"><div class="num">{generated}</div><div class="lbl">Generated</div></div>
<div class="stat"><div class="num">{template_count}</div><div class="lbl">Templates</div></div>
<div class="stat"><div class="num">{budget_pct}%</div><div class="lbl">Budget Used</div></div>
</div>

<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-bottom:24px">

<div class="card">
  <h3>Topic Discovery</h3>
  <p style="font-size:12px;color:#4a5260">AI researches trending AI/ML topics from universities, papers, and industry.</p>
  <p style="font-size:12px">Last run: {esc(last_discovery)}</p>
  <p style="font-size:12px">Frequency: {esc(s.discovery_frequency)}</p>
  <button class="btn primary" onclick="runAction('run-discovery', this)">Run Discovery Now</button>
  <div id="status-discovery" class="status-msg"></div>
</div>

<div class="card">
  <h3>Batch Generation</h3>
  <p style="font-size:12px;color:#4a5260">Generates curriculum variants for all approved topics.</p>
  <p style="font-size:12px">Last run: {esc(last_generation)}</p>
  <p style="font-size:12px">Approved topics: {approved}</p>
  <button class="btn primary" onclick="runAction('run-generation', this)" {'disabled' if approved == 0 else ''}>Generate All Pending</button>
  <div id="status-generation" class="status-msg"></div>
</div>

<div class="card">
  <h3>Content Refresh</h3>
  <p style="font-size:12px;color:#4a5260">Checks links and reviews content currency across all templates.</p>
  <p style="font-size:12px">Last run: {esc(last_refresh)}</p>
  <p style="font-size:12px">Templates: {template_count}</p>
  <button class="btn primary" onclick="runAction('run-refresh', this)">Run Refresh Now</button>
  <div id="status-refresh" class="status-msg"></div>
</div>

</div>

<script>
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
      statusEl.textContent = '✓ ' + JSON.stringify(data).substring(0, 200);
      statusEl.className = 'status-msg ok';
      setTimeout(() => window.location.reload(), 2000);
    }} else {{
      statusEl.textContent = '✗ ' + (data.error || data.detail || JSON.stringify(data));
      statusEl.className = 'status-msg error';
    }}
  }} catch(e) {{
    statusEl.textContent = '✗ ' + e.message;
    statusEl.className = 'status-msg error';
  }}
  btn.disabled = false;
  btn.textContent = origText;
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
            error_html = f'<div style="color:#d97757;font-size:11px;margin-top:2px">{esc(t.generation_error[:100])}</div>'

        rows_html += f"""<tr>
<td>{t.id}</td>
<td><strong>{esc(t.topic_name)}</strong><div style="font-size:11px;color:#4a5260">{esc(t.category)}{(' / ' + esc(t.subcategory)) if t.subcategory else ''}</div></td>
<td style="font-size:12px;max-width:300px">{esc(t.justification[:150])}{'...' if len(t.justification) > 150 else ''}</td>
<td>{t.confidence_score}</td>
<td><span class="badge {t.status}">{t.status}</span>{error_html}</td>
<td>{t.templates_generated}</td>
<td style="font-size:11px">{t.created_at.strftime('%Y-%m-%d') if t.created_at else ''}</td>
<td>{actions}</td>
</tr>"""

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Topics</title>
<style>{ADMIN_CSS}</style></head><body>
{NAV_HTML}
<div class="page">
<h1>Discovered Topics ({len(rows)})</h1>
<div class="subtitle">AI-discovered trending topics for curriculum generation</div>
<div style="margin-bottom:16px">{filter_html}</div>

<table>
<tr><th>ID</th><th>Topic</th><th>Justification</th><th>Score</th><th>Status</th><th>Templates</th><th>Discovered</th><th>Actions</th></tr>
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

</script>
<div style="margin-top:12px">{'<a href="/admin/pipeline/topics?page='+str(page-1)+'&status='+esc(status)+'" class="btn">Prev</a> ' if page>1 else ''}{'<a href="/admin/pipeline/topics?page='+str(page+1)+'&status='+esc(status)+'" class="btn">Next</a>' if page*50<total else ''} <span style="font-size:12px;color:#4a5260">{total} total</span></div>
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

<form id="settingsForm" class="card" style="max-width:700px">

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
    from sqlalchemy import case, cast, Float as SAFloat
    from app.ai.health import get_all_health

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

    return {
        "provider_stats": [
            {
                "provider": r.provider,
                "total_calls": r.total_calls,
                "success": r.success or 0,
                "rate_limited": r.rate_limited or 0,
                "errors": r.errors or 0,
                "total_tokens": r.total_tokens or 0,
                "avg_latency_ms": int(r.avg_latency_ms or 0),
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
        last_err = esc(h.get("last_error_msg", "") or "") if h else ""
        model = getattr(app_settings, f"{p}_model", "")

        if not has_key:
            status_badge = '<span class="badge rejected">No Key</span>'
        elif permanent:
            status_badge = '<span class="badge rejected">Unavailable</span>'
        elif not available:
            status_badge = '<span class="badge pending">Cooldown</span>'
        else:
            status_badge = '<span class="badge approved">Available</span>'

        reset_btn = ""
        if permanent or not available:
            reset_btn = f'<button class="btn" style="margin-top:6px;font-size:10px" onclick="resetProvider(\'{p}\')">Reset</button>'

        provider_cards += f"""<div class="card" style="flex:1;min-width:160px">
  <div style="display:flex;justify-content:space-between;align-items:center">
    <strong style="color:#e8a849;text-transform:capitalize">{esc(p)}</strong>
    {status_badge}
  </div>
  <div style="font-size:11px;color:#4a5260;margin:4px 0">{esc(model)}</div>
  <div style="font-size:12px">
    <span style="color:#6db585">{successes} ok</span> ·
    <span style="color:#e8a849">{rl_count} rl</span> ·
    <span style="color:#d97757">{errors} err</span>
  </div>
  {f'<div style="font-size:10px;color:#d97757;margin-top:2px">{last_err[:60]}</div>' if last_err else ''}
  {reset_btn}
</div>"""

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>AI Usage</title>
<style>{ADMIN_CSS}</style></head><body>
{NAV_HTML}
<div class="page">
<h1>AI Usage Dashboard</h1>
<div class="subtitle">Provider health, usage per task, token budget</div>

<h2>Token Budget</h2>
<div style="display:flex;gap:8px;margin-bottom:24px">
<div class="stat"><div class="num">{s.tokens_used_this_month:,}</div><div class="lbl">Tokens Used</div></div>
<div class="stat"><div class="num">{s.max_tokens_per_run:,}</div><div class="lbl">Monthly Limit</div></div>
<div class="stat"><div class="num">{budget_pct}%</div><div class="lbl">Budget Used</div></div>
<div class="stat"><div class="num">{esc(s.budget_month or 'N/A')}</div><div class="lbl">Budget Month</div></div>
</div>

<h2>Provider Health</h2>
<div style="display:flex;flex-wrap:wrap;gap:12px;margin-bottom:24px">
{provider_cards}
</div>

<h2>Usage by Provider</h2>
<div id="provider-stats"><em style="color:#4a5260">Loading...</em></div>

<h2>Usage by Task</h2>
<div id="task-stats"><em style="color:#4a5260">Loading...</em></div>

<h2>Recent Calls (last 50)</h2>
<div id="recent-calls" style="max-height:400px;overflow-y:auto"><em style="color:#4a5260">Loading...</em></div>

<script>
async function resetProvider(name) {{
  await fetch('/admin/pipeline/api/ai-usage/reset-provider', {{
    method: 'POST', credentials: 'same-origin',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{provider: name}})
  }});
  window.location.reload();
}}

async function loadUsageData() {{
  try {{
    const resp = await fetch('/admin/pipeline/api/ai-usage', {{credentials: 'same-origin'}});
    const data = await resp.json();

    // Provider stats table
    if (data.provider_stats.length > 0) {{
      let html = '<table><tr><th>Provider</th><th>Calls</th><th>Success</th><th>Rate Limited</th><th>Errors</th><th>Tokens</th><th>Avg Latency</th></tr>';
      for (const p of data.provider_stats) {{
        html += `<tr>
          <td style="text-transform:capitalize">${{p.provider}}</td>
          <td>${{p.total_calls}}</td>
          <td style="color:#6db585">${{p.success}}</td>
          <td style="color:#e8a849">${{p.rate_limited}}</td>
          <td style="color:#d97757">${{p.errors}}</td>
          <td>${{p.total_tokens.toLocaleString()}}</td>
          <td>${{p.avg_latency_ms}}ms</td>
        </tr>`;
      }}
      html += '</table>';
      document.getElementById('provider-stats').innerHTML = html;
    }} else {{
      document.getElementById('provider-stats').innerHTML = '<p style="color:#4a5260">No usage data yet. Run a pipeline task to generate data.</p>';
    }}

    // Task stats table
    if (data.task_stats.length > 0) {{
      let html = '<table><tr><th>Task</th><th>Subtask</th><th>Calls</th><th>Success</th><th>Failures</th><th>Tokens</th></tr>';
      for (const t of data.task_stats) {{
        html += `<tr>
          <td>${{t.task}}</td>
          <td style="font-size:11px;color:#4a5260;max-width:200px;overflow:hidden;text-overflow:ellipsis">${{t.subtask}}</td>
          <td>${{t.total_calls}}</td>
          <td style="color:#6db585">${{t.success}}</td>
          <td style="color:#d97757">${{t.failures}}</td>
          <td>${{t.total_tokens.toLocaleString()}}</td>
        </tr>`;
      }}
      html += '</table>';
      document.getElementById('task-stats').innerHTML = html;
    }} else {{
      document.getElementById('task-stats').innerHTML = '<p style="color:#4a5260">No task data yet.</p>';
    }}

    // Recent calls
    if (data.recent.length > 0) {{
      let html = '<table><tr><th>Time</th><th>Provider</th><th>Task</th><th>Subtask</th><th>Status</th><th>Latency</th><th>Error</th></tr>';
      for (const r of data.recent) {{
        const statusCls = r.status === 'ok' ? 'approved' : r.status === 'rate_limited' ? 'pending' : 'rejected';
        html += `<tr>
          <td style="font-size:11px;white-space:nowrap">${{r.called_at}}</td>
          <td style="text-transform:capitalize">${{r.provider}}</td>
          <td>${{r.task}}</td>
          <td style="font-size:11px;color:#4a5260;max-width:150px;overflow:hidden;text-overflow:ellipsis">${{r.subtask}}</td>
          <td><span class="badge ${{statusCls}}">${{r.status}}</span></td>
          <td>${{r.latency_ms}}ms</td>
          <td style="font-size:10px;color:#d97757;max-width:200px;overflow:hidden;text-overflow:ellipsis">${{r.error_message}}</td>
        </tr>`;
      }}
      html += '</table>';
      document.getElementById('recent-calls').innerHTML = html;
    }} else {{
      document.getElementById('recent-calls').innerHTML = '<p style="color:#4a5260">No recent calls.</p>';
    }}
  }} catch(e) {{
    document.getElementById('provider-stats').innerHTML = '<p style="color:#d97757">Failed to load: ' + e.message + '</p>';
  }}
}}

loadUsageData();
</script>
</div>
</body></html>"""
