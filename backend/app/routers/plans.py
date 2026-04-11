"""
Plan and progress router — enrollment, active plan, progress ticks, migration.

All endpoints under /api (prefix set in main.py).
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.curriculum.loader import load_template, list_templates
from app.db import get_db
from app.models.plan import Progress, UserPlan
from app.models.user import User

router = APIRouter()


# ---- Schemas ----

class EnrollBody(BaseModel):
    goal: str = "generalist"
    duration: str = "6mo"
    level: str = "intermediate"
    template_key: str | None = None  # Direct key — overrides goal/duration/level if provided


class ProgressBody(BaseModel):
    week_num: int
    check_idx: int
    done: bool


class MigrateBody(BaseModel):
    progress: dict[str, bool]


# ---- Helpers ----

def _template_key(goal: str, duration: str, level: str) -> str:
    return f"{goal}_{duration}_{level}"


def _plan_to_dict(plan: UserPlan, template, progress_rows: list[Progress]) -> dict:
    """Merge a plan template with progress rows into a response dict."""
    # Build progress lookup
    progress_map: dict[tuple[int, int], Progress] = {}
    for p in progress_rows:
        progress_map[(p.week_num, p.check_idx)] = p

    months = []
    for m in template.months:
        weeks = []
        for w in m.weeks:
            checks = []
            for idx, label in enumerate(w.checks):
                p = progress_map.get((w.n, idx))
                checks.append({
                    "idx": idx,
                    "label": label,
                    "done": p.done if p else False,
                    "completed_at": p.completed_at.isoformat() if p and p.completed_at else None,
                })
            weeks.append({
                "n": w.n, "t": w.t, "hours": w.hours,
                "focus": w.focus, "deliv": w.deliv,
                "resources": [r.model_dump() for r in w.resources],
                "checks": checks,
            })
        months.append({
            "month": m.month, "label": m.label, "title": m.title,
            "tagline": m.tagline, "checkpoint": m.checkpoint,
            "weeks": weeks,
        })

    return {
        "id": plan.id,
        "template_key": plan.template_key,
        "plan_version": plan.plan_version,
        "status": plan.status,
        "enrolled_at": plan.enrolled_at.isoformat() if plan.enrolled_at else None,
        "months": months,
    }


# ---- Endpoints ----

@router.get("/plan/default")
async def plan_default():
    """Return the default plan template for anonymous browsing."""
    tpl = load_template("generalist_6mo_intermediate")
    return tpl.model_dump()


@router.post("/plans")
async def enroll(
    body: EnrollBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new plan, archiving any previous active plan. Max 10 switches/day."""
    template_key = body.template_key or _template_key(body.goal, body.duration, body.level)

    # Validate template exists
    try:
        tpl = load_template(template_key)
    except FileNotFoundError:
        raise HTTPException(status_code=400, detail=f"Unknown plan template: {template_key}")

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Rate limit: max 10 plan switches per day
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    switches_today = await db.scalar(
        select(func.count()).select_from(UserPlan).where(
            UserPlan.user_id == user.id,
            UserPlan.enrolled_at >= day_start,
        )
    ) or 0
    if switches_today >= 10:
        raise HTTPException(status_code=429, detail="Plan switch limit reached (10/day). Try again tomorrow.")

    # Archive current active plan if any
    active = (
        await db.execute(
            select(UserPlan).where(
                UserPlan.user_id == user.id,
                UserPlan.status == "active",
            )
        )
    ).scalar_one_or_none()

    if active:
        active.status = "archived"
        active.archived_at = now

    # Create new plan
    plan = UserPlan(
        user_id=user.id,
        template_key=template_key,
        plan_version=tpl.version,
        status="active",
        enrolled_at=now,
    )
    db.add(plan)
    await db.flush()

    return _plan_to_dict(plan, tpl, [])


