"""
Weekly progress reminder emails.

Sends a summary email to active users every Monday.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import aiosmtplib
from email.message import EmailMessage
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.plan import Progress, UserPlan
from app.models.user import User

logger = logging.getLogger("roadmap.reminder")


async def send_weekly_reminders(session_factory) -> int:
    """Send progress reminder emails to all eligible users.

    Returns the number of emails sent.
    """
    settings = get_settings()
    sent = 0
    MAX_EMAILS_PER_RUN = 100  # Gmail free limit safety cap

    async with session_factory() as db:
        # Get all users with email_notifications=True and an active plan
        users = (await db.execute(
            select(User).where(
                User.email_notifications == True,
            )
        )).scalars().all()

        for user in users:
            if sent >= MAX_EMAILS_PER_RUN:
                logger.warning("Hit email cap (%d), stopping", MAX_EMAILS_PER_RUN)
                break
            try:
                # Get active plan
                plan = (await db.execute(
                    select(UserPlan).where(
                        UserPlan.user_id == user.id,
                        UserPlan.status == "active",
                    )
                )).scalar_one_or_none()

                if plan is None:
                    continue

                # Count progress
                total_done = (await db.execute(
                    select(func.count()).select_from(Progress).where(
                        Progress.user_plan_id == plan.id,
                        Progress.done == True,
                    )
                )).scalar() or 0

                # Count tasks done in the last 7 days
                week_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
                done_this_week = (await db.execute(
                    select(func.count()).select_from(Progress).where(
                        Progress.user_plan_id == plan.id,
                        Progress.done == True,
                        Progress.completed_at > week_ago,
                    )
                )).scalar() or 0

                # Skip inactive users (no activity in 30 days)
                last_activity = (await db.execute(
                    select(func.max(Progress.updated_at)).where(
                        Progress.user_plan_id == plan.id,
                    )
                )).scalar()

                if last_activity:
                    days_inactive = (datetime.now(timezone.utc).replace(tzinfo=None) - last_activity).days
                    if days_inactive > 30:
                        continue

                # Get total checks from template
                from app.curriculum.loader import load_template
                try:
                    tpl = load_template(plan.template_key)
                    total_checks = tpl.total_checks
                except Exception:
                    total_checks = 120  # fallback

                pct = round((total_done / total_checks) * 100) if total_checks else 0

                # Skip 100% complete
                if pct >= 100:
                    continue

                # Build and send email
                first_name = (user.name or "Learner").split()[0]
                await _send_reminder_email(
                    to=user.email,
                    first_name=first_name,
                    done_this_week=done_this_week,
                    total_done=total_done,
                    total_checks=total_checks,
                    pct=pct,
                )
                sent += 1
                # Throttle: 2 second delay between emails to avoid Gmail blocking
                await asyncio.sleep(2)

            except Exception as e:
                logger.error("Failed to send reminder to %s: %s", user.email, e)

    logger.info("Weekly reminders sent: %d", sent)
    return sent


async def _send_reminder_email(
    to: str, first_name: str, done_this_week: int,
    total_done: int, total_checks: int, pct: int,
) -> None:
    """Send a single reminder email."""
    settings = get_settings()

    if not settings.smtp_host:
        logger.info("DEV MODE — Reminder for %s: %d done this week, %d%% overall", to, done_this_week, pct)
        return

    if done_this_week > 0:
        subject = f"Great week, {first_name}! {done_this_week} tasks completed"
        intro = f"You completed <strong>{done_this_week} tasks</strong> this week. Keep the momentum going!"
    else:
        subject = f"{first_name}, your AI roadmap misses you"
        intro = "You didn't complete any tasks this week. Even 15 minutes of study compounds over time."

    html = f"""\
<div style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:24px">
  <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.15em;color:#c98e2f;margin-bottom:8px">AI Learning Roadmap</div>
  <h2 style="color:#1a1a1a;font-size:22px;margin:0 0 12px">Weekly Progress Update</h2>
  <p style="color:#444;font-size:14px;line-height:1.6">Hi {first_name},</p>
  <p style="color:#444;font-size:14px;line-height:1.6">{intro}</p>

  <div style="background:#f5f1e8;padding:16px;border-radius:8px;margin:16px 0;text-align:center">
    <div style="font-size:36px;font-weight:bold;color:#c98e2f">{pct}%</div>
    <div style="font-size:12px;color:#666">{total_done} / {total_checks} tasks complete</div>
  </div>

  <a href="https://automateedge.cloud" style="display:inline-block;padding:12px 24px;background:#c98e2f;color:#fff;text-decoration:none;border-radius:4px;font-weight:600;font-size:14px">Continue Learning</a>

  <p style="color:#999;font-size:11px;margin-top:24px;border-top:1px solid #eee;padding-top:12px">
    You're receiving this because you have an active plan on AI Learning Roadmap.
    <a href="https://automateedge.cloud" style="color:#999">Unsubscribe</a> in Account Settings.
  </p>
</div>"""

    msg = EmailMessage()
    msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(f"Hi {first_name}, you completed {done_this_week} tasks this week. {pct}% overall. Continue at https://automateedge.cloud")
    msg.add_alternative(html, subtype="html")

    await aiosmtplib.send(
        msg,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user,
        password=settings.smtp_password,
        start_tls=True,
    )
