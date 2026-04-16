"""Admin review-queue endpoint tests: auth, publish, reject, bulk-publish gate."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import app.db as db_module
import app.models  # noqa: F401
from app.auth.jwt import issue_token
from app.db import Base, close_db, init_db
from app.models import Job, JobCompany, JobSource
from app.models.user import User


async def _setup():
    await init_db(url="sqlite+aiosqlite:///:memory:")
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _app():
    from app.main import app
    return app


async def _mk_user(email: str, is_admin: bool):
    async with db_module.async_session_factory() as db:
        u = User(email=email, provider="otp", is_admin=is_admin, name=email)
        db.add(u)
        await db.flush()
        token = await issue_token(u, db)
        await db.commit()
        return u.id, token


async def _mk_job(source: str = "greenhouse:anthropic", tier: int = 1, bulk: int = 1,
                  status: str = "draft", slug: str = "job-1", ext: str = "gh-1") -> int:
    async with db_module.async_session_factory() as db:
        src = (await db.execute(select(JobSource).where(JobSource.key == source))).scalar_one_or_none()
        if not src:
            db.add(JobSource(key=source, kind=source.split(":")[0], label="X", tier=tier, enabled=1, bulk_approve=bulk))
        if not (await db.execute(select(JobCompany).where(JobCompany.slug == "anthropic"))).scalar_one_or_none():
            db.add(JobCompany(slug="anthropic", name="Anthropic"))
        j = Job(
            source=source, external_id=ext, source_url="http://x", hash=ext, status=status,
            posted_on=date.today(), valid_through=date.today() + timedelta(days=45),
            slug=slug, title="ML Engineer", company_slug="anthropic", designation="ML Engineer",
            country="US", remote_policy="Hybrid", verified=1,
            data={"tldr": "t", "must_have_skills": [], "employment": {}},
        )
        db.add(j)
        await db.commit()
        return j.id


@pytest.mark.asyncio
async def test_non_admin_rejected():
    await _setup()
    _, token = await _mk_user("u@t.com", is_admin=False)
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/admin/jobs/api/queue", cookies={"auth_token": token})
        assert r.status_code == 403
    await close_db()


@pytest.mark.asyncio
async def test_queue_lists_drafts():
    await _setup()
    _, token = await _mk_user("a@t.com", is_admin=True)
    await _mk_job()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/admin/jobs/api/queue", cookies={"auth_token": token})
        assert r.status_code == 200
        d = r.json()
        assert d["counts"].get("draft") == 1
        assert len(d["items"]) == 1
    await close_db()


@pytest.mark.asyncio
async def test_publish_flips_status_and_stamps_reviewer():
    await _setup()
    _, token = await _mk_user("reviewer@t.com", is_admin=True)
    job_id = await _mk_job()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.post(f"/admin/jobs/api/{job_id}/publish", cookies={"auth_token": token})
        assert r.status_code == 200
        assert r.json()["status"] == "published"
    async with db_module.async_session_factory() as db:
        job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one()
        assert job.status == "published"
        assert job.last_reviewed_by == "reviewer@t.com"
        assert job.last_reviewed_on == date.today()
    await close_db()


@pytest.mark.asyncio
async def test_reject_requires_valid_reason():
    await _setup()
    _, token = await _mk_user("a@t.com", is_admin=True)
    job_id = await _mk_job()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r1 = await c.post(f"/admin/jobs/api/{job_id}/reject",
                          json={"reason": "bogus"}, cookies={"auth_token": token})
        assert r1.status_code == 400
        r2 = await c.post(f"/admin/jobs/api/{job_id}/reject",
                          json={"reason": "off_topic"}, cookies={"auth_token": token})
        assert r2.status_code == 200
        assert r2.json()["reason"] == "off_topic"
    await close_db()


@pytest.mark.asyncio
async def test_bulk_publish_tier1_only():
    """Tier-2 sources (or tier-1 without bulk_approve) cannot be bulk-published."""
    await _setup()
    _, token = await _mk_user("a@t.com", is_admin=True)
    t1 = await _mk_job(source="greenhouse:anthropic", tier=1, bulk=1, slug="t1", ext="a")
    t2 = await _mk_job(source="yc:aggregate", tier=2, bulk=0, slug="t2", ext="b")
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.post("/admin/jobs/api/bulk-publish",
                         json={"ids": [t1, t2]}, cookies={"auth_token": token})
        assert r.status_code == 400   # Tier-2 in batch blocks the whole call
        # Tier-1 alone works.
        r2 = await c.post("/admin/jobs/api/bulk-publish",
                          json={"ids": [t1]}, cookies={"auth_token": token})
        assert r2.status_code == 200
        assert r2.json()["published"] == 1
    await close_db()


@pytest.mark.asyncio
async def test_blocklist_company():
    await _setup()
    _, token = await _mk_user("a@t.com", is_admin=True)
    await _mk_job()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.post("/admin/jobs/api/companies/anthropic/blocklist",
                         json={"blocked": True, "reason": "test"},
                         cookies={"auth_token": token})
        assert r.status_code == 200
        assert r.json()["blocklisted"] is True
    async with db_module.async_session_factory() as db:
        co = (await db.execute(select(JobCompany).where(JobCompany.slug == "anthropic"))).scalar_one()
        assert co.blocklisted == 1
        assert co.blocklist_reason == "test"
    await close_db()


@pytest.mark.asyncio
async def test_queue_expired_reason_subfilter_and_24h_counter():
    """Phase 13.3: expired_reason param splits auto-expired vs date-based;
    auto_expired_24h counter surfaces source-removed flips for the banner chip."""
    await _setup()
    _, token = await _mk_user("a@t.com", is_admin=True)

    async with db_module.async_session_factory() as db:
        db.add(JobSource(key="greenhouse:anthropic", kind="greenhouse", label="X",
                         tier=1, enabled=1, bulk_approve=1))
        db.add(JobCompany(slug="anthropic", name="Anthropic"))
        # Auto-expired (source_removed) — counts toward 24h chip.
        db.add(Job(
            source="greenhouse:anthropic", external_id="auto-1", source_url="http://x",
            hash="h1", status="expired", posted_on=date.today(),
            valid_through=date.today() + timedelta(days=45),
            slug="auto-1", title="T", company_slug="anthropic", designation="ML Engineer",
            country="US", remote_policy="Hybrid", verified=1,
            data={"_meta": {"expired_reason": "source_removed", "expired_on": "2026-04-15"}},
        ))
        # Date-based expiry — no _meta.expired_reason.
        db.add(Job(
            source="greenhouse:anthropic", external_id="date-1", source_url="http://x",
            hash="h2", status="expired", posted_on=date.today() - timedelta(days=60),
            valid_through=date.today() - timedelta(days=15),
            slug="date-1", title="T", company_slug="anthropic", designation="ML Engineer",
            country="US", remote_policy="Hybrid", verified=1, data={},
        ))
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        # Default expired view: both jobs, auto-counter = 1.
        r = await c.get("/admin/jobs/api/queue?status=expired", cookies={"auth_token": token})
        assert r.status_code == 200
        d = r.json()
        assert d["auto_expired_24h"] == 1
        assert len(d["items"]) == 2

        # Sub-filter: only auto-expired.
        r = await c.get("/admin/jobs/api/queue?status=expired&expired_reason=source_removed",
                        cookies={"auth_token": token})
        assert [j["external_id"] for j in r.json()["items"]] == ["auto-1"]

        # Sub-filter: only date-based.
        r = await c.get("/admin/jobs/api/queue?status=expired&expired_reason=date_based",
                        cookies={"auth_token": token})
        assert [j["external_id"] for j in r.json()["items"]] == ["date-1"]
    await close_db()


@pytest.mark.asyncio
async def test_stats_reports_publish_rate_and_top_reasons():
    """#6 quality signal: 45d publish_rate + top_reject_reasons surface in /api/stats."""
    await _setup()
    _, token = await _mk_user("a@t.com", is_admin=True)
    async with db_module.async_session_factory() as db:
        db.add(JobSource(key="greenhouse:noisy", kind="greenhouse", label="Noisy",
                         tier=1, enabled=1))
        db.add(JobCompany(slug="noisy", name="Noisy Co"))
        # 1 published, 4 rejected — 20% rate, off_topic dominates.
        for ext, status, reason in [
            ("p1", "published", None),
            ("r1", "rejected", "off_topic"),
            ("r2", "rejected", "off_topic"),
            ("r3", "rejected", "off_topic"),
            ("r4", "rejected", "low_quality"),
        ]:
            db.add(Job(
                source="greenhouse:noisy", external_id=ext, source_url="u",
                hash=ext, status=status, posted_on=date.today(),
                valid_through=date.today() + timedelta(days=45),
                slug=ext, title="T", company_slug="noisy", designation="ML Engineer",
                country="US", remote_policy="Hybrid", verified=1,
                reject_reason=reason, data={},
            ))
        await db.commit()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/admin/jobs/api/stats", cookies={"auth_token": token})
        src = next(s for s in r.json()["sources"] if s["key"] == "greenhouse:noisy")
        assert src["publish_rate_45d"] == 0.20
        assert src["published_45d"] == 1
        assert src["rejected_45d"] == 4
        top = src["top_reject_reasons_45d"]
        assert top[0]["reason"] == "off_topic" and top[0]["count"] == 3
        assert top[1]["reason"] == "low_quality"
    await close_db()


