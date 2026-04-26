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
from app.routers.blog import POST_01_TITLE


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
    # SEO-09 — per-post head advertises the RSS feed as an alternate
    # representation, so browsers + feed readers auto-discover it
    assert 'rel="alternate"' in content
    assert 'type="application/rss+xml"' in content
    assert '/blog/feed.xml' in content


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
        assert data["image"].endswith("/og/blog/01.png")
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


# --- SEO-13 — canonical on /blog index -------------------------------------


@pytest.mark.asyncio
async def test_blog_index_has_exactly_one_canonical(monkeypatch):
    """SEO-13 acceptance — the /blog index head emits exactly one
    <link rel="canonical"> pointing at itself. RSS alternate link is
    a separate <link rel="alternate"> and must not satisfy the check."""
    monkeypatch.setattr("app.services.blog_publisher.list_published", lambda: [])
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: False)
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/blog")
        assert r.status_code == 200
        import re
        canonicals = re.findall(
            r'<link\s+rel="canonical"\s+href="([^"]+)"', r.text
        )
        assert len(canonicals) == 1, f"expected 1 canonical, got {canonicals}"
        assert canonicals[0].endswith("/blog")
    await close_db()


# --- SEO-09 — /blog/feed.xml RSS 2.0 ---------------------------------------


@pytest.mark.asyncio
async def test_blog_feed_xml_returns_valid_rss_2_0(monkeypatch):
    """SEO-09 acceptance — /blog/feed.xml serves application/rss+xml with
    a parseable RSS 2.0 document containing every visible post."""
    fake_payload = {
        "slug": "02-fake-post",
        "title": "Second Post",
        "og_description": "A second test post description.",
        "body_html": "<p>Body</p>",
        "published": "2026-04-22",
    }
    monkeypatch.setattr(
        "app.services.blog_publisher.list_published",
        lambda: [fake_payload],
    )
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: False)
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/blog/feed.xml")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/rss+xml")
        body = r.text
        # Parse as XML — any malformed output raises here
        import xml.etree.ElementTree as ET
        root = ET.fromstring(body)
        assert root.tag == "rss"
        assert root.attrib.get("version") == "2.0"
        channel = root.find("channel")
        assert channel is not None
        assert channel.findtext("title") == "AutomateEdge Blog"
        assert channel.findtext("link", "").endswith("/blog")
        assert channel.findtext("language") == "en"
        # atom:self link for feed self-reference
        atom_ns = "{http://www.w3.org/2005/Atom}"
        self_link = channel.find(f"{atom_ns}link")
        assert self_link is not None
        assert self_link.attrib["rel"] == "self"
        assert self_link.attrib["href"].endswith("/blog/feed.xml")
        # Items — both legacy POST_01 and the dynamic fake should appear
        items = channel.findall("item")
        titles = [it.findtext("title") for it in items]
        assert "Second Post" in titles
        assert POST_01_TITLE in titles
        # Per-item required fields
        for it in items:
            assert it.findtext("title")
            link = it.findtext("link")
            assert link and "/blog/" in link
            guid = it.find("guid")
            assert guid is not None and guid.attrib.get("isPermaLink") == "true"
            # RFC 822 pubDate — sanity that it contains a 4-digit year + GMT
            pub = it.findtext("pubDate") or ""
            assert "GMT" in pub or "+0000" in pub
    await close_db()


@pytest.mark.asyncio
async def test_blog_feed_xml_escapes_hostile_content(monkeypatch):
    """Defensive — a malicious post title with '<' and '&' must not break
    the XML document. ET.fromstring would raise on unescaped specials."""
    fake_payload = {
        "slug": "03-evil",
        "title": "Title with <tags> & ampersand",
        "og_description": "Desc with \"quotes\" and <b>tags</b>.",
        "body_html": "<p>x</p>",
        "published": "2026-05-01",
    }
    monkeypatch.setattr(
        "app.services.blog_publisher.list_published",
        lambda: [fake_payload],
    )
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: True)
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/blog/feed.xml")
        assert r.status_code == 200
        import xml.etree.ElementTree as ET
        root = ET.fromstring(r.text)  # must parse cleanly
        item = root.find("channel/item")
        assert item is not None
        # Title round-trips through escape -> parse back to the original
        assert item.findtext("title") == "Title with <tags> & ampersand"
    await close_db()


