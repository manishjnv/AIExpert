"""Tests for plan enrollment, progress, and migration (Tasks 4.2–4.5).

AC 4.2: Re-enrolling archives old plan; /api/plan/default returns default without auth
AC 4.3: Fresh plan returns all checks done=false; /api/plan-versions returns version history
AC 4.4: Progress tick persists; unchecking clears completed_at
AC 4.5: Anonymous progress migrates on sign-in; server wins on conflicts
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import Base, close_db, init_db
import app.db as db_module
from app.auth.jwt import issue_token
from app.models.user import User
from app.models.plan import UserPlan

import app.models  # noqa: F401


async def _setup():
    await init_db(url="sqlite+aiosqlite:///:memory:")
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _get_app():
    from app.main import app
    return app


async def _create_user_and_token(email="test@plans.com", is_admin=False):
    async with db_module.async_session_factory() as db:
        user = User(email=email, provider="otp", is_admin=is_admin)
        db.add(user)
        await db.flush()
        token = await issue_token(user, db)
        await db.commit()
        return user.id, token


# ---- 4.2 ----

@pytest.mark.asyncio
async def test_plan_default_no_auth():
    await _setup()
    app = _get_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/plan/default")
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"] == "generalist_6mo_intermediate"
        assert len(data["months"]) == 6
    await close_db()


@pytest.mark.asyncio
async def test_enroll_creates_active_plan():
    await _setup()
    app = _get_app()
    _, token = await _create_user_and_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/plans", json={"goal": "generalist", "duration": "6mo", "level": "intermediate"}, cookies={"auth_token": token})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "active"
        assert data["template_key"] == "generalist_6mo_intermediate"
        assert len(data["months"]) == 6
    await close_db()


@pytest.mark.asyncio
async def test_re_enroll_archives_old_plan():
    await _setup()
    app = _get_app()
    user_id, token = await _create_user_and_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # First enrollment
        resp1 = await c.post("/api/plans", json={"goal": "generalist", "duration": "6mo", "level": "intermediate"}, cookies={"auth_token": token})
        plan1_id = resp1.json()["id"]

        # Re-enroll
        resp2 = await c.post("/api/plans", json={"goal": "generalist", "duration": "6mo", "level": "intermediate"}, cookies={"auth_token": token})
        plan2_id = resp2.json()["id"]
        assert plan2_id != plan1_id

    # Verify old plan is archived
    from sqlalchemy import select
    async with db_module.async_session_factory() as db:
        old = await db.get(UserPlan, plan1_id)
        assert old.status == "archived"
        new = await db.get(UserPlan, plan2_id)
        assert new.status == "active"

    await close_db()


# ---- 4.3 ----

@pytest.mark.asyncio
async def test_active_plan_all_checks_false():
    await _setup()
    app = _get_app()
    _, token = await _create_user_and_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/api/plans", json={"goal": "generalist", "duration": "6mo", "level": "intermediate"}, cookies={"auth_token": token})
        resp = await c.get("/api/plans/active", cookies={"auth_token": token})
        assert resp.status_code == 200
        data = resp.json()
        for m in data["months"]:
            for w in m["weeks"]:
                for ch in w["checks"]:
                    assert ch["done"] is False
    await close_db()


# ---- 4.4 ----

@pytest.mark.asyncio
async def test_progress_tick_persists():
    await _setup()
    app = _get_app()
    _, token = await _create_user_and_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/api/plans", json={"goal": "generalist", "duration": "6mo", "level": "intermediate"}, cookies={"auth_token": token})

        # Tick a checkbox
        resp = await c.patch("/api/progress", json={"week_num": 1, "check_idx": 0, "done": True}, cookies={"auth_token": token})
        assert resp.status_code == 204

        # Verify it persisted
        resp = await c.get("/api/plans/active", cookies={"auth_token": token})
        w1 = resp.json()["months"][0]["weeks"][0]
        assert w1["checks"][0]["done"] is True
        assert w1["checks"][0]["completed_at"] is not None

        # Uncheck
        resp = await c.patch("/api/progress", json={"week_num": 1, "check_idx": 0, "done": False}, cookies={"auth_token": token})
        assert resp.status_code == 204

        resp = await c.get("/api/plans/active", cookies={"auth_token": token})
        w1 = resp.json()["months"][0]["weeks"][0]
        assert w1["checks"][0]["done"] is False
        assert w1["checks"][0]["completed_at"] is None

    await close_db()


# ---- 4.5 ----

@pytest.mark.asyncio
async def test_migrate_progress():
    await _setup()
    app = _get_app()
    _, token = await _create_user_and_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/api/plans", json={"goal": "generalist", "duration": "6mo", "level": "intermediate"}, cookies={"auth_token": token})

        # Migrate localStorage blob
        blob = {"w1_0": True, "w1_1": True, "w2_0": True}
        resp = await c.post("/api/progress/migrate", json={"progress": blob}, cookies={"auth_token": token})
        assert resp.status_code == 200
        data = resp.json()
        w1 = data["months"][0]["weeks"][0]
        assert w1["checks"][0]["done"] is True
        assert w1["checks"][1]["done"] is True
        w2 = data["months"][0]["weeks"][1]
        assert w2["checks"][0]["done"] is True

    await close_db()


@pytest.mark.asyncio
async def test_migrate_server_wins():
    """Server-side done=True is not overwritten by client done=False."""
    await _setup()
    app = _get_app()
    _, token = await _create_user_and_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/api/plans", json={"goal": "generalist", "duration": "6mo", "level": "intermediate"}, cookies={"auth_token": token})

        # Set a tick server-side
        await c.patch("/api/progress", json={"week_num": 1, "check_idx": 0, "done": True}, cookies={"auth_token": token})

        # Migrate with that key as False — server should win
        blob = {"w1_0": False}
        resp = await c.post("/api/progress/migrate", json={"progress": blob}, cookies={"auth_token": token})
        w1 = resp.json()["months"][0]["weeks"][0]
        assert w1["checks"][0]["done"] is True  # server wins

    await close_db()
