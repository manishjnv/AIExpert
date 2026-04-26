"""Weekly jobs digest — Monday 09:00 IST, opt-in.

Eligibility rule: user has email_notifications=True AND at least one active
UserPlan. First filter keeps users in control; second filters out strangers
who signed up but never enrolled.

Top-N selection: compute match-% for every published job, descending.
Deduplicate by (company, designation) so the email isn't 5 ML Engineer roles
at Anthropic. Ship the top 5.

Content is signed with a per-user unsubscribe token so clicking "unsubscribe"
flips email_notifications=False in one round-trip, no login needed.

Costs: no AI calls (match is deterministic). SMTP only. Safe to re-run — the
digest is stateless, but we only want one per week, so the cron runs
Mondays and the in-process idempotence isn't needed.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from html import escape as _esc

import aiosmtplib
from sqlalchemy import select

import app.db as _db
from app.auth.jwt import issue_token  # reused signing key for unsub tokens
from app.config import get_settings
from app.models import Job
from app.models.plan import UserPlan
from app.models.user import User
from app.services.jobs_match import compute_match

logger = logging.getLogger("roadmap.jobs.digest")

TOP_N = 5
LOOKBACK_DAYS = 14  # only recent jobs appear in the digest
CONCURRENCY = 5     # parallel match computations per user


def esc(s: object) -> str:
    return _esc("" if s is None else str(s))


async def _eligible_users(db) -> list[User]:
    """Users with jobs notifications on AND ≥ 1 active plan."""
    stmt = (select(User).distinct()
            .join(UserPlan, UserPlan.user_id == User.id)
            .where(User.notify_jobs == True,  # noqa: E712
                   UserPlan.status == "active"))
    return list((await db.execute(stmt)).scalars().all())


async def _recent_published_jobs(db) -> list[Job]:
    cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)
    stmt = (select(Job)
            .where(Job.status == "published", Job.posted_on >= cutoff)
            .order_by(Job.posted_on.desc()).limit(500))
    return list((await db.execute(stmt)).scalars().all())


async def _top_matches(user: User, jobs: list[Job], db) -> list[tuple[Job, dict]]:
    """Compute match for each job, return top N deduplicated by (company, designation)."""
    sem = asyncio.Semaphore(CONCURRENCY)

    async def score(j: Job):
        async with sem:
            return j, await compute_match(user, j, db)

    results = await asyncio.gather(*(score(j) for j in jobs))
    # Filter out low scores — emailing 10% matches is noise.
    results = [r for r in results if r[1]["score"] >= 40]
    results.sort(key=lambda x: x[1]["score"], reverse=True)

    seen: set[tuple[str, str]] = set()
    out: list[tuple[Job, dict]] = []
    for job, match in results:
        bucket = (job.company_slug, job.designation)
        if bucket in seen:
            continue
        seen.add(bucket)
        out.append((job, match))
        if len(out) >= TOP_N:
            break
    return out


def _render_email(user: User, matches: list[tuple[Job, dict]], base_url: str,
                  unsub_token: str) -> tuple[str, str]:
    """Return (text_body, html_body). Keep HTML simple — Outlook / Gmail
    inline-styled only; no CSS stylesheets, no external fonts."""
    greeting = f"Hi {esc(user.name)}," if user.name else "Hi,"
    items_html = []
    items_text = []

    for job, m in matches:
        d = job.data or {}
        loc = d.get("location") or {}
        company_name = (d.get("company") or {}).get("name") or job.company_slug
        loc_str = " · ".join(filter(None, [loc.get("city"), loc.get("country"), loc.get("remote_policy")])) or "—"
        url = f"{base_url}/jobs/{job.slug}"
        tone = "#2e7d48" if m["score"] >= 70 else "#d88600"

        items_html.append(f"""
<div style="border:1px solid #e4e4e4;border-radius:6px;padding:14px 18px;margin-bottom:12px;background:#fff">
  <div style="display:flex;align-items:flex-start;gap:12px">
    <div style="background:{tone};color:#fff;padding:4px 10px;border-radius:3px;font-size:13px;font-weight:600;white-space:nowrap">{m["score"]}% match</div>
    <div style="flex:1">
      <div style="font-size:16px;font-weight:600"><a href="{esc(url)}" style="color:#1a1a1a;text-decoration:none">{esc(job.title)}</a></div>
      <div style="color:#666;font-size:13px;margin-top:2px">{esc(company_name)} · {esc(loc_str)}</div>
      <div style="color:#888;font-size:12px;margin-top:6px">{esc((d.get("tldr") or "")[:160])}</div>
    </div>
  </div>
</div>""")
        items_text.append(
            f"- {job.title} ({m['score']}% match)\n"
            f"  {company_name} · {loc_str}\n"
            f"  {url}\n"
        )

    unsub_url = f"{base_url}/api/profile/digest/unsubscribe?t={unsub_token}"

    html = f"""\
<div style="font-family:-apple-system,Segoe UI,sans-serif;max-width:640px;margin:0 auto;padding:24px 16px;color:#1a1a1a">
  <p style="font-size:15px">{greeting}</p>
  <p style="font-size:15px">Top AI/ML roles that line up with your AutomateEdge plan this week:</p>
  {"".join(items_html)}
  <p style="font-size:13px;color:#666;margin-top:18px">
    More at <a href="{esc(base_url)}/jobs" style="color:#0a7">automateedge.cloud/jobs</a>.
    Match percentages use your linked repos + completed modules.
  </p>
  <hr style="border:none;border-top:1px solid #eee;margin:24px 0 12px">
  <p style="font-size:11px;color:#999">
    You're receiving this because email notifications are on in your AutomateEdge account.
    <a href="{esc(unsub_url)}" style="color:#999">Unsubscribe</a>.
  </p>
</div>"""

    text = (
        f"{greeting}\n\n"
        f"Top AI/ML roles matching your plan this week:\n\n"
        + "\n".join(items_text)
        + f"\n\nMore: {base_url}/jobs\n"
        + f"Unsubscribe: {unsub_url}\n"
    )
    return text, html


async def _send(to_email: str, subject: str, text: str, html: str) -> None:
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


def _unsub_token(user: User) -> str:
    """Tiny signed token — reuses jwt_secret via python-jose, 90-day expiry."""
    from jose import jwt
    settings = get_settings()
    payload = {"sub": str(user.id), "k": "unsub",
               "exp": int((datetime.utcnow() + timedelta(days=90)).timestamp())}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


async def run_weekly_digest() -> dict[str, int]:
    """Cron entrypoint. Returns stats for logging."""
    settings = get_settings()
    base_url = (settings.public_base_url or "").rstrip("/")

    stats = {"eligible": 0, "sent": 0, "skipped_no_matches": 0, "errors": 0}
    async with _db.async_session_factory() as db:
        users = await _eligible_users(db)
        stats["eligible"] = len(users)
        jobs = await _recent_published_jobs(db)
        if not jobs:
            logger.info("digest: no recent published jobs — skipping entire run")
            return stats

        for user in users:
            try:
                matches = await _top_matches(user, jobs, db)
                if not matches:
                    stats["skipped_no_matches"] += 1
                    continue
                token = _unsub_token(user)
                text, html = _render_email(user, matches, base_url, token)
                subject = f"{matches[0][1]['score']}% match: {matches[0][0].title} + {len(matches)-1} more"
                await _send(user.email, subject, text, html)
                stats["sent"] += 1
            except Exception as exc:
                logger.exception("digest send failed for user %s: %s", user.id, exc)
                stats["errors"] += 1
    logger.info("digest complete: %s", stats)
    return stats
