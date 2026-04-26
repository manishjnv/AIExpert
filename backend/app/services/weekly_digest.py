"""Combined weekly digest — one email per opted-in user, Monday morning IST.

Sections render conditionally based on the user's per-channel toggles
AND whether each section has content. A section with the channel on but
no content (e.g. notify_jobs=True but no jobs match >=40%) is omitted
silently — we don't ship empty placeholders. If after composition no
sections rendered, the user is skipped (no empty email).

Section order is fixed: roadmap (course progress) > new courses > jobs >
blog. This mirrors per-user value: progress is most personal, new courses
nudge enrollment, jobs are action-oriented, blog is passive read.

Visual design: brand-aligned card layout (cream paper bg, white cards,
gold accent header, sky/sage/gold/rust per-section accent colors). Logo
is a table-based monogram for universal email-client rendering. Every
link carries UTM params for click attribution. The cron runs once per
Monday — no last_sent_at tracking; the schedule is the idempotence key.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from html import escape as _esc
from typing import Any

import aiosmtplib
from sqlalchemy import func, select

import app.db as _db
from app.config import get_settings
from app.models import Job
from app.models.plan import Progress, UserPlan
from app.models.user import User
from app.services.jobs_digest import (
    _recent_published_jobs,
    _top_matches,
)

logger = logging.getLogger("roadmap.digest.combined")

MAX_EMAILS_PER_RUN = 400
BATCH_SIZE = 50
MAX_JOBS_IN_EMAIL = 3  # cap inbox fatigue; surplus links to /jobs


# ---------------------------------------------------------------------------
# Brand palette (mirrors frontend/nav.css + frontend/account.html design tokens)
# ---------------------------------------------------------------------------

_BRAND = {
    "accent": "#e8a849",       # primary gold
    "accent_soft": "#c98e2f",  # deeper gold (hover/secondary)
    "navy": "#0f1419",         # deep navy / dark surface
    "paper": "#f5f1e8",        # signature warm cream
    "paper_dim": "#ede2c8",    # darker cream for dividers
    "ink": "#1a1a1a",          # body text
    "ink_soft": "#5a6473",     # muted slate
    "ink_mute": "#94a3b8",     # very muted (footer fine print)
    "line": "#e8e2d3",         # warm-tinted card border
    "success": "#6db585",      # sage (course progress)
    "danger": "#d97757",       # rust (jobs / opportunity urgency)
    "info": "#6fa8d6",         # sky (blog / informational)
    "card_bg": "#ffffff",
    "body_bg": "#efeae0",      # warm tinted body bg, distinct from white card
    "footer_bg": "#fbf8f0",    # lighter than body for separation
}


def _esc_str(s: object) -> str:
    return _esc("" if s is None else str(s))


# ---------------------------------------------------------------------------
# Shared SMTP sender
# ---------------------------------------------------------------------------

async def _send(to_email: str, subject: str, text: str, html: str) -> None:
    """Send a multipart email via aiosmtplib (shared across all digest helpers)."""
    settings = get_settings()
    if not settings.smtp_host:
        logger.info("DEV MODE — would send digest to %s (subject=%s)", to_email, subject)
        return
    msg = EmailMessage()
    msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    await aiosmtplib.send(
        msg,
        hostname=settings.smtp_host, port=settings.smtp_port,
        username=settings.smtp_user, password=settings.smtp_password,
        start_tls=not settings.smtp_use_tls, use_tls=settings.smtp_use_tls,
    )


# ---------------------------------------------------------------------------
# Unsubscribe token
# ---------------------------------------------------------------------------

def _unsub_token(user: User, channel: str | None = None) -> str:
    """Signed JWT for one-click unsubscribe.

    Args:
        user: The recipient user.
        channel: One of {"jobs", "roadmap", "blog", "new_courses"} to flip
            a single channel off, or None to flip all (backward-compat with
            the existing /api/profile/digest/unsubscribe endpoint).

    The token carries an optional ``c`` claim holding the channel name.
    Expiry: 90 days.
    """
    from jose import jwt
    settings = get_settings()
    payload: dict[str, Any] = {
        "sub": str(user.id),
        "k": "unsub",
        "exp": int((datetime.utcnow() + timedelta(days=90)).timestamp()),
    }
    if channel is not None:
        payload["c"] = channel
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------

async def _eligible_users(db) -> list[User]:
    """Users with at least one notification channel enabled."""
    stmt = select(User).where(
        (User.notify_jobs == True)  # noqa: E712
        | (User.notify_roadmap == True)  # noqa: E712
        | (User.notify_blog == True)  # noqa: E712
        | (User.notify_new_courses == True)  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# UTM helper — adds attribution to every outbound email link
# ---------------------------------------------------------------------------

def _utm(url: str, section: str) -> str:
    """Append utm_source/medium/campaign for click attribution. Idempotent."""
    if not url or "utm_source=email" in url:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}utm_source=email&utm_medium=weekly_digest&utm_campaign={section}"


# ---------------------------------------------------------------------------
# Section header builder (icon box + UPPER LABEL + headline) — mirrors the
# reference template's visual pattern but with brand colors per section.
# ---------------------------------------------------------------------------

def _section_header(icon: str, label: str, headline: str, accent: str,
                    icon_bg: str, sublabel: str = "") -> str:
    sublabel_html = (
        f'<p style="margin:8px 0 0;color:{_BRAND["ink_soft"]};font-size:14px">{_esc_str(sublabel)}</p>'
        if sublabel else ""
    )
    return f"""\
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
  <tr>
    <td width="44" valign="middle">
      <div style="width:36px;height:36px;background:{icon_bg};border-radius:9px;text-align:center;line-height:36px;font-size:18px">{icon}</div>
    </td>
    <td valign="middle" style="padding-left:12px">
      <div style="font-size:11px;letter-spacing:1.5px;color:{accent};font-weight:700">{_esc_str(label)}</div>
      <div style="font-size:20px;font-weight:700;color:{_BRAND["navy"]};margin-top:2px;font-family:Georgia,'Times New Roman',serif">{_esc_str(headline)}</div>
    </td>
  </tr>
