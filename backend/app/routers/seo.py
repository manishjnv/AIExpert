"""SEO sub-sitemaps (SEO-02). One child per resource class, referenced
from /sitemap_index.xml. Keeps per-resource <lastmod> clean.

Routes here:
  GET /sitemap-blog.xml      — /blog + /blog/{slug} with <image:image>
  GET /sitemap-pages.xml     — /, /jobs, /leaderboard, /verify
  GET /sitemap-certs.xml     — /verify/{credential_id} for non-revoked certs
  GET /sitemap-profiles.xml  — /profile/{user_id} for public_profile=True users

/sitemap-jobs.xml + /sitemap_index.xml remain in routers/jobs.py (their
existing home). Image extensions on sitemap-jobs.xml are added there.

Profile sitemap strictly gates on User.public_profile=True — regression
pytest in test_seo_sitemaps.py enforces this (SEO-02 acceptance #5).
"""

from __future__ import annotations

from datetime import date, datetime
from html import escape as _html_esc

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models.certificate import Certificate
from app.models.user import User
from app.routers.blog import POST_01_PUBLISHED
from app.services.blog_publisher import list_published

router = APIRouter()


def _esc(s: str) -> str:
    return _html_esc(s or "", quote=True)


_CACHE_1H = {"Cache-Control": "public, max-age=3600"}
_URLSET_OPEN = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
    ' xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">'
)


def _xml(urls: list[str]) -> str:
    return _URLSET_OPEN + "".join(urls) + "</urlset>"


def _url(loc: str, lastmod: str, priority: float,
         image: str | None = None) -> str:
    img = (f"<image:image><image:loc>{_esc(image)}</image:loc></image:image>"
           if image else "")
    return (f"<url><loc>{_esc(loc)}</loc>"
            f"<lastmod>{_esc(lastmod)}</lastmod>"
            f"<priority>{priority:.1f}</priority>{img}</url>")


@router.api_route("/sitemap-blog.xml", methods=["GET", "HEAD"])
async def sitemap_blog() -> Response:
    settings = get_settings()
    base = (settings.public_base_url or "").rstrip("/")
    today = date.today().isoformat()
    urls: list[str] = [
        # /blog index
        _url(f"{base}/blog", today, 0.7),
        # Hardcoded POST_01
        _url(f"{base}/blog/01", POST_01_PUBLISHED, 0.8,
             image=f"{base}/og/blog/01.png"),
    ]
    for post in list_published():
        slug = post.get("slug") or ""
        if not slug:
            continue
        lastmod = post.get("published") or today
        urls.append(_url(f"{base}/blog/{slug}", lastmod, 0.8,
                         image=f"{base}/og/blog/{slug}.png"))
    return Response(content=_xml(urls), media_type="application/xml",
                    headers=_CACHE_1H)


@router.api_route("/sitemap-pages.xml", methods=["GET", "HEAD"])
async def sitemap_pages(db: AsyncSession = Depends(get_db)) -> Response:
    settings = get_settings()
    base = (settings.public_base_url or "").rstrip("/")
    today = date.today().isoformat()
    # Home + high-traffic hubs. No /account (noindex), no /admin (disallow).
    urls = [
        _url(f"{base}/", today, 1.0, image=f"{base}/og/course/generalist.png"),
        _url(f"{base}/jobs", today, 0.9),
        _url(f"{base}/leaderboard", today, 0.6),
        _url(f"{base}/verify", today, 0.5),
    ]
    # SEO-10: include paginated /jobs?page=N for Googlebot discovery.
    # Single count query → same page-size constant the hub uses.
    from sqlalchemy import func as _func
    from app.models.job import Job as _Job
    from app.routers.jobs import JOBS_PAGE_SIZE
    total = (await db.execute(
        select(_func.count(_Job.id)).where(_Job.status == "published")
    )).scalar_one()
    total_pages = max(1, (total + JOBS_PAGE_SIZE - 1) // JOBS_PAGE_SIZE)
    for p in range(2, total_pages + 1):
        urls.append(_url(f"{base}/jobs?page={p}", today, 0.6))
    # SEO-19: include /vs index + every /vs/{slug} comparison page.
    from app.routers.compare import all_slugs as _vs_slugs
    urls.append(_url(f"{base}/vs", today, 0.7))
    for s in _vs_slugs():
        urls.append(_url(f"{base}/vs/{s}", today, 0.8))
    return Response(content=_xml(urls), media_type="application/xml",
                    headers=_CACHE_1H)


@router.api_route("/sitemap-certs.xml", methods=["GET", "HEAD"])
async def sitemap_certs(db: AsyncSession = Depends(get_db)) -> Response:
    settings = get_settings()
    base = (settings.public_base_url or "").rstrip("/")
    stmt = (select(Certificate)
            .where(Certificate.revoked_at.is_(None))
            .order_by(Certificate.issued_at.desc())
            .limit(10000))
    rows = (await db.execute(stmt)).scalars().all()
    urls: list[str] = []
    for c in rows:
        lastmod = (c.issued_at or datetime.utcnow()).date().isoformat()
        urls.append(_url(f"{base}/verify/{c.credential_id}", lastmod, 0.7))
    return Response(content=_xml(urls), media_type="application/xml",
                    headers=_CACHE_1H)


@router.api_route("/sitemap-profiles.xml", methods=["GET", "HEAD"])
async def sitemap_profiles(db: AsyncSession = Depends(get_db)) -> Response:
    """Only users with public_profile=True appear here.

    SEO-02 acceptance #5: regression test asserts no public_profile=False
    user is ever emitted. Strictly filtered at the DB layer; no post-
    filter fallback.
    """
    settings = get_settings()
    base = (settings.public_base_url or "").rstrip("/")
    stmt = (select(User)
            .where(User.public_profile.is_(True))
            .order_by(User.updated_at.desc())
            .limit(10000))
    rows = (await db.execute(stmt)).scalars().all()
    urls: list[str] = []
    for u in rows:
        lastmod = (u.updated_at or datetime.utcnow()).date().isoformat()
        urls.append(_url(f"{base}/profile/{u.id}", lastmod, 0.5))
    return Response(content=_xml(urls), media_type="application/xml",
                    headers=_CACHE_1H)
