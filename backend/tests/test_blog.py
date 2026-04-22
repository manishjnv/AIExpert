"""Blog router tests — covers the Jinja2-migrated per-post template
(SEO-06 Commit A). The previous implementation was an f-string in
routers/blog.py:_render_post, which would crash module import on any
literal { } in code samples / JSON / JS (RCA-027 pattern). The migration
moved the template to backend/app/templates/blog/post.html where { is
literal by default."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

import app.db as db_module
import app.models  # noqa: F401
from app.db import Base, close_db, init_db


async def _setup():
    await init_db(url="sqlite+aiosqlite:///:memory:")
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _app():
    from app.main import app
    return app


# --- Migration regression tests (Commit A) ------------------------------------


@pytest.mark.asyncio
async def test_post_01_renders_via_jinja2_template(monkeypatch):
    """Hardcoded /blog/01 still renders 200 with all expected sections,
    no Jinja2 syntax leaks into the rendered HTML, and the inline JS
    block (which had {{ }} f-string escapes pre-migration) emits with
    single braces."""
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: False)
    monkeypatch.setattr("app.services.blog_publisher.list_published", lambda: [])
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/blog/01")
        assert r.status_code == 200
        html = r.text
        # Page identity — title interpolated, breadcrumb structure intact
        assert "Building AutomateEdge Solo" in html
        assert '<nav class="post-breadcrumb"' in html
        assert "Published 2026-04-13" in html
        # Body HTML rendered raw (not escaped)
        assert "<h2>Why this exists</h2>" in html
        # Meta + OG tags carry through
        assert '<meta property="og:type" content="article">' in html
        assert '<meta property="article:published_time" content="2026-04-13T00:00:00Z">' in html
        # No unrendered Jinja2 syntax leaked
        assert "{{ title" not in html
        assert "{{ body_html" not in html
        assert "{{ blog_css" not in html
        assert "{% " not in html
        # Inline JS rendered with SINGLE braces — the f-string-doubled
        # {{ }} sequences became {  } in the migrated template
        assert "(function() {" in html
        assert "})();" in html
        assert "{ passive: true }" in html
    await close_db()


@pytest.mark.asyncio
async def test_post_dynamic_renders_via_jinja2_template(monkeypatch):
    """Dynamic /blog/{slug} path renders the same migrated template
    when load_published returns a payload."""
    fake_payload = {
        "slug": "test-slug",
        "title": "Test Post Title",
        "og_description": "A test post description.",
        "body_html": "<p>Body of the test post.</p><h2>Section</h2>",
        "published": "2026-04-22",
    }
    monkeypatch.setattr(
        "app.services.blog_publisher.load_published",
        lambda s: fake_payload if s == "test-slug" else None,
    )
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: False)
    monkeypatch.setattr("app.services.blog_publisher.list_published", lambda: [fake_payload])
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/blog/test-slug")
        assert r.status_code == 200
        html = r.text
        assert "Test Post Title" in html
        assert "Body of the test post." in html
        assert '<meta name="description" content="A test post description.">' in html
        assert '<meta property="article:published_time" content="2026-04-22T00:00:00Z">' in html
        # No template-syntax leakage
        assert "{{ " not in html
        assert "{% " not in html
    await close_db()


@pytest.mark.asyncio
async def test_post_unknown_slug_returns_404(monkeypatch):
    """Slug that load_published can't resolve still returns 404 — the
    migration must not have changed routing behavior."""
    monkeypatch.setattr("app.services.blog_publisher.load_published", lambda s: None)
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/blog/does-not-exist")
        assert r.status_code == 404
    await close_db()


@pytest.mark.asyncio
async def test_post_01_legacy_hidden_returns_404(monkeypatch):
    """Admin can hide POST_01 via the legacy-hidden flag; that path
    must still 404 after the migration."""
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: s == "01")
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/blog/01")
        assert r.status_code == 404
    await close_db()


# --- Template-file structural assertions --------------------------------------


def test_blog_post_template_file_exists_and_uses_jinja2_syntax():
    """The template file is bundled with the deployment and uses Jinja2
    syntax — { is literal, {{ var }} is interpolation. This is the core
    RCA-027 prevention guarantee."""
    from pathlib import Path
    import app
    template = Path(app.__file__).parent / "templates" / "blog" / "post.html"
    assert template.exists(), f"missing template: {template}"
    content = template.read_text(encoding="utf-8")
    # Required Jinja2 interpolations
    assert "{{ title }}" in content
    assert "{{ description }}" in content
    assert "{{ blog_css | safe }}" in content
    assert "{{ body_html | safe }}" in content
    assert "{{ sidebar_html | safe }}" in content
    assert "{{ post_nav_html | safe }}" in content
    # The inline JS must use SINGLE braces (Jinja2 treats { as literal)
    assert "(function() {" in content
    assert "{ passive: true }" in content
    # SEO-06 — Article JSON-LD block present in <head>, every value
    # routed through `tojson` so quotes/`</`/control chars can't break it
    assert '<script type="application/ld+json">' in content
    assert '"@type": "Article"' in content
    assert "{{ title | tojson }}" in content
    assert "{{ author | tojson }}" in content
    assert "{{ description | tojson }}" in content
    # SEO-08 — BreadcrumbList JSON-LD block present, current page (last
    # item) has no `item` URL per Google's spec
    assert '"@type": "BreadcrumbList"' in content
    assert '"position": 1' in content
    assert '"position": 2' in content
    assert '"position": 3' in content


# --- Article JSON-LD assertion tests (Commit B / SEO-06) ---------------------


def _extract_jsonld(html: str) -> dict:
    """Pull the Article JSON-LD block out of rendered HTML and parse it.
    Asserts the script tag is present so tests fail with a clear message
    if the template ever drops the block."""
    import json
    import re
    m = re.search(
        r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>',
        html,
        re.DOTALL,
    )
    assert m, "Article JSON-LD <script> block not found in rendered HTML"
    return json.loads(m.group(1))


def _extract_all_jsonld(html: str) -> list[dict]:
    """Pull EVERY JSON-LD block out of rendered HTML — pages can carry
    multiple types (Article + BreadcrumbList in our case)."""
    import json
    import re
    matches = re.findall(
        r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>',
        html,
        re.DOTALL,
    )
    assert matches, "no JSON-LD <script> blocks found"
    return [json.loads(m) for m in matches]


@pytest.mark.asyncio
async def test_post_01_article_json_ld_emitted(monkeypatch):
    """SEO-06 acceptance — /blog/01 emits Article JSON-LD with the full
    property set Google requires for rich-result eligibility."""
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: False)
    monkeypatch.setattr("app.services.blog_publisher.list_published", lambda: [])
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/blog/01")
        assert r.status_code == 200
        data = _extract_jsonld(r.text)
        assert data["@context"] == "https://schema.org"
        assert data["@type"] == "Article"
        assert data["headline"] == (
            "Building AutomateEdge Solo — A Free, AI-Curated Learning Platform"
        )
        # ISO 8601 — Z-suffixed UTC, matching the og article:published_time tag
        assert data["datePublished"] == "2026-04-13T00:00:00Z"
        # dateModified falls back to datePublished (TODO in template — payloads
        # don't yet track updated_at; documented in template comment)
        assert data["dateModified"] == "2026-04-13T00:00:00Z"
        assert data["author"] == {"@type": "Person", "name": "Manish Kumar"}
        assert data["publisher"]["@type"] == "Organization"
        assert data["publisher"]["name"] == "AutomateEdge"
        assert data["publisher"]["logo"]["url"] == (
            "https://automateedge.cloud/assets/logo.png"
        )
        assert data["image"].endswith("/assets/og-default.png")
        assert data["mainEntityOfPage"].endswith("/blog/01")
        assert data["description"].startswith("Why AutomateEdge exists")
        # Headline must stay ≤110 chars per Google guideline
        assert len(data["headline"]) <= 110, f"headline too long: {len(data['headline'])}"
    await close_db()


@pytest.mark.asyncio
async def test_post_dynamic_article_json_ld_uses_payload_author(monkeypatch):
    """Dynamic posts surface the payload's `author` field in JSON-LD,
    not the meta-tag hardcoded 'Manish Kumar'. Confirms the author
    plumbing _render_post -> template was actually wired."""
    fake_payload = {
        "slug": "guest-post",
        "title": "A Guest Post With Quotes \"Like This\" and < Special Chars",
        "og_description": "A description with a quote: \"foo\".",
        "body_html": "<p>Body</p>",
        "published": "2026-05-01",
        "author": "Guest Author",
    }
    monkeypatch.setattr(
        "app.services.blog_publisher.load_published",
        lambda s: fake_payload if s == "guest-post" else None,
    )
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: False)
    monkeypatch.setattr("app.services.blog_publisher.list_published", lambda: [fake_payload])
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/blog/guest-post")
        assert r.status_code == 200
        data = _extract_jsonld(r.text)
        # Author from payload (not the meta-tag hardcoded "Manish Kumar")
        assert data["author"]["name"] == "Guest Author"
        # Quotes + special chars in headline survive JSON-encoding intact
        assert data["headline"] == (
            "A Guest Post With Quotes \"Like This\" and < Special Chars"
        )
        assert data["description"] == "A description with a quote: \"foo\"."
        assert data["datePublished"] == "2026-05-01T00:00:00Z"
        assert data["dateModified"] == "2026-05-01T00:00:00Z"
    await close_db()


@pytest.mark.asyncio
async def test_post_breadcrumb_list_json_ld_emitted(monkeypatch):
    """SEO-08 — every blog post emits a BreadcrumbList JSON-LD block
    matching the visual breadcrumb (Home → Blog → {title}). Last item
    has no `item` URL per Google's spec."""
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: False)
    monkeypatch.setattr("app.services.blog_publisher.list_published", lambda: [])
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/blog/01")
        assert r.status_code == 200
        all_blocks = _extract_all_jsonld(r.text)
        # Two blocks expected: Article + BreadcrumbList
        types = [b.get("@type") for b in all_blocks]
        assert "Article" in types
        assert "BreadcrumbList" in types
        bc = next(b for b in all_blocks if b["@type"] == "BreadcrumbList")
        assert bc["@context"] == "https://schema.org"
        items = bc["itemListElement"]
        assert len(items) == 3
        assert items[0] == {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://automateedge.cloud/"}
        assert items[1] == {"@type": "ListItem", "position": 2, "name": "Blog", "item": "https://automateedge.cloud/blog"}
        # Current page item: name only, no `item` URL (Google spec — last
        # crumb is the page itself, doesn't link anywhere)
        assert items[2]["@type"] == "ListItem"
        assert items[2]["position"] == 3
        assert items[2]["name"] == (
            "Building AutomateEdge Solo — A Free, AI-Curated Learning Platform"
        )
        assert "item" not in items[2]
    await close_db()


@pytest.mark.asyncio
async def test_post_article_json_ld_safe_against_script_injection(monkeypatch):
    """Defensive: a malicious title containing </script> must not break
    out of the JSON-LD <script> block. Jinja2's tojson encodes < as
    \\u003c which neutralizes the tag-close attempt."""
    fake_payload = {
        "slug": "evil",
        "title": "Sneaky </script><script>alert(1)</script>",
        "og_description": "desc",
        "body_html": "<p>body</p>",
        "published": "2026-01-01",
        "author": "evil",
    }
    monkeypatch.setattr(
        "app.services.blog_publisher.load_published",
        lambda s: fake_payload if s == "evil" else None,
    )
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: False)
    monkeypatch.setattr("app.services.blog_publisher.list_published", lambda: [fake_payload])
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/blog/evil")
        assert r.status_code == 200
        # The literal "</script>" sequence must NOT appear inside the
        # JSON-LD block — Jinja2's tojson escapes < to <
        import re
        m = re.search(
            r'<script type="application/ld\+json">(.*?)</script>',
            r.text,
            re.DOTALL,
        )
        assert m, "JSON-LD block missing"
        jsonld_body = m.group(1)
        assert "</script>" not in jsonld_body
        assert "\\u003c" in jsonld_body or "\\u003C" in jsonld_body
        # The JSON itself still parses cleanly even with the malicious payload
        data = _extract_jsonld(r.text)
        assert "Sneaky" in data["headline"]
    await close_db()


def test_blog_post_template_renders_with_dummies():
    """Direct render bypassing FastAPI — catches template-syntax bugs
    before they become 500s in prod (mirrors the admin/jobs_guide
    sanity test added for RCA-027 prevention)."""
    from app.routers.blog import _blog_template_env, _BLOG_CSS
    html = _blog_template_env.get_template("blog/post.html").render(
        title="Hello",
        description="A description",
        url="https://example.com/blog/x",
        og_image="https://example.com/og.png",
        published="2026-01-01",
        author="Test Author",
        blog_css=_BLOG_CSS,
        body_html="<p>body</p>",
        sidebar_html="<div>side</div>",
        post_nav_html="<nav>nav</nav>",
    )
    assert html.strip().startswith("<!DOCTYPE html>")
    assert html.strip().endswith("</html>")
    assert "<title>Hello — AutomateEdge</title>" in html
    assert "<p>body</p>" in html
    assert "<div>side</div>" in html
    assert "<nav>nav</nav>" in html
    # Sanity bound — silently empty render would mean template was misnamed
    assert 5000 < len(html) < 50000, f"unexpected render length {len(html)}"