</table>
{sublabel_html}"""


# ---------------------------------------------------------------------------
# Section: Course progress
# ---------------------------------------------------------------------------

async def _roadmap_section(user: User, db) -> dict | None:
    """Build the roadmap progress section for a user.

    Returns None when:
    - The user has no active plan.
    - The user has had no Progress activity in the last 30 days.

    100%-complete plans render a celebration card (not skipped). Active
    in-progress plans render a progress bar + resume CTA.

    Returns a dict with keys: text, html, subject_hint, score.
    """
    plan = (await db.execute(
        select(UserPlan).where(
            UserPlan.user_id == user.id,
            UserPlan.status == "active",
        )
    )).scalar_one_or_none()

    if plan is None:
        return None

    # Last-activity guard (30-day inactivity → skip; don't pester the dormant).
    last_activity = (await db.execute(
        select(func.max(Progress.updated_at)).where(
            Progress.user_plan_id == plan.id,
        )
    )).scalar()

    if last_activity:
        days_inactive = (datetime.now(timezone.utc).replace(tzinfo=None) - last_activity).days
        if days_inactive > 30:
            return None

    # Progress counts.
    total_done = (await db.execute(
        select(func.count()).select_from(Progress).where(
            Progress.user_plan_id == plan.id,
            Progress.done == True,  # noqa: E712
        )
    )).scalar() or 0

    week_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
    done_this_week = (await db.execute(
        select(func.count()).select_from(Progress).where(
            Progress.user_plan_id == plan.id,
            Progress.done == True,  # noqa: E712
            Progress.completed_at > week_ago,
        )
    )).scalar() or 0

    # Total checks from the curriculum template.
    from app.curriculum.loader import load_template
    plan_title = "Your AI roadmap"
    try:
        tpl = load_template(plan.template_key)
        total_checks = tpl.total_checks
        plan_title = tpl.title
    except Exception:
        total_checks = 120  # fallback

    pct = round((total_done / total_checks) * 100) if total_checks else 0

    settings = get_settings()
    base_url = (settings.public_base_url or "").rstrip("/")
    dash_url = _utm(f"{base_url}/", "roadmap_progress")
    cert_url = _utm(f"{base_url}/account", "roadmap_complete")

    header = _section_header(
        icon="🎯",
        label="YOUR PROGRESS",
        headline="Course completed!" if pct >= 100 else "Keep your streak alive",
        accent=_BRAND["success"],
        icon_bg="#e3eee5",
    )

    if pct >= 100:
        # Celebration card — replaces the previous "skip when 100% complete"
        # behavior so users at the finish line still see their accomplishment.
        subject_hint = f"🎓 You completed {plan_title}"
        score = 80  # high — celebration is high-value content
        card_html = f"""\
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_BRAND["paper"]};border:1px solid {_BRAND["accent_soft"]};border-radius:10px;margin-bottom:10px">
  <tr>
    <td style="padding:24px;text-align:center">
      <div style="font-size:44px;line-height:1;margin-bottom:8px">🎓</div>
      <div style="font-size:18px;font-weight:600;color:{_BRAND["navy"]};font-family:Georgia,'Times New Roman',serif">{_esc_str(plan_title)}</div>
      <div style="font-size:13px;color:{_BRAND["ink_soft"]};margin-top:4px">100% complete &nbsp;·&nbsp; {total_done} / {total_checks} tasks</div>
      <a href="{_esc_str(cert_url)}" style="display:inline-block;margin-top:14px;padding:11px 22px;background:{_BRAND["accent"]};color:{_BRAND["navy"]};font-size:13px;font-weight:700;border-radius:7px;text-decoration:none">View certificate →</a>
    </td>
  </tr>
