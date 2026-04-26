"""Publish-gate tests (session 9).

Auto-publish is disabled by policy. publish_template() requires an admin_name,
and publishing stamps last_reviewed_on + last_reviewed_by into _meta.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.curriculum import loader


@pytest.fixture(autouse=True)
def _isolated_meta(tmp_path, monkeypatch):
    """Point the loader at a temp _meta.json so tests don't mutate real state."""
    meta = tmp_path / "_meta.json"
    monkeypatch.setattr(loader, "META_PATH", meta)
    loader.load_template.cache_clear()
    yield
    loader.load_template.cache_clear()


def test_publish_requires_admin_name():
    with pytest.raises(ValueError, match="admin_name"):
        loader.publish_template("some_key", 95, admin_name="")


def test_publish_below_threshold_returns_false():
    ok = loader.publish_template("sub_90", 85, admin_name="alice@example.com")
    assert ok is False
    # No meta entry should be stamped as published
    assert loader.get_template_status("sub_90")["status"] == "draft"


def test_publish_stamps_reviewer_and_date():
    ok = loader.publish_template("good_key", 93, admin_name="Manish Kumar")
    assert ok is True
    stamp = loader.get_review_stamp("good_key")
    assert stamp["last_reviewed_by"] == "Manish Kumar"
    # ISO date YYYY-MM-DD
    assert stamp["last_reviewed_on"] and len(stamp["last_reviewed_on"]) == 10
    assert stamp["last_reviewed_on"][4] == "-" and stamp["last_reviewed_on"][7] == "-"


def test_unpublish_preserves_review_stamp():
    """Unpublishing keeps the historical review stamp for audit."""
    loader.publish_template("k", 95, admin_name="admin@example.com")
    loader.unpublish_template("k")
    stamp = loader.get_review_stamp("k")
    assert stamp["last_reviewed_by"] == "admin@example.com"


def test_update_quality_score_does_not_touch_stamp():
    loader.publish_template("k", 95, admin_name="admin@example.com")
    loader.update_quality_score("k", 88)
    stamp = loader.get_review_stamp("k")
    assert stamp["last_reviewed_by"] == "admin@example.com"
    assert loader.get_template_status("k")["quality_score"] == 88


def test_get_review_stamp_unknown_key():
    stamp = loader.get_review_stamp("nope")
    assert stamp == {"last_reviewed_on": None, "last_reviewed_by": None}


def test_set_template_status_published_always_stamps_date():
    """set_template_status('published', ...) must ALWAYS stamp
    last_reviewed_on, even when reviewer_name is missing. The "New
    courses" weekly digest section filters by recency — an unstamped
    publish silently drops the template from user emails, which is what
    this fix permanently closes. last_reviewed_by is only set when a
    real reviewer name is supplied (no auto-attributed identity)."""
    # No reviewer_name → date stamped, reviewer left unset
    loader.set_template_status("k_no_reviewer", "published", quality_score=95)
    stamp = loader.get_review_stamp("k_no_reviewer")
    assert stamp["last_reviewed_on"] and len(stamp["last_reviewed_on"]) == 10
    assert stamp["last_reviewed_by"] in (None, "")  # nothing claimed

    # Empty-string reviewer_name → same: date stamped, no reviewer
    loader.set_template_status("k_empty", "published", quality_score=95, reviewer_name="")
    stamp = loader.get_review_stamp("k_empty")
    assert stamp["last_reviewed_on"]
    assert stamp["last_reviewed_by"] in (None, "")

    # Real reviewer_name → both stamped
    loader.set_template_status("k_named", "published", quality_score=95, reviewer_name="Manish Kumar")
    stamp = loader.get_review_stamp("k_named")
    assert stamp["last_reviewed_on"]
    assert stamp["last_reviewed_by"] == "Manish Kumar"

    # Draft transitions don't need or get a date stamp
    loader.set_template_status("k_draft", "draft", quality_score=10)
    assert loader.get_template_status("k_draft")["status"] == "draft"
