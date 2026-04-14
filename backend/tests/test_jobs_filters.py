"""Tests for every /api/jobs filter + combinations.

Ensures the filter UI contract matches the backend: every sidebar field maps
to a working query param, empty values are ignored, and combining filters
uses AND semantics.
"""

from __future__ import annotations

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


async def _seed(**over) -> str:
    defaults = dict(
        source="greenhouse:anthropic", external_id=f"j-{over.get('slug','x')}",
        source_url="http://x", hash=over.get("slug", "h"),
        status="published",
        posted_on=date.today(),
        valid_through=date.today() + timedelta(days=45),
        slug=over.get("slug", "s"),
        title="Senior ML Engineer",
        company_slug="anthropic",
        designation="ML Engineer",
        country="US",
        remote_policy="Hybrid",
        verified=1,
        data={
            "tldr": "Build LLMs.",
            "company": {"name": "Anthropic", "slug": "anthropic"},
            "location": {"country": "US", "city": "SF", "remote_policy": "Hybrid"},
            "employment": {"job_type": "Full-time", "experience_years": {"min": 5, "max": 8}},
            "topic": ["LLM"],
            "must_have_skills": ["PyTorch"],
        },
    )
    defaults.update(over)
    async with db_module.async_session_factory() as db:
        j = Job(**defaults)
        db.add(j)
        await db.commit()
        return j.slug


# ---------- Single-filter coverage ----------

@pytest.mark.asyncio
async def test_no_filters_returns_all_published():
    await _setup()
    await _seed(slug="a", external_id="1")
    await _seed(slug="b", external_id="2", designation="Research Scientist")
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/api/jobs")
        assert {it["slug"] for it in r.json()} == {"a", "b"}
    await close_db()


@pytest.mark.asyncio
async def test_filter_designation():
    await _setup()
    await _seed(slug="ml", designation="ML Engineer", external_id="1")
    await _seed(slug="rs", designation="Research Scientist", external_id="2")
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/api/jobs?designation=ML Engineer")
        assert [it["slug"] for it in r.json()] == ["ml"]
    await close_db()


@pytest.mark.asyncio
async def test_filter_country_case_insensitive():
    """UI sends country in caps; API also accepts lowercase (defensively uppercased)."""
    await _setup()
    await _seed(slug="us", country="US", external_id="1")
    await _seed(slug="in", country="IN", external_id="2")
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/api/jobs?country=us")
        assert [it["slug"] for it in r.json()] == ["us"]
        r2 = await c.get("/api/jobs?country=IN")
        assert [it["slug"] for it in r2.json()] == ["in"]
    await close_db()


@pytest.mark.asyncio
async def test_filter_remote_policy():
    await _setup()
    await _seed(slug="rm", remote_policy="Remote", external_id="1")
    await _seed(slug="hy", remote_policy="Hybrid", external_id="2")
    await _seed(slug="on", remote_policy="Onsite", external_id="3")
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/api/jobs?remote=Remote")
        assert [it["slug"] for it in r.json()] == ["rm"]
    await close_db()


@pytest.mark.asyncio
async def test_filter_company():
    await _setup()
    await _seed(slug="a", company_slug="anthropic", external_id="1")
    await _seed(slug="s", company_slug="scaleai", external_id="2")
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/api/jobs?company=scaleai")
        assert [it["slug"] for it in r.json()] == ["s"]
    await close_db()


@pytest.mark.asyncio
async def test_filter_topic_from_json():
    await _setup()
    data1 = {"topic": ["LLM", "Safety"], "location": {}, "employment": {}, "company": {}}
    data2 = {"topic": ["CV"], "location": {}, "employment": {}, "company": {}}
    await _seed(slug="l", external_id="1", data=data1)
    await _seed(slug="c", external_id="2", data=data2)
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/api/jobs?topic=Safety")
        assert [it["slug"] for it in r.json()] == ["l"]
        r2 = await c.get("/api/jobs?topic=CV")
        assert [it["slug"] for it in r2.json()] == ["c"]
    await close_db()


