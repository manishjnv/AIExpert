"""Tests for the JD simplifier — drop-filler + bullet-ify."""

from __future__ import annotations

from app.services.jobs_readable import render_simplified, simplify_jd


def test_drops_about_us_and_company_sections():
    html = """
    <h2>About Acme</h2>
    <p>We are a 10-year-old rocket company with a mission to change the world
       and we believe deeply in our values and culture of innovation blah blah.</p>
    <h2>What you'll do</h2>
    <ul>
      <li>Build production ML pipelines on PyTorch</li>
      <li>Work with distributed training frameworks</li>
      <li>Own RLHF datasets end-to-end</li>
    </ul>
    <h2>How we're different</h2>
    <p>We're a flat, friendly, fully-remote team that values autonomy.</p>
    <h2>Requirements</h2>
    <ul>
      <li>5+ years Python</li>
      <li>Strong PyTorch experience</li>
    </ul>
    <h2>Equal Opportunity</h2>
    <p>Acme is an equal opportunity employer and encourages applications from all.</p>
    """
    out = simplify_jd(html)
    assert "What you'll do" in out
    assert "Requirements" in out
    # Filler sections completely dropped.
    for filler in ("About Acme", "How we're different", "Equal Opportunity"):
        assert filler not in out
    # Bullets preserved.
    assert any("Build production ML pipelines on PyTorch" in b for b in out["What you'll do"])
    assert any("5+ years Python" in b for b in out["Requirements"])


def test_canonicalizes_heading_variants():
    html = """
    <h3>The Role</h3><ul><li>Lead model training</li></ul>
    <h3>What we're looking for</h3><ul><li>Senior ML background</li></ul>
    <h3>Nice-to-have</h3><ul><li>JAX exposure</li></ul>
    <h3>What you'll get</h3><ul><li>Top-of-market cash</li></ul>
    """
    out = simplify_jd(html)
    assert set(out.keys()) == {"What you'll do", "Requirements", "Nice to have", "Benefits"}


def test_sentence_bullets_paragraph_fallback():
    """Paragraphs under kept sections become bullets when no <li> present."""
    html = """
    <h2>What you'll do</h2>
    <p>You will design RLHF pipelines end-to-end. You will own distributed
       training infrastructure. You will mentor junior researchers on the team.
       You will run weekly model evals across benchmarks.</p>
    """
    out = simplify_jd(html)
    items = out["What you'll do"]
    assert len(items) >= 3
    assert any("RLHF" in i for i in items)


def test_section_order_prefers_responsibilities_first():
    html = """
    <h2>Benefits</h2><ul><li>Health insurance</li></ul>
    <h2>Requirements</h2><ul><li>5y Python</li></ul>
    <h2>Responsibilities</h2><ul><li>Build stuff</li></ul>
    """
    out = simplify_jd(html)
    keys = list(out.keys())
    # Responsibilities first, benefits last.
    assert keys.index("What you'll do") < keys.index("Requirements") < keys.index("Benefits")


def test_empty_when_nothing_usable():
    """Too-short or empty JDs signal fallback (empty dict)."""
    assert simplify_jd("") == {}
    assert simplify_jd("<p>Apply at careers@acme.com</p>") == {}


def test_render_simplified_escapes_and_wraps():
    sections = {"Requirements": ["5+ years <Python>", "Strong PyTorch"]}
    html = render_simplified(sections)
    assert 'class="jd-simple"' in html
    assert "&lt;Python&gt;" in html
    assert "5+ years" in html


def test_headingless_jd_extracts_signal_sentences():
    """JDs with no headings get sentence-split, filler dropped, signals kept."""
    html = """
    <p>Anthropic's mission is to create reliable, interpretable, and steerable AI systems.
       We are a diverse team with a culture of experimentation. Our mission is to ensure AI
       safety is prioritized. You will build production RLHF pipelines on PyTorch at scale.
       You will own distributed training infrastructure across thousands of GPUs.
       You'll collaborate with researchers on alignment evals. We are an equal opportunity
       employer and welcome applications regardless of background. Required: 5+ years of
       experience with Python. Must have strong expertise in distributed systems.</p>
    """
    out = simplify_jd(html)
    assert "Key points" in out
    kept = " | ".join(out["Key points"]).lower()
    # Signals kept.
    assert "rlhf" in kept or "pytorch" in kept
    assert "5+ years" in kept or "5+ year" in kept
    # Filler dropped.
    assert "mission is to create" not in kept
    assert "equal opportunity" not in kept
    assert "diverse team" not in kept


def test_bullets_capped_at_scan_length():
    """No bullet exceeds the hard max length."""
    long_p = (
        "You will build production RLHF pipelines on PyTorch at scale across thousands "
        "of GPUs, collaborate with researchers across multiple time zones on alignment "
        "evals, own distributed training infrastructure end-to-end, and mentor junior "
        "engineers. Required: 5+ years of experience with Python and distributed systems "
        "in high-throughput production environments serving millions of requests daily. "
        "You will own evaluation harnesses for frontier LLM deployments. "
        "You will design CUDA kernels for inference latency improvements."
    )
    out = simplify_jd(f"<p>{long_p}</p>")
    assert out, "should produce bullets"
    for items in out.values():
        for b in items:
            assert len(b) <= 141, f"bullet too long ({len(b)}): {b!r}"


def test_strips_leading_filler_clauses():
    """Preambles like 'As part of our commitment, ...' get stripped."""
    html = (
        "<p>As part of our commitment to responsible AI, you will design eval "
        "harnesses for large language models. The successful candidate will own "
        "distributed training infrastructure. In this role, you'll ship production "
        "RLHF pipelines. Required: 5+ years PyTorch.</p>"
    )
    out = simplify_jd(html)
    bullets = out.get("Key points", [])
    joined = " | ".join(bullets).lower()
    assert "as part of our commitment" not in joined
    assert "successful candidate will" not in joined
    assert "in this role" not in joined
    # The payload words survived.
    assert "eval" in joined or "rlhf" in joined or "distributed" in joined


def test_bullet_count_capped_for_headingless():
    """Headingless JDs never exceed MAX_BULLETS even with many signal sentences."""
    sentences = [
        f"You will own distributed training system number {i} at scale."
        for i in range(20)
    ]
    html = "<p>" + " ".join(sentences) + "</p>"
    out = simplify_jd(html)
    assert len(out["Key points"]) <= 8


def test_headingless_respects_min_bullets():
    """A JD with no headings and <3 signal sentences falls back (empty dict)."""
    html = "<p>We are a friendly team. Our mission is to win. Apply today.</p>"
    assert simplify_jd(html) == {}


def test_drops_filler_paragraphs_inside_kept_section_head():
    """A kept section's heading wins — but drop-sections dropped even between them."""
    html = """
    <h2>What you'll do</h2>
    <ul><li>Own LLM eval suites</li></ul>
    <h2>About the company</h2>
    <p>We are Acme, founded in 2015.</p>
    <h2>Requirements</h2>
    <ul><li>Python fluency</li></ul>
    """
    out = simplify_jd(html)
    assert "About the company" not in out
    assert "What you'll do" in out and "Requirements" in out
