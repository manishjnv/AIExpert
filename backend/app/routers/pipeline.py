"""
Admin pipeline router — auto-discovery, batch generation, content refresh, settings.

All endpoints under /admin/pipeline (prefix set in main.py). Protected by get_current_admin.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from html import escape as esc

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pydantic import BaseModel, Field
from typing import Optional

from app.auth.deps import get_current_admin
from app.db import get_db
from app.utils.time_fmt import fmt_ist, FMT_SHORT, FMT_DATE, iso_utc_z
from app.utils.admin_ui import workflow_steps
from app.models.curriculum import (
    AdminAlert, AICostLimit, AIUsageLog, CurriculumSettings, DiscoveredTopic,
    ProviderBalance, ProviderDailySpend,
)
from app.models.user import User


class PipelineSettingsUpdate(BaseModel):
    """Validated settings update body."""
    max_topics_per_discovery: Optional[int] = Field(None, ge=1, le=50)
    discovery_frequency: Optional[str] = Field(None, pattern=r"^(weekly|monthly|quarterly)$")
    auto_approve_topics: Optional[bool] = None
    auto_generate_variants: Optional[bool] = None
    ai_model_research: Optional[str] = Field(None, pattern=r"^(gemini|groq|cerebras|mistral|deepseek|sambanova)$")
    ai_model_formatting: Optional[str] = Field(None, pattern=r"^(gemini|groq|cerebras|mistral|deepseek|sambanova)$")
    max_tokens_per_run: Optional[int] = Field(None, ge=0, le=1000000)
    refresh_frequency: Optional[str] = Field(None, pattern=r"^(monthly|quarterly)$")

router = APIRouter()

ADMIN_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,400;9..144,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');
body { font-family: 'IBM Plex Sans', system-ui, sans-serif; background: #0f1419; color: #e0dbd2; margin: 0; padding: 0; -webkit-font-smoothing: antialiased; font-size: 14px; line-height: 1.6; }
.page { max-width: 100%; margin: 0; padding: 32px 48px; }
h1 { font-family: 'Fraunces', Georgia, serif; color: #e8a849; font-size: 28px; font-weight: 300; margin-bottom: 4px; }
h2 { font-family: 'Fraunces', Georgia, serif; color: #e8a849; font-size: 18px; margin-top: 24px; }
h3 { font-family: 'Fraunces', Georgia, serif; color: #e8a849; font-size: 15px; margin-top: 16px; }
p { color: #b0aaa0; line-height: 1.6; }
.subtitle { color: #6a7280; font-size: 13px; margin-bottom: 24px; font-family: 'IBM Plex Mono', monospace; letter-spacing: 0.03em; }
.stat { display: inline-block; background: #1d242e; padding: 16px 24px; border-radius: 6px; margin: 4px; text-align: center; }
.stat .num { font-family: 'Fraunces', Georgia, serif; font-size: 28px; font-weight: 400; color: #e8a849; }
.stat .lbl { font-family: 'IBM Plex Mono', monospace; font-size: 9px; text-transform: uppercase; letter-spacing: 0.12em; color: #6a7280; margin-top: 2px; }
table { width: 100%; border-collapse: collapse; margin-top: 12px; }
th { text-align: left; padding: 10px 8px; font-family: 'IBM Plex Mono', monospace; font-size: 10px; text-transform: uppercase; letter-spacing: 0.12em; color: #6a7280; border-bottom: 1px solid #2a323d; }
td { padding: 10px 8px; font-size: 13px; border-bottom: 1px solid #1d242e; color: #d0cbc2; }
.btn { font-family: 'IBM Plex Mono', monospace; font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; padding: 8px 14px; background: transparent; border: 1px solid #3a4452; color: #e8e2d3; cursor: pointer; transition: all 0.2s; border-radius: 2px; }
.btn:hover { border-color: #e8a849; color: #e8a849; }
.btn.success { border-color: #6db585; color: #6db585; }
.btn.success:hover { background: rgba(109,181,133,0.1); }
.btn.danger { border-color: #d97757; color: #d97757; }
.btn.danger:hover { background: rgba(217,119,87,0.1); }
.btn.primary { border-color: #e8a849; color: #e8a849; }
.btn.primary:hover { background: rgba(232,168,73,0.1); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.card { background: #1d242e; padding: 16px; border-radius: 6px; margin-bottom: 16px; }
.form-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; margin-bottom: 16px; }
@media (max-width: 900px) { .form-row { grid-template-columns: 1fr 1fr; } }
.form-group { display: flex; flex-direction: column; gap: 4px; }
.form-group label { font-family: 'IBM Plex Mono', monospace; font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #8a92a0; }
.form-group input, .form-group select { padding: 8px; background: #0f1419; border: 1px solid #2a323d; color: #f5f1e8; border-radius: 3px; font-family: 'IBM Plex Sans', system-ui, sans-serif; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
.badge.pending { background: #3d3520; color: #e8a849; }
.badge.approved { background: #1d3525; color: #6db585; }
.badge.generating { background: #1d2535; color: #5d9be8; }
.badge.generated { background: #1d3525; color: #6db585; }
.badge.rejected { background: #3d2020; color: #d97757; }
.status-msg { margin-top: 8px; font-size: 12px; }
.status-msg.ok { color: #6db585; }
.status-msg.error { color: #d97757; }
@media (max-width: 768px) { .page { padding: 20px 16px; } .stat { padding: 12px 14px; } .stat .num { font-size: 22px; } }
"""

NAV_HTML = '<link rel="stylesheet" href="/nav.css"><script src="/nav.js"></script>'


def _check_origin(request: Request) -> None:
    """Strict CSRF check: parsed hostname must match, reject if both headers absent."""
    from urllib.parse import urlparse
    origin = request.headers.get("origin") or request.headers.get("referer", "")
    host = request.headers.get("host", "")
    if not origin:
        raise HTTPException(status_code=403, detail="Missing Origin/Referer header")
    origin_host = urlparse(origin).hostname or ""
    expected_host = host.split(":")[0]  # strip port
    if origin_host != expected_host:
        raise HTTPException(status_code=403, detail="Origin mismatch")


def _topic_quality_cell(score_data: dict) -> str:
    """Render topic quality score as a colored number with tooltip."""
    s = score_data.get("composite_score", 0)
    if not s:
        return '<span style="color:#8a92a0">—</span>'
    color = "#6db585" if s >= 80 else "#e8a849" if s >= 60 else "#d97757"
    issues = score_data.get("issues", [])
    tooltip = " · ".join(issues[:3]) if issues else "No issues"
    return f'<span style="color:{color};font-weight:600;cursor:help" title="{esc(tooltip)}">{s}</span>'


async def _get_settings(db: AsyncSession) -> CurriculumSettings:
    result = await db.execute(select(CurriculumSettings).limit(1))
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = CurriculumSettings()
        db.add(settings)
        await db.flush()
    return settings


# ---- API Endpoints ----

