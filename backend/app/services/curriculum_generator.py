"""
AI-powered curriculum generator with quality pipeline.

Flow: Generate → Heuristic Score → AI Review → Refine → Validate.
Uses multi-model cross-review for quality assurance.
"""

import json
import logging
import re
from pathlib import Path

from app.ai.provider import complete as ai_complete
from app.curriculum.loader import PlanTemplate

logger = logging.getLogger("roadmap.curriculum_gen")

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "generate_curriculum.txt"
TEMPLATES_DIR = Path(__file__).parent.parent / "curriculum" / "templates"


def _make_key(topic: str, duration: str, level: str) -> str:
    """Generate a template key from topic, duration, level."""
    clean = re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")
    return f"{clean}_{duration}_{level}"


async def generate_curriculum(
    topic: str,
    duration_months: int,
    level: str,
    db=None,
    quality_check: bool = True,
) -> dict:
    """Generate a curriculum plan using AI, with optional quality pipeline.

    Args:
        topic: Course topic name
        duration_months: 3, 6, 9, or 12
        level: beginner, intermediate, or advanced
        db: DB session for usage logging
        quality_check: If True, run review → refine → validate pipeline

    Returns the validated plan dict. Raises on failure.
    """
    duration_map = {3: "3mo", 6: "6mo", 9: "9mo", 12: "12mo"}
    duration_str = duration_map.get(duration_months, f"{duration_months}mo")
    total_weeks = duration_months * 4
    key = _make_key(topic, duration_str, level)
    goal = re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")

    prompt_template = PROMPT_PATH.read_text(encoding="utf-8")
    prompt = prompt_template.format(
        topic=topic,
        duration_months=duration_months,
        total_weeks=total_weeks,
        level=level,
        key=key,
        goal=goal,
    )

    # Stage 1a: Try Gemini with structured output schema first — guarantees
    # valid JSON shape and eliminates parse-retry loops. Falls through to the
    # normal provider chain on any failure.
    result = None
    model = None
    try:
        from app.config import get_settings as _app_settings
        if _app_settings().gemini_api_key:
            from app.ai.gemini import complete as gemini_complete, GeminiError
            from app.ai.schemas import PLAN_TEMPLATE_SCHEMA
            try:
                result = await gemini_complete(
                    prompt, json_response=True,
                    task="generation",
                    json_schema=PLAN_TEMPLATE_SCHEMA,
                )
                model = _app_settings().gemini_model
                if db is not None:
                    from app.ai.health import log_usage
                    from app.ai.gemini import _last_usage as _gem_usage
                    await log_usage(
                        db, "gemini", model, "generation", "ok",
                        subtask=f"{topic} {duration_str} {level} [schema]",
                        tokens_estimated=int((_gem_usage or {}).get("total_tokens", 0)),
                    )
            except GeminiError as e:
                logger.warning("Gemini structured generation failed, using fallback chain: %s", e)
                result = None
    except Exception as e:
        logger.warning("Structured generation path error (falling through): %s", e)
        result = None

    # Stage 1b: Fallback to provider chain if structured path didn't succeed
    if result is None:
        result, model = await ai_complete(
            prompt, json_response=True,
            task="generation", subtask=f"{topic} {duration_str} {level}",
            db=db,
        )

    if isinstance(result, str):
        result = json.loads(result)

    # Validate against Pydantic schema
    template = PlanTemplate(**result)

    logger.info(
        "Generated curriculum: %s (%d months, %d weeks, %d checks) via %s",
        template.key, template.duration_months, template.total_weeks, template.total_checks, model,
    )

    # Stage 2-5: Quality pipeline (if enabled)
    if quality_check:
        try:
            from app.services.quality_pipeline import run_quality_pipeline
            qr = await run_quality_pipeline(result, model, db)

            improved_plan = qr["plan"]
            orig = qr["original_score"]
            final = qr["final_score"]
            stages = qr["stages_run"]
            models = qr["models_used"]
            skipped = qr["skipped"]

            if final > orig:
                logger.info(
                    "Quality pipeline improved %s: %d → %d (+%d) | stages=%s models=%s",
                    key, orig, final, final - orig, stages, models,
                )
                result = improved_plan
                # Re-validate after refinement
                PlanTemplate(**result)
            elif skipped:
                logger.info(
                    "Quality pipeline skipped for %s (score=%d): %s",
                    key, orig, "; ".join(skipped),
                )
            else:
                logger.info("Quality pipeline: no improvement for %s (score=%d)", key, orig)

        except Exception as e:
            logger.warning("Quality pipeline failed for %s (keeping original): %s", key, e)

    return result


async def save_curriculum_draft(plan_data: dict) -> str:
    """Save a generated curriculum as a draft JSON file.

    Returns the file path.
    """
    key = plan_data.get("key", "unknown")
    path = TEMPLATES_DIR / f"{key}.json"

    with open(path, "w", encoding="utf-8") as f:
        json.dump(plan_data, f, indent=2)

    # Clear the template cache so it's picked up
    from app.curriculum.loader import load_template
    load_template.cache_clear()

    logger.info("Saved curriculum draft: %s", path)
    return str(path)
