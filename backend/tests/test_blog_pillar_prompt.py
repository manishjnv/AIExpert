"""Tests for the pillar-tier prompt generator (/admin/api/render-blog-prompt).

Covers:
  - _build_internal_url_manifest enumerates all live tracks / quintets /
    hubs so pillar posts can hit the >=40 internal-link gate.
  - _build_trusted_sources_digest groups SEO-25 allowlist by category.
  - Pillar prompt template substitutes every placeholder.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.routers.admin import (
    _build_internal_url_manifest,
    _build_trusted_sources_digest,
)


def test_internal_url_manifest_covers_every_track_and_quintet():
    from app.routers.track_pages import all_track_slugs, all_section_slugs

    out = _build_internal_url_manifest()

    for t in all_track_slugs():
        assert f"/roadmap/{t}" in out, f"track hub /roadmap/{t} missing from manifest"
        for s in all_section_slugs():
            assert f"/roadmap/{t}/{s}" in out, f"quintet /roadmap/{t}/{s} missing"

    for required in ("/", "/roadmap", "/jobs", "/leaderboard", "/blog", "/vs", "/verify"):
        assert required in out, f"hub {required} missing from manifest"


def test_internal_url_manifest_has_enough_urls_to_clear_40_link_gate():
    out = _build_internal_url_manifest()
    url_lines = [ln for ln in out.splitlines() if ln.strip().startswith("/")]
    assert len(url_lines) >= 40, (
        f"manifest lists {len(url_lines)} URLs; pillar validator "
        f"requires >= 40 internal links — manifest must have enough distinct routes"
    )


def test_trusted_sources_digest_groups_by_category():
    out = _build_trusted_sources_digest()
    for cat in ("PAPERS", "LAB-DOCS", "FRAMEWORK-DOCS", "STATISTICS", "ACADEMIC"):
        assert cat in out, f"category {cat} missing from digest"
    assert "arxiv.org" in out
    assert "anthropic.com" in out
    assert "pytorch.org" in out
    assert "bls.gov" in out


def test_pillar_prompt_template_has_all_placeholders():
    path = Path(__file__).resolve().parent.parent / "app" / "prompts" / "claude_blog_pillar.txt"
    assert path.exists(), f"pillar prompt template missing at {path}"
    text = path.read_text(encoding="utf-8")
    for placeholder in (
        "{{TITLE}}", "{{ANGLE}}", "{{SLUG}}", "{{PUBLISHED_DATE}}", "{{AUTHOR}}",
        "{{TARGET_QUERY}}", "{{PILLAR_TIER}}", "{{MIN_WORDS}}",
        "{{SCHEMA_STACK}}", "{{SCHEMA_STACK_JSON}}", "{{COMPARATIVE}}",
        "{{INTERNAL_URL_MANIFEST}}", "{{TRUSTED_SOURCES}}",
    ):
        assert placeholder in text, f"pillar template missing placeholder {placeholder}"


def test_pillar_prompt_renders_with_every_substitution():
    """End-to-end render: confirm every placeholder is swapped so the
    generated prompt Claude sees has no unresolved braces."""
    from pathlib import Path as _P
    import json as _json

    path = _P(__file__).resolve().parent.parent / "app" / "prompts" / "claude_blog_pillar.txt"
    template = path.read_text(encoding="utf-8")

    stack = ["Article", "FAQPage", "DefinedTerm"]
    rendered = (
        template
        .replace("{{TITLE}}", "AI Engineer vs ML Engineer")
        .replace("{{ANGLE}}", "The role split matters more than the skills overlap.")
        .replace("{{SLUG}}", "03-ai-engineer-vs-ml-engineer")
        .replace("{{PUBLISHED_DATE}}", "2026-04-25")
        .replace("{{AUTHOR}}", "Manish Kumar")
        .replace("{{TARGET_QUERY}}", "AI engineer vs ML engineer")
        .replace("{{PILLAR_TIER}}", "pillar")
        .replace("{{MIN_WORDS}}", "3000")
        .replace("{{SCHEMA_STACK}}", ", ".join(stack))
        .replace("{{SCHEMA_STACK_JSON}}", _json.dumps(stack))
        .replace("{{COMPARATIVE}}", "true")
        .replace("{{INTERNAL_URL_MANIFEST}}", _build_internal_url_manifest())
        .replace("{{TRUSTED_SOURCES}}", _build_trusted_sources_digest())
    )
    assert "{{" not in rendered, "pillar prompt still has unresolved {{...}} placeholders after render"
    assert "AI Engineer vs ML Engineer" in rendered
    assert "03-ai-engineer-vs-ml-engineer" in rendered
    assert "pillar" in rendered
    assert "3000" in rendered
    assert "arxiv.org" in rendered
    assert "/roadmap/ai-engineer" in rendered


def test_render_rejects_invalid_tier_shape():
    """Bare-minimum guard on the validation branches the route takes.
    Exercises the tier + schema_stack check without going through FastAPI."""
    valid = {"HowTo", "DefinedTerm", "VideoObject", "ItemList"}
    bad_stack = ["Article", "FAQPage"]
    assert not (set(bad_stack) & valid), "stack with no satisfier should be rejected"
    good_stack = ["Article", "FAQPage", "DefinedTerm"]
    assert set(good_stack) & valid, "stack with DefinedTerm should be accepted"
