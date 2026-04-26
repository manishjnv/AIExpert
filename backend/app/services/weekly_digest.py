"""Combined weekly digest — one email per opted-in user, Monday morning IST.

Sections render conditionally based on the user's per-channel toggles
AND whether each section has content. A section with the channel on but
no content (e.g. notify_jobs=True but no jobs match >=40%) is omitted
silently — we don't ship empty placeholders. If after composition no
sections rendered, the user is skipped (no empty email).

Section order is fixed: roadmap (course progress) > jobs > blog. This
mirrors per-user value: progress is most personal, jobs are action-
oriented, blog is passive read.

Costs: no AI calls. SMTP only. Stateless across runs — the cron
guarantees one send per Monday; we don't track last_sent_at.
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
        channel: One of {"jobs", "roadmap", "blog"} to unsubscribe from a
            single channel, or None to unsubscribe from all (backward-compat
            with the existing /api/profile/digest/unsubscribe endpoint).

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
    )
    return list((await db.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

async def _roadmap_section(user: User, db) -> dict | None:
    """Build the roadmap progress section for a user.

    Returns None when:
    - The user has no active plan.
    - The plan is 100 % complete.
    - The user has had no Progress activity in the last 30 days.

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

    # Last-activity guard (30-day inactivity → skip).
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
    try:
        tpl = load_template(plan.template_key)
        total_checks = tpl.total_checks
    except Exception:
        total_checks = 120  # fallback

    pct = round((total_done / total_checks) * 100) if total_checks else 0

    # Skip completed plans.
    if pct >= 100:
        return None

    first_name = (user.name or "Learner").split()[0]

    if done_this_week > 0:
        subject_hint = f"Great week — {done_this_week} tasks done"
        intro_text = f"You completed {done_this_week} tasks this week. Keep the momentum going!"
        intro_html = f"You completed <strong>{done_this_week} tasks</strong> this week. Keep the momentum going!"
    else:
        subject_hint = "Your AI roadmap misses you"
        intro_text = "You didn't complete any tasks this week. Even 15 minutes of study compounds over time."
        intro_html = intro_text

    # intro_html is a controlled internal literal containing <strong> tags;
    # the only interpolated value is the int from a SQL COUNT(). Do NOT
    # _esc_str() it — that would render literal &lt;strong&gt; in the email.
    html = f"""\
<div style="margin-bottom:24px">
  <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.15em;color:#c98e2f;margin-bottom:6px">Course Progress</div>
  <p style="color:#444;font-size:14px;line-height:1.6;margin:0 0 12px">{intro_html}</p>
  <div style="background:#f5f1e8;padding:16px;border-radius:8px;text-align:center;margin-bottom:12px">
    <div style="font-size:36px;font-weight:bold;color:#c98e2f">{pct}%</div>
    <div style="font-size:12px;color:#666">{total_done} / {total_checks} tasks complete</div>
  </div>
  <a href="https://automateedge.cloud" style="display:inline-block;padding:10px 20px;background:#c98e2f;color:#fff;text-decoration:none;border-radius:4px;font-weight:600;font-size:13px">Continue Learning</a>
</div>"""

    text = (
        f"[COURSE PROGRESS]\n"
        f"{intro_text}\n"
        f"Overall: {pct}% ({total_done}/{total_checks} tasks)\n"
        f"Continue: https://automateedge.cloud\n"
    )

    score = min(done_this_week * 10, 100)

    return {
        "html": html,
        "text": text,
        "subject_hint": subject_hint[:80],
        "score": score,
    }


