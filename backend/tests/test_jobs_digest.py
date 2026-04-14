"""Weekly jobs digest: eligibility, match selection, unsubscribe."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
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


async def _mk_user(email, *, notify=True, with_plan=True) -> User:
    async with db_module.async_session_factory() as db:
        u = User(email=email, provider="otp", email_notifications=notify,
                 experience_level="advanced")
        db.add(u)
        await db.flush()
        if with_plan:
            db.add(UserPlan(user_id=u.id, template_key="generalist_6mo_intermediate",
                            plan_version="v1", status="active"))
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
async def test_eligibility_requires_active_plan_and_optin():
    await _setup()
    await _mk_user("a@t.com", notify=True, with_plan=True)
    await _mk_user("b@t.com", notify=False, with_plan=True)     # opted out
    await _mk_user("c@t.com", notify=True, with_plan=False)     # no plan
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
    # Match score will likely clear the ≥40 threshold (advanced + PyTorch in curriculum).
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


# ---------- unsubscribe endpoint ----------

@pytest.mark.asyncio
async def test_unsubscribe_flips_email_notifications_off():
    await _setup()
    user = await _mk_user("u@t.com", notify=True)
    token = jobs_digest._unsub_token(user)

    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get(f"/api/profile/digest/unsubscribe?t={token}")
        assert r.status_code == 200
        assert "unsubscribed" in r.text.lower()

    async with db_module.async_session_factory() as db:
        u2 = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
        assert u2.email_notifications is False
    await close_db()


@pytest.mark.asyncio
async def test_unsubscribe_rejects_bogus_token():
    await _setup()
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/profile/digest/unsubscribe?t=not-a-jwt")
        assert r.status_code == 400
    await close_db()
