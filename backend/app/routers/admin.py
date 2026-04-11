"""
Admin router — dashboard stats, user management, curriculum proposals.

All endpoints under /admin (prefix set in main.py). Protected by get_current_admin.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape as esc

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_admin
from app.db import get_db
from app.models.curriculum import CurriculumProposal, LinkHealth
from app.models.plan import UserPlan
from app.models.user import User

router = APIRouter()


def _check_origin(request: Request) -> None:
    """Basic CSRF mitigation: verify Origin/Referer matches our host."""
    origin = request.headers.get("origin") or request.headers.get("referer", "")
    host = request.headers.get("host", "")
    if origin and host and host not in origin:
        raise HTTPException(status_code=403, detail="Origin mismatch")


# ---- API endpoints ----

@router.get("/api/dashboard")
async def dashboard(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin dashboard stats."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    total_users = await db.scalar(select(func.count()).select_from(User)) or 0

    # DAU/WAU/MAU based on session issued_at (approximation)
    from app.models.user import Session as SessionModel
    dau = await db.scalar(
        select(func.count(func.distinct(SessionModel.user_id)))
        .where(SessionModel.issued_at > now - timedelta(days=1))
    ) or 0
    wau = await db.scalar(
        select(func.count(func.distinct(SessionModel.user_id)))
        .where(SessionModel.issued_at > now - timedelta(days=7))
    ) or 0
    mau = await db.scalar(
        select(func.count(func.distinct(SessionModel.user_id)))
        .where(SessionModel.issued_at > now - timedelta(days=30))
    ) or 0

    # Recent signups (last 7 days)
    recent_signups = (
        await db.execute(
            select(User.id, User.email, User.name, User.created_at)
            .where(User.created_at > now - timedelta(days=7))
            .order_by(User.created_at.desc())
            .limit(20)
        )
    ).all()

    # Dead links count
    dead_links = await db.scalar(
        select(func.count()).select_from(LinkHealth)
        .where(LinkHealth.consecutive_failures > 2)
    ) or 0

    return {
        "total_users": total_users,
        "dau": dau,
        "wau": wau,
        "mau": mau,
        "dead_links": dead_links,
        "recent_signups": [
            {"id": r.id, "email": r.email, "name": r.name,
             "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in recent_signups
        ],
    }


@router.get("/api/users")
async def list_users(
    q: str = Query("", description="Search by email or name"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Paginated user listing."""
    query = select(User)
    if q:
        query = query.where(
            User.email.contains(q) | User.name.contains(q)
        )
    query = query.order_by(User.created_at.desc())

    total = await db.scalar(
        select(func.count()).select_from(query.subquery())
    ) or 0

    rows = (
        await db.execute(
            query.offset((page - 1) * per_page).limit(per_page)
        )
    ).scalars().all()

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "name": u.name,
                "provider": u.provider,
                "is_admin": u.is_admin,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in rows
        ],
    }


