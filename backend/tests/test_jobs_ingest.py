"""Tests for the jobs ingest pipeline (dedup, stage, blocklist, enrichment fallback)."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

import app.db as db_module
from app.db import Base, close_db, init_db
from app.models import Job, JobCompany, JobSource
from app.services import jobs_ingest
from app.services.jobs_sources import RawJob


async def _setup():
    await init_db(url="sqlite+aiosqlite:///:memory:")
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _raw(**over) -> RawJob:
    base = RawJob(
        external_id="gh-1",
        source_url="https://boards.greenhouse.io/anthropic/jobs/1",
        title_raw="Senior ML Engineer",
        company="Anthropic",
        company_slug="anthropic",
        location_raw="San Francisco, CA",
        jd_html="<p>Build LLMs at scale. Must have PyTorch.</p>",
        posted_on="2026-04-10",
        extra={},
    )
    base.update(over)  # type: ignore[call-arg]
    return base


def _fake_enrich(raw: RawJob) -> dict:
    return {
        "title_raw": raw["title_raw"],
        "designation": "ML Engineer",
        "seniority": "Senior",
        "topic": ["LLM"],
        "company": {"name": raw["company"], "slug": raw["company_slug"]},
        "location": {"country": "US", "city": "San Francisco", "remote_policy": "Hybrid", "regions_allowed": []},
        "employment": {"job_type": "Full-time", "shift": "Day",
                       "experience_years": {"min": 5, "max": 8},
                       "salary": {"min": None, "max": None, "currency": None, "disclosed": False}},
        "description_html": raw["jd_html"],
        "tldr": "Rewrite of the JD.",
        "must_have_skills": ["PyTorch"],
        "nice_to_have_skills": [],
        "roadmap_modules_matched": [],
        "apply_url": raw["source_url"],
    }


# ---------- hash + slug ----------

def test_compute_hash_stable():
    r = _raw()
    assert jobs_ingest.compute_hash(r) == jobs_ingest.compute_hash(dict(r))  # type: ignore[arg-type]


def test_compute_hash_changes_on_content():
    h1 = jobs_ingest.compute_hash(_raw())
    h2 = jobs_ingest.compute_hash(_raw(jd_html="<p>Different content</p>"))
    assert h1 != h2


def test_slugify_safe():
    assert jobs_ingest.slugify("Senior ML Engineer, Alignment!!") == "senior-ml-engineer-alignment"


# ---------- stage_one ----------

@pytest.mark.asyncio
async def test_stage_new_then_unchanged_then_changed():
    await _setup()
    with patch("app.services.jobs_enrich.enrich_job", new_callable=AsyncMock) as m:
        m.side_effect = lambda raw: _fake_enrich(raw)
        async with db_module.async_session_factory() as db:
            r = _raw()
            assert await jobs_ingest._stage_one(r, "greenhouse:anthropic", db) == "new"
            await db.commit()
            # Same hash → unchanged.
            assert await jobs_ingest._stage_one(r, "greenhouse:anthropic", db) == "unchanged"
            # Different JD → changed, bounces back to draft.
            r2 = _raw(jd_html="<p>Updated salary range.</p>")
            assert await jobs_ingest._stage_one(r2, "greenhouse:anthropic", db) == "changed"
            await db.commit()
            job = (await db.execute(select(Job).where(Job.external_id == "gh-1"))).scalar_one()
            assert job.status == "draft"
            assert job.designation == "ML Engineer"
            assert job.country == "US"
    await close_db()


@pytest.mark.asyncio
async def test_stage_blocked_company_skipped():
    await _setup()
    async with db_module.async_session_factory() as db:
        db.add(JobCompany(slug="anthropic", name="Anthropic", blocklisted=1))
        await db.commit()
    with patch("app.services.jobs_enrich.enrich_job", new_callable=AsyncMock) as m:
        m.side_effect = lambda raw: _fake_enrich(raw)
        async with db_module.async_session_factory() as db:
            result = await jobs_ingest._stage_one(_raw(), "greenhouse:anthropic", db)
            assert result == "skipped_blocked"
            await db.commit()
            rows = (await db.execute(select(Job))).scalars().all()
            assert rows == []
    await close_db()


@pytest.mark.asyncio
async def test_enrichment_failure_falls_back():
    """On enrichment exception, ingest still stages the row with admin_notes set."""
    await _setup()
    with patch("app.services.jobs_enrich.enrich_job", new_callable=AsyncMock) as m:
        m.side_effect = RuntimeError("provider down")
        async with db_module.async_session_factory() as db:
            assert await jobs_ingest._stage_one(_raw(), "greenhouse:anthropic", db) == "new"
            await db.commit()
            job = (await db.execute(select(Job))).scalar_one()
            assert job.status == "draft"
            assert "enrichment failed" in (job.admin_notes or "")
            # Minimal fallback populated denormalized columns.
            assert job.designation == "Other"
            assert job.data["must_have_skills"] == []
    await close_db()


@pytest.mark.asyncio
async def test_valid_through_is_posted_plus_45d():
    await _setup()
    with patch("app.services.jobs_enrich.enrich_job", new_callable=AsyncMock) as m:
        m.side_effect = lambda raw: _fake_enrich(raw)
        async with db_module.async_session_factory() as db:
            await jobs_ingest._stage_one(_raw(posted_on="2026-04-01"), "greenhouse:anthropic", db)
            await db.commit()
            job = (await db.execute(select(Job))).scalar_one()
            assert job.posted_on == date(2026, 4, 1)
            assert (job.valid_through - job.posted_on).days == 45
    await close_db()


@pytest.mark.asyncio
async def test_ensure_source_rows_idempotent():
    await _setup()
    await jobs_ingest.ensure_source_rows()
    await jobs_ingest.ensure_source_rows()  # second call must not duplicate
    async with db_module.async_session_factory() as db:
        rows = (await db.execute(select(JobSource))).scalars().all()
        keys = [r.key for r in rows]
        # Both greenhouse + lever seeded.
        assert any(k.startswith("greenhouse:") for k in keys)
        assert any(k.startswith("lever:") for k in keys)
        assert len(keys) == len(set(keys))  # no dupes
    await close_db()
