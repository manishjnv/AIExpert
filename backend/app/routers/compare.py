"""SEO-19 programmatic comparison pages at /vs/{slug}.

Each comparison is defined in backend/data/comparisons.json. One Jinja2
template renders the page — visible content plus Article + FAQPage +
DefinedTerm × 2 + BreadcrumbList JSON-LD. The slug set is finite and
source-controlled; any unknown slug returns 404.

Also exposes GET /vs (index) listing all comparisons.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import get_settings

router = APIRouter()

_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
_COMPARISONS_PATH = Path(__file__).parent.parent / "data" / "comparisons.json"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


def _load_comparisons() -> dict[str, dict]:
    """Read comparisons.json at import time. File is source-controlled and
    small (~60KB); no cache invalidation needed between deploys."""
    payload = json.loads(_COMPARISONS_PATH.read_text(encoding="utf-8"))
    return {c["slug"]: c for c in payload["comparisons"]}


_COMPARISONS_BY_SLUG = _load_comparisons()


def _base() -> str:
    return (get_settings().public_base_url or "").rstrip("/")


@router.get("/vs", response_class=HTMLResponse)
@router.get("/vs/", response_class=HTMLResponse)
async def compare_index() -> HTMLResponse:
    """Index page listing all comparison URLs. Also serves as the crawl
    target for the BreadcrumbList 'Comparisons' node."""
    base = _base()
    items = "\n".join(
        f'<li><a href="/vs/{slug}">{c["title"]}</a>'
        f' — <span>{c["tldr"][:120]}…</span></li>'
        for slug, c in _COMPARISONS_BY_SLUG.items()
    )
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Career Comparisons — AutomateEdge</title>
<meta name="description" content="Side-by-side comparisons of AI/ML roles, tools, and concepts. Salary, skills, hiring volume, and decision guidance for 2026.">
<link rel="canonical" href="{base}/vs">
<meta property="og:title" content="AI Career Comparisons — AutomateEdge">
<meta property="og:description" content="Side-by-side comparisons of AI/ML roles and concepts for 2026.">
<meta property="og:type" content="website">
<meta property="og:url" content="{base}/vs">
<meta property="og:image" content="{base}/og/course/generalist.png">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:wght@400;500;700&family=IBM+Plex+Sans:wght@400;500&family=IBM+Plex+Mono:wght@400&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/nav.css">
<style>
  :root{{color-scheme:dark}}
  html,body{{margin:0;background:#0f1419;color:#e8e4d8;font-family:'IBM Plex Sans',system-ui,sans-serif;line-height:1.65}}
  main{{max-width:880px;margin:0 auto;padding:48px 24px 80px}}
  .eyebrow{{font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:#e8a849;margin-bottom:10px}}
  h1{{font-family:'Fraunces',Georgia,serif;font-size:clamp(30px,4.5vw,42px);color:#f5f1e8;font-weight:500;margin:0 0 14px;letter-spacing:-0.01em}}
  p.lede{{color:#c0c4cc;font-size:16px;margin:0 0 32px;max-width:640px}}
  ul.list{{padding:0;list-style:none;margin:0}}
  ul.list li{{padding:18px 22px;background:#161c24;border:1px solid #2a323d;border-radius:6px;margin-bottom:10px}}
  ul.list a{{color:#f5f1e8;font-weight:500;text-decoration:none;font-size:17px;font-family:'Fraunces',Georgia,serif}}
  ul.list a:hover{{color:#e8a849}}
  ul.list span{{display:block;margin-top:6px;color:#94a3b8;font-size:14px;line-height:1.6}}
</style>
</head><body>
<main>
  <div class="eyebrow">AutomateEdge · Comparisons</div>
  <h1>AI Career &amp; Concept Comparisons</h1>
  <p class="lede">Clear, data-backed side-by-sides for the questions AI learners and career changers actually ask. Salary bands, hiring volume, and decision factors updated for 2026.</p>
  <ul class="list">
{items}
  </ul>
</main>
<script src="/nav.js" defer></script>
</body></html>"""
    return HTMLResponse(html, headers={"Cache-Control": "public, max-age=600"})


@router.get("/vs/{slug}", response_class=HTMLResponse)
async def compare_page(slug: str) -> HTMLResponse:
    comp = _COMPARISONS_BY_SLUG.get(slug)
    if comp is None:
        raise HTTPException(404, "comparison not found")
    base = _base()
    canonical = f"{base}/vs/{slug}"
    html = _env.get_template("compare.html").render(
        comp=comp, canonical=canonical, base=base,
    )
    return HTMLResponse(html, headers={"Cache-Control": "public, max-age=600"})


def all_slugs() -> list[str]:
    """Used by sitemap emitter to enumerate comparison URLs."""
    return list(_COMPARISONS_BY_SLUG.keys())
