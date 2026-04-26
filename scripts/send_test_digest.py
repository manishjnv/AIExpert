"""Send the combined weekly digest to a single user — manual test entrypoint.

Usage:
    # Real send via SMTP (requires SMTP_HOST configured in env)
    docker compose exec backend python -m scripts.send_test_digest user@example.com

    # Dry-run: compose the email but skip the SMTP send. Writes HTML to stdout.
    docker compose exec backend python -m scripts.send_test_digest user@example.com --dry-run > /tmp/preview.html

The script composes exactly what the Mon-AM cron would send for this user,
honoring their per-channel notify_* toggles. Empty sections (channel on but
no content) drop silently — same behavior as the production cron.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys


async def _main(email: str, dry_run: bool) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    from sqlalchemy import select

    from app.config import get_settings
    from app.db import async_session_factory, close_db, init_db
    from app.models.user import User
    from app.services.jobs_digest import _recent_published_jobs
    from app.services.weekly_digest import (
        _compose_email,
        _recent_blog_posts,
        _recent_courses,
        _send,
        _send_user_digest,
        _unsub_token,
        _blog_section,
        _courses_section,
        _jobs_section,
        _roadmap_section,
    )

    settings = get_settings()
    base_url = (settings.public_base_url or "https://automateedge.cloud").rstrip("/")

    await init_db()
    try:
        async with async_session_factory() as db:
            user = (await db.execute(
                select(User).where(User.email == email)
            )).scalar_one_or_none()
            if user is None:
                print(f"ERROR: no user found with email {email}", file=sys.stderr)
                return 2

            print(
                f"User: id={user.id} email={user.email} name={user.name!r}\n"
                f"  notify_jobs={user.notify_jobs} notify_roadmap={user.notify_roadmap} "
                f"notify_blog={user.notify_blog} notify_new_courses={user.notify_new_courses}",
                file=sys.stderr,
            )

            recent_posts = _recent_blog_posts()
            recent_courses_list = _recent_courses()
            jobs_pool = await _recent_published_jobs(db)
            print(
                f"  recent_posts={len(recent_posts)} recent_courses={len(recent_courses_list)} "
                f"jobs_pool={len(jobs_pool)}",
                file=sys.stderr,
            )

            if dry_run:
                # Build sections + compose, but write HTML to stdout instead
                # of sending. Mirrors _send_user_digest's logic.
                sections: list[dict] = []
                channels: list[str] = []
                if user.notify_roadmap:
                    channels.append("roadmap")
                    s = await _roadmap_section(user, db)
                    if s:
                        sections.append(s)
                if user.notify_new_courses:
                    channels.append("new_courses")
                    s = _courses_section(recent_courses_list)
                    if s:
                        sections.append(s)
                if user.notify_jobs:
                    channels.append("jobs")
                    if jobs_pool:
                        s = await _jobs_section(user, jobs_pool, db)
                        if s:
                            sections.append(s)
                if user.notify_blog:
                    channels.append("blog")
                    s = _blog_section(recent_posts)
                    if s:
                        sections.append(s)

                if not sections:
                    print(f"NO SECTIONS RENDERED for {email} — would skip", file=sys.stderr)
                    return 0

                tokens = {
                    "jobs": _unsub_token(user, "jobs"),
                    "roadmap": _unsub_token(user, "roadmap"),
                    "blog": _unsub_token(user, "blog"),
                    "new_courses": _unsub_token(user, "new_courses"),
                    "all": _unsub_token(user),
                }
                subject, _text, html = _compose_email(
                    sections, user, base_url, tokens, subscribed_channels=channels,
                )
                print(f"DRY RUN — Subject: {subject}", file=sys.stderr)
                print(f"DRY RUN — Section count: {len(sections)}", file=sys.stderr)
                # HTML to stdout for capture/preview
                sys.stdout.write(html)
                return 0

            sent, status = await _send_user_digest(
                user, db,
                recent_posts=recent_posts,
                recent_courses_list=recent_courses_list,
                jobs_pool=jobs_pool,
                base_url=base_url,
            )
            if sent:
                print(f"SENT to {email}", file=sys.stderr)
                return 0
            print(f"NOT SENT — status={status}", file=sys.stderr)
            return 1
    finally:
        await close_db()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("email", help="Recipient email (must exist in users table)")
    p.add_argument("--dry-run", action="store_true",
                   help="Compose only; write HTML to stdout, skip SMTP send")
    args = p.parse_args()
    return asyncio.run(_main(args.email, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
