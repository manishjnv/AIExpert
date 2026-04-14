"""Greenhouse source — public Job Board API.

Endpoint: https://boards-api.greenhouse.io/v1/boards/<slug>/jobs?content=true

Tier-1 allowlist of AI/ML-native companies. Adding a company = append to
GREENHOUSE_BOARDS, redeploy. Admin CRUD moved to Step 11 per docs/JOBS.md §12.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable

import httpx

from app.services.jobs_sources import RawJob

logger = logging.getLogger("roadmap.jobs.greenhouse")

API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"

# Tier-1 verified AI/ML companies using Greenhouse ATS.
# (board_slug, human_name). board_slug is the path segment in Greenhouse URLs.
GREENHOUSE_BOARDS: list[tuple[str, str]] = [
    ("anthropic", "Anthropic"),
    ("scaleai", "Scale AI"),
    ("huggingface", "Hugging Face"),
    ("cohere", "Cohere"),
    ("databricks", "Databricks"),
    ("perplexityai", "Perplexity"),
    ("runwayml", "Runway"),
    ("character", "Character.AI"),
    ("anyscale", "Anyscale"),
    ("weightsandbiases", "Weights & Biases"),
]


async def fetch_board(board_slug: str, company_name: str) -> list[RawJob]:
    """Fetch all open roles from one Greenhouse board. Never raises — returns []
    on any failure (isolated per board, logged for admin).
    """
    url = API.format(slug=board_slug)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers={"Accept": "application/json"})
            if resp.status_code != 200:
                logger.warning("greenhouse %s returned %d", board_slug, resp.status_code)
                return []
            payload = resp.json()
    except Exception as exc:  # network, JSON, etc.
        logger.exception("greenhouse %s fetch failed: %s", board_slug, exc)
        return []

    jobs = payload.get("jobs") or []
    out: list[RawJob] = []
    for j in jobs:
        try:
            out.append(_normalize(j, board_slug, company_name))
        except Exception as exc:
            logger.warning("greenhouse %s: skipping job %s: %s", board_slug, j.get("id"), exc)
    return out


def _normalize(j: dict, board_slug: str, company_name: str) -> RawJob:
    gh_id = str(j["id"])
    updated = j.get("updated_at") or j.get("first_published") or datetime.utcnow().isoformat()
    posted_on = _iso_date(updated)
    location = (j.get("location") or {}).get("name") or ""
    content_html = j.get("content") or ""
    # Greenhouse returns HTML-escaped entities in `content` — unescape once.
    if "&lt;" in content_html or "&amp;" in content_html:
        import html as _html
        content_html = _html.unescape(content_html)

    return RawJob(
        external_id=gh_id,
        source_url=j.get("absolute_url", ""),
        title_raw=(j.get("title") or "").strip(),
        company=company_name,
        company_slug=board_slug,
        location_raw=location.strip(),
        jd_html=content_html,
        posted_on=posted_on,
        extra={
            "departments": [d.get("name") for d in (j.get("departments") or []) if d.get("name")],
            "offices": [o.get("name") for o in (j.get("offices") or []) if o.get("name")],
            "internal_job_id": j.get("internal_job_id"),
        },
    )


def _iso_date(s: str) -> str:
    # Greenhouse timestamps look like "2024-03-12T14:09:07-04:00".
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date().isoformat()
    except Exception:
        return datetime.utcnow().date().isoformat()


async def fetch_all() -> Iterable[tuple[str, RawJob]]:
    """Yield (source_key, RawJob) pairs across every enabled board."""
    for board_slug, company_name in GREENHOUSE_BOARDS:
        source_key = f"greenhouse:{board_slug}"
        rows = await fetch_board(board_slug, company_name)
        logger.info("greenhouse %s: fetched %d jobs", board_slug, len(rows))
        for r in rows:
            yield source_key, r
