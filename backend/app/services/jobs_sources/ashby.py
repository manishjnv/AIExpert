"""Ashby source — public Job Board API.

Endpoint: https://api.ashbyhq.com/posting-api/job-board/<slug>?includeCompensation=true

Ashby is the default ATS for many AI-native startups founded since 2023.
Same per-board fail-isolation contract as greenhouse.py + lever.py.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable

import httpx

from app.services.jobs_sources import RawJob

logger = logging.getLogger("roadmap.jobs.ashby")

API = "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"

# Tier-1 verified AI/ML companies on Ashby. (board_slug, human_name).
# Slugs verified 2026-04-15. Re-verify quarterly.
ASHBY_BOARDS: list[tuple[str, str]] = [
    ("sarvam", "Sarvam AI"),         # India AI lab
    ("decagon", "Decagon"),
    ("dust", "Dust"),
    ("cohere", "Cohere"),
    ("runway", "Runway"),
    ("langchain", "LangChain"),
    ("replit", "Replit"),
    ("harvey", "Harvey"),
    ("notion", "Notion"),
]


async def fetch_board(board_slug: str, company_name: str) -> list[RawJob]:
    """Fetch all listed roles from one Ashby board. Never raises."""
    url = API.format(slug=board_slug)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers={"Accept": "application/json"})
            if resp.status_code != 200:
                logger.warning("ashby %s returned %d", board_slug, resp.status_code)
                return []
            payload = resp.json()
    except Exception as exc:
        logger.exception("ashby %s fetch failed: %s", board_slug, exc)
        return []

    jobs = payload.get("jobs") or []
    out: list[RawJob] = []
    for j in jobs:
        # Ashby returns hidden roles (test postings, internal) with isListed=false.
        if j.get("isListed") is False:
            continue
        try:
            out.append(_normalize(j, board_slug, company_name))
        except Exception as exc:
            logger.warning("ashby %s: skipping job %s: %s", board_slug, j.get("id"), exc)
    return out


def _normalize(j: dict, board_slug: str, company_name: str) -> RawJob:
    job_id = str(j["id"])
    posted_on = _iso_date(j.get("publishedAt") or "")

    # Prefer the explicit address city/region when present, fall back to the
    # free-text `location` string Ashby renders on the job card.
    addr = j.get("address") or {}
    addr_parts = [addr.get("postalAddress", {}).get("addressLocality"),
                  addr.get("postalAddress", {}).get("addressRegion"),
                  addr.get("postalAddress", {}).get("addressCountry")]
    addr_str = ", ".join(p for p in addr_parts if p)
    location = addr_str or (j.get("location") or "").strip()

    return RawJob(
        external_id=job_id,
        source_url=j.get("jobUrl") or j.get("applyUrl") or "",
        title_raw=(j.get("title") or "").strip(),
        company=company_name,
        company_slug=board_slug,
        location_raw=location,
        jd_html=j.get("descriptionHtml") or "",
        posted_on=posted_on,
        extra={
            "department": j.get("department"),
            "team": j.get("team"),
            "employment_type": j.get("employmentType"),
            "is_remote": j.get("isRemote"),
            "secondary_locations": [
                (loc.get("location") or "") for loc in (j.get("secondaryLocations") or [])
            ],
        },
    )


def _iso_date(s: str) -> str:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date().isoformat()
    except Exception:
        return datetime.utcnow().date().isoformat()


async def fetch_all() -> Iterable[tuple[str, RawJob]]:
    """Yield (source_key, RawJob) pairs across every Ashby board."""
    for board_slug, company_name in ASHBY_BOARDS:
        source_key = f"ashby:{board_slug}"
        rows = await fetch_board(board_slug, company_name)
        logger.info("ashby %s: fetched %d jobs", board_slug, len(rows))
        for r in rows:
            yield source_key, r
