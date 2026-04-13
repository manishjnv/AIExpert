"""Tests for the Coursera affiliate URL rewriter."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from app.services import affiliate


AFF = "partner-123"


def _ir(url: str) -> str | None:
    qs = parse_qs(urlparse(url).query)
    vals = qs.get("irclickid")
    return vals[0] if vals else None


# ---- Single-URL rewriter ----

def test_empty_affiliate_id_is_noop():
    url = "https://www.coursera.org/learn/machine-learning"
    assert affiliate.rewrite_url(url, affiliate_id="") == url


def test_rewrite_learn_url_adds_irclickid():
    out = affiliate.rewrite_url(
        "https://www.coursera.org/learn/machine-learning", affiliate_id=AFF
    )
    click = _ir(out)
    assert click is not None and click.startswith(f"{AFF}-")


def test_rewrite_specialization_url_adds_irclickid():
    out = affiliate.rewrite_url(
        "https://www.coursera.org/specializations/deep-learning", affiliate_id=AFF
    )
    assert _ir(out) is not None


def test_existing_query_params_preserved():
    url = "https://www.coursera.org/learn/ml?foo=bar&baz=qux"
    out = affiliate.rewrite_url(url, affiliate_id=AFF)
    qs = parse_qs(urlparse(out).query)
    assert qs["foo"] == ["bar"]
    assert qs["baz"] == ["qux"]
    assert "irclickid" in qs


def test_existing_irclickid_not_overwritten():
    url = "https://www.coursera.org/learn/ml?irclickid=existing-click"
    assert affiliate.rewrite_url(url, affiliate_id=AFF) == url


def test_non_coursera_url_unchanged():
    for url in [
        "https://www.udacity.com/course/intro-to-ml",
        "https://fast.ai/courses/",
        "https://www.deeplearning.ai/short-courses/",
        "https://coursera.com/learn/ml",  # wrong TLD
    ]:
        assert affiliate.rewrite_url(url, affiliate_id=AFF) == url


def test_coursera_non_learn_path_unchanged():
    """Only /learn/* and /specializations/* get rewritten."""
    for url in [
        "https://www.coursera.org/",
        "https://www.coursera.org/professional-certificates/google-data-analytics",
        "https://www.coursera.org/learn/",  # empty slug
    ]:
        assert affiliate.rewrite_url(url, affiliate_id=AFF) == url


def test_malformed_url_handled_gracefully():
    assert affiliate.rewrite_url("", affiliate_id=AFF) == ""
    assert affiliate.rewrite_url("not a url", affiliate_id=AFF) == "not a url"


def test_subdomain_coursera_rewritten():
    url = "https://in.coursera.org/learn/ml"
    assert _ir(affiliate.rewrite_url(url, affiliate_id=AFF)) is not None


def test_click_ids_are_unique_per_call():
    url = "https://www.coursera.org/learn/ml"
    a = _ir(affiliate.rewrite_url(url, affiliate_id=AFF))
    b = _ir(affiliate.rewrite_url(url, affiliate_id=AFF))
    assert a != b


# ---- Plan-level rewriter ----

def _plan_fixture():
    return {
        "title": "Test",
        "top_resources": [
            {"name": "Coursera ML", "url": "https://www.coursera.org/learn/machine-learning", "hrs": 40},
            {"name": "fast.ai", "url": "https://fast.ai/courses/", "hrs": 20},
        ],
        "certifications": [
            {"name": "DL Spec", "provider": "DeepLearning.AI",
             "url": "https://www.coursera.org/specializations/deep-learning"},
        ],
        "months": [
            {
                "weeks": [
                    {
                        "n": 1, "resources": [
                            {"name": "X", "url": "https://www.coursera.org/learn/x", "hrs": 10},
                            {"name": "Y", "url": "https://github.com/foo/bar", "hrs": 5},
                        ],
                    },
                ],
            },
        ],
    }


def test_rewrite_plan_no_affiliate_returns_identity(monkeypatch):
    monkeypatch.setattr(affiliate, "get_settings",
                        lambda: type("S", (), {"coursera_affiliate_id": ""})())
    plan = _plan_fixture()
    out = affiliate.rewrite_plan(plan)
    assert out is plan  # early-return identity when disabled


def test_rewrite_plan_covers_all_three_fields(monkeypatch):
    monkeypatch.setattr(affiliate, "get_settings",
                        lambda: type("S", (), {"coursera_affiliate_id": AFF})())
    plan = _plan_fixture()
    out = affiliate.rewrite_plan(plan)
    # Original untouched (deepcopy)
    assert plan["top_resources"][0]["url"] == "https://www.coursera.org/learn/machine-learning"
    assert _ir(out["top_resources"][0]["url"]) is not None
    assert _ir(out["certifications"][0]["url"]) is not None
    assert _ir(out["months"][0]["weeks"][0]["resources"][0]["url"]) is not None
    # Non-coursera URLs untouched
    assert out["top_resources"][1]["url"] == "https://fast.ai/courses/"
    assert out["months"][0]["weeks"][0]["resources"][1]["url"] == "https://github.com/foo/bar"
