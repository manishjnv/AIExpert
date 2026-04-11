"""
AI-powered curriculum generator.

Takes a topic, duration, and level, calls AI to generate a full
plan template JSON, validates it, and saves as a draft.
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


async def generate_curriculum(topic: str, duration_months: int, level: str) -> dict:
    """Generate a curriculum plan using AI.

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

    # Call AI — need a larger response for full curriculum
    result, model = await ai_complete(prompt, json_response=True)

    if isinstance(result, str):
        result = json.loads(result)

    # Validate against Pydantic schema
    template = PlanTemplate(**result)

    logger.info(
        "Generated curriculum: %s (%d months, %d weeks, %d checks)",
        template.key, template.duration_months, template.total_weeks, template.total_checks,
    )

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
