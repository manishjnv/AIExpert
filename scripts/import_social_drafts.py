"""Import Opus-generated social drafts from stdin and write to social_posts.

Pairs with scripts.export_social_sources. Reads JSON from stdin (the Opus
output), validates against SocialCurateOutput (Pydantic), then UPDATEs the
two pending social_posts rows (twitter + linkedin) to status='draft' with
body / hashtags_json / reasoning_json populated.

On Pydantic ValidationError: increments retry_count on both rows; if
retry_count >= 3 after increment, flips that row to status='archived' with
archived_at=now() and captures the reason in reasoning_json.

Each row is committed separately per feedback_sqlite_writer_sessions.md.

CLI flags:
  --twitter-id N   — id of the pending twitter row to update with this draft
  --linkedin-id N  — id of the pending linkedin row to update with this draft
  --invalid        — prior claude call returned un-parseable JSON; reads the
                     export JSON from stdin (to get the pending pair IDs) and
                     increments retry_count on both rows.

If --twitter-id / --linkedin-id are omitted on the success path, the script
falls back to the 2 most recent pending rows (single-cron-runner assumption).

Run:
  cat opus.json | python -m scripts.import_social_drafts --twitter-id 42 --linkedin-id 43
  cat export.json | python -m scripts.import_social_drafts --invalid
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from datetime import datetime, timezone

logger = logging.getLogger("roadmap.social.import_drafts")

MAX_RETRIES_BEFORE_ARCHIVE = 3


def _tolerant_parse(raw: str) -> dict:
    """Parse Opus output that may be wrapped in code fences or have preamble."""
    s = raw.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```\s*$", "", s)
    # Find the first { to strip any prose preamble
    idx = s.find("{")
    if idx > 0:
        s = s[idx:]
    return json.loads(s)


async def _increment_retry(post_id: int, reason: str | None = None) -> None:
    """Increment retry_count for a social_posts row. If >= threshold, archive."""
    import app.db as _db
    from sqlalchemy import select
    from sqlalchemy.exc import OperationalError
    from app.models.social import SocialPost

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for attempt in range(4):
        try:
            async with _db.async_session_factory() as db:
                row = (
                    await db.execute(select(SocialPost).where(SocialPost.id == post_id))
                ).scalar_one_or_none()
                if not row:
                    logger.warning("social_posts row %d not found", post_id)
                    return
                row.retry_count = (row.retry_count or 0) + 1
                row.updated_at = now
                if row.retry_count >= MAX_RETRIES_BEFORE_ARCHIVE:
                    row.status = "archived"
                    row.archived_at = now
                    row.reasoning_json = json.dumps({
                        "archive_reason": reason or "max_retries_exceeded",
                        "retry_count": row.retry_count,
                        "archived_at": now.isoformat(),
                    })
                    logger.info(
                        "archived social_posts row %d after %d retries",
                        post_id, row.retry_count,
                    )
                else:
                    logger.info(
                        "incremented retry_count for social_posts row %d → %d",
                        post_id, row.retry_count,
                    )
                await db.commit()
            return
        except OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == 3:
                raise
            await asyncio.sleep(0.2 * (2 ** attempt))


async def _update_draft(
    post_id: int,
    platform: str,
    draft_data: dict,
) -> None:
    """Update one social_posts row to status='draft' with populated fields."""
    import app.db as _db
    from sqlalchemy import select
    from sqlalchemy.exc import OperationalError
    from app.models.social import SocialPost

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    hashtags = draft_data.get("hashtags") or []
    reasoning = draft_data.get("reasoning") or {}
    body = draft_data.get("body") or ""

    for attempt in range(4):
        try:
            async with _db.async_session_factory() as db:
                row = (
                    await db.execute(select(SocialPost).where(SocialPost.id == post_id))
                ).scalar_one_or_none()
                if not row:
                    logger.warning("social_posts row %d not found for %s draft", post_id, platform)
                    return
                row.status = "draft"
                row.body = body
                row.hashtags_json = json.dumps(hashtags, ensure_ascii=False)
                row.reasoning_json = json.dumps(reasoning, ensure_ascii=False)
                row.updated_at = now
                await db.commit()
            logger.info("updated social_posts row %d (%s) to draft", post_id, platform)
            return
        except OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == 3:
                raise
            await asyncio.sleep(0.2 * (2 ** attempt))


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--invalid",
        action="store_true",
        help="prior claude call returned unparseable output; increment retry_count only",
    )
    parser.add_argument(
        "--twitter-id",
        type=int,
        default=None,
        help="id of the pending twitter social_posts row",
    )
    parser.add_argument(
        "--linkedin-id",
        type=int,
        default=None,
        help="id of the pending linkedin social_posts row",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    from app.logging_redact import install_redacting_filter
    install_redacting_filter()

    raw = sys.stdin.read()
    if not raw.strip():
        logger.error("no input on stdin")
        return 2

    from app.db import init_db, close_db
    import app.db as _db
    await init_db()
    try:
        if args.invalid:
            # stdin is the export JSON; find the pending pair and increment retry
            try:
                export_data = json.loads(raw)
            except Exception as exc:
                logger.error("could not parse export JSON from stdin: %s", exc)
                return 2

            source = export_data.get("source") or {}
            twitter_id = source.get("twitter_post_id")
            linkedin_id = source.get("linkedin_post_id")

            if not twitter_id and not linkedin_id:
                # Fall back: find the most recent pending pair via DB
                from sqlalchemy import select
                from app.models.social import SocialPost
                async with _db.async_session_factory() as db:
                    rows = (
                        await db.execute(
                            select(SocialPost)
                            .where(SocialPost.status == "pending")
                            .order_by(SocialPost.id.desc())
                            .limit(2)
                        )
                    ).scalars().all()
                for row in rows:
                    await _increment_retry(row.id, reason="unparseable_claude_output")
            else:
                for pid in [twitter_id, linkedin_id]:
                    if pid:
                        await _increment_retry(pid, reason="unparseable_claude_output")
            return 0

        # Normal path: parse Opus output JSON
        try:
            raw_parsed = _tolerant_parse(raw)
        except Exception as exc:
            logger.error("could not parse Opus output JSON: %s", exc)
            return 2

        # IDs come from CLI args (passed by the cron from EXPORT_FILE).
        # Fallback: pick the 2 most recent pending rows (single-runner assumption,
        # safe under flock + commit-per-row pattern).
        twitter_id = args.twitter_id
        linkedin_id = args.linkedin_id

        if not twitter_id or not linkedin_id:
            from sqlalchemy import select
            from app.models.social import SocialPost
            async with _db.async_session_factory() as db:
                rows = (
                    await db.execute(
                        select(SocialPost)
                        .where(SocialPost.status == "pending")
                        .order_by(SocialPost.id.desc())
                        .limit(2)
                    )
                ).scalars().all()
            for row in rows:
                if row.platform == "twitter" and not twitter_id:
                    twitter_id = row.id
                elif row.platform == "linkedin" and not linkedin_id:
                    linkedin_id = row.id

        if not twitter_id or not linkedin_id:
            logger.error(
                "import_social_drafts: could not resolve pending row IDs for "
                "twitter and linkedin — pass --twitter-id / --linkedin-id, or "
                "ensure 2 pending rows exist."
            )
            return 2

        # Validate via Pydantic schema (slice-1 symbol). Done AFTER ID resolution
        # so a validation failure can correctly increment retry_count on the rows.
        try:
            from app.ai.schemas import SocialCurateOutput
            curated = SocialCurateOutput.model_validate(raw_parsed)
        except Exception as exc:
            logger.error("SocialCurateOutput validation failed: %s", exc)
            for pid in [twitter_id, linkedin_id]:
                if pid:
                    await _increment_retry(pid, reason="schema_validation_failed")
            return 2

        # Update twitter row
        await _update_draft(
            twitter_id,
            "twitter",
            {
                "body": curated.twitter.body,
                "hashtags": curated.twitter.hashtags,
                "reasoning": curated.twitter.reasoning.model_dump()
                if hasattr(curated.twitter, "reasoning") and curated.twitter.reasoning
                else {},
            },
        )

        # Update linkedin row (separate commit per feedback_sqlite_writer_sessions.md)
        await _update_draft(
            linkedin_id,
            "linkedin",
            {
                "body": curated.linkedin.body,
                "hashtags": curated.linkedin.hashtags,
                "reasoning": curated.linkedin.reasoning.model_dump()
                if hasattr(curated.linkedin, "reasoning") and curated.linkedin.reasoning
                else {},
            },
        )

        logger.info("import_social_drafts: success — rows %d + %d updated to draft", twitter_id, linkedin_id)
        return 0

    finally:
        await close_db()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
