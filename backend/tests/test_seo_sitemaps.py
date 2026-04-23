"""Sub-sitemap tests (SEO-02).

Covers:
  - sitemap_index lists all 5 children with <lastmod>
  - each child sitemap returns parseable XML
  - sitemap-jobs.xml emits <image:image> per job
  - sitemap-blog.xml emits <image:image> per post
  - sitemap-pages.xml includes /, /jobs, /leaderboard, /verify
  - sitemap-certs.xml excludes revoked certificates
  - sitemap-profiles.xml strictly excludes public_profile=False users
    (SEO-02 acceptance #5 regression)
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

import app.db as db_module
import app.models  # noqa: F401
from app.db import Base, close_db, init_db

SM = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
IMG = "{http://www.google.com/schemas/sitemap-image/1.1}"


async def _setup():
    await init_db(url="sqlite+aiosqlite:///:memory:")
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _app():
    from app.main import app
    return app


@pytest.mark.asyncio
async def test_sitemap_index_lists_five_children_with_lastmod():
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/sitemap_index.xml")
        assert r.status_code == 200
        root = ET.fromstring(r.text)
        assert root.tag == f"{SM}sitemapindex"
        children = root.findall(f"{SM}sitemap")
        locs = [s.find(f"{SM}loc").text for s in children]
        for name in ("sitemap-jobs.xml", "sitemap-blog.xml",
                     "sitemap-pages.xml", "sitemap-certs.xml",
                     "sitemap-profiles.xml"):
            assert any(l.endswith(name) for l in locs), f"missing {name}"
        # Every child entry carries a lastmod
        for s in children:
            assert s.find(f"{SM}lastmod") is not None
    await close_db()


@pytest.mark.asyncio
async def test_sitemap_jobs_embeds_image_extension(monkeypatch):
    from app.models.job import Job

    await _setup()
    async with db_module.async_session_factory() as s:
        s.add(Job(
            source="greenhouse:x", external_id="e1",
            source_url="https://x/y", hash="h" * 64,
            status="published",
            posted_on=date.today(), valid_through=date.today() + timedelta(days=30),
            slug="applied-ai-eng-at-x-abcd",
            title="Applied AI Engineer", company_slug="x",
            designation="AI Engineer", country="US",
            data={"company": {"name": "X Co"}},
        ))
        await s.commit()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/sitemap-jobs.xml")
        assert r.status_code == 200
        root = ET.fromstring(r.text)
        urls = root.findall(f"{SM}url")
        assert len(urls) == 1
        # image:image extension present, pointing at /og/jobs/{slug}.png
        img_loc = urls[0].find(f"{IMG}image/{IMG}loc")
        assert img_loc is not None
        assert img_loc.text.endswith("/og/jobs/applied-ai-eng-at-x-abcd.png")
    await close_db()


@pytest.mark.asyncio
async def test_sitemap_blog_embeds_image_and_includes_post_01(monkeypatch):
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: False)
    monkeypatch.setattr("app.services.blog_publisher.list_published", lambda: [])
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/sitemap-blog.xml")
        assert r.status_code == 200
        root = ET.fromstring(r.text)
        urls = root.findall(f"{SM}url")
        locs = [u.find(f"{SM}loc").text for u in urls]
        # /blog index + /blog/01
        assert any(l.endswith("/blog") for l in locs)
        assert any(l.endswith("/blog/01") for l in locs)
        # POST_01 entry has image extension
        post_01 = next(u for u in urls if u.find(f"{SM}loc").text.endswith("/blog/01"))
        img_loc = post_01.find(f"{IMG}image/{IMG}loc")
        assert img_loc is not None
        assert img_loc.text.endswith("/og/blog/01.png")
    await close_db()


@pytest.mark.asyncio
async def test_sitemap_pages_lists_core_hubs():
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/sitemap-pages.xml")
        assert r.status_code == 200
        root = ET.fromstring(r.text)
        locs = [u.find(f"{SM}loc").text for u in root.findall(f"{SM}url")]
        for needed in ("/", "/jobs", "/leaderboard", "/verify"):
            assert any(l.rstrip("/") == (l.rstrip("/") if needed != "/" else l).rstrip("/")
                       and l.endswith(needed) or (needed == "/" and l.endswith("//") is False and l.endswith("/"))
                       for l in locs), f"missing {needed} in {locs}"
    await close_db()


@pytest.mark.asyncio
async def test_sitemap_certs_excludes_revoked():
    from app.models.certificate import Certificate
    from app.models.plan import UserPlan
    from app.models.user import User

    await _setup()
    async with db_module.async_session_factory() as s:
        u = User(email="u@example.com", name="U", provider="otp")
        s.add(u)
        await s.flush()
        # Two distinct plans so certs don't collide on uq_certificate_user_plan
        p1 = UserPlan(user_id=u.id, template_key="generalist",
                      plan_version="v1", status="active")
        p2 = UserPlan(user_id=u.id, template_key="ai-engineer",
                      plan_version="v1", status="active")
        s.add(p1)
        s.add(p2)
        await s.flush()
        s.add(Certificate(
            user_id=u.id, user_plan_id=p1.id, template_key="generalist",
            credential_id="AER-2026-04-AAAAAA", tier="completion",
            display_name="U", course_title="AI Generalist",
            level="Beginner", duration_months=6,
            signed_hash="deadbeef" * 8,
        ))
        s.add(Certificate(
            user_id=u.id, user_plan_id=p2.id, template_key="ai-engineer",
            credential_id="AER-2026-04-BBBBBB", tier="completion",
            display_name="U", course_title="AI Engineer",
            level="Beginner", duration_months=6,
            signed_hash="deadbeef" * 8,
            revoked_at=datetime.utcnow(), revoke_reason="test",
        ))
        await s.commit()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/sitemap-certs.xml")
        assert r.status_code == 200
        assert "AER-2026-04-AAAAAA" in r.text
        assert "AER-2026-04-BBBBBB" not in r.text
    await close_db()


@pytest.mark.asyncio
async def test_sitemap_profiles_strict_public_filter():
    """SEO-02 acceptance #5 — public_profile=False users NEVER appear."""
    from app.models.user import User

    await _setup()
    async with db_module.async_session_factory() as s:
        s.add(User(email="private@example.com", name="Priv",
                   provider="otp", public_profile=False))
        s.add(User(email="pub@example.com", name="Pub",
                   provider="otp", public_profile=True))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/sitemap-profiles.xml")
        assert r.status_code == 200
        root = ET.fromstring(r.text)
        urls = root.findall(f"{SM}url")
        # Exactly one profile URL; private user excluded
        assert len(urls) == 1
        loc = urls[0].find(f"{SM}loc").text
        assert "/profile/" in loc
    await close_db()


@pytest.mark.asyncio
async def test_child_sitemaps_accept_head():
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        for path in ("/sitemap-blog.xml", "/sitemap-pages.xml",
                     "/sitemap-certs.xml", "/sitemap-profiles.xml"):
            r = await c.head(path)
            assert r.status_code == 200, path
            assert r.headers["content-type"].startswith("application/xml")
    await close_db()
