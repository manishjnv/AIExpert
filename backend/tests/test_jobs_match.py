"""Match-% scoring tests.

v2 formula: 0.5 * modules_overlap + 0.3 * skills_overlap + 0.2 * level_fit.

Module overlap depends on which curriculum weeks teach each must-have skill.
These tests run against the real grandfathered generalist templates (always
published), so 'PyTorch' has weeks but 'MLOps' / 'RLHF' don't — that's the
baseline the expected scores account for.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

import app.db as db_module
from app.db import Base, close_db, init_db
from app.models import Job
from app.models.plan import Evaluation, RepoLink, UserPlan
from app.models.user import User
from app.services.jobs_match import compute_match


async def _setup():
    await init_db(url="sqlite+aiosqlite:///:memory:")
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _seed_user_with_strengths(strengths: list[str], level: str = "advanced") -> User:
    async with db_module.async_session_factory() as db:
        user = User(email="t@t.com", provider="otp", experience_level=level)
        db.add(user)
        await db.flush()
        plan = UserPlan(user_id=user.id, template_key="k", plan_version="v1", status="active")
        db.add(plan)
        await db.flush()
        link = RepoLink(user_plan_id=plan.id, week_num=1, repo_owner="me", repo_name="r")
        db.add(link)
        await db.flush()
        db.add(Evaluation(
            repo_link_id=link.id, score=9, summary="s",
            strengths_json=json.dumps(strengths), improvements_json="[]",
            deliverable_met=True, commit_sha="a", model="m",
        ))
        await db.commit()
        return user


def _job(must: list[str], yrs_min: int | None = None, yrs_max: int | None = None) -> Job:
    return Job(
        source="t", external_id="1", source_url="", hash="h", status="published",
        posted_on=date.today(), valid_through=date.today(), slug="s",
        title="t", company_slug="c", designation="ML Engineer", verified=0,
        data={
            "must_have_skills": must,
            "employment": {"experience_years": {"min": yrs_min, "max": yrs_max}},
        },
    )


@pytest.mark.asyncio
async def test_full_skill_match_plus_level_fit():
    await _setup()
    user = await _seed_user_with_strengths(["PyTorch", "MLOps"], level="advanced")
    async with db_module.async_session_factory() as db:
        m = await compute_match(user, _job(["PyTorch", "MLOps"], 5, 8), db)
    # User has both skills (repo strengths), but no completed weeks.
    # Curriculum teaches PyTorch → covered=1, user_has=0 → mod=0.
    # 0.5*0 + 0.3*1.0 + 0.2*1.0 = 0.50 → 50
    assert m["score"] == 50
    assert m["missing_skills"] == []
    await close_db()


@pytest.mark.asyncio
async def test_half_skill_match():
    await _setup()
    user = await _seed_user_with_strengths(["pytorch"], level="advanced")
    async with db_module.async_session_factory() as db:
        m = await compute_match(user, _job(["PyTorch", "RLHF"], 5, 8), db)
    # skills 0.5, level 1.0, mod 0 (PyTorch covered but not completed; RLHF unknown to curriculum).
    # 0.5*0 + 0.3*0.5 + 0.2*1.0 = 0.35 → 35
    assert m["score"] == 35
    assert m["missing_skills"] == ["RLHF"]
    await close_db()


@pytest.mark.asyncio
async def test_level_mismatch_drops_score():
    await _setup()
    user = await _seed_user_with_strengths(["PyTorch"], level="beginner")
    async with db_module.async_session_factory() as db:
        m = await compute_match(user, _job(["PyTorch"], 5, 8), db)
    # skills 1.0, level 0.3, mod 0 → 0+0.3+0.06 = 0.36 → 36
    assert m["score"] == 36
    await close_db()


@pytest.mark.asyncio
async def test_missing_experience_range_is_neutral():
    await _setup()
    user = await _seed_user_with_strengths(["PyTorch"], level="advanced")
    async with db_module.async_session_factory() as db:
        m = await compute_match(user, _job(["PyTorch"], None, None), db)
    # skills 1.0, level 0.6 neutral, mod 0 → 0+0.3+0.12 = 0.42 → 42
    assert m["score"] == 42
    await close_db()


@pytest.mark.asyncio
async def test_skill_matching_is_case_insensitive():
    await _setup()
    user = await _seed_user_with_strengths(["  PyTorch ", "distributed training"], level="advanced")
    async with db_module.async_session_factory() as db:
        m = await compute_match(user, _job(["pytorch", "Distributed Training"], 5, 8), db)
    # User has both skills, level 1.0. PyTorch covered+not-completed → mod=0,
    # 'Distributed Training' not in curriculum tokens. 0+0.3+0.2 = 0.50 → 50
    assert m["score"] == 50
    await close_db()


# ---------- v2: module-overlap + gap_weeks ----------

@pytest.mark.asyncio
async def test_skills_with_no_curriculum_match_land_in_dedicated_bucket():
    """must_have_skills the curriculum doesn't teach show up under
    skills_without_curriculum so the UI can distinguish 'not yet learned'
    from 'plan never covers this'."""
    await _setup()
    user = await _seed_user_with_strengths([], level="advanced")
    async with db_module.async_session_factory() as db:
        m = await compute_match(user, _job(["RLHF", "Kubernetes"], 5, 8), db)
    # Neither skill is in curriculum tokens → mod_overlap falls back to neutral 0.5.
    assert m["modules_overlap"] == 0.5
    assert set(m["skills_without_curriculum"]) == {"RLHF", "Kubernetes"}
    assert m["gap_weeks"] == []
    await close_db()


@pytest.mark.asyncio
async def test_gap_weeks_populated_for_missing_curriculum_skills():
    """When the user is missing a skill the curriculum teaches, the weeks
    teaching it are surfaced as gap_weeks for the 'Close the gap' CTA."""
    await _setup()
    user = await _seed_user_with_strengths([], level="advanced")
    async with db_module.async_session_factory() as db:
        m = await compute_match(user, _job(["PyTorch"], 5, 8), db)
    assert any("template_key" in w and "week_num" in w for w in m["gap_weeks"])
    # The returned ref should include enough for the UI to render a link.
    first = m["gap_weeks"][0]
    assert first["template_key"]
    assert isinstance(first["week_num"], int)
    assert first["title"]
    assert first["month"]
    await close_db()


@pytest.mark.asyncio
async def test_payload_includes_v2_fields():
    """Contract check: match payload always exposes the v2 keys so UI/email
    consumers don't need defensive .get() everywhere."""
    await _setup()
    user = await _seed_user_with_strengths(["pytorch"], level="advanced")
    async with db_module.async_session_factory() as db:
        m = await compute_match(user, _job(["PyTorch"], 5, 8), db)
    for k in ("score", "modules_overlap", "skills_overlap", "level_fit",
             "missing_skills", "gap_weeks", "skills_without_curriculum"):
        assert k in m, f"match payload missing {k}"
    await close_db()
