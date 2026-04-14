"""Jobs ingestion sources.

Each source module exposes `async def fetch(source_key: str) -> list[RawJob]`
that returns normalized `RawJob` dicts. See docs/JOBS.md §4-5.
"""

from __future__ import annotations

from typing import Any, TypedDict


class RawJob(TypedDict):
    """Normalized pre-enrichment job payload, common across all sources."""

    external_id: str            # source-stable id
    source_url: str             # ATS apply URL
    title_raw: str              # raw title from source
    company: str                # human-readable company name
    company_slug: str           # stable slug (lowercase, hyphens)
    location_raw: str           # free-text location string
    jd_html: str                # full JD HTML/text (bleach-cleaned later)
    posted_on: str              # ISO date YYYY-MM-DD
    extra: dict[str, Any]       # anything source-specific (team, department, etc.)
