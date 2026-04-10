"""
Share router — public share pages for LinkedIn milestone cards.

Routes under /share (prefix set in main.py). No auth required.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.db import get_db
from app.models.user import User
from app.config import get_settings

router = APIRouter()

# Milestone definitions (month completions + capstone)
MILESTONES = {
    "month-1": {"title": "Foundations Complete", "subtitle": "Python, SQL, math, first ML models"},
    "month-2": {"title": "Classical ML Complete", "subtitle": "Features, trees, time series, Kaggle"},
    "month-3": {"title": "Deep Learning Complete", "subtitle": "Neural nets, vision, transformers"},
    "month-4": {"title": "LLMs & GenAI Complete", "subtitle": "Prompts, RAG, agents, evals"},
    "month-5": {"title": "MLOps & Deploy Complete", "subtitle": "FastAPI, Docker, cloud, responsible AI"},
    "month-6": {"title": "Capstone & Job Hunt Complete", "subtitle": "Ship, publish, apply"},
    "capstone": {"title": "AI Generalist Roadmap Complete", "subtitle": "24 weeks of AI learning — done!"},
}


@router.get("/{user_id}/{milestone_id}")
async def share_page(
    user_id: int,
    milestone_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Public share page with OpenGraph meta tags."""
    milestone = MILESTONES.get(milestone_id)
    if not milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")

    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Only show first name for privacy
    first_name = (user.name or "A learner").split()[0]
    settings = get_settings()
    base_url = settings.public_base_url.rstrip("/")
    share_url = f"{base_url}/share/{user_id}/{milestone_id}"
    og_image = f"{share_url}/og.svg"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{first_name} — {milestone['title']} | AI Roadmap</title>
<meta property="og:title" content="{first_name} completed: {milestone['title']}">
<meta property="og:description" content="{milestone['subtitle']} — AI Generalist Roadmap">
<meta property="og:image" content="{og_image}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:url" content="{share_url}">
<meta property="og:type" content="website">
<meta name="twitter:card" content="summary_large_image">
<style>
  body {{ font-family: system-ui, sans-serif; background: #0f1419; color: #f5f1e8; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }}
  .card {{ text-align: center; max-width: 500px; padding: 48px; }}
  h1 {{ font-size: 28px; margin-bottom: 8px; color: #e8a849; }}
  p {{ font-size: 16px; opacity: 0.7; }}
  .cta {{ display: inline-block; margin-top: 24px; padding: 12px 24px; background: #e8a849; color: #0f1419; text-decoration: none; border-radius: 4px; font-weight: 600; }}
  .cta:hover {{ background: #c98e2f; }}
</style>
</head>
<body>
<div class="card">
  <p style="font-size:12px;letter-spacing:0.15em;text-transform:uppercase;opacity:0.5">AI Generalist Roadmap</p>
  <h1>{milestone['title']}</h1>
  <p>{first_name} completed: {milestone['subtitle']}</p>
  <a class="cta" href="{base_url}">Start Your Own Roadmap</a>
</div>
</body>
</html>"""

    return HTMLResponse(content=html)


@router.get("/{user_id}/{milestone_id}/og.svg")
async def share_og_image(
    user_id: int,
    milestone_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Dynamic 1200x630 SVG for OpenGraph image."""
    milestone = MILESTONES.get(milestone_id)
    if not milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")

    user = await db.get(User, user_id)
    first_name = (user.name or "A learner").split()[0] if user else "A learner"

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630" width="1200" height="630">
  <rect width="1200" height="630" fill="#0f1419"/>
  <rect x="0" y="0" width="1200" height="6" fill="#e8a849"/>
  <text x="600" y="180" text-anchor="middle" fill="#e8a849" font-family="Georgia, serif" font-size="18" letter-spacing="4" text-transform="uppercase">AI GENERALIST ROADMAP</text>
  <text x="600" y="280" text-anchor="middle" fill="#f5f1e8" font-family="Georgia, serif" font-size="48" font-weight="300">{milestone['title']}</text>
  <text x="600" y="340" text-anchor="middle" fill="#e8e2d3" font-family="system-ui, sans-serif" font-size="22" opacity="0.7">{first_name} completed: {milestone['subtitle']}</text>
  <rect x="450" y="400" width="300" height="50" rx="4" fill="#e8a849"/>
  <text x="600" y="432" text-anchor="middle" fill="#0f1419" font-family="system-ui, sans-serif" font-size="16" font-weight="600">Start Your Own Roadmap</text>
  <text x="600" y="580" text-anchor="middle" fill="#4a5260" font-family="monospace" font-size="12">airoadmap.dev</text>
</svg>"""

    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )
