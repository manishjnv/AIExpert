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
from app.models.curriculum import CurriculumSettings, DiscoveredTopic
from app.models.user import User


class PipelineSettingsUpdate(BaseModel):
    """Validated settings update body."""
    max_topics_per_discovery: Optional[int] = Field(None, ge=1, le=50)
    discovery_frequency: Optional[str] = Field(None, pattern=r"^(weekly|monthly|quarterly)$")
    auto_approve_topics: Optional[bool] = None
    auto_generate_variants: Optional[bool] = None
    ai_model_research: Optional[str] = Field(None, pattern=r"^(gemini|groq)$")
    ai_model_formatting: Optional[str] = Field(None, pattern=r"^(gemini|groq)$")
    max_tokens_per_run: Optional[int] = Field(None, ge=0, le=1000000)
    refresh_frequency: Optional[str] = Field(None, pattern=r"^(monthly|quarterly)$")

router = APIRouter()

FONTS_HTML = '<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,400;9..144,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">'

LOGO_SVG = '<svg width="24" height="24" viewBox="0 0 24 24" style="vertical-align:middle;margin-right:6px"><rect width="24" height="24" rx="5" fill="#e8a849"/><path d="M7 17L12 6L17 17" stroke="#0f1419" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"/><circle cx="12" cy="10" r="2" fill="#0f1419"/><line x1="9" y1="14" x2="15" y2="14" stroke="#0f1419" stroke-width="1.5" stroke-linecap="round"/></svg>'

ADMIN_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,400;9..144,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');
body { font-family: 'IBM Plex Sans', system-ui, sans-serif; background: #0f1419; color: #f5f1e8; margin: 0; padding: 0; -webkit-font-smoothing: antialiased; }
.page { max-width: 1200px; margin: 0 auto; padding: 32px 48px; }
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
.topnav { padding: 12px 48px; display: flex; gap: 12px; align-items: center; border-bottom: 1px solid #2a323d; position: sticky; top: 0; z-index: 20; backdrop-filter: blur(12px); background: rgba(15,20,25,0.92); }
.topnav-brand { font-family: 'Fraunces', Georgia, serif; font-size: 16px; color: #e8a849; font-weight: 400; margin-right: auto; white-space: nowrap; text-decoration: none; }
.topnav-links { display: flex; gap: 4px; align-items: center; flex-wrap: wrap; }
.topnav-links a { font-family: 'IBM Plex Mono', monospace; font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: #e8e2d3; text-decoration: none; padding: 8px 12px; border-radius: 2px; transition: all 0.2s; }
.topnav-links a:hover { color: #e8a849; background: rgba(232,168,73,0.08); }
.topnav-links a.active { color: #e8a849; border-bottom: 2px solid #e8a849; }
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
@media (max-width: 768px) { .topnav { padding: 10px 16px; flex-wrap: wrap; } .topnav-brand { font-size: 14px; } .topnav-links a { font-size: 10px; padding: 6px 8px; } .page { padding: 20px 16px; } .stat { padding: 12px 14px; } .stat .num { font-size: 22px; } }
"""

NAV_HTML = """<nav class="topnav">
<a href="/" class="topnav-brand" style="text-decoration:none">""" + LOGO_SVG + """ AI Learning Roadmap</a>
<div class="topnav-links">
<a href="/admin/">Dashboard</a>
<a href="/admin/users">Users</a>
<a href="/admin/templates">Templates</a>
<a href="/admin/pipeline/">Pipeline</a>
<a href="/admin/pipeline/topics">Topics</a>
<a href="/admin/pipeline/settings">Settings</a>
</div>
</nav>"""


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
      <option value="gemini" {_sel(s.ai_model_research, 'gemini')}>Gemini (recommended)</option>
      <option value="groq" {_sel(s.ai_model_research, 'groq')}>Groq</option>
    </select>
  </div>
  <div class="form-group">
    <label>Formatting Model (cheap)</label>
    <select name="ai_model_formatting">
      <option value="groq" {_sel(s.ai_model_formatting, 'groq')}>Groq (recommended)</option>
      <option value="gemini" {_sel(s.ai_model_formatting, 'gemini')}>Gemini</option>
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
