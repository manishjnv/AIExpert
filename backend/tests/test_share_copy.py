"""test_share_copy.py — Unit tests for backend/app/services/share_copy.py.

Pure unit tests: no DB, no fixtures, no async.
All assertions use plain assert statements.
"""

from __future__ import annotations

from app.services.share_copy import build_share_copy, render_share_modal

# ---------------------------------------------------------------------------
# Shared sample payloads
# ---------------------------------------------------------------------------

_BLOG_POSTS = [
    {
        "title": "Getting Started with RAG",
        "description": "Retrieval-Augmented Generation lets you ground LLMs in your own data. It solves hallucination by fetching relevant context at inference time.",
        "lede": "Stop your LLM from hallucinating.",
        "tags": ["rag", "prompt-engineering"],
        "pillar_tier": 1,
    },
    {
        "title": "Building Production MLOps Pipelines",
        "description": "MLOps is no longer optional. Learn how to build end-to-end pipelines that version models, track experiments, and deploy reliably.",
        "lede": "MLOps for real teams — no vendor lock-in.",
        "tags": ["mlops", "ai-engineer"],
        "pillar_tier": 2,
    },
    {
        "title": "Fine-Tuning LLMs on Custom Datasets",
        "description": "Fine-tuning lets you adapt a pre-trained model to your specific domain. This guide covers dataset prep, training loops, and evaluation.",
        "lede": None,
        "tags": ["fine-tuning", "deep-learning"],
        "pillar_tier": 1,
    },
    {
        "title": "Vector Databases Explained",
        "description": "Vector databases store embeddings for fast similarity search. They are the backbone of modern RAG systems.",
        "lede": "Why every AI app needs a vector database.",
        "tags": ["vector-database", "embeddings"],
        "pillar_tier": 2,
    },
    {
        "title": "AI Agents: From Theory to Practice",
        "description": "Agents combine LLMs with tools and memory to complete multi-step tasks autonomously.",
        "lede": "Agents are the next frontier of AI applications.",
        "tags": ["agents", "foundation-model"],
        "pillar_tier": 1,
    },
]

_URL = "https://automatedge.ai/blog/test-post"

_JOB_SAMPLES = [
    {
        "title": "Senior ML Engineer",
        "company": "DeepMind",
        "designation": "Senior ML Engineer",
        "tldr": "Join a world-class team building the next generation of AI systems. You will work on large-scale training infrastructure and novel architectures.",
        "must_have_skills": ["Python", "PyTorch", "Kubernetes"],
        "topics": ["deep-learning", "mlops"],
        "remote_policy": "Hybrid",
        "salary_label": "$180k–$240k",
        "seniority": "Senior",
    },
    {
        "title": "ML Researcher",
        "company": "Anthropic",
        "designation": "ML Researcher",
        "tldr": "Research and develop novel alignment techniques for large language models.",
        "must_have_skills": ["Python", "TensorFlow"],
        "topics": ["foundation-model", "evaluation"],
        "remote_policy": "Remote",
        "salary_label": "",
        "seniority": "Mid",
    },
    {
        "title": "AI Platform Engineer",
        "company": "Stripe",
        "designation": "AI Platform Engineer",
        "tldr": "Build the AI platform that powers Stripe's product intelligence.",
        "must_have_skills": ["Python", "AWS"],
        "topics": [],
        "remote_policy": "On-site",
        "salary_label": "$160k–$200k",
        "seniority": "Senior",
    },
]

_JOB_URL = "https://automatedge.ai/jobs/12345"


# ---------------------------------------------------------------------------
# Blog tests
# ---------------------------------------------------------------------------


def test_blog_twitter_under_280() -> None:
    for post in _BLOG_POSTS:
        result = build_share_copy(surface="blog", url=_URL, payload=post)
        assert len(result["twitter"]) <= 280, (
            f"Twitter draft exceeds 280 for {post['title']!r}: "
            f"{len(result['twitter'])} chars"
        )


def test_blog_linkedin_under_3000() -> None:
    for post in _BLOG_POSTS:
        result = build_share_copy(surface="blog", url=_URL, payload=post)
        assert len(result["linkedin"]) <= 3000, (
            f"LinkedIn draft exceeds 3000 for {post['title']!r}: "
            f"{len(result['linkedin'])} chars"
        )


def test_blog_includes_url() -> None:
    for post in _BLOG_POSTS:
        result = build_share_copy(surface="blog", url=_URL, payload=post)
        assert _URL in result["twitter"], f"URL missing from twitter for {post['title']!r}"
        assert _URL in result["linkedin"], f"URL missing from linkedin for {post['title']!r}"


