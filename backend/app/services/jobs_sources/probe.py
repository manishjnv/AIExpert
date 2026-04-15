"""Source-board liveness probe.

Greenhouse / Lever / Ashby slugs decay silently — a company rebrands, drops
a board, or changes ATS, and our cron stops pulling without raising. This
module HEAD-checks every configured board and surfaces dead slugs to the
admin via JobSource.last_run_error, then disables boards that fail the
probe 3 runs in a row.

Called from the daily ingest (cheap — concurrent HEADs) and exposed via
`/admin/jobs/api/sources/probe` for on-demand checks.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Iterable

import httpx
from sqlalchemy import select

import app.db as _db
from app.models import JobSource
from app.services.jobs_sources.ashby import ASHBY_BOARDS
from app.services.jobs_sources.greenhouse import GREENHOUSE_BOARDS
from app.services.jobs_sources.lever import LEVER_BOARDS

logger = logging.getLogger("roadmap.jobs.probe")

# Use small, cheap GET requests (Ashby returns 405 on HEAD).
PROBES: dict[str, str] = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=false",
    "lever":      "https://api.lever.co/v0/postings/{slug}?mode=json&limit=1",
    "ashby":      "https://api.ashbyhq.com/posting-api/job-board/{slug}",
}

# Consecutive failed probes before we auto-disable a board so the daily
# ingest skips it. One bad day = no change. Three = the slug is genuinely
# dead and the admin should re-verify.
DISABLE_AFTER_FAILS = 3


async def _probe_one(source_key: str, kind: str, slug: str) -> tuple[str, bool, str]:
    url = PROBES[kind].format(slug=slug)
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, headers={"Accept": "application/json"})
        ok = resp.status_code == 200
        msg = "" if ok else f"HTTP {resp.status_code}"
        return source_key, ok, msg
    except Exception as exc:
        return source_key, False, f"{type(exc).__name__}: {exc}"[:120]


def _all_boards() -> Iterable[tuple[str, str, str]]:
    for slug, _ in GREENHOUSE_BOARDS:
        yield f"greenhouse:{slug}", "greenhouse", slug
    for slug, _ in LEVER_BOARDS:
        yield f"lever:{slug}", "lever", slug
    for slug, _ in ASHBY_BOARDS:
        yield f"ashby:{slug}", "ashby", slug


async def probe_all() -> dict[str, dict]:
    """Probe every configured board. Updates JobSource.last_run_error and
    auto-disables boards failing for DISABLE_AFTER_FAILS consecutive runs.
    Returns per-source status dict for callers/admin endpoint.
    """
    boards = list(_all_boards())
    results = await asyncio.gather(*[_probe_one(k, kind, slug) for k, kind, slug in boards])

    out: dict[str, dict] = {}
    async with _db.async_session_factory() as db:
        for source_key, ok, msg in results:
            src = (await db.execute(select(JobSource).where(JobSource.key == source_key))).scalar_one_or_none()
            if not src:
                out[source_key] = {"ok": ok, "msg": msg, "missing_row": True}
                continue
            # Track consecutive fail count in last_run_error JSON-tag prefix.
            # Format: "[fail_streak=N] HTTP 404"; 0 streak = no prefix.
            prev_streak = _parse_streak(src.last_run_error)
            if ok:
                src.last_run_error = None
                # Auto-re-enable if previously disabled by us (admin can still
                # manually disable; we don't override that — only re-enable if
                # the disable comment matches our marker).
                if not src.enabled and src.last_run_error and "[auto-disabled]" in (src.last_run_error or ""):
                    src.enabled = 1
                streak = 0
            else:
                streak = prev_streak + 1
                src.last_run_error = f"[fail_streak={streak}] {msg}"
                if streak >= DISABLE_AFTER_FAILS and src.enabled:
                    src.enabled = 0
                    src.last_run_error = f"[auto-disabled][fail_streak={streak}] {msg}"
                    logger.warning("auto-disabled source %s after %d failed probes",
                                   source_key, streak)
            out[source_key] = {"ok": ok, "msg": msg, "fail_streak": streak,
                               "enabled": bool(src.enabled)}
        await db.commit()
    return out


def _parse_streak(s: str | None) -> int:
    if not s:
        return 0
    import re
    m = re.search(r"\[fail_streak=(\d+)\]", s)
    return int(m.group(1)) if m else 0


async def is_disabled(source_key: str) -> bool:
    """Cheap helper for ingest fetchers — skip boards admin or probe disabled."""
    async with _db.async_session_factory() as db:
        src = (await db.execute(select(JobSource).where(JobSource.key == source_key))).scalar_one_or_none()
        return bool(src and not src.enabled)
