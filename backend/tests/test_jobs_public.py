"""Public jobs endpoint tests: list filtering, SSR JSON-LD, match 401 for anon."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

import app.db as db_module
import app.models  # noqa: F401
from app.db import Base, close_db, init_db
from app.models import Job


async def _setup():
    await init_db(url="sqlite+aiosqlite:///:memory:")
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _app():
    from app.main import app
    return app


async def _seed(status: str = "published", **over) -> str:
    defaults = dict(
        source="greenhouse:anthropic", external_id="a1", source_url="http://x",
        hash="h", status=status,
        posted_on=date.today(), valid_through=date.today() + timedelta(days=45),
        slug="senior-ml-engineer-at-anthropic-abcd",
        title="Senior ML Engineer", company_slug="anthropic",
        designation="ML Engineer", country="US", remote_policy="Hybrid", verified=1,
        data={
            "tldr": "Research-adjacent ML role.",
            "designation": "ML Engineer",
            "company": {"name": "Anthropic", "slug": "anthropic"},
            "location": {"country": "US", "city": "San Francisco", "remote_policy": "Hybrid"},
            "employment": {"job_type": "Full-time", "experience_years": {"min": 5, "max": 8},
                           "salary": {"disclosed": True, "currency": "USD", "min": 200000, "max": 300000}},
            "must_have_skills": ["PyTorch"],
            "description_html": "<p>Build things.</p>",
            "apply_url": "http://apply",
        },
    )
    defaults.update(over)
    async with db_module.async_session_factory() as db:
        j = Job(**defaults)
        db.add(j)
        await db.commit()
        return j.slug


@pytest.mark.asyncio
async def test_api_jobs_returns_only_published():
    await _setup()
    await _seed(status="published", slug="pub1", external_id="p1")
    await _seed(status="draft", slug="drft", external_id="p2")
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/api/jobs")
        assert r.status_code == 200
        items = r.json()
        slugs = [it["slug"] for it in items]
        assert "pub1" in slugs and "drft" not in slugs
    await close_db()


@pytest.mark.asyncio
async def test_api_jobs_filter_by_designation():
    await _setup()
    await _seed(slug="ml-1", external_id="m1", designation="ML Engineer")
    await _seed(slug="rs-1", external_id="r1", designation="Research Scientist")
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/api/jobs?designation=ML Engineer")
        slugs = [it["slug"] for it in r.json()]
        assert slugs == ["ml-1"]
    await close_db()


@pytest.mark.asyncio
async def test_per_job_ssr_includes_jobposting_jsonld():
    await _setup()
    slug = await _seed()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get(f"/jobs/{slug}")
        assert r.status_code == 200
        body = r.text
        m = re.search(r'<script type="application/ld\+json">(.+?)</script>', body, re.S)
        assert m, "JobPosting JSON-LD missing"
        ld = json.loads(m.group(1))
        assert ld["@type"] == "JobPosting"
        assert ld["title"] == "Senior ML Engineer"
        assert ld["hiringOrganization"]["name"] == "Anthropic"
        assert ld["baseSalary"]["currency"] == "USD"
    await close_db()


@pytest.mark.asyncio
async def test_draft_job_404():
    await _setup()
    slug = await _seed(status="draft", slug="draft-only", external_id="d1")
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get(f"/jobs/{slug}")
        assert r.status_code == 404
    await close_db()


@pytest.mark.asyncio
async def test_match_endpoint_requires_auth():
    await _setup()
    slug = await _seed()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get(f"/api/jobs/{slug}/match")
        assert r.status_code == 401
    await close_db()


@pytest.mark.asyncio
async def test_sitemap_jobs_includes_published_only():
    await _setup()
    pub_slug = await _seed(status="published", slug="pub-x", external_id="sx")
    await _seed(status="draft", slug="drft-x", external_id="sy")
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/sitemap-jobs.xml")
        assert r.status_code == 200
        assert pub_slug in r.text
        assert "drft-x" not in r.text
    await close_db()


@pytest.mark.asyncio
async def test_indexnow_key_verify_404_when_unconfigured():
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/somerandomstring.txt")
        assert r.status_code == 404
    await close_db()
