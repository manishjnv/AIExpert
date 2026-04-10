"""Tests for profile endpoints (Task 5.1).

AC: All four endpoints work; delete cascades; export returns all user data.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import Base, close_db, init_db
import app.db as db_module
from app.auth.jwt import issue_token
from app.models.user import User

import app.models  # noqa: F401


async def _setup():
    await init_db(url="sqlite+aiosqlite:///:memory:")
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _app():
    from app.main import app
    return app


async def _user_token(email="profile@test.com"):
    async with db_module.async_session_factory() as db:
        user = User(email=email, provider="otp", is_admin=False)
        db.add(user)
        await db.flush()
        token = await issue_token(user, db)
        await db.commit()
        return user.id, token


@pytest.mark.asyncio
async def test_get_profile():
    await _setup()
    _, token = await _user_token()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        resp = await c.get("/api/profile", cookies={"session": token})
        assert resp.status_code == 200
        d = resp.json()
        assert d["email"] == "profile@test.com"
        assert d["total_weeks"] == 0
        assert d["active_plan"] is None
    await close_db()


@pytest.mark.asyncio
async def test_patch_profile():
    await _setup()
    _, token = await _user_token()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        resp = await c.patch("/api/profile", json={"name": "New Name", "github_username": "ghuser"}, cookies={"session": token})
        assert resp.status_code == 200
        d = resp.json()
        assert d["name"] == "New Name"
        assert d["github_username"] == "ghuser"

        # Persists
        resp2 = await c.get("/api/profile", cookies={"session": token})
        assert resp2.json()["name"] == "New Name"
    await close_db()


@pytest.mark.asyncio
async def test_delete_profile_cascades():
    await _setup()
    user_id, token = await _user_token("delete@test.com")

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        # Enroll in a plan first
        await c.post("/api/plans", json={"goal": "generalist", "duration": "6mo", "level": "intermediate"}, cookies={"session": token})

        # Delete
        resp = await c.request("DELETE", "/api/profile", json={"confirm": "DELETE"}, cookies={"session": token})
        assert resp.status_code == 204

        # User gone
        async with db_module.async_session_factory() as db:
            user = await db.get(User, user_id)
            assert user is None

    await close_db()


@pytest.mark.asyncio
async def test_delete_profile_wrong_confirm():
    await _setup()
    _, token = await _user_token()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        resp = await c.request("DELETE", "/api/profile", json={"confirm": "WRONG"}, cookies={"session": token})
        assert resp.status_code == 400
    await close_db()


@pytest.mark.asyncio
async def test_export_profile():
    await _setup()
    _, token = await _user_token("export@test.com")
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        # Enroll
        await c.post("/api/plans", json={"goal": "generalist", "duration": "6mo", "level": "intermediate"}, cookies={"session": token})
        # Tick
        await c.patch("/api/progress", json={"week_num": 1, "check_idx": 0, "done": True}, cookies={"session": token})

        resp = await c.get("/api/profile/export", cookies={"session": token})
        assert resp.status_code == 200
        assert "attachment" in resp.headers.get("content-disposition", "")
        data = resp.json()
        assert data["profile"]["email"] == "export@test.com"
        assert len(data["plans"]) == 1
        assert len(data["plans"][0]["progress"]) == 1
    await close_db()
