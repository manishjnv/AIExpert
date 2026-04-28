"""Export ONE blog or course source needing a social_posts draft.

Inserts 2 pending rows (twitter + linkedin) atomically, emits the source
payload as JSON to stdout. Output shape:

  {"count": 0|1, "source": {kind, slug, title, lede, tags, url,
                             twitter_post_id, linkedin_post_id}}

count==0 means queue empty — caller breaks the loop.

Selection criteria:
  - Blog posts: published in /data/blog/published/ in the last 30 days
    that have NO row in social_posts with status IN ('pending','draft')
    for BOTH platforms. Pick the oldest eligible post first.
  - Course templates: published templates in app/curriculum/templates/
    that have NO row in social_posts with status IN ('pending','draft')
    for BOTH platforms. Pick the oldest eligible template first (by key,
    alphabetically, as a stable proxy for creation order).

The two pending rows are inserted in a single transaction so there is
no window where only one platform is queued.

Run:
  python -m scripts.export_social_sources
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("roadmap.social.export")


async def _pickup_repub_pair() -> dict | None:
    """Pick the oldest pair of pending rows with `_re_publish` markers.

    Returns a source_payload dict (same shape as the fresh-source path) with
    the parent's body attached as `prior_drafts`. Returns None if no
    re-publish pair is queued.

    The marker is a JSON object stored in reasoning_json on each pending row.
    Volume is small (rows from admin clicks only) so we parse in Python rather
    than crafting SQLite JSON-path queries.
    """
    import app.db as _db
    from sqlalchemy import select
    from app.models.social import SocialPost

    async with _db.async_session_factory() as db:
        # Oldest pending rows first
        rows = (
            await db.execute(
                select(SocialPost)
                .where(SocialPost.status == "pending")
                .order_by(SocialPost.created_at.asc(), SocialPost.id.asc())
            )
        ).scalars().all()

        # Group rows by (source_kind, source_slug, created_at) to find pairs
        # inserted by the same Re-publish click. Keep only rows whose
        # reasoning_json carries `_re_publish: true`.
        candidates: dict[tuple, dict] = {}
        for row in rows:
            try:
                meta = json.loads(row.reasoning_json or "{}")
            except Exception:
                continue
            if not isinstance(meta, dict) or not meta.get("_re_publish"):
                continue
            key = (row.source_kind, row.source_slug, row.created_at)
            slot = candidates.setdefault(key, {})
            slot[row.platform] = row
            slot["_parent_id"] = meta.get("_parent_post_id")

        # Find the oldest pair (both twitter + linkedin present)
        for key, slot in candidates.items():
            if "twitter" in slot and "linkedin" in slot:
                return await _build_repub_payload(db, slot)

    return None


async def _build_repub_payload(db, slot: dict) -> dict:
    """Build the source_payload for a re-publish round. Fetches the parent
    published row's body to attach as `prior_drafts`."""
    from app.models.social import SocialPost
    from sqlalchemy import select

    twitter_row = slot["twitter"]
    linkedin_row = slot["linkedin"]
    parent_id = slot.get("_parent_id")

    kind = twitter_row.source_kind
    slug = twitter_row.source_slug

    # Build the source meta exactly like a fresh-source export
    source_payload: dict = {"kind": kind, "slug": slug}
    if kind == "blog":
        try:
            from app.services.blog_publisher import load_published
            full = load_published(slug) or {}
            source_payload.update({
                "title": full.get("title", ""),
                "lede": full.get("lede", ""),
                "tags": full.get("tags", []),
                "url": f"/blog/{slug}",
            })
        except Exception:
            source_payload.update({"title": slug, "url": f"/blog/{slug}"})
    else:
        try:
            from app.curriculum.loader import load_template
            tpl = load_template(slug)
            source_payload.update({
                "title": tpl.title,
                "tagline": tpl.goal,
                "description": tpl.goal,
                "tags": [tpl.level, f"{tpl.duration_months}mo"],
                "url": f"/roadmap/{slug}",
            })
        except Exception:
            source_payload.update({"title": slug, "url": f"/roadmap/{slug}"})

    # Attach prior_drafts — the published body Opus must NOT echo
    prior_drafts: list[dict] = []
    if parent_id:
        parent = (
            await db.execute(
                select(SocialPost).where(SocialPost.id == int(parent_id))
            )
        ).scalar_one_or_none()
        if parent and parent.body:
            prior_drafts.append({
                "platform": parent.platform,
                "body": parent.body[:2000],  # sanity cap; LinkedIn is 3000
            })
    source_payload["prior_drafts"] = prior_drafts
    source_payload["twitter_post_id"] = twitter_row.id
    source_payload["linkedin_post_id"] = linkedin_row.id
    return source_payload


