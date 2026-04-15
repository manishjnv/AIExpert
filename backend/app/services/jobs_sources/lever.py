"""Lever source — public Postings API.

Endpoint: https://api.lever.co/v0/postings/<slug>?mode=json

Tier-1 AI/ML companies on Lever. Same contract as greenhouse.py: fail per-board,
never raise up to the orchestrator.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable

import httpx

from app.services.jobs_sources import RawJob

logger = logging.getLogger("roadmap.jobs.lever")

API = "https://api.lever.co/v0/postings/{slug}?mode=json"

# (board_slug, human_name). board_slug = path segment in jobs.lever.co/<slug>.
# Verified against api.lever.co 2026-04-14. Re-verify quarterly.
# Removed (404s as of 2026-04-14): elevenlabs, pika, luma-ai, contextual —
#   investigate before re-adding (may have moved to Ashby/Greenhouse).
LEVER_BOARDS: list[tuple[str, str]] = [
    ("mistral", "Mistral AI"),
    # India-focused additions (verified 2026-04-15).
    ("cred", "CRED"),
    ("mindtickle", "Mindtickle"),
]


async def fetch_board(board_slug: str, company_name: str) -> list[RawJob]:
    url = API.format(slug=board_slug)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers={"Accept": "application/json"})
            if resp.status_code != 200:
                logger.warning("lever %s returned %d", board_slug, resp.status_code)
                return []
            payload = resp.json()
    except Exception as exc:
        logger.exception("lever %s fetch failed: %s", board_slug, exc)
        return []

    out: list[RawJob] = []
    for p in payload or []:
        try:
            out.append(_normalize(p, board_slug, company_name))
        except Exception as exc:
            logger.warning("lever %s: skipping post %s: %s", board_slug, p.get("id"), exc)
    return out


def _normalize(p: dict, board_slug: str, company_name: str) -> RawJob:
    post_id = str(p["id"])
    created_ms = p.get("createdAt") or 0  # Lever returns epoch ms.
    try:
        posted_on = datetime.utcfromtimestamp(int(created_ms) / 1000).date().isoformat()
    except Exception:
        posted_on = datetime.utcnow().date().isoformat()

    categories = p.get("categories") or {}
    location = categories.get("location") or ""
    # Lever `descriptionPlain` is text; `description` is HTML. Prefer HTML.
    jd_html = p.get("description") or p.get("descriptionPlain") or ""
    # Append additional lists (requirements/lists section) if present.
    for section in p.get("lists") or []:
        text = section.get("text") or ""
        content = section.get("content") or ""
        if text or content:
            jd_html += f"<h3>{text}</h3>{content}"

    return RawJob(
        external_id=post_id,
        source_url=p.get("hostedUrl") or p.get("applyUrl", ""),
        title_raw=(p.get("text") or "").strip(),
        company=company_name,
        company_slug=board_slug,
        location_raw=location.strip(),
        jd_html=jd_html,
        posted_on=posted_on,
        extra={
            "team": categories.get("team"),
            "commitment": categories.get("commitment"),
            "department": categories.get("department"),
        },
    )


async def fetch_all() -> Iterable[tuple[str, RawJob]]:
    for board_slug, company_name in LEVER_BOARDS:
        source_key = f"lever:{board_slug}"
        rows = await fetch_board(board_slug, company_name)
        logger.info("lever %s: fetched %d jobs", board_slug, len(rows))
        for r in rows:
            yield source_key, r
