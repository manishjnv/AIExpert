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
async def test_per_job_ssr_includes_breadcrumblist_jsonld():
    """SEO-08 — every published job page emits a BreadcrumbList JSON-LD
    block matching the visual breadcrumb (Home → AI & ML Jobs → {title}).
    The current page (last item) has no `item` URL per Google's spec."""
    await _setup()
    slug = await _seed()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get(f"/jobs/{slug}")
        assert r.status_code == 200
        body = r.text
        # Page now carries TWO JSON-LD blocks: JobPosting + BreadcrumbList
        blocks = re.findall(r'<script type="application/ld\+json">(.+?)</script>', body, re.S)
        assert len(blocks) >= 2, f"expected ≥2 JSON-LD blocks, found {len(blocks)}"
        parsed = [json.loads(b) for b in blocks]
        bc = next((p for p in parsed if p.get("@type") == "BreadcrumbList"), None)
        assert bc is not None, "BreadcrumbList JSON-LD missing"
        assert bc["@context"] == "https://schema.org"
        items = bc["itemListElement"]
        assert len(items) == 3
        assert items[0]["position"] == 1
        assert items[0]["name"] == "Home"
        assert items[0]["item"].endswith("/")
        assert items[1]["position"] == 2
        assert items[1]["name"] == "AI & ML Jobs"
        assert items[1]["item"].endswith("/jobs")
        assert items[2]["position"] == 3
        assert items[2]["name"] == "Senior ML Engineer"
        assert "item" not in items[2]
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
async def test_sitemap_index_accepts_head():
    """SEO validators (Bing, W3C) probe with HEAD before GET. Routes must
    answer 200 on HEAD, not 405."""
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.head("/sitemap_index.xml")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/xml")
    await close_db()


@pytest.mark.asyncio
async def test_sitemap_jobs_accepts_head():
    await _setup()
    await _seed(status="published", slug="pub-h", external_id="sh")
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.head("/sitemap-jobs.xml")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/xml")
    await close_db()


@pytest.mark.asyncio
async def test_indexnow_key_verify_404_when_unconfigured():
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/somerandomstring.txt")
        assert r.status_code == 404
    await close_db()


def _with_loc(slug: str, ext: str, country: str, city: str) -> dict:
    return dict(
        slug=slug, external_id=ext, country=country,
        data={
            "tldr": "t", "designation": "ML Engineer",
            "company": {"name": "Anthropic", "slug": "anthropic"},
            "location": {"country": country, "city": city, "remote_policy": "Hybrid"},
            "employment": {"job_type": "Full-time"},
            "must_have_skills": [], "description_html": "<p>X</p>", "apply_url": "http://x",
        },
    )


@pytest.mark.asyncio
async def test_api_jobs_filter_by_city():
    await _setup()
    await _seed(**_with_loc("sf-1", "c1", "US", "San Francisco"))
    await _seed(**_with_loc("blr-1", "c2", "IN", "Bengaluru"))
    await _seed(**_with_loc("sf-2", "c3", "US", "San Francisco"))
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/api/jobs?city=Bengaluru")
        assert [it["slug"] for it in r.json()] == ["blr-1"]
        # Case-insensitive.
        r2 = await c.get("/api/jobs?city=san francisco")
        assert sorted(it["slug"] for it in r2.json()) == ["sf-1", "sf-2"]
        # City + country combined.
        r3 = await c.get("/api/jobs?country=US&city=San Francisco")
        assert len(r3.json()) == 2
    await close_db()


@pytest.mark.asyncio
async def test_draft_preview_requires_admin():
    """Draft jobs are 404 to public + anon, but viewable with ?preview=1 + admin cookie."""
    from app.auth.jwt import issue_token
    from app.models.user import User
    await _setup()
    slug = await _seed(status="draft", slug="prev-x", external_id="pv1")

    # Seed admin + non-admin users.
    async with db_module.async_session_factory() as db:
        admin = User(email="admin@t.com", provider="otp", is_admin=True, name="a")
        reg = User(email="u@t.com", provider="otp", is_admin=False, name="u")
        db.add_all([admin, reg])
        await db.flush()
        admin_token = await issue_token(admin, db)
        user_token = await issue_token(reg, db)
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        # Anonymous: 404.
        assert (await c.get(f"/jobs/{slug}")).status_code == 404
        # Anonymous with preview flag: still 404.
        assert (await c.get(f"/jobs/{slug}?preview=1")).status_code == 404
        # Non-admin with preview: still 404.
        r = await c.get(f"/jobs/{slug}?preview=1", cookies={"auth_token": user_token})
        assert r.status_code == 404
        # Admin with preview: 200 + banner + noindex.
        r = await c.get(f"/jobs/{slug}?preview=1", cookies={"auth_token": admin_token})
        assert r.status_code == 200
        assert "ADMIN PREVIEW" in r.text
        assert 'name="robots" content="noindex"' in r.text
        # Admin without preview flag: 404 (preview is explicit).
        r = await c.get(f"/jobs/{slug}", cookies={"auth_token": admin_token})
        assert r.status_code == 404
    await close_db()


@pytest.mark.asyncio
async def test_job_detail_shows_highlights_and_collapsible_jd():
    """Published page renders the highlights grid + collapsible JD wrapper."""
    await _setup()
    slug = await _seed()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        body = (await c.get(f"/jobs/{slug}")).text
        assert 'class="hl-grid"' in body
        assert 'class="jd-wrap"' in body
        # Salary highlight pulled from enrichment.
        assert "USD" in body
    await close_db()


@pytest.mark.asyncio
async def test_api_jobs_locations_aggregates_counts():
    await _setup()
    await _seed(**_with_loc("sf-1", "l1", "US", "San Francisco"))
    await _seed(**_with_loc("sf-2", "l2", "US", "San Francisco"))
    await _seed(**_with_loc("blr-1", "l3", "IN", "Bengaluru"))
    # Draft must NOT leak into public locations.
    await _seed(status="draft", **_with_loc("drft-x", "l4", "DE", "Berlin"))
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/api/jobs/locations")
        assert r.status_code == 200
        d = r.json()
        country_map = {c["code"]: c["count"] for c in d["countries"]}
        assert country_map == {"US": 2, "IN": 1}
        city_map = {c["name"]: c["count"] for c in d["cities"]}
        assert city_map == {"San Francisco": 2, "Bengaluru": 1}
    await close_db()