def test_blog_tags_mapped() -> None:
    post = {
        "title": "AI Career Guide",
        "description": "A guide to breaking into AI engineering and machine learning.",
        "lede": "Your roadmap to an AI career.",
        "tags": ["ai-engineer", "career-guide"],
        "pillar_tier": 1,
    }
    result = build_share_copy(surface="blog", url=_URL, payload=post)

    # LinkedIn: must contain both mapped tags AND #AutomateEdge
    assert "#AIEngineering" in result["linkedin"], "LinkedIn missing #AIEngineering"
    assert "#AICareer" in result["linkedin"], "LinkedIn missing #AICareer"
    assert "#AutomateEdge" in result["linkedin"], "LinkedIn missing #AutomateEdge"

    # Twitter: count hashtags (words starting with #)
    twitter_tags = [w for w in result["twitter"].split() if w.startswith("#")]
    assert len(twitter_tags) <= 2, f"Twitter has more than 2 hashtags: {twitter_tags}"


def test_blog_unmapped_tag_dropped() -> None:
    post = {
        "title": "Nonsense Topic",
        "description": "This post has an unmapped tag slug.",
        "lede": None,
        "tags": ["nonsense-slug"],
        "pillar_tier": 1,
    }
    result = build_share_copy(surface="blog", url=_URL, payload=post)
    assert "#nonsense" not in result["twitter"].lower(), (
        "Unmapped tag leaked into twitter"
    )
    assert "#nonsense" not in result["linkedin"].lower(), (
        "Unmapped tag leaked into linkedin"
    )


def test_blog_brand_only_on_linkedin() -> None:
    for post in _BLOG_POSTS:
        result = build_share_copy(surface="blog", url=_URL, payload=post)
        assert "#AutomateEdge" not in result["twitter"], (
            f"#AutomateEdge appeared in twitter for {post['title']!r}"
        )
        assert "#AutomateEdge" in result["linkedin"], (
            f"#AutomateEdge missing from linkedin for {post['title']!r}"
        )


# ---------------------------------------------------------------------------
# Job tests
# ---------------------------------------------------------------------------


def test_job_twitter_under_280() -> None:
    for job in _JOB_SAMPLES:
        result = build_share_copy(surface="job", url=_JOB_URL, payload=job)
        assert len(result["twitter"]) <= 280, (
            f"Twitter draft exceeds 280 for {job['designation']!r}: "
            f"{len(result['twitter'])} chars"
        )


def test_job_linkedin_includes_role_company() -> None:
    for job in _JOB_SAMPLES:
        result = build_share_copy(surface="job", url=_JOB_URL, payload=job)
        assert job["company"] in result["linkedin"], (
            f"Company {job['company']!r} missing from linkedin"
        )
        assert job["designation"] in result["linkedin"], (
            f"Designation {job['designation']!r} missing from linkedin"
        )


def test_job_skills_mapped() -> None:
    job = {
        "title": "ML Engineer",
        "company": "OpenAI",
        "designation": "ML Engineer",
        "tldr": "Build and scale ML infrastructure at OpenAI.",
        "must_have_skills": ["Python", "PyTorch"],
        "topics": [],
        "remote_policy": "Remote",
        "salary_label": "$200k+",
        "seniority": "Senior",
    }
    result = build_share_copy(surface="job", url=_JOB_URL, payload=job)
    assert "#Python" in result["linkedin"], "LinkedIn missing #Python"
    assert "#PyTorch" in result["linkedin"], "LinkedIn missing #PyTorch"


def test_job_aijobs_always() -> None:
    for job in _JOB_SAMPLES:
        result = build_share_copy(surface="job", url=_JOB_URL, payload=job)
        assert "#AIJobs" in result["linkedin"], (
            f"#AIJobs missing from linkedin for {job['designation']!r}"
        )


# ---------------------------------------------------------------------------
# Course milestone tests
# ---------------------------------------------------------------------------

_COURSE_PAYLOAD = {
    "milestone_title": "Week 4: Attention Is All You Need",
    "milestone_subtitle": "Implemented a transformer from scratch. Finally clicked.",
    "first_name": "Priya",
}
_COURSE_URL = "https://automatedge.ai/roadmap/priya-ai"


def test_course_milestone_first_name_in_linkedin() -> None:
    result = build_share_copy(surface="course_milestone", url=_COURSE_URL, payload=_COURSE_PAYLOAD)
    assert _COURSE_PAYLOAD["first_name"] in result["linkedin"], (
        "first_name missing from linkedin"
    )


def test_course_brand_in_linkedin_only() -> None:
    result = build_share_copy(surface="course_milestone", url=_COURSE_URL, payload=_COURSE_PAYLOAD)
    assert "#AutomateEdge" in result["linkedin"], "#AutomateEdge missing from linkedin"
    assert "#AutomateEdge" not in result["twitter"], "#AutomateEdge appeared in twitter"


# ---------------------------------------------------------------------------
# render_share_modal tests
# ---------------------------------------------------------------------------

_GOOD_COPY = {
    "twitter": "A great post about AI. https://automatedge.ai/blog/test #RAG",
    "linkedin": "A longer LinkedIn post about AI. Read more: https://automatedge.ai/blog/test #RAG #AutomateEdge",
}


