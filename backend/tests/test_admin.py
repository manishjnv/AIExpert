"""Tests for admin panel (Phase 10).

AC 10.1: Non-admin gets 403; admin gets the data
AC 10.2: Admin HTML pages load
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


async def _user_token(email, is_admin=False):
    async with db_module.async_session_factory() as db:
        user = User(email=email, provider="otp", is_admin=is_admin)
        db.add(user)
        await db.flush()
        token = await issue_token(user, db)
        await db.commit()
        return user.id, token


@pytest.mark.asyncio
async def test_non_admin_gets_403():
    await _setup()
    _, token = await _user_token("regular@test.com", is_admin=False)
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get("/admin/api/dashboard", cookies={"auth_token": token})
        assert resp.status_code == 403
    await close_db()


@pytest.mark.asyncio
async def test_admin_dashboard_api():
    await _setup()
    _, token = await _user_token("admin@test.com", is_admin=True)
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get("/admin/api/dashboard", cookies={"auth_token": token})
        assert resp.status_code == 200
        d = resp.json()
        assert "total_users" in d
        assert "dau" in d
        assert "wau" in d
        assert "mau" in d
    await close_db()


@pytest.mark.asyncio
async def test_admin_users_api():
    await _setup()
    _, token = await _user_token("admin2@test.com", is_admin=True)
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get("/admin/api/users", cookies={"auth_token": token})
        assert resp.status_code == 200
        d = resp.json()
        assert "users" in d
        assert d["total"] >= 1
    await close_db()


@pytest.mark.asyncio
async def test_admin_proposals_api():
    await _setup()
    _, token = await _user_token("admin3@test.com", is_admin=True)
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get("/admin/api/proposals", cookies={"auth_token": token})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
    await close_db()


@pytest.mark.asyncio
async def test_admin_dashboard_html():
    await _setup()
    _, token = await _user_token("adminhtml@test.com", is_admin=True)
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get("/admin/", cookies={"auth_token": token})
        assert resp.status_code == 200
        assert "Dashboard" in resp.text
        assert "Total Users" in resp.text
    await close_db()


@pytest.mark.asyncio
async def test_admin_users_html():
    await _setup()
    _, token = await _user_token("adminhtml2@test.com", is_admin=True)
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get("/admin/users", cookies={"auth_token": token})
        assert resp.status_code == 200
        assert "Users" in resp.text
    await close_db()


@pytest.mark.asyncio
async def test_admin_proposals_html():
    await _setup()
    _, token = await _user_token("adminhtml3@test.com", is_admin=True)
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get("/admin/proposals", cookies={"auth_token": token})
        assert resp.status_code == 200
        assert "Proposals" in resp.text
    await close_db()