async def _jobs_section(user: User, jobs_pool: list[Job], db) -> dict | None:
    """Build the top job matches section for a user.

    Returns None if no jobs score >= 40 %.
    """
    matches = await _top_matches(user, jobs_pool, db)
    if not matches:
        return None

    settings = get_settings()
    base_url = (settings.public_base_url or "").rstrip("/")

    items_html: list[str] = []
    items_text: list[str] = []

    for job, m in matches:
        d = job.data or {}
        loc = d.get("location") or {}
        company_name = (d.get("company") or {}).get("name") or job.company_slug
        loc_str = " · ".join(filter(None, [
            loc.get("city"), loc.get("country"), loc.get("remote_policy"),
        ])) or "—"
        url = f"{base_url}/jobs/{job.slug}"
        tone = "#2e7d48" if m["score"] >= 70 else "#d88600"

        items_html.append(f"""\
<div style="border:1px solid #e4e4e4;border-radius:6px;padding:14px 18px;margin-bottom:12px;background:#fff">
  <div style="display:flex;align-items:flex-start;gap:12px">
    <div style="background:{tone};color:#fff;padding:4px 10px;border-radius:3px;font-size:13px;font-weight:600;white-space:nowrap">{m["score"]}% match</div>
    <div style="flex:1">
      <div style="font-size:16px;font-weight:600"><a href="{_esc_str(url)}" style="color:#1a1a1a;text-decoration:none">{_esc_str(job.title)}</a></div>
      <div style="color:#666;font-size:13px;margin-top:2px">{_esc_str(company_name)} · {_esc_str(loc_str)}</div>
      <div style="color:#888;font-size:12px;margin-top:6px">{_esc_str((d.get("tldr") or "")[:160])}</div>
    </div>
  </div>
</div>""")
        items_text.append(
            f"- {job.title} ({m['score']}% match)\n"
            f"  {company_name} · {loc_str}\n"
            f"  {url}\n"
        )

    top_score = matches[0][1]["score"]
    top_title = (matches[0][0].title or "")[:80]

    html = f"""\
<div style="margin-bottom:24px">
  <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.15em;color:#0a7;margin-bottom:6px">Top Job Matches</div>
  <p style="color:#444;font-size:14px;line-height:1.6;margin:0 0 12px">AI/ML roles that line up with your plan this week:</p>
  {"".join(items_html)}
  <p style="font-size:13px;color:#666;margin-top:6px">
    More at <a href="{_esc_str(base_url)}/jobs" style="color:#0a7">automateedge.cloud/jobs</a>.
  </p>
</div>"""

    text = (
        "[JOB MATCHES]\n"
        "AI/ML roles matching your plan this week:\n\n"
        + "\n".join(items_text)
        + f"\nMore: {base_url}/jobs\n"
    )

    return {
        "html": html,
        "text": text,
        "subject_hint": f"{top_score}% match: {top_title}"[:80],
        "score": top_score,
    }


def _blog_section(recent_posts: list[dict]) -> dict | None:
    """Build the blog section from recent posts (last 7 days).

    Returns None if no recent posts.
    """
    if not recent_posts:
        return None

    settings = get_settings()
    base_url = (settings.public_base_url or "").rstrip("/")

    items_html: list[str] = []
    items_text: list[str] = []

    for post in recent_posts:
        slug = post.get("slug", "")
        title = post.get("title", "Untitled")
        published = post.get("published", "")
        url = f"{base_url}/blog/{slug}"

        items_html.append(f"""\
<div style="border:1px solid #e4e4e4;border-radius:6px;padding:12px 16px;margin-bottom:10px;background:#fff">
  <div style="font-size:15px;font-weight:600"><a href="{_esc_str(url)}" style="color:#1a1a1a;text-decoration:none">{_esc_str(title)}</a></div>
  {f'<div style="color:#999;font-size:12px;margin-top:4px">{_esc_str(published)}</div>' if published else ""}
</div>""")
        items_text.append(f"- {title}\n  {url}\n")

    first_title = (recent_posts[0].get("title") or "New posts")[:80]

    html = f"""\
<div style="margin-bottom:24px">
  <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.15em;color:#6644aa;margin-bottom:6px">New Blog Posts</div>
  {"".join(items_html)}
</div>"""

    text = (
        "[NEW BLOG POSTS]\n"
        + "\n".join(items_text)
    )

    return {
        "html": html,
        "text": text,
        "subject_hint": first_title,
        "score": 50,
    }


# ---------------------------------------------------------------------------
# Email composition
# ---------------------------------------------------------------------------

