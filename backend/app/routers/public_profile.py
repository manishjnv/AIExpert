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

async def _get_streak(user_id: int, plan_id: int, db) -> int:
    """Calculate consecutive weeks with at least 1 task completed."""
    from datetime import datetime, timedelta, timezone
    completions = (await db.execute(
        select(Progress.completed_at).where(
            Progress.user_plan_id == plan_id,
            Progress.done == True,
            Progress.completed_at.is_not(None),
        ).order_by(Progress.completed_at.desc())
    )).scalars().all()

    if not completions:
        return 0

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    streak = 0
    check_week = now

    for _ in range(52):  # max 1 year
        week_start = check_week - timedelta(days=check_week.weekday(), hours=check_week.hour, minutes=check_week.minute)
        week_end = week_start + timedelta(days=7)
        has_activity = any(week_start <= c < week_end for c in completions if c)
        if has_activity:
            streak += 1
        elif streak > 0:
            break
        check_week = week_start - timedelta(days=1)

    return streak


CSS = """
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,400;9..144,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');
body { font-family: 'IBM Plex Sans', system-ui, sans-serif; background: #0f1419; color: #f5f1e8; margin: 0; padding: 0; -webkit-font-smoothing: antialiased; }
.container { max-width: 1100px; margin: 0 auto; padding: 32px 48px; }
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
.container a { color: #6fa8d6; text-decoration: none; }
.container a:hover { color: #e8a849; }
/* nav styles in /nav.css */
@media (max-width: 768px) { .stat-row { gap: 8px; } .stat { padding: 12px 14px; } .stat .n { font-size: 22px; } }
"""