@router.get("/plans/active")
async def get_active_plan(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the user's active plan with progress merged in."""
    plan = (
        await db.execute(
            select(UserPlan).where(
                UserPlan.user_id == user.id,
                UserPlan.status == "active",
            )
        )
    ).scalar_one_or_none()

    if plan is None:
        raise HTTPException(status_code=404, detail="No active plan")

    tpl = load_template(plan.template_key)

    progress_rows = (
        await db.execute(
            select(Progress).where(Progress.user_plan_id == plan.id)
        )
    ).scalars().all()

    return _plan_to_dict(plan, tpl, list(progress_rows))


@router.get("/plan-versions")
async def plan_versions(db: AsyncSession = Depends(get_db)):
    """Return the full changelog from the plan_versions table."""
    from app.models.curriculum import PlanVersion
    rows = (
        await db.execute(
            select(PlanVersion).order_by(PlanVersion.published_at.desc())
        )
    ).scalars().all()

    return [
        {
            "version": r.version,
            "published_at": r.published_at.isoformat(),
            "label": r.label,
            "changes": r.changes_json,
            "is_current": r.is_current,
        }
        for r in rows
    ]


@router.patch("/progress", status_code=204)
async def update_progress(
    body: ProgressBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upsert a progress row for the user's active plan."""
    plan = (
        await db.execute(
            select(UserPlan).where(
                UserPlan.user_id == user.id,
                UserPlan.status == "active",
            )
        )
    ).scalar_one_or_none()

    if plan is None:
        raise HTTPException(status_code=404, detail="No active plan")

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Find existing progress row
    existing = (
        await db.execute(
            select(Progress).where(
                Progress.user_plan_id == plan.id,
                Progress.week_num == body.week_num,
                Progress.check_idx == body.check_idx,
            )
        )
    ).scalar_one_or_none()

    if existing:
        existing.done = body.done
        existing.completed_at = now if body.done else None
        existing.updated_at = now
    else:
        db.add(Progress(
            user_plan_id=plan.id,
            week_num=body.week_num,
            check_idx=body.check_idx,
            done=body.done,
            completed_at=now if body.done else None,
            updated_at=now,
        ))

    return Response(status_code=204)


@router.post("/progress/migrate")
async def migrate_progress(
    body: MigrateBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Merge localStorage progress blob into the user's active plan.

    Keys are like "w1_0", "w1_1", etc. Values are booleans.
    Merge rule: server wins on conflicts (if server says done, keep it).
    """
    plan = (
        await db.execute(
            select(UserPlan).where(
                UserPlan.user_id == user.id,
                UserPlan.status == "active",
            )
        )
    ).scalar_one_or_none()

    if plan is None:
        raise HTTPException(status_code=404, detail="No active plan")

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Load existing progress
    existing_rows = (
        await db.execute(
            select(Progress).where(Progress.user_plan_id == plan.id)
        )
    ).scalars().all()

    existing_map: dict[tuple[int, int], Progress] = {}
    for p in existing_rows:
        existing_map[(p.week_num, p.check_idx)] = p

    # Parse and merge
    for key, done in body.progress.items():
        if not key.startswith("w") or "_" not in key:
            continue
        parts = key[1:].split("_", 1)
        if len(parts) != 2:
            continue
        try:
            week_num = int(parts[0])
            check_idx = int(parts[1])
        except ValueError:
            continue

        existing = existing_map.get((week_num, check_idx))
        if existing:
            # Server wins: only upgrade from not-done to done
            if done and not existing.done:
                existing.done = True
                existing.completed_at = now
                existing.updated_at = now
        else:
            db.add(Progress(
                user_plan_id=plan.id,
                week_num=week_num,
                check_idx=check_idx,
                done=bool(done),
                completed_at=now if done else None,
                updated_at=now,
            ))

    await db.flush()

    # Return merged state
    all_progress = (
        await db.execute(
            select(Progress).where(Progress.user_plan_id == plan.id)
        )
    ).scalars().all()

    tpl = load_template(plan.template_key)
    return _plan_to_dict(plan, tpl, list(all_progress))
