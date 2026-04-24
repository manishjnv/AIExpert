"""Tests for blog_validator (SEO-21 pillar quality bar + SEO-22 VideoObject).

Covers every one of the 10 checks in docs/SEO.md SEO-21, plus the
VideoObject emitter and the integration seam with blog_publisher.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import blog_validator as bv
from app.services.blog_publisher import validate_payload


# ---------------- shared fixtures ----------------


def _filler_paragraph(idx: int, extra_words: int = 120) -> str:
    """Generate a deterministic ~extra_words-word paragraph. Uses a seeded
    vocabulary so tests stay stable across runs."""
    lex = ("learning models fundamentals principles practice dataset training "
           "evaluation deployment architecture gradient optimization loss "
           "function inference production engineering role skills career "
           "growth demand market salary compensation education background "
           "degree bootcamp portfolio project measured outcomes stakeholders "
           "business context teams reliability observability scaling").split()
    words = []
    for i in range(extra_words):
        words.append(lex[(idx * 7 + i) % len(lex)])
    return "<p>" + " ".join(words).capitalize() + ".</p>"


def _h2_section(idx: int, paragraphs: int = 3, extra_words: int = 120) -> str:
    return (f"<h2>Section {idx}</h2>\n" +
            "\n".join(_filler_paragraph(idx * 10 + p, extra_words) for p in range(paragraphs)))


def _build_body_html(
    *,
    h2_count: int = 10,
    paragraphs_per_section: int = 3,
    extra_words_per_para: int = 120,
    internal_links: int = 42,
    trusted_citations: int = 6,
    include_lede: bool = True,
    first_para_words: int = 50,
    include_table: bool = False,
) -> str:
    parts: list[str] = []
    if include_lede:
        parts.append('<p class="lede"><em>A short evocative lede sentence that kicks off the post.</em></p>')
    # Definitional first paragraph (post-lede). Built programmatically so
    # first_para_words always hits the target exactly.
    lex = ("AI engineer ships machine learning systems in production focused on "
           "reliability latency observability and measurable business outcomes while "
           "the machine learning engineer anchors on data curation training "
           "optimization evaluation iteration and full model lifecycle management as "
           "the central craft rather than pure integration plumbing or monitoring "
           "dashboards and incident response playbooks written by backend teams who "
           "own the serving infrastructure instead of the model artefact itself").split()
    # Cycle if caller asks for more than the lex length.
    definitional = " ".join(lex[i % len(lex)] for i in range(first_para_words))
    parts.append(f"<p>{definitional}.</p>")
    # Internal links — bundled in a single paragraph; one <a> each.
    internal_block = " ".join(
        f'<a href="/roadmap/ai-engineer/skills#item-{i}">skill {i}</a>'
        for i in range(internal_links)
    )
    parts.append(f"<p>Relevant internal context: {internal_block}.</p>")
    # Trusted external citations — real domains from trusted_sources.json.
    trusted_urls = [
        "https://arxiv.org/abs/2103.00020",
        "https://paperswithcode.com/paper/scaling-laws",
        "https://openai.com/research/gpt-4",
        "https://anthropic.com/research/claude",
        "https://pytorch.org/docs/stable/index.html",
        "https://bls.gov/ooh/computer-and-information-technology/data-scientists.htm",
        "https://aiindex.stanford.edu/report/",
        "https://huggingface.co/docs/transformers/index",
    ]
    cite_block = " ".join(
        f'<a href="{trusted_urls[i % len(trusted_urls)]}">reference {i}</a>'
        for i in range(trusted_citations)
    )
    parts.append(f"<p>External authority: {cite_block}.</p>")
    # Comparison table (gated).
    if include_table:
        parts.append("<table><tr><th>Role</th><th>Focus</th></tr>"
                     "<tr><td>AI Engineer</td><td>Integration</td></tr>"
                     "<tr><td>ML Engineer</td><td>Model lifecycle</td></tr></table>")
    # Main H2 sections.
    for i in range(h2_count):
        parts.append(_h2_section(i, paragraphs_per_section, extra_words_per_para))
    parts.append("<hr><p>Closing CTA.</p>")
    return "\n\n".join(parts)


def _mk_pillar_payload(**overrides) -> dict:
    """A payload that satisfies every SEO-21 pillar check by default.
    Override any field to trigger a specific failure."""
    body = _build_body_html()
    base = {
        "title": "AI Engineer vs ML Engineer: A Practical 2026 Breakdown",
        "slug": "03-ai-engineer-vs-ml-engineer",
        "author": "Manish Kumar",
        "published": "2026-04-24",
        "tags": ["build-in-public", "careers", "ai-engineer"],
        "og_description": "A practical, cited breakdown of how AI Engineers and ML Engineers diverge in 2026 — responsibilities, tooling, salary bands, and which role matches your background.",
        "lede": "The two titles sound interchangeable. In hiring, they are not.",
        "body_html": body,
        "word_count": 3000,
        "image_brief": {
            "hero_prompt": "A split-screen photorealistic illustration contrasting a production systems engineer reviewing dashboards on the left and a researcher training models on a workstation on the right, warm amber lighting, editorial composition, 16:9.",
            "hero_alt": "Split-screen showing an AI engineer at a monitoring dashboard and an ML engineer at a training workstation.",
            "hero_filename": "03-ai-engineer-vs-ml-engineer-hero.png",
        },
        "quotable_lines": ["The two titles sound interchangeable. In hiring, they are not."],
        # Pillar-specific extensions:
        "pillar_tier": "pillar",
        "schemas": ["Article", "FAQPage", "HowTo"],
        "faqs": [{"q": f"Question {i}?", "a": f"Answer {i}."} for i in range(10)],
        "og_image": "/og/blog/03-ai-engineer-vs-ml-engineer.png",
    }
    base.update(overrides)
    return base


# ---------------- SEO-25: trusted-sources allowlist ----------------


def test_trusted_sources_json_loads():
    t = bv.load_trusted_sources()
    assert not t.get("missing"), f"allowlist missing at {t.get('loaded_from')}"
    assert "arxiv.org" in t["domains"]
    assert "pytorch.org" in t["domains"]
    assert "bls.gov" in t["domains"]
    assert t.get("version") == 1


def test_is_trusted_domain_exact_match():
    domains = {"arxiv.org", "pytorch.org"}
    assert bv.is_trusted_domain("https://arxiv.org/abs/2103.00020", domains)
    assert bv.is_trusted_domain("https://pytorch.org/docs/", domains)


def test_is_trusted_domain_subdomain_match():
    domains = {"google.com"}
    assert bv.is_trusted_domain("https://ai.google.com/research", domains)
    assert bv.is_trusted_domain("https://research.google.com/paper", domains)


def test_is_trusted_domain_rejects_fake_suffix():
    domains = {"meta.com"}
    assert not bv.is_trusted_domain("https://fakemeta.com/phish", domains)
    assert not bv.is_trusted_domain("https://meta.com.attacker.io/", domains)


def test_is_trusted_domain_rejects_empty_and_malformed():
    domains = {"arxiv.org"}
    assert not bv.is_trusted_domain("", domains)
    assert not bv.is_trusted_domain("not-a-url", domains)
    assert not bv.is_trusted_domain("mailto:hi@arxiv.org", domains)


# ---------------- SEO-21: pillar quality bar ----------------


def test_validate_pillar_skips_without_tier():
    payload = _mk_pillar_payload()
    payload.pop("pillar_tier")
    report = bv.validate_pillar(payload)
    assert report["ok"] is True
    assert report["errors"] == []
    assert report["stats"] == {"pillar_tier": None}


def test_validate_pillar_happy_path():
    report = bv.validate_pillar(_mk_pillar_payload())
    assert report["ok"] is True, f"unexpected errors: {report['errors']}"
    stats = report["stats"]
    assert stats["pillar_tier"] == "pillar"
    assert stats["word_count"] >= 3000
    assert 40 <= stats["first_para_words"] <= 60
    assert 8 <= stats["h2_count"] <= 12
    assert stats["internal_links"] >= 40
    assert stats["trusted_citations"] >= 5
    assert stats["faq_count"] == 10


def test_validate_pillar_flags_word_count_below_tier():
    body = _build_body_html(h2_count=10, paragraphs_per_section=1, extra_words_per_para=5)
    payload = _mk_pillar_payload(body_html=body)
    report = bv.validate_pillar(payload)
    assert report["ok"] is False
    assert any("requires >= 3000 words" in e for e in report["errors"])


def test_validate_pillar_flagship_tier_raises_floor():
    # Default body is ~3900 words — passes pillar, fails flagship.
    payload = _mk_pillar_payload(pillar_tier="flagship")
    report = bv.validate_pillar(payload)
    assert report["ok"] is False
    assert any("requires >= 4500 words" in e for e in report["errors"])


def test_validate_pillar_rejects_unknown_tier():
    payload = _mk_pillar_payload(pillar_tier="nonsense")
    report = bv.validate_pillar(payload)
    assert report["ok"] is False
    assert any("not recognised" in e for e in report["errors"])


def test_validate_pillar_flags_first_paragraph_too_short():
    body = _build_body_html(first_para_words=20)
    payload = _mk_pillar_payload(body_html=body)
    report = bv.validate_pillar(payload)
    assert report["ok"] is False
    assert any("first non-lede paragraph is 20 words" in e for e in report["errors"])


def test_validate_pillar_flags_first_paragraph_too_long():
    body = _build_body_html(first_para_words=80)
    payload = _mk_pillar_payload(body_html=body)
    report = bv.validate_pillar(payload)
    assert report["ok"] is False
    assert any("first non-lede paragraph is 80 words" in e for e in report["errors"])


def test_validate_pillar_flags_h2_below_range():
    body = _build_body_html(h2_count=5, extra_words_per_para=300)
    payload = _mk_pillar_payload(body_html=body)
    report = bv.validate_pillar(payload)
    assert report["ok"] is False
    assert any("has 5 <h2>" in e for e in report["errors"])


def test_validate_pillar_flags_h2_above_range():
    body = _build_body_html(h2_count=14)
    payload = _mk_pillar_payload(body_html=body)
    report = bv.validate_pillar(payload)
    assert report["ok"] is False
    assert any("has 14 <h2>" in e for e in report["errors"])


def test_validate_pillar_flags_too_few_internal_links():
    body = _build_body_html(internal_links=10)
    payload = _mk_pillar_payload(body_html=body)
    report = bv.validate_pillar(payload)
    assert report["ok"] is False
    assert any("10 internal links" in e for e in report["errors"])


def test_validate_pillar_flags_too_few_trusted_citations():
    body = _build_body_html(trusted_citations=2)
    payload = _mk_pillar_payload(body_html=body)
    report = bv.validate_pillar(payload)
    assert report["ok"] is False
    assert any("2 citations to trusted sources" in e for e in report["errors"])


def test_validate_pillar_counts_absolute_site_links_as_internal():
    """Absolute URLs pointing at our own host count toward the internal
    link budget, same as relative '/...' links."""
    # Use 0 relative links but 42 absolute-to-self links.
    body_pieces = []
    body_pieces.append('<p>Lead words ' + ' '.join(['x'] * 50) + '.</p>')
    # Provide 42 absolute internal links.
    abs_block = " ".join(
        f'<a href="https://automateedge.cloud/blog/post-{i}">post {i}</a>'
        for i in range(42)
    )
    body_pieces.append(f'<p>{abs_block}</p>')
    # 6 trusted citations.
    cites = " ".join(
        f'<a href="https://arxiv.org/abs/0000.{i:04d}">ref {i}</a>' for i in range(6)
    )
    body_pieces.append(f'<p>{cites}</p>')
    for i in range(10):
        body_pieces.append(_h2_section(i, 3, 120))
    body_pieces.append('<hr><p>End.</p>')
    body = "\n".join(body_pieces)
    payload = _mk_pillar_payload(body_html=body)
    report = bv.validate_pillar(payload)
    # Should pass internal link check even though no '/...' links present.
    assert report["stats"]["internal_links"] >= 40, report


def test_validate_pillar_flags_missing_schemas_field():
    payload = _mk_pillar_payload()
    payload.pop("schemas")
    report = bv.validate_pillar(payload)
    assert report["ok"] is False
    assert any('schemas' in e for e in report["errors"])


def test_validate_pillar_flags_missing_article():
    payload = _mk_pillar_payload(schemas=["FAQPage", "HowTo"])
    report = bv.validate_pillar(payload)
    assert report["ok"] is False
    assert any('must include "Article"' in e for e in report["errors"])


def test_validate_pillar_flags_missing_faqpage():
    payload = _mk_pillar_payload(schemas=["Article", "HowTo"])
    report = bv.validate_pillar(payload)
    assert report["ok"] is False
    assert any('must include "FAQPage"' in e for e in report["errors"])


def test_validate_pillar_flags_missing_satisfying_schema():
    payload = _mk_pillar_payload(schemas=["Article", "FAQPage"])
    report = bv.validate_pillar(payload)
    assert report["ok"] is False
    assert any("at least one of" in e for e in report["errors"])


def test_validate_pillar_accepts_defined_term_as_satisfier():
    payload = _mk_pillar_payload(schemas=["Article", "FAQPage", "DefinedTerm"])
    report = bv.validate_pillar(payload)
    assert report["ok"] is True


def test_validate_pillar_flags_too_few_faqs():
    payload = _mk_pillar_payload(faqs=[{"q": "?", "a": "."} for _ in range(5)])
    report = bv.validate_pillar(payload)
    assert report["ok"] is False
    assert any("5 FAQ pairs" in e for e in report["errors"])


def test_validate_pillar_flags_too_many_faqs():
    payload = _mk_pillar_payload(faqs=[{"q": "?", "a": "."} for _ in range(20)])
    report = bv.validate_pillar(payload)
    assert report["ok"] is False
    assert any("20 FAQ pairs" in e for e in report["errors"])


def test_validate_pillar_flags_comparative_without_table():
    body = _build_body_html(include_table=False)
    payload = _mk_pillar_payload(body_html=body, comparative=True)
    report = bv.validate_pillar(payload)
    assert report["ok"] is False
    assert any("no <table>" in e for e in report["errors"])


def test_validate_pillar_accepts_comparative_with_table():
    body = _build_body_html(include_table=True)
    payload = _mk_pillar_payload(body_html=body, comparative=True)
    report = bv.validate_pillar(payload)
    assert report["ok"] is True, report


def test_validate_pillar_warns_on_stale_date_modified():
    payload = _mk_pillar_payload(last_reviewed_on="2025-01-01")
    report = bv.validate_pillar(payload)
    # Still passes (warning, not error), but warning is raised.
    assert report["ok"] is True
    assert any("days old" in w for w in report["warnings"])


def test_validate_pillar_warns_on_missing_og_image():
    payload = _mk_pillar_payload()
    payload.pop("og_image")
    report = bv.validate_pillar(payload)
    assert report["ok"] is True  # warning, not error
    assert any("og_image not set" in w for w in report["warnings"])


def test_validate_pillar_warns_on_mismatched_og_image():
    payload = _mk_pillar_payload(og_image="/og/somewhere-else.png")
    report = bv.validate_pillar(payload)
    assert report["ok"] is True
    assert any("does not match the SEO-11 pattern" in w for w in report["warnings"])


# ---------------- SEO-22: VideoObject emitter ----------------


def test_build_video_object_success():
    obj = bv.build_video_object({
        "id": "abc12345678",
        "title": "Introduction to transformers",
        "description": "A walkthrough of the transformer architecture.",
        "published_at": "2025-06-15T14:00:00Z",
        "duration": "PT14M23S",
    })
    assert obj is not None
    assert obj["@type"] == "VideoObject"
    assert obj["name"] == "Introduction to transformers"
    assert obj["contentUrl"] == "https://www.youtube.com/watch?v=abc12345678"
    assert obj["embedUrl"] == "https://www.youtube.com/embed/abc12345678"
    assert obj["thumbnailUrl"] == "https://i.ytimg.com/vi/abc12345678/maxresdefault.jpg"
    assert obj["uploadDate"] == "2025-06-15T14:00:00Z"
    assert obj["duration"] == "PT14M23S"


def test_build_video_object_coerces_mmss_duration():
    obj = bv.build_video_object({
        "id": "x", "title": "T", "description": "D",
        "published_at": "2025-06-15T14:00:00Z",
        "duration": "14:23",
    })
    assert obj is not None
    assert obj["duration"] == "PT14M23S"


def test_build_video_object_coerces_hhmmss_duration():
    obj = bv.build_video_object({
        "id": "x", "title": "T", "description": "D",
        "published_at": "2025-06-15T14:00:00Z",
        "duration": "1:14:23",
    })
    assert obj is not None
    assert obj["duration"] == "PT1H14M23S"


def test_build_video_object_rejects_bad_duration():
    obj = bv.build_video_object({
        "id": "x", "title": "T", "description": "D",
        "published_at": "2025-06-15T14:00:00Z",
        "duration": "garbage",
    })
    assert obj is None


def test_build_video_object_rejects_missing_required_fields():
    # Missing description
    assert bv.build_video_object({
        "id": "x", "title": "T", "description": "",
        "published_at": "2025-06-15T14:00:00Z", "duration": "PT1M",
    }) is None
    # Missing id
    assert bv.build_video_object({
        "id": "", "title": "T", "description": "D",
        "published_at": "2025-06-15T14:00:00Z", "duration": "PT1M",
    }) is None


def test_build_video_object_respects_explicit_thumbnail():
    obj = bv.build_video_object({
        "id": "x", "title": "T", "description": "D",
        "published_at": "2025-06-15T14:00:00Z", "duration": "PT1M",
        "thumbnail_url": "https://cdn.example.com/custom.jpg",
    })
    assert obj["thumbnailUrl"] == "https://cdn.example.com/custom.jpg"


def test_build_video_objects_drops_malformed_silently():
    out = bv.build_video_objects([
        {"id": "a", "title": "A", "description": "D",
         "published_at": "2025-01-01", "duration": "PT1M"},
        {"id": "b"},  # malformed
        {"id": "c", "title": "C", "description": "D",
         "published_at": "2025-01-01", "duration": "PT2M"},
    ])
    assert len(out) == 2
    assert [o["name"] for o in out] == ["A", "C"]


def test_validate_videos_metadata_detects_missing_entry():
    violations = bv.validate_videos_metadata({
        "youtube_ids": ["abc", "def"],
        "videos": [{"id": "abc", "title": "T", "description": "D",
                    "published_at": "2025-01-01", "duration": "PT1M"}],
    })
    assert any("'def'" in v and "no matching entry" in v for v in violations)


def test_validate_videos_metadata_detects_incomplete_entry():
    violations = bv.validate_videos_metadata({
        "youtube_ids": ["abc"],
        "videos": [{"id": "abc", "title": "", "description": "D",
                    "published_at": "2025-01-01", "duration": "PT1M"}],
    })
    assert any("missing field" in v for v in violations)


def test_validate_videos_metadata_clean_when_empty():
    assert bv.validate_videos_metadata({}) == []


# ---------------- integration with blog_publisher.validate_payload ----------------


def _mk_standard_payload(**overrides) -> dict:
    """Minimal payload that satisfies the STANDARD blog validator (no pillar)."""
    body = ('<p class="lede"><em>Short lede.</em></p>\n' +
            "\n".join(
                f"<h2>Section {i}</h2>\n<p>" + " ".join(["word"] * 120) + ".</p>"
                for i in range(8)
            ) +
            "\n<hr><p>End.</p>")
    base = {
        "title": "A Standard Build-In-Public Post",
        "slug": "99-a-standard-build-in-public-post",
        "author": "Manish Kumar",
        "published": "2026-04-24",
        "tags": ["build-in-public", "process", "lessons"],
        "og_description": "A short summary of the post for previews.",
        "lede": "Something short here.",
        "body_html": body,
        "word_count": 960,
        "image_brief": {
            "hero_prompt": "A photorealistic editorial image illustrating the topic with strong composition and warm lighting.",
            "hero_alt": "Hero image description.",
            "hero_filename": "99-a-standard-build-in-public-post-hero.png",
        },
        "quotable_lines": ["A memorable line."],
    }
    base.update(overrides)
    return base


def test_standard_post_still_rejects_ai_provider_names():
    """Regression: the split banned-terms list must not weaken the
    voice gate on normal build-in-public posts."""
    payload = _mk_standard_payload(
        body_html='<p class="lede"><em>Short.</em></p>\n<h2>A</h2><p>I used OpenAI.</p>'
                  '<h2>B</h2><p>x</p><h2>C</h2><p>x</p><h2>D</h2><p>x</p>',
    )
    report = validate_payload(payload)
    assert report["ok"] is False
    assert any("banned term" in e for e in report["errors"])


def test_pillar_tier_allows_ai_provider_names():
    """Pillar posts must be free to mention OpenAI, Anthropic, PyTorch
    etc. — they're targeting queries that require it."""
    payload = _mk_pillar_payload()
    # Inject legitimate provider references into body_html.
    payload["body_html"] = payload["body_html"].replace(
        "External authority:",
        "External authority — this post references OpenAI GPT-4, Anthropic Claude, and PyTorch:"
    )
    report = validate_payload(payload)
    # The banned-term error specifically must not appear.
    assert not any("banned term" in e for e in report["errors"]), report["errors"]


