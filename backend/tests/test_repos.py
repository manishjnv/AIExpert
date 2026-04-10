"""Tests for GitHub client and repo linking (Tasks 6.1–6.2).

AC 6.1: Mocked unit test + real public repo integration test
AC 6.2: Linking public repo succeeds; non-existent repo returns 404
"""

import pytest
from unittest.mock import AsyncMock, patch
from httpx import ASGITransport, AsyncClient

from app.db import Base, close_db, init_db
import app.db as db_module
from app.auth.jwt import issue_token
from app.models.user import User
from app.services.github_client import fetch_repo, parse_repo_input, RepoNotFound

import app.models  # noqa: F401


# ---- 6.1: GitHub client unit tests ----

def test_parse_repo_owner_name():
    assert parse_repo_input("octocat/Hello-World") == ("octocat", "Hello-World")


def test_parse_repo_url():
    assert parse_repo_input("https://github.com/octocat/Hello-World") == ("octocat", "Hello-World")


def test_parse_repo_url_trailing_slash():
    assert parse_repo_input("https://github.com/octocat/Hello-World/") == ("octocat", "Hello-World")


def test_parse_repo_invalid():
    with pytest.raises(ValueError):
        parse_repo_input("not-a-repo")


@pytest.mark.asyncio
async def test_fetch_repo_mocked():
    """Unit test with mocked httpx."""
    import httpx

    mock_repo_response = httpx.Response(200, json={
        "default_branch": "main",
        "owner": {"login": "octocat"},
        "name": "Hello-World",
    })
    mock_commit_response = httpx.Response(200, json={
        "sha": "abc123",
        "commit": {"committer": {"date": "2026-01-01T00:00:00Z"}},
    })

    with patch("app.services.github_client.httpx.AsyncClient") as MockClient:
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_instance.get = AsyncMock(side_effect=[mock_repo_response, mock_commit_response])
        MockClient.return_value = mock_instance

        result = await fetch_repo("octocat", "Hello-World")
        assert result["owner"] == "octocat"
        assert result["name"] == "Hello-World"
        assert result["default_branch"] == "main"
        assert result["last_commit_sha"] == "abc123"


@pytest.mark.asyncio
async def test_fetch_repo_not_found_mocked():
    """Mocked 404 raises RepoNotFound."""
    import httpx

    with patch("app.services.github_client.httpx.AsyncClient") as MockClient:
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_instance.get = AsyncMock(return_value=httpx.Response(404))
        MockClient.return_value = mock_instance

        with pytest.raises(RepoNotFound):
            await fetch_repo("nonexistent", "repo-xyz")


# ---- 6.1: Integration test (hits real GitHub) ----

@pytest.mark.asyncio
async def test_fetch_repo_real():
    """Integration test against a known public repo."""
    result = await fetch_repo("octocat", "Hello-World")
    assert result["owner"] == "octocat"
    assert result["name"] == "Hello-World"
    assert result["default_branch"] == "master"
    assert result["last_commit_sha"] is not None


# ---- 6.2: Endpoint tests ----

async def _setup():
    await init_db(url="sqlite+aiosqlite:///:memory:")
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _app():
    from app.main import app
    return app


async def _user_token(email="repo@test.com"):
    async with db_module.async_session_factory() as db:
        user = User(email=email, provider="otp", is_admin=False)
        db.add(user)
        await db.flush()
        token = await issue_token(user, db)
        await db.commit()
        return user.id, token


@pytest.mark.asyncio
async def test_link_repo_success():
    """Linking a real public repo succeeds."""
    await _setup()
    _, token = await _user_token()
    app = _app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        # Enroll first
        await c.post("/api/plans", json={"goal": "generalist", "duration": "6mo", "level": "intermediate"}, cookies={"session": token})

        resp = await c.post("/api/repos/link", json={"week_num": 1, "repo": "octocat/Hello-World"}, cookies={"session": token})
        assert resp.status_code == 200
        data = resp.json()
        assert data["owner"] == "octocat"
        assert data["name"] == "Hello-World"

    await close_db()


@pytest.mark.asyncio
async def test_link_nonexistent_repo():
    """Linking a non-existent repo returns 404."""
    await _setup()
    _, token = await _user_token("notfound@test.com")
    app = _app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.post("/api/plans", json={"goal": "generalist", "duration": "6mo", "level": "intermediate"}, cookies={"session": token})

        resp = await c.post("/api/repos/link", json={"week_num": 1, "repo": "nonexistent-user-xyz/no-such-repo-abc"}, cookies={"session": token})
        assert resp.status_code == 404

    await close_db()


@pytest.mark.asyncio
async def test_unlink_repo():
    """Unlink a previously linked repo."""
    await _setup()
    _, token = await _user_token("unlink@test.com")
    app = _app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.post("/api/plans", json={"goal": "generalist", "duration": "6mo", "level": "intermediate"}, cookies={"session": token})
        await c.post("/api/repos/link", json={"week_num": 1, "repo": "octocat/Hello-World"}, cookies={"session": token})

        resp = await c.delete("/api/repos/link?week_num=1", cookies={"session": token})
        assert resp.status_code == 204

    await close_db()
