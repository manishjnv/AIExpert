"""
Public user profiles and leaderboard.

/profile/{user_id} — public profile page (opt-in)
/leaderboard — ranked users by completion %
"""

from html import escape as esc

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.plan import Progress, UserPlan
from app.models.user import User

router = APIRouter()

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,400;9..144,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');
body { font-family: 'IBM Plex Sans', system-ui, sans-serif; background: #0f1419; color: #f5f1e8; margin: 0; padding: 0; -webkit-font-smoothing: antialiased; }
.container { max-width: 800px; margin: 0 auto; padding: 32px 20px; }
h1 { font-family: 'Fraunces', Georgia, serif; color: #e8a849; font-size: 28px; font-weight: 300; margin-bottom: 4px; }
h2 { font-family: 'Fraunces', Georgia, serif; color: #e8a849; font-size: 18px; margin-top: 24px; }
.subtitle { color: #4a5260; font-size: 13px; margin-bottom: 24px; font-family: 'IBM Plex Mono', monospace; letter-spacing: 0.03em; }
.stat-row { display: flex; gap: 16px; margin: 16px 0 24px; flex-wrap: wrap; }
.stat { background: #1d242e; padding: 16px 20px; border-radius: 6px; text-align: center; flex: 1; min-width: 80px; }
.stat .n { font-family: 'Fraunces', Georgia, serif; font-size: 28px; font-weight: 400; color: #e8a849; }
.stat .l { font-family: 'IBM Plex Mono', monospace; font-size: 9px; text-transform: uppercase; letter-spacing: 0.12em; color: #4a5260; margin-top: 2px; }
.badge { display: inline-block; font-size: 11px; padding: 3px 10px; border-radius: 12px; background: rgba(109,181,133,0.2); color: #6db585; margin-right: 6px; }
.progress-bar { background: #2a323d; border-radius: 4px; height: 6px; }
.progress-bar > div { height: 6px; border-radius: 4px; }
table { width: 100%; border-collapse: collapse; margin-top: 12px; }
th { text-align: left; padding: 10px 8px; font-family: 'IBM Plex Mono', monospace; font-size: 10px; text-transform: uppercase; letter-spacing: 0.12em; color: #4a5260; border-bottom: 1px solid #2a323d; }
td { padding: 10px 8px; font-size: 13px; border-bottom: 1px solid #1d242e; }
.rank { font-weight: bold; color: #e8a849; }
a { color: #6fa8d6; text-decoration: none; }
a:hover { color: #e8a849; }
nav { padding: 12px 48px; border-bottom: 1px solid #2a323d; display: flex; align-items: center; gap: 16px; backdrop-filter: blur(12px); background: rgba(15,20,25,0.92); }
nav a { color: #f5f1e8; font-size: 13px; font-family: 'IBM Plex Mono', monospace; font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; }
nav a:hover { color: #e8a849; }
.brand { font-family: 'Fraunces', Georgia, serif; color: #e8a849; font-size: 16px; margin-right: auto; text-transform: none; letter-spacing: 0; }
@media (max-width: 768px) { nav { padding: 10px 16px; } .stat-row { gap: 8px; } .stat { padding: 12px 14px; } .stat .n { font-size: 22px; } }
"""


async def _get_user_progress(user: User, db: AsyncSession) -> dict:
    """Calculate progress stats for a user."""
    plan = (await db.execute(
        select(UserPlan).where(UserPlan.user_id == user.id, UserPlan.status == "active")
    )).scalar_one_or_none()

    if plan is None:
        return {"plan": None, "done": 0, "total": 0, "pct": 0, "template": None}

    done = (await db.execute(
        select(func.count()).select_from(Progress).where(
            Progress.user_plan_id == plan.id, Progress.done == True
        )
    )).scalar() or 0

    from app.curriculum.loader import load_template
    try:
        tpl = load_template(plan.template_key)
        total = tpl.total_checks
    except Exception:
        total = 120

    pct = round((done / total) * 100) if total else 0
    return {"plan": plan, "done": done, "total": total, "pct": pct, "template": plan.template_key}


PLAN_LABELS = {
    "generalist_3mo_intermediate": "3-Month Accelerated",
    "generalist_6mo_intermediate": "6-Month Standard",
    "generalist_12mo_beginner": "12-Month Beginner",
}


@router.get("/profile/{user_id}", response_class=HTMLResponse)
async def public_profile(user_id: int, db: AsyncSession = Depends(get_db)):
    """Public profile page — only shown if user opted in."""
    user = await db.get(User, user_id)
    if user is None or not user.public_profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    first_name = esc((user.name or "Learner").split()[0])
    full_name = esc(user.name or "Learner")
    stats = await _get_user_progress(user, db)
    plan_label = PLAN_LABELS.get(stats["template"] or "", "No plan")

    badges_html = ""
    if user.github_username:
        badges_html += f'<a class="badge" href="https://github.com/{esc(user.github_username)}" target="_blank">GitHub: {esc(user.github_username)}</a>'
    if user.linkedin_url:
        li_href = user.linkedin_url if user.linkedin_url.startswith("http") else "https://" + user.linkedin_url
        badges_html += f'<a class="badge" href="{esc(li_href)}" target="_blank">LinkedIn</a>'

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>{full_name} — AI Learning Roadmap</title><style>{CSS}</style></head><body>
<nav><a href="/" class="brand" style="text-decoration:none">AI Learning Roadmap</a><a href="/">Home</a><a href="/leaderboard">Leaderboard</a></nav>
<div class="container">
<h1>{full_name}</h1>
<div class="subtitle">{plan_label} · Joined {user.created_at.strftime('%B %Y') if user.created_at else '—'}</div>
{badges_html}
<div class="stat-row">
  <div class="stat"><div class="n">{stats['pct']}%</div><div class="l">Complete</div></div>
  <div class="stat"><div class="n">{stats['done']}</div><div class="l">Tasks Done</div></div>
  <div class="stat"><div class="n">{stats['total']}</div><div class="l">Total Tasks</div></div>
</div>
<div class="progress-bar"><div style="width:{stats['pct']}%"></div></div>
</div></body></html>"""


@router.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard(db: AsyncSession = Depends(get_db)):
    """Public leaderboard — ranked by completion %."""
    # Get all users with public profiles and active plans
    users = (await db.execute(
        select(User).where(User.public_profile == True)
    )).scalars().all()

    entries = []
    total_tasks_all = 0
    for user in users:
        stats = await _get_user_progress(user, db)
        if stats["plan"] is None:
            continue
        total_tasks_all += stats["done"]
        joined = user.created_at.strftime("%b %Y") if user.created_at else "—"
        entries.append({
            "id": user.id,
            "name": esc((user.name or "Learner")),
            "plan": PLAN_LABELS.get(stats["template"] or "", "—"),
            "done": stats["done"],
            "total": stats["total"],
            "pct": stats["pct"],
            "github": user.github_username,
            "linkedin": user.linkedin_url,
            "joined": joined,
        })

    # Sort by completion % descending, then by done count
    entries.sort(key=lambda e: (e["pct"], e["done"]), reverse=True)

    medals = ["🥇", "🥈", "🥉"]

    rows = ""
    for i, e in enumerate(entries, 1):
        medal = medals[i-1] if i <= 3 else str(i)
        gh_link = f'<a href="https://github.com/{esc(e["github"])}" target="_blank">{esc(e["github"])}</a>' if e["github"] else ""
        li_link = ""
        if e["linkedin"]:
            li_href = e["linkedin"] if e["linkedin"].startswith("http") else "https://" + e["linkedin"]
            li_link = f' <a href="{esc(li_href)}" target="_blank" style="font-size:11px">LinkedIn</a>'
        bar_color = "#6db585" if e["pct"] >= 75 else "#e8a849" if e["pct"] >= 25 else "#4a5260"
        rows += f"""<tr>
            <td class="rank" style="font-size:18px">{medal}</td>
            <td>
              <a href="/profile/{e['id']}" style="font-weight:600">{e['name']}</a>
              <div style="font-size:10px;color:#4a5260">Joined {e['joined']}</div>
            </td>
            <td><span style="font-size:11px;background:#1d242e;padding:3px 8px;border-radius:10px">{e['plan']}</span></td>
            <td>
              <div style="font-size:12px;margin-bottom:3px">{e['done']}/{e['total']}</div>
              <div class="progress-bar" style="width:100px;height:6px"><div style="width:{e['pct']}%;background:{bar_color}"></div></div>
            </td>
            <td style="color:#e8a849;font-weight:bold;font-size:18px">{e['pct']}%</td>
            <td style="font-size:11px">{gh_link}{li_link}</td>
        </tr>"""

    if not rows:
        rows = '<tr><td colspan="6" style="text-align:center;color:#4a5260;padding:32px">No public profiles yet. Enable yours in Account Settings.</td></tr>'

    # Summary stats
    total_learners = len(entries)
    avg_pct = round(sum(e["pct"] for e in entries) / total_learners) if total_learners else 0

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Leaderboard — AI Learning Roadmap</title><style>{CSS}</style></head><body>
<nav><a href="/" class="brand" style="text-decoration:none">AI Learning Roadmap</a><a href="/">Home</a><a href="/leaderboard">Leaderboard</a></nav>
<div class="container">
<h1>Leaderboard</h1>
<div class="subtitle">Top learners ranked by progress. Enable your public profile in Account Settings to appear here.</div>

<div class="stat-row">
  <div class="stat"><div class="n">{total_learners}</div><div class="l">Learners</div></div>
  <div class="stat"><div class="n">{total_tasks_all}</div><div class="l">Tasks Done</div></div>
  <div class="stat"><div class="n">{avg_pct}%</div><div class="l">Avg Progress</div></div>
</div>

<table>
<tr><th>#</th><th>Learner</th><th>Plan</th><th>Progress</th><th>%</th><th>Links</th></tr>
{rows}
</table>
</div></body></html>"""
