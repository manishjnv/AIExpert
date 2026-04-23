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

from app.config import get_settings
from app.db import get_db
from app.utils.time_fmt import fmt_ist, FMT_MONTH_YEAR, FMT_FULL_MONTH_YEAR
from app.models.certificate import Certificate
from app.models.plan import Progress, RepoLink, UserPlan
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
.container { max-width: 100%; margin: 0 auto; padding: 32px clamp(20px, 4vw, 64px); }
@media (min-width: 1600px) { .container { padding-left: 6vw; padding-right: 6vw; } }
h1 { font-family: 'Fraunces', Georgia, serif; color: #e8a849; font-size: 28px; font-weight: 300; margin-bottom: 4px; }
h2 { font-family: 'Fraunces', Georgia, serif; color: #e8a849; font-size: 18px; margin-top: 24px; }
.subtitle { color: #8a92a0; font-size: 13px; margin-bottom: 24px; font-family: 'IBM Plex Mono', monospace; letter-spacing: 0.03em; }
.stat-row { display: flex; gap: 16px; margin: 16px 0 24px; flex-wrap: wrap; }
.stat { background: #1d242e; padding: 16px 20px; border-radius: 6px; text-align: center; flex: 1; min-width: 80px; }
.stat .n { font-family: 'Fraunces', Georgia, serif; font-size: 28px; font-weight: 400; color: #e8a849; }
.stat .l { font-family: 'IBM Plex Mono', monospace; font-size: 9px; text-transform: uppercase; letter-spacing: 0.12em; color: #8a92a0; margin-top: 2px; }
.badge { display: inline-block; font-size: 11px; padding: 3px 10px; border-radius: 12px; background: rgba(109,181,133,0.2); color: #6db585; margin-right: 6px; }
.progress-bar { background: #2a323d; border-radius: 4px; height: 6px; }
.progress-bar > div { height: 6px; border-radius: 4px; }
table { width: 100%; border-collapse: collapse; margin-top: 12px; }
th { text-align: left; padding: 10px 8px; font-family: 'IBM Plex Mono', monospace; font-size: 11px; text-transform: uppercase; letter-spacing: 0.12em; color: #8a92a0; border-bottom: 1px solid #2a323d; }
td { padding: 10px 8px; font-size: 13px; border-bottom: 1px solid #1d242e; }
.rank { font-weight: bold; color: #e8a849; }
.container a { color: #6fa8d6; text-decoration: none; }
.container a:hover { color: #e8a849; }

/* ----- Gamification ----- */
.tier-chip { display: inline-flex; align-items: center; gap: 8px; padding: 8px 14px; border-radius: 999px; border: 1px solid; font-weight: 600; font-size: 13px; font-family: 'IBM Plex Sans', sans-serif; letter-spacing: 0.02em; white-space: nowrap; }
.tier-chip .tier-icon { font-size: 22px; line-height: 1; }
.tier-chip .tier-name { text-transform: uppercase; letter-spacing: 0.08em; font-size: 11px; }

.xp-cell { min-width: 150px; }
.xp-num { font-family: 'Fraunces', Georgia, serif; font-size: 20px; color: #f5f1e8; font-weight: 400; line-height: 1; }
.xp-num .xp-unit { font-size: 11px; color: #8a92a0; font-family: 'IBM Plex Mono', monospace; letter-spacing: 0.1em; margin-left: 4px; }
.xp-next { font-size: 10px; color: #8a92a0; font-family: 'IBM Plex Mono', monospace; margin-top: 6px; letter-spacing: 0.03em; }
.xp-bar { height: 4px; background: #2a323d; border-radius: 2px; margin-top: 4px; overflow: hidden; }
.xp-bar > div { height: 100%; border-radius: 2px; transition: width 0.4s ease; }

.pct-badge { display: inline-block; font-size: 10px; font-family: 'IBM Plex Mono', monospace; color: #e8a849; background: rgba(232,168,73,0.12); border: 1px solid rgba(232,168,73,0.3); padding: 2px 8px; border-radius: 10px; letter-spacing: 0.05em; margin-top: 4px; }

.badges-row { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
.badge-pill { display: inline-flex; align-items: center; gap: 4px; font-size: 11px; padding: 3px 8px; border-radius: 999px; background: rgba(232,168,73,0.1); border: 1px solid rgba(232,168,73,0.25); color: #e8d5a8; white-space: nowrap; }
.badge-pill .be { font-size: 13px; line-height: 1; }

/* ----- Help / Legend ----- */
details.help { background: #161c24; border: 1px solid #2a323d; border-radius: 8px; padding: 16px 20px; margin: 20px 0 24px; }
details.help[open] { background: #1a2029; }
details.help summary { cursor: pointer; font-family: 'IBM Plex Mono', monospace; font-size: 12px; letter-spacing: 0.12em; text-transform: uppercase; color: #e8a849; list-style: none; display: flex; align-items: center; gap: 10px; }
details.help summary::-webkit-details-marker { display: none; }
details.help summary::before { content: '?'; display: inline-flex; align-items: center; justify-content: center; width: 22px; height: 22px; border-radius: 50%; background: rgba(232,168,73,0.15); color: #e8a849; font-family: 'Fraunces', serif; font-weight: 600; font-size: 13px; }
details.help[open] summary::before { content: '×'; }
.help-body { margin-top: 14px; font-size: 13px; color: #c4c7cc; line-height: 1.6; }
.help-body h4 { margin: 18px 0 8px; font-family: 'Fraunces', serif; color: #e8a849; font-size: 15px; font-weight: 500; }
.help-body h4:first-child { margin-top: 0; }
.help-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px; margin-top: 10px; }
.help-tile { padding: 10px 12px; background: #0f1419; border: 1px solid #2a323d; border-radius: 6px; font-size: 12px; }
.help-tile .big { font-size: 18px; margin-right: 6px; vertical-align: middle; }
.help-tile .thr { color: #8a92a0; font-family: 'IBM Plex Mono', monospace; font-size: 10px; letter-spacing: 0.08em; margin-top: 4px; }
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

    # Distinct GitHub repos the learner has produced for their courses
    # (active + archived plans). We dedupe by (owner, name) so re-linking
    # the same repo to multiple weeks counts once — matches the intuitive
    # 'how many repos did you build for learning' number.
    plan_ids = [p.id for p in all_plans]
    lifetime_repos = 0
    if plan_ids:
        distinct_subq = (
            select(RepoLink.repo_owner, RepoLink.repo_name)
            .where(RepoLink.user_plan_id.in_(plan_ids))
            .distinct()
            .subquery()
        )
        lifetime_repos = (await db.execute(
            select(func.count()).select_from(distinct_subq)
        )).scalar() or 0

    # Lifetime non-revoked certificates (need tier-level detail for XP scoring)
    cert_rows = (await db.execute(
        select(Certificate.tier).where(
            Certificate.user_id == user.id,
            Certificate.revoked_at.is_(None),
        )
    )).all()
    cert_tiers = [r[0] for r in cert_rows]
    lifetime_certs = len(cert_tiers)
    honors_count = sum(1 for t in cert_tiers if t == "honors")
    distinction_count = sum(1 for t in cert_tiers if t == "distinction")

    # Last activity timestamp — most recent of: progress tick, repo link.
    # Drives the 'Last Active' column. Real MAX() from the DB, no synthesis.
    last_activity = None
    if plan_ids:
        last_progress = (await db.execute(
            select(func.max(Progress.completed_at)).where(
                Progress.user_plan_id.in_(plan_ids),
                Progress.done == True,  # noqa: E712
            )
        )).scalar()
        last_repo = (await db.execute(
            select(func.max(RepoLink.linked_at)).where(
                RepoLink.user_plan_id.in_(plan_ids)
            )
        )).scalar()
        candidates = [t for t in (last_progress, last_repo) if t is not None]
        if candidates:
            last_activity = max(candidates)

    # Active plan stats for current progress
    active_done = 0
    active_total = 120
    template = None
    course_short = None         # e.g. "AI Generalist"
    duration_months = None
    current_month = None        # month index the learner is currently working in
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
            # Short course name = text before the em-dash separator in the
            # template title (e.g. 'AI Generalist — 3-Month Accelerated'
            # → 'AI Generalist'). Falls back to the full title.
            course_short = (tpl.title or "").split(" — ")[0].strip() or tpl.title
            duration_months = tpl.duration_months
            # Current month = month containing the highest week the learner
            # has any completion in. Empty → month 1 (just started).
            max_done_week = (await db.execute(
                select(func.max(Progress.week_num)).where(
                    Progress.user_plan_id == active_plan.id,
                    Progress.done == True,  # noqa: E712
                )
            )).scalar()
            if max_done_week is not None:
                for m in tpl.months:
                    week_nums = [w.n for w in m.weeks]
                    if week_nums and max_done_week in week_nums:
                        current_month = m.month
                        break
            if current_month is None:
                current_month = 1
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
        "lifetime_repos": lifetime_repos,
        "lifetime_certs": lifetime_certs,
        "cert_tiers": cert_tiers,
        "honors_count": honors_count,
        "distinction_count": distinction_count,
        "last_activity": last_activity,
        "course_short": course_short,
        "duration_months": duration_months,
        "current_month": current_month,
    }


def _fmt_last_active(ts) -> tuple[str, str]:
    """Render a relative 'Last Active' label.

    Returns (text, color). Tuned so any activity within the last day
    reads as fresh; a month+ of silence shades muted so recruiters see
    who's still in the fight.
    """
    if ts is None:
        return ("—", "#5a6473")
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # ts may be tz-aware or naive (SQLite strips tzinfo on read); normalise.
    if hasattr(ts, "tzinfo") and ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    delta = now - ts
    secs = int(delta.total_seconds())
    if secs < 0:
        secs = 0
    if secs < 3600:
        return ("Just now", "#6db585")
    if secs < 86400:
        h = secs // 3600
        return (f"{h}h ago", "#6db585")
    days = secs // 86400
    if days < 7:
        return (f"{days}d ago", "#6db585" if days <= 2 else "#e8a849")
    weeks = days // 7
    if weeks < 5:
        return (f"{weeks}w ago", "#e8a849")
    months = days // 30
    if months < 12:
        return (f"{months}mo ago", "#8a92a0")
    years = days // 365
    return (f"{years}y ago", "#5a6473")


# ---------------- Gamification: XP + Tiers + Badges ----------------
#
# Every activity is weighted against a published rubric so learners can
# predict their gains. Only simple, stable signals — no click-tracking
# or vanity metrics.

XP_PER_TASK = 10
XP_PER_REPO = 50
XP_CERT_COMPLETION = 500
XP_CERT_DISTINCTION = 750
XP_CERT_HONORS = 1000
XP_STREAK_PER_WEEK = 20       # flat bonus per active week

# Tiers listed in ascending order — first entry with xp >= threshold wins.
TIERS = [
    {"min_xp":     0, "name": "Apprentice",  "icon": "🥚", "color": "#94a3b8", "bg": "rgba(148,163,184,0.12)", "border": "rgba(148,163,184,0.5)"},
    {"min_xp":   100, "name": "Learner",     "icon": "📘", "color": "#60a5fa", "bg": "rgba(96,165,250,0.12)",  "border": "rgba(96,165,250,0.5)"},
    {"min_xp":   500, "name": "Practitioner","icon": "🛠️", "color": "#2dd4bf", "bg": "rgba(45,212,191,0.12)",  "border": "rgba(45,212,191,0.5)"},
    {"min_xp":  1500, "name": "Builder",     "icon": "🚀", "color": "#818cf8", "bg": "rgba(129,140,248,0.14)", "border": "rgba(129,140,248,0.55)"},
    {"min_xp":  4000, "name": "Engineer",    "icon": "💎", "color": "#c084fc", "bg": "rgba(192,132,252,0.14)", "border": "rgba(192,132,252,0.55)"},
    {"min_xp": 10000, "name": "Architect",   "icon": "👑", "color": "#f59e0b", "bg": "rgba(245,158,11,0.14)",  "border": "rgba(245,158,11,0.55)"},
    {"min_xp": 25000, "name": "AI Guru",     "icon": "🧙", "color": "#ec4899", "bg": "rgba(236,72,153,0.14)",  "border": "rgba(236,72,153,0.55)"},
]


def _compute_xp(stats: dict, streak: int) -> int:
    tasks = stats.get("lifetime_done", 0)
    repos = stats.get("lifetime_repos", 0)
    certs = stats.get("cert_tiers", [])
    xp = tasks * XP_PER_TASK + repos * XP_PER_REPO + streak * XP_STREAK_PER_WEEK
    for t in certs:
        if t == "honors":
            xp += XP_CERT_HONORS
        elif t == "distinction":
            xp += XP_CERT_DISTINCTION
        else:
            xp += XP_CERT_COMPLETION
    return xp


def _tier_for_xp(xp: int) -> dict:
    chosen = TIERS[0]
    for t in TIERS:
        if xp >= t["min_xp"]:
            chosen = t
        else:
            break
    return chosen


def _next_tier(xp: int) -> dict | None:
    for t in TIERS:
        if t["min_xp"] > xp:
            return t
    return None


# Achievement badges — shown as pills next to the name. Keep the set
# small so there's always headroom to earn another.
def _compute_badges(stats: dict, streak: int) -> list[dict]:
    tasks = stats.get("lifetime_done", 0)
    repos = stats.get("lifetime_repos", 0)
    certs = stats.get("lifetime_certs", 0)
    honors = stats.get("honors_count", 0)

    out: list[dict] = []
    if tasks >= 1:
        out.append({"icon": "🎯", "label": "First Task",     "hint": "Completed your first checklist item"})
    if tasks >= 50:
        out.append({"icon": "📚", "label": "50 Tasks",       "hint": "Completed 50 lifetime checklist items"})
    if tasks >= 250:
        out.append({"icon": "📖", "label": "250 Tasks",      "hint": "Completed 250 lifetime checklist items"})
    if certs >= 1:
        out.append({"icon": "🎓", "label": "First Cert",     "hint": "Earned your first course completion certificate"})
    if certs >= 3:
        out.append({"icon": "💎", "label": "Triple Crown",   "hint": "Earned 3 or more certificates"})
    if honors >= 1:
        out.append({"icon": "🏆", "label": "Honors",         "hint": "Earned at least one Honors-tier certificate"})
    if repos >= 5:
        out.append({"icon": "🚀", "label": "5 Repos",        "hint": "Linked 5 or more GitHub repos"})
    if repos >= 15:
        out.append({"icon": "⭐", "label": "15 Repos",       "hint": "Linked 15 or more GitHub repos"})
    if streak >= 4:
        out.append({"icon": "🔥", "label": f"{streak}w Streak", "hint": f"Active {streak} consecutive weeks"})
    if streak >= 10:
        out.append({"icon": "🔥🔥","label": "Hot Streak",     "hint": "10+ week streak — relentless"})
    return out


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

    base = get_settings().public_base_url.rstrip("/")
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>{full_name} — AI Learning Roadmap</title><link rel="canonical" href="{base}/profile/{user.id}"><style>{CSS}</style><link rel="stylesheet" href="/nav.css"></head><body>
<script src="/nav.js"></script>
<div class="container">
<h1>{full_name}</h1>
<div class="subtitle">{plan_label} · Joined {fmt_ist(user.created_at, FMT_FULL_MONTH_YEAR)}</div>
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
    total_repos_all = 0
    total_certs_all = 0
    total_xp_all = 0
    for user in users:
        stats = await _get_user_progress(user, db)
        lifetime = stats.get("lifetime_done", stats["done"])
        total_tasks_all += lifetime
        total_repos_all += stats.get("lifetime_repos", 0)
        total_certs_all += stats.get("lifetime_certs", 0)
        joined = fmt_ist(user.created_at, FMT_MONTH_YEAR)
        streak = await _get_streak(user.id, stats["plan"].id, db) if stats["plan"] else 0
        total_streak_all = max(total_streak_all, streak)

        xp = _compute_xp(stats, streak)
        total_xp_all += xp
        tier = _tier_for_xp(xp)
        nxt = _next_tier(xp)
        if nxt:
            prog_span = max(1, nxt["min_xp"] - tier["min_xp"])
            progress_pct = round(((xp - tier["min_xp"]) / prog_span) * 100)
            xp_to_next = nxt["min_xp"] - xp
        else:
            progress_pct = 100
            xp_to_next = 0
        badges = _compute_badges(stats, streak)

        # Build the subtitle phrase about what they're currently studying.
        # Active plan → 'Studying: <course> · Month X of Y'.
        # No active plan but has history → 'Between courses'.
        # Brand-new with nothing → 'New learner'.
        if stats.get("course_short") and stats.get("current_month") and stats.get("duration_months"):
            plan_phrase = (
                f'Studying: {esc(stats["course_short"])} · '
                f'Month {stats["current_month"]} of {stats["duration_months"]}'
            )
        elif stats.get("plans_count", 0) > 0:
            plan_phrase = "Between courses"
        else:
            plan_phrase = "New learner"

        entries.append({
            "id": user.id,
            "name": esc((user.name or "Learner")),
            "plan": plan_phrase,
            "done": stats["done"],
            "total": stats["total"],
            "pct": stats["pct"],
            "lifetime_done": lifetime,
            "plans_count": stats.get("plans_count", 1),
            "lifetime_repos": stats.get("lifetime_repos", 0),
            "lifetime_certs": stats.get("lifetime_certs", 0),
            "honors_count": stats.get("honors_count", 0),
            "github": user.github_username,
            "linkedin": user.linkedin_url,
            "joined": joined,
            "streak": streak,
            "last_activity": stats.get("last_activity"),
            "xp": xp,
            "tier": tier,
            "next_tier": nxt,
            "tier_progress_pct": progress_pct,
            "xp_to_next": xp_to_next,
            "badges": badges,
        })

    # Sort by XP desc (real number derived from DB-backed counts), tie-break by pct + lifetime tasks
    entries.sort(key=lambda e: (e["xp"], e["pct"], e["lifetime_done"]), reverse=True)

    # Percentile rank (top X%) computed post-sort from the real ranking
    n = len(entries)
    for i, e in enumerate(entries):
        e["percentile"] = round((i / n) * 100) if n else 0  # 0 = top, 100 = bottom

    medals = ["🥇", "🥈", "🥉"]

    rows = ""
    for i, e in enumerate(entries, 1):
        medal = medals[i-1] if i <= 3 else str(i)
        gh_link = f'<a href="https://github.com/{esc(e["github"])}" target="_blank" title="GitHub: {esc(e["github"])}" style="display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:50%;background:#1d242e;margin-right:4px"><svg width="16" height="16" viewBox="0 0 16 16" fill="#f5f1e8"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z"/></svg></a>' if e["github"] else ""
        li_link = ""
        if e["linkedin"]:
            li_href = e["linkedin"] if e["linkedin"].startswith("http") else "https://" + e["linkedin"]
            li_link = f'<a href="{esc(li_href)}" target="_blank" title="LinkedIn" style="display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:50%;background:#0a66c2"><svg width="14" height="14" viewBox="0 0 16 16" fill="#fff"><path d="M0 1.146C0 .513.526 0 1.175 0h13.65C15.474 0 16 .513 16 1.146v13.708c0 .633-.526 1.146-1.175 1.146H1.175C.526 16 0 15.487 0 14.854V1.146zm4.943 12.248V6.169H2.542v7.225h2.401zm-1.2-8.212c.837 0 1.358-.554 1.358-1.248-.015-.709-.52-1.248-1.342-1.248-.822 0-1.359.54-1.359 1.248 0 .694.521 1.248 1.327 1.248h.016zm4.908 8.212V9.359c0-.216.016-.432.08-.586.173-.431.568-.878 1.232-.878.869 0 1.216.662 1.216 1.634v3.865h2.401V9.25c0-2.22-1.184-3.252-2.764-3.252-1.274 0-1.845.7-2.165 1.193v.025h-.016l.016-.025V6.169h-2.4c.03.678 0 7.225 0 7.225h2.4z"/></svg></a>'
        streak_display = f'🔥 {e["streak"]}w' if e["streak"] > 0 else "—"
        la_text, la_color = _fmt_last_active(e["last_activity"])
        last_active_display = f'<span style="color:{la_color};font-weight:500">{la_text}</span>'
        repos_display = (
            f'<span style="font-weight:600">{e["lifetime_repos"]}</span>'
            if e["lifetime_repos"] > 0 else '<span style="color:#5a6473">—</span>'
        )
        certs_display = (
            f'<span style="color:#e8a849;font-weight:600">🎓 {e["lifetime_certs"]}</span>'
            if e["lifetime_certs"] > 0 else '<span style="color:#5a6473">—</span>'
        )

        # Tier chip — big icon, colored border, real XP-derived tier
        tier = e["tier"]
        tier_chip = (
            f'<span class="tier-chip" style="background:{tier["bg"]};border-color:{tier["border"]};color:{tier["color"]}">'
            f'<span class="tier-icon">{tier["icon"]}</span>'
            f'<span class="tier-name">{tier["name"]}</span>'
            f'</span>'
        )

        # XP cell with progress bar to next tier
        if e["next_tier"]:
            xp_next = f'<div class="xp-next">{e["xp_to_next"]:,} XP → {e["next_tier"]["icon"]} {e["next_tier"]["name"]}</div>'
        else:
            xp_next = '<div class="xp-next" style="color:#e8a849">🏅 Max tier reached</div>'
        xp_cell = (
            f'<div class="xp-cell">'
            f'<div class="xp-num">{e["xp"]:,}<span class="xp-unit">XP</span></div>'
            f'<div class="xp-bar"><div style="width:{e["tier_progress_pct"]}%;background:{tier["color"]}"></div></div>'
            f'{xp_next}'
            f'</div>'
        )

        # Badges row — real, derived from DB counts
        badges_html = ""
        if e["badges"]:
            badges_html = '<div class="badges-row">' + "".join(
                f'<span class="badge-pill" title="{esc(b["hint"])}"><span class="be">{b["icon"]}</span>{esc(b["label"])}</span>'
                for b in e["badges"]
            ) + '</div>'

        # Top % badge — only for genuine top tier (real percentile)
        pct_badge = ""
        if n >= 3 and e["percentile"] <= 10:
            pct_badge = f'<span class="pct-badge">TOP {max(1, e["percentile"])}%</span>'
        elif n >= 3 and e["percentile"] <= 25:
            pct_badge = f'<span class="pct-badge" style="color:#94a3b8;background:rgba(148,163,184,0.1);border-color:rgba(148,163,184,0.3)">TOP {e["percentile"]}%</span>'

        rows += f"""<tr>
            <td class="rank" style="font-size:22px;text-align:center;vertical-align:top;padding-top:16px">{medal}</td>
            <td style="min-width:280px">
              <a href="/profile/{e['id']}" style="font-weight:600;font-size:15px">{e['name']}</a>
              {pct_badge}
              <div style="font-size:12px;color:#8a92a0;margin-top:2px">Joined {e['joined']} · {e['plan']} · {e['lifetime_done']} tasks</div>
              {badges_html}
            </td>
            <td style="vertical-align:top;padding-top:14px">{tier_chip}</td>
            <td style="vertical-align:top;padding-top:12px">{xp_cell}</td>
            <td style="text-align:center;font-size:13px;vertical-align:top;padding-top:16px">{streak_display}</td>
            <td style="text-align:center;font-size:13px;vertical-align:top;padding-top:16px" title="Distinct GitHub repos built as part of learning">{repos_display}</td>
            <td style="text-align:center;font-size:13px;vertical-align:top;padding-top:16px" title="Course completion certificates earned">{certs_display}</td>
            <td style="text-align:center;font-size:12px;vertical-align:top;padding-top:16px" title="Most recent progress tick or repo link">{last_active_display}</td>
            <td style="text-align:center;vertical-align:top;padding-top:14px">{gh_link}{li_link}</td>
        </tr>"""

    if not rows:
        rows = '<tr><td colspan="9" style="text-align:center;color:#8a92a0;padding:40px;font-size:14px">No public profiles yet.<br><span style="font-size:12px">Enable yours in Account Settings to appear here and motivate others!</span></td></tr>'

    # Summary stats
    total_learners = len(entries)
    avg_pct = round(sum(e["pct"] for e in entries) / total_learners) if total_learners else 0
    top_streak = max((e["streak"] for e in entries), default=0)
    completers = sum(1 for e in entries if e["pct"] >= 100)

    base = get_settings().public_base_url.rstrip("/")
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Leaderboard — AI Learning Roadmap</title><link rel="canonical" href="{base}/leaderboard"><style>{CSS}</style><link rel="stylesheet" href="/nav.css"></head><body>
<script src="/nav.js"></script>
<div class="container">
<h1>Leaderboard</h1>
<div class="subtitle">Top learners ranked by progress. Enable your public profile in Account Settings to appear here.</div>

<div class="stat-row">
  <div class="stat"><div class="n">{total_learners}</div><div class="l">Learners</div></div>
  <div class="stat"><div class="n">{total_xp_all:,}</div><div class="l">Total XP</div></div>
  <div class="stat"><div class="n">{total_tasks_all}</div><div class="l">Tasks Done</div></div>
  <div class="stat"><div class="n">{total_repos_all}</div><div class="l">Projects Built</div></div>
  <div class="stat"><div class="n">🎓 {total_certs_all}</div><div class="l">Certificates</div></div>
  <div class="stat"><div class="n">🔥 {top_streak}w</div><div class="l">Top Streak</div></div>
  <div class="stat"><div class="n">{completers}</div><div class="l">Graduated</div></div>
</div>

<details class="help">
  <summary>How ranking &amp; XP work</summary>
  <div class="help-body">
    <p style="margin-top:0">Your rank is sorted by <strong>XP</strong> — a single number computed from real activity in the database. Every signal below is a live count, nothing synthetic.</p>

    <h4>How XP is earned</h4>
    <div class="help-grid">
      <div class="help-tile"><span class="big">✅</span> <strong>+{XP_PER_TASK} XP</strong> per checklist task you tick off<div class="thr">LIFETIME — NEVER RESETS</div></div>
      <div class="help-tile"><span class="big">🔗</span> <strong>+{XP_PER_REPO} XP</strong> per distinct GitHub repo built for a course<div class="thr">SAME REPO ACROSS WEEKS COUNTS ONCE</div></div>
      <div class="help-tile"><span class="big">🎓</span> <strong>+{XP_CERT_COMPLETION} XP</strong> — Completion certificate<div class="thr">≥90% PLAN + CAPSTONE 100%</div></div>
      <div class="help-tile"><span class="big">🥈</span> <strong>+{XP_CERT_DISTINCTION} XP</strong> — With Distinction<div class="thr">100% + ≥80% REPOS</div></div>
      <div class="help-tile"><span class="big">🏆</span> <strong>+{XP_CERT_HONORS} XP</strong> — With Honors<div class="thr">DISTINCTION + AI EVAL ≥ 8/10</div></div>
      <div class="help-tile"><span class="big">🔥</span> <strong>+{XP_STREAK_PER_WEEK} XP</strong> per active weekly streak<div class="thr">AT LEAST 1 TASK DONE THAT WEEK</div></div>
    </div>

    <h4>Tier ladder</h4>
    <div class="help-grid">
      {"".join(f'<div class="help-tile" style="border-color:{t["border"]}"><span class="big">{t["icon"]}</span><strong style="color:{t["color"]}">{t["name"]}</strong><div class="thr">{t["min_xp"]:,}+ XP</div></div>' for t in TIERS)}
    </div>

    <h4>Achievement badges</h4>
    <p>Earned automatically when real thresholds are crossed:</p>
    <div class="help-grid">
      <div class="help-tile"><span class="big">🎯</span> First Task · 📚 50 · 📖 250 tasks</div>
      <div class="help-tile"><span class="big">🎓</span> First Cert · 💎 Triple Crown · 🏆 Honors</div>
      <div class="help-tile"><span class="big">🚀</span> 5 Repos · ⭐ 15 Repos</div>
      <div class="help-tile"><span class="big">🔥</span> 4-week Streak · 🔥🔥 10-week Hot Streak</div>
    </div>

    <h4>Last Active</h4>
    <p>Shows the most recent moment you moved the needle — either ticking a task or linking a GitHub repo. Fresh (within 48h) renders green, amber within a week, muted thereafter. No XP attached; it's a pure recency signal.</p>

    <h4>Privacy</h4>
    <p style="margin-bottom:0">You only appear here if you opt in under <a href="/account">Account Settings → Show my profile on the public leaderboard</a>. Name and counts are the only things shown — email is never exposed.</p>
  </div>
</details>

<table>
<tr>
  <th style="text-align:center">#</th>
  <th>Learner</th>
  <th>Tier</th>
  <th>XP</th>
  <th style="text-align:center">Streak</th>
  <th style="text-align:center">Repos</th>
  <th style="text-align:center">Certs</th>
  <th style="text-align:center">Last Active</th>
  <th style="text-align:center">Links</th>
</tr>
{rows}
</table>
</div></body></html>"""
