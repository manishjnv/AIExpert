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