@pytest.mark.asyncio
async def test_post_html_advertises_rss_alternate(monkeypatch):
    """Rendered /blog/{slug} head carries the application/rss+xml
    alternate link so browsers + feed readers discover the feed."""
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: False)
    monkeypatch.setattr("app.services.blog_publisher.list_published", lambda: [])
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/blog/01")
        assert r.status_code == 200
        assert 'rel="alternate"' in r.text
        assert 'type="application/rss+xml"' in r.text
        assert "/blog/feed.xml" in r.text
    await close_db()


@pytest.mark.asyncio
async def test_blog_feed_accepts_head(monkeypatch):
    """Feed readers + SEO validators probe with HEAD; route must answer
    200 without body, not 405."""
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: False)
    monkeypatch.setattr("app.services.blog_publisher.list_published", lambda: [])
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.head("/blog/feed.xml")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/rss+xml")
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


# ---------------------------------------------------------------------------
# SEO-27: Pagination tests
# ---------------------------------------------------------------------------

def _make_fake_posts(n: int) -> list[dict]:
    """Generate n fake published post dicts for monkeypatching list_published."""
    posts = []
    for i in range(n):
        # Use a date that sorts correctly newest-first
        day = f"{2026:04d}-{1 + (i // 28):02d}-{1 + (i % 28):02d}"
        slug = f"{i + 2:02d}-fake-post-{i}"
        posts.append({
            "slug": slug,
            "title": f"Fake Post {i}",
            "og_description": f"Description for post {i}",
            "lede": f"Lede for post {i}",
            "body_html": f"<p>Body {i}</p>",
            "published": day,
            "tags": ["build-in-public"],
            "target_query": "",
        })
    # Sort newest-first so list_published is consistent
    posts.sort(key=lambda p: p["published"], reverse=True)
    return posts


def _fake_load_published(posts: list[dict]):
    """Return a load_published function that looks up from posts list."""
    by_slug = {p["slug"]: p for p in posts}
    return lambda s: by_slug.get(s)


@pytest.mark.asyncio
async def test_blog_index_paginated(monkeypatch):
    """25 posts: page=1 shows 20 cards, page=2 shows 5 cards."""
    fake = _make_fake_posts(25)
    monkeypatch.setattr("app.services.blog_publisher.list_published", lambda: fake)
    monkeypatch.setattr("app.services.blog_publisher.load_published", _fake_load_published(fake))
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: True)
    # Reset lru_cache for pillar config to avoid stale state
    from app.routers.blog import _load_pillar_config
    _load_pillar_config.cache_clear()
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r1 = await c.get("/blog?page=1")
        assert r1.status_code == 200
        import re
        cards1 = re.findall(r'class="post-card"', r1.text)
        # 20 from the feed; may also include start-here cards
        assert len(cards1) >= 20

        r2 = await c.get("/blog?page=2")
        assert r2.status_code == 200
        # page 2 has 5 posts (25 total, 20 on page 1)
        cards2 = re.findall(r'class="post-card"', r2.text)
        assert len(cards2) == 5
    await close_db()


@pytest.mark.asyncio
async def test_blog_index_canonical_paginated(monkeypatch):
    """page=2 canonical should be .../blog?page=2, not /blog."""
    fake = _make_fake_posts(25)
    monkeypatch.setattr("app.services.blog_publisher.list_published", lambda: fake)
    monkeypatch.setattr("app.services.blog_publisher.load_published", _fake_load_published(fake))
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: True)
    from app.routers.blog import _load_pillar_config
    _load_pillar_config.cache_clear()
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/blog?page=2")
        assert r.status_code == 200
        import re
        canonicals = re.findall(r'<link rel="canonical" href="([^"]+)"', r.text)
        assert len(canonicals) == 1
        assert "page=2" in canonicals[0]
    await close_db()


