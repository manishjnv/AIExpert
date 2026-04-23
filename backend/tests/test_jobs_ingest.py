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
        m.side_effect = lambda raw, **kw: _fake_enrich(raw)
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
        m.side_effect = lambda raw, **kw: _fake_enrich(raw)
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
async def test_stage_off_topic_reject_is_sticky_on_hash_change():
    """Once classifier-rejected as off_topic, a row stays rejected even when the
    source JD changes. Absorbs the new hash so we don't re-evaluate every run,
    but skips re-enrichment and keeps status='rejected'. Tombstone prevents
    re-ingestion if row is ever deleted (via (source, external_id) dedup).
    """
    await _setup()
    with patch("app.services.jobs_enrich.enrich_job", new_callable=AsyncMock) as m:
        m.side_effect = lambda raw, **kw: _fake_enrich(raw)
        # Stage once + mark as classifier-rejected (simulates prior admin/auto rejection).
        async with db_module.async_session_factory() as db:
            await jobs_ingest._stage_one(_raw(), "greenhouse:anthropic", db)
            await db.commit()
            job = (await db.execute(select(Job))).scalar_one()
            original_hash = job.hash
            original_data = dict(job.data)
            job.status = "rejected"
            job.reject_reason = "off_topic"
            job.admin_notes = "auto-skipped: non-AI title"
            await db.commit()

        # Source JD changes → new hash, but we must NOT flip back to draft or
        # re-enrich. enrich_job mock should never be called.
        m.reset_mock()
        async with db_module.async_session_factory() as db:
            result = await jobs_ingest._stage_one(
                _raw(jd_html="<p>Updated salary range and perks.</p>"),
                "greenhouse:anthropic",
                db,
            )
            assert result == "rejected_sticky"
            await db.commit()

        assert m.call_count == 0, "sticky reject must not trigger enrichment"

        async with db_module.async_session_factory() as db:
            job = (await db.execute(select(Job))).scalar_one()
            assert job.status == "rejected"
            assert job.reject_reason == "off_topic"
            assert job.hash != original_hash  # absorbed new hash
            assert job.data == original_data  # tombstone data untouched
    await close_db()


@pytest.mark.asyncio
async def test_stage_manual_reject_still_flips_to_draft_on_hash_change():
    """Manual rejects (reject_reason IS NULL) are NOT sticky — admin wants another
    look when the JD changes. Only off_topic (classifier) rejects are sticky.
    """
    await _setup()
    with patch("app.services.jobs_enrich.enrich_job", new_callable=AsyncMock) as m:
        m.side_effect = lambda raw, **kw: _fake_enrich(raw)
        async with db_module.async_session_factory() as db:
            await jobs_ingest._stage_one(_raw(), "greenhouse:anthropic", db)
            await db.commit()
            job = (await db.execute(select(Job))).scalar_one()
            job.status = "rejected"
            job.reject_reason = None  # manual reject, no auto-reason
            await db.commit()

        async with db_module.async_session_factory() as db:
            result = await jobs_ingest._stage_one(
                _raw(jd_html="<p>Updated JD copy.</p>"),
                "greenhouse:anthropic",
                db,
            )
            assert result == "changed"
            await db.commit()
            job = (await db.execute(select(Job))).scalar_one()
            assert job.status == "draft"  # flipped back for re-review
    await close_db()


@pytest.mark.asyncio
async def test_valid_through_is_posted_plus_45d():
    await _setup()
    with patch("app.services.jobs_enrich.enrich_job", new_callable=AsyncMock) as m:
        m.side_effect = lambda raw, **kw: _fake_enrich(raw)
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


# ---------- auto-expire on source-feed disappearance (Phase 13.1) ----------

async def _seed_published(source_key: str, external_id: str, *, missing_streak: int = 0) -> None:
    """Seed one `published` job for the auto-expire tests."""
    async with db_module.async_session_factory() as db:
        db.add(Job(
            source=source_key,
            external_id=external_id,
            source_url=f"https://example.com/{external_id}",
            hash=f"h-{external_id}",
            status="published",
            posted_on=date(2026, 4, 1),
            valid_through=date(2026, 5, 16),
            slug=f"slug-{external_id}",
            title="Senior ML Engineer",
            company_slug="anthropic",
            designation="ML Engineer",
            country="US",
            remote_policy="Hybrid",
            verified=1,
            data={"_meta": {"missing_streak": missing_streak}} if missing_streak else {},
        ))
        await db.commit()


