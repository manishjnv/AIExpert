"""Match-% scoring tests. v1 formula: 0.7 * skills + 0.3 * level_fit."""

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
    # 0.7 * 1.0 + 0.3 * 1.0 = 100
    assert m["score"] == 100
    assert m["missing_skills"] == []
    await close_db()


@pytest.mark.asyncio
async def test_half_skill_match():
    await _setup()
    user = await _seed_user_with_strengths(["pytorch"], level="advanced")
    async with db_module.async_session_factory() as db:
        m = await compute_match(user, _job(["PyTorch", "RLHF"], 5, 8), db)
    # skills_overlap 0.5 → 0.7 * 0.5 + 0.3 * 1.0 = 65
    assert m["score"] == 65
    assert m["missing_skills"] == ["RLHF"]
    await close_db()


@pytest.mark.asyncio
async def test_level_mismatch_drops_score():
    await _setup()
    user = await _seed_user_with_strengths(["PyTorch"], level="beginner")
    async with db_module.async_session_factory() as db:
        m = await compute_match(user, _job(["PyTorch"], 5, 8), db)
    # skills 1.0, level 0.3 → 0.7 + 0.09 = 79
    assert m["score"] == 79
    await close_db()


@pytest.mark.asyncio
async def test_missing_experience_range_is_neutral():
    await _setup()
    user = await _seed_user_with_strengths(["PyTorch"], level="advanced")
    async with db_module.async_session_factory() as db:
        m = await compute_match(user, _job(["PyTorch"], None, None), db)
    # level_fit 0.6 neutral → 0.7 + 0.18 = 88
    assert m["score"] == 88
    await close_db()


@pytest.mark.asyncio
async def test_skill_matching_is_case_insensitive():
    await _setup()
    user = await _seed_user_with_strengths(["  PyTorch ", "distributed training"], level="advanced")
    async with db_module.async_session_factory() as db:
        m = await compute_match(user, _job(["pytorch", "Distributed Training"], 5, 8), db)
    assert m["score"] == 100
    await close_db()
