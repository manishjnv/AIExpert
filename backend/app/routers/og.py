"""OG image routes (SEO-11). Dynamic per-slug 1200x630 PNGs for social share.

Routes:
  GET /og/course/generalist.png
  GET /og/roadmap/{track}.png         (track ∈ generalist|ai-engineer|ml-engineer|data-scientist)
  GET /og/blog/{slug}.png
  GET /og/jobs/{slug}.png

Disk cache at /data/og-cache/{type}/{id}.png. First request renders and
writes; subsequent requests serve from disk. No automatic TTL — callers
or admin can rm the cache file to force a regeneration.

/og/ is Disallowed in robots.txt — images are surfaced via og:image meta
on actual pages, not as crawlable URLs.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.job import Job
from app.services import og_render
from app.services.blog_publisher import is_legacy_hidden, list_published

router = APIRouter()

CACHE_ROOT = Path("/data/og-cache")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,120}$")
_CACHE_HEADERS = {"Cache-Control": "public, max-age=86400"}


def _cache_path(kind: str, ident: str) -> Path:
    return CACHE_ROOT / kind / f"{ident}.png"


def _from_cache(kind: str, ident: str) -> Response | None:
    p = _cache_path(kind, ident)
    if p.exists():
        return Response(content=p.read_bytes(), media_type="image/png",
                        headers={**_CACHE_HEADERS, "X-Cache": "HIT"})
    return None


def _serve_and_cache(kind: str, ident: str, body: bytes) -> Response:
    p = _cache_path(kind, ident)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
    except OSError:
        # Non-fatal — /data may be read-only on dev or tests. Still serve body.
        pass
    return Response(content=body, media_type="image/png",
                    headers={**_CACHE_HEADERS, "X-Cache": "MISS"})


@router.get("/og/course/{name}.png")
async def og_course(name: str) -> Response:
    if name != "generalist":
        raise HTTPException(404, "not found")
    cached = _from_cache("course", name)
    if cached:
        return cached
    return _serve_and_cache("course", name, og_render.render_course())


@router.get("/og/roadmap/{track}.png")
async def og_roadmap(track: str) -> Response:
    body = og_render.render_roadmap(track)
    if body is None:
        raise HTTPException(404, "not found")
    cached = _from_cache("roadmap", track)
    if cached:
        return cached
    return _serve_and_cache("roadmap", track, body)


@router.get("/og/blog/{slug}.png")
async def og_blog(slug: str) -> Response:
    if not _SLUG_RE.match(slug):
        raise HTTPException(404, "not found")
    # Hardcoded post-01 — title lives in routers/blog.py
    if slug in ("01", "01-building-automateedge-solo"):
        from app.routers.blog import (
            POST_01_TITLE, POST_01_PUBLISHED,
        )
        cached = _from_cache("blog", slug)
        if cached:
            return cached
        body = og_render.render_blog(POST_01_TITLE, POST_01_PUBLISHED, "Manish Kumar")
        return _serve_and_cache("blog", slug, body)
    # Dynamic posts from the publisher
    if is_legacy_hidden(slug):
        raise HTTPException(404, "not found")
    posts = list_published()
    match = next((p for p in posts if p.get("slug") == slug), None)
    if not match:
        raise HTTPException(404, "not found")
    cached = _from_cache("blog", slug)
    if cached:
        return cached
    body = og_render.render_blog(
        match.get("title", "AutomateEdge Blog"),
        match.get("published", ""),
        match.get("last_reviewed_by") or "AutomateEdge",
    )
    return _serve_and_cache("blog", slug, body)


@router.get("/og/jobs/{slug}.png")
async def og_jobs(slug: str, db: AsyncSession = Depends(get_db)) -> Response:
    if not _SLUG_RE.match(slug):
        raise HTTPException(404, "not found")
    job = (await db.execute(
        select(Job).where(Job.slug == slug, Job.status == "published")
    )).scalar_one_or_none()
    if job is None:
        raise HTTPException(404, "not found")

    d = job.data or {}
    company = (d.get("company") or {}).get("name") or job.company_slug
    loc = d.get("location") or {}
    loc_str = " · ".join(filter(None, [
        loc.get("city"), loc.get("country"), loc.get("remote_policy"),
    ]))
    emp = d.get("employment") or {}
    salary = emp.get("salary") or {}
    salary_label = ""
    if salary.get("disclosed") and salary.get("currency"):
        mn, mx, cur = salary.get("min"), salary.get("max"), salary.get("currency")
        if mn and mx:
            salary_label = f"{cur} {mn:,}–{mx:,}"
        elif mn:
            salary_label = f"{cur} {mn:,}+"
        elif mx:
            salary_label = f"up to {cur} {mx:,}"

    cached = _from_cache("jobs", slug)
    if cached:
        return cached
    body = og_render.render_jobs(
        role=job.title or "AI Role",
        company=company,
        location=loc_str,
        salary=salary_label,
    )
    return _serve_and_cache("jobs", slug, body)
