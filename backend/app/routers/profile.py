"""
Profile router — view, edit, delete, export user data.

All endpoints under /api/profile (prefix set in main.py).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db import get_db
from app.models.plan import Evaluation, Progress, RepoLink, UserPlan
from app.models.user import User

router = APIRouter()


# ---- Schemas ----

class ProfilePatch(BaseModel):
    name: Optional[str] = None
    github_username: Optional[str] = None
    linkedin_url: Optional[str] = None
    learning_goal: Optional[str] = Field(None, max_length=200)
    experience_level: Optional[str] = None


class DeleteConfirm(BaseModel):
    confirm: str


# ---- Helpers ----

async def _profile_dict(user: User, db: AsyncSession) -> dict:
    """Build the full profile response with computed fields."""
    # Active plan
    active_plan = (
        await db.execute(
            select(UserPlan).where(
                UserPlan.user_id == user.id,
                UserPlan.status == "active",
            )
        )
    ).scalar_one_or_none()

    # Completed weeks: weeks where all checks are done
    completed_weeks = 0
    total_weeks = 0
    if active_plan:
        from app.curriculum.loader import load_template
        try:
            tpl = load_template(active_plan.template_key)
            total_weeks = tpl.total_weeks
            # Get progress for this plan
            progress_rows = (
                await db.execute(
                    select(Progress).where(
                        Progress.user_plan_id == active_plan.id,
                        Progress.done == True,
                    )
                )
            ).scalars().all()
            done_by_week: dict[int, int] = {}
            for p in progress_rows:
                done_by_week[p.week_num] = done_by_week.get(p.week_num, 0) + 1
            for m in tpl.months:
                for w in m.weeks:
                    if done_by_week.get(w.n, 0) >= len(w.checks):
                        completed_weeks += 1
        except FileNotFoundError:
            pass

    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "avatar_url": user.avatar_url,
        "github_username": user.github_username,
        "linkedin_url": user.linkedin_url,
        "learning_goal": user.learning_goal,
        "experience_level": user.experience_level,
        "is_admin": user.is_admin,
        "total_weeks": total_weeks,
        "completed_weeks": completed_weeks,
        "active_plan": active_plan.template_key if active_plan else None,
        "account_created": user.created_at.isoformat() if user.created_at else None,
    }


# ---- Endpoints ----

@router.get("")
async def get_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the full profile with computed fields."""
    return await _profile_dict(user, db)


@router.patch("")
async def patch_profile(
    body: ProfilePatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partial update of profile fields."""
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    # Validate experience_level
    if "experience_level" in updates and updates["experience_level"] is not None:
        if updates["experience_level"] not in ("beginner", "intermediate", "advanced"):
            raise HTTPException(status_code=400, detail="experience_level must be beginner, intermediate, or advanced")

    for field, value in updates.items():
        setattr(user, field, value)

    await db.flush()
    return await _profile_dict(user, db)


@router.delete("", status_code=204)
async def delete_profile(
    body: DeleteConfirm,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete the user and all associated data. Requires confirm='DELETE'."""
    if body.confirm != "DELETE":
        raise HTTPException(status_code=400, detail="Must confirm with {\"confirm\":\"DELETE\"}")

    await db.delete(user)
    await db.flush()

    response = Response(status_code=204)
    response.delete_cookie("auth_token", path="/")
    return response


@router.get("/export")
async def export_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export all user data as a JSON download."""
    profile = await _profile_dict(user, db)

    # Plans
    plans = (
        await db.execute(select(UserPlan).where(UserPlan.user_id == user.id))
    ).scalars().all()

    plans_data = []
    for plan in plans:
        progress = (
            await db.execute(select(Progress).where(Progress.user_plan_id == plan.id))
        ).scalars().all()
        repo_links = (
            await db.execute(select(RepoLink).where(RepoLink.user_plan_id == plan.id))
        ).scalars().all()

        evals_data = []
        for rl in repo_links:
            evals = (
                await db.execute(select(Evaluation).where(Evaluation.repo_link_id == rl.id))
            ).scalars().all()
            evals_data.extend([
                {
                    "repo": f"{rl.repo_owner}/{rl.repo_name}",
                    "week_num": rl.week_num,
                    "score": e.score,
                    "summary": e.summary,
                    "model": e.model,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in evals
            ])

        plans_data.append({
            "id": plan.id,
            "template_key": plan.template_key,
            "plan_version": plan.plan_version,
            "status": plan.status,
            "enrolled_at": plan.enrolled_at.isoformat() if plan.enrolled_at else None,
            "progress": [
                {"week_num": p.week_num, "check_idx": p.check_idx, "done": p.done,
                 "completed_at": p.completed_at.isoformat() if p.completed_at else None}
                for p in progress
            ],
            "repo_links": [
                {"week_num": rl.week_num, "repo": f"{rl.repo_owner}/{rl.repo_name}",
                 "linked_at": rl.linked_at.isoformat() if rl.linked_at else None}
                for rl in repo_links
            ],
            "evaluations": evals_data,
        })

    import json
    content = json.dumps({"profile": profile, "plans": plans_data}, indent=2)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=my-roadmap-data.json"},
    )
