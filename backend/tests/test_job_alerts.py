"""Per-company job-alert subscription + daily digest tests."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import app.db as db_module
import app.models  # noqa: F401
from app.auth.jwt import issue_token
from app.db import Base, close_db, init_db
from app.models import Job, JobAlertSubscription, JobCompany
from app.models.user import User


async def _setup():
    await init_db(url="sqlite+aiosqlite:///:memory:")
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _app():
    from app.main import app
    return app


async def _mk_user(email: str = "u@t.com") -> tuple[int, str]:
    async with db_module.async_session_factory() as db:
        u = User(email=email, provider="otp", is_admin=False, name=email)
        db.add(u)
        await db.flush()
        token = await issue_token(u, db)
        await db.commit()
        return u.id, token


async def _mk_company(slug: str = "anthropic", name: str = "Anthropic") -> None:
    async with db_module.async_session_factory() as db:
        if not (await db.execute(select(JobCompany).where(JobCompany.slug == slug))).scalar_one_or_none():
            db.add(JobCompany(slug=slug, name=name))
            await db.commit()


async def _mk_job(slug: str, company: str = "anthropic", status: str = "published", ext: str = "e1") -> int:
    async with db_module.async_session_factory() as db:
        j = Job(
            source="greenhouse:" + company, external_id=ext, source_url="http://x", hash=ext,
            status=status, posted_on=date.today(), valid_through=date.today() + timedelta(days=90),
            slug=slug, title="ML Engineer", company_slug=company, designation="ML Engineer",
            country="US", remote_policy="Remote", verified=1,
            data={"tldr": "t", "location": {"city": "SF", "country": "US"}},
        )
        db.add(j)
        await db.commit()
        return j.id


async def _subscribe(uid: int, slug: str) -> None:
    async with db_module.async_session_factory() as db:
        db.add(JobAlertSubscription(user_id=uid, company_slug=slug, channel="email", active=1))
        await db.commit()


@pytest.mark.asyncio
async def test_subscribe_requires_auth():
    await _setup()
    await _mk_company()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.post("/api/jobs/subscribe", json={"company_slug": "anthropic"})
        assert r.status_code == 401
    await close_db()


@pytest.mark.asyncio
async def test_subscribe_list_unsubscribe_flow():
    await _setup()
    _, token = await _mk_user()
    await _mk_company()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.post("/api/jobs/subscribe", json={"company_slug": "anthropic"}, cookies={"auth_token": token})
        assert r.status_code == 200 and r.json()["subscribed"] is True
        # idempotent — second subscribe doesn't error or duplicate
        r2 = await c.post("/api/jobs/subscribe", json={"company_slug": "anthropic"}, cookies={"auth_token": token})
        assert r2.status_code == 200
        subs = (await c.get("/api/jobs/subscriptions", cookies={"auth_token": token})).json()["subscriptions"]
        assert len(subs) == 1
        assert subs[0]["company_slug"] == "anthropic" and subs[0]["company_name"] == "Anthropic"
        # unsubscribe
        r3 = await c.post("/api/jobs/unsubscribe", json={"company_slug": "anthropic"}, cookies={"auth_token": token})
        assert r3.status_code == 200 and r3.json()["subscribed"] is False
        assert (await c.get("/api/jobs/subscriptions", cookies={"auth_token": token})).json()["subscriptions"] == []
    await close_db()


@pytest.mark.asyncio
async def test_subscribe_unknown_company_404():
    await _setup()
    _, token = await _mk_user()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.post("/api/jobs/subscribe", json={"company_slug": "nope-co"}, cookies={"auth_token": token})
        assert r.status_code == 404
    await close_db()


@pytest.mark.asyncio
async def test_subscribe_to_company_with_jobs_but_no_company_row():
    """A company known only via Job.company_slug (no JobCompany row) is still subscribable."""
    await _setup()
    _, token = await _mk_user()
    await _mk_job(slug="x1", company="figure", ext="f1")  # no JobCompany('figure')
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.post("/api/jobs/subscribe", json={"company_slug": "figure"}, cookies={"auth_token": token})
        assert r.status_code == 200
    await close_db()


@pytest.mark.asyncio
async def test_digest_sends_only_to_matching_subscribers():
    await _setup()
    uid, _ = await _mk_user("sub@t.com")
    await _mk_company("anthropic", "Anthropic")
    await _mk_company("openai", "OpenAI")
    await _mk_job(slug="a1", company="anthropic", ext="a1")
    await _mk_job(slug="o1", company="openai", ext="o1")
    await _subscribe(uid, "anthropic")  # only follows anthropic

    from app.services.job_alerts_digest import run_job_alerts_digest
    since = datetime.now(timezone.utc) - timedelta(days=1)
    stats = await run_job_alerts_digest(since)
    assert stats["new_jobs"] >= 2
    assert stats["subscribers"] == 1
    assert stats["sent"] == 1   # DEV mode (no smtp_host) → _send no-ops, still counts as sent
    await close_db()


@pytest.mark.asyncio
async def test_digest_no_send_when_no_new_jobs():
    await _setup()
    uid, _ = await _mk_user()
    await _mk_company()
    await _mk_job(slug="a1", company="anthropic", ext="a1")
    await _subscribe(uid, "anthropic")

    from app.services.job_alerts_digest import run_job_alerts_digest
    since = datetime.now(timezone.utc) + timedelta(days=1)  # window starts in the future
    stats = await run_job_alerts_digest(since)
    assert stats["new_jobs"] == 0 and stats["sent"] == 0
    await close_db()


@pytest.mark.asyncio
async def test_digest_skips_unpublished_jobs():
    await _setup()
    uid, _ = await _mk_user()
    await _mk_company()
    await _mk_job(slug="d1", company="anthropic", status="draft", ext="d1")  # not published
    await _subscribe(uid, "anthropic")

    from app.services.job_alerts_digest import run_job_alerts_digest
    since = datetime.now(timezone.utc) - timedelta(days=1)
    stats = await run_job_alerts_digest(since)
    assert stats["new_jobs"] == 0 and stats["sent"] == 0
    await close_db()
