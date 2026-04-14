"""Admin review-queue endpoint tests: auth, publish, reject, bulk-publish gate."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import app.db as db_module
import app.models  # noqa: F401
from app.auth.jwt import issue_token
from app.db import Base, close_db, init_db
from app.models import Job, JobCompany, JobSource
from app.models.user import User


async def _setup():
    await init_db(url="sqlite+aiosqlite:///:memory:")
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _app():
    from app.main import app
    return app


async def _mk_user(email: str, is_admin: bool):
    async with db_module.async_session_factory() as db:
        u = User(email=email, provider="otp", is_admin=is_admin, name=email)
        db.add(u)
        await db.flush()
        token = await issue_token(u, db)
        await db.commit()
        return u.id, token


async def _mk_job(source: str = "greenhouse:anthropic", tier: int = 1, bulk: int = 1,
                  status: str = "draft", slug: str = "job-1", ext: str = "gh-1") -> int:
    async with db_module.async_session_factory() as db:
        src = (await db.execute(select(JobSource).where(JobSource.key == source))).scalar_one_or_none()
        if not src:
            db.add(JobSource(key=source, kind=source.split(":")[0], label="X", tier=tier, enabled=1, bulk_approve=bulk))
        if not (await db.execute(select(JobCompany).where(JobCompany.slug == "anthropic"))).scalar_one_or_none():
            db.add(JobCompany(slug="anthropic", name="Anthropic"))
        j = Job(
            source=source, external_id=ext, source_url="http://x", hash=ext, status=status,
            posted_on=date.today(), valid_through=date.today() + timedelta(days=45),
            slug=slug, title="ML Engineer", company_slug="anthropic", designation="ML Engineer",
            country="US", remote_policy="Hybrid", verified=1,
            data={"tldr": "t", "must_have_skills": [], "employment": {}},
        )
        db.add(j)
        await db.commit()
        return j.id


@pytest.mark.asyncio
async def test_non_admin_rejected():
    await _setup()
    _, token = await _mk_user("u@t.com", is_admin=False)
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/admin/jobs/api/queue", cookies={"auth_token": token})
        assert r.status_code == 403
    await close_db()


@pytest.mark.asyncio
async def test_queue_lists_drafts():
    await _setup()
    _, token = await _mk_user("a@t.com", is_admin=True)
    await _mk_job()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/admin/jobs/api/queue", cookies={"auth_token": token})
        assert r.status_code == 200
        d = r.json()
        assert d["counts"].get("draft") == 1
        assert len(d["items"]) == 1
    await close_db()


@pytest.mark.asyncio
async def test_publish_flips_status_and_stamps_reviewer():
    await _setup()
    _, token = await _mk_user("reviewer@t.com", is_admin=True)
    job_id = await _mk_job()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.post(f"/admin/jobs/api/{job_id}/publish", cookies={"auth_token": token})
        assert r.status_code == 200
        assert r.json()["status"] == "published"
    async with db_module.async_session_factory() as db:
        job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one()
        assert job.status == "published"
        assert job.last_reviewed_by == "reviewer@t.com"
        assert job.last_reviewed_on == date.today()
    await close_db()


@pytest.mark.asyncio
async def test_reject_requires_valid_reason():
    await _setup()
    _, token = await _mk_user("a@t.com", is_admin=True)
    job_id = await _mk_job()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r1 = await c.post(f"/admin/jobs/api/{job_id}/reject",
                          json={"reason": "bogus"}, cookies={"auth_token": token})
        assert r1.status_code == 400
        r2 = await c.post(f"/admin/jobs/api/{job_id}/reject",
                          json={"reason": "off_topic"}, cookies={"auth_token": token})
        assert r2.status_code == 200
        assert r2.json()["reason"] == "off_topic"
    await close_db()


@pytest.mark.asyncio
async def test_bulk_publish_tier1_only():
    """Tier-2 sources (or tier-1 without bulk_approve) cannot be bulk-published."""
    await _setup()
    _, token = await _mk_user("a@t.com", is_admin=True)
    t1 = await _mk_job(source="greenhouse:anthropic", tier=1, bulk=1, slug="t1", ext="a")
    t2 = await _mk_job(source="yc:aggregate", tier=2, bulk=0, slug="t2", ext="b")
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.post("/admin/jobs/api/bulk-publish",
                         json={"ids": [t1, t2]}, cookies={"auth_token": token})
        assert r.status_code == 400   # Tier-2 in batch blocks the whole call
        # Tier-1 alone works.
        r2 = await c.post("/admin/jobs/api/bulk-publish",
                          json={"ids": [t1]}, cookies={"auth_token": token})
        assert r2.status_code == 200
        assert r2.json()["published"] == 1
    await close_db()


@pytest.mark.asyncio
async def test_blocklist_company():
    await _setup()
    _, token = await _mk_user("a@t.com", is_admin=True)
    await _mk_job()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.post("/admin/jobs/api/companies/anthropic/blocklist",
                         json={"blocked": True, "reason": "test"},
                         cookies={"auth_token": token})
        assert r.status_code == 200
        assert r.json()["blocklisted"] is True
    async with db_module.async_session_factory() as db:
        co = (await db.execute(select(JobCompany).where(JobCompany.slug == "anthropic"))).scalar_one()
        assert co.blocklisted == 1
        assert co.blocklist_reason == "test"
    await close_db()
