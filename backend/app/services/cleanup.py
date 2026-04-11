"""
Background cleanup tasks for expired OTP codes and revoked/expired sessions.

Started as asyncio tasks during the FastAPI lifespan.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.models.user import OtpCode, Session as SessionModel

logger = logging.getLogger("roadmap.cleanup")


async def cleanup_expired_otps(get_session_factory):
    """Delete expired or consumed OTP codes every hour."""
    while True:
        try:
            async with get_session_factory() as db:
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                result = await db.execute(
                    delete(OtpCode).where(
                        (OtpCode.expires_at < now) | (OtpCode.consumed_at.is_not(None))
                    )
                )
                await db.commit()
                if result.rowcount:
                    logger.info("Cleaned up %d expired/consumed OTP codes", result.rowcount)
        except Exception:
            logger.exception("Error in OTP cleanup task")

        await asyncio.sleep(3600)  # 1 hour


async def cleanup_expired_sessions(get_session_factory):
    """Delete revoked or expired sessions daily."""
    while True:
        try:
            async with get_session_factory() as db:
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                result = await db.execute(
                    delete(SessionModel).where(
                        (SessionModel.expires_at < now) | (SessionModel.revoked_at.is_not(None))
                    )
                )
                await db.commit()
                if result.rowcount:
                    logger.info("Cleaned up %d expired/revoked sessions", result.rowcount)
        except Exception:
            logger.exception("Error in session cleanup task")

        await asyncio.sleep(86400)  # 24 hours


async def send_weekly_reminders(get_session_factory):
    """Send weekly progress reminder emails every Monday at 8 AM UTC."""
    while True:
        try:
            now = datetime.now(timezone.utc)
            # Calculate seconds until next Monday 8 AM UTC
            days_until_monday = (7 - now.weekday()) % 7
            if days_until_monday == 0 and now.hour >= 8:
                days_until_monday = 7
            next_monday = now.replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=days_until_monday)
            wait_seconds = (next_monday - now).total_seconds()
            logger.info("Next weekly reminder in %.1f hours", wait_seconds / 3600)
            await asyncio.sleep(wait_seconds)

            from app.services.weekly_reminder import send_weekly_reminders as do_send
            sent = await do_send(get_session_factory)
            logger.info("Weekly reminders sent: %d", sent)
        except Exception:
            logger.exception("Error in weekly reminder task")
            await asyncio.sleep(3600)  # retry in 1 hour on error
