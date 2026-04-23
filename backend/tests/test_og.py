"""OG card route tests (SEO-11).

Asserts route availability + PNG validity + 1200x630 dimensions + 404 on
bad inputs. Cache hit behavior is not tested here because /data is
writable on the dev host but not necessarily in the test fixture — the
route is correct either way (cache write is non-fatal).
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

import app.db as db_module
import app.models  # noqa: F401
from app.db import Base, close_db, init_db


async def _setup():
    await init_db(url="sqlite+aiosqlite:///:memory:")
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _app():
    from app.main import app
    return app


def _assert_png_1200x630(body: bytes) -> None:
    img = Image.open(io.BytesIO(body))
    assert img.format == "PNG"
    assert img.size == (1200, 630)


@pytest.mark.asyncio
async def test_og_course_generalist_200_1200x630(monkeypatch, tmp_path):
    # Redirect cache root to tmp so we don't need /data writable
    monkeypatch.setattr("app.routers.og.CACHE_ROOT", tmp_path / "og-cache")
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/og/course/generalist.png")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        _assert_png_1200x630(r.content)
    await close_db()


@pytest.mark.asyncio
async def test_og_course_unknown_name_404(monkeypatch, tmp_path):
    monkeypatch.setattr("app.routers.og.CACHE_ROOT", tmp_path / "og-cache")
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/og/course/nonexistent.png")
        assert r.status_code == 404
    await close_db()


@pytest.mark.asyncio
@pytest.mark.parametrize("track", ["generalist", "ai-engineer", "ml-engineer", "data-scientist"])
async def test_og_roadmap_known_tracks_200(monkeypatch, tmp_path, track):
    monkeypatch.setattr("app.routers.og.CACHE_ROOT", tmp_path / "og-cache")
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get(f"/og/roadmap/{track}.png")
        assert r.status_code == 200
        _assert_png_1200x630(r.content)
    await close_db()


@pytest.mark.asyncio
async def test_og_roadmap_unknown_track_404(monkeypatch, tmp_path):
    monkeypatch.setattr("app.routers.og.CACHE_ROOT", tmp_path / "og-cache")
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/og/roadmap/bogus-track.png")
        assert r.status_code == 404
    await close_db()


@pytest.mark.asyncio
async def test_og_blog_post_01_200(monkeypatch, tmp_path):
    """POST_01 is hardcoded in routers/blog.py — always renders."""
    monkeypatch.setattr("app.routers.og.CACHE_ROOT", tmp_path / "og-cache")
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: False)
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/og/blog/01.png")
        assert r.status_code == 200
        _assert_png_1200x630(r.content)
    await close_db()


@pytest.mark.asyncio
async def test_og_blog_unknown_slug_404(monkeypatch, tmp_path):
    monkeypatch.setattr("app.routers.og.CACHE_ROOT", tmp_path / "og-cache")
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: False)
    monkeypatch.setattr("app.services.blog_publisher.list_published", lambda: [])
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/og/blog/no-such-post.png")
        assert r.status_code == 404
    await close_db()


@pytest.mark.asyncio
async def test_og_blog_malformed_slug_404(monkeypatch, tmp_path):
    """Uppercase / special chars rejected by _SLUG_RE before DB lookup."""
    monkeypatch.setattr("app.routers.og.CACHE_ROOT", tmp_path / "og-cache")
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/og/blog/BAD_SLUG.png")
        assert r.status_code == 404
    await close_db()


@pytest.mark.asyncio
async def test_og_jobs_published_200(monkeypatch, tmp_path):
    """Seed one published job, confirm OG card renders."""
    from datetime import date, timedelta

    from app.models.job import Job

    monkeypatch.setattr("app.routers.og.CACHE_ROOT", tmp_path / "og-cache")
    await _setup()
    async with db_module.async_session_factory() as s:
        s.add(Job(
            source="greenhouse:acme", external_id="e1",
            source_url="https://x/y", hash="h" * 64,
            status="published",
            posted_on=date.today(), valid_through=date.today() + timedelta(days=30),
            slug="applied-ai-at-acme-abcd",
            title="Applied AI Engineer", company_slug="acme",
            designation="AI Engineer", country="US",
            data={"company": {"name": "Acme AI"},
                  "location": {"city": "SF", "country": "US", "remote_policy": "hybrid"},
                  "employment": {"salary": {"disclosed": True, "currency": "USD",
                                            "min": 180000, "max": 240000}}},
        ))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/og/jobs/applied-ai-at-acme-abcd.png")
        assert r.status_code == 200
        _assert_png_1200x630(r.content)
    await close_db()


@pytest.mark.asyncio
async def test_og_jobs_draft_not_served_404(monkeypatch, tmp_path):
    from datetime import date, timedelta

    from app.models.job import Job

    monkeypatch.setattr("app.routers.og.CACHE_ROOT", tmp_path / "og-cache")
    await _setup()
    async with db_module.async_session_factory() as s:
        s.add(Job(
            source="greenhouse:acme", external_id="e2",
            source_url="https://x/y", hash="h" * 64,
            status="draft",
            posted_on=date.today(), valid_through=date.today() + timedelta(days=30),
            slug="draft-role-xyz",
            title="Draft Role", company_slug="acme",
            designation="AI Engineer", country="US",
            data={},
        ))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/og/jobs/draft-role-xyz.png")
        assert r.status_code == 404
    await close_db()


def test_og_renderer_produces_valid_png_without_db():
    """Unit test against the renderer directly — no HTTP, no DB."""
    from app.services import og_render

    body = og_render.render_course()
    _assert_png_1200x630(body)

    body = og_render.render_roadmap("ai-engineer")
    assert body is not None
    _assert_png_1200x630(body)

    assert og_render.render_roadmap("not-a-track") is None


def test_og_cache_hit_on_second_call(tmp_path):
    """Writing a fake PNG to the expected cache path should be served
    without re-rendering. Uses the renderer utility directly to produce
    a tiny valid PNG, then hits the HTTP route."""
    import asyncio

    from app.routers import og as og_router

    og_router.CACHE_ROOT = tmp_path / "og-cache"
    p = og_router._cache_path("course", "generalist")
    p.parent.mkdir(parents=True, exist_ok=True)
    # Minimal 1x1 PNG we can distinguish from a fresh 1200x630 render
    marker = Image.new("RGB", (1, 1), (255, 0, 0))
    buf = io.BytesIO()
    marker.save(buf, format="PNG")
    marker_bytes = buf.getvalue()
    p.write_bytes(marker_bytes)

    async def _go():
        await _setup()
        async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
            r = await c.get("/og/course/generalist.png")
            assert r.status_code == 200
            assert r.content == marker_bytes
            assert r.headers.get("x-cache") == "HIT"
        await close_db()

    asyncio.run(_go())