async def _main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    from app.logging_redact import install_redacting_filter
    install_redacting_filter()

    from app.db import init_db, close_db
    import app.db as _db
    from sqlalchemy import select, and_, or_
    from app.models.social import SocialPost  # slice-1 symbol

    await init_db()
    try:
        # ---- Re-publish pickup (priority over fresh sources) ----------------
        # When admin clicks Re-publish on a published row, two pending rows
        # are queued with reasoning_json={"_re_publish": true,
        # "_parent_post_id": N}. Pick those up first so the cron Opus call
        # gets the prior body in `prior_drafts` and writes a different-angle
        # draft.
        repub_payload = await _pickup_repub_pair()
        if repub_payload is not None:
            sys.stdout.write(json.dumps(
                {"count": 1, "source": repub_payload}, ensure_ascii=False
            ))
            sys.stdout.flush()
            return 0

        # Collect candidates from both sources (blogs + courses)
        candidates: list[dict] = []

        # ---- Blog candidates ------------------------------------------------
        try:
            from app.services.blog_publisher import list_published, load_published
            now_utc = datetime.now(timezone.utc)
            cutoff = now_utc - timedelta(days=30)

            published_posts = list_published()
            for post_meta in published_posts:
                slug = post_meta.get("slug", "")
                published_str = post_meta.get("published", "")
                if not slug or not published_str:
                    continue
                try:
                    # published field is an ISO date string like "2026-04-15"
                    pub_date = datetime.strptime(published_str[:10], "%Y-%m-%d").replace(
                        tzinfo=timezone.utc
                    )
                except ValueError:
                    continue
                if pub_date < cutoff:
                    continue
                candidates.append({
                    "kind": "blog",
                    "slug": slug,
                    "published_dt": pub_date,
                    "meta": post_meta,
                })
        except Exception as exc:
            logger.warning("blog candidate scan failed: %s", exc)

        # ---- Course candidates ---------------------------------------------
        try:
            from app.curriculum.loader import list_templates, load_template, get_template_status
            for key in sorted(list_templates()):
                try:
                    status_info = get_template_status(key)
                    if status_info.get("status") != "published":
                        continue
                    candidates.append({
                        "kind": "course",
                        "slug": key,
                        "published_dt": datetime(2000, 1, 1, tzinfo=timezone.utc),  # stable sort last
                        "meta": {"key": key},
                    })
                except Exception:
                    continue
        except Exception as exc:
            logger.warning("course candidate scan failed: %s", exc)

        if not candidates:
            sys.stdout.write(json.dumps({"count": 0, "source": {}}, ensure_ascii=False))
            sys.stdout.flush()
            return 0

        # Sort: blogs by published_dt ascending (oldest first), then courses
        candidates.sort(key=lambda c: (0 if c["kind"] == "blog" else 1, c["published_dt"]))

        # ---- Filter: keep only sources without active pending/draft rows ----
        # Fetch all (source_kind, source_slug) pairs that have pending/draft rows
        async with _db.async_session_factory() as db:
            existing = (
                await db.execute(
                    select(SocialPost.source_kind, SocialPost.source_slug)
                    .where(SocialPost.status.in_(["pending", "draft"]))
                    .distinct()
                )
            ).all()
        blocked: set[tuple[str, str]] = {(r.source_kind, r.source_slug) for r in existing}

        eligible = [c for c in candidates if (c["kind"], c["slug"]) not in blocked]

        if not eligible:
            sys.stdout.write(json.dumps({"count": 0, "source": {}}, ensure_ascii=False))
            sys.stdout.flush()
            return 0

        chosen = eligible[0]
        kind = chosen["kind"]
        slug = chosen["slug"]

        # ---- Build source payload -------------------------------------------
        source_payload: dict = {"kind": kind, "slug": slug}

        if kind == "blog":
            from app.services.blog_publisher import load_published
            full = load_published(slug)
            if not full:
                logger.warning("blog post %s disappeared before export", slug)
                sys.stdout.write(json.dumps({"count": 0, "source": {}}, ensure_ascii=False))
                sys.stdout.flush()
                return 0
            source_payload.update({
                "title": full.get("title", ""),
                "lede": full.get("lede", ""),
                "tags": full.get("tags", []),
                "url": f"/blog/{slug}",
            })
        else:
            from app.curriculum.loader import load_template
            tpl = load_template(slug)
            source_payload.update({
                "title": tpl.title,
                "tagline": tpl.goal,
                "description": tpl.goal,
                "tags": [tpl.level, f"{tpl.duration_months}mo"],
                "url": f"/roadmap/{slug}",
            })

        # ---- Insert 2 pending rows atomically ------------------------------
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        twitter_row = SocialPost(
            source_kind=kind,
            source_slug=slug,
            platform="twitter",
            status="pending",
            body=None,
            hashtags_json=None,
            reasoning_json=None,
            retry_count=0,
            published_url=None,
            created_at=now,
            updated_at=now,
        )
        linkedin_row = SocialPost(
            source_kind=kind,
            source_slug=slug,
            platform="linkedin",
            status="pending",
            body=None,
            hashtags_json=None,
            reasoning_json=None,
            retry_count=0,
            published_url=None,
            created_at=now,
            updated_at=now,
        )
        async with _db.async_session_factory() as db:
            db.add(twitter_row)
            db.add(linkedin_row)
            await db.flush()
            twitter_id = twitter_row.id
            linkedin_id = linkedin_row.id
            await db.commit()

        source_payload["twitter_post_id"] = twitter_id
        source_payload["linkedin_post_id"] = linkedin_id

        sys.stdout.write(json.dumps({"count": 1, "source": source_payload}, ensure_ascii=False))
        sys.stdout.flush()
        return 0

    finally:
        await _db.close_db()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