@pytest.mark.asyncio
async def test_admin_queue_filters_by_city():
    """Admin city filter uses json_extract on data.location.city (case-insensitive)."""
    await _setup()
    _, token = await _mk_user("a@t.com", is_admin=True)
    async with db_module.async_session_factory() as db:
        db.add(JobSource(key="greenhouse:anthropic", kind="greenhouse", label="X",
                         tier=1, enabled=1, bulk_approve=1))
        db.add(JobCompany(slug="anthropic", name="Anthropic"))
        for ext, city in [("c1", "San Francisco"), ("c2", "Bengaluru")]:
            db.add(Job(
                source="greenhouse:anthropic", external_id=ext, source_url="http://x",
                hash=ext, status="draft", posted_on=date.today(),
                valid_through=date.today() + timedelta(days=45),
                slug=ext, title="T", company_slug="anthropic", designation="ML Engineer",
                country="US" if ext == "c1" else "IN", remote_policy="Hybrid", verified=1,
                data={"location": {"city": city, "country": "US" if ext == "c1" else "IN"}},
            ))
        await db.commit()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/admin/jobs/api/queue?status=draft&city=bengaluru",
                        cookies={"auth_token": token})
        assert [j["external_id"] for j in r.json()["items"]] == ["c2"]
    await close_db()


