"""Tests for chat endpoint (Task 8.1).

AC: SSE endpoint streams tokens; rate limit enforced.
"""

import pytest
from unittest.mock import AsyncMock, patch
from httpx import ASGITransport, AsyncClient

from app.db import Base, close_db, init_db
import app.db as db_module
from app.auth.jwt import issue_token
from app.models.user import User

import app.models  # noqa: F401


async def _setup():
    await init_db(url="sqlite+aiosqlite:///:memory:")
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _app():
    from app.main import app
    return app


async def _user_token(email="chat@test.com"):
    async with db_module.async_session_factory() as db:
        user = User(email=email, provider="otp", is_admin=False)
        db.add(user)
        await db.flush()
        token = await issue_token(user, db)
        await db.commit()
        return user.id, token


@pytest.mark.asyncio
async def test_chat_works_without_auth():
    """Chat is available to anonymous users."""
    await _setup()
    app = _app()

    async def mock_stream(messages):
        yield "ok"

    with patch("app.ai.stream.stream_complete", side_effect=lambda m: mock_stream(m)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.post("/api/chat", json={"week_num": 1, "message": "hello"})
            assert resp.status_code == 200
    await close_db()


@pytest.mark.asyncio
async def test_chat_streams_sse():
    """Chat endpoint returns SSE with mocked stream."""
    await _setup()
    _, token = await _user_token()
    app = _app()

    async def mock_stream(messages):
        yield "Hello "
        yield "world!"

    with patch("app.ai.stream.stream_complete", side_effect=lambda m: mock_stream(m)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.post(
                "/api/chat",
                json={"week_num": 1, "message": "hello"},
                cookies={"auth_token": token},
            )
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")
            body = resp.text
            assert "data: " in body

    await close_db()


@pytest.mark.asyncio
async def test_chat_rate_limit():
    """Rate limit blocks after 20 messages per hour."""
    await _setup()
    user_id, token = await _user_token("ratelimit@test.com")
    app = _app()

    # Clear any existing rate tracker entries (handler keys by str)
    from app.routers.chat import _rate_tracker
    _rate_tracker.clear()

    async def mock_stream(messages):
        yield "ok"

    with patch("app.ai.stream.stream_complete", side_effect=lambda m: mock_stream(m)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            for i in range(20):
                resp = await c.post(
                    "/api/chat",
                    json={"week_num": 1, "message": f"msg {i}"},
                    cookies={"auth_token": token},
                )
                assert resp.status_code == 200, f"Request {i} failed: {resp.status_code}"

            # 21st should be rate limited
            resp = await c.post(
                "/api/chat",
                json={"week_num": 1, "message": "one too many"},
                cookies={"auth_token": token},
            )
            assert resp.status_code == 429

    await close_db()
