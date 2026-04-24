"""SEO-20 + SEO-24 roadmap track pages.

Routes:
  GET /roadmap                                 — hub (SEO-24 ItemList of tracks)
  GET /roadmap/{track}                         — per-track hub
  GET /roadmap/{track}/skills                  — skill matrix
  GET /roadmap/{track}/tools                   — tool inventory
  GET /roadmap/{track}/projects                — portfolio project catalog
  GET /roadmap/{track}/certifications          — free cert guide
  GET /roadmap/{track}/salary                  — compensation bands
  GET /roadmap/{track}/career-path             — career progression

Data source: backend/app/data/tracks/{slug}.json — one per track, source-
controlled, loaded at import time. Five initial tracks: generalist,
ai-engineer, ml-engineer, data-scientist, mlops.

Any unknown track slug or section name returns 404. Track order is
preserved from the TRACK_ORDER manifest below, not the filesystem.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import get_settings

router = APIRouter()

_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
_TRACKS_DIR = Path(__file__).parent.parent / "data" / "tracks"

# Display order for the /roadmap hub + sitemap enumeration. Source of truth
# for "which tracks ship"; adding a file without listing it here is a no-op.
TRACK_ORDER: list[str] = [
    "generalist",
    "ai-engineer",
    "ml-engineer",
    "data-scientist",
    "mlops",
]

# Valid section slugs and their template filenames. Hyphen in URL maps to
# underscore in filename for career-path (Jinja file naming convention).
SECTION_TEMPLATES: dict[str, str] = {
    "skills": "tracks/skills.html",
    "tools": "tracks/tools.html",
    "projects": "tracks/projects.html",
    "certifications": "tracks/certifications.html",
    "salary": "tracks/salary.html",
    "career-path": "tracks/career_path.html",
}

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


def _load_tracks() -> dict[str, dict]:
    """Read every track JSON at import time. Files are source-controlled;
    no cache invalidation needed between deploys."""
    out: dict[str, dict] = {}
    for slug in TRACK_ORDER:
        path = _TRACKS_DIR / f"{slug}.json"
        if not path.exists():
            # Missing file is a hard deploy error — fail loud, don't
            # silently skip a listed track.
            raise RuntimeError(
                f"Missing track data: {path}. Every slug in TRACK_ORDER "
                f"must have a matching data file."
            )
        out[slug] = json.loads(path.read_text(encoding="utf-8"))
    return out


_TRACKS_BY_SLUG = _load_tracks()


def _base() -> str:
    return (get_settings().public_base_url or "").rstrip("/")


def all_track_slugs() -> list[str]:
    """Used by the sitemap emitter to enumerate /roadmap/{track}/* URLs."""
    return list(TRACK_ORDER)


def all_section_slugs() -> list[str]:
    """Used by the sitemap emitter to enumerate per-track sub-pages."""
    return list(SECTION_TEMPLATES.keys())


@router.get("/roadmap", response_class=HTMLResponse)
@router.get("/roadmap/", response_class=HTMLResponse)
async def roadmap_hub() -> HTMLResponse:
    """SEO-24: list every track with an ItemList schema."""
    tracks = [_TRACKS_BY_SLUG[s] for s in TRACK_ORDER]
    html = _env.get_template("tracks/hub.html").render(
        tracks=tracks, base=_base(),
    )
    return HTMLResponse(html, headers={"Cache-Control": "public, max-age=600"})


@router.get("/roadmap/{track_slug}", response_class=HTMLResponse)
async def track_hub(track_slug: str) -> HTMLResponse:
    track = _TRACKS_BY_SLUG.get(track_slug)
    if track is None:
        raise HTTPException(404, "track not found")
    html = _env.get_template("tracks/track_hub.html").render(
        track=track, base=_base(),
    )
    return HTMLResponse(html, headers={"Cache-Control": "public, max-age=600"})


@router.get("/roadmap/{track_slug}/{section}", response_class=HTMLResponse)
async def track_section(track_slug: str, section: str) -> HTMLResponse:
    track = _TRACKS_BY_SLUG.get(track_slug)
    if track is None:
        raise HTTPException(404, "track not found")
    template_name = SECTION_TEMPLATES.get(section)
    if template_name is None:
        raise HTTPException(404, "section not found")
    html = _env.get_template(template_name).render(
        track=track, base=_base(),
    )
    return HTMLResponse(html, headers={"Cache-Control": "public, max-age=600"})