@pytest.mark.asyncio
async def test_auto_expire_flips_after_two_misses():
    """Missing one run bumps streak to 1 (still published); missing again flips to expired."""
    await _setup()
    src = "greenhouse:anthropic"
    await _seed_published(src, "gh-present")
    await _seed_published(src, "gh-missing")

    # Run 1: feed contains only gh-present.
    stats = {}
    feed = [_raw(external_id="gh-present")]
    await jobs_ingest._auto_expire_missing({src: feed}, stats)
    assert stats.get("auto_expired", 0) == 0
    async with db_module.async_session_factory() as db:
        missing = (await db.execute(select(Job).where(Job.external_id == "gh-missing"))).scalar_one()
        assert missing.status == "published"
        assert missing.data["_meta"]["missing_streak"] == 1

    # Run 2: feed still missing gh-missing → flips to expired.
    stats = {}
    await jobs_ingest._auto_expire_missing({src: feed}, stats)
    assert stats["auto_expired"] == 1
    async with db_module.async_session_factory() as db:
        missing = (await db.execute(select(Job).where(Job.external_id == "gh-missing"))).scalar_one()
        assert missing.status == "expired"
        assert missing.data["_meta"]["expired_reason"] == "source_removed"
        assert "expired_on" in missing.data["_meta"]
        present = (await db.execute(select(Job).where(Job.external_id == "gh-present"))).scalar_one()
        assert present.status == "published"
    await close_db()


@pytest.mark.asyncio
async def test_auto_expire_resets_streak_on_reappearance():
    """A job missing once then returning must reset its streak, not expire."""
    await _setup()
    src = "greenhouse:anthropic"
    await _seed_published(src, "gh-flapper", missing_streak=1)

    feed = [_raw(external_id="gh-flapper")]
    stats = {}
    await jobs_ingest._auto_expire_missing({src: feed}, stats)
    assert stats.get("auto_expired", 0) == 0
    async with db_module.async_session_factory() as db:
        j = (await db.execute(select(Job).where(Job.external_id == "gh-flapper"))).scalar_one()
        assert j.status == "published"
        assert j.data["_meta"]["missing_streak"] == 0
    await close_db()


@pytest.mark.asyncio
async def test_auto_expire_skips_empty_source():
    """Source outage (0 rows fetched) must not expire anyone from that source."""
    await _setup()
    src = "greenhouse:anthropic"
    await _seed_published(src, "gh-safe", missing_streak=1)

    stats = {}
    await jobs_ingest._auto_expire_missing({src: []}, stats)
    assert stats.get("auto_expired", 0) == 0
    async with db_module.async_session_factory() as db:
        j = (await db.execute(select(Job).where(Job.external_id == "gh-safe"))).scalar_one()
        assert j.status == "published"
        # streak untouched
        assert j.data["_meta"]["missing_streak"] == 1
    await close_db()


@pytest.mark.asyncio
async def test_auto_expire_ignores_other_statuses():
    """Draft/rejected/expired jobs must not be touched by the auto-expire pass."""
    await _setup()
    src = "greenhouse:anthropic"
    async with db_module.async_session_factory() as db:
        for ext_id, status in [("gh-draft", "draft"), ("gh-reject", "rejected"), ("gh-already", "expired")]:
            db.add(Job(
                source=src, external_id=ext_id,
                source_url=f"https://example.com/{ext_id}",
                hash=f"h-{ext_id}", status=status,
                posted_on=date(2026, 4, 1), valid_through=date(2026, 5, 16),
                slug=f"slug-{ext_id}", title="X", company_slug="anthropic",
                designation="ML Engineer", country="US", remote_policy="Hybrid",
                verified=1, data={},
            ))
        await db.commit()

    stats = {}
    await jobs_ingest._auto_expire_missing({src: [_raw(external_id="gh-unrelated")]}, stats)
    assert stats.get("auto_expired", 0) == 0
    async with db_module.async_session_factory() as db:
        rows = {j.external_id: j.status for j in (await db.execute(select(Job))).scalars().all()}
        assert rows == {"gh-draft": "draft", "gh-reject": "rejected", "gh-already": "expired"}
    await close_db()
    await close_db()
