"""End-to-end smoke test (Task 12.1).

Simulates the full user flow: sign in → enroll → tick → link repo → view evals → chat → share.
All in one test, all against a real app instance with in-memory DB.
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


@pytest.mark.asyncio
async def test_full_user_journey():
    """Complete user journey: auth → enroll → tick → link → eval → chat → share."""
    await _setup()
    app = _app()

    # 1. Create user and get session token (simulates OTP sign-in)
    async with db_module.async_session_factory() as db:
        user = User(email="smoketest@example.com", name="Smoke Tester", provider="otp", is_admin=False)
        db.add(user)
        await db.flush()
        token = await issue_token(user, db)
        await db.commit()
        user_id = user.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        cookies = {"auth_token": token}

        # 2. GET /api/auth/me — verify signed in
        resp = await c.get("/api/auth/me", cookies=cookies)
        assert resp.status_code == 200
        assert resp.json()["email"] == "smoketest@example.com"

        # 3. GET /api/plan/default — anonymous browsing works
        resp = await c.get("/api/plan/default")
        assert resp.status_code == 200
        assert resp.json()["key"] == "generalist_6mo_intermediate"

        # 4. POST /api/plans — enroll
        resp = await c.post("/api/plans", json={
            "goal": "generalist", "duration": "6mo", "level": "intermediate"
        }, cookies=cookies)
        assert resp.status_code == 200
        plan = resp.json()
        assert plan["status"] == "active"
        assert len(plan["months"]) == 6

        # 5. GET /api/plans/active — returns plan with all checks false
        resp = await c.get("/api/plans/active", cookies=cookies)
        assert resp.status_code == 200
        w1_checks = resp.json()["months"][0]["weeks"][0]["checks"]
        assert all(ch["done"] is False for ch in w1_checks)

        # 6. PATCH /api/progress — tick a checkbox
        resp = await c.patch("/api/progress", json={
            "week_num": 1, "check_idx": 0, "done": True
        }, cookies=cookies)
        assert resp.status_code == 204

        # 7. Verify tick persisted
        resp = await c.get("/api/plans/active", cookies=cookies)
        assert resp.json()["months"][0]["weeks"][0]["checks"][0]["done"] is True

        # 8. POST /api/progress/migrate — migrate localStorage blob.
        # Guardrail: if the plan already has progress (step 6 ticked w1_0),
        # the migrate endpoint no-ops and returns 204 to prevent stale
        # localStorage from leaking across plan switches.
        resp = await c.post("/api/progress/migrate", json={
            "progress": {"w1_1": True, "w2_0": True}
        }, cookies=cookies)
        assert resp.status_code == 204

        # Server-side tick (w1_0) is untouched; the migrate blob is discarded.
        resp = await c.get("/api/plans/active", cookies=cookies)
        assert resp.json()["months"][0]["weeks"][0]["checks"][0]["done"] is True
        assert resp.json()["months"][0]["weeks"][0]["checks"][1]["done"] is False

        # 9. POST /api/repos/link — link a repo (mocked GitHub)
        mock_repo = {
            "owner": "octocat", "name": "Hello-World",
            "default_branch": "master", "last_commit_sha": "abc123",
            "last_commit_date": "2026-01-01T00:00:00Z",
        }
        with patch("app.routers.repos.fetch_repo", new_callable=AsyncMock, return_value=mock_repo):
            resp = await c.post("/api/repos/link", json={
                "week_num": 1, "repo": "octocat/Hello-World"
            }, cookies=cookies)
            assert resp.status_code == 200
            assert resp.json()["owner"] == "octocat"

        # 10. GET /api/evaluations — empty initially
        resp = await c.get("/api/evaluations?week_num=1", cookies=cookies)
        assert resp.status_code == 200
        assert resp.json() == []

        # 11. POST /api/chat — chat works (mocked stream)
        # Clear rate limiter from previous tests
        from app.routers.chat import _rate_tracker
        _rate_tracker.clear()
        async def mock_stream(messages):
            yield "Hello from AI!"

        with patch("app.ai.stream.stream_complete", side_effect=lambda m: mock_stream(m)):
            resp = await c.post("/api/chat", json={
                "week_num": 1, "message": "What should I focus on?"
            }, cookies=cookies)
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]
            assert "Hello from AI!" in resp.text

        # 12. GET /share/{user_id}/month-1 — share page loads (public)
        resp = await c.get(f"/share/{user_id}/month-1")
        assert resp.status_code == 200
        assert "og:title" in resp.text
        assert "Smoke" in resp.text  # first name

        # 13. GET /share/{user_id}/month-1/og.svg — OG image loads
        resp = await c.get(f"/share/{user_id}/month-1/og.svg")
        assert resp.status_code == 200
        assert "<svg" in resp.text

        # 14. GET /api/profile — profile works
        resp = await c.get("/api/profile", cookies=cookies)
        assert resp.status_code == 200
        assert resp.json()["active_plan"] == "generalist_6mo_intermediate"

        # 15. PATCH /api/profile — update works
        resp = await c.patch("/api/profile", json={"github_username": "smoky"}, cookies=cookies)
        assert resp.status_code == 200
        assert resp.json()["github_username"] == "smoky"

        # 16. GET /api/profile/export — export works
        resp = await c.get("/api/profile/export", cookies=cookies)
        assert resp.status_code == 200
        export = resp.json()
        assert export["profile"]["email"] == "smoketest@example.com"
        assert len(export["plans"]) == 1

        # 17. POST /api/auth/logout — logout works
        resp = await c.post("/api/auth/logout", cookies=cookies)
        assert resp.status_code == 204

        # 18. Verify logged out
        resp = await c.get("/api/auth/me", cookies=cookies)
        assert resp.status_code == 401

    await close_db()


@pytest.mark.asyncio
async def test_admin_flow():
    """Admin can access admin panel; non-admin cannot."""
    await _setup()
    app = _app()

    async with db_module.async_session_factory() as db:
        admin = User(email="admin@smoke.com", name="Admin", provider="otp", is_admin=True)
        regular = User(email="user@smoke.com", name="User", provider="otp", is_admin=False)
        db.add_all([admin, regular])
        await db.flush()
        admin_token = await issue_token(admin, db)
        user_token = await issue_token(regular, db)
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        # Admin can access
        resp = await c.get("/admin/api/dashboard", cookies={"auth_token": admin_token})
        assert resp.status_code == 200
        assert resp.json()["total_users"] >= 2

        # Non-admin gets 403
        resp = await c.get("/admin/api/dashboard", cookies={"auth_token": user_token})
        assert resp.status_code == 403

        # Admin HTML pages load
        resp = await c.get("/admin/", cookies={"auth_token": admin_token})
        assert resp.status_code == 200
        assert "Dashboard" in resp.text

    await close_db()