</table>"""
        card_text = (
            f"🎓 {plan_title}\n"
            f"100% complete ({total_done}/{total_checks} tasks)\n"
            f"View certificate: {cert_url}\n"
        )
    else:
        # In-progress card with table-based progress bar.
        if done_this_week > 0:
            subject_hint = f"Great week — {done_this_week} tasks done"
            intro_html = f"<strong>{done_this_week} tasks</strong> completed this week. Keep the momentum."
            intro_text = f"You completed {done_this_week} tasks this week. Keep the momentum."
            score = min(done_this_week * 10, 70)
        else:
            subject_hint = "Your AI roadmap misses you"
            intro_html = "Even 15 minutes today compounds — pick up where you left off."
            intro_text = intro_html
            score = 30

        # Width % must be a string for the progress-bar table cell.
        bar_pct = max(2, min(98, pct))  # avoid 0/100 collapse in renderers

        # intro_html contains a controlled <strong> literal — don't escape.
        # (See RCA-033 — escaping a controlled HTML literal renders &lt;strong&gt;.)
        card_html = f"""\
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_BRAND["paper"]};border:1px solid {_BRAND["line"]};border-radius:10px;margin-bottom:10px">
  <tr>
    <td style="padding:18px">
      <div style="font-size:15px;font-weight:600;color:{_BRAND["navy"]};font-family:Georgia,'Times New Roman',serif">{_esc_str(plan_title)}</div>
      <div style="font-size:13px;color:{_BRAND["ink_soft"]};margin:4px 0 14px">{intro_html}</div>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_BRAND["paper_dim"]};border-radius:999px">
        <tr>
          <td width="{bar_pct}%" style="background:{_BRAND["accent"]};background-image:linear-gradient(90deg,{_BRAND["accent_soft"]},{_BRAND["accent"]});height:8px;border-radius:999px;line-height:8px;font-size:1px">&nbsp;</td>
          <td style="background:transparent">&nbsp;</td>
        </tr>
      </table>
      <table role="presentation" width="100%" style="margin-top:12px">
        <tr>
          <td style="font-size:13px;color:{_BRAND["accent_soft"]};font-weight:700">{pct}% complete &nbsp;·&nbsp; {total_done} / {total_checks} tasks</td>
          <td align="right">
            <a href="{_esc_str(dash_url)}" style="font-size:13px;color:{_BRAND["accent_soft"]};text-decoration:none;font-weight:600">Resume →</a>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>"""
        card_text = (
            f"{plan_title}\n"
            f"{intro_text}\n"
            f"{pct}% complete ({total_done}/{total_checks} tasks)\n"
            f"Resume: {dash_url}\n"
        )

    html = f"""\
<tr><td style="padding:24px 28px 4px">{header}</td></tr>
<tr><td style="padding:14px 28px 8px">{card_html}</td></tr>"""

    text = f"[YOUR PROGRESS]\n{card_text}\n"

    return {
        "html": html,
        "text": text,
        "subject_hint": subject_hint[:80],
        "score": score,
    }


# ---------------------------------------------------------------------------
# Section: Top job matches
# ---------------------------------------------------------------------------

async def _jobs_section(user: User, jobs_pool: list[Job], db) -> dict | None:
    """Build the top job matches section. Returns None if no matches >=40%.

    Caps display at MAX_JOBS_IN_EMAIL to reduce inbox fatigue; surplus is
    surfaced via a "See all N matching jobs →" link to /jobs.
    """
    matches = await _top_matches(user, jobs_pool, db)
    if not matches:
        return None

    settings = get_settings()
    base_url = (settings.public_base_url or "").rstrip("/")
    total = len(matches)
    visible = matches[:MAX_JOBS_IN_EMAIL]

    items_html: list[str] = []
    items_text: list[str] = []

    for job, m in visible:
        d = job.data or {}
        loc = d.get("location") or {}
        company_name = (d.get("company") or {}).get("name") or job.company_slug
        loc_str = " · ".join(filter(None, [
            loc.get("city"), loc.get("country"), loc.get("remote_policy"),
        ])) or "—"
        url = _utm(f"{base_url}/jobs/{job.slug}", "jobs")
        score_pct = m["score"]
        # Match badge uses brand-success for high (>=70), brand-danger for medium.
        badge_bg = "#e3eee5" if score_pct >= 70 else "#f5e0d6"
        badge_fg = _BRAND["success"] if score_pct >= 70 else _BRAND["danger"]

        # Skill / employment chips
        emp = d.get("employment") or {}
        chips: list[str] = []
        salary = emp.get("salary")
        if salary:
            chips.append(_esc_str(salary)[:30])
        emp_type = emp.get("type")
        if emp_type:
            chips.append(_esc_str(emp_type)[:20])
        exp_y = emp.get("experience_years") or {}
        if exp_y.get("min") is not None:
            chips.append(f"{exp_y['min']}+ years")
        chips_html = "".join(
            f'<span style="display:inline-block;padding:4px 8px;background:{_BRAND["paper"]};color:{_BRAND["ink_soft"]};font-size:11px;font-weight:500;border-radius:4px;margin-right:4px;margin-bottom:4px">{c}</span>'
            for c in chips
        )

        items_html.append(f"""\
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {_BRAND["line"]};border-radius:10px;margin-bottom:10px">
  <tr>
    <td style="padding:16px">
      <table role="presentation" width="100%">
        <tr>
          <td valign="top">
            <div style="font-size:15px;font-weight:600;color:{_BRAND["navy"]};font-family:Georgia,'Times New Roman',serif">{_esc_str(job.title)}</div>
            <div style="font-size:13px;color:{_BRAND["ink_soft"]};margin-top:4px">{_esc_str(company_name)} &nbsp;·&nbsp; {_esc_str(loc_str)}</div>
          </td>
          <td align="right" valign="top" style="white-space:nowrap;padding-left:8px">
            <span style="display:inline-block;padding:4px 10px;background:{badge_bg};color:{badge_fg};font-size:11px;font-weight:700;border-radius:999px">{score_pct}% match</span>
          </td>
        </tr>
      </table>
      {f'<div style="margin-top:12px">{chips_html}</div>' if chips_html else ""}
      <a href="{_esc_str(url)}" style="display:inline-block;margin-top:14px;padding:9px 18px;background:{_BRAND["navy"]};color:#ffffff;font-size:13px;font-weight:600;border-radius:7px;text-decoration:none">View role</a>
    </td>
  </tr>