def _compose_email(
    sections: list[dict],
    user: User,
    base_url: str,
    unsub_tokens: dict[str, str],
) -> tuple[str, str, str]:
    """Combine section content blocks into a full email.

    Args:
        sections: Ordered list of section dicts (roadmap > jobs > blog).
            Each must have: html, text, subject_hint, score.
        user: Recipient.
        base_url: The public base URL (no trailing slash).
        unsub_tokens: Mapping of channel -> token, plus "all" -> token.

    Returns:
        (subject, text_body, html_body)
    """
    if not sections:
        # Defensive fallback — callers should gate on this.
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        subject = f"Your AI Roadmap — week of {monday.strftime('%b %d')}"
        return subject, "", ""

    # Subject = highest-score section's hint.
    best = max(sections, key=lambda s: s["score"])
    raw_hint = best["subject_hint"] or ""
    subject = raw_hint[:80] if raw_hint else (
        f"Your AI Roadmap — week of {(date.today() - timedelta(days=date.today().weekday())).strftime('%b %d')}"
    )

    greeting = f"Hi {_esc_str(user.name)}," if user.name else "Hi,"

    # Assemble body.
    combined_html = "\n".join(s["html"] for s in sections)
    combined_text = "\n".join(s["text"] for s in sections)

    unsub_jobs_url = f"{base_url}/api/profile/digest/unsubscribe?t={unsub_tokens.get('jobs', '')}"
    unsub_roadmap_url = f"{base_url}/api/profile/digest/unsubscribe?t={unsub_tokens.get('roadmap', '')}"
    unsub_blog_url = f"{base_url}/api/profile/digest/unsubscribe?t={unsub_tokens.get('blog', '')}"
    unsub_all_url = f"{base_url}/api/profile/digest/unsubscribe?t={unsub_tokens.get('all', '')}"

    html_body = f"""\
<div style="font-family:-apple-system,Segoe UI,sans-serif;max-width:640px;margin:0 auto;padding:24px 16px;color:#1a1a1a">
  <p style="font-size:15px">{greeting}</p>
  <p style="font-size:15px">Here's your weekly AI Roadmap update:</p>
  {combined_html}
  <hr style="border:none;border-top:1px solid #eee;margin:24px 0 12px">
  <p style="font-size:11px;color:#999;line-height:1.8">
    <a href="{_esc_str(unsub_jobs_url)}" style="color:#999">Unsubscribe from job alerts</a> &nbsp;·&nbsp;
    <a href="{_esc_str(unsub_roadmap_url)}" style="color:#999">Unsubscribe from progress reminders</a> &nbsp;·&nbsp;
    <a href="{_esc_str(unsub_blog_url)}" style="color:#999">Unsubscribe from blog updates</a><br>
    <a href="{_esc_str(unsub_all_url)}" style="color:#999">Unsubscribe from all</a>
  </p>
</div>"""

    text_body = (
        f"{greeting}\n\n"
        "Here's your weekly AI Roadmap update:\n\n"
        f"{combined_text}\n\n"
        f"Unsubscribe from job alerts: {unsub_jobs_url}\n"
        f"Unsubscribe from progress reminders: {unsub_roadmap_url}\n"
        f"Unsubscribe from blog updates: {unsub_blog_url}\n"
        f"Unsubscribe from all: {unsub_all_url}\n"
    )

    return subject, text_body, html_body


# ---------------------------------------------------------------------------
# Recent blog posts helper (computed once per run)
# ---------------------------------------------------------------------------

def _recent_blog_posts(lookback_days: int = 7) -> list[dict]:
    """Return posts published within the last ``lookback_days`` days.

    ``list_published()`` reads from disk — call once per run, not per user.
    """
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

    # Compute once per run (disk read, not per user).
    recent_posts = _recent_blog_posts()

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
                sections: list[dict] = []

                # Roadmap section.
                if user.notify_roadmap:
                    section = await _roadmap_section(user, db)
                    if section is not None:
                        sections.append(section)

                # Jobs section.
                if user.notify_jobs and jobs_pool:
                    section = await _jobs_section(user, jobs_pool, db)
                    if section is not None:
                        sections.append(section)

                # Blog section.
                if user.notify_blog:
                    section = _blog_section(recent_posts)
                    if section is not None:
                        sections.append(section)

                if not sections:
                    stats["skipped_no_content"] += 1
                    continue

                unsub_tokens = {
                    "jobs": _unsub_token(user, "jobs"),
                    "roadmap": _unsub_token(user, "roadmap"),
                    "blog": _unsub_token(user, "blog"),
                    "all": _unsub_token(user),
                }

                subject, text_body, html_body = _compose_email(
                    sections, user, base_url, unsub_tokens,
                )

                await _send(user.email, subject, text_body, html_body)
                stats["sent"] += 1
                sent_count += 1

                # Throttle: 2-second pause between emails.
                await asyncio.sleep(2)

                # 60-second pause between batches.
                if sent_count % BATCH_SIZE == 0:
                    logger.info(
                        "digest: batch %d complete (%d sent), pausing 60s",
                        sent_count // BATCH_SIZE, sent_count,
                    )
                    await asyncio.sleep(60)

            except Exception as exc:
                logger.exception("digest: send failed for user %s: %s", user.id, exc)
                stats["errors"] += 1

    logger.info("combined digest complete: %s", stats)
    return stats