# ===================================================================
# Wave 5+ — /admin/jobs-guide page (Jinja2 migration, RCA-027 prevention)
# ===================================================================

@pytest.mark.asyncio
async def test_jobs_guide_renders_for_admin():
    """Migrated from f-string to Jinja2 template. Verify rendered HTML
    contains expected sections, no unrendered Jinja2 syntax leaked, and
    the literal JSON code samples (RCA-027 trigger) survive intact."""
    await _setup()
    _, token = await _mk_user("a@t.com", is_admin=True)
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/admin/jobs-guide", cookies={"auth_token": token})
        assert r.status_code == 200
        html = r.text
        # Page identity
        assert "Jobs Admin Guide" in html
        # All 9 TOC sections present
        for anchor in ("overview", "daily", "publish", "reject", "expire",
                       "other", "classification", "audit", "never"):
            assert f'id="{anchor}"' in html, f"missing section {anchor!r}"
        # The Wave 4 #16 sections that triggered RCA-027 must render with
        # SINGLE braces (not the f-string-doubled {{ }})
        assert "{job_id, agreed, opus_topic, opus_designation, notes}" in html
        assert '{"results":[' in html
        assert '{"job_id":20' in html
        # No unrendered Jinja2 syntax leaked
        assert "{{ admin_css" not in html
        assert "{{ admin_nav" not in html
        assert "{% " not in html  # Jinja2 tag delimiter shouldn't appear
        # CSS rules render with single braces
        assert ".guide h2 { margin-top:" in html
        # Admin nav is interpolated (not literal "{ADMIN_NAV}")
        assert "{ADMIN_NAV}" not in html
        assert "{ADMIN_CSS}" not in html
    await close_db()


@pytest.mark.asyncio
async def test_jobs_guide_requires_admin():
    """Non-admin users get 403 — same auth gate as before migration."""
    await _setup()
    _, token = await _mk_user("u@t.com", is_admin=False)
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/admin/jobs-guide", cookies={"auth_token": token})
        assert r.status_code == 403
    await close_db()


def test_jobs_guide_template_file_exists():
    """Sanity check: the template file is bundled with the deployment."""
    from pathlib import Path
    import app
    template = Path(app.__file__).parent / "templates" / "admin" / "jobs_guide.html"
    assert template.exists(), f"missing template: {template}"
    content = template.read_text(encoding="utf-8")
    # The file must use Jinja2 syntax, not f-string syntax
    assert "{{ admin_css | safe }}" in content
    assert "{{ admin_nav | safe }}" in content
    # The RCA-027 triggers (literal JSON in code blocks) must be SINGLE-braced
    # in the template — Jinja2 treats { as literal by default
    assert "<code>{job_id, agreed, opus_topic, opus_designation, notes}</code>" in content
    assert '<code>{"results":[...]}</code>' in content


def test_jobs_guide_template_renders_with_dummies():
    """Direct render test bypassing the FastAPI auth layer.
    Catches template-syntax bugs before they become 500s in prod."""
    from app.routers.admin import _admin_template_env, ADMIN_CSS, ADMIN_NAV
    html = _admin_template_env.get_template("admin/jobs_guide.html").render(
        admin_css=ADMIN_CSS, admin_nav=ADMIN_NAV,
    )
    # Sanity bounds — too short means the template silently failed
    assert 15000 < len(html) < 100000, f"unexpected length {len(html)}"
    assert html.strip().startswith("<!DOCTYPE html>")
    assert html.strip().endswith("</html>")


def test_legacy_jobs_guide_constant_removed():
    """Per CLAUDE.md 'no backwards-compatibility shims' — the legacy
    f-string constant must be fully removed, not kept as a fallback."""
    from app.routers import admin as admin_module
    assert not hasattr(admin_module, "_JOBS_GUIDE_HTML"), \
        "legacy f-string constant should be removed after Jinja2 migration"
    assert not hasattr(admin_module, "_JOBS_GUIDE_HTML_LEGACY"), \
        "legacy fallback constant should be removed (no compat shim)"