</table>""")
        items_text.append(
            f"- {job.title} ({score_pct}% match)\n"
            f"  {company_name} · {loc_str}\n"
            f"  {url}\n"
        )

    all_jobs_url = _utm(f"{base_url}/jobs", "jobs_all")
    overflow_link = ""
    if total > MAX_JOBS_IN_EMAIL:
        overflow_link = f"""\
<a href="{_esc_str(all_jobs_url)}" style="display:block;text-align:center;padding:14px;font-size:13px;color:{_BRAND["accent_soft"]};font-weight:600;text-decoration:none">See all {total} matching jobs →</a>"""

    header = _section_header(
        icon="💼",
        label="AI JOBS",
        headline="Roles matching your skills",
        accent=_BRAND["danger"],
        icon_bg="#f5e0d6",
        sublabel=f"{total} new opportunit{'y' if total == 1 else 'ies'} this week",
    )

    html = f"""\
<tr><td style="padding:20px 28px 4px"><div style="height:1px;background:{_BRAND["line"]};margin-bottom:24px"></div>{header}</td></tr>
<tr><td style="padding:16px 28px 8px">{"".join(items_html)}{overflow_link}</td></tr>"""

    text = (
        "[AI JOBS]\n"
        f"Top {len(visible)} of {total} matches this week:\n\n"
        + "\n".join(items_text)
        + f"\nAll matches: {all_jobs_url}\n"
    )

    top_score = visible[0][1]["score"]
    top_title = (visible[0][0].title or "")[:60]

    return {
        "html": html,
        "text": text,
        "subject_hint": f"{top_score}% match: {top_title}"[:80],
        "score": top_score,
    }


# ---------------------------------------------------------------------------
# Section: New courses
# ---------------------------------------------------------------------------

def _courses_section(recent_courses: list[dict]) -> dict | None:
    """Build the new-courses section from templates published in the last 7 days."""
    if not recent_courses:
        return None

    settings = get_settings()
    base_url = (settings.public_base_url or "").rstrip("/")

    # Pick a level-appropriate icon
    level_icons = {"beginner": "🌱", "intermediate": "⚡", "advanced": "🤖"}

    items_html: list[str] = []
    items_text: list[str] = []

    for course in recent_courses:
        title = course.get("title", "Untitled course")
        summary = (course.get("summary") or "")[:200]
        level = (course.get("level") or "").lower()
        duration = course.get("duration_months")
        meta_bits = " · ".join(filter(None, [
            level.title() if level else "",
            f"{duration} months" if duration else "",
        ]))
        icon = level_icons.get(level, "📚")
        url = _utm(f"{base_url}/account", "new_courses")

        items_html.append(f"""\
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {_BRAND["line"]};border-radius:10px;margin-bottom:10px;overflow:hidden">
  <tr>
    <td width="92" style="background:{_BRAND["accent"]};background-image:linear-gradient(135deg,{_BRAND["accent_soft"]},{_BRAND["accent"]});padding:20px;vertical-align:middle;text-align:center">
      <span style="font-size:34px">{icon}</span>
    </td>
    <td style="padding:16px">
      <div style="font-size:11px;color:{_BRAND["accent_soft"]};font-weight:700;letter-spacing:1px;text-transform:uppercase">{_esc_str(meta_bits)}</div>
      <div style="font-size:15px;font-weight:600;color:{_BRAND["navy"]};margin:4px 0;font-family:Georgia,'Times New Roman',serif">{_esc_str(title)}</div>
      <div style="font-size:13px;color:{_BRAND["ink_soft"]};line-height:1.5">{_esc_str(summary)}</div>
      <a href="{_esc_str(url)}" style="display:inline-block;margin-top:10px;font-size:13px;color:{_BRAND["accent_soft"]};font-weight:600;text-decoration:none">Enroll now →</a>
    </td>
  </tr>
