"""Tests for the daily X tweet draft curator."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

import app.db as db_module
import app.models  # noqa: F401 — registers TweetDraft on Base.metadata
from app.db import Base, close_db, init_db
from app.models.tweet_draft import TweetDraft
from app.services import tweet_curator


@pytest.fixture
async def db_session():
    """Local DB fixture. The project-wide conftest.db_session imports
    `engine` at module-load before init_db() rebinds it (sees stale None);
    other tests bypass via db_module — we do the same."""
    await init_db(url="sqlite+aiosqlite:///:memory:")
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with db_module.async_session_factory() as session:
        yield session
    await close_db()


# ---------- slot_for_today ----------

@pytest.mark.parametrize(
    "ist_weekday,expected",
    [
        (0, "blog_teaser"),  # Mon
        (1, "quotable"),     # Tue
        (2, "blog_teaser"),  # Wed
        (3, "quotable"),     # Thu
        (4, "blog_teaser"),  # Fri
        (5, None),           # Sat
        (6, None),           # Sun
    ],
)
def test_slot_for_today_rotation(ist_weekday, expected):
    """Mon-Fri rotate, Sat/Sun return None. Use a known IST timestamp at noon
    to avoid timezone-edge weirdness — IST = UTC+5:30 so noon IST = 06:30 UTC."""
    # 2026-01-05 was a Monday IST. Walk forward `ist_weekday` days to the
    # weekday under test, set time to 06:30 UTC (noon IST).
    base_monday_ist_noon_utc = datetime(2026, 1, 5, 6, 30, tzinfo=timezone.utc)
    now_utc = base_monday_ist_noon_utc + timedelta(days=ist_weekday)
    assert tweet_curator.slot_for_today(now_utc) == expected


def test_slot_for_today_handles_ist_offset_at_midnight():
    """The cron fires at 13:30 UTC = 19:00 IST (US peak window). The IST-vs-UTC
    date flip matters at the early-morning window where the prior cron lived
    (02:30 UTC = 08:00 IST), so we keep both shapes covered:

      - 02:30 UTC Mon: pre-shift slot — Mon 08:00 IST → blog_teaser.
      - 13:30 UTC Mon: post-shift slot — Mon 19:00 IST → still blog_teaser.

    The weekday must be the same either way; otherwise the cadence cycle would
    drift when the cron time was shifted."""
    monday_morning_utc = datetime(2026, 1, 5, 2, 30, tzinfo=timezone.utc)
    monday_evening_utc = datetime(2026, 1, 5, 13, 30, tzinfo=timezone.utc)
    assert tweet_curator.slot_for_today(monday_morning_utc) == "blog_teaser"
    assert tweet_curator.slot_for_today(monday_evening_utc) == "blog_teaser"
    # Tuesday 13:30 UTC = Tue 19:00 IST → quotable.
    tuesday_evening_utc = datetime(2026, 1, 6, 13, 30, tzinfo=timezone.utc)
    assert tweet_curator.slot_for_today(tuesday_evening_utc) == "quotable"
    # Mid-Sunday IST (e.g. Sun 06:30 UTC = Sun 12:00 IST) → None
    sunday_noon_ist_utc = datetime(2026, 1, 4, 6, 30, tzinfo=timezone.utc)
    assert tweet_curator.slot_for_today(sunday_noon_ist_utc) is None
    # Sat 22:30 UTC = Sun 04:00 IST → still Sunday → None
    saturday_late_utc = datetime(2026, 1, 3, 22, 30, tzinfo=timezone.utc)
    assert tweet_curator.slot_for_today(saturday_late_utc) is None


# ---------- compose_draft ----------

def test_compose_draft_blog_teaser_prefers_quotable_falls_back_to_title():
    """Phase B engagement upgrade: blog_teaser now mirrors the quotable-first
    pattern from routers/blog.py _curate_share_copy (the Share-button code
    path). When a quotable line ≤ 253 chars exists it leads; otherwise the
    title takes over."""
    # Quotable available + within budget → leads with quotable.
    quoted = {
        "slug": "x-vs-y",
        "title": "X vs Y in 2026",
        "quotable_lines": ["The hook that pulled you in.", "Second beat."],
    }
    out_q = tweet_curator.compose_draft("blog_teaser", quoted, "https://example.com")
    assert out_q == "The hook that pulled you in.\n\nhttps://example.com/blog/x-vs-y"

    # No quotable_lines → falls back to title (the original behavior).
    no_q = {"slug": "x-vs-y", "title": "X vs Y in 2026"}
    out_t = tweet_curator.compose_draft("blog_teaser", no_q, "https://example.com")
    assert out_t == "X vs Y in 2026\n\nhttps://example.com/blog/x-vs-y"

    # Quotable exists but exceeds the 253-char prose budget → falls back to title.
    long_q = {
        "slug": "x-vs-y",
        "title": "X vs Y in 2026",
        "quotable_lines": ["x" * 260],
    }
    out_l = tweet_curator.compose_draft("blog_teaser", long_q, "https://example.com")
    assert out_l == "X vs Y in 2026\n\nhttps://example.com/blog/x-vs-y"


def test_compose_draft_quotable_uses_first_quotable():
    post = {
        "slug": "x", "title": "Title",
        "quotable_lines": ["First line.", "Second."],
    }
    out = tweet_curator.compose_draft("quotable", post, "https://example.com")
    assert out.startswith("First line.\n\n")
    assert out.endswith("/blog/x")


def test_compose_draft_quotable_falls_back_to_title_when_missing():
    """Quotable slot but the post never set quotable_lines — use title."""
    post = {"slug": "x", "title": "The fallback title"}
    out = tweet_curator.compose_draft("quotable", post, "https://example.com")
    assert out.startswith("The fallback title\n\n")


def test_compose_draft_quotable_falls_back_when_quotable_too_long():
    """Quotable that exceeds the 253-char prose budget reverts to title."""
    long_q = "x" * 260
    post = {"slug": "s", "title": "Short title", "quotable_lines": [long_q]}
    out = tweet_curator.compose_draft("quotable", post, "https://example.com")
    assert out.startswith("Short title\n\n")


def test_compose_draft_truncates_overlong_title():
    """Title beyond 253 chars must be truncated with ellipsis at a word boundary."""
    title = " ".join(["word"] * 100)  # ~500 chars
    post = {"slug": "s", "title": title}
    out = tweet_curator.compose_draft("blog_teaser", post, "https://example.com")
    hook = out.split("\n\n", 1)[0]
    assert len(hook) <= tweet_curator.PROSE_BUDGET
    assert hook.endswith("…")
    # Total tweet length budget: prose + 4 newlines + URL — but t.co wrapping
    # makes the *displayed* length 280; we don't pre-truncate on URL length
    # since X handles that. Sanity: hook + URL together is under 280 in our
    # check because our example URL is shorter than 23 chars.
    assert len(out) <= tweet_curator.TWITTER_HARD_LIMIT


# ---------- pick_source / queue_today (DB-backed) ----------

@pytest.fixture
def fake_published(monkeypatch, tmp_path):
    """Point the curator at a tmp dir of fake published JSON files."""
    pub_dir = tmp_path / "published"
    pub_dir.mkdir()
    monkeypatch.setattr(tweet_curator, "PUBLISHED_DIR", pub_dir)

    def add(slug, title, published_date, quotables=None):
        payload = {"slug": slug, "title": title, "published": published_date}
        if quotables is not None:
            payload["quotable_lines"] = quotables
        (pub_dir / f"{slug}.json").write_text(json.dumps(payload), encoding="utf-8")

    return add


@pytest.mark.asyncio
async def test_queue_today_inserts_pending_row(db_session, fake_published, monkeypatch):
    fake_published("a", "First Post", "2026-04-20", quotables=["A quote."])
    fake_published("b", "Second Post", "2026-04-22", quotables=["Another."])

    monday = datetime(2026, 1, 5, 6, 30, tzinfo=timezone.utc)  # Mon = blog_teaser
    draft = await tweet_curator.queue_today(db_session, "https://example.com", monday)
    assert draft is not None
    assert draft.slot_type == "blog_teaser"
    assert draft.source_kind == "blog"
    # Newest by `published` date wins → "b"
    assert draft.source_ref == "b"
    # blog_teaser now leads with quotable_lines[0] when available (Phase B
    # engagement upgrade) — "Another." is post b's first quotable.
    assert draft.draft_text.startswith("Another.\n\n")
    assert draft.status == "pending"
    assert draft.scheduled_date == "2026-01-05"


@pytest.mark.asyncio
async def test_queue_today_skips_weekend(db_session, fake_published):
    fake_published("a", "Post A", "2026-04-20")
    saturday = datetime(2026, 1, 10, 6, 30, tzinfo=timezone.utc)  # Sat
    draft = await tweet_curator.queue_today(db_session, "https://example.com", saturday)
    assert draft is None


@pytest.mark.asyncio
async def test_queue_today_dedupes_recently_posted_in_same_slot(
    db_session, fake_published,
):
    """If a post was already shipped via blog_teaser within 30 days, the
    curator picks the next-newest instead. A different slot (quotable) of
    the same post is allowed."""
    fake_published("recent", "Recent", "2026-04-25")
    fake_published("older", "Older", "2026-04-10")

    # Simulate "recent" already posted via blog_teaser 5 days ago
    db_session.add(TweetDraft(
        scheduled_date="2026-04-21", slot_type="blog_teaser",
        source_kind="blog", source_ref="recent",
        draft_text="x", status="posted",
        posted_tweet_id="999",
        posted_at=datetime.now(timezone.utc) - timedelta(days=5),
    ))
    await db_session.commit()

    monday = datetime(2026, 1, 5, 6, 30, tzinfo=timezone.utc)
    draft = await tweet_curator.queue_today(db_session, "https://example.com", monday)
    assert draft is not None
    assert draft.source_ref == "older"


@pytest.mark.asyncio
async def test_queue_today_dedupe_does_not_block_other_slot(
    db_session, fake_published,
):
    """A blog teased on Monday can still be quoted on Tuesday — different slots."""
    fake_published("a", "A", "2026-04-25", quotables=["Quote."])
    db_session.add(TweetDraft(
        scheduled_date="2026-04-21", slot_type="blog_teaser",
        source_kind="blog", source_ref="a",
        draft_text="x", status="posted",
        posted_tweet_id="1",
        posted_at=datetime.now(timezone.utc) - timedelta(days=1),
    ))
    await db_session.commit()

    tuesday = datetime(2026, 1, 6, 6, 30, tzinfo=timezone.utc)  # Tue = quotable
    draft = await tweet_curator.queue_today(db_session, "https://example.com", tuesday)
    assert draft is not None
    assert draft.slot_type == "quotable"
    assert draft.source_ref == "a"


@pytest.mark.asyncio
async def test_queue_today_returns_none_when_no_eligible(db_session, fake_published):
    """All posts deduped → None, no ghost row."""
    fake_published("a", "A", "2026-04-25")
    db_session.add(TweetDraft(
        scheduled_date="2026-04-21", slot_type="blog_teaser",
        source_kind="blog", source_ref="a",
        draft_text="x", status="posted",
        posted_tweet_id="1",
        posted_at=datetime.now(timezone.utc) - timedelta(days=1),
    ))
    await db_session.commit()

    monday = datetime(2026, 1, 5, 6, 30, tzinfo=timezone.utc)
    draft = await tweet_curator.queue_today(db_session, "https://example.com", monday)
    assert draft is None


@pytest.mark.asyncio
async def test_queue_today_dedupes_pending_in_flight(db_session, fake_published):
    """A pending draft for source 'a' must block re-queuing 'a' in the same
    slot — otherwise repeated /queue-now calls would create N drafts for
    the same source, and a future Post on each would post N times."""
    fake_published("a", "A", "2026-04-25")
    fake_published("b", "B", "2026-04-20")
    db_session.add(TweetDraft(
        scheduled_date="2026-04-25", slot_type="blog_teaser",
        source_kind="blog", source_ref="a",
        draft_text="x", status="pending",  # in-flight, never posted
    ))
    await db_session.commit()

    monday = datetime(2026, 1, 5, 6, 30, tzinfo=timezone.utc)
    draft = await tweet_curator.queue_today(db_session, "https://example.com", monday)
    assert draft is not None
    assert draft.source_ref == "b"  # 'a' deduped


@pytest.mark.asyncio
async def test_queue_today_dedupes_posting_in_flight(db_session, fake_published):
    """A draft mid-API-call (status='posting') must not be re-queued either."""
    fake_published("a", "A", "2026-04-25")
    fake_published("b", "B", "2026-04-20")
    db_session.add(TweetDraft(
        scheduled_date="2026-04-25", slot_type="blog_teaser",
        source_kind="blog", source_ref="a",
        draft_text="x", status="posting",
    ))
    await db_session.commit()

    monday = datetime(2026, 1, 5, 6, 30, tzinfo=timezone.utc)
    draft = await tweet_curator.queue_today(db_session, "https://example.com", monday)
    assert draft is not None
    assert draft.source_ref == "b"


@pytest.mark.asyncio
async def test_queue_today_dedupes_failed_in_flight(db_session, fake_published):
    """A failed draft is still 'in flight' until admin skips or successfully
    re-posts it. Don't re-queue the same source while a failure is pending
    admin attention."""
    fake_published("a", "A", "2026-04-25")
    fake_published("b", "B", "2026-04-20")
    db_session.add(TweetDraft(
        scheduled_date="2026-04-25", slot_type="blog_teaser",
        source_kind="blog", source_ref="a",
        draft_text="x", status="failed",
        error_message="X said no",
    ))
    await db_session.commit()

    monday = datetime(2026, 1, 5, 6, 30, tzinfo=timezone.utc)
    draft = await tweet_curator.queue_today(db_session, "https://example.com", monday)
    assert draft is not None
    assert draft.source_ref == "b"


@pytest.mark.asyncio
async def test_queue_today_skipped_does_not_dedupe(db_session, fake_published):
    """Skipped drafts are admin-rejected and the source becomes available
    again (admin chose not to post; we shouldn't punish the source)."""
    fake_published("a", "A", "2026-04-25")
    db_session.add(TweetDraft(
        scheduled_date="2026-04-21", slot_type="blog_teaser",
        source_kind="blog", source_ref="a",
        draft_text="x", status="skipped",
    ))
    await db_session.commit()

    monday = datetime(2026, 1, 5, 6, 30, tzinfo=timezone.utc)
    draft = await tweet_curator.queue_today(db_session, "https://example.com", monday)
    assert draft is not None
    assert draft.source_ref == "a"  # not deduped


@pytest.mark.asyncio
async def test_queue_today_dedupes_posted_with_null_posted_at(db_session, fake_published):
    """`status='posted'` with `posted_at=NULL` (legacy / manual rows) must
    still be treated as ineligible. SQLite NULL >= cutoff is NULL → False,
    so without the explicit IS NULL clause these rows leak past dedupe."""
    fake_published("a", "A", "2026-04-25")
    fake_published("b", "B", "2026-04-20")
    db_session.add(TweetDraft(
        scheduled_date="2026-04-21", slot_type="blog_teaser",
        source_kind="blog", source_ref="a",
        draft_text="x", status="posted",
        posted_tweet_id="999",
        posted_at=None,  # ← the gap codex flagged
    ))
    await db_session.commit()

    monday = datetime(2026, 1, 5, 6, 30, tzinfo=timezone.utc)
    draft = await tweet_curator.queue_today(db_session, "https://example.com", monday)
    assert draft is not None
    assert draft.source_ref == "b"  # 'a' is deduped despite NULL posted_at


# ---------- queue_today + OG image attachment ----------


@pytest.fixture
def no_twitter_creds(monkeypatch):
    """Default: no creds in env. queue_today must skip the upload entirely
    and store media_id=NULL on the row, never raising."""
    for k in ("TWITTER_API_KEY", "TWITTER_API_SECRET",
              "TWITTER_ACCESS_TOKEN", "TWITTER_ACCESS_TOKEN_SECRET"):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def with_twitter_creds(monkeypatch):
    """Provide test creds so credentials_from_env() returns a real object;
    individual tests still mock out the actual httpx calls."""
    monkeypatch.setenv("TWITTER_API_KEY", "ck")
    monkeypatch.setenv("TWITTER_API_SECRET", "cs")
    monkeypatch.setenv("TWITTER_ACCESS_TOKEN", "at")
    monkeypatch.setenv("TWITTER_ACCESS_TOKEN_SECRET", "ats")


@pytest.mark.asyncio
async def test_queue_today_no_creds_stores_null_media_id(
    db_session, fake_published, no_twitter_creds, monkeypatch,
):
    """When TWITTER_* env vars are unset, queue_today still ships the draft
    (admin can post text-only or skip) — media_id stays NULL, no fetch
    attempt, no log spam."""
    fake_published("a", "A", "2026-04-25")
    # Sentinel: if either helper is hit despite missing creds, the test
    # fails loudly instead of silently making a network call.
    monkeypatch.setattr(
        tweet_curator, "_fetch_og_image",
        _fail_if_called("og fetch should not run when creds are unset"),
    )
    monday = datetime(2026, 1, 5, 6, 30, tzinfo=timezone.utc)
    draft = await tweet_curator.queue_today(db_session, "https://example.com", monday)
    assert draft is not None
    assert draft.media_id is None


@pytest.mark.asyncio
async def test_queue_today_image_fetch_failure_creates_text_only_draft(
    db_session, fake_published, with_twitter_creds, monkeypatch,
):
    """When the OG image route is unreachable / 404 / 5xx, the draft is
    still created with media_id=NULL — text-only fallback is the safety
    net. Critically, no exception escapes into queue_today."""
    fake_published("a", "A", "2026-04-25")

    async def _broken_fetch(base_url, slug, **kw):
        return None  # mimics 404 / timeout / network blip

    monkeypatch.setattr(tweet_curator, "_fetch_og_image", _broken_fetch)

    monday = datetime(2026, 1, 5, 6, 30, tzinfo=timezone.utc)
    draft = await tweet_curator.queue_today(db_session, "https://example.com", monday)
    assert draft is not None
    assert draft.source_ref == "a"
    assert draft.media_id is None  # text-only fallback


@pytest.mark.asyncio
async def test_queue_today_upload_failure_creates_text_only_draft(
    db_session, fake_published, with_twitter_creds, monkeypatch,
):
    """OG image fetch succeeds but X media upload returns 4xx — draft still
    ships with media_id=NULL. The TwitterAPIError must be swallowed inside
    _attach_og_media; a transient X outage should never prevent queueing."""
    fake_published("a", "A", "2026-04-25")

    async def _ok_fetch(base_url, slug, **kw):
        return b"\x89PNG fake bytes"

    async def _bad_upload(creds, image_bytes, **kw):
        from app.services.twitter_client import TwitterAPIError
        raise TwitterAPIError("upload failed", status=400)

    monkeypatch.setattr(tweet_curator, "_fetch_og_image", _ok_fetch)
    monkeypatch.setattr(
        tweet_curator.twitter_client, "upload_media", _bad_upload,
    )

    monday = datetime(2026, 1, 5, 6, 30, tzinfo=timezone.utc)
    draft = await tweet_curator.queue_today(db_session, "https://example.com", monday)
    assert draft is not None
    assert draft.media_id is None


@pytest.mark.asyncio
async def test_queue_today_happy_path_attaches_media_id(
    db_session, fake_published, with_twitter_creds, monkeypatch,
):
    """Full end-to-end: image fetched, X uploaded, draft.media_id stored."""
    fake_published("a", "A", "2026-04-25")
    captured = {}

    async def _fetch(base_url, slug, **kw):
        captured["fetched_slug"] = slug
        captured["base_url"] = base_url
        return b"\x89PNG" + b"\x00" * 50

    async def _upload(creds, image_bytes, **kw):
        captured["uploaded_bytes"] = len(image_bytes)
        return "9999"  # simulated media_id_string

    monkeypatch.setattr(tweet_curator, "_fetch_og_image", _fetch)
    monkeypatch.setattr(
        tweet_curator.twitter_client, "upload_media", _upload,
    )

    monday = datetime(2026, 1, 5, 6, 30, tzinfo=timezone.utc)
    draft = await tweet_curator.queue_today(db_session, "https://example.com", monday)
    assert draft is not None
    assert draft.media_id == "9999"
    assert captured["fetched_slug"] == "a"
    assert captured["base_url"] == "https://example.com"
    assert captured["uploaded_bytes"] > 0


@pytest.mark.asyncio
async def test_fetch_og_image_404_returns_none(monkeypatch):
    """The OG fetch helper itself must absorb non-200 status codes."""
    import httpx as _httpx

    def handler(request):
        return _httpx.Response(404, content=b"Not Found")

    transport = _httpx.MockTransport(handler)

    # Patch httpx.AsyncClient to use our mock transport.
    real_client = _httpx.AsyncClient

    class _MockClient(real_client):
        def __init__(self, *a, **kw):
            kw.pop("timeout", None)
            super().__init__(transport=transport, timeout=1.0)

    monkeypatch.setattr(tweet_curator.httpx, "AsyncClient", _MockClient)

    out = await tweet_curator._fetch_og_image("https://example.com", "missing")
    assert out is None


@pytest.mark.asyncio
async def test_fetch_og_image_network_error_returns_none(monkeypatch):
    """Connection errors absorbed too — never propagate to caller."""
    import httpx as _httpx

    def handler(request):
        raise _httpx.ConnectError("network down")

    transport = _httpx.MockTransport(handler)
    real_client = _httpx.AsyncClient

    class _MockClient(real_client):
        def __init__(self, *a, **kw):
            kw.pop("timeout", None)
            super().__init__(transport=transport, timeout=1.0)

    monkeypatch.setattr(tweet_curator.httpx, "AsyncClient", _MockClient)

    out = await tweet_curator._fetch_og_image("https://example.com", "x")
    assert out is None


def _fail_if_called(msg: str):
    """Returns an async callable that fails the test if invoked. Used as
    a sentinel for code paths that must NOT run."""
    async def _called(*a, **kw):
        raise AssertionError(msg)
    return _called
