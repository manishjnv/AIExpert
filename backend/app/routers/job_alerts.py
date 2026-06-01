"""Per-company job-alert subscriptions (Phase 1 — email).

A logged-in user follows a company; a daily digest (scripts/send_job_alerts.py)
emails them the new published jobs from companies they follow. Channel is
'email' in Phase 1 (telegram/whatsapp reserved in the model for later phases).

Auth: every endpoint requires a logged-in user. State-changing routes rely on
the SameSite=Lax auth cookie (same posture as /api/profile mutations).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db import get_db
from app.models import Job, JobAlertSubscription, JobCompany
from app.models.user import User

logger = logging.getLogger("roadmap.jobs.alerts")

router = APIRouter()

ALLOWED_CHANNELS = {"email"}  # Phase 1; telegram/whatsapp land in later phases.


class SubscribeBody(BaseModel):
    company_slug: str
    channel: str = "email"

    @field_validator("company_slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if not v or len(v) > 120:
            raise ValueError("invalid company_slug")
        return v

    @field_validator("channel")
    @classmethod
    def _channel(cls, v: str) -> str:
        v = (v or "email").strip().lower()
        if v not in ALLOWED_CHANNELS:
            raise ValueError(f"channel must be one of {sorted(ALLOWED_CHANNELS)}")
        return v


async def _company_exists(db: AsyncSession, slug: str) -> bool:
    """A subscribable company = a registered JobCompany OR any job from it."""
    co = (await db.execute(select(JobCompany.id).where(JobCompany.slug == slug))).first()
    if co:
        return True
    job = (await db.execute(select(Job.id).where(Job.company_slug == slug).limit(1))).first()
    return job is not None


@router.post("/api/jobs/subscribe")
async def subscribe(
    body: SubscribeBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not await _company_exists(db, body.company_slug):
        raise HTTPException(404, "unknown company")
    # Check-then-insert (clean session → no post-IntegrityError attribute access,
    # which trips async SQLAlchemy's MissingGreenlet). Idempotent: an existing
    # row is re-activated if it had been turned off.
    existing = (await db.execute(
        select(JobAlertSubscription).where(
            JobAlertSubscription.user_id == user.id,
            JobAlertSubscription.company_slug == body.company_slug,
            JobAlertSubscription.channel == body.channel,
        )
    )).scalar_one_or_none()
    if existing is not None:
        if not existing.active:
            existing.active = 1
            await db.commit()
        return {"ok": True, "company_slug": body.company_slug, "channel": body.channel, "subscribed": True}
    db.add(JobAlertSubscription(
        user_id=user.id, company_slug=body.company_slug, channel=body.channel, active=1
    ))
    try:
        await db.commit()
    except IntegrityError:
        # Rare concurrent double-click hit the unique index — already created
        # by the other request. Treat as success; don't touch a stale object.
        await db.rollback()
    return {"ok": True, "company_slug": body.company_slug, "channel": body.channel, "subscribed": True}


@router.post("/api/jobs/unsubscribe")
async def unsubscribe(
    body: SubscribeBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = (await db.execute(
        select(JobAlertSubscription).where(
            JobAlertSubscription.user_id == user.id,
            JobAlertSubscription.company_slug == body.company_slug,
            JobAlertSubscription.channel == body.channel,
        )
    )).scalar_one_or_none()
    if existing:
        await db.delete(existing)
        await db.commit()
    return {"ok": True, "company_slug": body.company_slug, "channel": body.channel, "subscribed": False}


@router.get("/api/jobs/subscriptions")
async def list_subscriptions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    subs = (await db.execute(
        select(JobAlertSubscription).where(
            JobAlertSubscription.user_id == user.id,
            JobAlertSubscription.active == 1,
        ).order_by(JobAlertSubscription.created_at.desc())
    )).scalars().all()
    # Resolve friendly company names in one query.
    slugs = {s.company_slug for s in subs}
    names: dict[str, str] = {}
    if slugs:
        for slug, name in (await db.execute(
            select(JobCompany.slug, JobCompany.name).where(JobCompany.slug.in_(slugs))
        )).all():
            names[slug] = name
    return {
        "subscriptions": [
            {
                "company_slug": s.company_slug,
                "company_name": names.get(s.company_slug, s.company_slug),
                "channel": s.channel,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in subs
        ]
    }
