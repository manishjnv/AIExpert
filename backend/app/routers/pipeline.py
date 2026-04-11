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
            reset_btn = f'<button class="btn" style="margin-top:6px;font-size:10px" onclick="resetProvider(\'{p}\')">Retry This Provider</button>'

        provider_cards += f"""<div class="card" style="flex:1;min-width:170px">
  <div style="display:flex;justify-content:space-between;align-items:center">
    <strong style="color:#e8a849;text-transform:capitalize">{esc(p)}</strong>
    <span style="font-size:13px">{dot}</span>
  </div>
  <div style="font-size:13px;margin:6px 0;color:#f5f1e8">{status_text}</div>
  <div style="font-size:11px;color:#4a5260">{esc(reason)}</div>
  <div style="font-size:10px;color:#3a4452;margin-top:4px">Model: {esc(model)}</div>
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
      let html = '<table><tr><th>Provider</th><th>Total Calls</th><th>Succeeded</th><th>Rate Limited</th><th>Failed</th><th>Avg Speed</th></tr>';
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

      let html = '<table><tr><th>Time</th><th>Provider</th><th>Task</th><th>Result</th><th>Speed</th></tr>';
      for (const r of data.recent) {{
        html += `<tr>
          <td style="font-size:11px;white-space:nowrap">${{r.called_at.slice(11)}}</td>
          <td style="text-transform:capitalize">${{r.provider}}</td>
          <td>${{r.task}}${{r.subtask ? ' <span style="color:#4a5260;font-size:10px">(' + r.subtask.slice(0,30) + ')</span>' : ''}}</td>
          <td>${{friendlyStatus(r.status, r.error_message)}}</td>
          <td>${{friendlyTime(r.latency_ms)}}</td>
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


@router.get("/normalization", response_class=HTMLResponse)
async def normalization_page(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Normalization pipeline dashboard — stages, lifecycle, quality metrics."""
    s = await _get_settings(db)

    # Quick topic counts for server-rendered stats
    counts = {}
    for sv in ["pending", "approved", "generating", "generated", "rejected"]:
        counts[sv] = await db.scalar(
            select(func.count()).select_from(DiscoveredTopic).where(DiscoveredTopic.status == sv)
        ) or 0
    total = sum(counts.values())

    from app.curriculum.loader import list_templates
    templates_on_disk = len(list_templates())

    from app.models.curriculum import LinkHealth
    broken = await db.scalar(
        select(func.count()).select_from(LinkHealth).where(LinkHealth.consecutive_failures >= 2)
    ) or 0
    total_links = await db.scalar(select(func.count()).select_from(LinkHealth)) or 0

    last_disc = s.last_discovery_run.strftime("%Y-%m-%d %H:%M") if s.last_discovery_run else "Never"
    last_gen = s.last_generation_run.strftime("%Y-%m-%d %H:%M") if s.last_generation_run else "Never"
    last_ref = s.last_refresh_run.strftime("%Y-%m-%d %H:%M") if s.last_refresh_run else "Never"

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Normalization</title>
<style>{ADMIN_CSS}
.flow-row {{ display: flex; gap: 0; align-items: center; margin-bottom: 24px; flex-wrap: wrap; }}
.flow-stage {{ background: #1d242e; padding: 14px 18px; border-radius: 6px; text-align: center; min-width: 130px; }}
.flow-stage .num {{ font-family: 'Fraunces', Georgia, serif; font-size: 24px; color: #e8a849; }}
.flow-stage .lbl {{ font-family: 'IBM Plex Mono', monospace; font-size: 9px; text-transform: uppercase; letter-spacing: 0.1em; color: #4a5260; margin-top: 2px; }}
.flow-arrow {{ color: #3a4452; font-size: 20px; padding: 0 6px; }}
.grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px; }}
@media (max-width: 768px) {{ .grid-2 {{ grid-template-columns: 1fr; }} }}
</style></head><body>
{NAV_HTML}
<div class="page">
<h1>Normalization Pipeline</h1>
<div class="subtitle">Lifecycle stages, data quality, cache health, content freshness</div>

<h2>Pipeline Flow</h2>
<div class="flow-row">
  <div class="flow-stage"><div class="num">{total}</div><div class="lbl">Discovered</div></div>
  <div class="flow-arrow">&rarr;</div>
  <div class="flow-stage"><div class="num">{counts['pending']}</div><div class="lbl">Pending</div></div>
  <div class="flow-arrow">&rarr;</div>
  <div class="flow-stage"><div class="num">{counts['approved']}</div><div class="lbl">Approved</div></div>
  <div class="flow-arrow">&rarr;</div>
  <div class="flow-stage"><div class="num">{counts['generating']}</div><div class="lbl">Generating</div></div>
  <div class="flow-arrow">&rarr;</div>
  <div class="flow-stage"><div class="num">{counts['generated']}</div><div class="lbl">Generated</div></div>
  <div class="flow-arrow" style="margin-left:16px">|</div>
  <div class="flow-stage" style="border:1px solid #3d2020"><div class="num">{counts['rejected']}</div><div class="lbl">Rejected</div></div>
</div>

<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:24px">
  <div class="stat"><div class="num">{templates_on_disk}</div><div class="lbl">Templates on Disk</div></div>
  <div class="stat"><div class="num">{total_links}</div><div class="lbl">Links Tracked</div></div>
  <div class="stat"><div class="num" style="color:{'#d97757' if broken > 0 else '#6db585'}">{broken}</div><div class="lbl">Broken Links</div></div>
  <div class="stat"><div class="num">{esc(last_disc)}</div><div class="lbl">Last Discovery</div></div>
  <div class="stat"><div class="num">{esc(last_gen)}</div><div class="lbl">Last Generation</div></div>
  <div class="stat"><div class="num">{esc(last_ref)}</div><div class="lbl">Last Refresh</div></div>
</div>

<div class="grid-2">

<div>
<h2>Stage A: Discovery</h2>
<div class="card" id="discovery-stats"><em style="color:#4a5260">Loading...</em></div>

<h2>Stage B: Generation</h2>
<div class="card" id="generation-stats"><em style="color:#4a5260">Loading...</em></div>
</div>

<div>
<h2>Stage C: Content Refresh</h2>
<div class="card" id="refresh-stats"><em style="color:#4a5260">Loading...</em></div>

<h2>Cache Health</h2>
<div class="card" id="cache-stats"><em style="color:#4a5260">Loading...</em></div>

<h2>Config</h2>
<div class="card" id="config-stats"><em style="color:#4a5260">Loading...</em></div>
</div>

</div>

<h2>Discovery Runs</h2>
<div id="discovery-runs"><em style="color:#4a5260">Loading...</em></div>

<h2>Generation by Topic</h2>
<div id="gen-by-topic" style="max-height:400px;overflow-y:auto"><em style="color:#4a5260">Loading...</em></div>

<script>
async function loadNormData() {{
  try {{
    const resp = await fetch('/admin/pipeline/api/normalization', {{credentials: 'same-origin'}});
    const d = await resp.json();

    // Discovery stats
    const disc = d.discovery;
    let catHtml = disc.categories.map(c => `<span style="display:inline-block;background:#0f1419;padding:2px 8px;border-radius:10px;font-size:11px;margin:2px">${{c.category}} <strong>${{c.count}}</strong></span>`).join('');
    document.getElementById('discovery-stats').innerHTML = `
      <div style="font-size:13px;margin-bottom:8px"><strong>Avg Confidence:</strong> <span style="color:#e8a849">${{disc.avg_confidence}}/100</span></div>
      <div style="font-size:13px;margin-bottom:8px"><strong>Categories:</strong></div>
      <div style="margin-bottom:8px">${{catHtml || '<em style="color:#4a5260">No topics yet</em>'}}</div>
      <div style="font-size:12px;color:#4a5260">
        Dedup and triage filtering happen during discovery.<br>
        Rejected topics can be re-approved from the Topics page.
      </div>`;

    // Generation stats
    const gen = d.generation;
    document.getElementById('generation-stats').innerHTML = `
      <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:8px">
        <div><span style="color:#e8a849;font-size:20px;font-family:'Fraunces',serif">${{gen.total_variants_generated}}</span><div style="font-size:9px;color:#4a5260;text-transform:uppercase">Variants Generated</div></div>
        <div><span style="color:#6db585;font-size:20px;font-family:'Fraunces',serif">${{gen.topics_with_templates}}</span><div style="font-size:9px;color:#4a5260;text-transform:uppercase">Topics Complete</div></div>
        <div><span style="color:#d97757;font-size:20px;font-family:'Fraunces',serif">${{gen.topics_with_errors}}</span><div style="font-size:9px;color:#4a5260;text-transform:uppercase">With Errors</div></div>
        <div><span style="color:#f5f1e8;font-size:20px;font-family:'Fraunces',serif">${{gen.templates_on_disk}}</span><div style="font-size:9px;color:#4a5260;text-transform:uppercase">On Disk</div></div>
      </div>
      <div style="font-size:12px;color:#4a5260">
        Each topic generates up to 5 variants: 3mo/6mo × beginner/intermediate/advanced.
      </div>`;

    // Refresh stats
    const ref = d.refresh;
    const linkPct = ref.total_links > 0 ? Math.round(ref.ok_links / ref.total_links * 100) : 0;
    let brokenHtml = ref.broken_by_template.length > 0
      ? '<div style="margin-top:8px;font-size:12px"><strong>Broken by template:</strong></div>' +
        ref.broken_by_template.map(b => `<div style="font-size:11px;color:#d97757">• ${{b.template}}: ${{b.count}} broken</div>`).join('')
      : '';
    document.getElementById('refresh-stats').innerHTML = `
      <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:8px">
        <div><span style="color:#6db585;font-size:20px;font-family:'Fraunces',serif">${{ref.ok_links}}</span><div style="font-size:9px;color:#4a5260;text-transform:uppercase">Links OK</div></div>
        <div><span style="color:#d97757;font-size:20px;font-family:'Fraunces',serif">${{ref.broken_links}}</span><div style="font-size:9px;color:#4a5260;text-transform:uppercase">Broken</div></div>
        <div><span style="color:#f5f1e8;font-size:20px;font-family:'Fraunces',serif">${{ref.total_links}}</span><div style="font-size:9px;color:#4a5260;text-transform:uppercase">Total</div></div>
        <div><span style="color:#e8a849;font-size:20px;font-family:'Fraunces',serif">${{linkPct}}%</span><div style="font-size:9px;color:#4a5260;text-transform:uppercase">Health</div></div>
      </div>
      <div style="font-size:12px;color:#4a5260">Last refresh: ${{ref.last_refresh || 'Never'}}</div>
      ${{brokenHtml}}`;

    // Cache stats
    const cache = d.cache;
    document.getElementById('cache-stats').innerHTML = `
      <table style="margin:0">
        <tr><th>Type</th><th>Cached</th></tr>
        <tr><td>Discovery</td><td>${{cache.discovery}}</td></tr>
        <tr><td>Triage</td><td>${{cache.triage}}</td></tr>
        <tr><td>Generation</td><td>${{cache.generation}}</td></tr>
        <tr><td>Currency Review</td><td>${{cache.currency_review}}</td></tr>
        <tr><td style="color:#d97757">Expired</td><td style="color:#d97757">${{cache.expired}}</td></tr>
        <tr><td><strong>Total Files</strong></td><td><strong>${{cache.total_files}}</strong></td></tr>
      </table>`;

    // Config
    const cfg = d.config;
    document.getElementById('config-stats').innerHTML = `
      <table style="margin:0">
        <tr><td style="color:#4a5260">Discovery Limit</td><td>${{cfg.max_topics_per_discovery}} topics</td></tr>
        <tr><td style="color:#4a5260">Discovery Freq</td><td>${{cfg.discovery_frequency}}</td></tr>
        <tr><td style="color:#4a5260">Auto-Approve</td><td>${{cfg.auto_approve ? '✓ Yes' : '✗ No'}}</td></tr>
        <tr><td style="color:#4a5260">Auto-Generate</td><td>${{cfg.auto_generate ? '✓ Yes' : '✗ No'}}</td></tr>
        <tr><td style="color:#4a5260">Refresh Freq</td><td>${{cfg.refresh_frequency}}</td></tr>
      </table>`;

    // Discovery runs
    if (disc.recent_runs.length > 0) {{
      let html = '<table><tr><th>Run</th><th>Model</th><th>Topics Found</th></tr>';
      for (const r of disc.recent_runs) {{
        html += `<tr><td style="font-size:11px">${{r.run_id}}</td><td>${{r.model}}</td><td>${{r.topics_found}}</td></tr>`;
      }}
      html += '</table>';
      document.getElementById('discovery-runs').innerHTML = html;
    }} else {{
      document.getElementById('discovery-runs').innerHTML = '<p style="color:#4a5260">No discovery runs yet.</p>';
    }}

    // Generation by topic
    if (gen.per_topic.length > 0) {{
      let html = '<table><tr><th>Topic</th><th>Variants</th><th>Status</th><th>Error</th></tr>';
      for (const t of gen.per_topic) {{
        const statusCls = t.status === 'generated' ? 'approved' : t.status === 'approved' ? 'pending' : 'rejected';
        html += `<tr>
          <td style="max-width:250px;overflow:hidden;text-overflow:ellipsis">${{t.topic}}</td>
          <td>${{t.variants}}/5</td>
          <td><span class="badge ${{statusCls}}">${{t.status}}</span></td>
          <td style="font-size:10px;color:#d97757;max-width:300px;overflow:hidden;text-overflow:ellipsis">${{t.error}}</td>
        </tr>`;
      }}
      html += '</table>';
      document.getElementById('gen-by-topic').innerHTML = html;
    }} else {{
      document.getElementById('gen-by-topic').innerHTML = '<p style="color:#4a5260">No templates generated yet.</p>';
    }}
  }} catch(e) {{
    document.getElementById('discovery-stats').innerHTML = '<p style="color:#d97757">Failed: ' + e.message + '</p>';
  }}
}}

loadNormData();
</script>
</div>
</body></html>"""
