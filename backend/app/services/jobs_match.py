"""Match-% scoring between a user and a job.

v2 formula:

    match = 0.5 * modules_overlap + 0.3 * skills_overlap + 0.2 * level_fit

    modules_overlap = |user_completed_weeks ∩ weeks_teaching_job_skills|
                      / |weeks_teaching_job_skills|
    skills_overlap  = |user_skills ∩ job.must_have_skills| / |job.must_have_skills|
    level_fit       = 1.0 if user_level ∈ job.experience_years range else 0.3

Modules are computed via jobs_modules.find_weeks_for_skill(): each must-have
skill maps to curriculum weeks that teach it. Match scores how many of those
weeks the user has already completed (all checklist items done in that week).

If the curriculum has zero weeks matching any must-have skill, modules_overlap
falls back to 0.5 (neutral) so the score isn't crushed — this tends to happen
for non-technical AI roles (e.g. Product Manager).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.curriculum.loader import load_template
from app.models import Job
from app.models.plan import Evaluation, Progress, RepoLink, UserPlan
from app.models.user import User
from app.services.jobs_modules import WeekRef, find_weeks_for_skill

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


async def _completed_weeks(user_id: int, db: AsyncSession) -> set[tuple[str, int]]:
    """Weeks where the user has ticked every checklist item. Returned as
    (template_key, week_num) pairs so cross-template enrollment also counts.

    A week is 'complete' iff every Progress.check_idx for that week is done.
    Since templates vary in checks-per-week, we compute per (plan, week):
    total_checks in the template, completed = sum(Progress.done). Complete
    iff they match.
    """
    # Collapse in Python — cleaner than a cross-dialect bool-to-int cast.
    stmt = (select(UserPlan.template_key, Progress.week_num, Progress.done)
            .join(Progress, Progress.user_plan_id == UserPlan.id)
            .where(UserPlan.user_id == user_id))
    rows = (await db.execute(stmt)).all()

    # Group by (template_key, week_num).
    by_week: dict[tuple[str, int], list[bool]] = {}
    for tk, wn, done in rows:
        by_week.setdefault((tk, wn), []).append(bool(done))

    # Mark complete only if every check for that week is True AND the week
    # had the expected number of checks per its template definition.
    completed: set[tuple[str, int]] = set()
    for (tk, wn), flags in by_week.items():
        if not all(flags):
            continue
        try:
            tpl = load_template(tk)
        except Exception:
            continue
        expected = 0
        for m in tpl.months:
            for w in m.weeks:
                if w.n == wn:
                    expected = len(w.checks)
                    break
        if expected and len(flags) >= expected:
            completed.add((tk, wn))
    return completed


def _modules_overlap(must_skills: list[str], completed: set[tuple[str, int]]
                     ) -> tuple[float, list[WeekRef], list[str]]:
    """For each must-have skill, find curriculum weeks teaching it. Returns
    (overlap_fraction, top_gap_weeks, skills_with_no_curriculum_match).

    overlap_fraction is over skills that DO have a curriculum match — skills
    the curriculum doesn't teach at all (e.g. Kubernetes on a pure-ML plan)
    are surfaced separately so the UI can differentiate 'you haven't learned
    this yet' from 'the plan never covers this'.
    """
    if not must_skills:
        return 0.5, [], []  # neutral

    covered_skills = 0
    user_has = 0
    gap_weeks: list[WeekRef] = []
    no_match: list[str] = []

    for skill in must_skills:
        weeks = find_weeks_for_skill(skill, limit=2)
        if not weeks:
            no_match.append(skill)
            continue
        covered_skills += 1
        if any((w.template_key, w.week_num) in completed for w in weeks):
            user_has += 1
        else:
            # Surface the shallowest week as the 'close the gap' target.
            gap_weeks.append(weeks[0])

    if covered_skills == 0:
        return 0.5, [], no_match
    return user_has / covered_skills, gap_weeks[:5], no_match


async def compute_match(user: User, job: Job, db: AsyncSession) -> dict[str, Any]:
    """Returns the full match payload — used by the API endpoint + digest."""
    must_raw = [(s or "").strip() for s in ((job.data or {}).get("must_have_skills") or []) if s]
    must_norm = {_normalize_skill(s) for s in must_raw}

    user_skills = await _user_skills(user.id, db)
    completed = await _completed_weeks(user.id, db)

    # Skills overlap (unchanged from v1).
    if must_norm:
        matched_ct = len(must_norm & user_skills)
        skills_overlap = matched_ct / len(must_norm)
        missing_skills = [s for s in must_raw if _normalize_skill(s) not in user_skills]
    else:
        skills_overlap = 0.5
        missing_skills = []
        matched_ct = 0

    # Module overlap (new in v2).
    mod_overlap, gap_weeks, no_curriculum = _modules_overlap(must_raw, completed)

    lvl = _level_fit(user, job)

    score = round((0.5 * mod_overlap + 0.3 * skills_overlap + 0.2 * lvl) * 100)

    return {
        "score": score,
        "modules_overlap": round(mod_overlap, 2),
        "skills_overlap": round(skills_overlap, 2),
        "level_fit": round(lvl, 2),
        "missing_skills": missing_skills[:8],
        "matched_skills_count": matched_ct,
        # Close-the-gap targets: deepest-actionable missing weeks.
        "gap_weeks": [
            {"template_key": w.template_key, "week_num": w.week_num,
             "title": w.week_title, "month": w.month}
            for w in gap_weeks
        ],
        # Skills the curriculum doesn't teach (yet) — useful UI hint.
        "skills_without_curriculum": no_curriculum[:5],
    }
