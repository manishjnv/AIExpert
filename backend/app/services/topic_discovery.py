"""
Auto-discovery service — AI researches trending AI/ML topics.

Follows AI Enrichment Blueprint:
- Cache-first: check cache before every AI call
- Budget-gated: check token budget before every AI call
- Schema-enforced: validate every AI output against Pydantic schema
- Reasoning trail: every output includes justification
- Model tiering: Gemini for research, Groq for triage
- Triage pattern: cheap classifier filters before expensive reasoner

Follows Normalization Blueprint:
- Deduplication: normalized_name prevents re-discovering existing topics
- Lifecycle state machine: pending → approved → generating → generated (or rejected)
- Idempotent: safe to re-run
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.curriculum import CurriculumSettings, DiscoveredTopic
from app.services.ai_cache import cache_get, cache_set
from app.services.budget import BudgetExceeded, check_budget, track_tokens

logger = logging.getLogger("roadmap.discovery")

DISCOVER_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "discover_topics.txt"
TRIAGE_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "triage_topic.txt"

# Estimated tokens per call (for budget tracking without actual token counting)
DISCOVERY_TOKENS_ESTIMATE = 3000
TRIAGE_TOKENS_ESTIMATE = 200


# ----- Schema enforcement (per enrichment blueprint) -----

class DiscoveredTopicSchema(BaseModel):
    """Strict schema for a single AI-discovered topic."""
    topic_name: str = Field(min_length=3, max_length=200)
    category: str
    subcategory: Optional[str] = None
    justification: str = Field(min_length=20)
    evidence_sources: list[str] = Field(min_length=1)
    confidence_score: int = Field(ge=0, le=100)

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        allowed = {"nlp", "cv", "mlops", "rl", "generative", "multimodal",
                    "optimization", "safety", "agents", "data_engineering", "edge_ml", "other"}
        if v.lower() not in allowed:
            return "other"
        return v.lower()


class DiscoveryResponseSchema(BaseModel):
    """Strict schema for the full discovery AI response."""
    topics: list[DiscoveredTopicSchema]
    research_notes: str = ""


class TriageResponseSchema(BaseModel):
    """Schema for triage classifier response."""
    worth_generating: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


def _normalize_topic_name(name: str) -> str:
    """Normalize topic name for dedup (per normalization blueprint)."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


async def _get_existing_topic_names(db: AsyncSession) -> list[str]:
    """Get all existing topic names for dedup."""
    result = await db.execute(select(DiscoveredTopic.topic_name))
    return [row[0] for row in result.all()]


async def run_discovery(db: AsyncSession) -> dict:
    """Run a full topic discovery cycle.

    Returns summary dict with discovered/skipped/errors counts.
    """
    from app.services.budget import get_settings as get_budget_settings

    settings = await get_budget_settings(db)
    run_id = datetime.now(timezone.utc).isoformat()

    logger.info("Starting topic discovery run: %s", run_id)

    # 1. Budget check (per enrichment blueprint invariant #2)
    try:
        budget_status, used_pct = await check_budget(db)
    except BudgetExceeded as e:
        logger.error("Discovery aborted: %s", e)
        return {"status": "budget_exceeded", "error": str(e)}

    # 2. Cache check (per enrichment blueprint invariant #1)
    cache_key_params = f"discovery:{settings.max_topics_per_discovery}"
    cached = cache_get("discovery", cache_key_params)
    if cached is not None:
        logger.info("Using cached discovery results")
        # Still process cached results to save new topics
        return await _process_discovery_results(
            cached, run_id, "cached", db, settings
        )

    # 3. Get existing topics for dedup (per normalization blueprint)
    # Sanitize for prompt injection: wrap in JSON to prevent instruction injection
    existing_topics = await _get_existing_topic_names(db)
    existing_str = json.dumps(existing_topics) if existing_topics else "[]"

    # 4. Build prompt and call AI
    prompt_template = DISCOVER_PROMPT_PATH.read_text(encoding="utf-8")
    prompt = prompt_template.format(
        max_topics=settings.max_topics_per_discovery,
        existing_topics=existing_str,
    )

    # Model selection: use research model (Gemini by default), fallback if budget tight
    use_fallback = budget_status == "fallback"

    try:
        if use_fallback:
            from app.ai.groq import complete as groq_complete
            raw_result = await groq_complete(prompt, json_response=True)
            model_used = "groq_fallback"
        else:
            from app.ai.provider import complete as ai_complete
            raw_result, model_used = await ai_complete(prompt, json_response=True)
    except Exception as e:
        logger.error("AI discovery call failed: %s", e)
        return {"status": "ai_error", "error": str(e)}

    # 5. Track token usage (per enrichment blueprint)
    await track_tokens(db, DISCOVERY_TOKENS_ESTIMATE)

    # 6. Parse response
    if isinstance(raw_result, str):
        raw_result = json.loads(raw_result)

    # 7. Cache the result (per enrichment blueprint)
    cache_set("discovery", cache_key_params, raw_result, ttl=86400)  # 24h cache

    # 8. Schema validation (per enrichment blueprint invariant #3)
    return await _process_discovery_results(raw_result, run_id, model_used, db, settings)