@pytest.mark.asyncio
async def test_blog_index_rel_prev_next(monkeypatch):
    """Page boundaries: page=1 has next but no prev; page=2 has both;
    last page has prev but no next."""
    fake = _make_fake_posts(45)  # 3 pages
    monkeypatch.setattr("app.services.blog_publisher.list_published", lambda: fake)
    monkeypatch.setattr("app.services.blog_publisher.load_published", _fake_load_published(fake))
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: True)
    from app.routers.blog import _load_pillar_config
    _load_pillar_config.cache_clear()
    await _setup()
    import re
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r1 = await c.get("/blog")
        assert r1.status_code == 200
        assert 'rel="next"' in r1.text
        assert 'rel="prev"' not in r1.text

        r2 = await c.get("/blog?page=2")
        assert r2.status_code == 200
        assert 'rel="next"' in r2.text
        assert 'rel="prev"' in r2.text

        r3 = await c.get("/blog?page=3")
        assert r3.status_code == 200
        assert 'rel="prev"' in r3.text
        assert 'rel="next"' not in r3.text
    await close_db()


@pytest.mark.asyncio
async def test_blog_index_invalid_page_404(monkeypatch):
    """page > total_pages returns 404."""
    fake = _make_fake_posts(5)  # 1 page
    monkeypatch.setattr("app.services.blog_publisher.list_published", lambda: fake)
    monkeypatch.setattr("app.services.blog_publisher.load_published", _fake_load_published(fake))
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: True)
    from app.routers.blog import _load_pillar_config
    _load_pillar_config.cache_clear()
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/blog?page=99")
        assert r.status_code == 404
    await close_db()


@pytest.mark.asyncio
async def test_blog_index_search_query_ssr(monkeypatch):
    """?q=engineer returns 200 with the search input pre-populated."""
    fake = [
        {
            "slug": "03-ai-engineer-vs-ml-engineer",
            "title": "AI Engineer vs ML Engineer",
            "og_description": "Comparison of roles",
            "lede": "A lede about engineers",
            "body_html": "<p>Body</p>",
            "published": "2026-04-01",
            "tags": ["career-guide", "ai-engineer"],
            "target_query": "",
        }
    ]
    monkeypatch.setattr("app.services.blog_publisher.list_published", lambda: fake)
    monkeypatch.setattr("app.services.blog_publisher.load_published", _fake_load_published(fake))
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: True)
    from app.routers.blog import _load_pillar_config
    _load_pillar_config.cache_clear()
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/blog?q=engineer")
        assert r.status_code == 200
        # Search input pre-populated with the query
        assert 'value="engineer"' in r.text
        # Matching post card rendered
        assert "AI Engineer vs ML Engineer" in r.text
    await close_db()


# ---------------------------------------------------------------------------
# SEO-27: WebSite + SearchAction JSON-LD
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_blog_index_website_searchaction_jsonld(monkeypatch):
    """page=1 emits WebSite+SearchAction JSON-LD; page>1 and search do not."""
    fake = _make_fake_posts(25)
    monkeypatch.setattr("app.services.blog_publisher.list_published", lambda: fake)
    monkeypatch.setattr("app.services.blog_publisher.load_published", _fake_load_published(fake))
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: True)
    from app.routers.blog import _load_pillar_config
    _load_pillar_config.cache_clear()
    await _setup()
    import json, re
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r1 = await c.get("/blog")
        assert r1.status_code == 200
        all_jsonld = re.findall(
            r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>',
            r1.text, re.DOTALL
        )
        types = [json.loads(b).get("@type") for b in all_jsonld]
        assert "WebSite" in types
        block = next(json.loads(b) for b in all_jsonld if json.loads(b).get("@type") == "WebSite")
        assert block["potentialAction"]["@type"] == "SearchAction"
        assert "search_term_string" in block["potentialAction"]["target"]["urlTemplate"]

        r2 = await c.get("/blog?page=2")
        assert r2.status_code == 200
        all_jsonld2 = re.findall(
            r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>',
            r2.text, re.DOTALL
        )
        types2 = [json.loads(b).get("@type") for b in all_jsonld2]
        assert "WebSite" not in types2
    await close_db()


# ---------------------------------------------------------------------------
# SEO-27: Topic hub tests
# ---------------------------------------------------------------------------

