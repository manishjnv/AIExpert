"""Tests for auth router — /me, /logout, Google endpoints (Tasks 3.3 + 3.6).

AC 3.3: Google login redirects (501 when not configured)
AC 3.6: /me returns user, /logout revokes session, /me then returns 401
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


def _get_app():
    """Import the real app — must be called after init_db."""
    from app.main import app
    return app


@pytest.mark.asyncio
async def test_me_returns_user():
    await _setup()
    app = _get_app()

    async with db_module.async_session_factory() as db:
        user = User(email="me@test.com", name="Test User", provider="otp", is_admin=False)
        db.add(user)
        await db.flush()
        token = await issue_token(user, db)
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/auth/me", cookies={"session": token})
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "me@test.com"
        assert data["name"] == "Test User"
        assert data["is_admin"] is False

    await close_db()


@pytest.mark.asyncio
async def test_me_without_cookie_returns_401():
    await _setup()
    app = _get_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/auth/me")
        assert resp.status_code == 401

    await close_db()


@pytest.mark.asyncio
async def test_logout_then_me_returns_401():
    await _setup()
    app = _get_app()

    async with db_module.async_session_factory() as db:
        user = User(email="logout@test.com", provider="otp", is_admin=False)
        db.add(user)
        await db.flush()
        token = await issue_token(user, db)
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Logout
        resp = await client.post("/api/auth/logout", cookies={"session": token})
        assert resp.status_code == 204

        # /me should now fail
        resp = await client.get("/api/auth/me", cookies={"session": token})
        assert resp.status_code == 401

    await close_db()


@pytest.mark.asyncio
async def test_google_login_returns_501_when_not_configured():
    """When google_client_id is empty, /google/login returns 501."""
    await _setup()
    app = _get_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/auth/google/login")
        assert resp.status_code == 501

    await close_db()
