"""Daily X/Twitter draft curator.

Flow:
  cron 8am IST → queue_today() → picks slot per weekday → picks freshest unused
  blog post → composes draft text ≤ 280 chars → inserts pending TweetDraft row.

Slot rotation (M-F, weekend skipped):
  Mon  blog_teaser   title + URL
  Tue  quotable      quotable_lines[0] + URL
  Wed  blog_teaser
  Thu  quotable
  Fri  blog_teaser

Dedupe: exclude blogs that have a status='posted' draft of the SAME slot_type
within the last 30 days. A blog can be both teased (Mon) and quoted (Tue) in
the same week — different framings of the same source.

Twitter t.co wraps every URL to 23 chars regardless of length, so the budget
math is title (≤253) + 4 newlines + URL (counts as 23) = ≤280.

If a slot has no eligible source (e.g. all blogs queue-deduped), we insert
nothing and the admin sees no new pending row that morning. No spam, no
re-queue of the same blog.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tweet_draft import TweetDraft
from app.services import twitter_client
from app.services.blog_publisher import PUBLISHED_DIR

logger = logging.getLogger(__name__)

# OG image fetch budget. The card is generated server-side and served by
# nginx; 10s is generous and bounds the cron run time when the route is
# slow (e.g., on an edge cache miss with the Python OG renderer cold).
OG_FETCH_TIMEOUT_S = 10.0

# IST = UTC+05:30. The cron fires once per UTC day; we resolve "what day is it
# in IST" so the slot weekday matches the admin's local calendar.
IST_OFFSET = timedelta(hours=5, minutes=30)

# Mon=0 ... Sun=6. None means skip the day entirely.
_SLOT_BY_WEEKDAY: dict[int, Optional[str]] = {
    0: "blog_teaser",
    1: "quotable",
    2: "blog_teaser",
    3: "quotable",
    4: "blog_teaser",
    5: None,  # Sat
    6: None,  # Sun
}

LOOKBACK_DAYS = 30
TWITTER_HARD_LIMIT = 280
# t.co wrapping eats 23 chars regardless of URL length; reserve that + 4 chars
# for the two `\n\n` separators between text and URL.
_URL_BUDGET = 23
_NEWLINE_BUDGET = 4
PROSE_BUDGET = TWITTER_HARD_LIMIT - _URL_BUDGET - _NEWLINE_BUDGET  # 253


def slot_for_today(now_utc: Optional[datetime] = None) -> Optional[str]:
    """Returns the slot_type to queue today, or None if today is skipped."""
    now_utc = now_utc or datetime.now(timezone.utc)
    ist = now_utc + IST_OFFSET
    return _SLOT_BY_WEEKDAY.get(ist.weekday())


def _read_published_full(slug: str) -> Optional[dict]:
    """Read the full JSON payload for a published post. Returns None on
    missing/corrupt — caller treats as ineligible source."""
    path = PUBLISHED_DIR / f"{slug}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _list_published_full() -> list[dict]:
    """All published posts as full dicts, sorted by `published` date desc."""
    out: list[dict] = []
    if not PUBLISHED_DIR.exists():
        return out
    for f in sorted(PUBLISHED_DIR.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            out.append(d)
        except (OSError, json.JSONDecodeError):
            continue
    out.sort(key=lambda d: d.get("published", ""), reverse=True)
    return out


async def _ineligible_refs(
    session: AsyncSession,
    slot_type: str,
    lookback_days: int = LOOKBACK_DAYS,
) -> set[str]:
    """source_refs that should NOT be queued today for this slot.

    Three classes of ineligibility:

    1. In-flight rows for the same slot — `pending`, `posting`, `failed`.
       These are content that's queued but not yet decided. Re-queuing
       would create a second draft for the same source (and post-twice
       risk if both eventually ship). Time-unbounded since "in flight"
       has no natural expiry.

    2. Successfully posted rows for the same slot within the lookback
       window. The 30-day cap matches the "don't repost the same item"
       Twitter best practice.

    3. `posted` rows with NULL posted_at (e.g. legacy rows or manual
       inserts) — treated as recent for safety. The dedupe ought to err
       toward NOT reposting; a missing timestamp shouldn't open the door.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    in_flight = select(TweetDraft.source_ref).where(
        and_(
            TweetDraft.slot_type == slot_type,
            TweetDraft.status.in_(("pending", "posting", "failed")),
        )
    )
    recent_posted = select(TweetDraft.source_ref).where(
        and_(
            TweetDraft.slot_type == slot_type,
            TweetDraft.status == "posted",
            # NULL posted_at counts as ineligible (case 3 above): SQLite
            # treats `NULL >= cutoff` as NULL → False, so without the
            # explicit OR these rows would slip past the dedupe.
            (TweetDraft.posted_at >= cutoff) | (TweetDraft.posted_at.is_(None)),
        )
    )
    refs: set[str] = set()
    for stmt in (in_flight, recent_posted):
        result = await session.execute(stmt)
        refs.update(row[0] for row in result.all())
    return refs


def _truncate(text: str, limit: int) -> str:
    """Cut to `limit` chars at a word boundary, append ellipsis. Falls back
    to hard cut + ellipsis if no whitespace before the limit."""
    text = text.strip()
    if len(text) <= limit:
        return text
    if limit < 4:
        return text[:limit]
    cut = text[: limit - 1]
    ws = cut.rfind(" ")
    if ws > limit // 2:  # don't truncate to nothing if the first word is huge
        cut = cut[:ws]
    return cut.rstrip(".,;:- ") + "…"


