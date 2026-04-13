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
  *{{box-sizing:border-box}}
  html,body{{margin:0;padding:0;background:#0f1419;color:#f5f1e8;font-family:system-ui,sans-serif;min-height:100vh}}
  .nav{{background:#0a0e13;border-bottom:1px solid #1f2937;padding:14px 28px;display:flex;align-items:center;justify-content:space-between}}
  .brand{{display:flex;align-items:center;gap:10px;font-weight:700;color:#e8a849;font-size:16px;text-decoration:none}}
  .brand-dot{{width:10px;height:10px;border-radius:50%;background:#e8a849}}
  .nav .home-link{{color:#a8a29e;text-decoration:none;font-size:13px}}
  .nav .home-link:hover{{color:#e8a849}}
  .wrap{{max-width:680px;margin:0 auto;padding:60px 24px 80px;text-align:center}}
  .badge{{display:inline-flex;align-items:center;gap:8px;background:rgba(232,168,73,0.12);border:1px solid rgba(232,168,73,0.3);color:#e8a849;padding:6px 14px;border-radius:20px;font-size:11px;letter-spacing:2px;text-transform:uppercase;margin-bottom:18px}}
  h1{{font-size:42px;margin:0 0 10px;color:#e8a849;line-height:1.15;font-weight:700}}
  .subtitle{{font-size:17px;opacity:0.8;margin:0 0 8px}}
  .name{{font-size:14px;opacity:0.55;margin-bottom:36px}}
  .ctas{{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin-bottom:30px}}
  .cta{{display:inline-block;padding:13px 26px;text-decoration:none;border-radius:5px;font-weight:600;font-size:14px}}
  .cta-primary{{background:#e8a849;color:#0f1419}}
  .cta-primary:hover{{background:#c98e2f}}
  .cta-secondary{{background:transparent;color:#e8a849;border:1px solid #e8a849}}
  .cta-secondary:hover{{background:rgba(232,168,73,0.08)}}
  .meta{{margin-top:50px;padding-top:24px;border-top:1px solid #1f2937;font-size:12px;opacity:0.5}}
  .meta a{{color:#e8a849}}
</style>
</head>
<body>
<nav class="nav">
  <a class="brand" href="{base_url}"><span class="brand-dot"></span> AutomateEdge</a>
  <a class="home-link" href="{base_url}">← Back to roadmap</a>
</nav>
<div class="wrap">
  <div class="badge">★ Milestone Reached</div>
  <h1>{milestone['title']}</h1>
  <p class="subtitle">{milestone['subtitle']}</p>
  <p class="name">— shipped by {first_name}</p>
  <div class="ctas">
    <a class="cta cta-primary" href="{base_url}">Start your own roadmap</a>
    <a class="cta cta-secondary" href="https://www.linkedin.com/sharing/share-offsite/?url={share_url}" target="_blank" rel="noopener">Share on LinkedIn</a>
  </div>
  <div class="meta">
    Course completion certificates with verifiable credential IDs are issued at the end of each program.<br>
    Visit <a href="{base_url}">{base_url.replace('https://','').replace('http://','')}</a> to enroll.
  </div>
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