</table>""")
        items_text.append(
            f"- {title}\n"
            f"  {meta_bits}\n"
            f"  {summary}\n"
            f"  {url}\n"
        )

    first_title = (recent_courses[0].get("title") or "New courses")[:60]

    header = _section_header(
        icon="🚀",
        label="NEW COURSES",
        headline="Just dropped",
        accent=_BRAND["accent_soft"],
        icon_bg="#f5e6c8",
        sublabel="Fresh AI courses matched to your interests",
    )

    html = f"""\
<tr><td style="padding:20px 28px 4px"><div style="height:1px;background:{_BRAND["line"]};margin-bottom:24px"></div>{header}</td></tr>
<tr><td style="padding:16px 28px 8px">{"".join(items_html)}</td></tr>"""

    text = "[NEW COURSES]\n" + "".join(items_text)

    return {
        "html": html,
        "text": text,
        "subject_hint": f"New course: {first_title}"[:80],
        "score": 60,
    }


# ---------------------------------------------------------------------------
# Section: From the blog
# ---------------------------------------------------------------------------

def _blog_section(recent_posts: list[dict]) -> dict | None:
    """Build the blog section from posts published in the last 7 days."""
    if not recent_posts:
        return None

    settings = get_settings()
    base_url = (settings.public_base_url or "").rstrip("/")

    items_html: list[str] = []
    items_text: list[str] = []

    for i, post in enumerate(recent_posts):
        slug = post.get("slug", "")
        title = post.get("title", "Untitled")
        excerpt = (post.get("excerpt") or post.get("summary") or "")[:200]
        category = (post.get("category") or post.get("pillar_tier") or "ARTICLE").upper()
        read_time = post.get("read_time") or post.get("read_minutes")
        meta_parts = [category]
        if read_time:
            meta_parts.append(f"{read_time} min read")
        meta = " · ".join(meta_parts)
        url = _utm(f"{base_url}/blog/{slug}", "blog")

        # Last item — no bottom border
        border = (
            "" if i == len(recent_posts) - 1
            else f"border-bottom:1px solid {_BRAND['line']}"
        )

        items_html.append(f"""\
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:14px;padding-bottom:14px;{border}">
  <tr>
    <td>
      <div style="font-size:11px;color:{_BRAND["ink_soft"]};font-weight:700;letter-spacing:1px;text-transform:uppercase">{_esc_str(meta)}</div>
      <a href="{_esc_str(url)}" style="text-decoration:none">
        <div style="font-size:16px;font-weight:600;color:{_BRAND["navy"]};margin:6px 0;line-height:1.4;font-family:Georgia,'Times New Roman',serif">{_esc_str(title)}</div>
      </a>
      {f'<div style="font-size:13px;color:{_BRAND["ink_soft"]};line-height:1.5">{_esc_str(excerpt)}</div>' if excerpt else ""}
      <a href="{_esc_str(url)}" style="display:inline-block;margin-top:8px;font-size:13px;color:{_BRAND["info"]};font-weight:600;text-decoration:none">Read article →</a>
    </td>
  </tr>
</table>""")
        items_text.append(
            f"- {title} ({meta})\n"
            f"  {url}\n"
        )

    first_title = (recent_posts[0].get("title") or "New posts")[:60]

    header = _section_header(
        icon="📝",
        label="FROM THE BLOG",
        headline="This week's reads",
        accent=_BRAND["info"],
        icon_bg="#dde7ed",
    )

    html = f"""\
<tr><td style="padding:20px 28px 4px"><div style="height:1px;background:{_BRAND["line"]};margin-bottom:24px"></div>{header}</td></tr>
<tr><td style="padding:16px 28px 20px">{"".join(items_html)}</td></tr>"""

    text = "[FROM THE BLOG]\n" + "".join(items_text)

    return {
        "html": html,
        "text": text,
        "subject_hint": first_title,
        "score": 50,
    }


# ---------------------------------------------------------------------------
# Compose: full email shell with brand header / CTA banner / footer
# ---------------------------------------------------------------------------

# Section name → footer label (shown in subscribed-channels list)
_CHANNEL_LABELS = {
    "roadmap": "Course progress",
    "new_courses": "New courses",
    "jobs": "AI jobs",
    "blog": "Blog",
}


def _build_preheader(user: User, sections: list[dict]) -> str:
    """Inbox-preview line that summarizes what's inside the email."""
    bits: list[str] = []
    for s in sections:
        hint = (s.get("subject_hint") or "").strip()
        if hint:
            bits.append(hint)
    if not bits:
        return "Your weekly AutomateEdge digest"
    # Cap at 110 chars (Gmail/iOS preview line truncation)
    joined = " · ".join(bits)
    return joined if len(joined) <= 110 else joined[:107] + "…"


def _format_today() -> str:
    """Date string in IST-friendly format. Cron runs Mon 03:30 UTC = 09:00 IST.
    Uses %d.lstrip('0') instead of %-d (POSIX-only; %-d crashes on Windows)."""
    today = date.today()
    return f"{today.strftime('%d').lstrip('0')} {today.strftime('%B %Y')}"


