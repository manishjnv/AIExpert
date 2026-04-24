"""SEO-20 + SEO-24 roadmap track page tests.

Acceptance per docs/SEO.md §SEO-20:
  - All 30 URLs return 200 with > 1000 visible words
  - Rich Results Test passes on one URL per page-type (verified by JSON-LD
    presence + parseability per page type)
  - Each URL surfaced in sitemap-pages.xml (jointly with /roadmap hub)
  - Salary pages refresh date controlled by data file (not yet wired to
    cron — covered by acceptance #4 follow-up)

Acceptance per docs/SEO.md §SEO-24:
  - /roadmap hub renders ItemList enumerating every track
"""

from __future__ import annotations

import html as html_lib
import json
import re
import xml.etree.ElementTree as ET

import pytest
from httpx import ASGITransport, AsyncClient

import app.db as db_module
import app.models  # noqa: F401
from app.db import Base, close_db, init_db
from app.routers.track_pages import (
    TRACK_ORDER,
    SECTION_TEMPLATES,
    _TRACKS_BY_SLUG,
)


SECTIONS = list(SECTION_TEMPLATES.keys())


async def _setup():
    await init_db(url="sqlite+aiosqlite:///:memory:")
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _app():
    from app.main import app
    return app


def _strip_html(html: str) -> str:
    """Crude HTML → plain-text for visible-word count. Drops <script> and
    <style> blocks completely so JSON-LD payload doesn't pad the count."""
    html = re.sub(r"<script\b[^>]*>.*?</script>", " ", html,
                  flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style\b[^>]*>.*?</style>", " ", html,
                  flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<[^>]+>", " ", html)
    html = re.sub(r"&[a-zA-Z#0-9]+;", " ", html)
    return re.sub(r"\s+", " ", html).strip()


def _ld_blocks(html: str) -> list[dict]:
    """Parse every <script type='application/ld+json'> block as JSON.
    Fails the test if any block is unparseable (the trailing-comma bug
    pattern is the most common culprit)."""
    raw = re.findall(
        r'<script type="application/ld\+json">(.*?)</script>',
        html, flags=re.DOTALL,
    )
    out: list[dict] = []
    for b in raw:
        try:
            out.append(json.loads(b))
        except json.JSONDecodeError as e:
            pytest.fail(f"Unparseable JSON-LD block: {e}\nBlock head: {b[:200]}")
    return out


# ---- Schema sanity (data files only, no HTTP needed) -----------------------


def test_five_tracks_loaded():
    """SEO-20 ships exactly 5 tracks initially, in canonical order."""
    assert TRACK_ORDER == [
        "generalist", "ai-engineer", "ml-engineer",
        "data-scientist", "mlops",
    ]
    assert set(_TRACKS_BY_SLUG.keys()) == set(TRACK_ORDER)


def test_six_sections_defined():
    """SEO-20 mandates 6 sub-pages per track."""
    assert set(SECTIONS) == {
        "skills", "tools", "projects",
        "certifications", "salary", "career-path",
    }


@pytest.mark.parametrize("slug", TRACK_ORDER)
def test_track_data_file_has_required_top_level_keys(slug):
    track = _TRACKS_BY_SLUG[slug]
    required = {
        "_meta", "slug", "name", "tagline", "hero_blurb",
        "weeks_total", "hours_per_week",
        "skills", "tools", "projects",
        "certifications", "salary", "career_path",
    }
    missing = required - set(track.keys())
    assert not missing, f"{slug} missing top-level keys: {missing}"
    assert track["slug"] == slug, f"{slug}: slug field mismatch"


@pytest.mark.parametrize("slug", TRACK_ORDER)
def test_every_section_has_at_least_seven_faqs(slug):
    """Match generalist.json's FAQ density baseline. FAQs feed the
    visible-word count and the FAQPage JSON-LD."""
    track = _TRACKS_BY_SLUG[slug]
    section_keys = ["skills", "tools", "projects",
                    "certifications", "salary", "career_path"]
    for k in section_keys:
        faqs = track[k].get("faqs", [])
        assert len(faqs) >= 7, \
            f"{slug}.{k} has {len(faqs)} FAQs (want >= 7)"
        for qa in faqs:
            assert "q" in qa and "a" in qa, \
                f"{slug}.{k} FAQ malformed: {qa}"


# ---- Hub page (SEO-24) -----------------------------------------------------


@pytest.mark.asyncio
async def test_roadmap_hub_returns_200():
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()),
                           base_url="http://t") as c:
        r = await c.get("/roadmap")
        assert r.status_code == 200
        assert "AI Learning Roadmaps 2026" in r.text
    await close_db()


