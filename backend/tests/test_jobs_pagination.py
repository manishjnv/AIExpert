"""SSR jobs hub pagination tests (SEO-10)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

import app.db as db_module
import app.models  # noqa: F401
from app.db import Base, close_db, init_db
from app.models.job import Job


async def _setup():
    await init_db(url="sqlite+aiosqlite:///:memory:")
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _app():
    from app.main import app
    return app


async def _seed_published_jobs(n: int) -> None:
    """Insert n published Job rows with stable ordering (posted_on descending
    by inverse index)."""
    base_day = date.today()
    async with db_module.async_session_factory() as s:
        for i in range(n):
            posted = base_day - timedelta(days=i)
            s.add(Job(
                source="greenhouse:test", external_id=f"e{i}",
                source_url=f"https://test/{i}", hash=("h" * 60) + f"{i:04d}",
                status="published",
                posted_on=posted, valid_through=posted + timedelta(days=30),
                slug=f"role-{i:04d}-at-test-{i:04d}",
                title=f"Role {i}", company_slug="test",
                designation="AI Engineer", country="US",
                data={"company": {"name": "Test Co"}},
            ))
        await s.commit()


@pytest.mark.asyncio
async def test_page_1_renders_canonical_no_query():
    await _setup()
    await _seed_published_jobs(60)
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/jobs")
        assert r.status_code == 200
        html = r.text
        # Canonical points at /jobs, not /jobs?page=1
        assert '<link rel="canonical" href="' in html
        assert '/jobs?page=1"' not in html
        # No rel=prev on page 1
        assert 'rel="prev"' not in html
        # Has rel=next because 60 > 50 (one more page)
        assert 'rel="next" href="' in html
        assert 'page=2' in html
        # Page 1 should show first 50 role slugs (0..49)
        assert "role-0000-at-test-0000" in html
        assert "role-0049-at-test-0049" in html
        # Slug 50 shouldn't appear on page 1
        assert "role-0050-at-test-0050" not in html
    await close_db()


@pytest.mark.asyncio
async def test_page_2_canonical_and_prev_next():
    await _setup()
    await _seed_published_jobs(130)  # 3 pages of 50 + 30
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/jobs?page=2")
        assert r.status_code == 200
        html = r.text
        # Canonical points to /jobs?page=2
        assert 'rel="canonical"' in html
        assert 'page=2' in html
        # rel=prev → page 1 (which is /jobs, not /jobs?page=1)
        assert 'rel="prev"' in html
        # rel=next → page 3
        assert 'rel="next"' in html
        # Page 2 shows rows 50..99
        assert "role-0050-at-test-0050" in html
        assert "role-0099-at-test-0099" in html
        assert "role-0049-at-test-0049" not in html
        # Title includes "Page 2 of 3"
        assert "Page 2 of 3" in html
    await close_db()


@pytest.mark.asyncio
async def test_last_page_has_no_rel_next():
    await _setup()
    await _seed_published_jobs(130)  # 3 pages
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/jobs?page=3")
        assert r.status_code == 200
        html = r.text
        assert 'rel="prev"' in html
        assert 'rel="next"' not in html
        # Tail rows present
        assert "role-0129-at-test-0129" in html
    await close_db()


@pytest.mark.asyncio
async def test_page_out_of_range_404():
    await _setup()
    await _seed_published_jobs(10)  # fits on page 1
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/jobs?page=2")
        assert r.status_code == 404
    await close_db()


@pytest.mark.asyncio
async def test_page_zero_is_validation_error():
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/jobs?page=0")
        assert r.status_code == 422  # Query(ge=1) enforces
    await close_db()


@pytest.mark.asyncio
async def test_pagination_footer_links_emitted():
    """Footer must carry numbered links + Prev/Next anchors."""
    await _setup()
    await _seed_published_jobs(130)
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/jobs?page=2")
        html = r.text
        assert '<nav class="pagination"' in html
        # Links to pages 1 and 3 present
        assert 'href="/jobs"' in html         # page 1 href
        assert 'href="/jobs?page=3"' in html  # page 3 href
        # Current page 2 rendered as <strong>
        assert '<strong aria-current="page">2</strong>' in html
    await close_db()


@pytest.mark.asyncio
async def test_single_page_hides_pagination_footer():
    await _setup()
    await _seed_published_jobs(10)
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/jobs")
        html = r.text
        assert '<nav class="pagination"' not in html
    await close_db()


@pytest.mark.asyncio
async def test_sitemap_pages_includes_paginated_jobs():
    """sitemap-pages.xml should list /jobs?page=N for N=2..total_pages."""
    await _setup()
    await _seed_published_jobs(130)  # 3 pages
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/sitemap-pages.xml")
        assert r.status_code == 200
        root = ET.fromstring(r.text)
        SM = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        locs = [u.find(f"{SM}loc").text for u in root.findall(f"{SM}url")]
        # /jobs (page 1 canonical) + /jobs?page=2, page=3 present
        assert any(l.endswith("/jobs") and "?" not in l for l in locs)
        assert any(l.endswith("/jobs?page=2") for l in locs)
        assert any(l.endswith("/jobs?page=3") for l in locs)
        # No /jobs?page=1 (would collide with canonical /jobs)
        assert not any(l.endswith("/jobs?page=1") for l in locs)
    await close_db()


def test_paginate_numbers_small_returns_all():
    from app.routers.jobs import _paginate_numbers
    assert _paginate_numbers(1, 5) == [1, 2, 3, 4, 5]
    assert _paginate_numbers(3, 9) == [1, 2, 3, 4, 5, 6, 7, 8, 9]


def test_paginate_numbers_large_uses_ellipsis():
    from app.routers.jobs import _paginate_numbers
    result = _paginate_numbers(10, 50, window=2)
    # First page always shown
    assert result[0] == 1
    # Last page always shown
    assert result[-1] == 50
    # Current page shown
    assert 10 in result
    # Neighbors of current shown
    for n in (8, 9, 11, 12):
        assert n in result
    # Ellipsis on both sides
    assert None in result
