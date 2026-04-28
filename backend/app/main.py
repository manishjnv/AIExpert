"""
FastAPI application factory and entrypoint.

This is the minimal skeleton for Phase 1 of TASKS.md. Claude Code will
extend this incrementally as phases progress:
  - Phase 2 adds DB session middleware and the learner-count wire-up
  - Phase 3 adds auth routers
  - Phase 4+ adds the rest

Do not put business logic in this file. Put it in services/ and routers/.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from sqlalchemy import func, select

from app.config import get_settings
import app.db as db_module
from app.db import close_db, init_db
from app.models.user import User

logger = logging.getLogger("roadmap")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

# Strip API keys from any log record before it hits handlers. Must run
# BEFORE any provider client is constructed so early init logs are covered.
from app.logging_redact import install_redacting_filter  # noqa: E402
install_redacting_filter()

# Map HTTP status codes to API_SPEC error slugs
_STATUS_SLUGS = {
    400: "invalid_input",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    429: "rate_limited",
}

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs on app startup and shutdown."""
    logger.info("Starting AI Roadmap Platform backend (env=%s)", settings.env)
    await init_db()
    from app.auth.google import register_google_oauth
    register_google_oauth()

    # Start background cleanup tasks. The Monday weekly digest is now owned
    # by scripts/scheduler.py (cron container), not the backend lifespan —
    # see services/cleanup.py for the rationale.
    import asyncio
    from app.services.cleanup import cleanup_expired_otps, cleanup_expired_sessions
    from app.services.pipeline_scheduler import pipeline_scheduler
    import app.db as _db
    otp_task = asyncio.create_task(cleanup_expired_otps(_db.async_session_factory))
    session_task = asyncio.create_task(cleanup_expired_sessions(_db.async_session_factory))
    pipeline_task = asyncio.create_task(pipeline_scheduler(_db.async_session_factory))

    yield

    # Cancel cleanup tasks
    otp_task.cancel()
    session_task.cancel()
    pipeline_task.cancel()
    logger.info("Shutting down")
    await close_db()


app = FastAPI(
    title="AI Roadmap Platform",
    description="Self-hosted AI learning roadmap with progress tracking, AI eval, and quarterly curriculum refresh.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs" if settings.env == "dev" else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if settings.env == "dev" else None,
)

# ----- Rate limiter -----
limiter = Limiter(key_func=get_remote_address, default_limits=["300/hour"])
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"error": "rate_limited", "message": "Too many requests. Please slow down."},
    )


# ----- Middleware -----

# SessionMiddleware is required by Authlib for OAuth state cookies
app.add_middleware(SessionMiddleware, secret_key=settings.jwt_secret)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["content-type", "authorization", "x-requested-with"],
)


# ----- Global exception handlers -----

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Format all HTTPExceptions per API_SPEC.md error schema."""
    slug = _STATUS_SLUGS.get(exc.status_code, "internal_error")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": slug, "message": str(exc.detail)},
    )


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    """Catch-all so we never leak stack traces to the client."""
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "message": "Something went wrong. Please try again."},
    )


# ----- Anonymous visit tracking (in-memory, resets on restart) -----
import time as _time
from collections import defaultdict as _defaultdict

_anon_stats = {
    "total_hits": 0,
    "unique_ips": set(),
    "today": "",
    "today_hits": 0,
    "today_ips": set(),
}


def _track_anonymous_hit(ip: str) -> None:
    """Track an anonymous page visit. Called from middleware."""
    today = _time.strftime("%Y-%m-%d")
    if _anon_stats["today"] != today:
        _anon_stats["today"] = today
        _anon_stats["today_hits"] = 0
        _anon_stats["today_ips"] = set()
    _anon_stats["total_hits"] += 1
    _anon_stats["unique_ips"].add(ip)
    _anon_stats["today_hits"] += 1
    _anon_stats["today_ips"].add(ip)


@app.middleware("http")
async def track_anonymous_visits(request: Request, call_next):
    """Count anonymous visits (no auth cookie) to public pages."""
    response = await call_next(request)
    path = request.url.path
    # Only track public page hits, skip API/admin/static
    if path in ("/", "/leaderboard", "/account") or path.startswith("/profile/"):
        auth_cookie = request.cookies.get("auth_token")
        if not auth_cookie:
            ip = request.headers.get("x-real-ip") or request.client.host if request.client else "unknown"
            _track_anonymous_hit(ip)
    return response


def get_anon_stats() -> dict:
    """Return anonymous visit stats for admin dashboard."""
    return {
        "total_hits": _anon_stats["total_hits"],
        "unique_visitors": len(_anon_stats["unique_ips"]),
        "today_hits": _anon_stats["today_hits"],
        "today_unique": len(_anon_stats["today_ips"]),
    }


# ----- Public endpoints (Phase 1) -----

@app.get("/api/health", tags=["public"])
async def health():
    """Liveness probe. Minimal payload — version/env were removed to avoid
    leaking build metadata to unauthenticated clients. Admins can read
    those from /api/admin/* which is behind auth."""
    return {"status": "ok"}


# In-memory cache for learner count (60s TTL).
_learner_count_cache: dict = {"value": 0, "expires_at": 0.0}


@app.get("/api/learner-count", tags=["public"])
async def learner_count():
    """Public learner count. Cached 60s in-process."""
    import time
    now = time.time()
    if now < _learner_count_cache["expires_at"]:
        return {"count": _learner_count_cache["value"]}

    async with db_module.async_session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(User))
    count = count or 0

    _learner_count_cache["value"] = count
    _learner_count_cache["expires_at"] = now + 60
    return {"count": count}


# ----- Router registration -----
from app.routers import auth, plans, profile, repos, evaluate, chat, share, admin, contact, public_profile, templates, pipeline, certificates, verify, blog, jobs, admin_jobs, admin_social, og, seo, compare, track_pages
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(plans.router, prefix="/api", tags=["plans"])
app.include_router(profile.router, prefix="/api/profile", tags=["profile"])
app.include_router(repos.router, prefix="/api/repos", tags=["repos"])
app.include_router(evaluate.router, prefix="/api", tags=["evaluate"])
app.include_router(chat.router, prefix="/api", tags=["chat"])
app.include_router(share.router, prefix="/share", tags=["share"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(contact.router, prefix="/api", tags=["contact"])
app.include_router(public_profile.router, tags=["public"])
app.include_router(templates.router, prefix="/api", tags=["templates"])
app.include_router(pipeline.router, prefix="/admin/pipeline", tags=["pipeline"])
app.include_router(certificates.router, prefix="/api", tags=["certificates"])
app.include_router(verify.router, tags=["verify"])
app.include_router(blog.router, tags=["blog"])
app.include_router(jobs.router, tags=["jobs"])
app.include_router(admin_jobs.router, prefix="/admin/jobs", tags=["admin-jobs"])
app.include_router(admin_social.router, prefix="/admin/social", tags=["admin-social"])
app.include_router(og.router, tags=["og"])
app.include_router(seo.router, tags=["seo"])
app.include_router(compare.router, tags=["compare"])
app.include_router(track_pages.router, tags=["tracks"])
