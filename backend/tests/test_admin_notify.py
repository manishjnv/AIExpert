"""Tests for the programmatic notification endpoint /admin/api/notify.

Auth path is bearer-token only (intentionally separate from cookie-auth
admin endpoints) because the consumer is a scheduled remote agent.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import Base, close_db, init_db
import app.db as db_module
import app.models  # noqa: F401


async def _setup():
    await init_db(url="sqlite+aiosqlite:///:memory:")
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _app():
    from app.main import app
    return app


@pytest.fixture(autouse=True)
def _disable_rate_limiter():
    """slowapi keeps per-IP counters in process memory; sequential tests
    in the same module hit the limit and get 429s instead of the status
    we're testing. Disable for the suite."""
    from app.routers.admin import _tweet_limiter
    prev = _tweet_limiter.enabled
    _tweet_limiter.enabled = False
    try:
        yield
    finally:
        _tweet_limiter.enabled = prev


@pytest.mark.asyncio
async def test_notify_503_when_token_unset(monkeypatch):
    monkeypatch.delenv("NOTIFY_API_TOKEN", raising=False)
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.post("/admin/api/notify",
                         json={"subject": "x", "body": "y"})
    assert r.status_code == 503
    assert "NOTIFY_API_TOKEN" in r.json()["message"]
    await close_db()


@pytest.mark.asyncio
async def test_notify_401_no_auth_header(monkeypatch):
    monkeypatch.setenv("NOTIFY_API_TOKEN", "secret123")
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.post("/admin/api/notify",
                         json={"subject": "x", "body": "y"})
    assert r.status_code == 401
    await close_db()


@pytest.mark.asyncio
async def test_notify_401_wrong_token(monkeypatch):
    monkeypatch.setenv("NOTIFY_API_TOKEN", "secret123")
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.post("/admin/api/notify",
                         json={"subject": "x", "body": "y"},
                         headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401
    await close_db()


@pytest.mark.asyncio
async def test_notify_401_wrong_scheme(monkeypatch):
    """Reject non-Bearer schemes (Basic, Token, raw value) to avoid
    accidentally matching a value-only header."""
    monkeypatch.setenv("NOTIFY_API_TOKEN", "secret123")
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        for header_value in ("secret123",  # raw, no scheme
                             "Token secret123",
                             "Basic secret123"):
            r = await c.post("/admin/api/notify",
                             json={"subject": "x", "body": "y"},
                             headers={"Authorization": header_value})
            assert r.status_code == 401, f"accepted: {header_value!r}"
    await close_db()


@pytest.mark.asyncio
async def test_notify_400_missing_fields(monkeypatch):
    monkeypatch.setenv("NOTIFY_API_TOKEN", "secret123")
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        h = {"Authorization": "Bearer secret123"}
        r = await c.post("/admin/api/notify", headers=h, json={})
        assert r.status_code == 400
        r = await c.post("/admin/api/notify", headers=h, json={"subject": "x"})
        assert r.status_code == 400  # body missing
        r = await c.post("/admin/api/notify", headers=h, json={"body": "x"})
        assert r.status_code == 400  # subject missing
    await close_db()


@pytest.mark.asyncio
async def test_notify_400_field_too_long(monkeypatch):
    monkeypatch.setenv("NOTIFY_API_TOKEN", "secret123")
    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        h = {"Authorization": "Bearer secret123"}
        r = await c.post("/admin/api/notify", headers=h,
                         json={"subject": "x" * 301, "body": "ok"})
        assert r.status_code == 400
        r = await c.post("/admin/api/notify", headers=h,
                         json={"subject": "ok", "body": "x" * 20001})
        assert r.status_code == 400
    await close_db()


@pytest.mark.asyncio
async def test_notify_success_sends_email(monkeypatch):
    """Happy path — endpoint calls send_admin_notification with the right
    args and returns ok. Mock the SMTP send so the test doesn't actually
    talk to Brevo."""
    monkeypatch.setenv("NOTIFY_API_TOKEN", "secret123")
    captured = {}

    async def fake_send(subject: str, body: str) -> None:
        captured["subject"] = subject
        captured["body"] = body

    monkeypatch.setattr(
        "app.services.email_sender.send_admin_notification", fake_send
    )

    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.post(
            "/admin/api/notify",
            headers={"Authorization": "Bearer secret123"},
            json={"subject": "Test subject", "body": "Test body line 1\nline 2"},
        )
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert captured["subject"] == "Test subject"
    assert captured["body"] == "Test body line 1\nline 2"
    await close_db()


@pytest.mark.asyncio
async def test_notify_502_on_smtp_failure_does_not_leak(monkeypatch):
    """SMTP exception body must not be echoed in the response — could
    contain auth-failure error strings with credentials."""
    monkeypatch.setenv("NOTIFY_API_TOKEN", "secret123")

    async def boom(subject, body):
        raise RuntimeError("smtp auth failed for user=brevo-leak")

    monkeypatch.setattr(
        "app.services.email_sender.send_admin_notification", boom
    )

    await _setup()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.post(
            "/admin/api/notify",
            headers={"Authorization": "Bearer secret123"},
            json={"subject": "x", "body": "y"},
        )
    assert r.status_code == 502
    detail = r.json().get("message", "")
    assert "brevo-leak" not in detail
    assert "RuntimeError" in detail  # type name only
    await close_db()
