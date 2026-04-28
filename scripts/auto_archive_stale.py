"""Flip drafts older than 30 days to archived with reason='stale_30d'.

Standalone wrapper for the daily cron's tail step. Per
feedback_scripts_need_init_db.md and feedback_sqlite_writer_sessions.md:

  - calls init_db()/close_db() explicitly (async_session_factory starts None)
  - one transaction per row (live backend can write concurrently under WAL)

Run:
  python -m scripts.auto_archive_stale [--days N]    # default 30

Exit code:
  0 — success (count of archived rows printed to stdout)
  2 — DB or import error
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("roadmap.social.archive_stale")


async def _archive_one(post_id: int, now: datetime) -> bool:
    """Flip one draft row to archived. Returns True on success."""
    import app.db as _db
    from sqlalchemy import select
    from app.models.social import SocialPost

    async with _db.async_session_factory() as db:
        row = (
            await db.execute(select(SocialPost).where(SocialPost.id == post_id))
        ).scalar_one_or_none()
        if not row or row.status != "draft":
            return False
        try:
            existing = json.loads(row.reasoning_json or "{}")
            if not isinstance(existing, dict):
                existing = {"_legacy": existing}
        except Exception:
            existing = {}
        existing["archive_reason"] = "stale_30d"
        existing["archived_at"] = now.isoformat()
        row.status = "archived"
        row.archived_at = now
        row.updated_at = now
        row.reasoning_json = json.dumps(existing, ensure_ascii=False)
        await db.commit()
        return True


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30,
                        help="archive drafts older than N days (default 30)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    from app.logging_redact import install_redacting_filter
    install_redacting_filter()

    from app.db import init_db, close_db
    import app.db as _db
    from sqlalchemy import select
    from app.models.social import SocialPost

    await init_db()
    try:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            days=args.days
        )
        async with _db.async_session_factory() as db:
            rows = (
                await db.execute(
                    select(SocialPost.id).where(
                        SocialPost.status == "draft",
                        SocialPost.created_at < cutoff,
                    )
                )
            ).all()

        ids = [r[0] for r in rows]
        if not ids:
            logger.info("auto_archive_stale: no drafts older than %dd", args.days)
            print(json.dumps({"archived": 0, "cutoff_days": args.days}))
            return 0

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        archived = 0
        for post_id in ids:
            try:
                if await _archive_one(post_id, now):
                    archived += 1
            except Exception as exc:
                logger.warning("could not archive row %d: %s", post_id, exc)

        logger.info(
            "auto_archive_stale: archived %d row(s) older than %dd",
            archived, args.days,
        )
        print(json.dumps({"archived": archived, "cutoff_days": args.days}))
        return 0

    finally:
        await close_db()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
