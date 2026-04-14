"""Match-% scoring between a user and a job.

v1 is deterministic, no ML. See docs/JOBS.md §9 for the formula. This is
simpler than spec: module-overlap requires template content access, so v1
uses skills + level only. Revisit when template content is queryable.

    match = 0.7 * skills_overlap + 0.3 * level_fit

    skills_overlap = |user_skills ∩ job.must_have_skills| / |job.must_have_skills|
    level_fit      = 1.0 if user_level ∈ job.experience_years range else 0.3
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job
from app.models.plan import Evaluation, RepoLink, UserPlan
from app.models.user import User

logger = logging.getLogger("roadmap.jobs.match")


LEVEL_TO_YEARS = {
    "beginner": (0, 2),
    "intermediate": (2, 5),
    "advanced": (5, 20),
}


def _normalize_skill(s: str) -> str:
    return s.strip().lower()


async def _user_skills(user_id: int, db: AsyncSession) -> set[str]:
    """Union of strengths from the user's repo evaluations. Lowercased."""
    stmt = (select(Evaluation.strengths_json)
            .join(RepoLink, RepoLink.id == Evaluation.repo_link_id)
            .join(UserPlan, UserPlan.id == RepoLink.user_plan_id)
            .where(UserPlan.user_id == user_id))
    rows = (await db.execute(stmt)).scalars().all()

    skills: set[str] = set()
    for raw in rows:
        try:
            items = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except Exception:
            continue
        for s in items or []:
            if isinstance(s, str):
                skills.add(_normalize_skill(s))
    return skills


def _level_fit(user: User, job: Job) -> float:
    exp = ((job.data or {}).get("employment") or {}).get("experience_years") or {}
    jmin, jmax = exp.get("min"), exp.get("max")
    if not isinstance(jmin, int) or not isinstance(jmax, int):
        return 0.6  # unknown requirement — neutral
    rng = LEVEL_TO_YEARS.get((user.experience_level or "").lower())
    if not rng:
        return 0.6
    umin, umax = rng
    # Overlap check.
    if umax < jmin or umin > jmax:
        return 0.3
    return 1.0


async def compute_match(user: User, job: Job, db: AsyncSession) -> dict[str, Any]:
    """Returns { score: 0-100, skills_overlap, level_fit, missing_skills[] }."""
    must = [(s or "").strip() for s in ((job.data or {}).get("must_have_skills") or []) if s]
    must_norm = {_normalize_skill(s) for s in must}

    user_skills = await _user_skills(user.id, db)

    if must_norm:
        matched = must_norm & user_skills
        skills_overlap = len(matched) / len(must_norm)
        missing = [s for s in must if _normalize_skill(s) not in user_skills]
    else:
        skills_overlap = 0.5  # no requirements listed — neutral
        missing = []

    lvl = _level_fit(user, job)
    score = round((0.7 * skills_overlap + 0.3 * lvl) * 100)
    return {
        "score": score,
        "skills_overlap": round(skills_overlap, 2),
        "level_fit": round(lvl, 2),
        "missing_skills": missing[:8],
        "matched_skills_count": len(must_norm & user_skills) if must_norm else 0,
    }
