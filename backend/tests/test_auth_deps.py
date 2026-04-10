"""Tests for auth dependencies (Task 3.2).

AC: 401 without cookie, 200 with valid cookie, 403 for non-admin on admin route.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from fastapi import FastAPI, Depends

from app.db import Base, close_db, init_db
import app.db as db_module
from app.auth.jwt import issue_token
from app.auth.deps import get_current_user, get_current_admin
from app.db import get_db
from app.models.user import User

import app.models  # noqa: F401


def _make_app() -> FastAPI:
    """Build a minimal FastAPI app with protected test routes."""
    test_app = FastAPI()

    @test_app.get("/protected")
    async def protected(user: User = Depends(get_current_user)):
        return {"id": user.id, "email": user.email}

    @test_app.get("/admin-only")
    async def admin_only(user: User = Depends(get_current_admin)):
        return {"id": user.id, "is_admin": user.is_admin}

    return test_app


async def _setup():
    await init_db(url="sqlite+aiosqlite:///:memory:")
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest.mark.asyncio
async def test_401_without_cookie():
    await _setup()
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/protected")
        assert resp.status_code == 401
    await close_db()


@pytest.mark.asyncio
async def test_200_with_valid_cookie():
    await _setup()
    app = _make_app()

    # Create a user and issue a token
    async with db_module.async_session_factory() as db:
        user = User(email="u@test.com", provider="otp", is_admin=False)
        db.add(user)
        await db.flush()
        token = await issue_token(user, db)
        await db.commit()
        user_id = user.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/protected", cookies={"auth_token": token})
        assert resp.status_code == 200
        assert resp.json()["id"] == user_id
        assert resp.json()["email"] == "u@test.com"

    await close_db()


@pytest.mark.asyncio
async def test_403_non_admin_on_admin_route():
    await _setup()
    app = _make_app()

    async with db_module.async_session_factory() as db:
        user = User(email="regular@test.com", provider="otp", is_admin=False)
        db.add(user)
        await db.flush()
        token = await issue_token(user, db)
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/admin-only", cookies={"auth_token": token})
        assert resp.status_code == 403

    await close_db()


@pytest.mark.asyncio
async def test_200_admin_on_admin_route():
    await _setup()
    app = _make_app()

    async with db_module.async_session_factory() as db:
        user = User(email="admin@test.com", provider="otp", is_admin=True)
        db.add(user)
        await db.flush()
        token = await issue_token(user, db)
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/admin-only", cookies={"auth_token": token})
        assert resp.status_code == 200
        assert resp.json()["is_admin"] is True

    await close_db()


@pytest.mark.asyncio
async def test_401_with_garbage_cookie():
    await _setup()
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/protected", cookies={"auth_token": "garbage.token.here"})
        assert resp.status_code == 401
    await close_db()
