"""
Repo linking router — link/unlink GitHub repos to plan weeks.

All endpoints under /api/repos (prefix set in main.py).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db import get_db
from app.models.plan import RepoLink, UserPlan
from app.models.user import User
from app.services.github_client import (
    GitHubError,
    GitHubRateLimited,
    RepoNotFound,
    fetch_repo,
    parse_repo_input,
)

router = APIRouter()


class LinkBody(BaseModel):
    week_num: int
    repo_url: Optional[str] = None
    repo: Optional[str] = None


@router.post("/link")
async def link_repo(
    body: LinkBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Link a GitHub repo to a week in the user's active plan."""
    # Get active plan
    plan = (
        await db.execute(
            select(UserPlan).where(UserPlan.user_id == user.id, UserPlan.status == "active")
        )
    ).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="No active plan")

    # Parse repo input
    repo_input = body.repo_url or body.repo
    if not repo_input:
        raise HTTPException(status_code=400, detail="Provide repo_url or repo")

    try:
        owner, name = parse_repo_input(repo_input)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Validate against GitHub
    try:
        repo_info = await fetch_repo(owner, name)
    except RepoNotFound:
        raise HTTPException(status_code=404, detail=f"Repository {owner}/{name} not found on GitHub")
    except GitHubRateLimited:
        raise HTTPException(status_code=429, detail="GitHub API rate limit exceeded. Try again later.")
    except GitHubError as e:
        raise HTTPException(status_code=502, detail=str(e))

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Upsert repo link
    existing = (
        await db.execute(
            select(RepoLink).where(
                RepoLink.user_plan_id == plan.id,
                RepoLink.week_num == body.week_num,
            )
        )
    ).scalar_one_or_none()

    if existing:
        existing.repo_owner = repo_info["owner"]
        existing.repo_name = repo_info["name"]
        existing.default_branch = repo_info["default_branch"]
        existing.last_commit_sha = repo_info["last_commit_sha"]
        existing.linked_at = now
    else:
        db.add(RepoLink(
            user_plan_id=plan.id,
            week_num=body.week_num,
            repo_owner=repo_info["owner"],
            repo_name=repo_info["name"],
            default_branch=repo_info["default_branch"],
            last_commit_sha=repo_info["last_commit_sha"],
            linked_at=now,
        ))

    await db.flush()

    # Linking a new repo can cross the Distinction repos-required gate.
    from app.services.certificates import safe_check_and_issue
    await safe_check_and_issue(db, user, plan)

    return repo_info


@router.delete("/link", status_code=204)
async def unlink_repo(
    week_num: int = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove the repo link for a given week. Does not remove past evaluations."""
    plan = (
        await db.execute(
            select(UserPlan).where(UserPlan.user_id == user.id, UserPlan.status == "active")
        )
    ).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="No active plan")

    link = (
        await db.execute(
            select(RepoLink).where(
                RepoLink.user_plan_id == plan.id,
                RepoLink.week_num == week_num,
            )
        )
    ).scalar_one_or_none()

    if link is None:
        raise HTTPException(status_code=404, detail="No repo linked for this week")

    await db.delete(link)
    return Response(status_code=204)