_RENDER_DEFAULTS = {
    "og_image_url": "https://automatedge.ai/og.png",
    "surface": "blog",
    "source_id": "test-post",
    "url": "https://automatedge.ai/blog/test-post",
}


def test_render_share_modal_html_escapes_xss() -> None:
    evil_title = "<script>alert(1)</script>"
    html_out = render_share_modal(
        share_copy=_GOOD_COPY,
        title=evil_title,
        description="Safe description.",
        **_RENDER_DEFAULTS,
    )
    # The escaped form must appear; the raw <script>alert(1)</script>
    # must NOT appear inside the modal markup. (The trailing JS block
    # legitimately contains the substring "<script>" as part of its own
    # opening tag — we verify only the title-escape path here.)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_out, (
        "Expected escaped XSS payload in output, not found"
    )
    # And the literal evil string did not survive into the title slot
    assert f'<p class="ttl">{evil_title}</p>' not in html_out, (
        "Evil title slipped into <p class=\"ttl\"> unescaped"
    )


def test_render_share_modal_json_island_no_close_tag_break() -> None:
    evil_copy = {
        "twitter": "evil </script><img onerror=x>",
        "linkedin": "ok",
    }
    html_out = render_share_modal(
        share_copy=evil_copy,
        title="Normal title",
        description="Normal description.",
        **_RENDER_DEFAULTS,
    )
    # The raw </script> must NOT appear inside the JSON island content.
    # Output now includes a trailing inline JS <script>...</script> block
    # AFTER the JSON island, so use find() (first occurrence) to locate
    # the JSON island's own closing tag, not rfind() which would walk
    # past it into the JS block.
    start_marker = '<script id="shareCopyData" type="application/json">'
    end_marker = "</script>"
    start_idx = html_out.find(start_marker)
    assert start_idx != -1, "JSON island script tag not found in output"
    json_content_start = start_idx + len(start_marker)
    json_close = html_out.find(end_marker, json_content_start)
    assert json_close != -1, "JSON island closing </script> not found"
    json_data_only = html_out[json_content_start:json_close]
    assert "</script>" not in json_data_only, (
        "Raw </script> found inside JSON island content — injection risk"
    )
    # Confirm the escaped form IS present
    assert "<\\/script>" in json_data_only or r"<\/script>" in json_data_only, (
        "Expected escaped <\\/script> inside JSON island, not found"
    )


def test_render_share_modal_emits_data_attrs() -> None:
    """surface / source_id / source_url must surface as data-* on the overlay."""
    html_out = render_share_modal(
        share_copy=_GOOD_COPY,
        title="Title",
        description="Desc.",
        og_image_url="https://automatedge.ai/og.png",
        surface="job",
        source_id="ml-engineer-at-anthropic-abc123",
        url="https://automatedge.ai/jobs/ml-engineer-at-anthropic-abc123",
    )
    assert 'data-surface="job"' in html_out
    assert 'data-source-id="ml-engineer-at-anthropic-abc123"' in html_out
    assert 'data-source-url="https://automatedge.ai/jobs/ml-engineer-at-anthropic-abc123"' in html_out


def test_render_share_modal_data_attrs_xss_escaped() -> None:
    """Any HTML metachars in surface/source_id/url must be escaped."""
    html_out = render_share_modal(
        share_copy=_GOOD_COPY,
        title="Title",
        description="Desc.",
        og_image_url="https://automatedge.ai/og.png",
        surface='blog" onerror="alert(1)',
        source_id="abc",
        url="https://automatedge.ai/x",
    )
    # The raw quote-breaking payload must NOT appear; the escaped form must
    assert 'onerror="alert(1)' not in html_out
    assert "&quot;" in html_out


def test_render_share_modal_emits_share_log_endpoint() -> None:
    """Inline JS block must reference the /api/share/log endpoint."""
    html_out = render_share_modal(
        share_copy=_GOOD_COPY,
        title="Title",
        description="Desc.",
        **_RENDER_DEFAULTS,
    )
    assert "/api/share/log" in html_out, "Inline JS missing /api/share/log POST"
    assert "navigator.sendBeacon" in html_out, "Inline JS missing sendBeacon path"


# ---------------------------------------------------------------------------
# Twitter truncation test
# ---------------------------------------------------------------------------


def test_long_twitter_truncated() -> None:
    long_description = "A" * 500
    post = {
        "title": "Some Post",
        "description": long_description,
        "lede": "Lede that is quite short.",
        "tags": ["rag"],
        "pillar_tier": 1,
    }
    result = build_share_copy(surface="blog", url=_URL, payload=post)
    assert len(result["twitter"]) <= 280, (
        f"Twitter draft not truncated: {len(result['twitter'])} chars"
    )
    assert _URL in result["twitter"], "URL was removed during truncation"