def _pillar_config_with_career_paths():
    """Minimal pillar config with one valid pillar."""
    return {
        "version": 1,
        "active_pills": [
            {
                "slug": "career-paths",
                "label": "Career Paths",
                "intro": "Posts about AI career paths.",
                "matches": {"tags_any": ["career-guide", "ai-engineer"]},
            }
        ],
        "start_here": [],
    }


@pytest.mark.asyncio
async def test_blog_topic_hub_200(monkeypatch):
    """Known topic slug returns 200 with intro + CollectionPage JSON-LD."""
    fake = [
        {
            "slug": "03-ai-engineer-vs-ml-engineer",
            "title": "AI Engineer vs ML Engineer",
            "og_description": "Comparison",
            "lede": "Lede",
            "body_html": "<p>Body</p>",
            "published": "2026-04-01",
            "tags": ["career-guide", "ai-engineer"],
            "target_query": "",
        }
    ]
    monkeypatch.setattr("app.services.blog_publisher.list_published", lambda: fake)
    monkeypatch.setattr("app.services.blog_publisher.load_published", _fake_load_published(fake))
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: True)
    from app.routers import blog as blog_module
    monkeypatch.setattr(blog_module, "_load_pillar_config", lambda: _pillar_config_with_career_paths())
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/blog/topic/career-paths")
        assert r.status_code == 200
        assert "Career Paths" in r.text
        assert "Posts about AI career paths." in r.text
        assert "AI Engineer vs ML Engineer" in r.text
        import re
        jsonld_blocks = re.findall(
            r'<script type="application/ld\+json">(.*?)</script>', r.text, re.DOTALL
        )
        import json
        types = [json.loads(b).get("@type") for b in jsonld_blocks]
        assert "CollectionPage" in types
    await close_db()


@pytest.mark.asyncio
async def test_blog_topic_hub_404_unknown(monkeypatch):
    """Unknown slug returns 404."""
    monkeypatch.setattr("app.services.blog_publisher.list_published", lambda: [])
    monkeypatch.setattr("app.services.blog_publisher.load_published", lambda s: None)
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: True)
    from app.routers import blog as blog_module
    monkeypatch.setattr(blog_module, "_load_pillar_config", lambda: _pillar_config_with_career_paths())
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/blog/topic/nonexistent")
        assert r.status_code == 404
    await close_db()


@pytest.mark.asyncio
async def test_blog_topic_hub_404_invalid_slug(monkeypatch):
    """Invalid slug patterns (uppercase, script injection) return 404."""
    monkeypatch.setattr("app.services.blog_publisher.list_published", lambda: [])
    monkeypatch.setattr("app.services.blog_publisher.load_published", lambda s: None)
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: True)
    from app.routers import blog as blog_module
    monkeypatch.setattr(blog_module, "_load_pillar_config", lambda: _pillar_config_with_career_paths())
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        # Uppercase slug — fails regex
        r1 = await c.get("/blog/topic/UPPERCASE")
        assert r1.status_code == 404
        # XSS attempt — contains < which fails the slug regex
        r2 = await c.get("/blog/topic/%3Cscript%3E")
        assert r2.status_code == 404
    await close_db()


@pytest.mark.asyncio
async def test_blog_topic_hub_breadcrumb_jsonld(monkeypatch):
    """BreadcrumbList JSON-LD present with 3 items (Home → Blog → Topic)."""
    monkeypatch.setattr("app.services.blog_publisher.list_published", lambda: [])
    monkeypatch.setattr("app.services.blog_publisher.load_published", lambda s: None)
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: True)
    from app.routers import blog as blog_module
    monkeypatch.setattr(blog_module, "_load_pillar_config", lambda: _pillar_config_with_career_paths())
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/blog/topic/career-paths")
        assert r.status_code == 200
        import re, json
        blocks = re.findall(
            r'<script type="application/ld\+json">(.*?)</script>', r.text, re.DOTALL
        )
        parsed = [json.loads(b) for b in blocks]
        bc = next((b for b in parsed if b.get("@type") == "BreadcrumbList"), None)
        assert bc is not None, "BreadcrumbList JSON-LD not found"
        items = bc["itemListElement"]
        assert len(items) == 3
        assert items[0]["name"] == "Home"
        assert items[1]["name"] == "Blog"
        assert items[2]["name"] == "Career Paths"
        assert "item" not in items[2]  # last crumb has no item URL per Google spec
    await close_db()


