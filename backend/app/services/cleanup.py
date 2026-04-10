"""
Background cleanup tasks for expired OTP codes and revoked/expired sessions.

Started as asyncio tasks during the FastAPI lifespan.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

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
