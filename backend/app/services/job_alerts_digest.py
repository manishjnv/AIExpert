"""Per-company job-alert digest — daily, opt-in (Phase 1, email channel).

For each user who follows one or more companies (job_alert_subscriptions,
channel='email', active=1), email them the jobs from those companies that were
published since the last run. Clones the jobs_digest.py send/render shape;
SMTP only, no AI calls. Safe to re-run — `since` bounds the window, so a double
run on the same day just re-sends the same small set (the script's watermark
prevents that in production).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from email.message import EmailMessage
from html import escape as _esc

import aiosmtplib
from sqlalchemy import select

import app.db as _db
from app.config import get_settings
from app.models import Job, JobAlertSubscription, JobCompany
from app.models.user import User

logger = logging.getLogger("roadmap.jobs.alerts_digest")

MAX_JOBS = 500          # cap the new-jobs window scan
MAX_PER_COMPANY = 10    # cap rows shown per company in one email


def esc(s: object) -> str:
    return _esc("" if s is None else str(s))


async def _send(to_email: str, subject: str, text: str, html: str) -> None:
    settings = get_settings()
    if not settings.smtp_host:
        logger.info("DEV MODE — would send alert digest to %s (subject=%s)", to_email, subject)
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


def _render(user: User, matched: list[tuple[str, str, list[Job]]],
            base_url: str) -> tuple[str, str, str]:
    """matched: list of (company_slug, company_name, jobs). Returns (text, html, subject)."""
    greeting = f"Hi {esc(user.name)}," if user.name else "Hi,"
    total = sum(len(j) for _, _, j in matched)
    blocks_html, blocks_text = [], []

    for _slug, company_name, jobs in matched:
        rows_html, rows_text = [], []
        for job in jobs[:MAX_PER_COMPANY]:
            d = job.data or {}
            loc = d.get("location") or {}
            loc_str = " · ".join(filter(None, [loc.get("city"), loc.get("country"), loc.get("remote_policy")])) or "—"
            url = f"{base_url}/jobs/{job.slug}"
            rows_html.append(
                f'<div style="border:1px solid #e4e4e4;border-radius:6px;padding:12px 16px;margin-bottom:10px;background:#fff">'
                f'<div style="font-size:15px;font-weight:600"><a href="{esc(url)}" style="color:#1a1a1a;text-decoration:none">{esc(job.title)}</a></div>'
                f'<div style="color:#666;font-size:13px;margin-top:2px">{esc(loc_str)}</div></div>'
            )
            rows_text.append(f"  - {job.title}\n    {loc_str}\n    {url}\n")
        blocks_html.append(
            f'<p style="font-size:15px;font-weight:600;margin:18px 0 8px">{esc(company_name)} '
            f'<span style="color:#888;font-weight:400">({len(jobs)} new)</span></p>'
            + "".join(rows_html)
        )
        blocks_text.append(f"{company_name} ({len(jobs)} new):\n" + "".join(rows_text))

    manage_url = f"{base_url}/account"
    html = (
        '<div style="font-family:-apple-system,Segoe UI,sans-serif;max-width:640px;margin:0 auto;padding:24px 16px;color:#1a1a1a">'
        f'<p style="font-size:15px">{greeting}</p>'
        f'<p style="font-size:15px">New AI/ML roles from companies you follow:</p>'
        + "".join(blocks_html)
        + '<hr style="border:none;border-top:1px solid #eee;margin:24px 0 12px">'
        f'<p style="font-size:11px;color:#999">You follow these companies on AutomateEdge. '
        f'<a href="{esc(manage_url)}" style="color:#999">Manage your job alerts</a>.</p></div>'
    )
    text = (
        f"{greeting}\n\nNew AI/ML roles from companies you follow:\n\n"
        + "\n".join(blocks_text)
        + f"\nManage your job alerts: {manage_url}\n"
    )
    first_company = matched[0][1]
    subject = (f"{total} new AI jobs at {first_company}"
               if len(matched) == 1
               else f"{total} new AI jobs from {len(matched)} companies you follow")
    return text, html, subject


async def run_job_alerts_digest(since: datetime) -> dict[str, int]:
    """Email each subscriber the jobs published since `since` from companies
    they follow. Returns stats for logging."""
    settings = get_settings()
    base_url = (settings.public_base_url or "").rstrip("/")
    stats = {"new_jobs": 0, "subscribers": 0, "sent": 0, "errors": 0}

    async with _db.async_session_factory() as db:
        jobs = list((await db.execute(
            select(Job)
            .where(Job.status == "published", Job.updated_at >= since)
            .order_by(Job.posted_on.desc())
            .limit(MAX_JOBS)
        )).scalars().all())
        stats["new_jobs"] = len(jobs)
        if not jobs:
            logger.info("alert digest: no jobs published since %s — skipping", since)
            return stats

        jobs_by_company: dict[str, list[Job]] = defaultdict(list)
        for j in jobs:
            jobs_by_company[j.company_slug].append(j)

        subs = (await db.execute(
            select(JobAlertSubscription).where(
                JobAlertSubscription.channel == "email",
                JobAlertSubscription.active == 1,
                JobAlertSubscription.company_slug.in_(list(jobs_by_company.keys())),
            )
        )).scalars().all()
        user_companies: dict[int, set[str]] = defaultdict(set)
        for s in subs:
            user_companies[s.user_id].add(s.company_slug)
        if not user_companies:
            logger.info("alert digest: %d new jobs but no matching subscribers", len(jobs))
            return stats

        users = list((await db.execute(
            select(User).where(User.id.in_(list(user_companies.keys())))
        )).scalars().all())
        names = {slug: name for slug, name in (await db.execute(
            select(JobCompany.slug, JobCompany.name)
            .where(JobCompany.slug.in_(list(jobs_by_company.keys())))
        )).all()}
        stats["subscribers"] = len(users)

        for user in users:
            matched: list[tuple[str, str, list[Job]]] = []
            for slug in sorted(user_companies[user.id]):
                cj = jobs_by_company.get(slug)
                if cj:
                    matched.append((slug, names.get(slug, slug), cj))
            if not matched:
                continue
            try:
                text, html, subject = _render(user, matched, base_url)
                await _send(user.email, subject, text, html)
                stats["sent"] += 1
            except Exception as exc:
                logger.exception("alert digest send failed for user %s: %s", user.id, exc)
                stats["errors"] += 1

    logger.info("alert digest complete: %s", stats)
    return stats
