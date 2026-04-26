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
    """The cron fires at 02:30 UTC = 08:00 IST. The IST-vs-UTC date flip
    matters: a UTC time before midnight may already be tomorrow in IST.
    Mon 02:30 UTC = Mon 08:00 IST (the actual cron firing window) → blog_teaser."""
    monday_cron_utc = datetime(2026, 1, 5, 2, 30, tzinfo=timezone.utc)
    assert tweet_curator.slot_for_today(monday_cron_utc) == "blog_teaser"
    # Mid-Sunday IST (e.g. Sun 06:30 UTC = Sun 12:00 IST) → None
    sunday_noon_ist_utc = datetime(2026, 1, 4, 6, 30, tzinfo=timezone.utc)
    assert tweet_curator.slot_for_today(sunday_noon_ist_utc) is None
    # Sat 22:30 UTC = Sun 04:00 IST → still Sunday → None
    saturday_late_utc = datetime(2026, 1, 3, 22, 30, tzinfo=timezone.utc)
    assert tweet_curator.slot_for_today(saturday_late_utc) is None


# ---------- compose_draft ----------

def test_compose_draft_blog_teaser_uses_title():
    post = {"slug": "x-vs-y", "title": "X vs Y in 2026"}
    out = tweet_curator.compose_draft("blog_teaser", post, "https://example.com")
    assert out == "X vs Y in 2026\n\nhttps://example.com/blog/x-vs-y"


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
    assert "Second Post" in draft.draft_text
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
