"""Workday source — public CXS Job Board API.

Workday powers most large enterprises (Broadcom, Adobe, Salesforce, NVIDIA, …),
nearly all of which run mixed boards where AI/ML roles are a minority. Unlike
Greenhouse/Lever/Ashby a single slug is not enough: each board is identified by
a tenant subdomain + a CXS tenant id + a site path. We keep ``WORKDAY_BOARDS``
shape-compatible with the other providers (``(slug, company_name)``) so the
ingest registry + probe loops iterate it uniformly, and hold the connection
details (tenant / site / country filter) in ``_BOARDS_CONFIG`` keyed by the
same slug.

Endpoints (no auth, public):
  list   POST  https://{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
  detail GET   https://{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{externalPath}

The list response only carries title + location + req-id; the full JD, real
post date, and apply URL live on the per-posting detail call, so each board is
list-then-detail (one detail GET per posting we keep).

Workday exposes no stable country-level facet, but the ``locations`` facet
labels carry the ISO country prefix ("IND-…", "India-…"). We read the facet
list on the first call, collect the matching location IDs, and apply them
server-side so we only ever fetch the target-country postings — never the
company's entire global board. Same per-board fail-isolation contract as
greenhouse.py / lever.py / ashby.py: never raises up to the orchestrator.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable

import httpx

from app.services.jobs_sources import RawJob

logger = logging.getLogger("roadmap.jobs.workday")

# slug -> (host_subdomain, cxs_tenant, site, country_label_prefixes)
#   host_subdomain  : the "<tenant>.wdNN" portion of <host>.myworkdayjobs.com
#   cxs_tenant      : the tenant id in the /wday/cxs/<tenant>/ path
#                     (usually the host_subdomain minus its ".wdNN" suffix)
#   site            : the job-board site path segment
#   country_prefixes: location-facet label prefixes to keep; () = no geo filter
# Verified live against api 2026-05-31. Re-verify quarterly — enterprises
# rebrand, change Workday sites, or migrate ATS providers.
_BOARDS_CONFIG: dict[str, tuple[str, str, str, tuple[str, ...]]] = {
    "broadcom": ("broadcom.wd1", "broadcom", "External_Career", ("IND-", "India")),
}

# (board_slug, human_name) — kept shape-compatible with the other providers.
WORKDAY_BOARDS: list[tuple[str, str]] = [
    ("broadcom", "Broadcom"),
]

_LIST_LIMIT = 20    # Workday's default/maximum page size for the CXS endpoint
_MAX_PAGES = 60     # safety cap: 60 * 20 = 1200 postings/board/run
_TIMEOUT = 20.0


def _base_url(host: str, tenant: str, site: str) -> str:
    return f"https://{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"


def probe_url(slug: str) -> str | None:
    """Liveness URL for the probe — the public site landing page (GET 200).

    The CXS ``/jobs`` endpoint is POST-only (GET → 400), so the probe (which is
    GET-based) targets the human site page instead; it returns 200 to a plain
    GET with ``Accept: application/json``.
    """
    cfg = _BOARDS_CONFIG.get(slug)
    if not cfg:
        return None
    host, _tenant, site, _prefixes = cfg
    return f"https://{host}.myworkdayjobs.com/{site}"


def _collect_country_location_ids(facets: list, prefixes: tuple[str, ...]) -> list[str]:
    """Walk the facet tree and return ``locations`` facet IDs whose label starts
    with any country prefix. Workday nests the ``locations`` facet under a
    ``locationMainGroup`` parent, so we recurse rather than assume depth."""
    ids: list[str] = []

    def walk(values: list) -> None:
        for v in values:
            if v.get("facetParameter") == "locations":
                for vv in v.get("values", []):
                    desc = vv.get("descriptor") or ""
                    if vv.get("id") and any(desc.startswith(p) for p in prefixes):
                        ids.append(vv["id"])
            if v.get("values"):
                walk(v["values"])

    for f in facets or []:
        walk([f])
    return ids


async def _resolve_location_facets(
    client: httpx.AsyncClient, base: str, prefixes: tuple[str, ...]
) -> dict | None:
    """Return an ``appliedFacets`` dict scoping the search to the target country,
    or ``None`` when a country filter is configured but no matching locations
    were found.

    The ``None`` case is a deliberate safety guard: fetching with empty facets
    would pull the company's ENTIRE global board into what is meant to be a
    country-scoped feed. Returning ``None`` makes the caller fetch nothing and
    surfaces the miss in the logs instead.
    """
    if not prefixes:
        return {}
    resp = await client.post(
        f"{base}/jobs",
        json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""},
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    if resp.status_code != 200:
        logger.warning("workday facet probe %s returned %d", base, resp.status_code)
        return None
    ids = _collect_country_location_ids(resp.json().get("facets", []), prefixes)
    if not ids:
        logger.warning(
            "workday %s: no location facets matched %s — skipping board this run",
            base, prefixes,
        )
        return None
    return {"locations": ids}


async def _list_postings(
    client: httpx.AsyncClient, base: str, applied: dict
) -> list[dict]:
    """Page through the CXS list endpoint until exhausted or the safety cap."""
    out: list[dict] = []
    offset = 0
    for _ in range(_MAX_PAGES):
        resp = await client.post(
            f"{base}/jobs",
            json={"appliedFacets": applied, "limit": _LIST_LIMIT,
                  "offset": offset, "searchText": ""},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        if resp.status_code != 200:
            logger.warning("workday list %s offset=%d returned %d", base, offset, resp.status_code)
            break
        payload = resp.json()
        batch = payload.get("jobPostings") or []
        if not batch:
            break
        out.extend(batch)
        offset += _LIST_LIMIT
        if offset >= (payload.get("total") or 0):
            break
    return out


def _matches_country(location: str, country: str | None, prefixes: tuple[str, ...]) -> bool:
    """Belt-and-suspenders confirmation that a posting is in the target country.

    The server-side location facet already scopes results, but multi-location
    postings or facet drift could bleed a foreign role through. Keep the posting
    only if its location label starts with a country prefix OR its explicit
    country descriptor matches a prefix root ("India" from "India" / "IND-")."""
    if not prefixes:
        return True
    loc = location or ""
    if any(loc.startswith(p) for p in prefixes):
        return True
    c = (country or "").strip().lower()
    return any(c and c == p.rstrip("-").lower() for p in prefixes)


async def _fetch_detail(
    client: httpx.AsyncClient, base: str, posting: dict, prefixes: tuple[str, ...]
) -> RawJob | None:
    ext_path = posting.get("externalPath") or ""
    if not ext_path:
        return None
    resp = await client.get(f"{base}{ext_path}", headers={"Accept": "application/json"})
    if resp.status_code != 200:
        logger.warning("workday detail %s returned %d", ext_path, resp.status_code)
        return None
    info = resp.json().get("jobPostingInfo") or {}

    country_obj = info.get("country")
    country = country_obj.get("descriptor") if isinstance(country_obj, dict) else country_obj
    location = (info.get("location") or "").strip()

    if not _matches_country(location, country, prefixes):
        logger.debug("workday: dropping out-of-country posting %s (%s)", ext_path, location)
        return None

    external_id = str(info.get("jobReqId") or "").strip()
    if not external_id:
        bullets = posting.get("bulletFields") or []
        external_id = str(bullets[0]) if bullets else ext_path

    # `externalUrl` is the authoritative public apply URL (present on every row
    # observed). Fallback rebuilds it as https://<host>/<site><externalPath>.
    root, _, tail = base.partition("/wday/cxs/")          # root = https://<host>
    site = tail.split("/", 1)[1] if "/" in tail else tail  # <tenant>/<site> -> <site>
    source_url = info.get("externalUrl") or f"{root}/{site}{ext_path}"

    return RawJob(
        external_id=external_id,
        source_url=source_url,
        title_raw=(info.get("title") or posting.get("title") or "").strip(),
        company="",  # set by caller (company_name not in scope here)
        company_slug="",
        location_raw=location,
        jd_html=info.get("jobDescription") or "",
        posted_on=_iso_date(info.get("startDate") or info.get("postedOn") or ""),
        extra={
            "job_req_id": info.get("jobReqId"),
            "time_type": info.get("timeType"),
            "country": country,
            "remote_type": info.get("remoteType"),
        },
    )


def _iso_date(s: str) -> str:
    # Workday detail `startDate` is already "YYYY-MM-DD"; guard anyway.
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date().isoformat()
    except Exception:
        return datetime.utcnow().date().isoformat()


async def fetch_board(slug: str, company_name: str) -> list[RawJob]:
    """Fetch all in-scope roles from one Workday board. Never raises — returns []
    on any failure (isolated per board, logged for admin)."""
    cfg = _BOARDS_CONFIG.get(slug)
    if not cfg:
        logger.warning("workday: no _BOARDS_CONFIG entry for slug %s", slug)
        return []
    host, tenant, site, prefixes = cfg
    base = _base_url(host, tenant, site)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            applied = await _resolve_location_facets(client, base, prefixes)
            if applied is None:
                return []
            postings = await _list_postings(client, base, applied)
            out: list[RawJob] = []
            for p in postings:
                try:
                    job = await _fetch_detail(client, base, p, prefixes)
                except Exception as exc:
                    logger.warning("workday %s: skipping posting %s: %s",
                                   slug, p.get("externalPath"), exc)
                    continue
                if job is not None:
                    job["company"] = company_name
                    job["company_slug"] = slug
                    out.append(job)
            return out
    except Exception as exc:  # network, JSON, etc.
        logger.exception("workday %s fetch failed: %s", slug, exc)
        return []


async def fetch_all() -> Iterable[tuple[str, RawJob]]:
    """Yield (source_key, RawJob) pairs across every Workday board."""
    for slug, company_name in WORKDAY_BOARDS:
        source_key = f"workday:{slug}"
        rows = await fetch_board(slug, company_name)
        logger.info("workday %s: fetched %d jobs", slug, len(rows))
        for r in rows:
            yield source_key, r
