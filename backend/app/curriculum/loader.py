"""
Plan template loader — reads JSON templates from disk and validates
them against Pydantic schemas.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

TEMPLATES_DIR = Path(__file__).parent / "templates"


# ---- Pydantic schemas ----

class Resource(BaseModel):
    name: str
    url: str
    hrs: int


class Week(BaseModel):
    n: int
    t: str
    hours: int
    focus: list[str]
    deliv: list[str]
    resources: list[Resource]
    checks: list[str]


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
    months: list[Month]

    @property
    def total_weeks(self) -> int:
        return sum(len(m.weeks) for m in self.months)

    @property
    def total_checks(self) -> int:
        return sum(len(w.checks) for m in self.months for w in m.weeks)

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
    """Return available template keys."""
    return [p.stem for p in TEMPLATES_DIR.glob("*.json")]
