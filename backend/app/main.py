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

    # Start background cleanup tasks
    import asyncio
    from app.services.cleanup import cleanup_expired_otps, cleanup_expired_sessions
    import app.db as _db
    otp_task = asyncio.create_task(cleanup_expired_otps(_db.async_session_factory))
    session_task = asyncio.create_task(cleanup_expired_sessions(_db.async_session_factory))

    yield

    # Cancel cleanup tasks
    otp_task.cancel()
    session_task.cancel()
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

# ----- Middleware -----

# SessionMiddleware is required by Authlib for OAuth state cookies
app.add_middleware(SessionMiddleware, secret_key=settings.jwt_secret)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
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


# ----- Public endpoints (Phase 1) -----

@app.get("/api/health", tags=["public"])
async def health():
    """Liveness probe. Always returns ok if the process is up."""
    return {"status": "ok", "version": settings.app_version, "env": settings.env}


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
from app.routers import auth, plans, profile, repos, evaluate, chat, share, admin
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(plans.router, prefix="/api", tags=["plans"])
app.include_router(profile.router, prefix="/api/profile", tags=["profile"])
app.include_router(repos.router, prefix="/api/repos", tags=["repos"])
app.include_router(evaluate.router, prefix="/api", tags=["evaluate"])
app.include_router(chat.router, prefix="/api", tags=["chat"])
app.include_router(share.router, prefix="/share", tags=["share"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])