def compose_draft(slot_type: str, post: dict, base_url: str) -> str:
    """Build the tweet body for a given slot from a published post.

    Both slots prefer quotable_lines[0] when it fits the prose budget — the
    pattern validated by the per-post Share button (routers/blog.py
    _curate_share_copy). Quotable hooks consistently outperform plain
    titles in feed engagement, so blog_teaser shouldn't be different.
    Falls back to title + URL when no usable quotable exists (or it's too
    long for the budget); falls back further to a truncated title if the
    title itself overflows. Never returns "".
    """
    slug = post.get("slug", "")
    url = f"{base_url.rstrip('/')}/blog/{slug}"
    title = (post.get("title") or "").strip()

    hook = ""
    quotables = post.get("quotable_lines") or []
    if isinstance(quotables, list):
        for q in quotables:
            if isinstance(q, str) and q.strip():
                hook = q.strip()
                break

    # Fallback to title when the quotable is missing OR exceeds the budget.
    if not hook or len(hook) > PROSE_BUDGET:
        hook = title

    if len(hook) > PROSE_BUDGET:
        hook = _truncate(hook, PROSE_BUDGET)

    # slot_type kept in the signature — it drives dedupe at the row level
    # (a Mon blog_teaser doesn't block the same post from being a Tue
    # quotable), and a future slot type may want different framing.
    _ = slot_type

    return f"{hook}\n\n{url}"


async def pick_source(
    session: AsyncSession,
    slot_type: str,
    lookback_days: int = LOOKBACK_DAYS,
) -> Optional[dict]:
    """Pick the freshest published post not already used in this slot's
    lookback window. Returns the full post dict, or None if none eligible."""
    used = await _ineligible_refs(session, slot_type, lookback_days)
    for post in _list_published_full():
        slug = post.get("slug")
        if not slug or slug in used:
            continue
        # Quotable slot needs at least one usable quotable_line; if missing,
        # the post falls through to title — still acceptable for now (Phase B).
        # Future: for the dedicated quotable slot, prefer posts that actually
        # have quotables and skip those that don't.
        return post
    return None


async def _fetch_og_image(
    base_url: str,
    slug: str,
    *,
    timeout: float = OG_FETCH_TIMEOUT_S,
) -> Optional[bytes]:
    """Fetch the OG card PNG for a blog post.

    Returns the raw bytes on 2xx with non-empty body, None on any failure
    (404, 5xx, timeout, network, malformed). Image attachment is a
    best-effort engagement upgrade; a missing or broken image must NEVER
    propagate up into queue_today — text-only posts still ship.
    """
    url = f"{base_url.rstrip('/')}/og/blog/{slug}.png"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
    except (httpx.HTTPError, OSError) as e:
        logger.info(
            "tweet_curator: og image fetch errored for slug=%s: %s",
            slug, type(e).__name__,
        )
        return None
    if resp.status_code != 200 or not resp.content:
        logger.info(
            "tweet_curator: og image fetch slug=%s status=%s len=%s — text-only fallback",
            slug, resp.status_code, len(resp.content) if resp.content else 0,
        )
        return None
    return resp.content


async def _attach_og_media(base_url: str, slug: str) -> Optional[str]:
    """Attempt to fetch the OG card and upload it to X v1.1. Returns the
    media_id_string on full success; None if creds are unset, image fetch
    fails, or upload fails. NEVER raises — image attachment is best-effort.
    """
    creds = twitter_client.credentials_from_env()
    if creds is None:
        # Same posture as the admin UI: no creds means "X not configured";
        # we still queue the draft so the admin sees it on /admin/social.
        return None
    image_bytes = await _fetch_og_image(base_url, slug)
    if image_bytes is None:
        return None
    try:
        return await twitter_client.upload_media(creds, image_bytes)
    except (twitter_client.TwitterAPIError, ValueError) as e:
        # Auth-side failures (4xx) and validation issues both land here;
        # both must drop us into the text-only fallback path, not crash
        # the curator.
        logger.info(
            "tweet_curator: media upload failed for slug=%s: %s",
            slug, type(e).__name__,
        )
        return None


async def queue_today(
    session: AsyncSession,
    base_url: str,
    now_utc: Optional[datetime] = None,
) -> Optional[TweetDraft]:
    """Top-level entry — called from the cron loop and the admin manual-trigger.

    Returns the inserted TweetDraft (already added to session, NOT committed
    by this function — the caller controls the transaction). Returns None
    when:
      - today's slot is None (Sat/Sun)
      - all eligible sources are deduped
      - PUBLISHED_DIR is empty

    On a successful pick, attempts to fetch the post's OG card and upload
    it to X for inline display. Image upload is best-effort: failures
    leave media_id NULL on the row, and the post still ships as text-only.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    slot = slot_for_today(now_utc)
    if slot is None:
        logger.info("tweet_curator: skipping (weekend, slot=None)")
        return None

    post = await pick_source(session, slot)
    if post is None:
        logger.info("tweet_curator: skipping (no eligible source for slot=%s)", slot)
        return None

    text = compose_draft(slot, post, base_url)
    slug = post.get("slug", "")
    media_id = await _attach_og_media(base_url, slug)

    ist = now_utc + IST_OFFSET
    draft = TweetDraft(
        scheduled_date=ist.strftime("%Y-%m-%d"),
        slot_type=slot,
        source_kind="blog",
        source_ref=slug,
        draft_text=text,
        status="pending",
        media_id=media_id,
    )
    session.add(draft)
    await session.flush()  # populate draft.id without committing
    logger.info(
        "tweet_curator: queued draft id=%s slot=%s source=%s len=%s media=%s",
        draft.id, slot, draft.source_ref, len(text),
        "yes" if media_id else "no",
    )
    return draft