@router.get("/api/proposals")
async def list_proposals(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List curriculum proposals."""
    rows = (
        await db.execute(
            select(CurriculumProposal).order_by(CurriculumProposal.created_at.desc())
        )
    ).scalars().all()

    return [
        {
            "id": p.id,
            "source_run": p.source_run,
            "status": p.status,
            "notes": p.notes,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "reviewed_at": p.reviewed_at.isoformat() if p.reviewed_at else None,
        }
        for p in rows
    ]


@router.post("/api/proposals/{proposal_id}/apply")
async def apply_proposal(
    proposal_id: int,
    request: Request,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Mark a proposal as applied."""
    _check_origin(request)
    proposal = await db.get(CurriculumProposal, proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    proposal.status = "applied"
    proposal.reviewer_id = user.id
    proposal.reviewed_at = now
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
    proposal = await db.get(CurriculumProposal, proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    proposal.status = "rejected"
    proposal.reviewer_id = user.id
    proposal.reviewed_at = now
    await db.flush()
    return {"ok": True, "status": "rejected"}


@router.post("/api/generate-template")
async def generate_template(
    request: Request,
    _user: User = Depends(get_current_admin),
):
    """Generate a new curriculum template using AI."""
    _check_origin(request)
    body = await request.json()
    topic = body.get("topic", "").strip()
    duration = int(body.get("duration", 6))
    level = body.get("level", "intermediate")

    if not topic:
        raise HTTPException(status_code=400, detail="Topic is required")
    if duration not in (3, 6, 9, 12):
        raise HTTPException(status_code=400, detail="Duration must be 3, 6, 9, or 12 months")
    if level not in ("beginner", "intermediate", "advanced"):
        raise HTTPException(status_code=400, detail="Level must be beginner, intermediate, or advanced")

    from app.services.curriculum_generator import generate_curriculum, save_curriculum_draft
    from app.ai.provider import AIProviderError

    try:
        plan_data = await generate_curriculum(topic, duration, level)
        path = await save_curriculum_draft(plan_data)
        return {
            "ok": True,
            "key": plan_data.get("key"),
            "title": plan_data.get("title"),
            "weeks": sum(len(m.get("weeks", [])) for m in plan_data.get("months", [])),
            "path": path,
        }
    except AIProviderError as e:
        raise HTTPException(status_code=503, detail=f"AI unavailable: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")


@router.get("/api/templates")
async def list_admin_templates(
    _user: User = Depends(get_current_admin),
):
    """List all templates with file details for admin."""
    from app.curriculum.loader import list_templates, load_template
    keys = list_templates()
    result = []
    for key in sorted(keys):
        try:
            tpl = load_template(key)
            result.append({
                "key": tpl.key,
                "title": tpl.title,
                "goal": tpl.goal,
                "level": tpl.level,
                "duration_months": tpl.duration_months,
                "total_weeks": tpl.total_weeks,
                "total_checks": tpl.total_checks,
            })
        except Exception:
            continue
    return result


@router.delete("/api/templates/{key}")
async def delete_template(
    key: str,
    request: Request,
    _user: User = Depends(get_current_admin),
):
    """Delete a template file."""
    _check_origin(request)
    from pathlib import Path
    path = Path(__file__).parent.parent / "curriculum" / "templates" / f"{key}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Template not found")
    # Don't delete the 3 original generalist templates
    if key.startswith("generalist_"):
        raise HTTPException(status_code=400, detail="Cannot delete default generalist templates")
    path.unlink()
    from app.curriculum.loader import load_template
    load_template.cache_clear()
    return {"ok": True, "deleted": key}


# ---- Jinja2 admin UI ----

ADMIN_CSS = """
body { font-family: system-ui, sans-serif; background: #0f1419; color: #f5f1e8; margin: 0; padding: 24px; }
h1 { color: #e8a849; font-size: 24px; margin-bottom: 16px; }
h2 { color: #e8a849; font-size: 18px; margin-top: 24px; }
.stat { display: inline-block; background: #1d242e; padding: 16px 24px; border-radius: 6px; margin: 4px; text-align: center; }
.stat .num { font-size: 28px; font-weight: bold; color: #e8a849; }
.stat .lbl { font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #4a5260; }
table { width: 100%; border-collapse: collapse; margin-top: 12px; }
th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid #2a323d; font-size: 13px; }
th { color: #4a5260; text-transform: uppercase; font-size: 10px; letter-spacing: 0.1em; }
.btn { padding: 4px 10px; border: 1px solid #2a323d; background: none; color: #f5f1e8; cursor: pointer; border-radius: 3px; font-size: 11px; }
.btn:hover { border-color: #e8a849; color: #e8a849; }
.btn.success { border-color: #6db585; color: #6db585; }
.btn.danger { border-color: #d97757; color: #d97757; }
nav { margin-bottom: 24px; }
nav a { color: #e8a849; text-decoration: none; margin-right: 16px; font-size: 13px; }
nav a:hover { text-decoration: underline; }
"""


@router.get("/", response_class=HTMLResponse)
async def admin_dashboard_page(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin dashboard HTML page."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    total_users = await db.scalar(select(func.count()).select_from(User)) or 0

    from app.models.user import Session as SessionModel
    dau = await db.scalar(
        select(func.count(func.distinct(SessionModel.user_id)))
        .where(SessionModel.issued_at > now - timedelta(days=1))
    ) or 0
    wau = await db.scalar(
        select(func.count(func.distinct(SessionModel.user_id)))
        .where(SessionModel.issued_at > now - timedelta(days=7))
    ) or 0
    mau = await db.scalar(
        select(func.count(func.distinct(SessionModel.user_id)))
        .where(SessionModel.issued_at > now - timedelta(days=30))
    ) or 0
    dead_links = await db.scalar(
        select(func.count()).select_from(LinkHealth)
        .where(LinkHealth.consecutive_failures > 2)
    ) or 0

    recent = (await db.execute(
        select(User).where(User.created_at > now - timedelta(days=7))
        .order_by(User.created_at.desc()).limit(10)
    )).scalars().all()

    signups_html = "".join(
        f"<tr><td>{u.id}</td><td>{esc(u.email)}</td><td>{esc(u.name or '-')}</td><td>{u.created_at}</td></tr>"
        for u in recent
    )

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Admin</title><style>{ADMIN_CSS}</style></head><body>
<nav><a href="/">← Site</a><a href="/admin/">Dashboard</a><a href="/admin/users">Users</a><a href="/admin/proposals">Proposals</a><a href="/admin/templates">Templates</a></nav>
<h1>Dashboard</h1>
<div class="stat"><div class="num">{total_users}</div><div class="lbl">Total Users</div></div>
<div class="stat"><div class="num">{dau}</div><div class="lbl">DAU</div></div>
<div class="stat"><div class="num">{wau}</div><div class="lbl">WAU</div></div>
<div class="stat"><div class="num">{mau}</div><div class="lbl">MAU</div></div>
<div class="stat"><div class="num">{dead_links}</div><div class="lbl">Dead Links</div></div>
<h2>Recent Signups</h2>
<table><tr><th>ID</th><th>Email</th><th>Name</th><th>Created</th></tr>{signups_html}</table>
</body></html>"""


@router.get("/users", response_class=HTMLResponse)
async def admin_users_page(
    q: str = Query(""),
    page: int = Query(1, ge=1),
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin users list HTML page."""
    query = select(User)
    if q:
        query = query.where(User.email.contains(q) | User.name.contains(q))
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (await db.execute(query.order_by(User.created_at.desc()).offset((page-1)*20).limit(20))).scalars().all()

    rows_html = "".join(
        f"<tr><td>{u.id}</td><td>{esc(u.email)}</td><td>{esc(u.name or '-')}</td><td>{esc(u.provider)}</td><td>{'Yes' if u.is_admin else ''}</td><td>{u.created_at}</td></tr>"
        for u in rows
    )

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Users</title><style>{ADMIN_CSS}</style></head><body>
<nav><a href="/">← Site</a><a href="/admin/">Dashboard</a><a href="/admin/users">Users</a><a href="/admin/proposals">Proposals</a><a href="/admin/templates">Templates</a></nav>
<h1>Users ({total})</h1>
<form style="margin-bottom:12px"><input name="q" value="{esc(q)}" placeholder="Search email or name" style="padding:6px;background:#1d242e;border:1px solid #2a323d;color:#f5f1e8;border-radius:3px"> <button class="btn" type="submit">Search</button></form>
<table><tr><th>ID</th><th>Email</th><th>Name</th><th>Provider</th><th>Admin</th><th>Created</th></tr>{rows_html}</table>
<div style="margin-top:12px">{'<a href="/admin/users?page='+str(page-1)+'&q='+esc(q)+'" class="btn">Prev</a> ' if page>1 else ''}{'<a href="/admin/users?page='+str(page+1)+'&q='+esc(q)+'" class="btn">Next</a>' if page*20<total else ''}</div>
</body></html>"""


@router.get("/proposals", response_class=HTMLResponse)
async def admin_proposals_page(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin proposals list HTML page."""
    rows = (await db.execute(
        select(CurriculumProposal).order_by(CurriculumProposal.created_at.desc())
    )).scalars().all()

    rows_html = ""
    for p in rows:
        actions = ""
        if p.status == "pending":
            actions = f'<form method="post" action="/admin/api/proposals/{p.id}/apply" style="display:inline"><button class="btn success">Apply</button></form> <form method="post" action="/admin/api/proposals/{p.id}/reject" style="display:inline"><button class="btn danger">Reject</button></form>'
        rows_html += f"<tr><td>{p.id}</td><td>{esc(p.source_run)}</td><td>{esc(p.status)}</td><td>{esc(p.notes or '-')}</td><td>{p.created_at}</td><td>{actions}</td></tr>"

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Proposals</title><style>{ADMIN_CSS}</style></head><body>
<nav><a href="/">← Site</a><a href="/admin/">Dashboard</a><a href="/admin/users">Users</a><a href="/admin/proposals">Proposals</a><a href="/admin/templates">Templates</a></nav>
<h1>Curriculum Proposals</h1>
<table><tr><th>ID</th><th>Source Run</th><th>Status</th><th>Notes</th><th>Created</th><th>Actions</th></tr>{rows_html}</table>
</body></html>"""


@router.get("/templates", response_class=HTMLResponse)
async def admin_templates_page(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin templates management page."""
    from app.curriculum.loader import list_templates, load_template

    keys = list_templates()
    rows_html = ""
    for key in sorted(keys):
        try:
            tpl = load_template(key)
            is_default = key.startswith("generalist_")
            delete_btn = "" if is_default else f'<button class="btn danger" onclick="deleteTemplate(&quot;{key}&quot;)">Delete</button>'
            rows_html += f"<tr><td>{esc(tpl.title)}</td><td>{esc(tpl.goal)}</td><td>{esc(tpl.level)}</td><td>{tpl.duration_months}mo</td><td>{tpl.total_weeks}</td><td>{tpl.total_checks}</td><td>{delete_btn}</td></tr>"
        except Exception:
            continue

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Templates</title><style>{ADMIN_CSS}</style></head><body>
<nav><a href="/">← Site</a><a href="/admin/">Dashboard</a><a href="/admin/users">Users</a><a href="/admin/proposals">Proposals</a><a href="/admin/templates">Templates</a></nav>
<h1>Plan Templates</h1>
<p style="color:#4a5260;font-size:13px;margin-bottom:16px">Add new templates by topic. AI generates the full curriculum automatically.</p>

<div style="background:#1d242e;padding:16px;border-radius:6px;margin-bottom:24px">
  <h2 style="font-size:16px;margin-bottom:12px">Generate New Template</h2>
  <div style="display:grid;grid-template-columns:2fr 1fr 1fr auto;gap:8px;align-items:end">
    <div><label style="font-size:10px;text-transform:uppercase;letter-spacing:0.1em;color:#4a5260;display:block;margin-bottom:4px">Topic</label><input id="genTopic" placeholder="e.g. NLP, Computer Vision, MLOps" style="width:100%;padding:8px;background:#0f1419;border:1px solid #2a323d;color:#f5f1e8;border-radius:3px"></div>
    <div><label style="font-size:10px;text-transform:uppercase;letter-spacing:0.1em;color:#4a5260;display:block;margin-bottom:4px">Duration</label><select id="genDuration" style="width:100%;padding:8px;background:#0f1419;border:1px solid #2a323d;color:#f5f1e8;border-radius:3px"><option value="3">3 months</option><option value="6" selected>6 months</option><option value="9">9 months</option><option value="12">12 months</option></select></div>
    <div><label style="font-size:10px;text-transform:uppercase;letter-spacing:0.1em;color:#4a5260;display:block;margin-bottom:4px">Level</label><select id="genLevel" style="width:100%;padding:8px;background:#0f1419;border:1px solid #2a323d;color:#f5f1e8;border-radius:3px"><option value="beginner">Beginner</option><option value="intermediate" selected>Intermediate</option><option value="advanced">Advanced</option></select></div>
    <button class="btn success" onclick="generateTemplate()" id="genBtn" style="padding:8px 16px">Generate</button>
  </div>
  <div id="genStatus" style="margin-top:8px;font-size:12px;color:#4a5260"></div>
</div>

<table><tr><th>Title</th><th>Goal</th><th>Level</th><th>Duration</th><th>Weeks</th><th>Checks</th><th>Actions</th></tr>{rows_html}</table>

<script>
async function generateTemplate() {{
  const btn = document.getElementById('genBtn');
  const status = document.getElementById('genStatus');
  const topic = document.getElementById('genTopic').value.trim();
  if (!topic) {{ status.textContent = 'Enter a topic'; return; }}
  btn.disabled = true;
  btn.textContent = 'Generating...';
  status.textContent = 'AI is generating curriculum... this takes 15-30 seconds.';
  try {{
    const resp = await fetch('/admin/api/generate-template', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      credentials: 'same-origin',
      body: JSON.stringify({{
        topic: topic,
        duration: document.getElementById('genDuration').value,
        level: document.getElementById('genLevel').value,
      }})
    }});
    const data = await resp.json();
    if (resp.ok) {{
      status.innerHTML = '<span style="color:#6db585">✓ Generated: ' + data.title + ' (' + data.weeks + ' weeks). Refreshing...</span>';
      setTimeout(() => window.location.reload(), 1500);
    }} else {{
      status.innerHTML = '<span style="color:#d97757">✗ ' + (data.detail || 'Failed') + '</span>';
    }}
  }} catch(e) {{
    status.innerHTML = '<span style="color:#d97757">✗ Error: ' + e.message + '</span>';
  }}
  btn.disabled = false;
  btn.textContent = 'Generate';
}}

async function deleteTemplate(key) {{
  if (!confirm('Delete template: ' + key + '?')) return;
  const resp = await fetch('/admin/api/templates/' + key, {{method: 'DELETE', credentials: 'same-origin'}});
  if (resp.ok) window.location.reload();
  else alert('Delete failed');
}}
</script>
</body></html>"""