def test_pillar_tier_still_blocks_operational_leaks():
    """Repo paths and session references are always banned, pillar or not."""
    payload = _mk_pillar_payload()
    payload["body_html"] = payload["body_html"] + "<p>See github.com/manishjnv/AIExpert for the source code.</p>"
    report = validate_payload(payload)
    assert report["ok"] is False
    assert any("banned term" in e for e in report["errors"])


def test_validate_payload_runs_pillar_validator_on_pillar_tier():
    """A pillar-tier payload with obvious pillar violations must bubble
    up through validate_payload()."""
    body = _build_body_html(h2_count=10, paragraphs_per_section=1, extra_words_per_para=3)
    payload = _mk_pillar_payload(body_html=body)
    report = validate_payload(payload)
    assert report["ok"] is False
    # Pillar word-count error should be in there.
    assert any("requires >= 3000 words" in e for e in report["errors"])
    # Pillar stats block is merged into the payload.
    assert "pillar" in report["stats"]


def test_validate_payload_standard_post_no_pillar_stats():
    report = validate_payload(_mk_standard_payload())
    assert "pillar" not in report["stats"]


def test_validate_payload_video_metadata_propagates():
    """SEO-22 youtube_ids without matching videos[] blocks publish for
    any tier."""
    payload = _mk_standard_payload()
    payload["youtube_ids"] = ["zzz111"]
    # No videos[] array — should fail.
    report = validate_payload(payload)
    assert report["ok"] is False
    assert any("no matching entry" in e for e in report["errors"])