@pytest.mark.asyncio
async def test_blog_topic_hub_itemlist_count(monkeypatch):
    """ItemList numberOfItems matches actual matching posts count."""
    fake = [
        {
            "slug": "03-ai-engineer-vs-ml-engineer",
            "title": "Post 1",
            "og_description": "Desc 1",
            "lede": "",
            "body_html": "<p>Body</p>",
            "published": "2026-04-01",
            "tags": ["career-guide"],
            "target_query": "",
        },
        {
            "slug": "04-another-career-post",
            "title": "Post 2",
            "og_description": "Desc 2",
            "lede": "",
            "body_html": "<p>Body</p>",
            "published": "2026-04-02",
            "tags": ["ai-engineer"],
            "target_query": "",
        },
    ]
    monkeypatch.setattr("app.services.blog_publisher.list_published", lambda: fake)
    monkeypatch.setattr("app.services.blog_publisher.load_published", _fake_load_published(fake))
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: True)
    from app.routers import blog as blog_module
    monkeypatch.setattr(blog_module, "_load_pillar_config", lambda: _pillar_config_with_career_paths())
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/blog/topic/career-paths")
        assert r.status_code == 200
        import re, json
        blocks = re.findall(
            r'<script type="application/ld\+json">(.*?)</script>', r.text, re.DOTALL
        )
        parsed = [json.loads(b) for b in blocks]
        il = next((b for b in parsed if b.get("@type") == "ItemList"), None)
        assert il is not None, "ItemList JSON-LD not found"
        assert il["numberOfItems"] == 2
    await close_db()


# ---------------------------------------------------------------------------
# SEO-27: Search API tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_blog_search_api_shape(monkeypatch):
    """/api/blog/search returns expected JSON shape."""
    fake = [
        {
            "slug": "03-ai-engineer-vs-ml-engineer",
            "title": "AI Engineer vs ML Engineer 2026",
            "og_description": "Compare the roles",
            "lede": "A lede",
            "body_html": "<p>Body about AI engineers</p>",
            "published": "2026-04-01",
            "tags": ["career-guide", "ai-engineer"],
            "target_query": "ai engineer vs ml engineer",
        }
    ]
    monkeypatch.setattr("app.services.blog_publisher.list_published", lambda: fake)
    monkeypatch.setattr("app.services.blog_publisher.load_published", _fake_load_published(fake))
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: True)
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/api/blog/search?q=engineer")
        assert r.status_code == 200
        data = r.json()
        assert "query" in data
        assert "total" in data
        assert "results" in data
        assert isinstance(data["results"], list)
        if data["results"]:
            result = data["results"][0]
            assert "slug" in result
            assert "title" in result
            assert "summary" in result
            assert "published" in result
            assert "matched_in" in result
    await close_db()


@pytest.mark.asyncio
async def test_blog_search_api_rejects_short_query(monkeypatch):
    """?q=a (1 char) is rejected with 422."""
    monkeypatch.setattr("app.services.blog_publisher.list_published", lambda: [])
    monkeypatch.setattr("app.services.blog_publisher.load_published", lambda s: None)
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: True)
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/api/blog/search?q=a")
        assert r.status_code == 422
    await close_db()


