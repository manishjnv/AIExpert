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
    notify_jobs: Optional[bool] = None
    notify_roadmap: Optional[bool] = None
    notify_blog: Optional[bool] = None
    notify_new_courses: Optional[bool] = None
    public_profile: Optional[bool] = None


class DeleteConfirm(BaseModel):
    confirm: str


class SubscribeIntent(BaseModel):
    channel: str  # "jobs" | "roadmap" | "blog" | "new_courses" — validated in the handler


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

    # Course history — all non-active plans with their progress
    all_plans = (
        await db.execute(
            select(UserPlan).where(UserPlan.user_id == user.id)
            .order_by(UserPlan.enrolled_at.desc())
        )
    ).scalars().all()

    plan_history = []
    for plan in all_plans:
        done_count = await db.scalar(
            select(func.count()).select_from(Progress).where(
                Progress.user_plan_id == plan.id, Progress.done == True
            )
        ) or 0
        total_checks = 0
        plan_title = plan.template_key
        try:
            from app.curriculum.loader import load_template
            tpl = load_template(plan.template_key)
            total_checks = tpl.total_checks
            plan_title = tpl.title
        except Exception:
            total_checks = 120
        pct = round((done_count / total_checks) * 100) if total_checks else 0
        plan_history.append({
            "template_key": plan.template_key,
            "title": plan_title,
            "status": plan.status,
            "enrolled_at": plan.enrolled_at.isoformat() if plan.enrolled_at else None,
            "archived_at": plan.archived_at.isoformat() if plan.archived_at else None,
            "done": done_count,
            "total": total_checks,
            "pct": pct,
        })

    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "avatar_url": user.avatar_url,
        "github_username": user.github_username,
        "linkedin_url": user.linkedin_url,
        "learning_goal": user.learning_goal,
        "notify_jobs": user.notify_jobs,
        "notify_roadmap": user.notify_roadmap,
        "notify_blog": user.notify_blog,
        "notify_new_courses": user.notify_new_courses,
        "public_profile": user.public_profile,
        "experience_level": user.experience_level,
        "is_admin": user.is_admin,
        "total_weeks": total_weeks,
        "completed_weeks": completed_weeks,
        "active_plan": active_plan.template_key if active_plan else None,
        "plan_history": plan_history,
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
    raw = body.model_dump(exclude_unset=True)
    if not raw:
        raise HTTPException(status_code=400, detail="No fields to update")

    # Booleans are written as sent. For text fields, null is treated as
    # "leave alone" (not "clear") so a save with a blank input never wipes
    # a previously populated value. To clear, send an empty string.
    BOOL_FIELDS = {"notify_jobs", "notify_roadmap", "notify_blog", "notify_new_courses", "public_profile"}
    updates = {}
    for field, value in raw.items():
        if field in BOOL_FIELDS:
            updates[field] = value
        elif value is None:
            continue  # skip — preserves existing value
        else:
            updates[field] = value

    if not updates:
        # Nothing to apply; still return current profile without error.
        return await _profile_dict(user, db)

    if "experience_level" in updates:
        if updates["experience_level"] not in ("beginner", "intermediate", "advanced"):
            raise HTTPException(status_code=400, detail="experience_level must be beginner, intermediate, or advanced")

    # Write audit log + apply updates
    from app.models.user_audit import UserAuditLog
    for field, value in updates.items():
        old = getattr(user, field, None)
        if old != value:
            db.add(UserAuditLog(
                user_id=user.id, field=field,
                old_value=str(old) if old is not None else None,
                new_value=str(value) if value is not None else None,
                source="profile_patch",
            ))
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


# ---- Weekly digest: one-click unsubscribe (no login) ----
# Link comes from an email; user may not be signed in on this device.
# The token is a short signed JWT (k=unsub) issued by services.weekly_digest.
# Optional `c` claim names a single channel ("jobs"|"roadmap"|"blog") to flip
# off; absence of `c` flips all three off (covers in-flight emails sent before
# the per-channel toggle landed and the "Unsubscribe from all" link).
_VALID_CHANNELS = {"jobs", "roadmap", "blog", "new_courses"}


@router.get("/digest/unsubscribe", response_class=Response)
async def digest_unsubscribe(t: str, db=Depends(get_db)):
    from jose import jwt, JWTError
    from app.config import get_settings
    from app.models.user import User
    from sqlalchemy import select

    try:
        payload = jwt.decode(t, get_settings().jwt_secret, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(status_code=400, detail="Invalid or expired link")
    if payload.get("k") != "unsub" or not payload.get("sub"):
        raise HTTPException(status_code=400, detail="Invalid token")
    try:
        uid = int(payload["sub"])
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid token")

    user = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    channel = payload.get("c")
    if channel is None:
        user.notify_jobs = False
        user.notify_roadmap = False
        user.notify_blog = False
        user.notify_new_courses = False
        scope_label = "all email digests"
    elif channel in _VALID_CHANNELS:
        setattr(user, f"notify_{channel}", False)
        scope_label = {
            "jobs": "weekly job alerts",
            "roadmap": "weekly progress reminders",
            "blog": "new blog post alerts",
            "new_courses": "new course alerts",
        }[channel]
    else:
        raise HTTPException(status_code=400, detail="Invalid channel claim")

    await db.commit()

    html = ("<html><body style='font-family:sans-serif;max-width:500px;margin:60px auto;"
            "text-align:center;padding:24px'>"
            "<h2 style='color:#1a1a1a'>Unsubscribed</h2>"
            f"<p style='color:#555'>{user.email} won't receive {scope_label}. "
            "You can re-enable channels anytime on your "
            "<a href='/account' style='color:#0a7'>account page</a>.</p></body></html>")
    return Response(content=html, media_type="text/html")


# ---- Anonymous subscribe-intent funnel ----
# Kept for backward-compat with cached/external links. The ribbon's anonymous
# CTA now points directly at "/", so this endpoint is no longer the primary
# path — it just redirects to home if hit.
from fastapi import Request
from fastapi.responses import RedirectResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

_limiter = Limiter(key_func=get_remote_address)


@router.get("/subscribe-intent", response_class=Response)
@_limiter.limit("20/hour")
async def subscribe_intent(channel: str, request: Request):
    if channel not in _VALID_CHANNELS:
        raise HTTPException(status_code=400, detail="Invalid channel")
    return RedirectResponse(url="/", status_code=302)
