"""
Batch generation service — generates curriculum template variants for approved topics.

For each approved topic, generates up to 6 variants:
- 3mo beginner, 3mo intermediate, 3mo advanced
- 6mo beginner, 6mo intermediate, 6mo advanced

Follows AI Enrichment Blueprint:
- Model tiering: Gemini for deep content generation, Groq for triage
- Budget-gated: checks budget before each generation
- Schema-enforced: validates against PlanTemplate schema
- Cache: caches generation results to avoid re-work

Follows Normalization Blueprint:
- Lifecycle state machine: approved → generating → generated
- Idempotent: skips already-generated variants
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.curriculum import CurriculumSettings, DiscoveredTopic
from app.services.ai_cache import cache_get, cache_set
from app.services.budget import BudgetExceeded, check_budget, track_tokens
from app.services.curriculum_generator import generate_curriculum, save_curriculum_draft

logger = logging.getLogger("roadmap.batch_gen")

# Variants to generate per topic
VARIANTS = [
    (3, "beginner"),
    (3, "intermediate"),
    (6, "beginner"),
    (6, "intermediate"),
    (6, "advanced"),
]

GENERATION_TOKENS_ESTIMATE = 5000  # per variant


async def run_batch_generation(db: AsyncSession) -> dict:
    """Generate curriculum variants for all approved topics.

    Returns summary dict.
    """
    from app.services.budget import get_settings as get_budget_settings

    settings = await get_budget_settings(db)

    # Find approved topics
    result = await db.execute(
        select(DiscoveredTopic).where(DiscoveredTopic.status == "approved")
    )
    approved_topics = result.scalars().all()

    if not approved_topics:
        logger.info("No approved topics to generate")
        return {"status": "ok", "message": "No approved topics", "generated": 0}

    logger.info("Batch generation starting for %d approved topics", len(approved_topics))

    total_generated = 0
    total_skipped = 0
    total_errors = 0
    topic_results = []

    for topic in approved_topics:
        # Transition to "generating" state
        topic.status = "generating"
        topic.generation_error = None
        await db.flush()

        variants_generated = 0
        variant_errors = []

        for duration, level in VARIANTS:
            # Budget check before each generation
            try:
                budget_status, _ = await check_budget(db)
            except BudgetExceeded as e:
                logger.warning("Budget exceeded during batch generation: %s", e)
                topic.status = "approved"  # revert so it can be retried
                topic.generation_error = f"Budget exceeded after {variants_generated} variants"
                await db.flush()
                return {
                    "status": "budget_exceeded",
                    "generated": total_generated,
                    "skipped": total_skipped,
                    "errors": total_errors,
                    "topic_results": topic_results,
                }

            # Cache check
            cache_params = f"gen:{topic.normalized_name}:{duration}mo:{level}"
            cached = cache_get("generation", cache_params)
            if cached is not None:
                # Already generated — save if not on disk
                try:
                    from app.curriculum.loader import load_template
                    key = cached.get("key", "")
                    load_template(key)
                    # Already exists on disk, skip
                    total_skipped += 1
                    continue
                except FileNotFoundError:
                    # Cached but not on disk — save it
                    await save_curriculum_draft(cached)
                    variants_generated += 1
                    total_generated += 1
                    continue

            # Generate via AI
            try:
                plan_data = await generate_curriculum(
                    topic.topic_name, duration, level, db=db
                )
                await save_curriculum_draft(plan_data)

                # Track budget
                await track_tokens(db, GENERATION_TOKENS_ESTIMATE)

                # Cache the result
                cache_set("generation", cache_params, plan_data, ttl=86400 * 30)

                variants_generated += 1
                total_generated += 1
                logger.info("Generated: %s %dmo %s", topic.topic_name, duration, level)

            except Exception as e:
                error_msg = f"{duration}mo {level}: {e}"
                variant_errors.append(error_msg)
                total_errors += 1
                logger.error("Generation failed for %s %dmo %s: %s",
                             topic.topic_name, duration, level, e)

        # Update topic status
        topic.templates_generated = variants_generated
        if variant_errors:
            topic.generation_error = "; ".join(variant_errors)

        if variants_generated > 0:
            topic.status = "generated"
        else:
            # All variants failed — revert to approved for retry
            topic.status = "approved"

        await db.flush()

        topic_results.append({
            "topic": topic.topic_name,
            "generated": variants_generated,
            "errors": len(variant_errors),
        })

    # Update last run timestamp
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    settings.last_generation_run = now
    await db.flush()

    summary = {
        "status": "ok",
        "total_topics": len(approved_topics),
        "generated": total_generated,
        "skipped": total_skipped,
        "errors": total_errors,
        "topic_results": topic_results,
    }
    logger.info("Batch generation complete: %s", summary)
    return summary
