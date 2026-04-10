"""Tests for share pages (Phase 9).

AC 9.1: Page loads; OG tags present; no private data exposed
AC 9.2: SVG loads and is valid; cached 1 hour
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import Base, close_db, init_db
import app.db as db_module
from app.models.user import User

import app.models  # noqa: F401


async def _setup():
    await init_db(url="sqlite+aiosqlite:///:memory:")
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _app():
    from app.main import app
    return app


async def _create_user():
    async with db_module.async_session_factory() as db:
        user = User(email="share@test.com", name="Jane Doe", provider="otp", is_admin=False)
        db.add(user)
        await db.flush()
        await db.commit()
        return user.id


@pytest.mark.asyncio
async def test_share_page_loads():
    await _setup()
    user_id = await _create_user()
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get(f"/share/{user_id}/month-1")
        assert resp.status_code == 200
        html = resp.text
        assert "og:title" in html
        assert "og:image" in html
        assert "Jane" in html  # first name only
        assert "Doe" not in html  # last name NOT exposed
        assert "share@test.com" not in html  # email NOT exposed
    await close_db()


@pytest.mark.asyncio
async def test_share_page_404_bad_milestone():
    await _setup()
    user_id = await _create_user()
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get(f"/share/{user_id}/nonexistent")
        assert resp.status_code == 404
    await close_db()


@pytest.mark.asyncio
async def test_og_svg_loads():
    await _setup()
    user_id = await _create_user()
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get(f"/share/{user_id}/month-1/og.svg")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/svg+xml"
        assert "Cache-Control" in resp.headers
        assert "3600" in resp.headers["Cache-Control"]
        assert "<svg" in resp.text
        assert "Jane" in resp.text
    await close_db()


@pytest.mark.asyncio
async def test_share_page_no_auth_required():
    """Share pages are public — no session cookie needed."""
    await _setup()
    user_id = await _create_user()
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        # No cookies
        resp = await c.get(f"/share/{user_id}/capstone")
        assert resp.status_code == 200
        assert "AI Generalist Roadmap Complete" in resp.text
    await close_db()
