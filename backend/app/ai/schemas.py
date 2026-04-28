"""
Gemini structured output schemas.

Defines JSON schemas in Gemini's responseSchema format to guarantee valid output.
This eliminates retry loops from malformed JSON — Gemini enforces the schema natively.

Reference: https://ai.google.dev/gemini-api/docs/structured-output
"""

# PlanTemplate schema for curriculum generation.
# Gemini uses a subset of OpenAPI 3.0 schema — no $ref, no oneOf, no const.
PLAN_TEMPLATE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "key": {"type": "STRING"},
        "version": {"type": "STRING"},
        "title": {"type": "STRING"},
        "level": {"type": "STRING", "enum": ["beginner", "intermediate", "advanced"]},
        "goal": {"type": "STRING"},
        "duration_months": {"type": "INTEGER"},
        "months": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "month": {"type": "INTEGER"},
                    "label": {"type": "STRING"},
                    "title": {"type": "STRING"},
                    "tagline": {"type": "STRING"},
                    "checkpoint": {"type": "STRING"},
                    "weeks": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "n": {"type": "INTEGER"},
                                "t": {"type": "STRING"},
                                "hours": {"type": "INTEGER"},
                                "focus": {
                                    "type": "ARRAY",
                                    "items": {"type": "STRING"},
                                },
                                "deliv": {
                                    "type": "ARRAY",
                                    "items": {"type": "STRING"},
                                },
                                "resources": {
                                    "type": "ARRAY",
                                    "items": {
                                        "type": "OBJECT",
                                        "properties": {
                                            "name": {"type": "STRING"},
                                            "url": {"type": "STRING"},
                                            "hrs": {"type": "INTEGER"},
                                        },
                                        "required": ["name", "url", "hrs"],
                                    },
                                },
                                "checks": {
                                    "type": "ARRAY",
                                    "items": {"type": "STRING"},
                                },
                            },
                            "required": ["n", "t", "hours", "focus", "deliv", "resources", "checks"],
                        },
                    },
                },
                "required": ["month", "label", "title", "tagline", "checkpoint", "weeks"],
            },
        },
    },
    "required": ["key", "version", "title", "level", "goal", "duration_months", "months"],
}

