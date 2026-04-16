"""Tests for source registry, Ashby normalization, and probe auto-disable."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

import app.db as db_module
from app.db import Base, close_db, init_db
from app.models import JobSource
from app.services.jobs_sources import ashby
from app.services.jobs_sources.greenhouse import GREENHOUSE_BOARDS
from app.services.jobs_sources.lever import LEVER_BOARDS


async def _setup():
    await init_db(url="sqlite+aiosqlite:///:memory:")
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def test_india_focused_slugs_added():
    """Step 1: confirm we ship the India-focused slugs we probed live."""
    gh_slugs = {s for s, _ in GREENHOUSE_BOARDS}
    lv_slugs = {s for s, _ in LEVER_BOARDS}
    assert {"phonepe", "groww"}.issubset(gh_slugs)
    assert {"cred", "mindtickle"}.issubset(lv_slugs)


def test_ashby_registry_includes_sarvam():
    """Step 2: Sarvam (India AI lab) must be in the Ashby allowlist."""
    slugs = {s for s, _ in ashby.ASHBY_BOARDS}
    assert "sarvam" in slugs


def test_ashby_normalizes_real_payload_shape():
    """Real Ashby payload (verified against api.ashbyhq.com 2026-04-15)."""
    j = {
        "id": "abc-123",
        "title": "ML Engineer",
        "publishedAt": "2026-04-09T16:06:31.765+00:00",
        "isListed": True,
        "location": "Bangalore",
        "secondaryLocations": [{"location": "Remote, India"}],
        "descriptionHtml": "<p>Hi</p>",
        "jobUrl": "https://jobs.ashbyhq.com/sarvam/abc-123",
        "applyUrl": "https://jobs.ashbyhq.com/sarvam/abc-123/application",
        "department": "Engineering",
        "team": "Platform",
        "employmentType": "FullTime",
        "isRemote": False,
    }
    raw = ashby._normalize(j, "sarvam", "Sarvam AI")
    assert raw["external_id"] == "abc-123"
    assert raw["title_raw"] == "ML Engineer"
    assert raw["company"] == "Sarvam AI"
    assert raw["company_slug"] == "sarvam"
    assert raw["location_raw"] == "Bangalore"
    assert raw["posted_on"] == "2026-04-09"
    assert raw["jd_html"] == "<p>Hi</p>"


def test_ashby_skips_unlisted_jobs():
    """Test/internal Ashby roles have isListed=False — must drop."""
    payload = {
        "jobs": [
            {"id": "1", "title": "Hidden", "isListed": False,
             "publishedAt": "2026-04-01T00:00:00Z", "descriptionHtml": "x"},
            {"id": "2", "title": "Visible", "isListed": True,
             "publishedAt": "2026-04-01T00:00:00Z", "descriptionHtml": "y",
             "jobUrl": "u", "location": "Bangalore"},
        ]
    }

    class _Resp:
        status_code = 200
        def json(self): return payload

    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **kw): return _Resp()

    with patch("app.services.jobs_sources.ashby.httpx.AsyncClient", lambda **kw: _Client()):
        import asyncio
        rows = asyncio.get_event_loop().run_until_complete(
            ashby.fetch_board("sarvam", "Sarvam AI")
        )
    assert len(rows) == 1 and rows[0]["external_id"] == "2"


@pytest.mark.asyncio
async def test_probe_auto_disables_after_threshold():
    """Step 3: 3 consecutive probe failures must flip JobSource.enabled to 0."""
    await _setup()
    from app.services.jobs_sources import probe

    # Seed one source row.
    async with db_module.async_session_factory() as db:
        db.add(JobSource(key="greenhouse:dead", kind="greenhouse",
                         label="Dead Co", tier=1, enabled=1))
        await db.commit()

    async def _fail(*a, **kw):
        return ("greenhouse:dead", False, "HTTP 404")

    # Force the probe iterator to only yield this one source.
    with patch.object(probe, "_all_boards",
                      lambda: iter([("greenhouse:dead", "greenhouse", "dead")])):
        with patch.object(probe, "_probe_one", AsyncMock(side_effect=_fail)):
            # Run 1 — streak 1, still enabled.
            r1 = await probe.probe_all()
            assert r1["greenhouse:dead"]["enabled"] is True
            assert r1["greenhouse:dead"]["fail_streak"] == 1
            # Run 2 — streak 2, still enabled.
            r2 = await probe.probe_all()
            assert r2["greenhouse:dead"]["enabled"] is True
            assert r2["greenhouse:dead"]["fail_streak"] == 2
            # Run 3 — streak 3, AUTO-DISABLED.
            r3 = await probe.probe_all()
            assert r3["greenhouse:dead"]["enabled"] is False
            assert r3["greenhouse:dead"]["fail_streak"] == 3

    async with db_module.async_session_factory() as db:
        src = (await db.execute(select(JobSource).where(JobSource.key == "greenhouse:dead"))).scalar_one()
        assert src.enabled == 0
        assert "[auto-disabled]" in (src.last_run_error or "")
    await close_db()


@pytest.mark.asyncio
async def test_probe_resets_streak_on_recovery():
    """A previously-failing source that probes OK again must reset its streak."""
    await _setup()
    from app.services.jobs_sources import probe

    async with db_module.async_session_factory() as db:
        db.add(JobSource(key="greenhouse:flapper", kind="greenhouse",
                         label="Flapper", tier=1, enabled=1,
                         last_run_error="[fail_streak=2] HTTP 503"))
        await db.commit()

    async def _ok(*a, **kw):
        return ("greenhouse:flapper", True, "")

    with patch.object(probe, "_all_boards",
                      lambda: iter([("greenhouse:flapper", "greenhouse", "flapper")])):
        with patch.object(probe, "_probe_one", AsyncMock(side_effect=_ok)):
            r = await probe.probe_all()
            assert r["greenhouse:flapper"]["fail_streak"] == 0

    async with db_module.async_session_factory() as db:
        src = (await db.execute(select(JobSource).where(JobSource.key == "greenhouse:flapper"))).scalar_one()
        assert src.last_run_error is None
    await close_db()


@pytest.mark.asyncio
async def test_module_grounding_returns_published_template_keys():
    """Bug #2 fix: _get_module_slugs must return real template keys, not
    crash on the phantom PlanVersion.status column."""
    from unittest.mock import patch
    from app.services.jobs_enrich import _get_module_slugs

    with patch("app.curriculum.loader.list_published",
               return_value=["ai-zero-to-hero-12mo", "fast-track-6mo", "beginner-3mo"]):
        slugs = await _get_module_slugs()
    assert "ai-zero-to-hero-12mo" in slugs
    assert len(slugs) == 3
    # Sorted output so the prompt is deterministic across runs.
    assert slugs == sorted(slugs)


@pytest.mark.asyncio
async def test_module_grounding_returns_empty_on_loader_failure():
    """Enricher must still run if the template loader explodes."""
    from unittest.mock import patch
    from app.services.jobs_enrich import _get_module_slugs

    with patch("app.curriculum.loader.list_published",
               side_effect=RuntimeError("disk gone")):
        slugs = await _get_module_slugs()
    assert slugs == []


@pytest.mark.asyncio
async def test_date_based_auto_expire_flips_status():
    """Bug fix: published jobs whose valid_through has passed must flip to expired."""
    from datetime import date, timedelta
    from app.models import Job
    from app.services.jobs_ingest import _auto_expire_past_valid_through
    await _setup()

    today = date.today()
    async with db_module.async_session_factory() as db:
        # Past valid_through — should expire.
        db.add(Job(
            source="greenhouse:x", external_id="old-1", source_url="u",
            hash="h1", status="published", posted_on=today - timedelta(days=60),
            valid_through=today - timedelta(days=15), slug="old-1", title="T",
            company_slug="x", designation="ML Engineer", country="US",
            remote_policy="Hybrid", verified=1, data={},
        ))
        # Still valid — must stay published.
        db.add(Job(
            source="greenhouse:x", external_id="fresh-1", source_url="u",
            hash="h2", status="published", posted_on=today - timedelta(days=10),
            valid_through=today + timedelta(days=35), slug="fresh-1", title="T",
            company_slug="x", designation="ML Engineer", country="US",
            remote_policy="Hybrid", verified=1, data={},
        ))
        await db.commit()

    stats = {}
    await _auto_expire_past_valid_through(stats)
    assert stats.get("auto_expired") == 1
    async with db_module.async_session_factory() as db:
        rows = {j.external_id: j for j in (await db.execute(select(Job))).scalars().all()}
        assert rows["old-1"].status == "expired"
        assert rows["old-1"].data["_meta"]["expired_reason"] == "date_based"
        assert rows["fresh-1"].status == "published"
    await close_db()