@pytest.mark.asyncio
async def test_roadmap_hub_emits_itemlist_with_every_track():
    """SEO-24 acceptance: ItemList enumerates every track."""
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()),
                           base_url="http://t") as c:
        r = await c.get("/roadmap")
        blocks = _ld_blocks(r.text)
        item_lists = [b for b in blocks if b.get("@type") == "ItemList"]
        assert len(item_lists) == 1, \
            f"want exactly 1 ItemList on /roadmap, got {len(item_lists)}"
        items = item_lists[0]["itemListElement"]
        assert len(items) == len(TRACK_ORDER), \
            f"ItemList has {len(items)} entries, expected {len(TRACK_ORDER)}"
        urls = [it["url"] for it in items]
        for slug in TRACK_ORDER:
            assert any(u.endswith(f"/roadmap/{slug}") for u in urls), \
                f"{slug} missing from ItemList: {urls}"
    await close_db()


@pytest.mark.asyncio
async def test_roadmap_hub_canonical_present():
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()),
                           base_url="http://t") as c:
        r = await c.get("/roadmap")
        assert 'rel="canonical"' in r.text
        assert '/roadmap"' in r.text
    await close_db()


@pytest.mark.asyncio
async def test_roadmap_trailing_slash_works():
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()),
                           base_url="http://t") as c:
        r = await c.get("/roadmap/")
        assert r.status_code == 200
    await close_db()


# ---- Per-track hub ---------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("slug", TRACK_ORDER)
async def test_track_hub_returns_200_with_breadcrumb_schema(slug):
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()),
                           base_url="http://t") as c:
        r = await c.get(f"/roadmap/{slug}")
        assert r.status_code == 200
        blocks = _ld_blocks(r.text)
        types = [b.get("@type") for b in blocks]
        assert "Article" in types, f"{slug} hub missing Article schema"
        assert "ItemList" in types, f"{slug} hub missing ItemList schema"
        assert "BreadcrumbList" in types, \
            f"{slug} hub missing BreadcrumbList schema"
    await close_db()


# ---- Section pages (SEO-20 main acceptance) --------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("slug", TRACK_ORDER)
@pytest.mark.parametrize("section", SECTIONS)
async def test_section_page_returns_200_with_substantive_content(slug, section):
    """SEO-20 acceptance #1: All 30 URLs 200 with > 1000 visible words.
    Visible-word count excludes JSON-LD payload."""
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()),
                           base_url="http://t") as c:
        r = await c.get(f"/roadmap/{slug}/{section}")
        assert r.status_code == 200, \
            f"/roadmap/{slug}/{section} returned {r.status_code}"
        text = _strip_html(r.text)
        wc = len(text.split())
        assert wc >= 1000, \
            f"/roadmap/{slug}/{section} visible word count {wc} < 1000"
    await close_db()


@pytest.mark.asyncio
@pytest.mark.parametrize("slug", TRACK_ORDER)
@pytest.mark.parametrize("section", SECTIONS)
async def test_section_page_required_schemas_present(slug, section):
    """Every section page must emit Article + BreadcrumbList + FAQPage at
    minimum. Section-specific schemas (ItemList, HowTo, Dataset) checked
    in dedicated tests below."""
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()),
                           base_url="http://t") as c:
        r = await c.get(f"/roadmap/{slug}/{section}")
        blocks = _ld_blocks(r.text)
        types = [b.get("@type") for b in blocks]
        for needed in ("Article", "BreadcrumbList", "FAQPage"):
            assert needed in types, \
                f"/roadmap/{slug}/{section} missing {needed}: {types}"
    await close_db()


