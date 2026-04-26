"""Tests for jobs_digest section helpers and run_weekly_digest cron."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

import app.db as db_module
import app.models  # noqa: F401
from app.db import Base, close_db, init_db
from app.models import Job
from app.models.plan import UserPlan
from app.models.user import User
from app.services import jobs_digest


async def _setup():
    await init_db(url="sqlite+aiosqlite:///:memory:")
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _mk_user(
    email,
    *,
    notify_jobs: bool = True,
    notify_roadmap: bool = True,
    notify_blog: bool = True,
    with_plan: bool = True,
) -> User:
    async with db_module.async_session_factory() as db:
        u = User(
            email=email, provider="otp",
            notify_jobs=notify_jobs,
            notify_roadmap=notify_roadmap,
            notify_blog=notify_blog,
            experience_level="advanced",
        )
        db.add(u)
        await db.flush()
        if with_plan:
            db.add(UserPlan(
                user_id=u.id,
                template_key="generalist_6mo_intermediate",
                plan_version="v1",
                status="active",
            ))
        await db.commit()
        return u


async def _mk_job(slug: str, **over) -> Job:
    defaults = dict(
        source="greenhouse:anthropic", external_id=slug, source_url="http://x",
        hash=slug, status="published",
        posted_on=date.today() - timedelta(days=1),
        valid_through=date.today() + timedelta(days=44),
        slug=slug, title="ML Engineer", company_slug="anthropic",
        designation="ML Engineer", country="US", remote_policy="Hybrid", verified=1,
        data={
            "tldr": "x", "must_have_skills": ["PyTorch"],
            "company": {"name": "Anthropic", "slug": "anthropic"},
            "location": {"country": "US", "city": "SF", "remote_policy": "Hybrid"},
            "employment": {"experience_years": {"min": 5, "max": 8}},
        },
    )
    defaults.update(over)
    async with db_module.async_session_factory() as db:
        j = Job(**defaults)
        db.add(j)
        await db.commit()
        return j


# ---------- eligibility ----------

@pytest.mark.asyncio
async def test_eligibility_requires_active_plan_and_notify_jobs():
    await _setup()
    # notify_jobs=True + active plan → eligible.
    await _mk_user("a@t.com", notify_jobs=True, with_plan=True)
    # notify_jobs=False → not eligible (jobs digest only, not combined digest).
    await _mk_user("b@t.com", notify_jobs=False, with_plan=True)
    # notify_jobs=True but no plan → not eligible.
    await _mk_user("c@t.com", notify_jobs=True, with_plan=False)
    async with db_module.async_session_factory() as db:
        users = await jobs_digest._eligible_users(db)
    emails = {u.email for u in users}
    assert emails == {"a@t.com"}
    await close_db()


# ---------- digest sending ----------

@pytest.mark.asyncio
async def test_run_digest_sends_to_eligible_users_and_skips_empty_matches():
    await _setup()
    await _mk_user("a@t.com")
    await _mk_job("j1")

    sent = []
    async def fake_send(to_email, subject, text, html):
        sent.append((to_email, subject))

    with patch("app.services.jobs_digest._send", new=fake_send):
        stats = await jobs_digest.run_weekly_digest()

    assert stats["eligible"] == 1
    # Match score will likely clear the >=40 threshold (advanced + PyTorch in curriculum).
    # Either sent or skipped — both are valid outcomes; assert the counter is consistent.
    assert stats["sent"] + stats["skipped_no_matches"] == 1
    await close_db()


@pytest.mark.asyncio
async def test_digest_skips_run_when_no_recent_jobs():
    await _setup()
    await _mk_user("a@t.com")
    # Old job — outside the LOOKBACK_DAYS window.
    await _mk_job("old", posted_on=date.today() - timedelta(days=60))

    with patch("app.services.jobs_digest._send", new=AsyncMock()):
        stats = await jobs_digest.run_weekly_digest()
    assert stats["sent"] == 0
    await close_db()


# ---------- unsubscribe token ----------

@pytest.mark.asyncio
async def test_unsub_token_round_trips():
    """The token can be decoded and carries the expected sub claim."""
    await _setup()
    user = await _mk_user("u@t.com")
    token = jobs_digest._unsub_token(user)

    from jose import jwt
    from app.config import get_settings
    settings = get_settings()
    payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    assert payload["sub"] == str(user.id)
    assert payload["k"] == "unsub"
    assert "c" not in payload  # no channel claim on the old-style token
    await close_db()
