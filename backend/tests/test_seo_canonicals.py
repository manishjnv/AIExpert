"""SEO-13 canonicals — every SSR route must emit exactly one
<link rel="canonical"> in <head>. Blog-index canonical is covered in
test_blog.py; this file covers the non-blog SSR routes: /leaderboard,
/verify, /profile/{user_id}."""

from __future__ import annotations

import re

import pytest
from httpx import ASGITransport, AsyncClient

import app.db as db_module
import app.models  # noqa: F401
from app.db import Base, close_db, init_db
from app.models.user import User


_CANONICAL_RE = re.compile(r'<link\s+rel="canonical"\s+href="([^"]+)"')


async def _setup():
    await init_db(url="sqlite+aiosqlite:///:memory:")
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _app():
    from app.main import app
    return app


@pytest.mark.asyncio
async def test_verify_index_has_exactly_one_canonical():
    """/verify (the lookup form) emits one canonical pointing at itself."""
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/verify")
        assert r.status_code == 200
        canonicals = _CANONICAL_RE.findall(r.text)
        assert len(canonicals) == 1, f"expected 1 canonical, got {canonicals}"
        assert canonicals[0].endswith("/verify")
    await close_db()


@pytest.mark.asyncio
async def test_leaderboard_has_exactly_one_canonical():
    """/leaderboard emits one canonical pointing at itself even when the
    table is empty (no public-profile users yet)."""
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/leaderboard")
        assert r.status_code == 200
        canonicals = _CANONICAL_RE.findall(r.text)
        assert len(canonicals) == 1, f"expected 1 canonical, got {canonicals}"
        assert canonicals[0].endswith("/leaderboard")
    await close_db()


@pytest.mark.asyncio
async def test_public_profile_has_exactly_one_canonical():
    """/profile/{user_id} emits one canonical pointing at the user's own
    profile URL. Requires a user with public_profile=True."""
    await _setup()
    async with db_module.async_session_factory() as db:
        user = User(
            email="pub@test.com",
            name="Public Tester",
            provider="otp",
            public_profile=True,
        )
        db.add(user)
        await db.flush()
        uid = user.id
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get(f"/profile/{uid}")
        assert r.status_code == 200
        canonicals = _CANONICAL_RE.findall(r.text)
        assert len(canonicals) == 1, f"expected 1 canonical, got {canonicals}"
        assert canonicals[0].endswith(f"/profile/{uid}")
    await close_db()
