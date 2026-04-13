"""
Plan template loader — reads JSON templates from disk and validates
them against Pydantic schemas.

Publishing model:
- All templates are saved as drafts by default
- Templates must score >= PUBLISH_THRESHOLD (90) to be publishable
- Admin can publish/unpublish via API
- User-facing endpoints only see published templates
- _meta.json in templates dir tracks status + scores
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("roadmap.loader")

TEMPLATES_DIR = Path(__file__).parent / "templates"
META_PATH = TEMPLATES_DIR / "_meta.json"
PUBLISH_THRESHOLD = 90


# ---- Pydantic schemas ----

class Resource(BaseModel):
    name: str
    url: str
    hrs: int


class Certification(BaseModel):
    """Industry certification a learner can pursue after completing the course."""
    name: str
    provider: str                   # e.g. "DeepLearning.AI", "Google Cloud", "AWS"
    url: str                        # certification info page
    cost_usd: int | None = None     # 0 for free, None if unknown
    prep_hours: int | None = None   # estimated additional prep hours on top of this course


class Week(BaseModel):
    n: int
    t: str
    hours: int = 16
    focus: list[str] = Field(default_factory=list)
    deliv: list[str] = Field(default_factory=list)
    resources: list[Resource] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)


class Month(BaseModel):
    month: int
    label: str
    title: str
    tagline: str
    checkpoint: str
    weeks: list[Week]


class PlanTemplate(BaseModel):
    key: str
    version: str
    title: str
    level: str
    goal: str
    duration_months: int
    # Short 2–3 sentence course description shown on the hero + cert pages.
    # Optional so older templates that predate the field still load; newer
    # auto-generated and Claude-Opus-generated templates always emit it.
    summary: Optional[str] = None
    months: list[Month]
    # Optional course-level metadata (newer templates). Backward-compatible:
    # existing templates that don't carry these just get None.
    top_resources: list[Resource] | None = None      # 3 foundational anchors for the whole course
    certifications: list[Certification] | None = None # industry certs learner can pursue on completion

    @property
    def total_weeks(self) -> int:
        return sum(len(m.weeks) for m in self.months)

    @property
    def total_checks(self) -> int:
        return sum(len(w.checks) for m in self.months for w in m.weeks)

    @property
    def total_hours(self) -> int:
        return sum(w.hours for m in self.months for w in m.weeks)

    @property
    def total_focus_areas(self) -> int:
        """Sum of per-week focus areas across all weeks.

        Note: 'focus areas' are the subtopics taught inside a template.
        Not to be confused with DiscoveredTopic (course subject).
        """
        return sum(len(w.focus) for m in self.months for w in m.weeks)

    @property
    def certification_count(self) -> int:
        """Count of resources/deliverables/checks that reference a certification."""
        n = 0
        for m in self.months:
            for w in m.weeks:
                for r in w.resources:
                    if "certif" in r.name.lower():
                        n += 1
                for d in w.deliv:
                    if "certif" in d.lower():
                        n += 1
                for c in w.checks:
                    if "certif" in c.lower():
                        n += 1
        return n

    @property
    def github_resource_count(self) -> int:
        """DEPRECATED — retained for backward compat. Counts github.com URLs in resources."""
        n = 0
        for m in self.months:
            for w in m.weeks:
                for r in w.resources:
                    if "github.com" in r.url.lower():
                        n += 1
        return n

    @property
    def repos_required(self) -> int:
        """Count of deliverables that the learner must produce as a GitHub artifact.

        Scans deliv[] across all weeks for artifact keywords (repo, notebook,
        project, app, API, service, demo, dashboard, pipeline, etc.) — each
        match is a github-linkable deliverable the user should produce.

        User-facing completion maps to: linked_repos / repos_required (e.g. 4/5).
        """
        import re as _re
        patterns = [
            r"\brepo(sitor(y|ies))?\b",
            r"\bnotebook\b",
            r"\bproject\b",
            r"\bapp(lication)?\b",
            r"\bapi\b",
            r"\bservice\b",
            r"\bserver\b",
            r"\bdemo\b",
            r"\bdashboard\b",
            r"\bpipeline\b",
            r"\bportfolio\b",
            r"\bharness\b",
            r"\bsuite\b",
            r"\blibrary\b",
            r"\bcli\b",
            r"\bsdk\b",
            r"\bpackage\b",
            r"\bbenchmark\b",
            r"\bmiddleware\b",
            r"\bmodel\b",
            r"\bagent\b",
            r"\bmicroservice\b",
            r"\bsite\b",
        ]
        regex = _re.compile("|".join(patterns), _re.IGNORECASE)
        n = 0
        for m in self.months:
            for w in m.weeks:
                for d in w.deliv:
                    if isinstance(d, str) and regex.search(d):
                        n += 1
        return n

    def week_by_number(self, n: int) -> Week | None:
        for m in self.months:
            for w in m.weeks:
                if w.n == n:
                    return w
        return None


# ---- Loader ----

@lru_cache(maxsize=8)
def load_template(key: str) -> PlanTemplate:
    """Load and validate a plan template by key.

    Raises FileNotFoundError if the template doesn't exist.
    Raises pydantic.ValidationError if the JSON doesn't match the schema.
    """
    path = TEMPLATES_DIR / f"{key}.json"
    if not path.exists():
        raise FileNotFoundError(f"Plan template not found: {key}")

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    return PlanTemplate(**data)


def list_templates() -> list[str]:
    """Return ALL template keys (admin use)."""
    return [p.stem for p in TEMPLATES_DIR.glob("*.json") if p.stem != "_meta"]


# ---- Publishing model ----

def _load_meta() -> dict:
    """Load template metadata (publish status + quality scores)."""
    if META_PATH.exists():
        with open(META_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_meta(meta: dict) -> None:
    """Persist template metadata."""
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


def get_template_status(key: str) -> dict:
    """Get publish status for a template."""
    meta = _load_meta()
    return meta.get(key, {"status": "draft", "quality_score": 0})


def set_template_status(key: str, status: str, quality_score: int = 0) -> None:
    """Set publish status for a template ('draft' or 'published')."""
    meta = _load_meta()
    meta[key] = {"status": status, "quality_score": quality_score}
    _save_meta(meta)
    load_template.cache_clear()
    logger.info("Template %s → %s (score: %d)", key, status, quality_score)


def publish_template(key: str, quality_score: int) -> bool:
    """Publish a template if it meets the quality threshold.

    Returns True if published, False if score too low.
    """
    if quality_score < PUBLISH_THRESHOLD:
        return False
    set_template_status(key, "published", quality_score)
    return True


def unpublish_template(key: str) -> None:
    """Move a template back to draft status."""
    meta = _load_meta()
    if key in meta:
        meta[key]["status"] = "draft"
        _save_meta(meta)
        load_template.cache_clear()


def list_published() -> list[str]:
    """Return only published template keys (user-facing).

    The 3 original generalist templates are always published (grandfathered in).
    """
    meta = _load_meta()
    all_keys = list_templates()
    # Generalist templates are always available (they predate the publish system)
    grandfathered = {"generalist_3mo_intermediate", "generalist_6mo_intermediate", "generalist_12mo_beginner"}
    return [k for k in all_keys
            if meta.get(k, {}).get("status") == "published" or k in grandfathered]


def update_quality_score(key: str, score: int) -> None:
    """Update the cached quality score for a template."""
    meta = _load_meta()
    entry = meta.get(key, {"status": "draft", "quality_score": 0})
    entry["quality_score"] = score
    meta[key] = entry
    _save_meta(meta)
