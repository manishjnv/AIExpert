"""IndexNow service + wiring tests (SEO-07).

Unit tests:
  - ping() no-op when INDEXNOW_KEY empty
  - ping() POSTs correct payload shape when key + urls present
  - ping() swallows HTTP 4xx/5xx (non-fatal)
  - ping() swallows connection errors (non-fatal)

Integration tests (wiring):
  - POST /admin/api/blog/publish calls ping_async with /blog/{slug}
  - Certificate issuance (new cert) calls ping_async with /verify/{id}
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

import app.db as db_module
import app.models  # noqa: F401
from app.db import Base, close_db, init_db


async def _setup():
    await init_db(url="sqlite+aiosqlite:///:memory:")
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _app():
    from app.main import app
    return app


# ---- Unit tests: ping() ------------------------------------------------------


@pytest.mark.asyncio
async def test_ping_noop_when_key_empty(monkeypatch):
    """No HTTP request should fire when indexnow_key is not set."""
    from app.services import indexnow

    fake_post = AsyncMock()
    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

    class _S:
        indexnow_key = ""
        public_base_url = "https://automateedge.cloud"
    monkeypatch.setattr(indexnow, "get_settings", lambda: _S())

    await indexnow.ping(["https://automateedge.cloud/blog/test"])
    fake_post.assert_not_called()


@pytest.mark.asyncio
async def test_ping_noop_when_urls_empty(monkeypatch):
    from app.services import indexnow

    fake_post = AsyncMock()
    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

    class _S:
        indexnow_key = "abc123"
        public_base_url = "https://automateedge.cloud"
    monkeypatch.setattr(indexnow, "get_settings", lambda: _S())

    await indexnow.ping([])
    fake_post.assert_not_called()


@pytest.mark.asyncio
async def test_ping_posts_correct_payload(monkeypatch):
    """Payload must carry host, key, keyLocation, urlList; endpoint is
    the official IndexNow URL."""
    from app.services import indexnow

    captured = {}

    async def fake_post(self, url, json=None, **_kwargs):  # noqa: A002
        captured["url"] = url
        captured["json"] = json
        return httpx.Response(200)

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

    class _S:
        indexnow_key = "da644d9738c272503eb10a09c1feb9d7"
        public_base_url = "https://automateedge.cloud"
    monkeypatch.setattr(indexnow, "get_settings", lambda: _S())

    urls = ["https://automateedge.cloud/blog/hello",
            "https://automateedge.cloud/blog/world"]
    await indexnow.ping(urls)

    assert captured["url"] == "https://api.indexnow.org/indexnow"
    body = captured["json"]
    assert body["host"] == "automateedge.cloud"
    assert body["key"] == "da644d9738c272503eb10a09c1feb9d7"
    assert body["keyLocation"] == (
        "https://automateedge.cloud/da644d9738c272503eb10a09c1feb9d7.txt"
    )
    assert body["urlList"] == urls


@pytest.mark.asyncio
async def test_ping_swallows_4xx_response(monkeypatch, caplog):
    """A 403 key-mismatch response must not raise; publish should never
    fail because Bing rejected the ping."""
    from app.services import indexnow

    async def fake_post(self, url, json=None, **_kwargs):
        return httpx.Response(403, text="key mismatch")

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

    class _S:
        indexnow_key = "abc"
        public_base_url = "https://automateedge.cloud"
    monkeypatch.setattr(indexnow, "get_settings", lambda: _S())

    # Should complete without raising
    await indexnow.ping(["https://automateedge.cloud/x"])


@pytest.mark.asyncio
async def test_ping_swallows_network_error(monkeypatch):
    from app.services import indexnow

    async def fake_post(self, url, json=None, **_kwargs):
        raise httpx.ConnectError("network down")

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

    class _S:
        indexnow_key = "abc"
        public_base_url = "https://automateedge.cloud"
    monkeypatch.setattr(indexnow, "get_settings", lambda: _S())

    await indexnow.ping(["https://automateedge.cloud/x"])  # must not raise


# ---- Wiring: blog publish fires ping_async ---------------------------------


@pytest.mark.asyncio
async def test_blog_publish_triggers_indexnow_ping(monkeypatch, tmp_path):
    """Publishing a draft must call ping_async with /blog/{slug} on the
    configured base URL."""
    from app.services import blog_publisher

    calls: list[list[str]] = []

    def _capture(urls: list[str]) -> None:
        calls.append(list(urls))

    # ping_async is imported inside the publish handler at call time —
    # patching the canonical module covers both use sites.
    monkeypatch.setattr("app.services.indexnow.ping_async", _capture)

    # Redirect blog_publisher data dirs so we don't touch /data/blog
    monkeypatch.setattr(blog_publisher, "DRAFTS_DIR", tmp_path / "drafts")
    monkeypatch.setattr(blog_publisher, "PUBLISHED_DIR", tmp_path / "published")
    monkeypatch.setattr(blog_publisher, "_ensure_dirs", lambda: (
        (tmp_path / "drafts").mkdir(parents=True, exist_ok=True),
        (tmp_path / "published").mkdir(parents=True, exist_ok=True),
    ))
    monkeypatch.setattr(blog_publisher, "validate_payload",
                        lambda p: {"ok": True, "errors": [], "warnings": []})

    slug = "test-indexnow-post"
    (tmp_path / "drafts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "published").mkdir(parents=True, exist_ok=True)
    import json
    (tmp_path / "drafts" / f"{slug}.json").write_text(json.dumps({
        "slug": slug, "title": "T", "description": "D",
        "published": "2026-04-23", "body_html": "<p>x</p>",
    }))

    # Stand up the app with an admin cookie
    await _setup()
    from app.auth.jwt import issue_token
    from app.models.user import User

    async with db_module.async_session_factory() as s:
        admin = User(email="a@t", name="A", provider="otp", is_admin=True)
        s.add(admin)
        await s.flush()
        tok = await issue_token(admin, s)
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.post(
            "/admin/api/blog/publish",
            json={"slug": slug},
            headers={"Origin": "http://t", "Host": "t"},
            cookies={"auth_token": tok},
        )
        assert r.status_code == 200, r.text

    # One ping with exactly one URL ending in /blog/{slug}
    assert len(calls) == 1
    assert len(calls[0]) == 1
    assert calls[0][0].endswith(f"/blog/{slug}")
    await close_db()


# ---- Wiring: cert issue fires ping_async ------------------------------------


@pytest.mark.asyncio
async def test_cert_issuance_triggers_indexnow_ping(monkeypatch):
    """New certificate row → one ping_async call with /verify/{id}."""
    from app.models.plan import UserPlan
    from app.models.user import User
    from app.services import certificates

    calls: list[list[str]] = []

    def _capture(urls: list[str]) -> None:
        calls.append(list(urls))

    monkeypatch.setattr("app.services.indexnow.ping_async", _capture)

    # Stub the stats + tier so we force issue path
    class _Tpl:
        title = "AI Generalist"; level = "Beginner"; duration_months = 6
        total_hours = 240; total_checks = 10; repos_required = 3

    async def _fake_stats(db, plan):
        return {
            "template": _Tpl(),
            "total_checks": 10, "checks_done": 10,
            "capstone_total": 0, "capstone_done": 0,
            "repos_required": 3, "repos_linked": 3,
            "has_honors_eval": False,
        }
    monkeypatch.setattr(certificates, "_collect_plan_stats", _fake_stats)
    monkeypatch.setattr(certificates, "_determine_tier",
                        lambda **_: "completion")

    await _setup()
    async with db_module.async_session_factory() as s:
        u = User(email="u@t", name="U", provider="otp")
        s.add(u); await s.flush()
        p = UserPlan(user_id=u.id, template_key="generalist",
                     plan_version="v1", status="active")
        s.add(p); await s.commit()
        cert = await certificates.check_and_issue(s, u, p)
        assert cert is not None

    assert len(calls) == 1
    assert len(calls[0]) == 1
    assert calls[0][0].startswith("http")
    assert "/verify/" in calls[0][0]
    await close_db()
