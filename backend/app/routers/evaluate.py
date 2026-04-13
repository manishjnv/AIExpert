"""
Evaluation router — trigger AI evaluation and view history.

All endpoints under /api (prefix set in main.py).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db import get_db
from app.models.plan import Evaluation, RepoLink, UserPlan
from app.models.user import User

router = APIRouter()


class EvaluateBody(BaseModel):
    week_num: int


@router.post("/evaluate")
async def evaluate(
    body: EvaluateBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run AI evaluation on a week's linked repo."""
    # Get active plan
    plan = (
        await db.execute(
            select(UserPlan).where(UserPlan.user_id == user.id, UserPlan.status == "active")
        )
    ).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="No active plan")

    # Get repo link
    repo_link = (
        await db.execute(
            select(RepoLink).where(
                RepoLink.user_plan_id == plan.id,
                RepoLink.week_num == body.week_num,
            )
        )
    ).scalar_one_or_none()
    if repo_link is None:
        raise HTTPException(status_code=404, detail="No repo linked for this week")

    # Check 24h cooldown with row-level lock (SELECT FOR UPDATE via flush)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cooldown_cutoff = now - timedelta(hours=24)
    last_eval = (
        await db.execute(
            select(Evaluation)
            .where(
                Evaluation.repo_link_id == repo_link.id,
                Evaluation.created_at > cooldown_cutoff,
            )
            .order_by(Evaluation.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if last_eval is not None:
        raise HTTPException(status_code=429, detail="Evaluation cooldown: one per repo per 24 hours")

    # Run evaluation
    from app.services.evaluate import run_evaluation
    from app.ai.provider import AIProviderError

    try:
        evaluation = await run_evaluation(repo_link, plan, db)
    except AIProviderError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Evaluation failed. Please try again.")

    # A high-scoring capstone-week eval can trigger the Honors upgrade.
    from app.services.certificates import safe_check_and_issue
    await safe_check_and_issue(db, user, plan)

    return {
        "id": evaluation.id,
        "score": evaluation.score,
        "summary": evaluation.summary,
        "strengths": json.loads(evaluation.strengths_json),
        "improvements": json.loads(evaluation.improvements_json),
        "deliverable_met": evaluation.deliverable_met,
        "commit_sha": evaluation.commit_sha,
        "model": evaluation.model,
        "created_at": evaluation.created_at.isoformat() if evaluation.created_at else None,
    }


@router.get("/evaluations")
async def get_evaluations(
    week_num: int = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return evaluation history for a week, newest first."""
    plan = (
        await db.execute(
            select(UserPlan).where(UserPlan.user_id == user.id, UserPlan.status == "active")
        )
    ).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="No active plan")

    repo_link = (
        await db.execute(
            select(RepoLink).where(
                RepoLink.user_plan_id == plan.id,
                RepoLink.week_num == week_num,
            )
        )
    ).scalar_one_or_none()
    if repo_link is None:
        return []

    evals = (
        await db.execute(
            select(Evaluation)
            .where(Evaluation.repo_link_id == repo_link.id)
            .order_by(Evaluation.created_at.desc())
        )
    ).scalars().all()

    return [
        {
            "id": e.id,
            "score": e.score,
            "summary": e.summary,
            "strengths": json.loads(e.strengths_json),
            "improvements": json.loads(e.improvements_json),
            "deliverable_met": e.deliverable_met,
            "commit_sha": e.commit_sha,
            "model": e.model,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in evals
    ]