async def _get_user_progress(user: User, db: AsyncSession) -> dict:
    """Calculate progress stats for a user — lifetime across all plans."""
    # Get active plan for display
    active_plan = (await db.execute(
        select(UserPlan).where(UserPlan.user_id == user.id, UserPlan.status == "active")
    )).scalar_one_or_none()

    # Get ALL plans (active + archived) for lifetime stats
    all_plans = (await db.execute(
        select(UserPlan).where(UserPlan.user_id == user.id)
    )).scalars().all()

    if not all_plans:
        return {"plan": None, "done": 0, "total": 0, "pct": 0, "template": None, "lifetime_done": 0, "plans_count": 0}

    # Count unique completed tasks across all plans
    lifetime_done = 0
    for p in all_plans:
        done = (await db.execute(
            select(func.count()).select_from(Progress).where(
                Progress.user_plan_id == p.id, Progress.done == True
            )
        )).scalar() or 0
        lifetime_done += done

    # Active plan stats for current progress
    active_done = 0
    active_total = 120
    template = None
    if active_plan:
        active_done = (await db.execute(
            select(func.count()).select_from(Progress).where(
                Progress.user_plan_id == active_plan.id, Progress.done == True
            )
        )).scalar() or 0
        template = active_plan.template_key
        from app.curriculum.loader import load_template
        try:
            tpl = load_template(active_plan.template_key)
            active_total = tpl.total_checks
        except Exception:
            active_total = 120

    pct = round((active_done / active_total) * 100) if active_total else 0
    return {
        "plan": active_plan,
        "done": active_done,
        "total": active_total,
        "pct": pct,
        "template": template,
        "lifetime_done": lifetime_done,
        "plans_count": len(all_plans),
    }


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

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>{full_name} — AI Learning Roadmap</title><style>{CSS}</style><link rel="stylesheet" href="/nav.css"></head><body>
<script src="/nav.js"></script>
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
    total_streak_all = 0
    for user in users:
        stats = await _get_user_progress(user, db)
        lifetime = stats.get("lifetime_done", stats["done"])
        total_tasks_all += lifetime
        joined = user.created_at.strftime("%b %Y") if user.created_at else "—"
        streak = await _get_streak(user.id, stats["plan"].id, db) if stats["plan"] else 0
        total_streak_all = max(total_streak_all, streak)
        entries.append({
            "id": user.id,
            "name": esc((user.name or "Learner")),
            "plan": PLAN_LABELS.get(stats["template"] or "", "Not enrolled yet"),
            "done": stats["done"],
            "total": stats["total"],
            "pct": stats["pct"],
            "lifetime_done": lifetime,
            "plans_count": stats.get("plans_count", 1),
            "github": user.github_username,
            "linkedin": user.linkedin_url,
            "joined": joined,
            "streak": streak,
        })

    # Sort by completion % descending, then by lifetime tasks
    entries.sort(key=lambda e: (e["pct"], e["lifetime_done"]), reverse=True)

    medals = ["🥇", "🥈", "🥉"]

    rows = ""
    for i, e in enumerate(entries, 1):
        medal = medals[i-1] if i <= 3 else str(i)
        gh_link = f'<a href="https://github.com/{esc(e["github"])}" target="_blank" title="GitHub: {esc(e["github"])}" style="display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:50%;background:#1d242e;margin-right:4px"><svg width="16" height="16" viewBox="0 0 16 16" fill="#f5f1e8"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z"/></svg></a>' if e["github"] else ""
        li_link = ""
        if e["linkedin"]:
            li_href = e["linkedin"] if e["linkedin"].startswith("http") else "https://" + e["linkedin"]
            li_link = f'<a href="{esc(li_href)}" target="_blank" title="LinkedIn" style="display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:50%;background:#0a66c2"><svg width="14" height="14" viewBox="0 0 16 16" fill="#fff"><path d="M0 1.146C0 .513.526 0 1.175 0h13.65C15.474 0 16 .513 16 1.146v13.708c0 .633-.526 1.146-1.175 1.146H1.175C.526 16 0 15.487 0 14.854V1.146zm4.943 12.248V6.169H2.542v7.225h2.401zm-1.2-8.212c.837 0 1.358-.554 1.358-1.248-.015-.709-.52-1.248-1.342-1.248-.822 0-1.359.54-1.359 1.248 0 .694.521 1.248 1.327 1.248h.016zm4.908 8.212V9.359c0-.216.016-.432.08-.586.173-.431.568-.878 1.232-.878.869 0 1.216.662 1.216 1.634v3.865h2.401V9.25c0-2.22-1.184-3.252-2.764-3.252-1.274 0-1.845.7-2.165 1.193v.025h-.016l.016-.025V6.169h-2.4c.03.678 0 7.225 0 7.225h2.4z"/></svg></a>'
        bar_color = "#6db585" if e["pct"] >= 75 else "#e8a849" if e["pct"] >= 25 else "#4a5260"
        streak_display = f'🔥 {e["streak"]}w' if e["streak"] > 0 else "—"
        rows += f"""<tr>
            <td class="rank" style="font-size:20px;text-align:center">{medal}</td>
            <td>
              <a href="/profile/{e['id']}" style="font-weight:600;font-size:14px">{e['name']}</a>
              <div style="font-size:10px;color:#4a5260">Joined {e['joined']} · {e['lifetime_done']} lifetime tasks</div>
            </td>
            <td><span style="font-size:11px;background:#1d242e;padding:4px 10px;border-radius:12px">{e['plan']}</span></td>
            <td>
              <div style="display:flex;align-items:center;gap:8px">
                <div style="flex:1">
                  <div class="progress-bar" style="width:100%;height:8px"><div style="width:{e['pct']}%;background:{bar_color}"></div></div>
                </div>
                <span style="font-size:11px;color:#4a5260;min-width:50px">{e['done']}/{e['total']}</span>
              </div>
            </td>
            <td style="color:#e8a849;font-weight:bold;font-size:20px;text-align:center">{e['pct']}%</td>
            <td style="text-align:center;font-size:13px">{streak_display}</td>
            <td style="text-align:center">{gh_link}{li_link}</td>
        </tr>"""

    if not rows:
        rows = '<tr><td colspan="7" style="text-align:center;color:#4a5260;padding:40px;font-size:14px">No public profiles yet.<br><span style="font-size:12px">Enable yours in Account Settings to appear here and motivate others!</span></td></tr>'

    # Summary stats
    total_learners = len(entries)
    avg_pct = round(sum(e["pct"] for e in entries) / total_learners) if total_learners else 0
    top_streak = max((e["streak"] for e in entries), default=0)
    completers = sum(1 for e in entries if e["pct"] >= 100)

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Leaderboard — AI Learning Roadmap</title><style>{CSS}</style><link rel="stylesheet" href="/nav.css"></head><body>
<script src="/nav.js"></script>
<div class="container">
<h1>Leaderboard</h1>
<div class="subtitle">Top learners ranked by progress. Enable your public profile in Account Settings to appear here.</div>

<div class="stat-row">
  <div class="stat"><div class="n">{total_learners}</div><div class="l">Learners</div></div>
  <div class="stat"><div class="n">{total_tasks_all}</div><div class="l">Tasks Done</div></div>
  <div class="stat"><div class="n">{avg_pct}%</div><div class="l">Avg Progress</div></div>
  <div class="stat"><div class="n">🔥 {top_streak}w</div><div class="l">Top Streak</div></div>
  <div class="stat"><div class="n">{completers}</div><div class="l">Graduated</div></div>
</div>

<table>
<tr><th style="text-align:center">#</th><th>Learner</th><th>Plan</th><th>Progress</th><th style="text-align:center">%</th><th style="text-align:center">Streak</th><th style="text-align:center">Links</th></tr>
{rows}
</table>
</div></body></html>"""
