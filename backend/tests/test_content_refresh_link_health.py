"""check_link_health must survive a NEW link whose first check fails (RCA-037).

A freshly constructed LinkHealth has consecutive_failures=None until it is flushed
(SQLAlchemy applies `default=0` at INSERT), so `+= 1` on the first failure crashed and
aborted the whole daily content refresh.
"""
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

import app.db as db_module
import app.models  # noqa: F401  (registers LinkHealth on Base.metadata)
from app.db import Base, close_db, init_db
from app.models.curriculum import LinkHealth
from app.services import content_refresh


@pytest.fixture
async def db_session():
    """Local DB fixture: the shared conftest one sees a stale `engine` (same workaround as test_tweet_curator)."""
    await init_db(url="sqlite+aiosqlite:///:memory:")
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with db_module.async_session_factory() as session:
        yield session
    await close_db()


def _template(url: str) -> SimpleNamespace:
    week = SimpleNamespace(n=1, resources=[SimpleNamespace(url=url)])
    return SimpleNamespace(months=[SimpleNamespace(weeks=[week])])


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["http_404", "network_error"])
async def test_new_link_first_check_fails(db_session, monkeypatch, failure):
    url = "https://example.com/gone"
    monkeypatch.setattr("app.curriculum.loader.list_templates", lambda: ["tpl"])
    monkeypatch.setattr("app.curriculum.loader.load_template", lambda key: _template(url))
    monkeypatch.setattr(content_refresh, "_is_safe_url", lambda u: True)

    async def fake_head(self, u, **kw):
        if failure == "network_error":
            raise httpx.ConnectError("boom")
        return httpx.Response(404, request=httpx.Request("HEAD", u))

    monkeypatch.setattr(httpx.AsyncClient, "head", fake_head)

    summary = await content_refresh.check_link_health(db_session)

    assert summary == {"total_checked": 1, "ok": 0, "broken": 1}
    row = (await db_session.execute(select(LinkHealth).where(LinkHealth.url == url))).scalar_one()
    assert row.consecutive_failures == 1