def _logo_block() -> str:
    """Table-based gold square + 'A' monogram. Universal email-client safe."""
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" '
        'style="display:inline-block;vertical-align:middle">'
        f'<tr><td style="background:{_BRAND["accent"]};width:40px;height:40px;'
        'border-radius:8px;text-align:center;font-family:Georgia,serif;'
        f'font-size:24px;font-weight:700;color:{_BRAND["navy"]};line-height:40px">A</td></tr>'
        '</table>'
    )


def _compose_email(
    sections: list[dict],
    user: User,
    base_url: str,
    unsub_tokens: dict[str, str],
    subscribed_channels: list[str] | None = None,
) -> tuple[str, str, str]:
    """Combine section HTML+text blocks into the full email.

    Args:
        sections: Ordered list of section dicts (html, text, subject_hint, score).
        user: Recipient.
        base_url: Public base URL (no trailing slash).
        unsub_tokens: Mapping of channel -> JWT, plus "all" -> JWT.
        subscribed_channels: List of channel names the user is subscribed to,
            in display order. Used for the footer "you subscribed to" line.
            If None, derived from unsub_tokens keys (excluding "all").

    Returns:
        (subject, text_body, html_body)
    """
    if not sections:
        # Defensive fallback — callers should gate on this.
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        subject = f"Your AutomateEdge — week of {monday.strftime('%b %d')}"
        return subject, "", ""

    # Subject = highest-score section's hint.
    best = max(sections, key=lambda s: s["score"])
    subject = (best["subject_hint"] or "").strip()[:80] or (
        f"Your AutomateEdge — week of {(date.today() - timedelta(days=date.today().weekday())).strftime('%b %d')}"
    )

    first_name = (user.name or "").split()[0] if user.name else ""
    greeting_line = (
        f"Hi {_esc_str(first_name)}, here's what's new in your AI journey"
        if first_name
        else "Here's what's new in your AI journey"
    )

    preheader = _build_preheader(user, sections)
    today_str = _format_today() or date.today().isoformat()
    section_count = len(sections)
    section_word = "update" if section_count == 1 else "updates"

    if subscribed_channels is None:
        subscribed_channels = [k for k in unsub_tokens.keys() if k != "all"]
    subscription_list_str = " · ".join(
        _CHANNEL_LABELS.get(c, c.title()) for c in subscribed_channels
    ) or "all channels"

    # Combined section markup (each section returns full <tr>...</tr> blocks).
    combined_html = "\n".join(s["html"] for s in sections)
    combined_text = "\n".join(s["text"] for s in sections)

    # Unsub URLs
    def _unsub_url(channel_or_all: str) -> str:
        return f"{base_url}/api/profile/digest/unsubscribe?t={unsub_tokens.get(channel_or_all, '')}"

    prefs_url = _utm(f"{base_url}/account", "footer_prefs")
    dashboard_url = _utm(f"{base_url}/", "cta_banner")

    html_body = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="x-apple-disable-message-reformatting">
<title>Your AutomateEdge weekly</title>
<!--[if mso]><style>table {{border-collapse:collapse;}} td {{mso-line-height-rule:exactly;}}</style><![endif]-->
</head>
<body style="margin:0;padding:0;background:{_BRAND["body_bg"]};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased">

<div style="display:none;max-height:0;overflow:hidden;mso-hide:all">
{_esc_str(preheader)} &nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;
</div>

<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{_BRAND["body_bg"]}">
<tr><td align="center" style="padding:24px 12px">

