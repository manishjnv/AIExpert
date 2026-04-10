"""
GitHub REST client — fetch repo metadata via httpx.

Uses the public API (no auth required for public repos).
If GITHUB_TOKEN is set, uses it for higher rate limits.
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from app.config import get_settings

logger = logging.getLogger("roadmap.github")

GITHUB_API = "https://api.github.com"


class RepoNotFound(Exception):
    pass


class GitHubRateLimited(Exception):
    pass


class GitHubError(Exception):
    pass


async def fetch_repo(owner: str, name: str) -> dict:
    """Fetch repo metadata from GitHub.

    Returns: {owner, name, default_branch, last_commit_sha, last_commit_date}

    Raises:
        RepoNotFound: 404
        GitHubRateLimited: 403/429
        GitHubError: other failures
    """
    settings = get_settings()
    headers = {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{GITHUB_API}/repos/{owner}/{name}", headers=headers)

        if resp.status_code == 404:
            raise RepoNotFound(f"Repository {owner}/{name} not found")
        if resp.status_code in (403, 429):
            raise GitHubRateLimited("GitHub API rate limit exceeded")
        if resp.status_code != 200:
            raise GitHubError(f"GitHub API error: {resp.status_code}")

        data = resp.json()
        default_branch = data.get("default_branch", "main")

        # Fetch latest commit on default branch
        commit_resp = await client.get(
            f"{GITHUB_API}/repos/{owner}/{name}/commits/{default_branch}",
            headers=headers,
        )

        last_commit_sha = None
        last_commit_date = None
        if commit_resp.status_code == 200:
            commit_data = commit_resp.json()
            last_commit_sha = commit_data.get("sha")
            commit_info = commit_data.get("commit", {}).get("committer", {})
            last_commit_date = commit_info.get("date")

    return {
        "owner": owner,
        "name": name,
        "default_branch": default_branch,
        "last_commit_sha": last_commit_sha,
        "last_commit_date": last_commit_date,
    }


def parse_repo_input(repo_input: str) -> tuple[str, str]:
    """Parse 'owner/name' or 'https://github.com/owner/name' into (owner, name).

    Raises ValueError if the input is not valid.
    """
    repo_input = repo_input.strip().rstrip("/")

    # URL form
    if repo_input.startswith("https://github.com/"):
        parts = repo_input.replace("https://github.com/", "").split("/")
        if len(parts) >= 2:
            return parts[0], parts[1]
        raise ValueError(f"Invalid GitHub URL: {repo_input}")

    # owner/name form
    if "/" in repo_input:
        parts = repo_input.split("/", 1)
        if len(parts) == 2 and parts[0] and parts[1]:
            return parts[0], parts[1]

    raise ValueError(f"Invalid repo format: {repo_input}. Use 'owner/name' or a GitHub URL.")