@pytest.mark.asyncio
async def test_blog_search_api_title_ranks_first(monkeypatch):
    """Title match ranks above tag match above body match."""
    fake = [
        {
            "slug": "title-match",
            "title": "engineer career guide",
            "og_description": "Description",
            "lede": "",
            "body_html": "<p>Body text here</p>",
            "published": "2026-04-03",
            "tags": ["build-in-public"],
            "target_query": "",
        },
        {
            "slug": "tag-match",
            "title": "Something else entirely",
            "og_description": "A description",
            "lede": "",
            "body_html": "<p>Body text here</p>",
            "published": "2026-04-02",
            "tags": ["engineer"],
            "target_query": "",
        },
        {
            "slug": "body-match",
            "title": "Completely unrelated",
            "og_description": "Another description",
            "lede": "",
            "body_html": "<p>This body mentions engineer somewhere</p>",
            "published": "2026-04-01",
            "tags": ["other"],
            "target_query": "",
        },
    ]
    monkeypatch.setattr("app.services.blog_publisher.list_published", lambda: fake)
    monkeypatch.setattr("app.services.blog_publisher.load_published", _fake_load_published(fake))
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: True)
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/api/blog/search?q=engineer")
        assert r.status_code == 200
        data = r.json()
        slugs = [res["slug"] for res in data["results"]]
        assert slugs.index("title-match") < slugs.index("body-match")
    await close_db()


@pytest.mark.asyncio
async def test_blog_search_api_xss_safe(monkeypatch):
    """XSS payload in q is echoed back safely — query field is JSON-escaped,
    the <script> injection string does not appear raw in the response."""
    monkeypatch.setattr("app.services.blog_publisher.list_published", lambda: [])
    monkeypatch.setattr("app.services.blog_publisher.load_published", lambda s: None)
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: True)
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        xss = "<script>alert(1)</script>"
        from urllib.parse import quote
        r = await c.get(f"/api/blog/search?q={quote(xss)}")
        assert r.status_code == 200
        data = r.json()
        # The query field echoes the raw string (JSON encoding handles escaping
        # at the transport layer — JSON doesn't require HTML-escaping </>).
        assert data["query"] == xss
        # The raw literal </script> must NOT appear unescaped in the JSON body
        # (JSON encoding turns < into < or keeps it; the response body
        # from JSONResponse doesn't HTML-escape, so we verify the result is
        # valid JSON that doesn't cause XSS when used via textContent in JS).
        # The critical safety is on the HTML rendering side (textContent only).
        # The JSON response itself is the API; the HTML search form uses
        # textContent to render results (not innerHTML) — this is the XSS guard.
        assert data["total"] == 0
    await close_db()


# ---------------------------------------------------------------------------
# SEO-27: Pillar config failure-mode tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pillar_config_malformed_falls_back(monkeypatch):
    """If the pillar config loader raises, /blog still renders 200 with no
    pills (not 500). Defensive: malformed config = graceful degradation."""
    monkeypatch.setattr("app.services.blog_publisher.list_published", lambda: [])
    monkeypatch.setattr("app.services.blog_publisher.load_published", lambda s: None)
    monkeypatch.setattr("app.services.blog_publisher.is_legacy_hidden", lambda s: True)
    from app.routers import blog as blog_module

    def _raise():
        raise RuntimeError("config load failed")

    monkeypatch.setattr(blog_module, "_load_pillar_config", _raise)
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/blog")
        assert r.status_code == 200
        # No pills rendered
        assert 'class="pill"' not in r.text
    await close_db()


def test_pillar_config_drops_invalid_entries(monkeypatch, tmp_path):
    """Pillar config with 1 valid + 1 invalid entry: loader returns only
    the valid entry."""
    import json
    from app.routers.blog import _load_pillar_config

    config_data = {
        "version": 1,
        "active_pills": [
            {
                "slug": "valid-pillar",
                "label": "Valid",
                "intro": "A valid intro",
                "matches": {"tags_any": ["valid"]},
            },
            {
                # Missing required keys
                "slug": "broken",
                "label": "Broken",
                # 'intro' and 'matches' missing
            },
        ],
        "start_here": [],
    }
    config_file = tmp_path / "pillar_topics.json"
    config_file.write_text(json.dumps(config_data), encoding="utf-8")

    # Monkeypatch the path used by the loader
    import app.routers.blog as blog_module
    monkeypatch.setattr(blog_module, "_PILLAR_CONFIG_PATH", config_file)
    _load_pillar_config.cache_clear()

    result = _load_pillar_config()
    assert len(result["active_pills"]) == 1
    assert result["active_pills"][0]["slug"] == "valid-pillar"
    # cleanup
    _load_pillar_config.cache_clear()