<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;width:100%;background:{_BRAND["card_bg"]};border-radius:14px;overflow:hidden;box-shadow:0 1px 3px rgba(15,20,25,0.08)">

  <!-- HEADER -->
  <tr>
    <td style="background:{_BRAND["navy"]};background-image:linear-gradient(135deg,{_BRAND["navy"]} 0%,#1a1f2a 50%,{_BRAND["accent_soft"]} 130%);padding:36px 28px;text-align:center">
      <div style="margin-bottom:14px">{_logo_block()}</div>
      <div style="display:inline-block;padding:6px 14px;background:rgba(232,168,73,0.18);border-radius:999px;font-size:11px;letter-spacing:2px;color:{_BRAND["accent"]};font-weight:700">
        WEEKLY DIGEST
      </div>
      <h1 style="margin:14px 0 0;color:#ffffff;font-size:30px;font-weight:600;letter-spacing:-0.5px;font-family:Georgia,'Times New Roman',serif">
        AutomateEdge<span style="color:{_BRAND["accent"]}">.cloud</span>
      </h1>
      <p style="margin:10px 0 0;color:{_BRAND["paper"]};font-size:15px;line-height:1.5">
        {greeting_line}
      </p>
    </td>
  </tr>

  <!-- Date strip -->
  <tr>
    <td style="padding:18px 28px 0;color:{_BRAND["ink_soft"]};font-size:12px;letter-spacing:0.5px">
      {_esc_str(today_str)} &nbsp;·&nbsp; {section_count} {section_word} curated for you
    </td>
  </tr>

  {combined_html}

  <!-- CTA BANNER -->
  <tr>
    <td style="padding:8px 28px 28px">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_BRAND["navy"]};background-image:linear-gradient(135deg,{_BRAND["navy"]},#1a1f2a);border-radius:12px">
        <tr>
          <td style="padding:26px;text-align:center">
            <div style="color:{_BRAND["accent"]};font-size:11px;font-weight:700;letter-spacing:1.5px">DAILY HABIT</div>
            <div style="color:#ffffff;font-size:18px;font-weight:600;margin:8px 0 4px;font-family:Georgia,'Times New Roman',serif">15 minutes a day = mastery in 90 days</div>
            <a href="{_esc_str(dashboard_url)}" style="display:inline-block;margin-top:14px;padding:13px 26px;background:{_BRAND["accent"]};color:{_BRAND["navy"]};font-size:14px;font-weight:700;border-radius:8px;text-decoration:none">Open my dashboard</a>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- FOOTER -->
  <tr>
    <td style="padding:26px 28px;background:{_BRAND["footer_bg"]};border-top:1px solid {_BRAND["line"]}">
      <table role="presentation" width="100%">
        <tr>
          <td style="text-align:center">
            <div style="font-size:14px;font-weight:700;color:{_BRAND["navy"]};font-family:Georgia,'Times New Roman',serif">AutomateEdge.cloud</div>
            <div style="font-size:12px;color:{_BRAND["ink_soft"]};margin-top:4px">Practical AI learning, built for builders</div>

            <div style="margin-top:22px;padding-top:20px;border-top:1px solid {_BRAND["line"]};font-size:12px;color:{_BRAND["ink_mute"]};line-height:1.6">
              You're getting this because you subscribed to:<br>
              <span style="color:{_BRAND["accent_soft"]};font-weight:600">{_esc_str(subscription_list_str)}</span>
              <br><br>
              <a href="{_esc_str(prefs_url)}" style="color:{_BRAND["accent_soft"]};text-decoration:none;font-weight:600">Manage preferences</a>
              &nbsp;·&nbsp;
              <a href="{_esc_str(_unsub_url('all'))}" style="color:{_BRAND["ink_soft"]};text-decoration:none">Unsubscribe from all</a>
              <div style="margin-top:10px;font-size:11px;color:{_BRAND["ink_mute"]}">
                One-click stop:
                <a href="{_esc_str(_unsub_url('roadmap'))}" style="color:{_BRAND["ink_soft"]};text-decoration:underline">Unsubscribe from progress reminders</a> &nbsp;·&nbsp;
                <a href="{_esc_str(_unsub_url('new_courses'))}" style="color:{_BRAND["ink_soft"]};text-decoration:underline">Unsubscribe from new course alerts</a> &nbsp;·&nbsp;
                <a href="{_esc_str(_unsub_url('jobs'))}" style="color:{_BRAND["ink_soft"]};text-decoration:underline">Unsubscribe from job alerts</a> &nbsp;·&nbsp;
                <a href="{_esc_str(_unsub_url('blog'))}" style="color:{_BRAND["ink_soft"]};text-decoration:underline">Unsubscribe from blog updates</a>
              </div>
              <br>
              © 2026 AutomateEdge.cloud &nbsp;·&nbsp; Bengaluru, India
            </div>
          </td>
        </tr>
      </table>
    </td>
  </tr>

</table>

</td></tr>
</table>

</body>
</html>"""

    text_body = (
        f"{greeting_line}\n"
        f"{today_str} · {section_count} {section_word}\n\n"
        f"{combined_text}\n\n"
        "---\n"
        "15 minutes a day = mastery in 90 days\n"
        f"Open dashboard: {dashboard_url}\n\n"
        f"You subscribed to: {subscription_list_str}\n"
        f"Manage preferences: {prefs_url}\n"
        f"Unsubscribe from job alerts: {_unsub_url('jobs')}\n"
        f"Unsubscribe from progress reminders: {_unsub_url('roadmap')}\n"
        f"Unsubscribe from new course alerts: {_unsub_url('new_courses')}\n"
        f"Unsubscribe from blog updates: {_unsub_url('blog')}\n"
        f"Unsubscribe from all: {_unsub_url('all')}\n"
    )

    return subject, text_body, html_body


# ---------------------------------------------------------------------------
# Recent content helpers (computed once per run)
# ---------------------------------------------------------------------------

def _recent_blog_posts(lookback_days: int = 7) -> list[dict]:
    """Posts published within the last ``lookback_days`` days. Disk read."""
    from app.services.blog_publisher import list_published
    cutoff = date.today() - timedelta(days=lookback_days)
    out: list[dict] = []
    for post in list_published():
        raw_date = post.get("published", "")
        if not raw_date:
            continue
        try:
            pub_date = date.fromisoformat(raw_date[:10])
        except ValueError:
            continue
        if pub_date >= cutoff:
            out.append(post)
    return out


def _recent_courses(lookback_days: int = 7) -> list[dict]:
    """Curriculum templates published (last_reviewed_on) within the last
    ``lookback_days`` days. Reads _meta.json on disk."""
    from app.curriculum.loader import _load_meta, load_template
    cutoff = date.today() - timedelta(days=lookback_days)
    out: list[dict] = []
    meta = _load_meta()
    for key, m in meta.items():
        if not isinstance(m, dict) or m.get("status") != "published":
            continue
        last = m.get("last_reviewed_on", "")
        if not last:
            continue
        try:
            pub_date = date.fromisoformat(str(last)[:10])
        except ValueError:
            continue
        if pub_date < cutoff:
            continue
        try:
            tpl = load_template(key)
        except Exception:
            continue
        out.append({
            "key": key,
            "title": tpl.title,
            "summary": tpl.summary or "",
            "duration_months": tpl.duration_months,
            "level": tpl.level,
            "published": str(last),
        })
    return out


# ---------------------------------------------------------------------------
# Per-user composer + sender (extracted so test scripts can call it directly)
# ---------------------------------------------------------------------------

async def _send_user_digest(
    user: User,
    db,
    *,
    recent_posts: list[dict],
    recent_courses_list: list[dict],
    jobs_pool: list[Job],
    base_url: str,
    dry_run: bool = False,
) -> tuple[bool, str]:
    """Build and send the digest for a single user.

    Returns (sent, status) where status is one of:
        "sent"            — email was dispatched
        "no_content"      — user has channels on but no section had content
        "all_off"         — user has no channels enabled (filtered upstream
                            but defensive here)
    With dry_run=True, the SMTP send is skipped; the function still composes
    the email and returns ("sent" if it would have sent, status).
    """
    sections: list[dict] = []
    subscribed_channels: list[str] = []

    if user.notify_roadmap:
        subscribed_channels.append("roadmap")
        section = await _roadmap_section(user, db)
        if section is not None:
            sections.append(section)

    if user.notify_new_courses:
        subscribed_channels.append("new_courses")
        section = _courses_section(recent_courses_list)
        if section is not None:
            sections.append(section)

    if user.notify_jobs and jobs_pool:
        subscribed_channels.append("jobs")
        section = await _jobs_section(user, jobs_pool, db)
        if section is not None:
            sections.append(section)
    elif user.notify_jobs:
        subscribed_channels.append("jobs")

    if user.notify_blog:
        subscribed_channels.append("blog")
        section = _blog_section(recent_posts)
        if section is not None:
            sections.append(section)

    if not subscribed_channels:
        return False, "all_off"

    if not sections:
        return False, "no_content"

    unsub_tokens = {
        "jobs": _unsub_token(user, "jobs"),
        "roadmap": _unsub_token(user, "roadmap"),
        "blog": _unsub_token(user, "blog"),
        "new_courses": _unsub_token(user, "new_courses"),
        "all": _unsub_token(user),
    }

    subject, text_body, html_body = _compose_email(
        sections, user, base_url, unsub_tokens,
        subscribed_channels=subscribed_channels,
    )

    if not dry_run:
        await _send(user.email, subject, text_body, html_body)
    return True, "sent"


# ---------------------------------------------------------------------------
# Main cron entrypoint
# ---------------------------------------------------------------------------

async def run_weekly_combined_digest() -> dict[str, int]:
    """Cron entrypoint — one combined email per opted-in user.

    Returns stats dict: eligible, sent, skipped_no_content, errors.
    """
    settings = get_settings()
    base_url = (settings.public_base_url or "").rstrip("/")

    stats = {"eligible": 0, "sent": 0, "skipped_no_content": 0, "errors": 0}

    # Compute once per run (disk reads, not per user).
    recent_posts = _recent_blog_posts()
    recent_courses_list = _recent_courses()

    async with _db.async_session_factory() as db:
        users = await _eligible_users(db)
        stats["eligible"] = len(users)

        # Jobs pool also computed once per run.
        jobs_pool = await _recent_published_jobs(db)

        sent_count = 0
        for user in users:
            if sent_count >= MAX_EMAILS_PER_RUN:
                logger.warning("digest: hit email cap (%d), stopping", MAX_EMAILS_PER_RUN)
                break

            try:
                sent, status = await _send_user_digest(
                    user, db,
                    recent_posts=recent_posts,
                    recent_courses_list=recent_courses_list,
                    jobs_pool=jobs_pool,
                    base_url=base_url,
                )
                if sent:
                    stats["sent"] += 1
                    sent_count += 1
                    await asyncio.sleep(2)
                    if sent_count % BATCH_SIZE == 0:
                        logger.info(
                            "digest: batch %d complete (%d sent), pausing 60s",
                            sent_count // BATCH_SIZE, sent_count,
                        )
                        await asyncio.sleep(60)
                elif status == "no_content":
                    stats["skipped_no_content"] += 1

            except Exception as exc:
                logger.exception("digest: send failed for user %s: %s", user.id, exc)
                stats["errors"] += 1

    logger.info("combined digest complete: %s", stats)
    return stats
