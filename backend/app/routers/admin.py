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
    """List all templates with file details and publish status for admin."""
    from app.curriculum.loader import list_templates, load_template, get_template_status
    grandfathered = {"generalist_3mo_intermediate", "generalist_6mo_intermediate", "generalist_12mo_beginner"}
    keys = list_templates()
    result = []
    for key in sorted(keys):
        try:
            tpl = load_template(key)
            status_info = get_template_status(key)
            pub_status = status_info.get("status", "draft")
            if key in grandfathered and pub_status == "draft":
                pub_status = "published"
            result.append({
                "key": tpl.key,
                "title": tpl.title,
                "goal": tpl.goal,
                "level": tpl.level,
                "duration_months": tpl.duration_months,
                "total_weeks": tpl.total_weeks,
                "total_checks": tpl.total_checks,
                "publish_status": pub_status,
                "quality_score": status_info.get("quality_score", 0),
            })
        except Exception:
            continue
    return result


@router.get("/api/templates/{key}")
async def get_template_detail(
    key: str,
    _user: User = Depends(get_current_admin),
):
    """Get full template content for admin review."""
    from app.curriculum.loader import load_template
    try:
        tpl = load_template(key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Template not found")
    return tpl.model_dump()


@router.get("/templates/{key}", response_class=HTMLResponse)
async def admin_template_view(
    key: str,
    _user: User = Depends(get_current_admin),
):
    """Admin template detail page — view full curriculum content."""
    from app.curriculum.loader import load_template, get_template_status

    try:
        tpl = load_template(key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Template not found")

    status_info = get_template_status(key)
    pub_status = status_info.get("status", "draft")
    grandfathered = {"generalist_3mo_intermediate", "generalist_6mo_intermediate", "generalist_12mo_beginner"}
    if key in grandfathered and pub_status == "draft":
        pub_status = "published"
    q_score = status_info.get("quality_score", 0)

    status_color = "#6db585" if pub_status == "published" else "#e8a849"
    score_color = "#6db585" if q_score >= 90 else "#e8a849" if q_score >= 70 else "#d97757" if q_score > 0 else "#8a92a0"

    months_html = ""
    for m in tpl.months:
        weeks_html = ""
        for w in m.weeks:
            resources_html = "".join(
                f'<li><a href="{esc(r.url)}" target="_blank" style="color:#e8a849">{esc(r.name)}</a> <span style="color:#8a92a0">({r.hrs}h)</span></li>'
                for r in w.resources
            )
            checks_html = "".join(f"<li>{esc(c)}</li>" for c in w.checks)
            focus_html = " · ".join(esc(f) for f in w.focus)
            deliv_html = "".join(f"<li>{esc(d)}</li>" for d in w.deliv)

            weeks_html += f"""
            <div style="background:#0f1419;border-radius:6px;padding:16px;margin-bottom:12px">
                <h4 style="margin:0 0 8px">Week {w.n}: {esc(w.t)} <span style="color:#8a92a0;font-weight:400;font-size:12px">({w.hours}h)</span></h4>
                <div style="font-size:12px;color:#8a92a0;margin-bottom:8px">{focus_html}</div>
                {'<div style="margin-bottom:8px"><strong style="font-size:12px;color:#e8a849">Deliverables</strong><ul style="margin:4px 0;padding-left:20px;font-size:13px">' + deliv_html + '</ul></div>' if w.deliv else ''}
                {'<div style="margin-bottom:8px"><strong style="font-size:12px;color:#6db585">Resources</strong><ul style="margin:4px 0;padding-left:20px;font-size:13px">' + resources_html + '</ul></div>' if w.resources else ''}
                {'<div><strong style="font-size:12px;color:#d0cbc2">Checklist</strong><ul style="margin:4px 0;padding-left:20px;font-size:13px">' + checks_html + '</ul></div>' if w.checks else ''}
            </div>"""

        months_html += f"""
        <div style="margin-bottom:24px">
            <h3 style="color:#e8a849;margin-bottom:4px">{esc(m.label)}: {esc(m.title)}</h3>
            <p style="font-size:13px;color:#8a92a0;margin-bottom:4px"><em>{esc(m.tagline)}</em></p>
            <p style="font-size:12px;color:#6db585;margin-bottom:12px">Checkpoint: {esc(m.checkpoint)}</p>
            {weeks_html}
        </div>"""

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>{esc(tpl.title)}</title>
<style>{ADMIN_CSS}</style></head><body>
{ADMIN_NAV}
<div class="page">
<div style="margin-bottom:16px"><a href="/admin/templates" style="color:#8a92a0;font-size:13px">&larr; Back to Templates</a></div>
<h1>{esc(tpl.title)}</h1>
<div style="display:flex;gap:12px;align-items:center;margin-bottom:16px">
    <span style="color:{status_color};font-weight:600">{pub_status.title()}</span>
    <span style="color:#8a92a0">·</span>
    <span>{esc(tpl.level)} · {tpl.duration_months}mo · {tpl.total_weeks} weeks · {tpl.total_checks} checks</span>
    <span style="color:#8a92a0">·</span>
    <span style="color:{score_color};font-weight:600">Quality: {q_score if q_score else '—'}</span>
</div>
<p style="color:#8a92a0;font-size:13px;margin-bottom:24px">{esc(tpl.goal)}</p>
{months_html}
</div></body></html>"""


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
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,400;9..144,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');
body { font-family: 'IBM Plex Sans', system-ui, sans-serif; background: #0f1419; color: #e0dbd2; margin: 0; padding: 0; -webkit-font-smoothing: antialiased; font-size: 14px; line-height: 1.6; }
.page { max-width: 100%; margin: 0; padding: 32px 48px; }
h1 { font-family: 'Fraunces', Georgia, serif; color: #e8a849; font-size: 28px; font-weight: 300; margin-bottom: 4px; }
h2 { font-family: 'Fraunces', Georgia, serif; color: #e8a849; font-size: 18px; margin-top: 24px; }
h3 { font-family: 'Fraunces', Georgia, serif; color: #e8a849; font-size: 15px; }
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
.btn.danger { border-color: #d97757; color: #d97757; }
.card { background: #1d242e; padding: 16px; border-radius: 6px; }
@media (max-width: 768px) { .page { padding: 20px 16px; } .stat { padding: 12px 14px; } .stat .num { font-size: 22px; } }
"""

ADMIN_NAV = '<link rel="stylesheet" href="/nav.css"><script src="/nav.js"></script>'


@router.get("/", response_class=HTMLResponse)
async def admin_dashboard_page(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin dashboard — platform-wide overview."""
    from app.curriculum.loader import list_templates
    from app.models.curriculum import DiscoveredTopic

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    total_users = await db.scalar(select(func.count()).select_from(User)) or 0
    enrolled = await db.scalar(
        select(func.count(func.distinct(UserPlan.user_id)))
        .where(UserPlan.status == "active")
    ) or 0

    # ---- Content ----
    template_count = len(list_templates())
    total_topics = await db.scalar(select(func.count()).select_from(DiscoveredTopic)) or 0
    generated_topics = await db.scalar(
        select(func.count()).select_from(DiscoveredTopic)
        .where(DiscoveredTopic.status == "generated")
    ) or 0
    pending_topics = await db.scalar(
        select(func.count()).select_from(DiscoveredTopic)
        .where(DiscoveredTopic.status == "pending")
    ) or 0
    dead_links = await db.scalar(
        select(func.count()).select_from(LinkHealth)
        .where(LinkHealth.consecutive_failures > 2)
    ) or 0

    # ---- Recent signups ----
    recent = (await db.execute(
        select(User).where(User.created_at > now - timedelta(days=7))
        .order_by(User.created_at.desc()).limit(5)
    )).scalars().all()

    signups_html = "".join(
        f'<tr><td>{esc(u.name or "-")}</td><td style="color:#8a92a0">{esc(u.email)}</td><td>{esc(u.provider)}</td><td>{u.created_at.strftime("%b %d, %H:%M") if u.created_at else "-"}</td></tr>'
        for u in recent
    )

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Admin</title><style>{ADMIN_CSS}</style></head><body>
{ADMIN_NAV}
<div class="page">
<h1>Dashboard</h1>
<div class="subtitle">Platform overview</div>

<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:24px">
<div class="stat"><div class="num">{total_users}</div><div class="lbl">Total Users</div></div>
<div class="stat"><div class="num">{enrolled}</div><div class="lbl">Enrolled</div></div>
<div class="stat"><div class="num">{template_count}</div><div class="lbl">Templates</div></div>
<div class="stat"><div class="num">{total_topics}</div><div class="lbl">Topics</div></div>
<div class="stat"><div class="num">{generated_topics}</div><div class="lbl">Generated</div></div>
<div class="stat"><div class="num">{pending_topics}</div><div class="lbl">Pending Review</div></div>
<div class="stat"><div class="num" style="color:{'#d97757' if dead_links > 0 else '#6db585'}">{dead_links}</div><div class="lbl">Broken Links</div></div>
</div>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-bottom:24px">

<div>
<h2>Recent Signups</h2>
{f'<table><tr><th>Name</th><th>Email</th><th>Auth</th><th>Joined</th></tr>{signups_html}</table>' if signups_html else '<p style="color:#8a92a0;font-size:13px">No signups this week</p>'}
</div>

<div>
<h2>Quick Actions</h2>
<div style="display:flex;flex-direction:column;gap:8px">
<a href="/admin/users" class="btn" style="text-align:center">Manage Users</a>
<a href="/admin/pipeline/" class="btn" style="text-align:center">Run Pipeline</a>
<a href="/admin/templates" class="btn" style="text-align:center">Manage Templates</a>
<a href="/admin/pipeline/ai-usage" class="btn" style="text-align:center">AI Usage</a>
</div>
</div>

</div>

</div></body></html>"""


@router.get("/users", response_class=HTMLResponse)
async def admin_users_page(
    q: str = Query(""),
    page: int = Query(1, ge=1),
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin users list with stats, session history, device info."""
    from app.models.user import Session as SessionModel

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # ---- Anonymous stats ----
    from app.main import get_anon_stats
    anon = get_anon_stats()

    # ---- Summary stats ----
    total_users = await db.scalar(select(func.count()).select_from(User)) or 0
    users_with_plans = await db.scalar(
        select(func.count(func.distinct(UserPlan.user_id)))
        .where(UserPlan.status == "active")
    ) or 0
    active_sessions = await db.scalar(
        select(func.count()).select_from(SessionModel)
        .where(SessionModel.expires_at > now, SessionModel.revoked_at.is_(None))
    ) or 0
    google_users = await db.scalar(
        select(func.count()).select_from(User).where(User.provider == "google")
    ) or 0
    otp_users = await db.scalar(
        select(func.count()).select_from(User).where(User.provider == "otp")
    ) or 0
    today_logins = await db.scalar(
        select(func.count(func.distinct(SessionModel.user_id)))
        .where(SessionModel.issued_at > now - timedelta(days=1))
    ) or 0
    week_logins = await db.scalar(
        select(func.count(func.distinct(SessionModel.user_id)))
        .where(SessionModel.issued_at > now - timedelta(days=7))
    ) or 0
    new_this_week = await db.scalar(
        select(func.count()).select_from(User)
        .where(User.created_at > now - timedelta(days=7))
    ) or 0

    # ---- User list ----
    query = select(User)
    if q:
        query = query.where(User.email.contains(q) | User.name.contains(q))
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (await db.execute(query.order_by(User.created_at.desc()).offset((page-1)*20).limit(20))).scalars().all()

    # Get last session for each user (for IP, user_agent, last login)
    user_ids = [u.id for u in rows]
    last_sessions = {}
    if user_ids:
        for uid in user_ids:
            sess = (await db.execute(
                select(SessionModel)
                .where(SessionModel.user_id == uid)
                .order_by(SessionModel.issued_at.desc())
                .limit(1)
            )).scalar_one_or_none()
            if sess:
                last_sessions[uid] = sess

    # Get plan info per user
    user_plans = {}
    if user_ids:
        plan_rows = (await db.execute(
            select(UserPlan.user_id, UserPlan.template_key, UserPlan.status)
            .where(UserPlan.user_id.in_(user_ids), UserPlan.status == "active")
        )).all()
        for pr in plan_rows:
            user_plans[pr.user_id] = pr.template_key

    rows_html = ""
    for u in rows:
        sess = last_sessions.get(u.id)
        last_ip = esc(sess.ip or "-") if sess else "-"
        last_login = sess.issued_at.strftime("%b %d, %H:%M") if sess else "-"

        # Parse user agent for device info
        ua_raw = sess.user_agent if sess else ""
        device = _parse_device(ua_raw)

        plan = user_plans.get(u.id, "")
        plan_badge = f'<span style="color:#6db585;font-size:12px">{esc(plan)}</span>' if plan else '<span style="color:#8a92a0;font-size:12px">No plan</span>'

        provider_icon = "G" if u.provider == "google" else "✉"
        admin_badge = ' <span style="color:#e8a849;font-size:12px">ADMIN</span>' if u.is_admin else ""

        created = u.created_at.strftime("%b %d, %Y") if u.created_at else "-"

        rows_html += f"""<tr>
<td>{u.id}</td>
<td>
  <div><strong>{esc(u.name or '-')}</strong>{admin_badge}</div>
  <div style="font-size:12px;color:#8a92a0">{esc(u.email)}</div>
</td>
<td><span title="{esc(u.provider)}">{provider_icon}</span></td>
<td>{plan_badge}</td>
<td style="font-size:12px">{last_login}</td>
<td style="font-size:12px;color:#8a92a0">{last_ip}</td>
<td style="font-size:12px;color:#8a92a0" data-ip="{esc(sess.ip or '') if sess else ''}" class="loc-cell">—</td>
<td style="font-size:12px;color:#8a92a0" title="{esc((ua_raw or '')[:100])}">{esc(device)}</td>
<td style="font-size:12px">{created}</td>
</tr>"""

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Users</title><style>{ADMIN_CSS}</style></head><body>
{ADMIN_NAV}
<div class="page">
<h1>Users</h1>
<div class="subtitle">User activity, sessions, and enrollment</div>

<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px">
<div class="stat"><div class="num">{total_users}</div><div class="lbl">Total Users</div></div>
<div class="stat"><div class="num">{today_logins}</div><div class="lbl">Logged In Today</div></div>
<div class="stat"><div class="num">{week_logins}</div><div class="lbl">This Week</div></div>
<div class="stat"><div class="num">{new_this_week}</div><div class="lbl">New This Week</div></div>
<div class="stat"><div class="num">{active_sessions}</div><div class="lbl">Active Sessions</div></div>
<div class="stat"><div class="num">{users_with_plans}</div><div class="lbl">Enrolled</div></div>
<div class="stat"><div class="num">{google_users}</div><div class="lbl">Google SSO</div></div>
<div class="stat"><div class="num">{otp_users}</div><div class="lbl">Email OTP</div></div>
</div>
<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:24px">
<div class="stat" style="border-left:3px solid #5d9be8"><div class="num">{anon['today_hits']}</div><div class="lbl">Anonymous Today</div></div>
<div class="stat" style="border-left:3px solid #5d9be8"><div class="num">{anon['today_unique']}</div><div class="lbl">Unique Visitors Today</div></div>
<div class="stat" style="border-left:3px solid #5d9be8"><div class="num">{anon['total_hits']}</div><div class="lbl">Total Anonymous</div></div>
<div class="stat" style="border-left:3px solid #5d9be8"><div class="num">{anon['unique_visitors']}</div><div class="lbl">Unique All Time</div></div>
</div>

<form style="margin-bottom:12px"><input name="q" value="{esc(q)}" placeholder="Search email or name" style="padding:8px 12px;background:#1d242e;border:1px solid #2a323d;color:#f5f1e8;border-radius:3px;width:250px"> <button class="btn" type="submit">Search</button></form>

<table>
<tr><th>ID</th><th>User</th><th>Auth</th><th>Plan</th><th>Last Login</th><th>IP</th><th>Location</th><th>Device</th><th>Joined</th></tr>
{rows_html}
</table>
<div style="margin-top:12px;font-size:12px;color:#8a92a0">
  Showing {len(rows)} of {total} users
  {'  <a href="/admin/users?page='+str(page-1)+'&q='+esc(q)+'" class="btn">Prev</a>' if page>1 else ''}
  {'  <a href="/admin/users?page='+str(page+1)+'&q='+esc(q)+'" class="btn">Next</a>' if page*20<total else ''}
</div>

<script>
// Geo-lookup for IP addresses (free ip-api.com, no key needed)
(async function() {{
  const cells = document.querySelectorAll('.loc-cell');
  const ips = new Set();
  cells.forEach(c => {{ const ip = c.dataset.ip; if (ip && ip !== '-' && !ip.startsWith('127.') && !ip.startsWith('10.')) ips.add(ip); }});
  if (ips.size === 0) return;

  // Batch lookup (ip-api supports batch POST for up to 100 IPs)
  try {{
    const ipList = [...ips].slice(0, 100);
    const resp = await fetch('http://ip-api.com/batch?fields=query,city,country,countryCode', {{
      method: 'POST',
      body: JSON.stringify(ipList.map(ip => ({{ query: ip }})))
    }});
    const results = await resp.json();
    const lookup = {{}};
    for (const r of results) {{
      if (r.city && r.countryCode) lookup[r.query] = r.city + ', ' + r.countryCode;
      else if (r.country) lookup[r.query] = r.country;
    }}
    cells.forEach(c => {{
      const ip = c.dataset.ip;
      if (lookup[ip]) c.textContent = lookup[ip];
    }});
  }} catch(e) {{
    // Geo-lookup failed silently — locations stay as "—"
  }}
}})();
</script>
</div></body></html>"""


def _parse_device(ua: str) -> str:
    """Extract a short device description from User-Agent string."""
    if not ua:
        return "-"
    ua_lower = ua.lower()

    # OS
    if "iphone" in ua_lower:
        os_name = "iPhone"
    elif "ipad" in ua_lower:
        os_name = "iPad"
    elif "android" in ua_lower:
        os_name = "Android"
    elif "macintosh" in ua_lower or "mac os" in ua_lower:
        os_name = "Mac"
    elif "windows" in ua_lower:
        os_name = "Windows"
    elif "linux" in ua_lower:
        os_name = "Linux"
    elif "cli-test" in ua_lower:
        return "CLI"
    else:
        os_name = "Other"

    # Browser
    if "edg/" in ua_lower:
        browser = "Edge"
    elif "chrome" in ua_lower and "safari" in ua_lower:
        browser = "Chrome"
    elif "firefox" in ua_lower:
        browser = "Firefox"
    elif "safari" in ua_lower:
        browser = "Safari"
    else:
        browser = ""

    return f"{os_name} · {browser}" if browser else os_name


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
{ADMIN_NAV}
<div class="page">
<h1>Curriculum Proposals</h1>
<table><tr><th>ID</th><th>Source Run</th><th>Status</th><th>Notes</th><th>Created</th><th>Actions</th></tr>{rows_html}</table>
</div></body></html>"""


@router.get("/templates", response_class=HTMLResponse)
async def admin_templates_page(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin templates management page."""
    from app.curriculum.loader import list_templates, load_template, get_template_status
    from app.models.plan import UserPlan

    # Get subscriber counts per template (active enrollments only)
    sub_rows = await db.execute(
        select(UserPlan.template_key, func.count(UserPlan.id))
        .where(UserPlan.status == "active")
        .group_by(UserPlan.template_key)
    )
    subscriber_counts = {row[0]: row[1] for row in sub_rows}

    grandfathered = {"generalist_3mo_intermediate", "generalist_6mo_intermediate", "generalist_12mo_beginner"}
    keys = list_templates()
    rows_html = ""
    for key in sorted(keys):
        try:
            tpl = load_template(key)
            is_default = key in grandfathered
            delete_btn = "" if is_default else f'<button class="btn danger" onclick="deleteTemplate(&quot;{key}&quot;)">Delete</button>'

            status_info = get_template_status(key)
            pub_status = status_info.get("status", "draft")
            q_score = status_info.get("quality_score", 0)
            if is_default and pub_status == "draft":
                pub_status = "published"

            if pub_status == "published":
                status_badge = '<span style="background:#1d3525;color:#6db585;padding:2px 8px;border-radius:10px;font-size:11px">Published</span>'
            else:
                status_badge = '<span style="background:#2a2520;color:#e8a849;padding:2px 8px;border-radius:10px;font-size:11px">Draft</span>'

            score_color = "#6db585" if q_score >= 90 else "#e8a849" if q_score >= 70 else "#d97757" if q_score > 0 else "#8a92a0"
            score_display = f'<span style="color:{score_color};font-weight:600">{q_score}</span>' if q_score > 0 else '<span style="color:#8a92a0">—</span>'

            subs = subscriber_counts.get(key, 0)
            subs_display = f'<span style="font-weight:600">{subs}</span>' if subs > 0 else '<span style="color:#8a92a0">0</span>'

            rows_html += f"<tr><td><a href='/admin/templates/{key}' style='color:#e8a849'>{esc(tpl.title)}</a></td><td>{esc(tpl.level)}</td><td>{tpl.duration_months}mo</td><td>{tpl.total_weeks}</td><td>{tpl.total_checks}</td><td style='text-align:center'>{subs_display}</td><td style='text-align:center'>{status_badge}</td><td style='text-align:center'>{score_display}</td><td>{delete_btn}</td></tr>"
        except Exception:
            continue

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Templates</title><style>{ADMIN_CSS}</style></head><body>
{ADMIN_NAV}
<div class="page">
<h1>Plan Templates</h1>
<p style="color:#8a92a0;font-size:13px;margin-bottom:16px">Add new templates by topic. AI generates the full curriculum automatically.</p>

<div style="background:#1d242e;padding:16px;border-radius:6px;margin-bottom:24px">
  <h2 style="font-size:16px;margin-bottom:12px">Generate New Template</h2>
  <div style="display:grid;grid-template-columns:2fr 1fr 1fr auto;gap:8px;align-items:end">
    <div><label style="font-size:12px;text-transform:uppercase;letter-spacing:0.1em;color:#8a92a0;display:block;margin-bottom:4px">Topic</label><input id="genTopic" placeholder="e.g. NLP, Computer Vision, MLOps" style="width:100%;padding:8px;background:#0f1419;border:1px solid #2a323d;color:#f5f1e8;border-radius:3px"></div>
    <div><label style="font-size:12px;text-transform:uppercase;letter-spacing:0.1em;color:#8a92a0;display:block;margin-bottom:4px">Duration</label><select id="genDuration" style="width:100%;padding:8px;background:#0f1419;border:1px solid #2a323d;color:#f5f1e8;border-radius:3px"><option value="3">3 months</option><option value="6" selected>6 months</option><option value="9">9 months</option><option value="12">12 months</option></select></div>
    <div><label style="font-size:12px;text-transform:uppercase;letter-spacing:0.1em;color:#8a92a0;display:block;margin-bottom:4px">Level</label><select id="genLevel" style="width:100%;padding:8px;background:#0f1419;border:1px solid #2a323d;color:#f5f1e8;border-radius:3px"><option value="beginner">Beginner</option><option value="intermediate" selected>Intermediate</option><option value="advanced">Advanced</option></select></div>
    <button class="btn success" onclick="generateTemplate()" id="genBtn" style="padding:8px 16px">Generate</button>
  </div>
  <div id="genStatus" style="margin-top:8px;font-size:12px;color:#8a92a0"></div>
</div>

<table><tr><th>Title</th><th>Level</th><th>Duration</th><th>Weeks</th><th>Checks</th><th>Subscribers</th><th>Status</th><th>Quality</th><th>Actions</th></tr>{rows_html}</table>

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
</div></body></html>"""