@pytest.mark.asyncio
async def test_filter_posted_within_days():
    await _setup()
    today = date.today()
    await _seed(slug="fresh", external_id="1", posted_on=today - timedelta(days=1))
    await _seed(slug="week", external_id="2", posted_on=today - timedelta(days=6))
    await _seed(slug="old", external_id="3", posted_on=today - timedelta(days=30))
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r1 = await c.get("/api/jobs?posted_within_days=1")
        assert [it["slug"] for it in r1.json()] == ["fresh"]
        r7 = await c.get("/api/jobs?posted_within_days=7")
        assert {it["slug"] for it in r7.json()} == {"fresh", "week"}
        r30 = await c.get("/api/jobs?posted_within_days=30")
        assert {it["slug"] for it in r30.json()} == {"fresh", "week", "old"}
    await close_db()


@pytest.mark.asyncio
async def test_filter_q_matches_title_case_insensitive():
    await _setup()
    await _seed(slug="llm", title="Senior LLM Engineer", external_id="1")
    await _seed(slug="rl", title="Robotics Researcher", external_id="2")
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/api/jobs?q=llm")
        assert [it["slug"] for it in r.json()] == ["llm"]
        r2 = await c.get("/api/jobs?q=ROBOT")
        assert [it["slug"] for it in r2.json()] == ["rl"]
    await close_db()


@pytest.mark.asyncio
async def test_filter_q_matches_company_slug():
    """Search should find a job if the company name matches, not just the title."""
    await _setup()
    await _seed(slug="a", title="Engineer", company_slug="anthropic", external_id="1")
    await _seed(slug="s", title="Engineer", company_slug="scaleai", external_id="2")
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/api/jobs?q=anthropic")
        assert [it["slug"] for it in r.json()] == ["a"]
    await close_db()


# ---------- Combined / edge cases ----------

@pytest.mark.asyncio
async def test_filters_combine_with_and():
    await _setup()
    await _seed(slug="a", designation="ML Engineer", country="US", external_id="1")
    await _seed(slug="b", designation="ML Engineer", country="IN", external_id="2")
    await _seed(slug="c", designation="Data Scientist", country="US", external_id="3")
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/api/jobs?designation=ML Engineer&country=US")
        assert [it["slug"] for it in r.json()] == ["a"]
    await close_db()


@pytest.mark.asyncio
async def test_empty_query_params_ignored():
    """UI sends empty params when a filter is cleared; must not filter to zero."""
    await _setup()
    await _seed(slug="a", external_id="1")
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/api/jobs?designation=&country=&remote=&company=&q=")
        assert [it["slug"] for it in r.json()] == ["a"]
    await close_db()


@pytest.mark.asyncio
async def test_draft_jobs_never_in_results():
    await _setup()
    await _seed(slug="p", status="published", external_id="1")
    await _seed(slug="d", status="draft", external_id="2")
    await _seed(slug="r", status="rejected", external_id="3")
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/api/jobs")
        assert [it["slug"] for it in r.json()] == ["p"]
    await close_db()


@pytest.mark.asyncio
async def test_posted_within_days_bounds():
    """Out-of-range values return 422, not 500."""
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        assert (await c.get("/api/jobs?posted_within_days=0")).status_code == 422
        assert (await c.get("/api/jobs?posted_within_days=400")).status_code == 422
    await close_db()


@pytest.mark.asyncio
async def test_ordering_newest_first():
    await _setup()
    today = date.today()
    await _seed(slug="old", external_id="1", posted_on=today - timedelta(days=20))
    await _seed(slug="new", external_id="2", posted_on=today - timedelta(days=1))
    await _seed(slug="mid", external_id="3", posted_on=today - timedelta(days=10))
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/api/jobs")
        assert [it["slug"] for it in r.json()] == ["new", "mid", "old"]
    await close_db()


@pytest.mark.asyncio
async def test_limit_enforced():
    await _setup()
    for i in range(5):
        await _seed(slug=f"j{i}", external_id=f"e{i}")
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/api/jobs?limit=2")
        assert len(r.json()) == 2
    await close_db()