@pytest.mark.asyncio
@pytest.mark.parametrize("slug", TRACK_ORDER)
@pytest.mark.parametrize("section", SECTIONS)
async def test_section_page_canonical_matches_url(slug, section):
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()),
                           base_url="http://t") as c:
        r = await c.get(f"/roadmap/{slug}/{section}")
        assert 'rel="canonical"' in r.text
        assert f"/roadmap/{slug}/{section}" in r.text
    await close_db()


@pytest.mark.asyncio
@pytest.mark.parametrize("slug", TRACK_ORDER)
@pytest.mark.parametrize("section", SECTIONS)
async def test_faqs_render_visibly_matching_schema(slug, section):
    """Google requires FAQPage Questions to be visibly present. Every
    Question.name in the FAQPage JSON-LD must appear as <summary>."""
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()),
                           base_url="http://t") as c:
        r = await c.get(f"/roadmap/{slug}/{section}")
        unescaped = html_lib.unescape(r.text)
        blocks = _ld_blocks(r.text)
        faq = next((b for b in blocks if b.get("@type") == "FAQPage"), None)
        assert faq is not None, f"{slug}/{section}: FAQPage missing"
        for qa in faq["mainEntity"]:
            q = qa["name"]
            assert f"<summary>{q}</summary>" in unescaped, \
                f"{slug}/{section}: question not rendered visibly: {q}"
    await close_db()


@pytest.mark.asyncio
@pytest.mark.parametrize("slug", TRACK_ORDER)
async def test_career_path_emits_howto(slug):
    """Career-path uses HowTo schema (steps progression)."""
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()),
                           base_url="http://t") as c:
        r = await c.get(f"/roadmap/{slug}/career-path")
        blocks = _ld_blocks(r.text)
        types = [b.get("@type") for b in blocks]
        assert "HowTo" in types, f"{slug} career-path missing HowTo"
    await close_db()


@pytest.mark.asyncio
@pytest.mark.parametrize("slug", TRACK_ORDER)
async def test_salary_emits_dataset(slug):
    """Salary uses Dataset schema (per spec — embedded compensation data)."""
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()),
                           base_url="http://t") as c:
        r = await c.get(f"/roadmap/{slug}/salary")
        blocks = _ld_blocks(r.text)
        types = [b.get("@type") for b in blocks]
        assert "Dataset" in types, f"{slug} salary missing Dataset"
    await close_db()


# ---- 404 paths -------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_track_returns_404():
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()),
                           base_url="http://t") as c:
        r = await c.get("/roadmap/not-a-real-track")
        assert r.status_code == 404
    await close_db()


@pytest.mark.asyncio
async def test_unknown_section_returns_404():
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()),
                           base_url="http://t") as c:
        r = await c.get("/roadmap/generalist/not-a-section")
        assert r.status_code == 404
    await close_db()


# ---- Sitemap inclusion (SEO-20 acceptance #3) ------------------------------


@pytest.mark.asyncio
async def test_sitemap_pages_includes_roadmap_urls():
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()),
                           base_url="http://t") as c:
        r = await c.get("/sitemap-pages.xml")
        assert r.status_code == 200
        root = ET.fromstring(r.text)
        SM = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        locs = [u.find(f"{SM}loc").text for u in root.findall(f"{SM}url")]
        # Hub
        assert any(l.endswith("/roadmap") for l in locs), \
            "/roadmap hub not in sitemap"
        # Every track hub
        for slug in TRACK_ORDER:
            assert any(l.endswith(f"/roadmap/{slug}") for l in locs), \
                f"/roadmap/{slug} not in sitemap"
            for section in SECTIONS:
                assert any(l.endswith(f"/roadmap/{slug}/{section}")
                           for l in locs), \
                    f"/roadmap/{slug}/{section} not in sitemap"
    await close_db()
