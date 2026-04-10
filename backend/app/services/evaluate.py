"""
Evaluation service — fetches repo content, sanitizes, calls AI, stores result.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.provider import complete as ai_complete
from app.ai.sanitize import is_excluded_file, redact_secrets
from app.config import get_settings
from app.curriculum.loader import load_template
from app.models.plan import Evaluation, RepoLink, UserPlan

logger = logging.getLogger("roadmap.evaluate")

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "evaluate.txt"
MAX_FILES = 10
MAX_FILE_SIZE = 8000  # chars per file


async def _fetch_repo_content(owner: str, name: str, branch: str) -> tuple[str, str]:
    """Fetch file tree and top file contents from GitHub.

    Returns (file_tree_str, file_contents_str)
    """
    settings = get_settings()
    headers = {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Get tree
        tree_resp = await client.get(
            f"https://api.github.com/repos/{owner}/{name}/git/trees/{branch}",
            params={"recursive": "1"},
            headers=headers,
        )
        if tree_resp.status_code != 200:
            return "(unable to fetch tree)", "(unable to fetch files)"

        tree_data = tree_resp.json()
        tree_entries = tree_data.get("tree", [])

        # Build file tree string (exclude secret files from tree too)
        file_paths = [
            e["path"] for e in tree_entries
            if e["type"] == "blob" and not is_excluded_file(e["path"])
        ]
        file_tree = "\n".join(file_paths[:100])  # cap at 100 entries

        # Fetch top files (small, non-secret)
        fetchable = [
            p for p in file_paths
            if not is_excluded_file(p)
            and not p.endswith((".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".ttf", ".mp4", ".zip", ".tar", ".gz", ".bin", ".pkl", ".h5", ".pt"))
        ]

        file_contents_parts = []
        fetched = 0
        for path in fetchable:
            if fetched >= MAX_FILES:
                break
            raw_resp = await client.get(
                f"https://raw.githubusercontent.com/{owner}/{name}/{branch}/{path}",
                headers=headers,
            )
            if raw_resp.status_code != 200:
                continue
            content = raw_resp.text[:MAX_FILE_SIZE]
            content = redact_secrets(content)
            file_contents_parts.append(f"--- {path} ---\n{content}")
            fetched += 1

    return file_tree, "\n\n".join(file_contents_parts)


async def run_evaluation(
    repo_link: RepoLink,
    plan: UserPlan,
    db: AsyncSession,
) -> Evaluation:
    """Run AI evaluation on a linked repo.

    Fetches content, builds prompt, calls AI provider, stores result.
    """
    tpl = load_template(plan.template_key)
    week = tpl.week_by_number(repo_link.week_num)
    if week is None:
        raise ValueError(f"Week {repo_link.week_num} not found in template")

    # Fetch repo content
    branch = repo_link.default_branch or "main"
    file_tree, file_contents = await _fetch_repo_content(
        repo_link.repo_owner, repo_link.repo_name, branch,
    )

    # Build prompt
    prompt_template = PROMPT_PATH.read_text(encoding="utf-8")
    prompt = prompt_template.format(
        week_num=week.n,
        week_title=week.t,
        deliverables=", ".join(week.deliv),
        checklist=", ".join(week.checks),
        repo_owner=repo_link.repo_owner,
        repo_name=repo_link.repo_name,
        branch=branch,
        file_tree=file_tree,
        file_contents=file_contents,
    )

    # Call AI
    result, model = await ai_complete(prompt, json_response=True)

    # Parse and store
    import json
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    evaluation = Evaluation(
        repo_link_id=repo_link.id,
        score=int(result.get("score", 0)),
        summary=result.get("summary", ""),
        strengths_json=json.dumps(result.get("strengths", [])),
        improvements_json=json.dumps(result.get("improvements", [])),
        deliverable_met=bool(result.get("deliverable_met", False)),
        commit_sha=repo_link.last_commit_sha or "unknown",
        model=model,
        created_at=now,
    )
    db.add(evaluation)
    await db.flush()

    return evaluation
