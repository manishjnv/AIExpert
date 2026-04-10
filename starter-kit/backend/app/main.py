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

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings

logger = logging.getLogger("roadmap")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs on app startup and shutdown."""
    logger.info("Starting AI Roadmap Platform backend (env=%s)", settings.env)
    # Phase 2: initialize DB connection pool here
    yield
    logger.info("Shutting down")
    # Phase 2: dispose DB engine here


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)


# ----- Global exception handler -----

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
# Phase 2 replaces the hardcoded 0 with a real DB count.
_learner_count_cache: dict = {"value": 0, "expires_at": 0.0}


@app.get("/api/learner-count", tags=["public"])
async def learner_count():
    """Public learner count. Cached 60s in-process."""
    import time
    now = time.time()
    if now < _learner_count_cache["expires_at"]:
        return {"count": _learner_count_cache["value"]}

    # Phase 2 TODO: replace with actual DB query
    # async with get_session() as s:
    #     count = await s.scalar(select(func.count()).select_from(User))
    count = 0

    _learner_count_cache["value"] = count
    _learner_count_cache["expires_at"] = now + 60
    return {"count": count}


# ----- Router registration (Phase 3+) -----
# Claude Code: register routers here as they are built.
# Example (uncomment when routers/auth.py exists):
#
# from app.routers import auth, profile, progress, evaluate, chat, admin, share
# app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
# app.include_router(profile.router, prefix="/api/profile", tags=["profile"])
# app.include_router(progress.router, prefix="/api/progress", tags=["progress"])
# app.include_router(evaluate.router, prefix="/api/evaluate", tags=["evaluate"])
# app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
# app.include_router(admin.router, prefix="/admin", tags=["admin"])
# app.include_router(share.router, prefix="/share", tags=["share"])
