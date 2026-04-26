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


# ---------------------------------------------------------------------------
# SEO-27: Blog paginated + topic hub canonical tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_blog_page2_canonical_is_page2(monkeypatch):
    """/blog?page=2 canonical URL must include page=2 (not just /blog)."""
    # Create enough fake posts to have 2 pages
    fake = []
    for i in range(25):
        slug = f"{i + 2:02d}-fake-post-{i}"
        fake.append({
            "slug": slug,
            "title": f"Post {i}",
            "og_description": f"Desc {i}",
            "lede": "",
            "body_html": "<p>Body</p>",
            "published": f"2026-01-{i + 1:02d}",
            "tags": [],
            "target_query": "",
        })
    fake.sort(key=lambda p: p["published"], reverse=True)

    monkeypatch.setattr("app.services.blog_publisher.list_published", lambda: fake)
    by_slug = {p["slug"]: p for p in fake}
    monkeypatch.setattr("app.services.blog_publisher.load_published", lambda s: by_slug.get(s))
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: True)
    from app.routers.blog import _load_pillar_config
    _load_pillar_config.cache_clear()

    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/blog?page=2")
        assert r.status_code == 200
        canonicals = _CANONICAL_RE.findall(r.text)
        assert len(canonicals) == 1, f"expected 1 canonical, got {canonicals}"
        assert "page=2" in canonicals[0]
    await close_db()


@pytest.mark.asyncio
async def test_blog_topic_canonical(monkeypatch):
    """/blog/topic/{slug} emits a canonical pointing at the topic URL."""
    monkeypatch.setattr("app.services.blog_publisher.list_published", lambda: [])
    monkeypatch.setattr("app.services.blog_publisher.load_published", lambda s: None)
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: True)
    from app.routers import blog as blog_module
    from app.routers.blog import _load_pillar_config
    _load_pillar_config.cache_clear()

    monkeypatch.setattr(blog_module, "_load_pillar_config", lambda: {
        "version": 1,
        "active_pills": [
            {
                "slug": "career-paths",
                "label": "Career Paths",
                "intro": "Career intro.",
                "matches": {"tags_any": ["career-guide"]},
            }
        ],
        "start_here": [],
    })
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/blog/topic/career-paths")
        assert r.status_code == 200
        canonicals = _CANONICAL_RE.findall(r.text)
        assert len(canonicals) == 1, f"expected 1 canonical, got {canonicals}"
        assert "/blog/topic/career-paths" in canonicals[0]
    await close_db()


@pytest.mark.asyncio
async def test_sitemap_pages_includes_topic_urls(monkeypatch):
    """/sitemap-pages.xml includes /blog/topic/{slug} for each active pillar."""
    monkeypatch.setattr("app.services.blog_publisher.list_published", lambda: [])
    monkeypatch.setattr("app.services.blog_publisher.load_published", lambda s: None)
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: True)
    from app.routers import blog as blog_module
    from app.routers.blog import _load_pillar_config
    _load_pillar_config.cache_clear()

    monkeypatch.setattr(blog_module, "_load_pillar_config", lambda: {
        "version": 1,
        "active_pills": [
            {
                "slug": "career-paths",
                "label": "Career Paths",
                "intro": "Intro.",
                "matches": {"tags_any": ["career-guide"]},
            }
        ],
        "start_here": [],
    })
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/sitemap-pages.xml")
        assert r.status_code == 200
        assert "/blog/topic/career-paths" in r.text
    await close_db()