@router.get("/api/settings")
async def get_pipeline_settings(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get current pipeline settings."""
    s = await _get_settings(db)
    return {
        "max_topics_per_discovery": s.max_topics_per_discovery,
        "discovery_frequency": s.discovery_frequency,
        "auto_approve_topics": s.auto_approve_topics,
        "auto_generate_variants": s.auto_generate_variants,
        "ai_model_research": s.ai_model_research,
        "ai_model_formatting": s.ai_model_formatting,
        "max_tokens_per_run": s.max_tokens_per_run,
        "tokens_used_this_month": s.tokens_used_this_month,
        "budget_month": s.budget_month,
        "refresh_frequency": s.refresh_frequency,
        "last_discovery_run": s.last_discovery_run.isoformat() if s.last_discovery_run else None,
        "last_generation_run": s.last_generation_run.isoformat() if s.last_generation_run else None,
        "last_refresh_run": s.last_refresh_run.isoformat() if s.last_refresh_run else None,
    }


@router.post("/api/settings")
async def update_pipeline_settings(
    request: Request,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update pipeline settings."""
    _check_origin(request)
    body = await request.json()
    validated = PipelineSettingsUpdate(**body)
    s = await _get_settings(db)

    for field, value in validated.model_dump(exclude_none=True).items():
        setattr(s, field, value)

    await db.flush()
    return {"ok": True}


@router.post("/api/run-discovery")
async def trigger_discovery(
    request: Request,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger topic discovery."""
    _check_origin(request)
    from app.services.topic_discovery import run_discovery
    result = await run_discovery(db)
    return result


@router.post("/api/run-generation")
async def trigger_generation(
    request: Request,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger batch generation for approved topics."""
    _check_origin(request)
    from app.services.batch_generator import run_batch_generation
    result = await run_batch_generation(db)
    return result


@router.post("/api/run-refine")
async def trigger_refine(
    request: Request,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Refine existing templates via AI quality pipeline to push scores toward 90+."""
    _check_origin(request)
    from app.services.quality_pipeline import refine_existing_templates
    result = await refine_existing_templates(db)
    return result


@router.post("/api/refine-one/{template_key}")
async def refine_one_template(
    template_key: str,
    request: Request,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Run the quality pipeline on a single template. Returns before/after scores."""
    _check_origin(request)
    import json as _json
    from app.curriculum.loader import load_template, update_quality_score
    from app.services.quality_pipeline import run_quality_pipeline, _quick_heuristic_score
    from app.services.curriculum_generator import save_curriculum_draft

    try:
        tpl = load_template(template_key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Template not found")

    plan = _json.loads(tpl.model_dump_json())
    before = _quick_heuristic_score(plan)

    qr = await run_quality_pipeline(plan, "unknown", db)
    after = qr["final_score"]
    update_quality_score(template_key, after)

    improved = qr["plan"] != plan and after > before
    if improved:
        await save_curriculum_draft(qr["plan"])

    return {
        "key": template_key,
        "score_before": before,
        "score_after": after,
        "improved": improved,
        "stages_run": qr.get("stages_run", []),
        "models_used": qr.get("models_used", {}),
        "skipped": qr.get("skipped", []),
    }


@router.post("/api/run-refresh")
async def trigger_refresh(
    request: Request,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger content refresh (link checks + currency review)."""
    _check_origin(request)
    from app.services.content_refresh import run_content_refresh
    result = await run_content_refresh(db)
    return result


@router.get("/api/topics")
async def list_topics(
    status: str = Query("", description="Filter by status"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List discovered topics (paginated)."""
    query = select(DiscoveredTopic).order_by(DiscoveredTopic.created_at.desc())
    if status:
        query = query.where(DiscoveredTopic.status == status)

    rows = (await db.execute(query.offset((page - 1) * per_page).limit(per_page))).scalars().all()
    return [
        {
            "id": t.id,
            "topic_name": t.topic_name,
            "category": t.category,
            "subcategory": t.subcategory,
            "justification": t.justification,
            "evidence_sources": json.loads(t.evidence_sources) if t.evidence_sources else [],
            "confidence_score": t.confidence_score,
            "status": t.status,
            "discovery_run": t.discovery_run,
            "ai_model_used": t.ai_model_used,
            "templates_generated": t.templates_generated,
            "generation_error": t.generation_error,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in rows
    ]


@router.get("/api/topics/quality")
async def get_topic_quality_scores(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Score all topics on 7 quality dimensions."""
    from app.services.quality_scorer import score_topic
    result = await db.execute(select(DiscoveredTopic).order_by(DiscoveredTopic.created_at.desc()))
    topics = result.scalars().all()
    return [score_topic(t) for t in topics]


@router.get("/api/topics/{topic_id}")
async def get_topic_detail(
    topic_id: int,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get full topic detail — plus the associated templates (if any)."""
    result = await db.execute(
        select(DiscoveredTopic).where(DiscoveredTopic.id == topic_id)
    )
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Topic not found")

    # Look up associated templates by slug match (same algo as the
    # Topics Quality column uses).
    from app.curriculum.loader import list_templates, load_template, get_template_status
    import re as _re

    def _candidates(raw):
        if not raw:
            return set()
        head = _re.split(r"\s+[—\-–]\s+", raw, maxsplit=1)[0]
        return {
            _re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
            for s in (raw, head) if s
        }

    candidates = _candidates(t.topic_name) | _candidates(t.normalized_name)
    associated = []
    for key in list_templates():
        m = _re.match(r"^(.+)_(\d+)mo_(beginner|intermediate|advanced)$", key)
        if not m:
            continue
        key_topic, dur, lvl = m.group(1), int(m.group(2)), m.group(3)
        if any(c and (key_topic == c or key_topic.startswith(c) or c.startswith(key_topic)) for c in candidates):
            try:
                tpl = load_template(key)
                meta = get_template_status(key) or {}
                associated.append({
                    "key": key,
                    "title": tpl.title,
                    "level": tpl.level,
                    "duration_months": tpl.duration_months,
                    "total_weeks": tpl.total_weeks,
                    "total_hours": tpl.total_hours,
                    "total_focus_areas": tpl.total_focus_areas,
                    "total_checks": tpl.total_checks,
                    "certification_count": tpl.certification_count,
                    "github_resource_count": tpl.github_resource_count,
                    "top_resources_count": len(tpl.top_resources or []),
                    "certifications_count": len(tpl.certifications or []),
                    "goal": tpl.goal,
                    "quality_score": int(meta.get("quality_score") or 0),
                    "status": meta.get("status") or "draft",
                })
            except Exception:
                continue

    return {
        "id": t.id,
        "topic_name": t.topic_name,
        "category": t.category,
        "subcategory": t.subcategory,
        "justification": t.justification,
        "evidence_sources": json.loads(t.evidence_sources) if t.evidence_sources else [],
        "confidence_score": t.confidence_score,
        "status": t.status,
        "discovery_run": t.discovery_run,
        "ai_model_used": t.ai_model_used,
        "templates_generated": t.templates_generated,
        "generation_error": t.generation_error,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "associated_templates": associated,
    }


@router.post("/api/topics/{topic_id}/approve")
async def approve_topic(
    topic_id: int,
    request: Request,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Approve a discovered topic for curriculum generation."""
    _check_origin(request)
    topic = await db.get(DiscoveredTopic, topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    if topic.status not in ("pending", "rejected"):
        raise HTTPException(status_code=400, detail=f"Cannot approve topic in '{topic.status}' state")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    topic.status = "approved"
    topic.reviewer_id = user.id
    topic.reviewed_at = now
    await db.flush()
    return {"ok": True, "status": "approved"}


@router.post("/api/claude-prompt")
async def claude_prompt(
    request: Request,
    _user: User = Depends(get_current_admin),
):
    """Render a ready-to-paste prompt for Claude Max chat.

    Embeds the full generation schema + structure rules + level calibration
    + action-verb / measurability thresholds (the same rules the heuristic
    scorer enforces, so Claude's output should hit 95+ first-shot).
    """
    _check_origin(request)
    from pathlib import Path as _Path
    import re as _re

    body = await request.json()
    topic = (body.get("topic") or "").strip()
    duration = int(body.get("duration_months") or 6)
    level = (body.get("level") or "intermediate").strip().lower()

    if not topic:
        raise HTTPException(status_code=400, detail="topic required")
    if duration not in (3, 6, 9, 12):
        raise HTTPException(status_code=400, detail="duration_months must be 3, 6, 9, or 12")
    if level not in ("beginner", "intermediate", "advanced"):
        raise HTTPException(status_code=400, detail="level must be beginner, intermediate, or advanced")

    duration_map = {3: "3mo", 6: "6mo", 9: "9mo", 12: "12mo"}
    duration_str = duration_map[duration]
    total_weeks = duration * 4
    key = _re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_") + f"_{duration_str}_{level}"

    # Render the rich Claude Opus prompt with the admin's inputs substituted.
    # Uses {{PLACEHOLDER}} tokens (not Python .format) so the JSON schema
    # examples inside the prompt don't get mangled.
    prompt_path = _Path(__file__).parent.parent / "prompts" / "claude_opus_manual.txt"
    template = prompt_path.read_text(encoding="utf-8")
    rendered = (
        template
        .replace("{{TOPIC}}", topic)
        .replace("{{DURATION_MONTHS}}", str(duration))
        .replace("{{TOTAL_WEEKS}}", str(total_weeks))
        .replace("{{LEVEL}}", level)
        .replace("{{KEY}}", key)
    )
    return {
        "prompt": rendered,
        "key": key,
        "expected_weeks": total_weeks,
    }


@router.get("/api/sample-template")
async def sample_template(_user: User = Depends(get_current_admin)):
    """Download a minimal valid sample template for manual upload reference."""
    from fastapi.responses import JSONResponse
    sample = {
        "key": "sample_topic_3mo_intermediate",
        "version": "1.0",
        "title": "Sample Topic — Intermediate 3-Month Roadmap",
        "level": "intermediate",
        "goal": "Ship a production-ready project demonstrating <capability> across real-world data in ~180 hours.",
        "duration_months": 3,
        "top_resources": [
            {"name": "Primary textbook / course (visual-intuitive)", "url": "https://real-anchor-1.com", "hrs": 20},
            {"name": "Rigorous reference (math/theory)",             "url": "https://real-anchor-2.com", "hrs": 15},
            {"name": "Hands-on codebase (practice)",                 "url": "https://github.com/example/anchor-3", "hrs": 25},
        ],
        "certifications": [
            {"name": "Relevant industry cert", "provider": "DeepLearning.AI", "url": "https://www.deeplearning.ai/courses/...", "cost_usd": 49, "prep_hours": 20},
        ],
        "months": [
            {
                "month": 1,
                "label": "Foundations",
                "title": "Core concepts and tooling",
                "tagline": "Get grounded in the fundamentals and set up the dev environment.",
                "checkpoint": "Learner can explain <core concept> and has a working environment.",
                "weeks": [
                    {
                        "n": 1,
                        "t": "Environment setup",
                        "hours": 16,
                        "focus": ["Topic A", "Topic B", "Topic C", "Topic D"],
                        "deliv": ["Notebook demonstrating basics", "GitHub repo initialised"],
                        "resources": [
                            {"name": "Primary course or tutorial", "url": "https://real-url.com", "hrs": 6},
                            {"name": "Official documentation", "url": "https://real-docs.com", "hrs": 4},
                            {"name": "Hands-on practice", "url": "https://github.com/example", "hrs": 6},
                        ],
                        "checks": [
                            "Implement a Python module with 3 tested functions",
                            "Configure local dev environment and verify with a test run",
                            "Build a notebook documenting <topic> fundamentals",
                            "Write unit tests with >80% coverage",
                            "Submit GitHub repo with README, .gitignore, and license",
                        ],
                    }
                ],
            }
        ],
    }
    return JSONResponse(
        content=sample,
        headers={"Content-Disposition": "attachment; filename=sample-template.json"},
    )


def _lenient_cleanup(data):
    """Best-effort normalisation of a Claude-generated template before strict
    schema validation. Fixes common LLM output quirks without changing semantics.

    Handles:
    - Markdown chars (**, `, ~~, ```json, extra quotes) leaking into string values
    - Numeric fields arriving as strings ("16" → 16)
    - Missing https:// on URLs
    - Stray whitespace / newlines in titles/goals
    - Wrong-case level ("Intermediate" → "intermediate")
    - Empty certifications array omitted vs null
    - Common Claude-isms like "…" (ellipsis) in URLs

    Returns (cleaned_dict, list_of_notes).
    """
    import re as _re
    notes: list[str] = []
    if not isinstance(data, dict):
        return data, notes

    NUMERIC_KEYS = {"duration_months", "n", "month", "hours", "hrs", "cost_usd", "prep_hours"}
    MARKDOWN_RE = _re.compile(r"\*\*|__|~~|`+")

    def _clean_str(s, key=""):
        if not isinstance(s, str):
            return s
        original = s
        # Strip markdown emphasis chars
        s = MARKDOWN_RE.sub("", s)
        # Strip code fences if they somehow appear in a value
        s = s.replace("```json", "").replace("```", "")
        # Collapse excess whitespace (but preserve single spaces)
        s = _re.sub(r"[\r\n\t]+", " ", s)
        s = _re.sub(r" +", " ", s).strip()
        # URL fixups
        if key == "url" and s and not s.lower().startswith(("http://", "https://")):
            if s.startswith("//"):
                s = "https:" + s
            elif _re.match(r"^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", s):
                s = "https://" + s
        if s != original:
            notes.append(f"cleaned string at '{key}'")
        return s

    def _coerce_num(v, key=""):
        if isinstance(v, (int, float)) or v is None:
            return v
        if isinstance(v, str):
            stripped = v.strip().replace(",", "")
            try:
                if "." in stripped:
                    val = int(float(stripped))
                else:
                    val = int(stripped)
                notes.append(f"coerced {key}: '{v}' → {val}")
                return val
            except (ValueError, TypeError):
                return v
        return v

    def _walk(node, parent_key=""):
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if k in NUMERIC_KEYS:
                    v = _coerce_num(v, k)
                elif isinstance(v, str):
                    v = _clean_str(v, k)
                elif isinstance(v, (list, dict)):
                    v = _walk(v, k)
                out[k] = v
            return out
        if isinstance(node, list):
            return [_walk(item, parent_key) for item in node]
        if isinstance(node, str):
            return _clean_str(node, parent_key)
        return node

    cleaned = _walk(data)

    # Level normalisation
    if isinstance(cleaned.get("level"), str):
        lv = cleaned["level"].strip().lower()
        if lv in ("beginner", "intermediate", "advanced") and lv != cleaned["level"]:
            notes.append(f"normalised level to lowercase '{lv}'")
            cleaned["level"] = lv

    # Ensure optional fields that might be null arrive as [] (Pydantic
    # allows None, but downstream code is happier with [])
    for opt_list in ("top_resources", "certifications"):
        if cleaned.get(opt_list) is None:
            cleaned[opt_list] = []

    # Strip any leading/trailing junk from key (slugify leftovers)
    if isinstance(cleaned.get("key"), str):
        clean_key = _re.sub(r"[^a-z0-9_]+", "_", cleaned["key"].lower()).strip("_")
        if clean_key != cleaned["key"]:
            notes.append(f"normalised key: '{cleaned['key']}' → '{clean_key}'")
            cleaned["key"] = clean_key

    return cleaned, notes


@router.post("/api/topics/upload-template")
async def upload_manual_template(
    request: Request,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Manually upload a full curriculum template JSON.

    Validates structure against PlanTemplate (same schema as AI-generated
    templates), saves to data/templates/, and creates a DiscoveredTopic
    row so the template shows up on the Topics tab with status=generated
    and source flagged as manual upload.

    Key collision handling: body.overwrite=true allows replacing an
    existing template; otherwise rejects with 409.
    """
    _check_origin(request)
    from app.curriculum.loader import PlanTemplate, load_template
    from app.services.curriculum_generator import save_curriculum_draft
    import re as _re

    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {e}")

    overwrite = bool(body.pop("overwrite", False))
    auto_publish = bool(body.pop("auto_publish", False))
    # Accept either {"template": {...}} or the template dict at the top level
    plan_data = body.get("template") if isinstance(body.get("template"), dict) else body

    # Lenient cleanup — fix common issues in Claude/LLM output before strict
    # Pydantic validation. Handles markdown stragglers, type coercions,
    # URL protocol, etc.
    plan_data, cleanup_notes = _lenient_cleanup(plan_data)

    # Structural validation via Pydantic
    try:
        tpl = PlanTemplate(**plan_data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Template validation failed: {e}")

    key = tpl.key

    # Collision check
    from pathlib import Path
    template_path = Path(__file__).parent.parent / "curriculum" / "templates" / f"{key}.json"
    if template_path.exists() and not overwrite:
        raise HTTPException(
            status_code=409,
            detail=f"Template '{key}' already exists. Re-submit with overwrite=true to replace.",
        )

    # Save template JSON
    await save_curriculum_draft(plan_data)

    # Create/update a DiscoveredTopic row so it appears on the Topics tab.
    # Use the TOPIC PORTION (before any " — ..." suffix) as the topic_name so
    # it slug-matches the template key pattern (key = <topic>_<duration>mo_<level>).
    raw_title = plan_data.get("title") or key
    topic_name = _re.split(r"\s+[—\-–]\s+", raw_title, maxsplit=1)[0].strip() or raw_title
    normalized = _re.sub(r"[^a-z0-9]+", "-", topic_name.lower()).strip("-")[:120]
    existing_topic = (await db.execute(
        select(DiscoveredTopic).where(DiscoveredTopic.normalized_name == normalized)
    )).scalar_one_or_none()

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if existing_topic:
        existing_topic.status = "generated"
        existing_topic.templates_generated = (existing_topic.templates_generated or 0) + (0 if overwrite else 1)
        existing_topic.reviewer_id = user.id
        existing_topic.reviewed_at = now
        topic_id = existing_topic.id
    else:
        new_topic = DiscoveredTopic(
            topic_name=topic_name,
            normalized_name=normalized,
            category=(plan_data.get("level") or "manual")[:60],
            subcategory=f"{tpl.duration_months}mo",
            justification=f"Manually uploaded by admin on {now.strftime('%Y-%m-%d %H:%M UTC')}",
            evidence_sources=json.dumps(["manual_upload"]),
            confidence_score=100,
            status="generated",
            discovery_run=f"manual-{now.strftime('%Y%m%dT%H%M%S')}",
            ai_model_used="manual_upload",
            reviewer_id=user.id,
            reviewed_at=now,
            templates_generated=1,
        )
        db.add(new_topic)
        await db.flush()
        topic_id = new_topic.id

    # Run the full quality pipeline (prefix → score → review → refine → validate).
    # The pipeline can improve weak templates, and auto-publish only fires on
    # the final score. Uploaded templates from Claude usually land near-perfect,
    # so refine rarely triggers; but if it does, the refined version is saved.
    quality_score = None
    published = False
    publish_reason = None
    pipeline_stages: list[str] = []
    try:
        from app.services.quality_pipeline import run_quality_pipeline
        from app.curriculum.loader import (
            update_quality_score, publish_template, PUBLISH_THRESHOLD,
        )
        qr = await run_quality_pipeline(plan_data, generator_model="manual_upload", db=db)
        quality_score = int(qr.get("final_score", 0))
        pipeline_stages = qr.get("stages_run", [])

        # If the pipeline improved the plan, persist the improved version
        improved_plan = qr.get("plan") or plan_data
        if improved_plan is not plan_data:
            await save_curriculum_draft(improved_plan)
            plan_data = improved_plan

        update_quality_score(key, quality_score)

        if auto_publish:
            if quality_score >= PUBLISH_THRESHOLD:
                if publish_template(key, quality_score):
                    published = True
                else:
                    publish_reason = f"publish_template declined (score={quality_score})"
            else:
                publish_reason = f"score {quality_score} < {PUBLISH_THRESHOLD} threshold"
    except Exception as e:
        logger.exception("Quality pipeline on manual upload failed")
        publish_reason = f"pipeline failed: {type(e).__name__}"

    return {
        "ok": True,
        "key": key,
        "title": tpl.title,
        "topic_id": topic_id,
        "overwritten": existing_topic is not None and overwrite,
        "weeks": tpl.total_weeks,
        "hours": tpl.total_hours,
        "quality_score": quality_score,
        "published": published,
        "publish_reason": publish_reason,
        "cleanup_notes": cleanup_notes,
        "pipeline_stages": pipeline_stages,
    }


@router.post("/api/topics/{topic_id}/reject")
async def reject_topic(
    topic_id: int,
    request: Request,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Reject a discovered topic."""
    _check_origin(request)
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    topic = await db.get(DiscoveredTopic, topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    if topic.status not in ("pending", "approved"):
        raise HTTPException(status_code=400, detail=f"Cannot reject topic in '{topic.status}' state")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    topic.status = "rejected"
    topic.reviewer_id = user.id
    topic.reviewed_at = now
    topic.reviewer_notes = body.get("notes", "")
    await db.flush()
    return {"ok": True, "status": "rejected"}


@router.get("/api/quality")
async def get_quality_scores(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Score all templates on structure, resources, checklist, progression, links."""
    from app.services.quality_scorer import score_all_templates
    return await score_all_templates(db)


@router.get("/api/quality/{template_key}")
async def get_template_quality(
    template_key: str,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Score a single template."""
    from app.services.quality_scorer import score_template
    from app.curriculum.loader import load_template
    try:
        tpl = load_template(template_key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Template not found")
    return await score_template(tpl, db)


@router.post("/api/quality/{template_key}/publish")
async def publish_template_endpoint(
    template_key: str,
    request: Request,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Publish a template if it meets the quality threshold (>= 90)."""
    _check_origin(request)
    from app.services.quality_scorer import score_template
    from app.curriculum.loader import load_template, publish_template, PUBLISH_THRESHOLD
    try:
        tpl = load_template(template_key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Template not found")

    result = await score_template(tpl, db)
    score = result["composite_score"]

    if publish_template(template_key, score):
        return {"ok": True, "status": "published", "score": score}
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Score {score} is below publish threshold ({PUBLISH_THRESHOLD}). Fix quality issues first.",
        )


@router.post("/api/quality/{template_key}/unpublish")
async def unpublish_template_endpoint(
    template_key: str,
    request: Request,
    _user: User = Depends(get_current_admin),
):
    """Unpublish a template (move back to draft)."""
    _check_origin(request)
    from app.curriculum.loader import unpublish_template
    unpublish_template(template_key)
    return {"ok": True, "status": "draft"}


@router.delete("/api/topics/{topic_id}")
async def delete_topic(
    topic_id: int,
    request: Request,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a discovered topic AND any associated template files.

    Templates are matched by key prefix: if the topic's normalized_name
    (as used by the generator) is a prefix of any template key, that
    template file is removed (with metadata entry), so re-uploading
    won't hit a 409 duplicate.
    """
    _check_origin(request)
    from pathlib import Path as _Path
    from app.curriculum.loader import (
        list_templates, load_template, unpublish_template, TEMPLATES_DIR,
    )
    import re as _re

    topic = await db.get(DiscoveredTopic, topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    # Build a key-prefix candidate from the topic name (same algo generators use)
    name_slug = _re.sub(r"[^a-z0-9]+", "_", (topic.topic_name or "").lower()).strip("_")
    normalized_slug = _re.sub(r"[^a-z0-9]+", "_", (topic.normalized_name or "").lower()).strip("_")
    # Grandfathered generalist templates are protected
    protected = {"generalist_3mo_intermediate", "generalist_6mo_intermediate", "generalist_12mo_beginner"}

    deleted_templates: list[str] = []
    for key in list_templates():
        if key in protected:
            continue
        if name_slug and key.startswith(name_slug):
            pass
        elif normalized_slug and key.startswith(normalized_slug):
            pass
        else:
            continue
        try:
            path = TEMPLATES_DIR / f"{key}.json"
            if path.exists():
                path.unlink()
            # Clear publish metadata so it doesn't linger
            try:
                unpublish_template(key)
            except Exception:
                pass
            deleted_templates.append(key)
        except Exception as e:
            logger.warning("Failed to delete template file %s: %s", key, e)

    # Clear the load_template cache so stale entries don't linger
    try:
        load_template.cache_clear()
    except Exception:
        pass

    await db.delete(topic)
    await db.flush()
    return {"ok": True, "deleted_templates": deleted_templates}


# ---- HTML Pages ----

@router.get("/", response_class=HTMLResponse)
async def pipeline_dashboard_page(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Pipeline actions page — run discovery, generation, refresh."""
    s = await _get_settings(db)

    approved = await db.scalar(
        select(func.count()).select_from(DiscoveredTopic).where(DiscoveredTopic.status == "approved")
    ) or 0
    pending_topics = await db.scalar(
        select(func.count()).select_from(DiscoveredTopic).where(DiscoveredTopic.status == "pending")
    ) or 0

    from app.curriculum.loader import list_templates
    template_count = len(list_templates())

    last_discovery = fmt_ist(s.last_discovery_run, default="Never")
    last_generation = fmt_ist(s.last_generation_run, default="Never")
    last_refresh = fmt_ist(s.last_refresh_run, default="Never")

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Pipeline</title>
<style>{ADMIN_CSS}</style></head><body>
{NAV_HTML}
<div class="page">
<h1>Pipeline Actions</h1>
<div class="subtitle">Run tasks, review pipeline status · Provider health on <a href="/admin/pipeline/ai-usage" style="color:#e8a849">AI Usage</a></div>
{workflow_steps(2)}
<div style="background:#1d242e;border-left:3px solid #e8a849;padding:12px 16px;border-radius:4px;margin:12px 0 16px;font-size:13px;line-height:1.6">
  <div style="color:#e8a849;font-weight:600;margin-bottom:6px">Your workflow — how the pipeline runs</div>
  <ol style="margin:0 0 8px 18px;padding:0;color:#d0cbc2">
    <li><strong>Configure once</strong> — scroll to <em>Pipeline Settings</em> to set frequency (weekly/monthly/quarterly), daily token budget, and the AI models used per stage. Everything below then runs on cron.</li>
    <li><strong>Discover</strong> <span style="color:#8a92a0">(auto · manual override below)</span> → AI scans universities, papers, and industry for trending AI/ML topics. Results land on <a href="/admin/pipeline/topics" style="color:#e8a849">Topics</a>.</li>
    <li><strong>Approve topics</strong> → on the Topics tab. Or flip <em>auto-approve</em> in Settings to skip manual review.</li>
    <li><strong>Generate</strong> <span style="color:#8a92a0">(auto · manual override below)</span> → creates curriculum variants (3/6/9/12 mo × beginner/intermediate/advanced) for each approved topic. Quality pipeline runs automatically: Generate → Score → Review → Refine → Validate.</li>
    <li><strong>Refine</strong> <span style="color:#8a92a0">(manual)</span> → re-runs the quality pipeline on any draft below the publish threshold (90). Use when you want to salvage a weak template before regenerating.</li>
    <li><strong>Refresh</strong> <span style="color:#8a92a0">(auto · manual override below)</span> → checks that resource links still resolve and that published content is still current.</li>
    <li><strong>Publish</strong> → happens on <a href="/admin/templates" style="color:#e8a849">Templates</a> tab once a draft scores ≥ 90.</li>
  </ol>
  <div style="color:#8a92a0;font-size:12px">Normal order: <strong style="color:#d0cbc2">Discover → Generate → Refine → Refresh</strong>. The 4 buttons below are manual overrides; each stage feeds the next, so running out of order is rarely useful. Monitor the <em>Pipeline Status</em> and <em>Template Quality</em> tables further down.</div>
</div>

<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;background:#0f1419;border:1px solid #2a323d;border-radius:6px;padding:10px 14px;margin-bottom:14px;font-size:12px;color:#8a92a0;flex-wrap:wrap">
  <span><span style="color:#e8a849">Discover</span></span>
  <span style="color:#5a6472">→</span>
  <span><a href="/admin/pipeline/topics" style="color:#d0cbc2;text-decoration:none"><strong style="color:#e8a849">{pending_topics}</strong> pending</a> · <strong>{approved}</strong> approved</span>
  <span style="color:#5a6472">→</span>
  <span><span style="color:#e8a849">Generate</span></span>
  <span style="color:#5a6472">→</span>
  <span><a href="/admin/templates" style="color:#d0cbc2;text-decoration:none"><strong>{template_count}</strong> templates</a></span>
  <span style="color:#5a6472">→</span>
  <span><span style="color:#e8a849">Refine</span> / <span style="color:#e8a849">Refresh</span></span>
</div>
<div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:16px;margin-bottom:24px">

<div class="card">
  <h3>1. Discover Topics</h3>
  <p style="font-size:12px;color:#8a92a0">AI finds trending AI/ML topics from universities, papers, and industry.</p>
  <p style="font-size:12px">Last run: {esc(last_discovery)}</p>
  <p style="font-size:12px">Discovers: {s.max_topics_per_discovery} topic(s) per run</p>
  <button class="btn primary" onclick="runAction('run-discovery', this)">Run Discovery Now</button>
  <div id="status-discovery" class="status-msg"></div>
</div>

<div class="card">
  <h3>2. Generate Curricula</h3>
  <p style="font-size:12px;color:#8a92a0">Creates study plans (3mo/6mo, beginner/intermediate/advanced) for approved topics.</p>
  <p style="font-size:12px">Last run: {esc(last_generation)}</p>
  <p style="font-size:12px">Ready to generate: <strong>{approved}</strong> approved topic(s)</p>
  <button class="btn primary" onclick="runAction('run-generation', this)" {'disabled' if approved == 0 else ''}>Generate Curricula</button>
  <div id="status-generation" class="status-msg"></div>
</div>

<div class="card">
  <h3>3. Refine Quality</h3>
  <p style="font-size:12px;color:#8a92a0">AI reviews templates below 90 and surgically fixes weak dimensions.</p>
  <p style="font-size:12px">Templates to refine: <strong>{template_count}</strong></p>
  <p style="font-size:12px">Pipeline: Score → Review → Refine → Validate</p>
  <button class="btn primary" onclick="runAction('run-refine', this)">Refine Now</button>
  <div id="status-refine" class="status-msg"></div>
</div>

<div class="card">
  <h3>4. Refresh Content</h3>
  <p style="font-size:12px;color:#8a92a0">Checks resource links and reviews if content is still current.</p>
  <p style="font-size:12px">Last run: {esc(last_refresh)}</p>
  <p style="font-size:12px">Templates to check: <strong>{template_count}</strong></p>
  <button class="btn primary" onclick="runAction('run-refresh', this)">Run Refresh Now</button>
  <div id="status-refresh" class="status-msg"></div>
</div>

</div>

<h2>Pipeline Status</h2>
<div id="norm-data"><em style="color:#8a92a0">Loading pipeline stats...</em></div>

<h2>Template Quality Scores</h2>
<div id="quality-data"><em style="color:#8a92a0">Scoring templates...</em></div>

<script>
// Load normalization stats inline
(async function() {{
  try {{
    const resp = await fetch('/admin/pipeline/api/normalization', {{credentials: 'same-origin'}});
    const d = await resp.json();
    const disc = d.discovery, gen = d.generation, ref = d.refresh, cache = d.cache;

    const linkPct = ref.total_links > 0 ? Math.round(ref.ok_links / ref.total_links * 100) : 100;
    const catHtml = disc.categories.map(c =>
      `<span style="display:inline-block;background:#0f1419;padding:2px 8px;border-radius:10px;font-size:12px;margin:2px">${{c.category}} <strong>${{c.count}}</strong></span>`
    ).join('');

    let topicRows = '';
    for (const t of gen.per_topic) {{
      const cls = t.status === 'generated' ? 'approved' : t.status === 'approved' ? 'pending' : 'rejected';
      topicRows += `<tr>
        <td style="max-width:250px;overflow:hidden;text-overflow:ellipsis">${{t.topic}}</td>
        <td>${{t.variants}}/5</td>
        <td><span class="badge ${{cls}}">${{t.status}}</span></td>
        <td style="font-size:12px;color:#d97757;max-width:250px;overflow:hidden;text-overflow:ellipsis">${{t.error}}</td>
      </tr>`;
    }}

    document.getElementById('norm-data').innerHTML = `
      <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px">
        <div class="stat"><div class="num">${{disc.total_topics}}</div><div class="lbl">Topics</div></div>
        <div class="stat"><div class="num">${{disc.status_counts.pending}}</div><div class="lbl">Pending</div></div>
        <div class="stat"><div class="num">${{disc.status_counts.generated}}</div><div class="lbl">Generated</div></div>
        <div class="stat"><div class="num">${{disc.status_counts.rejected}}</div><div class="lbl">Rejected</div></div>
        <div class="stat"><div class="num">${{gen.templates_on_disk}}</div><div class="lbl">Templates</div></div>
        <div class="stat"><div class="num">${{disc.avg_confidence}}</div><div class="lbl">Avg Score</div></div>
        <div class="stat"><div class="num" style="color:${{linkPct < 80 ? '#d97757' : '#6db585'}}">${{linkPct}}%</div><div class="lbl">Link Health</div></div>
        <div class="stat"><div class="num">${{cache.total_files}}</div><div class="lbl">Cached</div></div>
      </div>
      <div style="margin-bottom:16px">${{catHtml || ''}}</div>
      ${{topicRows ? '<h3 style="margin-top:8px">Generation by Topic</h3><div style="max-height:300px;overflow-y:auto"><table><tr><th>Topic</th><th>Variants</th><th>Status</th><th>Errors</th></tr>' + topicRows + '</table></div>' : ''}}

      <h2 style="margin-top:32px;font-family:Fraunces,Georgia,serif;color:#e8a849;font-size:18px">Pipeline Stages</h2>
      <p style="font-size:12px;color:#8a92a0;margin-bottom:4px">Every topic goes through these stages before becoming a course. Stages marked with <span style="color:#e8a849">AI</span> use AI providers and consume budget.</p>
      <p style="font-size:12px;color:#6a7280;margin-bottom:14px"><span style="color:#e8a849">■</span> Data cleanup · <span style="color:#5d9be8">■</span> AI enrichment · <span style="color:#6db585">■</span> Process control · <span style="color:#d97757">■</span> Maintenance</p>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
        <div style="background:#1d242e;padding:16px 18px;border-radius:6px;border-left:3px solid #e8a849">
          <div style="font-size:14px;font-weight:600;margin-bottom:6px">1. Name Normalization</div>
          <div style="font-size:12px;color:#8a92a0;line-height:1.5">Cleans topic names — lowercased, special characters removed, creates a unique key. Prevents "LLMs" and "llms" from creating duplicates.</div>
        </div>
        <div style="background:#1d242e;padding:16px 18px;border-radius:6px;border-left:3px solid #e8a849">
          <div style="font-size:14px;font-weight:600;margin-bottom:6px">2. Deduplication</div>
          <div style="font-size:12px;color:#8a92a0;line-height:1.5">Checks if a topic already exists by its normalized name. Duplicates are skipped silently. Safe to re-run discovery.</div>
        </div>
        <div style="background:#1d242e;padding:16px 18px;border-radius:6px;border-left:3px solid #5d9be8">
          <div style="font-size:14px;font-weight:600;margin-bottom:6px"><span style="color:#e8a849">AI</span> 3. Topic Discovery</div>
          <div style="font-size:12px;color:#8a92a0;line-height:1.5">AI researches trending topics from universities, papers, and industry. Uses the research model (Gemini/Groq/Mistral) from the fallback chain. Costs ~3,000 tokens per run.</div>
        </div>
        <div style="background:#1d242e;padding:16px 18px;border-radius:6px;border-left:3px solid #5d9be8">
          <div style="font-size:14px;font-weight:600;margin-bottom:6px"><span style="color:#e8a849">AI</span> 4. Triage Classifier</div>
          <div style="font-size:12px;color:#8a92a0;line-height:1.5">A cheap, fast AI classifier filters each topic: "Worth generating a course?" Uses the cheapest available model (Groq). Costs ~200 tokens per topic. Filters ~80% of low-value topics.</div>
        </div>
        <div style="background:#1d242e;padding:16px 18px;border-radius:6px;border-left:3px solid #5d9be8">
          <div style="font-size:14px;font-weight:600;margin-bottom:6px"><span style="color:#e8a849">AI</span> 5. Curriculum Generation</div>
          <div style="font-size:12px;color:#8a92a0;line-height:1.5">AI creates full study plans — weeks, resources, checklists, deliverables. Generates up to 5 variants per topic (3mo/6mo × levels). Costs ~5,000 tokens per variant. The most expensive stage.</div>
        </div>
        <div style="background:#1d242e;padding:16px 18px;border-radius:6px;border-left:3px solid #5d9be8">
          <div style="font-size:14px;font-weight:600;margin-bottom:6px"><span style="color:#e8a849">AI</span> 6. Currency Review</div>
          <div style="font-size:12px;color:#8a92a0;line-height:1.5">During content refresh, AI reviews each template: "Is this content still current?" Checks if topics, frameworks, or best practices have changed. Flags stale content for update.</div>
        </div>
        <div style="background:#1d242e;padding:16px 18px;border-radius:6px;border-left:3px solid #6db585">
          <div style="font-size:14px;font-weight:600;margin-bottom:6px">7. Schema Validation</div>
          <div style="font-size:12px;color:#8a92a0;line-height:1.5">Every AI response is validated against a strict schema — required fields, value ranges, correct types. Malformed data is rejected and the next provider is tried.</div>
        </div>
        <div style="background:#1d242e;padding:16px 18px;border-radius:6px;border-left:3px solid #6db585">
          <div style="font-size:14px;font-weight:600;margin-bottom:6px">8. Lifecycle State Machine</div>
          <div style="font-size:12px;color:#8a92a0;line-height:1.5"><strong>Pending</strong> → <strong>Approved</strong> → <strong>Generating</strong> → <strong>Generated</strong>. Each transition is tracked. Topics can be <strong>Rejected</strong> and later re-approved.</div>
        </div>
        <div style="background:#1d242e;padding:16px 18px;border-radius:6px;border-left:3px solid #d97757">
          <div style="font-size:14px;font-weight:600;margin-bottom:6px">9. Budget Gating</div>
          <div style="font-size:12px;color:#8a92a0;line-height:1.5">&lt;80%: normal · 80-90%: warning · 90-100%: fallback to cheaper models · &gt;100%: hard stop. Checked before every AI call.</div>
        </div>
        <div style="background:#1d242e;padding:16px 18px;border-radius:6px;border-left:3px solid #d97757">
          <div style="font-size:14px;font-weight:600;margin-bottom:6px">10. Cache &amp; Link Health</div>
          <div style="font-size:12px;color:#8a92a0;line-height:1.5">AI responses cached (24h–30d TTL). Resource URLs checked periodically — broken links flagged, private IPs blocked (SSRF protection).</div>
        </div>
      </div>
    `;
  }} catch(e) {{
    document.getElementById('norm-data').innerHTML = '<p style="color:#d97757">Failed to load stats</p>';
  }}
}})();

// Load quality scores
(async function() {{
  try {{
    const resp = await fetch('/admin/pipeline/api/quality', {{credentials: 'same-origin'}});
    const data = await resp.json();
    if (!data.length) {{
      document.getElementById('quality-data').innerHTML = '<p style="color:#8a92a0">No templates to score yet.</p>';
      return;
    }}

    // Summary stats
    const avg = Math.round(data.reduce((s, t) => s + t.composite_score, 0) / data.length);
    const lowest = data[0];
    const highest = data[data.length - 1];
    const issueCount = data.reduce((s, t) => s + (t.issues || []).length, 0);

    function scoreColor(s) {{ return s >= 70 ? '#6db585' : s >= 40 ? '#e8a849' : '#d97757'; }}
    function bar(score, label) {{
      return `<div style="display:flex;align-items:center;gap:6px;margin:2px 0">
        <span style="font-size:12px;color:#8a92a0;width:70px">${{label}}</span>
        <div style="flex:1;background:#0f1419;border-radius:2px;height:8px;max-width:120px">
          <div style="width:${{score}}%;height:100%;background:${{scoreColor(score)}};border-radius:2px"></div>
        </div>
        <span style="font-size:12px;color:${{scoreColor(score)}}">${{score}}</span>
      </div>`;
    }}

    let rows = '';
    for (const t of data) {{
      const c = t.composite_score;
      const s = t.scores || {{}};
      const d = t.details || {{}};
      const issueList = (t.issues || []).slice(0, 3).map(i =>
        `<div style="font-size:12px;color:#d97757">• ${{i}}</div>`
      ).join('');
      const pub = t.publish_status === 'published';
      const canPublish = t.publishable;
      const statusBadge = pub
        ? '<span style="background:#1d3525;color:#6db585;padding:2px 8px;border-radius:10px;font-size:11px">Published</span>'
        : '<span style="background:#2a2520;color:#e8a849;padding:2px 8px;border-radius:10px;font-size:11px">Draft</span>';
      const pubBtn = pub
        ? `<button class="btn" style="font-size:11px;padding:4px 10px;margin-top:4px" onclick="togglePublish('${{t.key}}','unpublish',this)">Unpublish</button>`
        : (canPublish
          ? `<button class="btn primary" style="font-size:11px;padding:4px 10px;margin-top:4px" onclick="togglePublish('${{t.key}}','publish',this)">Publish</button>`
          : `<div style="font-size:11px;color:#8a92a0;margin-top:4px">Score &lt; ${{t.publish_threshold}} — fix issues first</div>`);
      rows += `<tr>
        <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis">
          <strong><a href="/admin/templates/${{t.key}}" style="color:#e8a849">${{t.title || t.key}}</a></strong>
          <div style="font-size:12px;color:#8a92a0">${{t.level}} · ${{t.duration_months}}mo · ${{d.total_weeks || 0}} weeks</div>
          <div style="margin-top:4px">${{statusBadge}}</div>
          ${{pubBtn}}
        </td>
        <td style="text-align:center"><span style="font-size:20px;font-family:'Fraunces',serif;color:${{scoreColor(c)}}">${{c}}</span></td>
        <td style="min-width:200px">
          ${{bar(s.blooms_progression || 0, "Bloom's")}}
          ${{bar(s.theory_practice || 0, 'Theory/Practice')}}
          ${{bar(s.project_density || 0, 'Projects')}}
          ${{bar(s.assessment_quality || 0, 'Assessment')}}
          ${{bar(s.completeness || 0, 'Completeness')}}
          ${{bar(s.difficulty_calibration || 0, 'Difficulty')}}
          ${{bar(s.industry_alignment || 0, 'Industry')}}
          ${{bar(s.freshness || 0, 'Freshness')}}
          ${{bar(s.prerequisites_clarity || 0, 'Prerequisites')}}
          ${{bar(s.real_world_readiness || 0, 'Readiness')}}
          <div style="border-top:1px solid #333;margin:4px 0;padding-top:4px">
          ${{bar(s.structure || 0, 'Structure')}}
          ${{bar(s.resources || 0, 'Resources')}}
          ${{bar(s.checklist || 0, 'Checklist')}}
          ${{bar(s.progression || 0, 'Progression')}}
          ${{bar(s.links || 0, 'Links')}}
          </div>
        </td>
        <td style="font-size:12px">
          ${{d.practice_pct || 0}}% practice · ${{d.project_density_pct || 0}}% projects
          <div style="color:#8a92a0">${{d.total_resources || 0}} resources · ${{d.unique_domains || 0}} domains · ${{d.reputable_pct || 0}}% reputable</div>
          <div style="color:#8a92a0">${{d.completeness_pct || 0}}% topics · ${{d.measurable_pct || 0}}% measurable</div>
          <div style="color:#6db585;font-size:11px">${{(d.industry_tools || []).slice(0,5).join(', ')}}</div>
        </td>
        <td style="max-width:250px">${{issueList || '<span style="color:#6db585;font-size:12px">No issues</span>'}}</td>
      </tr>`;
    }}

    document.getElementById('quality-data').innerHTML = `
      <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px">
        <div class="stat"><div class="num" style="color:${{scoreColor(avg)}}">${{avg}}</div><div class="lbl">Avg Score</div></div>
        <div class="stat"><div class="num">${{data.length}}</div><div class="lbl">Templates</div></div>
        <div class="stat"><div class="num" style="color:#d97757">${{issueCount}}</div><div class="lbl">Total Issues</div></div>
        <div class="stat"><div class="num" style="color:${{scoreColor(lowest.composite_score)}}">${{lowest.composite_score}}</div><div class="lbl">Lowest</div></div>
        <div class="stat"><div class="num" style="color:${{scoreColor(highest.composite_score)}}">${{highest.composite_score}}</div><div class="lbl">Highest</div></div>
      </div>
      <div style="max-height:500px;overflow-y:auto">
      <table>
        <tr><th>Template</th><th>Score</th><th>Breakdown</th><th>Details</th><th>Issues</th></tr>
        ${{rows}}
      </table>
      </div>
    `;
  }} catch(e) {{
    document.getElementById('quality-data').innerHTML = '<p style="color:#d97757">Failed to load: ' + e.message + '</p>';
  }}
}})();


async function runAction(action, btn) {{
  btn.disabled = true;
  const origText = btn.textContent;
  btn.textContent = 'Running...';
  const statusEl = document.getElementById('status-' + action.replace('run-', ''));
  statusEl.textContent = 'Processing... this may take 30-60 seconds.';
  statusEl.className = 'status-msg';
  try {{
    const resp = await fetch('/admin/pipeline/api/' + action, {{
      method: 'POST', credentials: 'same-origin'
    }});
    const data = await resp.json();
    if (resp.ok && data.status !== 'ai_error' && data.status !== 'budget_exceeded') {{
      let msg = '';
      if (data.total_discovered !== undefined) msg = data.total_discovered + ' topic(s) discovered, ' + data.saved + ' saved';
      else if (data.generated !== undefined) msg = data.generated + ' curricula generated, ' + data.errors + ' failed';
      else if (data.improved !== undefined) msg = data.improved + ' improved, ' + data.skipped + ' skipped, ' + data.failed + ' failed';
      else msg = JSON.stringify(data).substring(0, 150);
      statusEl.textContent = '✓ ' + msg;
      statusEl.className = 'status-msg ok';
      setTimeout(() => window.location.reload(), 2000);
    }} else {{
      statusEl.textContent = '✗ ' + (data.error || data.detail || 'Failed');
      statusEl.className = 'status-msg error';
    }}
  }} catch(e) {{
    statusEl.textContent = '✗ ' + e.message;
    statusEl.className = 'status-msg error';
  }}
  btn.disabled = false;
  btn.textContent = origText;
}}

async function togglePublish(key, action, btn) {{
  btn.disabled = true;
  btn.textContent = 'Working...';
  try {{
    const resp = await fetch('/admin/pipeline/api/quality/' + key + '/' + action, {{
      method: 'POST', credentials: 'same-origin'
    }});
    const data = await resp.json();
    if (resp.ok) {{
      window.location.reload();
    }} else {{
      alert(data.detail || 'Failed: ' + JSON.stringify(data));
      btn.disabled = false;
      btn.textContent = action === 'publish' ? 'Publish' : 'Unpublish';
    }}
  }} catch(e) {{
    alert('Error: ' + e.message);
    btn.disabled = false;
    btn.textContent = action === 'publish' ? 'Publish' : 'Unpublish';
  }}
}}
</script>
</div>
</body></html>"""


@router.get("/topics", response_class=HTMLResponse)
async def pipeline_topics_page(
    status: str = Query("", description="Filter by status"),
    page: int = Query(1, ge=1),
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Discovered topics management page (paginated)."""
    query = select(DiscoveredTopic).order_by(DiscoveredTopic.created_at.desc())
    if status:
        query = query.where(DiscoveredTopic.status == status)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (await db.execute(query.offset((page - 1) * 50).limit(50))).scalars().all()

    # Compute quality scores for each topic.
    # For topics that already generated templates (status=generated), the
    # template's quality score (0-100, 15-dim curriculum scorer) is far more
    # meaningful than the topic-evidence score (7-dim, driven by justification
    # length and source count — which is always low for manual uploads).
    # Prefer template score when available.
    from app.services.quality_scorer import score_topic
    from app.curriculum.loader import list_templates, get_template_status
    import re as _re

    _all_keys = list_templates()
    def _avg_template_score_for(topic):
        # Candidate slugs derived from the topic's identifiers. We match a
        # template key iff the key's TOPIC PART (everything before the final
        # "_<N>mo_<level>" suffix) equals the candidate — this is robust to
        # topic_name carrying a "— Level X-Month Roadmap" tail.
        candidates = set()
        for raw in (topic.topic_name, topic.normalized_name):
            if not raw:
                continue
            # Strip any "— Level X-Month Roadmap" style suffix
            head = _re.split(r"\s+[—\-–]\s+", raw, maxsplit=1)[0]
            for s in (raw, head):
                candidates.add(_re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_"))

        scores = []
        for k in _all_keys:
            # Extract the topic portion of the key (strip "_<N>mo_<level>")
            m = _re.match(r"^(.+)_(\d+)mo_(beginner|intermediate|advanced)$", k)
            key_topic = m.group(1) if m else k
            for cand in candidates:
                if not cand:
                    continue
                if key_topic == cand or key_topic.startswith(cand) or cand.startswith(key_topic):
                    meta = get_template_status(k) or {}
                    s = int(meta.get("quality_score") or 0)
                    if s:
                        scores.append(s)
                    break
        return round(sum(scores) / len(scores)) if scores else None

    topic_scores = {}
    for t in rows:
        base = score_topic(t)
        tpl_score = _avg_template_score_for(t) if t.status in ("generated", "generating") else None
        if tpl_score is not None:
            base["composite_score"] = tpl_score
            base["issues"] = [f"Average of {len([k for k in _all_keys if k.startswith(_re.sub(r'[^a-z0-9]+', '_', (t.topic_name or '').lower()).strip('_'))])} template(s) · curriculum scorer (15 dims)"] + list(base.get("issues", []))
        topic_scores[t.id] = base

    # Status filter links
    statuses = ["", "pending", "approved", "generating", "generated", "rejected"]
    filter_html = " ".join(
        f'<a href="/admin/pipeline/topics?status={s}" class="btn {"primary" if s == status else ""}">{s or "All"}</a>'
        for s in statuses
    )

    rows_html = ""
    for t in rows:
        sources = []
        try:
            sources = json.loads(t.evidence_sources) if t.evidence_sources else []
        except Exception:
            pass
        sources_str = ", ".join(sources[:3])

        actions = ""
        if t.status == "pending":
            actions = f'''<button class="btn success" onclick="topicAction({t.id},'approve')">Approve</button>
                         <button class="btn danger" onclick="topicAction({t.id},'reject')">Reject</button>'''
        elif t.status == "approved":
            actions = f'<button class="btn danger" onclick="topicAction({t.id},\'reject\')">Reject</button>'
        elif t.status == "rejected":
            actions = f'<button class="btn success" onclick="topicAction({t.id},\'approve\')">Re-approve</button>'

        actions += f' <button class="btn" onclick="deleteTopic({t.id})" title="Delete">×</button>'

        error_html = ""
        if t.generation_error:
            error_html = f'<div style="color:#d97757;font-size:12px;margin-top:2px">{esc(t.generation_error[:100])}</div>'

        rows_html += f"""<tr>
<td>{t.id}</td>
<td><strong><a href="#" onclick="viewTopic({t.id});return false" style="color:#e8a849">{esc(t.topic_name)}</a></strong><div style="font-size:12px;color:#8a92a0">{esc(t.category)}{(' / ' + esc(t.subcategory)) if t.subcategory else ''}</div></td>
<td style="font-size:12px;max-width:300px">{esc(t.justification[:150])}{'...' if len(t.justification) > 150 else ''}</td>
<td><span title="AI's confidence this topic is relevant, trending, and non-duplicate (0–100). Treat this as a hint — read the justification to make your call. ≥70 is usually safe to approve." style="cursor:help;border-bottom:1px dotted #5a6472">{t.confidence_score}</span></td>
<td style="text-align:center">{_topic_quality_cell(topic_scores.get(t.id, {}))}</td>
<td><span class="badge {t.status}">{t.status}</span>{error_html}</td>
<td>{t.templates_generated}</td>
<td style="font-size:12px">{fmt_ist(t.created_at, FMT_DATE, default='')}</td>
<td>{actions}</td>
</tr>"""

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Topics</title>
<style>{ADMIN_CSS}</style></head><body>
{NAV_HTML}
<div class="page">
<h1>Discovered Topics ({len(rows)})</h1>
<div class="subtitle">AI-discovered trending topics for curriculum generation</div>
{workflow_steps(1)}
<div style="background:#1d242e;border-left:3px solid #e8a849;padding:12px 16px;border-radius:4px;margin:12px 0 16px;font-size:13px;line-height:1.6">
  <div style="color:#e8a849;font-weight:600;margin-bottom:6px">Your workflow — what to do on this page</div>
  <ol style="margin:0 0 8px 18px;padding:0;color:#d0cbc2">
    <li><strong>Wait for topics to appear</strong> — Discovery runs on the <a href="/admin/pipeline/" style="color:#e8a849">Pipeline</a> schedule (weekly/monthly/quarterly) or when you click <em>Run Discovery Now</em>.</li>
    <li><strong>Read the justification</strong> — this is your primary signal. It explains why AI thinks the topic is valuable (trend, sources, audience). The score alone is not enough.</li>
    <li><strong>Glance at the confidence score</strong> — a hint, not a verdict. <span style="color:#6db585">≥70</span> is usually safe; below that, scrutinise.</li>
    <li><strong>Approve or Reject</strong> in the Actions column. Delete (×) removes obvious noise or duplicates.</li>
    <li><strong>Re-approve</strong> a rejected topic anytime (same button reappears).</li>
    <li><strong>Generation</strong> happens next — approved topics are picked up by <a href="/admin/pipeline/" style="color:#e8a849">Pipeline → Generate</a> (auto on schedule, or click to trigger now). 5 template variants are created per topic.</li>
    <li><strong>Review output</strong> on the <a href="/admin/templates" style="color:#e8a849">Templates</a> tab — check quality, refine if needed, publish when ≥ 90.</li>
  </ol>
  <div style="color:#8a92a0;font-size:12px">Status flow: <span class="badge pending" style="padding:1px 6px;border-radius:3px;background:#2a2520;color:#e8a849">pending</span> → <span class="badge approved" style="padding:1px 6px;border-radius:3px;background:#1d3525;color:#6db585">approved</span> → <span style="color:#d0cbc2">generating</span> → <span style="color:#d0cbc2">generated</span>. Enable <em>auto-approve</em> in Pipeline Settings to skip step 4 for trusted runs.</div>
</div>
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;gap:12px;flex-wrap:wrap">
  <div>{filter_html}</div>
  <div style="display:flex;gap:8px;align-items:center">
    <a href="/admin/pipeline/api/sample-template" download="sample-template.json" style="font-size:12px;color:#8a92a0;text-decoration:underline">Sample JSON</a>
    <button class="btn" onclick="document.getElementById('promptModal').style.display='flex'" title="Fill topic/duration/level, Generate, Copy, paste into Claude.ai">Claude prompt</button>
    <button class="btn primary" onclick="document.getElementById('uploadModal').style.display='flex'">+ Upload Template JSON</button>
  </div>
</div>

<!-- Claude prompt generator modal -->
<div id="promptModal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.7);z-index:100;align-items:center;justify-content:center">
  <div style="background:#1d242e;border-radius:8px;padding:24px;max-width:780px;width:90%;max-height:85vh;overflow-y:auto;color:#d0cbc2">
    <button onclick="document.getElementById('promptModal').style.display='none'" style="float:right;cursor:pointer;font-size:20px;color:#8a92a0;background:none;border:none">&times;</button>
    <h2 style="margin-top:0;color:#e8a849">Generate Claude prompt</h2>
    <p style="color:#8a92a0;font-size:13px;line-height:1.6;margin-bottom:10px">
      Create a curriculum manually via Claude.ai (free under your Max plan) and upload the JSON for auto-publish. The generated prompt embeds the full Opus 4.6 spec — schema, level-calibrated load, Bloom's progression, action-verb + measurability thresholds, URL-quality rules, top-3 resources, certifications, 12-point self-check.
    </p>
    <details style="background:#0f1419;border:1px solid #2a323d;border-radius:4px;padding:10px 14px;margin-bottom:12px;font-size:13px;line-height:1.6">
      <summary style="cursor:pointer;color:#e8a849;font-weight:600;user-select:none">End-to-end steps (click to expand)</summary>
      <ol style="margin:10px 0 4px 18px;padding:0;color:#d0cbc2">
        <li><strong>Fill inputs</strong> — enter Topic (e.g. <em>Retrieval-Augmented Generation</em>), pick Duration and Level.</li>
        <li><strong>Click Generate</strong> — the full prompt appears in the textarea. Meta line confirms key + expected week count.</li>
        <li><strong>Click Copy prompt</strong> — clipboard gets the whole thing.</li>
        <li><strong>Click Open Claude.ai ↗</strong> — opens a new tab. Start a fresh conversation, use <strong>Claude Opus 4.6</strong> (model picker top-right). Paste and send.</li>
        <li><strong>Wait ~60–90s</strong> — Claude returns a raw JSON object. If it wrapped it in <code>```json</code>, that's fine — our paste parser strips fences automatically.</li>
        <li><strong>Copy Claude's entire response</strong> — triple-click, Ctrl+A in the message, or just copy the whole chat bubble.</li>
        <li><strong>Come back to this page</strong> (Topics tab) and click <strong>+ Upload Template JSON</strong>.</li>
        <li><strong>Switch to "Paste from Claude" tab</strong> in the upload modal.</li>
        <li><strong>Paste</strong> — a green preview line confirms title, key, level, duration, month + week counts. Red means parse error; fix and retry.</li>
        <li><strong>Leave "Auto-publish if score ≥ 90" ticked</strong> (default). Tick "Overwrite existing" only if replacing a template with the same key.</li>
        <li><strong>Click Upload</strong> — backend validates schema, scores across 15 quality dimensions, auto-publishes if ≥ 90.</li>
        <li><strong>Done</strong> — success banner shows: uploaded, hours, score, published. Page reloads; template is live on the <a href="/admin/templates" style="color:#e8a849">Templates</a> tab.</li>
      </ol>
      <div style="margin-top:8px;color:#8a92a0;font-size:12px">
        <strong>If score &lt; 90:</strong> template lands as Draft. Use the per-row <em>Refine</em> button on Templates, or edit the JSON and re-upload with <em>Overwrite existing</em>. If Claude cuts off mid-JSON, start a new chat and ask it to continue from the last valid object.<br>
        <strong>Cost:</strong> zero — Claude Max chat is unmetered; the platform does one free OpenAI embedding call for the similarity guardrail.
      </div>
    </details>
    <div style="display:grid;grid-template-columns:2fr 1fr 1fr auto;gap:8px;align-items:end;margin-bottom:12px">
      <div><label style="font-size:11px;text-transform:uppercase;letter-spacing:0.1em;color:#8a92a0;display:block;margin-bottom:4px">Topic</label>
        <input id="ptTopic" placeholder="e.g. Retrieval-Augmented Generation" style="width:100%;padding:8px;background:#0f1419;border:1px solid #2a323d;color:#f5f1e8;border-radius:3px"></div>
      <div><label style="font-size:11px;text-transform:uppercase;letter-spacing:0.1em;color:#8a92a0;display:block;margin-bottom:4px">Duration</label>
        <select id="ptDuration" style="width:100%;padding:8px;background:#0f1419;border:1px solid #2a323d;color:#f5f1e8;border-radius:3px"><option value="3">3 months</option><option value="6" selected>6 months</option><option value="9">9 months</option><option value="12">12 months</option></select></div>
      <div><label style="font-size:11px;text-transform:uppercase;letter-spacing:0.1em;color:#8a92a0;display:block;margin-bottom:4px">Level</label>
        <select id="ptLevel" style="width:100%;padding:8px;background:#0f1419;border:1px solid #2a323d;color:#f5f1e8;border-radius:3px"><option value="beginner">Beginner</option><option value="intermediate" selected>Intermediate</option><option value="advanced">Advanced</option></select></div>
      <button class="btn primary" onclick="generateClaudePrompt()">Generate</button>
    </div>
    <div id="promptMeta" style="font-size:12px;color:#8a92a0;min-height:18px"></div>
    <textarea id="promptOutput" readonly placeholder="Prompt will appear here. Copy, paste into Claude.ai chat." style="width:100%;min-height:300px;padding:10px;background:#0f1419;border:1px solid #2a323d;color:#e8e2d3;border-radius:3px;font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:12px;line-height:1.5;resize:vertical;margin-top:8px"></textarea>
    <div style="display:flex;gap:8px;justify-content:space-between;margin-top:12px;flex-wrap:wrap">
      <button class="btn danger" onclick="clearPrompt()" title="Reset inputs and clear output">Clear</button>
      <div style="display:flex;gap:8px">
        <button class="btn success" onclick="copyPromptToClipboard()">Copy prompt</button>
        <a href="https://claude.ai" target="_blank" class="btn" style="text-decoration:none">Open Claude.ai ↗</a>
        <button class="btn" onclick="document.getElementById('promptModal').style.display='none'">Close</button>
      </div>
    </div>
  </div>
</div>

<!-- Upload modal -->
<div id="uploadModal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.7);z-index:100;align-items:center;justify-content:center">
  <div style="background:#1d242e;border-radius:8px;padding:24px;max-width:640px;width:90%;max-height:80vh;overflow-y:auto;color:#d0cbc2">
    <button onclick="document.getElementById('uploadModal').style.display='none'" style="float:right;cursor:pointer;font-size:20px;color:#8a92a0;background:none;border:none">&times;</button>
    <h2 style="margin-top:0;color:#e8a849">Upload Template JSON</h2>
    <p style="color:#8a92a0;font-size:13px;line-height:1.6">
      Upload a fully-formed curriculum (same schema as AI-generated). Validated, saved, and a Topic row is created with status <code>generated</code>. <a href="/admin/pipeline/api/sample-template" download="sample-template.json" style="color:#e8a849">Sample JSON</a>.
    </p>
    <div style="display:flex;gap:4px;margin-bottom:8px;border-bottom:1px solid #2a323d">
      <button id="tabFile" class="tab-btn active" onclick="switchUploadTab('file')" style="padding:8px 16px;background:none;border:none;color:#e8a849;font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:11px;letter-spacing:0.1em;text-transform:uppercase;border-bottom:2px solid #e8a849;cursor:pointer">File upload</button>
      <button id="tabPaste" class="tab-btn" onclick="switchUploadTab('paste')" style="padding:8px 16px;background:none;border:none;color:#8a92a0;font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:11px;letter-spacing:0.1em;text-transform:uppercase;border-bottom:2px solid transparent;cursor:pointer">Paste from Claude</button>
    </div>
    <div id="panelFile">
      <input type="file" id="uploadFile" accept="application/json,.json" style="margin:12px 0;color:#d0cbc2">
    </div>
    <div id="panelPaste" style="display:none">
      <p style="color:#8a92a0;font-size:12px;line-height:1.5;margin:4px 0 8px">Paste Claude's response — prose, <code>```json</code> fences, and commentary are auto-stripped. First <code>{{...}}</code> block is extracted.</p>
      <textarea id="uploadPaste" placeholder='Paste Claude response here. Example:
```json
{{ "key": "...", "title": "...", "months": [...] }}
```
(fences optional)' style="width:100%;min-height:200px;padding:10px;background:#0f1419;border:1px solid #2a323d;color:#e8e2d3;border-radius:3px;font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:12px;line-height:1.5;resize:vertical" oninput="previewPaste()"></textarea>
    </div>
    <div id="uploadPreview" style="margin:10px 0;font-size:12px;color:#8a92a0;min-height:18px"></div>
    <div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap">
      <label style="font-size:13px;color:#d0cbc2"><input type="checkbox" id="uploadOverwrite"> Overwrite existing</label>
      <label style="font-size:13px;color:#d0cbc2" title="After upload, run quality check. If score >= 90, auto-publish."><input type="checkbox" id="uploadAutoPublish" checked> Auto-publish if score ≥ 90</label>
    </div>
    <div id="uploadStatus" style="margin:12px 0;font-size:13px;min-height:20px"></div>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">
      <button class="btn" onclick="document.getElementById('uploadModal').style.display='none'">Cancel</button>
      <button class="btn success" onclick="uploadTemplate()">Upload</button>
    </div>
  </div>
</div>

<table>
<tr><th>ID</th><th>Topic</th><th>Justification</th><th>Confidence</th><th>Quality</th><th>Status</th><th>Templates</th><th>Discovered</th><th>Actions</th></tr>
{rows_html}
</table>

<script>
async function topicAction(id, action) {{
  const resp = await fetch('/admin/pipeline/api/topics/' + id + '/' + action, {{
    method: 'POST', credentials: 'same-origin',
    headers: {{'Content-Type': 'application/json'}},
    body: '{{}}'
  }});
  if (resp.ok) window.location.reload();
  else alert('Failed: ' + (await resp.json()).detail);
}}

async function deleteTopic(id) {{
  if (!confirm('Delete this topic?')) return;
  const resp = await fetch('/admin/pipeline/api/topics/' + id, {{
    method: 'DELETE', credentials: 'same-origin'
  }});
  if (resp.ok) window.location.reload();
  else alert('Failed');
}}

async function generateClaudePrompt() {{
  const topic = document.getElementById('ptTopic').value.trim();
  const duration = parseInt(document.getElementById('ptDuration').value, 10);
  const level = document.getElementById('ptLevel').value;
  const meta = document.getElementById('promptMeta');
  const out = document.getElementById('promptOutput');
  if (!topic) {{ meta.innerHTML = '<span style="color:#d97757">Enter a topic first</span>'; return; }}
  meta.textContent = 'Generating…';
  try {{
    const resp = await fetch('/admin/pipeline/api/claude-prompt', {{
      method: 'POST', credentials: 'same-origin',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{topic, duration_months: duration, level}}),
    }});
    const d = await resp.json();
    if (resp.ok) {{
      out.value = d.prompt;
      meta.innerHTML = '<span style="color:#6db585">✓ Ready</span> — key: <code>' + d.key + '</code> · expected weeks: ' + d.expected_weeks;
    }} else {{
      meta.innerHTML = '<span style="color:#d97757">' + (d.detail || resp.statusText) + '</span>';
    }}
  }} catch(e) {{
    meta.innerHTML = '<span style="color:#d97757">' + e.message + '</span>';
  }}
}}

function clearPrompt() {{
  document.getElementById('ptTopic').value = '';
  document.getElementById('ptDuration').value = '6';
  document.getElementById('ptLevel').value = 'intermediate';
  document.getElementById('promptOutput').value = '';
  document.getElementById('promptMeta').textContent = '';
  document.getElementById('ptTopic').focus();
}}

async function copyPromptToClipboard() {{
  const out = document.getElementById('promptOutput');
  const meta = document.getElementById('promptMeta');
  if (!out.value) {{ meta.innerHTML = '<span style="color:#d97757">Nothing to copy</span>'; return; }}
  try {{
    await navigator.clipboard.writeText(out.value);
    meta.innerHTML = '<span style="color:#6db585">✓ Copied to clipboard — paste into Claude.ai chat</span>';
  }} catch {{
    out.select();
    document.execCommand('copy');
    meta.innerHTML = '<span style="color:#6db585">✓ Copied (fallback)</span>';
  }}
}}

function switchUploadTab(which) {{
  const file = document.getElementById('panelFile'), paste = document.getElementById('panelPaste');
  const tF = document.getElementById('tabFile'), tP = document.getElementById('tabPaste');
  if (which === 'file') {{
    file.style.display = ''; paste.style.display = 'none';
    tF.style.color = '#e8a849'; tF.style.borderBottomColor = '#e8a849';
    tP.style.color = '#8a92a0'; tP.style.borderBottomColor = 'transparent';
  }} else {{
    file.style.display = 'none'; paste.style.display = '';
    tP.style.color = '#e8a849'; tP.style.borderBottomColor = '#e8a849';
    tF.style.color = '#8a92a0'; tF.style.borderBottomColor = 'transparent';
  }}
  document.getElementById('uploadPreview').textContent = '';
  document.getElementById('uploadStatus').textContent = '';
}}

// Extract a JSON object from a text blob that may include markdown fences,
// Claude's preamble/commentary, trailing prose, etc. Returns {{ok, parsed, raw, err}}.
function smartExtractJSON(text) {{
  if (!text || !text.trim()) return {{ok: false, err: 'Empty'}};
  let t = text.trim();
  // Strip ```json ... ``` or ``` ... ```
  const fence = t.match(/```(?:json)?\\s*([\\s\\S]*?)```/i);
  if (fence) t = fence[1].trim();
  // Find first and last braces
  const first = t.indexOf('{{');
  const last = t.lastIndexOf('}}');
  if (first < 0 || last < 0 || last < first) return {{ok: false, err: 'No JSON object found'}};
  const raw = t.slice(first, last + 1);
  try {{
    return {{ok: true, parsed: JSON.parse(raw), raw}};
  }} catch(e) {{
    return {{ok: false, raw, err: e.message}};
  }}
}}

function previewPaste() {{
  const txt = document.getElementById('uploadPaste').value;
  const prev = document.getElementById('uploadPreview');
  if (!txt.trim()) {{ prev.textContent = ''; return; }}
  const r = smartExtractJSON(txt);
  if (!r.ok) {{
    prev.innerHTML = '<span style="color:#d97757">Cannot parse: ' + r.err + '</span>';
    return;
  }}
  const p = r.parsed;
  const months = Array.isArray(p.months) ? p.months.length : 0;
  const weeks = Array.isArray(p.months) ? p.months.reduce((a,m) => a + (Array.isArray(m.weeks) ? m.weeks.length : 0), 0) : 0;
  prev.innerHTML = '<span style="color:#6db585">✓</span> <strong>' + (p.title || '?') + '</strong> · '
    + '<code>' + (p.key || '?') + '</code> · ' + (p.level || '?') + ' · '
    + (p.duration_months || '?') + 'mo · ' + months + ' months, ' + weeks + ' weeks';
}}

async function uploadTemplate() {{
  const status = document.getElementById('uploadStatus');
  const overwrite = document.getElementById('uploadOverwrite').checked;
  const autoPublish = document.getElementById('uploadAutoPublish').checked;
  const fileTabActive = document.getElementById('panelFile').style.display !== 'none';

  let parsed = null;
  if (fileTabActive) {{
    const fileInput = document.getElementById('uploadFile');
    if (!fileInput.files || !fileInput.files[0]) {{
      status.innerHTML = '<span style="color:#d97757">Pick a JSON file first</span>';
      return;
    }}
    try {{
      const text = await fileInput.files[0].text();
      parsed = JSON.parse(text);
    }} catch(e) {{
      status.innerHTML = '<span style="color:#d97757">Invalid JSON: ' + e.message + '</span>';
      return;
    }}
  }} else {{
    const r = smartExtractJSON(document.getElementById('uploadPaste').value);
    if (!r.ok) {{
      status.innerHTML = '<span style="color:#d97757">Cannot parse pasted JSON: ' + r.err + '</span>';
      return;
    }}
    parsed = r.parsed;
  }}
  parsed.overwrite = overwrite;
  parsed.auto_publish = autoPublish;
  status.textContent = 'Uploading…';
  try {{
    const resp = await fetch('/admin/pipeline/api/topics/upload-template', {{
      method: 'POST', credentials: 'same-origin',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(parsed),
    }});
    const data = await resp.json().catch(() => ({{}}));
    if (resp.ok) {{
      let msg = '✓ ' + data.title + ' uploaded (' + data.weeks + ' weeks, ' + data.hours + 'h)';
      if (typeof data.quality_score !== 'undefined' && data.quality_score !== null) msg += ' · score ' + data.quality_score;
      if (data.published) msg += ' · <strong>published</strong>';
      else if (data.publish_reason) msg += ' · not published (' + data.publish_reason + ')';
      if (Array.isArray(data.pipeline_stages) && data.pipeline_stages.length) {{
        msg += '<div style="color:#8a92a0;font-size:11px;margin-top:4px">stages: ' + data.pipeline_stages.join(' → ') + '</div>';
      }}
      if (Array.isArray(data.cleanup_notes) && data.cleanup_notes.length) {{
        const shown = data.cleanup_notes.slice(0, 3).join('; ');
        const more = data.cleanup_notes.length > 3 ? ` (+${{data.cleanup_notes.length - 3}} more)` : '';
        msg += '<div style="color:#8a92a0;font-size:11px;margin-top:2px">auto-cleaned: ' + shown + more + '</div>';
      }}
      status.innerHTML = '<span style="color:#6db585">' + msg + '. Reloading…</span>';
      setTimeout(() => window.location.reload(), 2500);
    }} else {{
      const detail = (typeof data.detail === 'string' ? data.detail : (data.detail ? JSON.stringify(data.detail) : '')) || resp.statusText || ('HTTP ' + resp.status);
      // 409 = key collision — add a specific hint so admin knows to tick overwrite
      let hint = '';
      if (resp.status === 409) {{
        hint = '<div style="color:#e8a849;font-size:12px;margin-top:6px">&rarr; Tick <strong>Overwrite existing</strong> above and click Upload again.</div>';
      }}
      status.innerHTML = '<div style="color:#d97757;background:#2a1a1a;padding:8px 10px;border-radius:4px;border-left:3px solid #d97757;word-break:break-word">✗ <strong>HTTP ' + resp.status + '</strong> — ' + detail + '</div>' + hint;
    }}
  }} catch(e) {{
    status.innerHTML = '<span style="color:#d97757">Network error: ' + e.message + '</span>';
  }}
}}

async function viewTopic(id) {{
  const modal = document.getElementById('topicModal');
  const content = document.getElementById('topicContent');
  content.innerHTML = 'Loading...';
  modal.style.display = 'flex';
  try {{
    const resp = await fetch('/admin/pipeline/api/topics/' + id, {{credentials: 'same-origin'}});
    const t = await resp.json();
    const sources = (t.evidence_sources || []).map(s => '<li>' + s + '</li>').join('');
    const tplCards = (t.associated_templates || []).map(tp => {{
      const scoreColor = tp.quality_score >= 90 ? '#6db585' : tp.quality_score >= 70 ? '#e8a849' : '#d97757';
      const statusColor = tp.status === 'published' ? '#6db585' : '#e8a849';
      return `
        <div style="background:#0f1419;border:1px solid #2a323d;border-left:3px solid ${{scoreColor}};padding:12px 14px;border-radius:4px;margin-bottom:8px">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:6px">
            <a href="/admin/templates/${{tp.key}}" style="color:#e8a849;font-weight:600;font-size:14px;text-decoration:none">${{tp.title}}</a>
            <div style="font-size:11px">
              <span style="color:${{statusColor}};text-transform:uppercase;letter-spacing:0.08em;padding:2px 8px;background:#1d242e;border-radius:3px">${{tp.status}}</span>
              <span style="color:${{scoreColor}};font-weight:600;margin-left:6px">score ${{tp.quality_score || '—'}}</span>
            </div>
          </div>
          <div style="color:#b0aaa0;font-size:12px;margin-bottom:6px;line-height:1.5">${{tp.goal || ''}}</div>
          <div style="color:#8a92a0;font-size:11px;display:flex;gap:14px;flex-wrap:wrap">
            <span>${{tp.level}} · ${{tp.duration_months}}mo</span>
            <span>${{tp.total_weeks}} weeks · ${{tp.total_hours}}h</span>
            <span>${{tp.total_focus_areas}} focus areas</span>
            <span>${{tp.total_checks}} checks</span>
            <span>${{tp.top_resources_count}} anchor resources</span>
            <span>${{tp.certifications_count}} cert(s)</span>
            <span>${{tp.github_resource_count}} GH repos</span>
          </div>
        </div>
      `;
    }}).join('');

    content.innerHTML = `
      <h2 style="color:#e8a849;margin:0 0 12px">${{t.topic_name}}</h2>
      <div style="margin-bottom:12px">
        <span class="badge ${{t.status}}">${{t.status}}</span>
        <span style="color:#8a92a0;margin-left:8px">Confidence: ${{t.confidence_score}}%</span>
        <span style="color:#8a92a0;margin-left:8px">Model: ${{t.ai_model_used || '—'}}</span>
      </div>
      <div style="margin-bottom:12px"><strong style="color:#d0cbc2">Category:</strong> ${{t.category}}${{t.subcategory ? ' / ' + t.subcategory : ''}}</div>
      <div style="margin-bottom:16px"><strong style="color:#d0cbc2">Justification:</strong><p style="color:#b0aaa0;line-height:1.6">${{t.justification}}</p></div>
      ${{sources ? '<div style="margin-bottom:16px"><strong style="color:#d0cbc2">Evidence Sources:</strong><ul style="color:#b0aaa0;padding-left:20px;line-height:1.8">' + sources + '</ul></div>' : ''}}
      ${{tplCards ? '<div style="margin:16px 0"><strong style="color:#d0cbc2;display:block;margin-bottom:8px">Associated templates (' + t.associated_templates.length + '):</strong>' + tplCards + '</div>' : ''}}
      <div style="color:#8a92a0;font-size:12px">Discovered: ${{t.created_at ? t.created_at.substring(0,10) : '—'}} · Templates generated: ${{t.templates_generated}}</div>
      ${{t.generation_error ? '<div style="color:#d97757;font-size:12px;margin-top:8px">Error: ' + t.generation_error.substring(0,200) + '</div>' : ''}}
      <div style="margin-top:16px;padding-top:12px;border-top:1px solid #2a323d">
        ${{t.status === 'pending' ? '<button class="btn success" onclick="topicAction('+t.id+',\\'approve\\');document.getElementById(\\'topicModal\\').style.display=\\'none\\'">Approve</button> <button class="btn danger" onclick="topicAction('+t.id+',\\'reject\\');document.getElementById(\\'topicModal\\').style.display=\\'none\\'">Reject</button>' : ''}}
        ${{t.status === 'approved' ? '<span style="color:#6db585;font-weight:600">✓ Approved</span> — go to Pipeline page and click "Generate Curricula" to create templates' : ''}}
        ${{t.status === 'generated' && (!t.associated_templates || !t.associated_templates.length) ? '<span style="color:#6db585;font-weight:600">✓ Generated</span> — ' + t.templates_generated + ' templates created. Review them in Templates page.' : ''}}
        ${{t.status === 'rejected' ? '<button class="btn success" onclick="topicAction('+t.id+',\\'approve\\');document.getElementById(\\'topicModal\\').style.display=\\'none\\'">Re-approve</button>' : ''}}
      </div>
    `;
  }} catch(e) {{
    content.innerHTML = 'Error: ' + e.message;
  }}
}}

document.getElementById('topicModal').addEventListener('click', function(e) {{
  if (e.target === this) this.style.display = 'none';
}});

</script>

<div id="topicModal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.7);z-index:100;align-items:center;justify-content:center">
  <div style="background:#1d242e;border-radius:8px;padding:24px;max-width:700px;width:90%;max-height:80vh;overflow-y:auto">
    <button onclick="document.getElementById('topicModal').style.display='none'" style="float:right;cursor:pointer;font-size:20px;color:#8a92a0;background:none;border:none">&times;</button>
    <div id="topicContent">Loading...</div>
  </div>
</div>
<div style="margin-top:12px">{'<a href="/admin/pipeline/topics?page='+str(page-1)+'&status='+esc(status)+'" class="btn">Prev</a> ' if page>1 else ''}{'<a href="/admin/pipeline/topics?page='+str(page+1)+'&status='+esc(status)+'" class="btn">Next</a>' if page*50<total else ''} <span style="font-size:12px;color:#8a92a0">{total} total</span></div>
</div>
</body></html>"""


@router.get("/settings", response_class=HTMLResponse)
async def pipeline_settings_page(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Pipeline settings configuration page."""
    s = await _get_settings(db)

    def _sel(field_val: str, option: str) -> str:
        return "selected" if field_val == option else ""

    def _chk(val: bool) -> str:
        return "checked" if val else ""

    budget_pct = 0
    if s.max_tokens_per_run > 0:
        budget_pct = int((s.tokens_used_this_month / s.max_tokens_per_run) * 100)

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Pipeline Settings</title>
<style>{ADMIN_CSS}</style></head><body>
{NAV_HTML}
<div class="page">
<h1>Pipeline Settings</h1>
<div class="subtitle">Configure auto-discovery, AI models, budget, and refresh schedule</div>

<form id="settingsForm" class="card">

<h3>Discovery</h3>
<div class="form-row">
  <div class="form-group">
    <label>Max Topics Per Discovery</label>
    <input type="number" name="max_topics_per_discovery" value="{s.max_topics_per_discovery}" min="1" max="50">
  </div>
  <div class="form-group">
    <label>Discovery Frequency</label>
    <select name="discovery_frequency">
      <option value="weekly" {_sel(s.discovery_frequency, 'weekly')}>Weekly</option>
      <option value="monthly" {_sel(s.discovery_frequency, 'monthly')}>Monthly</option>
      <option value="quarterly" {_sel(s.discovery_frequency, 'quarterly')}>Quarterly</option>
    </select>
  </div>
</div>
<div class="form-row">
  <div class="form-group">
    <label><input type="checkbox" name="auto_approve_topics" {_chk(s.auto_approve_topics)}> Auto-approve discovered topics</label>
    <div style="font-size:11px;color:#8a92a0;margin-top:4px;line-height:1.5">Skips your review on the Topics page — every discovered topic goes straight to "approved". Leave off if you want to curate.</div>
  </div>
  <div class="form-group">
    <label><input type="checkbox" name="auto_generate_variants" {_chk(s.auto_generate_variants)}> Auto-generate variants after approval</label>
    <div style="font-size:11px;color:#8a92a0;margin-top:4px;line-height:1.5">As soon as a topic is approved (by you or auto-approve), queue generation of all level × duration variants. Combined with auto-approve = fully hands-off.</div>
  </div>
</div>

<h3>AI Models</h3>
<div class="form-row">
  <div class="form-group">
    <label>Research Model (deep)</label>
    <select name="ai_model_research">
      <option value="gemini" {_sel(s.ai_model_research, 'gemini')}>Gemini</option>
      <option value="groq" {_sel(s.ai_model_research, 'groq')}>Groq</option>
      <option value="cerebras" {_sel(s.ai_model_research, 'cerebras')}>Cerebras</option>
      <option value="mistral" {_sel(s.ai_model_research, 'mistral')}>Mistral</option>
      <option value="deepseek" {_sel(s.ai_model_research, 'deepseek')}>DeepSeek</option>
      <option value="sambanova" {_sel(s.ai_model_research, 'sambanova')}>Sambanova</option>
    </select>
  </div>
  <div class="form-group">
    <label>Formatting Model (cheap)</label>
    <select name="ai_model_formatting">
      <option value="groq" {_sel(s.ai_model_formatting, 'groq')}>Groq</option>
      <option value="gemini" {_sel(s.ai_model_formatting, 'gemini')}>Gemini</option>
      <option value="cerebras" {_sel(s.ai_model_formatting, 'cerebras')}>Cerebras</option>
      <option value="mistral" {_sel(s.ai_model_formatting, 'mistral')}>Mistral</option>
      <option value="deepseek" {_sel(s.ai_model_formatting, 'deepseek')}>DeepSeek</option>
      <option value="sambanova" {_sel(s.ai_model_formatting, 'sambanova')}>Sambanova</option>
    </select>
  </div>
</div>

<h3>Budget</h3>
<div class="form-row">
  <div class="form-group">
    <label>Max Tokens Per Month</label>
    <input type="number" name="max_tokens_per_run" value="{s.max_tokens_per_run}" min="0" step="1000">
  </div>
  <div class="form-group">
    <label>Current Usage</label>
    <div style="padding:8px;font-size:14px">{s.tokens_used_this_month:,} / {s.max_tokens_per_run:,} ({budget_pct}%)</div>
  </div>
</div>

<h3>Content Refresh</h3>
<div class="form-row">
  <div class="form-group">
    <label>Refresh Frequency</label>
    <select name="refresh_frequency">
      <option value="monthly" {_sel(s.refresh_frequency, 'monthly')}>Monthly</option>
      <option value="quarterly" {_sel(s.refresh_frequency, 'quarterly')}>Quarterly</option>
    </select>
  </div>
</div>

<div style="margin-top:16px">
  <button type="submit" class="btn success" style="padding:10px 24px;font-size:14px">Save Settings</button>
  <span id="saveStatus" class="status-msg" style="margin-left:12px"></span>
</div>

</form>

<script>
document.getElementById('settingsForm').addEventListener('submit', async function(e) {{
  e.preventDefault();
  const form = e.target;
  const data = {{}};
  for (const input of form.querySelectorAll('input, select')) {{
    if (!input.name) continue;
    if (input.type === 'checkbox') data[input.name] = input.checked;
    else if (input.type === 'number') data[input.name] = parseInt(input.value);
    else data[input.name] = input.value;
  }}
  const status = document.getElementById('saveStatus');
  try {{
    const resp = await fetch('/admin/pipeline/api/settings', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      credentials: 'same-origin',
      body: JSON.stringify(data)
    }});
    if (resp.ok) {{
      status.textContent = '✓ Saved';
      status.className = 'status-msg ok';
    }} else {{
      const d = await resp.json();
      status.textContent = '✗ ' + (d.detail || 'Failed');
      status.className = 'status-msg error';
    }}
  }} catch(e) {{
    status.textContent = '✗ ' + e.message;
    status.className = 'status-msg error';
  }}
}});
</script>
</div>
</body></html>"""


# ---- AI Usage API + Page ----

@router.get("/api/ai-usage")
async def get_ai_usage(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get AI usage stats for admin dashboard."""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    from sqlalchemy import case, cast, Float as SAFloat
    from app.ai.health import get_all_health
    from app.ai.pricing import compute_cost, get_price

    now_utc = _dt.now(_tz.utc).replace(tzinfo=None)
    today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    seven_days_ago = now_utc - _td(days=7)
    thirty_days_ago = now_utc - _td(days=30)

    async def _sum_cost(since: _dt) -> float:
        rows = (await db.execute(
            select(
                AIUsageLog.provider, AIUsageLog.model,
                func.sum(AIUsageLog.tokens_estimated).label("tok"),
            ).where(
                AIUsageLog.called_at >= since,
                AIUsageLog.status == "ok",
            ).group_by(AIUsageLog.provider, AIUsageLog.model)
        )).all()
        total = 0.0
        for r in rows:
            in_price, _ = get_price(r.provider, r.model)
            total += ((r.tok or 0) / 1_000_000.0) * in_price
        return total

    cost_today = await _sum_cost(today_start)
    cost_7d = await _sum_cost(seven_days_ago)
    cost_30d = await _sum_cost(thirty_days_ago)

    # Per-provider stats
    provider_stats = (await db.execute(
        select(
            AIUsageLog.provider,
            func.count().label("total_calls"),
            func.sum(case((AIUsageLog.status == "ok", 1), else_=0)).label("success"),
            func.sum(case((AIUsageLog.status == "rate_limited", 1), else_=0)).label("rate_limited"),
            func.sum(case((AIUsageLog.status == "error", 1), else_=0)).label("errors"),
            func.sum(AIUsageLog.tokens_estimated).label("total_tokens"),
            func.avg(AIUsageLog.latency_ms).label("avg_latency_ms"),
        ).group_by(AIUsageLog.provider)
    )).all()

    # Per-task stats
    task_stats = (await db.execute(
        select(
            AIUsageLog.task,
            AIUsageLog.subtask,
            func.count().label("total_calls"),
            func.sum(case((AIUsageLog.status == "ok", 1), else_=0)).label("success"),
            func.sum(case((AIUsageLog.status != "ok", 1), else_=0)).label("failures"),
            func.sum(AIUsageLog.tokens_estimated).label("total_tokens"),
        ).group_by(AIUsageLog.task, AIUsageLog.subtask)
        .order_by(AIUsageLog.task, AIUsageLog.subtask)
    )).all()

    # Recent calls (last 50)
    recent = (await db.execute(
        select(AIUsageLog)
        .order_by(AIUsageLog.called_at.desc())
        .limit(50)
    )).scalars().all()

    # Health state
    health = get_all_health()

    # Cost rollup per provider (all-time, approximate using input price)
    provider_cost_rows = (await db.execute(
        select(
            AIUsageLog.provider, AIUsageLog.model,
            func.sum(AIUsageLog.tokens_estimated).label("tok"),
        ).where(AIUsageLog.status == "ok")
        .group_by(AIUsageLog.provider, AIUsageLog.model)
    )).all()
    provider_cost_map: dict[str, float] = {}
    for r in provider_cost_rows:
        in_price, _ = get_price(r.provider, r.model)
        provider_cost_map[r.provider] = provider_cost_map.get(r.provider, 0.0) + \
            ((r.tok or 0) / 1_000_000.0) * in_price

    # Per-provider reference info.
    # Static technical fields (price, primary model, purpose) come from
    # PROVIDER_INFO constants; admin-editable fields (balance, recommended
    # cap) come from the provider_balance DB table. Admin edits the DB row
    # via the inline UI — no code changes needed.
    from app.ai.pricing import PROVIDER_INFO

    balance_rows = (await db.execute(select(ProviderBalance))).scalars().all()
    balance_map = {b.provider: b for b in balance_rows}
    provider_info = []
    for name, info in PROVIDER_INFO.items():
        b = balance_map.get(name)
        provider_info.append({
            "provider": name,
            **info,
            "balance_usd": b.balance_usd if b else info.get("balance_usd", 0.0),
            "recommended_cap_usd": (b.recommended_cap_usd if b
                                     else info.get("recommended_cap_usd", 0.0)),
            "notes": (b.notes if b else "") or "",
        })

    # Spend-so-far for each paid provider (today, UTC) — used to show progress bars
    spend_today_map: dict[str, float] = {}
    spend_rows_today = (await db.execute(
        select(
            AIUsageLog.provider, AIUsageLog.model,
            func.sum(AIUsageLog.tokens_estimated).label("tok"),
        ).where(
            AIUsageLog.called_at >= today_start,
            AIUsageLog.status == "ok",
        ).group_by(AIUsageLog.provider, AIUsageLog.model)
    )).all()
    for r in spend_rows_today:
        in_price, _ = get_price(r.provider, r.model)
        spend_today_map[r.provider] = spend_today_map.get(r.provider, 0.0) + \
            ((r.tok or 0) / 1_000_000.0) * in_price

    # Daily cost caps
    limit_rows = (await db.execute(select(AICostLimit))).scalars().all()
    limits_list = [
        {
            "id": lim.id,
            "provider": lim.provider,
            "model": lim.model,
            "daily_cost_usd": lim.daily_cost_usd,
            "daily_token_limit": lim.daily_token_limit,
            "notes": lim.notes or "",
        }
        for lim in limit_rows
    ]

    return {
        "cost_summary": {
            "today": round(cost_today, 6),
            "last_7d": round(cost_7d, 6),
            "last_30d": round(cost_30d, 6),
        },
        "limits": limits_list,
        "provider_info": provider_info,
        "spend_today": {k: round(v, 6) for k, v in spend_today_map.items()},
        "provider_stats": [
            {
                "provider": r.provider,
                "total_calls": r.total_calls,
                "success": r.success or 0,
                "rate_limited": r.rate_limited or 0,
                "errors": r.errors or 0,
                "total_tokens": r.total_tokens or 0,
                "avg_latency_ms": int(r.avg_latency_ms or 0),
                "cost_usd": round(provider_cost_map.get(r.provider, 0.0), 6),
            }
            for r in provider_stats
        ],
        "task_stats": [
            {
                "task": r.task,
                "subtask": r.subtask or "",
                "total_calls": r.total_calls,
                "success": r.success or 0,
                "failures": r.failures or 0,
                "total_tokens": r.total_tokens or 0,
            }
            for r in task_stats
        ],
        "recent": [
            {
                "id": r.id,
                "called_at": fmt_ist(r.called_at, default=""),
                "called_at_utc": iso_utc_z(r.called_at),
                "provider": r.provider,
                "model": r.model,
                "task": r.task,
                "subtask": r.subtask or "",
                "status": r.status,
                "error_message": r.error_message or "",
                "tokens_estimated": r.tokens_estimated,
                "latency_ms": r.latency_ms,
                "cost_usd": round(compute_cost(r.provider, r.model, r.tokens_estimated), 6),
            }
            for r in recent
        ],
        "health": {
            name: {
                "available": s.get("available", True),
                "permanent_error": s.get("permanent_error", False),
                "success_count": s.get("success_count", 0),
                "error_count": s.get("error_count", 0),
                "rate_limit_count": s.get("rate_limit_count", 0),
                "last_error_msg": s.get("last_error_msg", ""),
            }
            for name, s in health.items()
        },
    }


@router.get("/api/ai-usage/alerts")
async def list_alerts(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return unresolved admin alerts."""
    rows = (await db.execute(
        select(AdminAlert)
        .where(AdminAlert.resolved_at.is_(None))
        .order_by(AdminAlert.created_at.desc())
    )).scalars().all()
    return {
        "alerts": [
            {
                "id": a.id, "kind": a.kind, "key": a.key,
                "severity": a.severity, "message": a.message,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in rows
        ]
    }


@router.post("/api/ai-usage/alerts/dismiss")
async def dismiss_alert(
    request: Request,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    _check_origin(request)
    body = await request.json()
    alert_id = body.get("id")
    if not alert_id:
        raise HTTPException(status_code=400, detail="id required")
    row = await db.get(AdminAlert, int(alert_id))
    if row is not None:
        from datetime import datetime as _dt, timezone as _tz
        row.resolved_at = _dt.now(_tz.utc).replace(tzinfo=None)
        await db.commit()
    return {"ok": True}


@router.post("/api/ai-usage/alerts/run-checks")
async def run_alert_checks(
    request: Request,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger alert rule evaluation."""
    _check_origin(request)
    from app.services.cost_alerts import run_all_checks
    res = await run_all_checks(db)
    return res


@router.post("/api/ai-usage/sync-now")
async def trigger_sync_now(
    request: Request,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger the daily provider-spend sync (normally runs at 06:00 UTC)."""
    _check_origin(request)
    from app.services.provider_usage_sync import run_daily_sync, archive_old_usage_logs
    sync_res = await run_daily_sync(db)
    arch_res = await archive_old_usage_logs(db)
    return {"sync": sync_res, "archive": arch_res}


@router.get("/api/ai-usage/reconciliation")
async def reconciliation_view(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Compare local ai_usage_log cost vs provider-reported cost (last 30 days)."""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    thirty_days_ago_str = (_dt.now(_tz.utc) - _td(days=30)).date().isoformat()

    rows = (await db.execute(
        select(ProviderDailySpend)
        .where(ProviderDailySpend.day >= thirty_days_ago_str)
        .order_by(ProviderDailySpend.day.desc(),
                   ProviderDailySpend.provider, ProviderDailySpend.model)
    )).scalars().all()

    return {
        "rows": [
            {
                "day": r.day,
                "provider": r.provider,
                "model": r.model,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "cost_provider": round(r.cost_usd_provider, 6),
                "cost_local": round(r.cost_usd_local, 6),
                "drift_pct": r.drift_pct,
            }
            for r in rows
        ],
    }


@router.get("/api/ai-usage/analytics")
async def ai_usage_analytics(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Persistent usage analytics — all-time + monthly + daily, grouped per model.

    Source of truth: ai_usage_log (written on every AI call). Survives deploys,
    container rebuilds, and restarts. Cost computed via ai.pricing.compute_cost
    using real token counts captured from provider API responses.
    """
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    from sqlalchemy import case
    from app.ai.pricing import get_price

    # --- All-time per-model totals ---
    alltime_rows = (await db.execute(
        select(
            AIUsageLog.provider, AIUsageLog.model,
            func.count().label("calls"),
            func.sum(case((AIUsageLog.status == "ok", 1), else_=0)).label("success"),
            func.sum(AIUsageLog.tokens_estimated).label("tokens"),
        )
        .where(AIUsageLog.status == "ok")
        .group_by(AIUsageLog.provider, AIUsageLog.model)
        .order_by(func.sum(AIUsageLog.tokens_estimated).desc())
    )).all()

    alltime = []
    for r in alltime_rows:
        in_p, _ = get_price(r.provider, r.model)
        cost = ((r.tokens or 0) / 1_000_000.0) * in_p
        alltime.append({
            "provider": r.provider, "model": r.model,
            "calls": r.calls, "success": r.success or 0,
            "tokens": int(r.tokens or 0),
            "cost_usd": round(cost, 6),
        })

    # --- Monthly per-model (last 12 months) ---
    monthly_rows = (await db.execute(
        select(
            func.strftime("%Y-%m", AIUsageLog.called_at).label("month"),
            AIUsageLog.provider, AIUsageLog.model,
            func.count().label("calls"),
            func.sum(AIUsageLog.tokens_estimated).label("tokens"),
        )
        .where(AIUsageLog.status == "ok")
        .group_by("month", AIUsageLog.provider, AIUsageLog.model)
        .order_by("month")
    )).all()

    monthly = []
    for r in monthly_rows:
        in_p, _ = get_price(r.provider, r.model)
        cost = ((r.tokens or 0) / 1_000_000.0) * in_p
        monthly.append({
            "month": r.month, "provider": r.provider, "model": r.model,
            "calls": r.calls,
            "tokens": int(r.tokens or 0),
            "cost_usd": round(cost, 6),
        })

    # --- Daily per-model (last 30 days) ---
    thirty_days_ago = _dt.now(_tz.utc).replace(tzinfo=None) - _td(days=30)
    daily_rows = (await db.execute(
        select(
            func.strftime("%Y-%m-%d", AIUsageLog.called_at).label("day"),
            AIUsageLog.provider, AIUsageLog.model,
            func.count().label("calls"),
            func.sum(AIUsageLog.tokens_estimated).label("tokens"),
        )
        .where(
            AIUsageLog.status == "ok",
            AIUsageLog.called_at >= thirty_days_ago,
        )
        .group_by("day", AIUsageLog.provider, AIUsageLog.model)
        .order_by("day")
    )).all()

    daily = []
    for r in daily_rows:
        in_p, _ = get_price(r.provider, r.model)
        cost = ((r.tokens or 0) / 1_000_000.0) * in_p
        daily.append({
            "day": r.day, "provider": r.provider, "model": r.model,
            "calls": r.calls,
            "tokens": int(r.tokens or 0),
            "cost_usd": round(cost, 6),
        })

    # --- Top tasks by cost (last 30d) — where the money is going ---
    task_rows = (await db.execute(
        select(
            AIUsageLog.task, AIUsageLog.provider, AIUsageLog.model,
            func.count().label("calls"),
            func.sum(AIUsageLog.tokens_estimated).label("tokens"),
            func.avg(AIUsageLog.latency_ms).label("avg_latency"),
        )
        .where(
            AIUsageLog.status == "ok",
            AIUsageLog.called_at >= thirty_days_ago,
        )
        .group_by(AIUsageLog.task, AIUsageLog.provider, AIUsageLog.model)
    )).all()
    top_tasks_by_cost = []
    for r in task_rows:
        in_p, _ = get_price(r.provider, r.model)
        cost = ((r.tokens or 0) / 1_000_000.0) * in_p
        top_tasks_by_cost.append({
            "task": r.task, "provider": r.provider, "model": r.model,
            "calls": r.calls,
            "tokens": int(r.tokens or 0),
            "avg_latency_ms": int(r.avg_latency or 0),
            "cost_usd": round(cost, 6),
        })
    top_tasks_by_cost.sort(key=lambda x: -x["cost_usd"])
    top_tasks_by_cost = top_tasks_by_cost[:20]

    # --- 7d vs prior 7d trend ---
    now_utc = _dt.now(_tz.utc).replace(tzinfo=None)
    seven = now_utc - _td(days=7)
    fourteen = now_utc - _td(days=14)

    async def _sum_cost(since, until):
        rows = (await db.execute(
            select(AIUsageLog.provider, AIUsageLog.model,
                    func.sum(AIUsageLog.tokens_estimated).label("tok"))
            .where(
                AIUsageLog.status == "ok",
                AIUsageLog.called_at >= since,
                AIUsageLog.called_at < until,
            )
            .group_by(AIUsageLog.provider, AIUsageLog.model)
        )).all()
        total = 0.0
        for r in rows:
            in_p, _ = get_price(r.provider, r.model)
            total += ((r.tok or 0) / 1_000_000.0) * in_p
        return total

    cost_7d = await _sum_cost(seven, now_utc)
    cost_prior_7d = await _sum_cost(fourteen, seven)
    pct_change = None
    if cost_prior_7d > 0:
        pct_change = round(((cost_7d - cost_prior_7d) / cost_prior_7d) * 100, 1)

    trend = {
        "last_7d": round(cost_7d, 6),
        "prior_7d": round(cost_prior_7d, 6),
        "pct_change": pct_change,
    }

    # --- Fallback rate: how often a non-first provider served a task ---
    # (A rough proxy: count non-ok statuses per provider as "needed fallback".)
    fallback_rows = (await db.execute(
        select(
            AIUsageLog.provider,
            func.sum(case((AIUsageLog.status == "ok", 1), else_=0)).label("ok_cnt"),
            func.sum(case((AIUsageLog.status != "ok", 1), else_=0)).label("fail_cnt"),
        )
        .where(AIUsageLog.called_at >= thirty_days_ago)
        .group_by(AIUsageLog.provider)
    )).all()
    fallback_rate = []
    for r in fallback_rows:
        total = (r.ok_cnt or 0) + (r.fail_cnt or 0)
        if total > 0:
            fallback_rate.append({
                "provider": r.provider,
                "ok": r.ok_cnt or 0,
                "fail": r.fail_cnt or 0,
                "fail_pct": round((r.fail_cnt or 0) / total * 100, 1),
            })
    fallback_rate.sort(key=lambda x: -x["fail_pct"])

    return {
        "alltime": alltime, "monthly": monthly, "daily": daily,
        "top_tasks_by_cost": top_tasks_by_cost,
        "trend": trend,
        "fallback_rate": fallback_rate,
    }


@router.get("/api/ai-usage/cost-per-template")
async def cost_per_template(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Attribute AI spend to each template — generation + review + refine + refresh.

    Attribution heuristic: match `ai_usage_log.subtask` substring against each
    template's title. Works because generation logs subtask=title and refine
    logs subtask=title[:50]. Not perfect (rows without a template-identifying
    subtask are excluded), but gives a solid cost-per-template ranking.
    """
    from app.curriculum.loader import list_templates, load_template
    from app.ai.pricing import get_price

    # Fetch all OK rows with a non-empty subtask in one query
    rows = (await db.execute(
        select(
            AIUsageLog.provider, AIUsageLog.model, AIUsageLog.task,
            AIUsageLog.subtask, AIUsageLog.tokens_estimated,
        ).where(AIUsageLog.status == "ok", AIUsageLog.subtask != "")
    )).all()

    # Build template summary list
    out = []
    for key in list_templates():
        try:
            tpl = load_template(key)
        except Exception:
            continue

        # Multi-stage matching, most specific first:
        #   1. Exact canonical form "topic Xmo level" (matches batch_generator subtask)
        #   2. Topic prefix at START of subtask (anchored — rejects "AI" matching
        #      "Advanced NLP" accidentally)
        #   3. Full title substring (belt and braces)
        import re as _re
        full_title = tpl.title.lower()
        topic_portion = (tpl.title.split("—")[0].split("-")[0]).strip().lower()
        topic_portion = _re.sub(r"[^a-z0-9 ]+", " ", topic_portion).strip()
        topic_portion = _re.sub(r"\s+", " ", topic_portion)

        duration_tag = f"{tpl.duration_months}mo"
        level_tag = (tpl.level or "").lower()
        canonical = f"{topic_portion} {duration_tag} {level_tag}".strip()

        per_task: dict[str, dict] = {}
        total_cost = 0.0
        total_calls = 0
        total_tokens = 0

        for r in rows:
            sub = (r.subtask or "").lower()
            if not sub:
                continue
            sub_norm = _re.sub(r"[^a-z0-9 ]+", " ", sub)
            sub_norm = _re.sub(r"\s+", " ", sub_norm).strip()

            # Tier 1: canonical exact or prefix match — most precise
            if canonical and (sub_norm == canonical or sub_norm.startswith(canonical)):
                pass
            # Tier 2: topic appears at the *start* of the subtask — anchored
            elif topic_portion and sub_norm.startswith(topic_portion + " "):
                pass
            # Tier 3: broad substring (loose fallback, covers ad-hoc subtasks)
            elif topic_portion and len(topic_portion) >= 10 and topic_portion in sub_norm:
                pass
            elif sub in full_title or full_title in sub:
                pass
            else:
                continue
            in_p, _ = get_price(r.provider, r.model)
            tok = int(r.tokens_estimated or 0)
            cost = (tok / 1_000_000.0) * in_p
            bucket = per_task.setdefault(r.task, {"calls": 0, "tokens": 0, "cost_usd": 0.0})
            bucket["calls"] += 1
            bucket["tokens"] += tok
            bucket["cost_usd"] += cost
            total_cost += cost
            total_calls += 1
            total_tokens += tok

        out.append({
            "key": key,
            "title": tpl.title,
            "level": tpl.level,
            "duration_months": tpl.duration_months,
            "total_cost_usd": round(total_cost, 6),
            "total_calls": total_calls,
            "total_tokens": total_tokens,
            "by_task": {k: {
                "calls": v["calls"],
                "tokens": v["tokens"],
                "cost_usd": round(v["cost_usd"], 6),
            } for k, v in per_task.items()},
        })
    out.sort(key=lambda x: -x["total_cost_usd"])
    return {"templates": out}


@router.post("/api/ai-usage/set-balance")
async def set_provider_balance(
    request: Request,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Upsert the admin-visible balance/recommended-cap for a provider."""
    _check_origin(request)
    body = await request.json()
    provider = (body.get("provider") or "").strip().lower()
    if not provider:
        raise HTTPException(status_code=400, detail="provider required")
    try:
        balance = float(body.get("balance_usd", 0))
        rec_cap = float(body.get("recommended_cap_usd", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid numeric values")
    if balance < 0 or rec_cap < 0:
        raise HTTPException(status_code=400, detail="values cannot be negative")

    existing = (await db.execute(
        select(ProviderBalance).where(ProviderBalance.provider == provider)
    )).scalar_one_or_none()
    if existing is None:
        row = ProviderBalance(
            provider=provider, balance_usd=balance,
            recommended_cap_usd=rec_cap, notes=body.get("notes"),
        )
        db.add(row)
    else:
        existing.balance_usd = balance
        existing.recommended_cap_usd = rec_cap
        if "notes" in body:
            existing.notes = body.get("notes")
    await db.commit()
    return {"ok": True}


@router.post("/api/ai-usage/set-limit")
async def set_cost_limit(
    request: Request,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Upsert a daily cost/token cap for a provider+model. model='*' = provider-wide."""
    _check_origin(request)
    body = await request.json()
    provider = (body.get("provider") or "").strip().lower()
    model = (body.get("model") or "*").strip()
    try:
        daily_cost = float(body.get("daily_cost_usd", 0))
        daily_tokens = int(body.get("daily_token_limit", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid numeric values")
    if not provider:
        raise HTTPException(status_code=400, detail="provider required")
    if daily_cost < 0 or daily_tokens < 0:
        raise HTTPException(status_code=400, detail="limits cannot be negative")

    existing = (await db.execute(
        select(AICostLimit).where(
            AICostLimit.provider == provider, AICostLimit.model == model,
        )
    )).scalar_one_or_none()

    if existing is None:
        lim = AICostLimit(
            provider=provider, model=model,
            daily_cost_usd=daily_cost, daily_token_limit=daily_tokens,
            notes=body.get("notes"),
        )
        db.add(lim)
    else:
        existing.daily_cost_usd = daily_cost
        existing.daily_token_limit = daily_tokens
        if "notes" in body:
            existing.notes = body.get("notes")
    await db.commit()
    return {"ok": True}


@router.post("/api/ai-usage/delete-limit")
async def delete_cost_limit(
    request: Request,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    _check_origin(request)
    body = await request.json()
    lim_id = body.get("id")
    if not lim_id:
        raise HTTPException(status_code=400, detail="id required")
    lim = await db.get(AICostLimit, int(lim_id))
    if lim is not None:
        await db.delete(lim)
        await db.commit()
    return {"ok": True}


@router.post("/api/ai-usage/reset-provider")
async def reset_provider_health(
    request: Request,
    _user: User = Depends(get_current_admin),
):
    """Reset a provider's circuit breaker state."""
    _check_origin(request)
    body = await request.json()
    provider = body.get("provider", "")
    if not provider:
        raise HTTPException(status_code=400, detail="provider required")
    from app.ai.health import reset_provider
    reset_provider(provider)
    return {"ok": True, "provider": provider}


@router.get("/ai-usage", response_class=HTMLResponse)
async def ai_usage_page(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """AI Usage dashboard — per-provider stats, per-task breakdown, health status."""
    from app.ai.health import get_all_health

    s = await _get_settings(db)

    # Real tokens-this-month from ai_usage_log (not the stale track_tokens counter,
    # which was incremented by hardcoded estimates regardless of actual usage).
    from datetime import datetime as _dt, timezone as _tz
    now_utc = _dt.now(_tz.utc).replace(tzinfo=None)
    month_start = now_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    tokens_this_month_real = await db.scalar(
        select(func.sum(AIUsageLog.tokens_estimated)).where(
            AIUsageLog.called_at >= month_start,
            AIUsageLog.status == "ok",
        )
    ) or 0

    # Provider health for status indicators
    health = get_all_health()

    # All known providers
    all_providers = ["gemini", "groq", "cerebras", "mistral", "deepseek", "sambanova"]
    from app.config import get_settings as get_app_settings
    app_settings = get_app_settings()

    provider_cards = ""
    for p in all_providers:
        api_key = getattr(app_settings, f"{p}_api_key", "")
        has_key = bool(api_key)
        h = health.get(p, {})
        available = h.get("available", True) if h else True
        permanent = h.get("permanent_error", False) if h else False
        successes = h.get("success_count", 0) if h else 0
        errors = h.get("error_count", 0) if h else 0
        rl_count = h.get("rate_limit_count", 0) if h else 0
        last_err_raw = h.get("last_error_msg", "") or "" if h else ""
        model = getattr(app_settings, f"{p}_model", "")

        # Human-readable status + reason
        if not has_key:
            dot = "🔴"
            status_text = "Not configured"
            reason = "No API key set"
        elif permanent:
            dot = "🔴"
            status_text = "Down"
            if "402" in last_err_raw or "Insufficient" in last_err_raw:
                reason = "Out of credits — needs top-up"
            elif "404" in last_err_raw or "not found" in last_err_raw:
                reason = "Model retired or invalid"
            else:
                reason = "Permanent error"
        elif not available:
            dot = "🟡"
            status_text = "Cooling down"
            reason = "Hit rate limit — auto-retries in 60s"
        elif successes > 0:
            dot = "🟢"
            status_text = "Working"
            reason = f"{successes} successful calls"
        elif rl_count > 0:
            dot = "🟡"
            status_text = "Rate limited"
            reason = f"Hit limit {rl_count} times — will retry"
        else:
            dot = "🟢"
            status_text = "Ready"
            reason = "No calls yet"

        reset_btn = ""
        if permanent or not available:
            reset_btn = f'<button class="btn" style="margin-top:6px;font-size:12px" onclick="resetProvider(\'{p}\')">Retry This Provider</button>'

        provider_cards += f"""<div class="card" style="flex:1;min-width:170px">
  <div style="display:flex;justify-content:space-between;align-items:center">
    <strong style="color:#e8a849;text-transform:capitalize">{esc(p)}</strong>
    <span style="font-size:13px">{dot}</span>
  </div>
  <div style="font-size:13px;margin:6px 0;color:#f5f1e8">{status_text}</div>
  <div style="font-size:12px;color:#8a92a0">{esc(reason)}</div>
  <div style="font-size:12px;color:#8a92a0;margin-top:4px">Model: {esc(model)}</div>
  {reset_btn}
</div>"""

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>AI Usage</title>
<style>{ADMIN_CSS}</style></head><body>
{NAV_HTML}
<div class="page">
<h1>AI Usage Dashboard</h1>
<div class="subtitle">Provider health, usage per task, token budget</div>

<div id="alerts-banner" style="margin:12px 0"></div>

<h2>Cost (USD)</h2>
<div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap">
<div class="stat"><div class="num" id="cost-today" style="color:#6db585">$0.0000</div><div class="lbl">Today</div></div>
<div class="stat"><div class="num" id="cost-7d" style="color:#e8a849">$0.0000</div><div class="lbl">Last 7 days</div></div>
<div class="stat"><div class="num" id="cost-30d" style="color:#d97757">$0.0000</div><div class="lbl">Last 30 days</div></div>
<div class="stat"><div class="num">{tokens_this_month_real:,}</div><div class="lbl">Tokens this month</div></div>
</div>
<div style="font-size:12px;color:#8a92a0;margin-bottom:24px">
Free-tier providers (Gemini / Groq / Cerebras / Mistral / Sambanova) contribute $0.00.
Paid spend comes from Anthropic (refinement) + OpenAI (embeddings).
</div>

<h2 style="display:flex;align-items:center;gap:12px">
  Provider Caps &amp; Balances
  <button class="btn" style="font-size:12px;padding:4px 10px" onclick="applyAllRecommended()">Apply all recommended caps</button>
</h2>
<div style="font-size:13px;color:#8a92a0;margin-bottom:12px">
Click any <span style="border-bottom:1px dashed #e8a849;color:#e8a849">balance</span>
or <span style="border-bottom:1px dashed #e8a849;color:#e8a849">cap</span> value below to edit — saves on Enter / blur.
Cap breach blocks further calls that day; calls fall through to a cheaper provider or skip gracefully.
</div>

<div id="provider-cards" style="margin-bottom:16px"><em style="color:#8a92a0">Loading...</em></div>

<h2>Provider Health</h2>
<div style="display:flex;flex-wrap:wrap;gap:12px;margin-bottom:24px">
{provider_cards}
</div>

<h2>Usage by Provider</h2>
<div id="provider-stats"><em style="color:#8a92a0">Loading...</em></div>

<h2>Usage by Task</h2>
<div id="task-stats"><em style="color:#8a92a0">Loading...</em></div>

<h2>Usage Analytics (persistent)</h2>
<div style="font-size:13px;color:#8a92a0;margin-bottom:8px">
All data from <code>ai_usage_log</code> — survives deploys and rebuilds. Costs use real token counts from provider API responses.
</div>

<h3 style="color:#e8a849;margin:14px 0 6px 0">Cost Trend — last 7 days vs prior 7 days</h3>
<div id="trend-card"><em style="color:#8a92a0">Loading...</em></div>

<h3 style="color:#e8a849;margin:14px 0 6px 0">All-Time Usage by Model</h3>
<div id="alltime-stats"><em style="color:#8a92a0">Loading...</em></div>

<h3 style="color:#e8a849;margin:14px 0 6px 0">Top Tasks by Cost (last 30 days)</h3>
<div id="top-tasks"><em style="color:#8a92a0">Loading...</em></div>

<h3 style="color:#e8a849;margin:14px 0 6px 0">Monthly Usage by Model (last 12 months)</h3>
<div id="monthly-stats"><em style="color:#8a92a0">Loading...</em></div>

<h3 style="color:#e8a849;margin:14px 0 6px 0">Daily Usage by Model (last 30 days)</h3>
<div id="daily-stats" style="max-height:400px;overflow-y:auto"><em style="color:#8a92a0">Loading...</em></div>

<h3 style="color:#e8a849;margin:14px 0 6px 0">Reliability — Failure Rate by Provider (last 30 days)</h3>
<div id="fallback-stats"><em style="color:#8a92a0">Loading...</em></div>

<h3 style="color:#e8a849;margin:14px 0 6px 0;display:flex;align-items:center;gap:12px">
  Provider-Authoritative Reconciliation (last 30 days)
  <button class="btn" style="font-size:12px;padding:4px 10px" onclick="syncNow()">Sync now</button>
</h3>
<div style="font-size:13px;color:#8a92a0;margin-bottom:4px">
Pulled nightly from OpenAI + Anthropic Usage APIs (requires admin API keys in <code>.env</code>).
Drift column = our local estimate vs provider-reported spend. Gemini not available — no public usage API.
</div>
<div id="sync-status" style="font-size:13px;margin-bottom:8px;min-height:20px"></div>
<div id="reconciliation"><em style="color:#8a92a0">Loading...</em></div>

<h2 style="margin-top:28px">Cost per Template</h2>
<div style="font-size:13px;color:#8a92a0;margin-bottom:8px">
  AI spend attributed to each template via <code>subtask</code> substring matching. Useful for spotting templates that cost more than they should (e.g. repeated refinements that never lift past the publish threshold).
</div>
<div id="cost-per-template"><em style="color:#8a92a0">Loading...</em></div>

<h2 style="margin-top:28px">Recent Calls (last 50)</h2>
<div id="recent-calls" style="max-height:400px;overflow-y:auto"><em style="color:#8a92a0">Loading...</em></div>

<script>
async function resetProvider(name) {{
  await fetch('/admin/pipeline/api/ai-usage/reset-provider', {{
    method: 'POST', credentials: 'same-origin',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{provider: name}})
  }});
  window.location.reload();
}}

function fmtCost(usd) {{
  if (usd === 0) return '<span style="color:#8a92a0">$0.00</span>';
  if (usd < 0.01) return '$' + usd.toFixed(6);
  if (usd < 1) return '$' + usd.toFixed(4);
  return '$' + usd.toFixed(2);
}}

async function loadAlerts() {{
  try {{
    const resp = await fetch('/admin/pipeline/api/ai-usage/alerts', {{credentials:'same-origin'}});
    const d = await resp.json();
    const el = document.getElementById('alerts-banner');
    if (!d.alerts || d.alerts.length === 0) {{ el.innerHTML = ''; return; }}
    let html = '';
    for (const a of d.alerts) {{
      const color = a.severity === 'critical' ? '#d97757'
        : (a.severity === 'warn' ? '#e8a849' : '#6db585');
      const icon = a.severity === 'critical' ? '🚨'
        : (a.severity === 'warn' ? '⚠️' : 'ℹ️');
      const label = {{cap_breach:'Cap breached',
                       balance_low:'Balance low',
                       pricing_drift:'Pricing drift'}}[a.kind] || a.kind;
      html += '<div style="border-left:3px solid ' + color + ';background:#1a1c22;'
        + 'padding:10px 14px;margin-bottom:6px;border-radius:4px;'
        + 'display:flex;align-items:center;gap:10px">'
        + '<span style="font-size:18px">' + icon + '</span>'
        + '<span style="color:' + color + ';font-weight:600;font-size:13px">' + label + ':</span>'
        + '<span style="font-size:13px;flex:1">' + a.message + '</span>'
        + '<button class="btn" style="font-size:11px;padding:3px 10px" '
        + 'onclick="dismissAlert(' + a.id + ')">Dismiss</button>'
        + '</div>';
    }}
    el.innerHTML = html;
  }} catch(e) {{ /* silent */ }}
}}

async function dismissAlert(id) {{
  await fetch('/admin/pipeline/api/ai-usage/alerts/dismiss', {{
    method:'POST', credentials:'same-origin',
    headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify({{id}}),
  }});
  loadAlerts();
}}

async function runAlertChecks() {{
  const resp = await fetch('/admin/pipeline/api/ai-usage/alerts/run-checks', {{
    method:'POST', credentials:'same-origin',
    headers:{{'Content-Type':'application/json'}},
  }});
  const r = await resp.json();
  alert('Alert checks: ' + JSON.stringify(r));
  loadAlerts();
}}

// Wire up inline-editable balance + cap spans. Saves on blur or Enter.
function wireInlineEdits() {{
  const spans = document.querySelectorAll('.inline-edit');
  spans.forEach(span => {{
    const prev = span.textContent.trim();
    span.dataset.prev = prev;

    span.addEventListener('focus', () => {{
      if (span.textContent.trim() === 'unset') span.textContent = '';
      // select all on focus
      const r = document.createRange(); r.selectNodeContents(span);
      const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
    }});

    span.addEventListener('keydown', (e) => {{
      if (e.key === 'Enter') {{ e.preventDefault(); span.blur(); }}
      if (e.key === 'Escape') {{ span.textContent = span.dataset.prev; span.blur(); }}
    }});

    span.addEventListener('blur', async () => {{
      const raw = span.textContent.trim().replace(/[^0-9.]/g, '');
      if (raw === span.dataset.prev) return; // no change
      const num = parseFloat(raw || '0');
      if (isNaN(num) || num < 0) {{
        alert('Invalid number'); span.textContent = span.dataset.prev; return;
      }}
      const kind = span.dataset.kind;
      const provider = span.dataset.provider;
      if (kind === 'balance') {{
        const existing = (window.__lastInfo || []).find(p => p.provider === provider) || {{}};
        const rec = existing.recommended_cap_usd || 0;
        const resp = await fetch('/admin/pipeline/api/ai-usage/set-balance', {{
          method:'POST', credentials:'same-origin',
          headers:{{'Content-Type':'application/json'}},
          body: JSON.stringify({{provider, balance_usd: num, recommended_cap_usd: rec}}),
        }});
        if (!resp.ok) {{ alert('Save failed'); span.textContent = span.dataset.prev; return; }}
      }} else if (kind === 'cap') {{
        if (num === 0) {{
          // Remove cap
          const resp0 = await fetch('/admin/pipeline/api/ai-usage', {{credentials:'same-origin'}});
          const d0 = await resp0.json();
          const row = (d0.limits || []).find(l => l.provider === provider && l.model === '*');
          if (row) {{
            await fetch('/admin/pipeline/api/ai-usage/delete-limit', {{
              method:'POST', credentials:'same-origin',
              headers:{{'Content-Type':'application/json'}},
              body: JSON.stringify({{id: row.id}}),
            }});
          }}
        }} else {{
          const resp = await fetch('/admin/pipeline/api/ai-usage/set-limit', {{
            method:'POST', credentials:'same-origin',
            headers:{{'Content-Type':'application/json'}},
            body: JSON.stringify({{provider, model:'*', daily_cost_usd: num, daily_token_limit: 0}}),
          }});
          if (!resp.ok) {{ alert('Save failed'); span.textContent = span.dataset.prev; return; }}
        }}
      }}
      loadUsageData();
    }});
  }});
}}

async function editBalancePrompt(provider, currentBal, currentRec) {{
  const balStr = prompt('Credit remaining for ' + provider + ' (USD):', currentBal.toFixed(2));
  if (balStr === null) return;
  const bal = parseFloat(balStr);
  if (isNaN(bal) || bal < 0) {{ alert('Invalid balance'); return; }}
  const recStr = prompt('Recommended daily cap for ' + provider + ' (USD):', currentRec.toFixed(2));
  if (recStr === null) return;
  const rec = parseFloat(recStr);
  if (isNaN(rec) || rec < 0) {{ alert('Invalid cap'); return; }}
  const resp = await fetch('/admin/pipeline/api/ai-usage/set-balance', {{
    method:'POST', credentials:'same-origin',
    headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify({{provider, balance_usd: bal, recommended_cap_usd: rec}}),
  }});
  if (!resp.ok) {{ alert('Save failed'); return; }}
  loadUsageData();
}}

async function editCapOnly(provider, currentCap) {{
  const s = prompt('Daily $ cap for ' + provider + ' (0 to remove):', currentCap.toFixed(2));
  if (s === null) return;
  const cap = parseFloat(s);
  if (isNaN(cap) || cap < 0) {{ alert('Invalid cap'); return; }}
  if (cap === 0) {{
    // Remove: find the provider-wide cap row and delete it
    const resp0 = await fetch('/admin/pipeline/api/ai-usage', {{credentials:'same-origin'}});
    const d0 = await resp0.json();
    const row = (d0.limits || []).find(l => l.provider === provider && l.model === '*');
    if (row) {{
      await fetch('/admin/pipeline/api/ai-usage/delete-limit', {{
        method:'POST', credentials:'same-origin',
        headers:{{'Content-Type':'application/json'}},
        body: JSON.stringify({{id: row.id}}),
      }});
    }}
    loadUsageData();
    return;
  }}
  const resp = await fetch('/admin/pipeline/api/ai-usage/set-limit', {{
    method:'POST', credentials:'same-origin',
    headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify({{provider, model:'*', daily_cost_usd: cap, daily_token_limit: 0}}),
  }});
  if (!resp.ok) {{ alert('Save failed'); return; }}
  loadUsageData();
}}

async function applyAllRecommended() {{
  const resp0 = await fetch('/admin/pipeline/api/ai-usage', {{credentials:'same-origin'}});
  const d0 = await resp0.json();
  const todo = (d0.provider_info || []).filter(p =>
    p.paid && p.recommended_cap_usd > 0
  );
  if (todo.length === 0) {{ alert('Nothing to apply.'); return; }}
  if (!confirm('Set daily caps for ' + todo.map(p => p.provider).join(', ') + ' to their recommended values?')) return;
  for (const p of todo) {{
    await fetch('/admin/pipeline/api/ai-usage/set-limit', {{
      method:'POST', credentials:'same-origin',
      headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{provider: p.provider, model:'*',
        daily_cost_usd: p.recommended_cap_usd, daily_token_limit: 0}}),
    }});
  }}
  loadUsageData();
}}

async function editBalance(provider, currentBal, currentRec) {{
  const balStr = prompt('Credit remaining for ' + provider + ' (USD):', currentBal.toFixed(2));
  if (balStr === null) return;
  const balance = parseFloat(balStr);
  if (isNaN(balance) || balance < 0) {{ alert('Invalid balance'); return; }}
  const recStr = prompt('Recommended daily cap for ' + provider + ' (USD):', currentRec.toFixed(2));
  if (recStr === null) return;
  const rec_cap = parseFloat(recStr);
  if (isNaN(rec_cap) || rec_cap < 0) {{ alert('Invalid cap'); return; }}
  const resp = await fetch('/admin/pipeline/api/ai-usage/set-balance', {{
    method: 'POST', credentials: 'same-origin',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{provider, balance_usd: balance, recommended_cap_usd: rec_cap}}),
  }});
  if (!resp.ok) {{ alert('Save failed'); return; }}
  loadUsageData();
}}

async function applyRecommendedCap(provider, cap) {{
  if (!confirm('Set daily cap for ' + provider + ' to $' + cap.toFixed(2) + '?')) return;
  const resp = await fetch('/admin/pipeline/api/ai-usage/set-limit', {{
    method: 'POST', credentials: 'same-origin',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{provider, model: '*', daily_cost_usd: cap, daily_token_limit: 0}}),
  }});
  if (!resp.ok) {{ alert('Save failed'); return; }}
  loadUsageData();
}}

async function saveLimit() {{
  const body = {{
    provider: document.getElementById('lim-provider').value,
    model: document.getElementById('lim-model').value || '*',
    daily_cost_usd: parseFloat(document.getElementById('lim-cost').value) || 0,
    daily_token_limit: parseInt(document.getElementById('lim-tokens').value) || 0,
  }};
  const resp = await fetch('/admin/pipeline/api/ai-usage/set-limit', {{
    method: 'POST', credentials: 'same-origin',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(body),
  }});
  if (!resp.ok) {{ alert('Failed to save limit'); return; }}
  loadUsageData();
}}

async function deleteLimit(id) {{
  if (!confirm('Remove this cap?')) return;
  await fetch('/admin/pipeline/api/ai-usage/delete-limit', {{
    method: 'POST', credentials: 'same-origin',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{id}}),
  }});
  loadUsageData();
}}

async function loadUsageData() {{
  try {{
    const resp = await fetch('/admin/pipeline/api/ai-usage', {{credentials: 'same-origin'}});
    const data = await resp.json();

    // Cost cards
    if (data.cost_summary) {{
      document.getElementById('cost-today').textContent = '$' + data.cost_summary.today.toFixed(4);
      document.getElementById('cost-7d').textContent = '$' + data.cost_summary.last_7d.toFixed(4);
      document.getElementById('cost-30d').textContent = '$' + data.cost_summary.last_30d.toFixed(4);
    }}

    // Consolidated provider table — Provider | Balance | Rec. $ cap |
    // Current $ cap | Today spend | Primary model | Price | Actions
    // Balance and Current $ cap are inline-editable (click → type → autosave).
    if (data.provider_info) {{
      window.__lastInfo = data.provider_info;
      const limitsByProvider = {{}};
      (data.limits || []).forEach(l => {{
        if (l.model === '*') limitsByProvider[l.provider] = l.daily_cost_usd;
      }});
      const spend = data.spend_today || {{}};

      let html = '<table style="font-size:13px"><tr>'
        + '<th>Provider</th><th>Balance</th><th>Rec. $ cap</th><th>Current $ cap</th>'
        + '<th>Today spend</th><th>Primary model</th><th>Price</th><th>Actions</th></tr>';

      for (const p of data.provider_info) {{
        const curCap = limitsByProvider[p.provider];
        const rec = p.recommended_cap_usd || 0;
        const bal = p.balance_usd || 0;
        const sp = spend[p.provider] || 0;
        const disabled = (p.price_note || '').includes('402');

        // Provider name
        const nameColor = p.paid ? '#e8a849' : '#6db585';
        const nameCell = '<span style="color:' + (disabled ? '#8a92a0' : nameColor)
          + ';text-transform:capitalize;font-weight:' + (p.paid ? '600' : '400') + '">'
          + p.provider + '</span>';

        // Balance — inline editable for paid
        let balCell;
        if (p.paid) {{
          balCell = '$<span class="inline-edit" contenteditable="true" '
            + 'data-kind="balance" data-provider="' + p.provider + '" '
            + 'style="border-bottom:1px dashed #e8a849;color:#e8a849;'
            + 'padding:1px 4px;min-width:40px;display:inline-block;font-weight:600">'
            + bal.toFixed(2) + '</span>';
        }} else {{
          balCell = '<span style="color:#8a92a0">free</span>';
        }}

        // Rec. $ cap (read-only display)
        const recCell = p.paid && rec > 0
          ? '$' + rec.toFixed(2)
          : '<span style="color:#8a92a0">—</span>';

        // Current $ cap — inline editable, "unset" red for paid with no cap
        let capCell;
        if (p.paid) {{
          if (curCap != null) {{
            capCell = '$<span class="inline-edit" contenteditable="true" '
              + 'data-kind="cap" data-provider="' + p.provider + '" '
              + 'style="border-bottom:1px dashed #e8a849;color:#e8a849;'
              + 'padding:1px 4px;min-width:40px;display:inline-block;font-weight:600">'
              + curCap.toFixed(2) + '</span>';
          }} else {{
            capCell = '<span class="inline-edit" contenteditable="true" '
              + 'data-kind="cap" data-provider="' + p.provider + '" '
              + 'style="border-bottom:1px dashed #d97757;color:#d97757;'
              + 'padding:1px 4px;min-width:40px;display:inline-block;font-weight:600">'
              + 'unset</span>';
          }}
        }} else {{
          capCell = '<span style="color:#8a92a0">unset</span>';
        }}

        // Today spend
        let spendCell;
        if (p.paid) {{
          spendCell = sp > 0 ? '$' + sp.toFixed(4) : '<span style="color:#8a92a0">$0</span>';
        }} else {{
          spendCell = '<span style="color:#8a92a0">—</span>';
        }}

        // Actions
        let actionCell;
        if (p.paid) {{
          actionCell = '<button class="btn" style="font-size:11px;padding:3px 8px" '
            + 'onclick="editBalancePrompt(\\'' + p.provider + '\\',' + bal + ','
            + rec + ')">Edit balance</button>';
          if (curCap == null && rec > 0) {{
            actionCell += ' <button class="btn" style="font-size:11px;padding:3px 8px;background:#6db585" '
              + 'onclick="applyRecommendedCap(\\'' + p.provider + '\\',' + rec + ')">Apply rec</button>';
          }}
        }} else {{
          actionCell = '<span style="color:#8a92a0;font-size:12px">' + p.use
            + (disabled ? ' (disabled)' : '') + '</span>';
        }}

        html += '<tr>'
          + '<td>' + nameCell + '</td>'
          + '<td>' + balCell + '</td>'
          + '<td>' + recCell + '</td>'
          + '<td>' + capCell + '</td>'
          + '<td>' + spendCell + '</td>'
          + '<td style="font-family:monospace;font-size:12px">' + p.primary_model + '</td>'
          + '<td style="font-size:12px;color:#8a92a0">' + p.price_note + '</td>'
          + '<td>' + actionCell + '</td>'
          + '</tr>';
      }}
      html += '</table>';
      document.getElementById('provider-cards').innerHTML = html;
      wireInlineEdits();
    }}

    // (Consolidated caps/balances rendered above in provider-cards; no separate limits table.)

    // Provider stats table
    if (data.provider_stats.length > 0) {{
      let html = '<table><tr><th>Provider</th><th>Total Calls</th><th>Succeeded</th><th>Rate Limited</th><th>Failed</th><th>Avg Speed</th><th>Cost</th></tr>';
      for (const p of data.provider_stats) {{
        const successRate = p.total_calls > 0 ? Math.round(p.success / p.total_calls * 100) : 0;
        const speedLabel = p.avg_latency_ms < 1000 ? p.avg_latency_ms + 'ms' : (p.avg_latency_ms / 1000).toFixed(1) + 's';
        html += `<tr>
          <td style="text-transform:capitalize"><strong>${{p.provider}}</strong></td>
          <td>${{p.total_calls}}</td>
          <td style="color:#6db585">${{p.success}} (${{successRate}}%)</td>
          <td style="color:#e8a849">${{p.rate_limited}}</td>
          <td style="color:#d97757">${{p.errors}}</td>
          <td>${{speedLabel}}</td>
          <td>${{fmtCost(p.cost_usd || 0)}}</td>
        </tr>`;
      }}
      html += '</table>';
      document.getElementById('provider-stats').innerHTML = html;
    }} else {{
      document.getElementById('provider-stats').innerHTML = '<p style="color:#8a92a0">No usage data yet. Run a pipeline task to generate data.</p>';
    }}

    // Task stats table
    if (data.task_stats.length > 0) {{
      let html = '<table><tr><th>Task</th><th>Subtask</th><th>Calls</th><th>Success</th><th>Failures</th><th>Tokens</th></tr>';
      for (const t of data.task_stats) {{
        html += `<tr>
          <td>${{t.task}}</td>
          <td style="font-size:12px;color:#8a92a0;max-width:200px;overflow:hidden;text-overflow:ellipsis">${{t.subtask}}</td>
          <td>${{t.total_calls}}</td>
          <td style="color:#6db585">${{t.success}}</td>
          <td style="color:#d97757">${{t.failures}}</td>
          <td>${{t.total_tokens.toLocaleString()}}</td>
        </tr>`;
      }}
      html += '</table>';
      document.getElementById('task-stats').innerHTML = html;
    }} else {{
      document.getElementById('task-stats').innerHTML = '<p style="color:#8a92a0">No task data yet.</p>';
    }}

    // Recent calls
    if (data.recent.length > 0) {{
      // Human-readable status labels
      function friendlyStatus(status, err) {{
        if (status === 'ok') return '<span class="badge approved">Success</span>';
        if (status === 'rate_limited') return '<span class="badge pending">Rate Limited</span>';
        if (err && (err.includes('402') || err.includes('Insufficient'))) return '<span class="badge rejected">No Credits</span>';
        if (err && (err.includes('404') || err.includes('not found'))) return '<span class="badge rejected">Bad Model</span>';
        if (err && err.includes('non-JSON')) return '<span class="badge rejected">Bad Response</span>';
        return '<span class="badge rejected">Error</span>';
      }}
      function friendlyTime(ms) {{ return ms < 1000 ? ms + 'ms' : (ms/1000).toFixed(1) + 's'; }}

      let html = '<table><tr><th>Time</th><th>Provider</th><th>Task</th><th>Result</th><th>Speed</th><th>Cost</th></tr>';
      for (const r of data.recent) {{
        html += `<tr>
          <td style="font-size:12px;white-space:nowrap" title="${{r.called_at}}">${{r.called_at_utc ? window.fmtIST(r.called_at_utc) : r.called_at}}</td>
          <td style="text-transform:capitalize">${{r.provider}}</td>
          <td>${{r.task}}${{r.subtask ? ' <span style="color:#8a92a0;font-size:12px">(' + r.subtask.slice(0,30) + ')</span>' : ''}}</td>
          <td>${{friendlyStatus(r.status, r.error_message)}}</td>
          <td>${{friendlyTime(r.latency_ms)}}</td>
          <td>${{fmtCost(r.cost_usd || 0)}}</td>
        </tr>`;
      }}
      html += '</table>';
      document.getElementById('recent-calls').innerHTML = html;
    }} else {{
      document.getElementById('recent-calls').innerHTML = '<p style="color:#8a92a0">No recent calls.</p>';
    }}
  }} catch(e) {{
    document.getElementById('provider-stats').innerHTML = '<p style="color:#d97757">Failed to load: ' + e.message + '</p>';
  }}
}}

function setSyncStatus(html) {{
  const el = document.getElementById('sync-status');
  if (el) el.innerHTML = html;
}}

async function syncNow() {{
  const btn = event && event.target;
  if (btn) {{ btn.textContent = 'Syncing...'; btn.disabled = true; }}
  setSyncStatus('<span style="color:#e8a849">⏳ Syncing...</span>');
  try {{
    const resp = await fetch('/admin/pipeline/api/ai-usage/sync-now', {{
      method:'POST', credentials:'same-origin',
      headers:{{'Content-Type':'application/json'}},
    }});
    const r = await resp.json();
    if (!resp.ok) {{
      setSyncStatus('<span style="color:#d97757">✗ failed: ' + (r.detail || resp.status) + '</span>');
      return;
    }}
    const day = r.sync && r.sync.day ? r.sync.day : '?';
    const provs = (r.sync && r.sync.providers) || {{}};
    const bits = [];
    let hasError = false;
    for (const [name, info] of Object.entries(provs)) {{
      if (info.status === 'ok') {{
        const color = info.rows > 0 ? '#6db585' : '#8a92a0';
        bits.push('<span style="color:' + color + '">' + name + ' ' + info.rows + 'r</span>');
      }} else if (info.status === 'skipped') {{
        bits.push('<span style="color:#8a92a0">' + name + ' skipped</span>');
      }} else {{
        hasError = true;
        bits.push('<span style="color:#d97757">' + name + ' err</span>');
      }}
    }}
    const arch = r.archive || {{}};
    const archStr = arch.status === 'ok' && (arch.deleted_rows || 0) > 0
      ? ' · archived ' + arch.deleted_rows : '';
    const icon = hasError ? '⚠' : '✓';
    const iconColor = hasError ? '#d97757' : '#6db585';
    const now = new Date().toLocaleTimeString();
    setSyncStatus('<span style="color:' + iconColor + '">' + icon + '</span> '
      + day + ' · ' + bits.join(' · ') + archStr
      + ' <span style="color:#4a4f5a">@ ' + now + '</span>');
  }} finally {{
    if (btn) {{ btn.textContent = 'Sync now'; btn.disabled = false; }}
  }}
  loadReconciliation();
}}

async function loadReconciliation() {{
  try {{
    const resp = await fetch('/admin/pipeline/api/ai-usage/reconciliation', {{credentials:'same-origin'}});
    const d = await resp.json();
    if (!d.rows || d.rows.length === 0) {{
      const syncEl = document.getElementById('sync-status');
      const hasSyncRun = syncEl && syncEl.textContent.trim().length > 0;
      const msg = hasSyncRun
        ? 'Sync completed · no paid-tier spend to reconcile yet. Any billed calls (OpenAI embeddings / Claude refinement) will appear here after the next sync.'
        : 'No sync data yet. Click <b>Sync now</b>, or wait for the 06:00 UTC scheduled run. Reconciliation rows appear only when a provider has reported billed usage for a past day.';
      document.getElementById('reconciliation').innerHTML =
        '<p style="color:#8a92a0">' + msg + '</p>';
      return;
    }}
    let h = '<table><tr><th>Day</th><th>Provider</th><th>Model</th><th>In tokens</th><th>Out tokens</th><th>Provider cost</th><th>Our estimate</th><th>Drift</th></tr>';
    for (const r of d.rows) {{
      let driftCell;
      if (r.drift_pct === null) driftCell = '<span style="color:#8a92a0">—</span>';
      else {{
        const abs = Math.abs(r.drift_pct);
        const color = abs > 10 ? '#d97757' : (abs > 3 ? '#e8a849' : '#6db585');
        const sign = r.drift_pct > 0 ? '+' : '';
        driftCell = '<span style="color:' + color + '">' + sign + r.drift_pct + '%</span>';
      }}
      h += '<tr><td style="font-size:12px">' + r.day + '</td>'
        + '<td style="text-transform:capitalize">' + r.provider + '</td>'
        + '<td style="font-family:monospace;font-size:12px">' + r.model + '</td>'
        + '<td>' + r.input_tokens.toLocaleString() + '</td>'
        + '<td>' + r.output_tokens.toLocaleString() + '</td>'
        + '<td>' + fmtCost(r.cost_provider) + '</td>'
        + '<td>' + fmtCost(r.cost_local) + '</td>'
        + '<td>' + driftCell + '</td></tr>';
    }}
    h += '</table>';
    document.getElementById('reconciliation').innerHTML = h;
  }} catch(e) {{
    document.getElementById('reconciliation').innerHTML =
      '<p style="color:#d97757">Failed: ' + e.message + '</p>';
  }}
}}

async function loadAnalytics() {{
  try {{
    const resp = await fetch('/admin/pipeline/api/ai-usage/analytics', {{credentials:'same-origin'}});
    const d = await resp.json();

    // Trend card
    if (d.trend) {{
      const pct = d.trend.pct_change;
      let pctHtml;
      if (pct === null) pctHtml = '<span style="color:#8a92a0">no prior data</span>';
      else if (pct > 0) pctHtml = '<span style="color:#d97757">▲ +' + pct + '%</span>';
      else if (pct < 0) pctHtml = '<span style="color:#6db585">▼ ' + pct + '%</span>';
      else pctHtml = '<span style="color:#8a92a0">flat</span>';
      document.getElementById('trend-card').innerHTML =
        '<div style="display:flex;gap:12px">'
        + '<div class="stat"><div class="num">$' + d.trend.last_7d.toFixed(4) + '</div><div class="lbl">Last 7 days</div></div>'
        + '<div class="stat"><div class="num">$' + d.trend.prior_7d.toFixed(4) + '</div><div class="lbl">Prior 7 days</div></div>'
        + '<div class="stat"><div class="num">' + pctHtml + '</div><div class="lbl">Change</div></div>'
        + '</div>';
    }}

    // All-time per model
    if (d.alltime && d.alltime.length > 0) {{
      let h = '<table><tr><th>Provider</th><th>Model</th><th>Calls</th><th>Success</th><th>Tokens</th><th>Cost</th></tr>';
      for (const r of d.alltime) {{
        h += '<tr><td style="text-transform:capitalize">' + r.provider + '</td>'
          + '<td style="font-family:monospace;font-size:12px">' + r.model + '</td>'
          + '<td>' + r.calls + '</td><td style="color:#6db585">' + r.success + '</td>'
          + '<td>' + r.tokens.toLocaleString() + '</td>'
          + '<td>' + fmtCost(r.cost_usd) + '</td></tr>';
      }}
      h += '</table>';
      document.getElementById('alltime-stats').innerHTML = h;
    }} else {{
      document.getElementById('alltime-stats').innerHTML = '<p style="color:#8a92a0">No usage logged yet.</p>';
    }}

    // Top tasks by cost
    if (d.top_tasks_by_cost && d.top_tasks_by_cost.length > 0) {{
      let h = '<table><tr><th>Task</th><th>Provider</th><th>Model</th><th>Calls</th><th>Tokens</th><th>Avg latency</th><th>Cost</th></tr>';
      for (const r of d.top_tasks_by_cost) {{
        const lat = r.avg_latency_ms < 1000 ? r.avg_latency_ms + 'ms' : (r.avg_latency_ms/1000).toFixed(1)+'s';
        h += '<tr><td>' + r.task + '</td>'
          + '<td style="text-transform:capitalize">' + r.provider + '</td>'
          + '<td style="font-family:monospace;font-size:12px">' + r.model + '</td>'
          + '<td>' + r.calls + '</td><td>' + r.tokens.toLocaleString() + '</td>'
          + '<td>' + lat + '</td><td>' + fmtCost(r.cost_usd) + '</td></tr>';
      }}
      h += '</table>';
      document.getElementById('top-tasks').innerHTML = h;
    }} else {{
      document.getElementById('top-tasks').innerHTML = '<p style="color:#8a92a0">No successful calls in last 30 days.</p>';
    }}

    // Monthly per model
    if (d.monthly && d.monthly.length > 0) {{
      let h = '<table><tr><th>Month</th><th>Provider</th><th>Model</th><th>Calls</th><th>Tokens</th><th>Cost</th></tr>';
      for (const r of d.monthly) {{
        h += '<tr><td>' + r.month + '</td>'
          + '<td style="text-transform:capitalize">' + r.provider + '</td>'
          + '<td style="font-family:monospace;font-size:12px">' + r.model + '</td>'
          + '<td>' + r.calls + '</td><td>' + r.tokens.toLocaleString() + '</td>'
          + '<td>' + fmtCost(r.cost_usd) + '</td></tr>';
      }}
      h += '</table>';
      document.getElementById('monthly-stats').innerHTML = h;
    }} else {{
      document.getElementById('monthly-stats').innerHTML = '<p style="color:#8a92a0">No monthly data yet.</p>';
    }}

    // Daily per model
    if (d.daily && d.daily.length > 0) {{
      let h = '<table><tr><th>Date</th><th>Provider</th><th>Model</th><th>Calls</th><th>Tokens</th><th>Cost</th></tr>';
      for (const r of d.daily) {{
        h += '<tr><td style="white-space:nowrap;font-size:12px">' + r.day + '</td>'
          + '<td style="text-transform:capitalize">' + r.provider + '</td>'
          + '<td style="font-family:monospace;font-size:12px">' + r.model + '</td>'
          + '<td>' + r.calls + '</td><td>' + r.tokens.toLocaleString() + '</td>'
          + '<td>' + fmtCost(r.cost_usd) + '</td></tr>';
      }}
      h += '</table>';
      document.getElementById('daily-stats').innerHTML = h;
    }} else {{
      document.getElementById('daily-stats').innerHTML = '<p style="color:#8a92a0">No daily data yet.</p>';
    }}

    // Fallback / reliability
    if (d.fallback_rate && d.fallback_rate.length > 0) {{
      let h = '<table><tr><th>Provider</th><th>Successes</th><th>Failures</th><th>Failure rate</th></tr>';
      for (const r of d.fallback_rate) {{
        const color = r.fail_pct > 20 ? '#d97757' : (r.fail_pct > 5 ? '#e8a849' : '#6db585');
        h += '<tr><td style="text-transform:capitalize">' + r.provider + '</td>'
          + '<td style="color:#6db585">' + r.ok + '</td>'
          + '<td style="color:#d97757">' + r.fail + '</td>'
          + '<td style="color:' + color + '">' + r.fail_pct + '%</td></tr>';
      }}
      h += '</table>';
      document.getElementById('fallback-stats').innerHTML = h;
    }} else {{
      document.getElementById('fallback-stats').innerHTML = '<p style="color:#8a92a0">No reliability data yet.</p>';
    }}
  }} catch(e) {{
    document.getElementById('alltime-stats').innerHTML = '<p style="color:#d97757">Failed: ' + e.message + '</p>';
  }}
}}

async function loadCostPerTemplate() {{
  try {{
    const resp = await fetch('/admin/pipeline/api/ai-usage/cost-per-template', {{credentials:'same-origin'}});
    const d = await resp.json();
    const container = document.getElementById('cost-per-template');
    if (!d.templates || d.templates.length === 0) {{
      container.innerHTML = '<p style="color:#8a92a0">No spend attributed to templates yet.</p>';
      return;
    }}
    let html = '<div style="overflow-x:auto;border:1px solid #2a323d;border-radius:4px"><table style="min-width:900px;margin:0">'
      + '<tr><th>Template</th><th>Level · Duration</th><th>Calls</th><th>Tokens</th><th>Cost (USD)</th><th>Per Task</th></tr>';
    for (const t of d.templates) {{
      const perTask = Object.entries(t.by_task || {{}})
        .map(([task, v]) => `${{task}}: ${{fmtCost(v.cost_usd)}} (${{v.calls}})`)
        .join('<br>') || '<span style="color:#5a6472">—</span>';
      html += '<tr>'
        + '<td style="font-size:13px"><a href="/admin/templates/' + encodeURIComponent(t.key) + '" style="color:#e8a849">' + t.title + '</a></td>'
        + '<td style="font-size:12px;color:#8a92a0">' + t.level + ' · ' + t.duration_months + 'mo</td>'
        + '<td style="font-size:12px">' + t.total_calls + '</td>'
        + '<td style="font-size:12px">' + t.total_tokens.toLocaleString() + '</td>'
        + '<td style="font-size:12px;font-weight:600">' + fmtCost(t.total_cost_usd) + '</td>'
        + '<td style="font-size:11px;color:#8a92a0">' + perTask + '</td>'
        + '</tr>';
    }}
    html += '</table></div>';
    container.innerHTML = html;
  }} catch(e) {{
    document.getElementById('cost-per-template').innerHTML = '<p style="color:#d97757">Failed: ' + e.message + '</p>';
  }}
}}

loadUsageData();
loadAnalytics();
loadCostPerTemplate();
loadReconciliation();
loadAlerts();
</script>
</div>
</body></html>"""


# ---- Normalization Dashboard API + Page ----

@router.get("/api/normalization")
async def get_normalization_stats(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get normalization pipeline stats for admin dashboard."""
    from sqlalchemy import case
    from app.models.curriculum import LinkHealth
    from app.curriculum.loader import list_templates

    # ---- Stage A: Discovery stats ----
    status_counts = {}
    for status_val in ["pending", "approved", "generating", "generated", "rejected"]:
        count = await db.scalar(
            select(func.count()).select_from(DiscoveredTopic)
            .where(DiscoveredTopic.status == status_val)
        ) or 0
        status_counts[status_val] = count
    total_topics = sum(status_counts.values())

    avg_confidence = await db.scalar(
        select(func.avg(DiscoveredTopic.confidence_score))
    ) or 0

    # Category distribution
    cat_rows = (await db.execute(
        select(
            DiscoveredTopic.category,
            func.count().label("cnt"),
        ).group_by(DiscoveredTopic.category)
        .order_by(func.count().desc())
    )).all()

    # Discovery runs
    run_rows = (await db.execute(
        select(
            DiscoveredTopic.discovery_run,
            DiscoveredTopic.ai_model_used,
            func.count().label("topics_found"),
        ).group_by(DiscoveredTopic.discovery_run, DiscoveredTopic.ai_model_used)
        .order_by(DiscoveredTopic.discovery_run.desc())
        .limit(10)
    )).all()

    # ---- Stage B: Generation stats ----
    total_templates_on_disk = len(list_templates())

    gen_topics = (await db.execute(
        select(
            DiscoveredTopic.topic_name,
            DiscoveredTopic.templates_generated,
            DiscoveredTopic.generation_error,
            DiscoveredTopic.status,
        ).where(DiscoveredTopic.templates_generated > 0)
        .order_by(DiscoveredTopic.templates_generated.desc())
    )).all()

    total_variants_generated = sum(t.templates_generated for t in gen_topics)
    topics_with_errors = sum(1 for t in gen_topics if t.generation_error)

    # ---- Stage C: Content Refresh stats ----
    total_links = await db.scalar(
        select(func.count()).select_from(LinkHealth)
    ) or 0
    broken_links = await db.scalar(
        select(func.count()).select_from(LinkHealth)
        .where(LinkHealth.consecutive_failures >= 2)
    ) or 0
    ok_links = await db.scalar(
        select(func.count()).select_from(LinkHealth)
        .where(LinkHealth.consecutive_failures == 0)
    ) or 0

    # Broken links by template
    broken_by_template = (await db.execute(
        select(
            LinkHealth.template_key,
            func.count().label("broken_count"),
        ).where(LinkHealth.consecutive_failures >= 2)
        .group_by(LinkHealth.template_key)
        .order_by(func.count().desc())
        .limit(10)
    )).all()

    # ---- Cache stats ----
    cache_stats = _get_cache_stats()

    # ---- Settings ----
    s = await _get_settings(db)

    return {
        "discovery": {
            "total_topics": total_topics,
            "status_counts": status_counts,
            "avg_confidence": round(avg_confidence, 1),
            "categories": [{"category": r.category, "count": r.cnt} for r in cat_rows],
            "recent_runs": [
                {
                    "run_id": r.discovery_run[:19] if r.discovery_run else "",
                    "model": r.ai_model_used,
                    "topics_found": r.topics_found,
                }
                for r in run_rows
            ],
        },
        "generation": {
            "templates_on_disk": total_templates_on_disk,
            "total_variants_generated": total_variants_generated,
            "topics_with_templates": len(gen_topics),
            "topics_with_errors": topics_with_errors,
            "per_topic": [
                {
                    "topic": t.topic_name,
                    "variants": t.templates_generated,
                    "status": t.status,
                    "has_error": bool(t.generation_error),
                    "error": (t.generation_error or "")[:100],
                }
                for t in gen_topics
            ],
        },
        "refresh": {
            "total_links": total_links,
            "ok_links": ok_links,
            "broken_links": broken_links,
            "broken_by_template": [
                {"template": r.template_key, "count": r.broken_count}
                for r in broken_by_template
            ],
            "last_refresh": s.last_refresh_run.isoformat() if s.last_refresh_run else None,
        },
        "cache": cache_stats,
        "config": {
            "max_topics_per_discovery": s.max_topics_per_discovery,
            "discovery_frequency": s.discovery_frequency,
            "auto_approve": s.auto_approve_topics,
            "auto_generate": s.auto_generate_variants,
            "refresh_frequency": s.refresh_frequency,
        },
    }


def _get_cache_stats() -> dict:
    """Get cache file stats by type."""
    from app.services.ai_cache import CACHE_DIR
    import time as _time

    stats = {"discovery": 0, "triage": 0, "generation": 0, "currency_review": 0, "other": 0, "expired": 0, "total_files": 0}
    if not CACHE_DIR.exists():
        return stats

    for path in CACHE_DIR.glob("*.json"):
        stats["total_files"] += 1
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            ptype = data.get("prompt_type", "other")
            if _time.time() > data.get("expires_at", 0):
                stats["expired"] += 1
            elif ptype in stats:
                stats[ptype] += 1
            else:
                stats["other"] += 1
        except Exception:
            stats["other"] += 1

    return stats


@router.get("/normalization")
async def normalization_redirect():
    """Redirect old normalization URL to pipeline page."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/admin/pipeline/", status_code=301)


# ---- Proposals page ----

@router.get("/api/proposals")
async def list_proposals(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all curriculum proposals."""
    from app.models.curriculum import CurriculumProposal
    result = await db.execute(
        select(CurriculumProposal).order_by(CurriculumProposal.created_at.desc())
    )
    proposals = result.scalars().all()
    return [{
        "id": p.id,
        "source_run": p.source_run,
        "status": p.status,
        "created_at": str(p.created_at),
        "reviewed_at": str(p.reviewed_at) if p.reviewed_at else None,
        "notes": p.notes,
        "proposal_md": p.proposal_md[:500],
    } for p in proposals]


@router.get("/api/proposals/{proposal_id}")
async def get_proposal(
    proposal_id: int,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get full proposal content."""
    from app.models.curriculum import CurriculumProposal
    result = await db.execute(
        select(CurriculumProposal).where(CurriculumProposal.id == proposal_id)
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return {
        "id": p.id,
        "source_run": p.source_run,
        "status": p.status,
        "created_at": str(p.created_at),
        "reviewed_at": str(p.reviewed_at) if p.reviewed_at else None,
        "notes": p.notes,
        "proposal_md": p.proposal_md,
    }


@router.post("/api/proposals/{proposal_id}/approve")
async def approve_proposal(
    proposal_id: int,
    request: Request,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Mark a proposal as approved/applied."""
    _check_origin(request)
    from app.models.curriculum import CurriculumProposal
    from datetime import datetime, timezone
    result = await db.execute(
        select(CurriculumProposal).where(CurriculumProposal.id == proposal_id)
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Proposal not found")
    p.status = "applied"
    p.reviewer_id = user.id
    p.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.flush()
    return {"ok": True, "status": "applied"}


@router.post("/api/proposals/{proposal_id}/reject")
async def reject_proposal(
    proposal_id: int,
    request: Request,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Mark a proposal as rejected."""
    _check_origin(request)
    from app.models.curriculum import CurriculumProposal
    from datetime import datetime, timezone
    result = await db.execute(
        select(CurriculumProposal).where(CurriculumProposal.id == proposal_id)
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Proposal not found")
    p.status = "rejected"
    p.reviewer_id = user.id
    p.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.flush()
    return {"ok": True, "status": "rejected"}


@router.get("/proposals", response_class=HTMLResponse)
async def proposals_page(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin proposals review page."""
    from app.models.curriculum import CurriculumProposal

    result = await db.execute(
        select(CurriculumProposal).order_by(CurriculumProposal.created_at.desc())
    )
    proposals = result.scalars().all()

    pending_count = sum(1 for p in proposals if p.status == "pending")

    rows = ""
    for p in proposals:
        status_color = {"pending": "#e8a849", "applied": "#6db585", "rejected": "#d97757"}.get(p.status, "#8a92a0")
        status_badge = f'<span style="color:{status_color};font-weight:600">{p.status.title()}</span>'
        created = str(p.created_at)[:10] if p.created_at else "—"
        reviewed = str(p.reviewed_at)[:10] if p.reviewed_at else "—"
        preview = esc(p.proposal_md[:200]).replace("\\n", " ")

        actions = ""
        if p.status == "pending":
            actions = f"""
                <button class="btn success" style="font-size:11px;padding:4px 8px" onclick="proposalAction({p.id},'approve',this)">Approve</button>
                <button class="btn danger" style="font-size:11px;padding:4px 8px" onclick="proposalAction({p.id},'reject',this)">Reject</button>
            """

        rows += f"""<tr>
            <td>{p.id}</td>
            <td>{esc(p.source_run)}</td>
            <td>{created}</td>
            <td>{status_badge}</td>
            <td>{reviewed}</td>
            <td style="max-width:300px;font-size:12px;color:#8a92a0;overflow:hidden;text-overflow:ellipsis">{preview}</td>
            <td>
                <button class="btn" style="font-size:11px;padding:4px 8px" onclick="viewProposal({p.id})">View</button>
                {actions}
            </td>
        </tr>"""

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Proposals</title>
<style>{ADMIN_CSS}
.modal {{ display:none; position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.7); z-index:100; align-items:center; justify-content:center; }}
.modal-content {{ background:#1d242e; border-radius:8px; padding:24px; max-width:800px; width:90%; max-height:80vh; overflow-y:auto; color:#d0cbc2; white-space:pre-wrap; font-size:13px; line-height:1.7; }}
.modal-close {{ float:right; cursor:pointer; font-size:20px; color:#8a92a0; background:none; border:none; }}
</style></head><body>
{NAV_HTML}
<div class="page">
<h1>Curriculum Proposals <span style="font-size:11px;background:#3a2a1a;color:#e8a849;padding:3px 8px;border-radius:3px;vertical-align:middle;margin-left:8px;letter-spacing:0.08em">LEGACY</span></h1>
<div style="background:#1d242e;border-left:3px solid #8a92a0;padding:12px 16px;border-radius:4px;margin:12px 0 16px;font-size:13px;line-height:1.6">
  <div style="color:#d0cbc2;font-weight:600;margin-bottom:6px">Your workflow — what to do on this page</div>
  <ol style="margin:0 0 8px 18px;padding:0;color:#d0cbc2">
    <li><strong>Check for pending items</strong> — old proposals from the quarterly sync land here. If you see "All reviewed" below, you're done.</li>
    <li><strong>Open each pending proposal</strong> via the Preview column to see the suggested add/update/retire actions.</li>
    <li><strong>Apply</strong> to accept the proposed change, or <strong>Reject</strong> to dismiss it. Both actions are recorded with a reviewer stamp.</li>
    <li><strong>Do NOT generate new curricula from here</strong> — use <a href="/admin/pipeline/topics" style="color:#e8a849">Topics</a> → <a href="/admin/pipeline/" style="color:#e8a849">Pipeline</a> → <a href="/admin/templates" style="color:#e8a849">Templates</a> instead. That's the live flow.</li>
  </ol>
  <div style="color:#8a92a0;font-size:12px"><strong>Legacy:</strong> the quarterly sync cron (Jan / Apr / Jul / Oct 1st) still fills this page, but the auto-curriculum pipeline replaces it for day-to-day work. Safe to ignore this tab unless pending items are shown.</div>
</div>
<p style="color:#8a92a0;font-size:13px;margin-bottom:16px">
    {f'<span style="color:#e8a849;font-weight:600">{pending_count} pending</span>' if pending_count else '<span style="color:#6db585">All reviewed</span>'}
</p>

{'<p style="color:#8a92a0;font-size:13px">No proposals yet. The quarterly sync runs on Jan/Apr/Jul/Oct 1st, or trigger it manually from the Pipeline page.</p>' if not proposals else f"""
<table>
<tr><th>ID</th><th>Run</th><th>Created</th><th>Status</th><th>Reviewed</th><th>Preview</th><th>Actions</th></tr>
{rows}
</table>
"""}

<div class="modal" id="proposalModal">
    <div class="modal-content">
        <button class="modal-close" onclick="document.getElementById('proposalModal').style.display='none'">&times;</button>
        <div id="proposalContent">Loading...</div>
    </div>
</div>

<script>
async function viewProposal(id) {{
    const modal = document.getElementById('proposalModal');
    const content = document.getElementById('proposalContent');
    content.textContent = 'Loading...';
    modal.style.display = 'flex';
    try {{
        const resp = await fetch('/admin/pipeline/api/proposals/' + id, {{credentials: 'same-origin'}});
        const data = await resp.json();
        content.textContent = data.proposal_md;
    }} catch(e) {{
        content.textContent = 'Error: ' + e.message;
    }}
}}

async function proposalAction(id, action, btn) {{
    btn.disabled = true;
    try {{
        const resp = await fetch('/admin/pipeline/api/proposals/' + id + '/' + action, {{
            method: 'POST', credentials: 'same-origin'
        }});
        if (resp.ok) window.location.reload();
        else alert('Failed: ' + (await resp.json()).detail);
    }} catch(e) {{
        alert('Error: ' + e.message);
    }}
    btn.disabled = false;
}}

document.getElementById('proposalModal').addEventListener('click', function(e) {{
    if (e.target === this) this.style.display = 'none';
}});
</script>
</div></body></html>"""