# Quality review response schema
QUALITY_REVIEW_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "blooms_progression": {
            "type": "OBJECT",
            "properties": {
                "score": {"type": "INTEGER"},
                "issues": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": ["score", "issues"],
        },
        "theory_practice_ratio": {
            "type": "OBJECT",
            "properties": {
                "score": {"type": "INTEGER"},
                "issues": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": ["score", "issues"],
        },
        "project_density": {
            "type": "OBJECT",
            "properties": {
                "score": {"type": "INTEGER"},
                "issues": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": ["score", "issues"],
        },
        "assessment_quality": {
            "type": "OBJECT",
            "properties": {
                "score": {"type": "INTEGER"},
                "issues": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": ["score", "issues"],
        },
        "completeness": {
            "type": "OBJECT",
            "properties": {
                "score": {"type": "INTEGER"},
                "issues": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": ["score", "issues"],
        },
        "difficulty_calibration": {
            "type": "OBJECT",
            "properties": {
                "score": {"type": "INTEGER"},
                "issues": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": ["score", "issues"],
        },
        "industry_alignment": {
            "type": "OBJECT",
            "properties": {
                "score": {"type": "INTEGER"},
                "issues": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": ["score", "issues"],
        },
        "freshness": {
            "type": "OBJECT",
            "properties": {
                "score": {"type": "INTEGER"},
                "issues": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": ["score", "issues"],
        },
        "prerequisites_clarity": {
            "type": "OBJECT",
            "properties": {
                "score": {"type": "INTEGER"},
                "issues": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": ["score", "issues"],
        },
        "real_world_readiness": {
            "type": "OBJECT",
            "properties": {
                "score": {"type": "INTEGER"},
                "issues": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": ["score", "issues"],
        },
        "overall_score": {"type": "INTEGER"},
        "critical_fixes": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "week": {"type": "INTEGER"},
                    "field": {"type": "STRING"},
                    "problem": {"type": "STRING"},
                    "fix": {"type": "STRING"},
                },
                "required": ["week", "field", "problem", "fix"],
            },
        },
    },
    "required": [
        "blooms_progression", "theory_practice_ratio", "project_density",
        "assessment_quality", "completeness", "difficulty_calibration",
        "industry_alignment", "freshness", "prerequisites_clarity",
        "real_world_readiness", "overall_score", "critical_fixes",
    ],
}

# ---------------------------------------------------------------------------
# Pydantic models — Track 1 (Opus via Claude CLI) output validation
# Per AI_PIPELINE_PLAN.md §4 invariant #4 (mandatory reasoning trail) and
# §3.11 (social post curation v1).
# ---------------------------------------------------------------------------

import re
from typing import Literal
from pydantic import BaseModel, Field, model_validator

_HASHTAG_RE = re.compile(r"^#[A-Z][A-Za-z0-9]+$")
_BRAND_TAG = "#AutomateEdge"


class ReasoningTrail(BaseModel):
    """Per-output reasoning trail — invariant #4 across all Track 1 surfaces.

    evidence_sources MUST be non-empty: empty array means the model hallucinated.
    """
    score_justification: str = Field(..., min_length=10)
    evidence_sources: list[str] = Field(..., min_length=1)
    uncertainty_factors: list[str] = Field(default_factory=list)


class SocialDraftSchema(BaseModel):
    """One social-post draft (Twitter or LinkedIn). §3.11 v1.

    Validation dispatches by `platform` field:
      twitter  → body ≤ 280, hashtags 1-2, never includes #AutomateEdge
      linkedin → body ≤ 3000, hashtags 3-5, last entry exactly #AutomateEdge

    Hashtag format ^#[A-Z][A-Za-z0-9]+$ enforced on every entry.
    No `#` chars allowed in body (hashtags live ONLY in the hashtags array).
    """
    platform: Literal["twitter", "linkedin"]
    body: str = Field(..., min_length=1)
    hashtags: list[str] = Field(..., min_length=1)
    reasoning: ReasoningTrail

    @model_validator(mode="after")
    def _validate(self):
        # Hashtag format on every entry (both platforms)
        for tag in self.hashtags:
            if tag == _BRAND_TAG:
                continue  # #AutomateEdge has different shape; allowed only on LinkedIn last
            if not _HASHTAG_RE.match(tag):
                raise ValueError(
                    f"hashtag {tag!r} not canonical form ^#[A-Z][A-Za-z0-9]+$"
                )
        # No '#' in body (hashtags must not be inline)
        if "#" in self.body:
            raise ValueError("hashtags must not appear inline in body")
        # Per-platform rules
        if self.platform == "twitter":
            if len(self.body) > 280:
                raise ValueError(f"Twitter body {len(self.body)} chars > 280")
            if not (1 <= len(self.hashtags) <= 2):
                raise ValueError(
                    f"Twitter requires 1-2 hashtags, got {len(self.hashtags)}"
                )
            if _BRAND_TAG in self.hashtags:
                raise ValueError("Twitter must not include #AutomateEdge")
        else:  # linkedin
            if len(self.body) > 3000:
                raise ValueError(f"LinkedIn body {len(self.body)} chars > 3000")
            if not (3 <= len(self.hashtags) <= 5):
                raise ValueError(
                    f"LinkedIn requires 3-5 hashtags, got {len(self.hashtags)}"
                )
            if self.hashtags[-1] != _BRAND_TAG:
                raise ValueError(
                    f"LinkedIn hashtags must end with #AutomateEdge, got {self.hashtags[-1]!r}"
                )
        return self


class SocialCurateOutput(BaseModel):
    """Top-level Opus output: one source -> one Twitter draft + one LinkedIn draft."""
    twitter: SocialDraftSchema
    linkedin: SocialDraftSchema

    @model_validator(mode="after")
    def _validate_platforms(self):
        if self.twitter.platform != "twitter":
            raise ValueError("twitter draft must have platform='twitter'")
        if self.linkedin.platform != "linkedin":
            raise ValueError("linkedin draft must have platform='linkedin'")
        return self
