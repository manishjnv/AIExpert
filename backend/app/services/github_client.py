"""
GitHub REST client — fetch repo metadata via httpx.

Uses the public API (no auth required for public repos).
If GITHUB_TOKEN is set, uses it for higher rate limits.
"""

from __future__ import annotations

import logging
import re
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


_GH_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


def parse_repo_input(repo_input: str) -> tuple[str, str]:
    """Parse 'owner/name' or 'https://github.com/owner/name' into (owner, name).

    Accepts ONLY github.com URLs. Any other scheme or hostname (including
    GitHub Enterprise, IP literals, or attacker-controlled look-alike hosts
    such as `github.com.evil.tld`) is rejected with ValueError. This matters
    because `fetch_repo` embeds the parsed values into `api.github.com` URLs
    — without a host check we'd have a narrow but real SSRF primitive if a
    future caller ever forwarded the raw URL instead of the parsed tuple.

    Also enforces the GitHub username/reponame character class so the values
    can never contain path separators, `@`, `:`, `?`, or `#`.

    Raises ValueError if the input is not valid.
    """
    from urllib.parse import urlparse

    repo_input = (repo_input or "").strip().rstrip("/")
    if not repo_input:
        raise ValueError("Empty repo input")

    # URL form — must be an exact github.com host over https.
    if "://" in repo_input:
        parsed = urlparse(repo_input)
        if parsed.scheme != "https":
            raise ValueError("Only https:// GitHub URLs are accepted")
        host = (parsed.hostname or "").lower()
        if host != "github.com":
            raise ValueError(f"Only github.com is accepted (got: {host or 'none'})")
        path_parts = [p for p in parsed.path.split("/") if p]
        if len(path_parts) < 2:
            raise ValueError(f"Invalid GitHub URL: {repo_input}")
        owner, name = path_parts[0], path_parts[1]
    # owner/name form
    elif "/" in repo_input:
        parts = repo_input.split("/", 1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ValueError(f"Invalid repo format: {repo_input}")
        owner, name = parts[0], parts[1]
    else:
        raise ValueError(
            f"Invalid repo format: {repo_input}. Use 'owner/name' or a GitHub URL."
        )

    # Trim a possible `.git` suffix that some users copy from clone URLs.
    if name.endswith(".git"):
        name = name[:-4]

    if not _GH_NAME_RE.match(owner) or not _GH_NAME_RE.match(name):
        raise ValueError(f"Invalid repo format: {repo_input}")
    return owner, name