async def _process_discovery_results(
    raw_result: dict,
    run_id: str,
    model_used: str,
    db: AsyncSession,
    settings: CurriculumSettings,
) -> dict:
    """Validate, dedup, and save discovered topics."""
    # Schema validation
    try:
        validated = DiscoveryResponseSchema(**raw_result)
    except Exception as e:
        logger.error("Discovery response failed schema validation: %s", e)
        return {"status": "schema_error", "error": str(e)}

    saved = 0
    skipped_dedup = 0
    skipped_triage = 0
    errors = 0

    for topic_data in validated.topics:
        normalized = _normalize_topic_name(topic_data.topic_name)

        # Dedup check (per normalization blueprint)
        existing = await db.execute(
            select(DiscoveredTopic).where(DiscoveredTopic.normalized_name == normalized)
        )
        if existing.scalar_one_or_none() is not None:
            logger.info("Skipping duplicate topic: %s", topic_data.topic_name)
            skipped_dedup += 1
            continue

        # Triage (per enrichment blueprint: cheap classifier before expensive work)
        triage_result = await _triage_topic(topic_data, db)
        if triage_result is not None and not triage_result.worth_generating:
            logger.info("Triage rejected topic: %s (reason: %s)",
                        topic_data.topic_name, triage_result.reason)
            skipped_triage += 1
            continue

        # Save to DB
        try:
            initial_status = "approved" if settings.auto_approve_topics else "pending"
            topic = DiscoveredTopic(
                topic_name=topic_data.topic_name,
                normalized_name=normalized,
                category=topic_data.category,
                subcategory=topic_data.subcategory,
                justification=topic_data.justification,
                evidence_sources=json.dumps(topic_data.evidence_sources),
                confidence_score=topic_data.confidence_score,
                status=initial_status,
                discovery_run=run_id,
                ai_model_used=model_used,
            )
            db.add(topic)
            await db.flush()
            saved += 1
            logger.info("Saved topic: %s (status=%s, confidence=%d)",
                        topic_data.topic_name, initial_status, topic_data.confidence_score)
        except Exception as e:
            logger.error("Failed to save topic %s: %s", topic_data.topic_name, e)
            errors += 1

    # Update last run timestamp
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    settings.last_discovery_run = now
    await db.flush()

    summary = {
        "status": "ok",
        "run_id": run_id,
        "model_used": model_used,
        "total_discovered": len(validated.topics),
        "saved": saved,
        "skipped_dedup": skipped_dedup,
        "skipped_triage": skipped_triage,
        "errors": errors,
        "research_notes": validated.research_notes,
    }
    logger.info("Discovery complete: %s", summary)
    return summary


async def _triage_topic(
    topic: DiscoveredTopicSchema,
    db: AsyncSession,
) -> TriageResponseSchema | None:
    """Run cheap triage classifier on a topic.

    Per enrichment blueprint: triage pattern filters ~80% before expensive work.
    Uses Groq (cheap/fast model).
    Returns None if triage fails (topic passes by default).
    """
    # Budget check for triage call
    try:
        await check_budget(db)
    except BudgetExceeded:
        return None  # pass through if budget exceeded (fail open for triage)

    # Cache check
    cache_params = f"triage:{topic.topic_name}"
    cached = cache_get("triage", cache_params)
    if cached is not None:
        try:
            return TriageResponseSchema(**cached)
        except Exception:
            pass

    prompt_template = TRIAGE_PROMPT_PATH.read_text(encoding="utf-8")
    # Sanitize: truncate and strip control chars to prevent prompt injection
    safe_name = topic.topic_name[:100].replace("\n", " ")
    safe_category = topic.category[:50].replace("\n", " ")
    safe_justification = topic.justification[:300].replace("\n", " ")
    prompt = prompt_template.format(
        topic_name=safe_name,
        category=safe_category,
        justification=safe_justification,
    )

    try:
        from app.ai.groq import complete as groq_complete
        raw = await groq_complete(prompt, json_response=True)
        await track_tokens(db, TRIAGE_TOKENS_ESTIMATE)

        if isinstance(raw, str):
            raw = json.loads(raw)

        result = TriageResponseSchema(**raw)
        cache_set("triage", cache_params, raw, ttl=86400 * 7)
        return result
    except Exception as e:
        logger.warning("Triage failed for %s: %s (passing through)", topic.topic_name, e)
        return None  # fail open
