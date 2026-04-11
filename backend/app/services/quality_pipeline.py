"""
AI Quality Pipeline: Generate → Review → Refine → Validate.

Improves curriculum quality using multi-model cross-review:
1. GENERATE: Free model creates initial curriculum (existing flow)
2. SCORE: Heuristic scorer checks base quality (no AI cost)
3. REVIEW: Different AI model critiques on 10 dimensions (Gemini preferred)
4. REFINE: Claude surgically fixes only broken weeks (minimal tokens)
5. VALIDATE: Heuristic scorer confirms improvement (no AI cost)

Cost optimization:
- Skip review if heuristic score >= 85
- Skip refinement if all review dimensions >= 7
- Claude only sees broken weeks (3-5 out of 24), not full plan
- Cache review results by template hash
- Cross-review: never use same model for generation and review
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai_cache import cache_get, cache_set

logger = logging.getLogger("roadmap.quality_pipeline")

REVIEW_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "review_curriculum.txt"
REFINE_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "refine_curriculum.txt"

# Thresholds
SKIP_REVIEW_THRESHOLD = 85      # Heuristic score above which we skip AI review
SKIP_REFINE_THRESHOLD = 7       # All dimensions >= this → skip refinement
CLAUDE_THRESHOLD = 3            # Use Claude only if >= this many dimensions fail
REVIEW_CACHE_TTL = 86400 * 30   # 30 days


def _plan_hash(plan: dict) -> str:
    """Deterministic hash of plan content for cache keying."""
    raw = json.dumps(plan, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


async def run_quality_pipeline(
    plan: dict,
    generator_model: str,
    db: AsyncSession | None = None,
) -> dict:
    """Run the full quality improvement pipeline on a generated curriculum.

    Args:
        plan: The generated curriculum dict
        generator_model: Which model generated it (to avoid self-review)
        db: DB session for usage logging

    Returns:
        {
            "plan": improved_plan_dict,
            "original_score": int,
            "final_score": int,
            "review": review_dict or None,
            "refined_weeks": list of week numbers that were fixed,
            "stages_run": ["score", "review", "refine", "validate"],
            "models_used": {"review": "gemini", "refine": "claude"},
            "skipped": ["review: score >= 85"] or [],
        }
    """
    result = {
        "plan": plan,
        "original_score": 0,
        "final_score": 0,
        "review": None,
        "refined_weeks": [],
        "stages_run": [],
        "models_used": {},
        "skipped": [],
    }

    # ---- Stage 1: Heuristic Score ----
    heuristic_score = _quick_heuristic_score(plan)
    result["original_score"] = heuristic_score
    result["stages_run"].append("score")
    logger.info("Quality pipeline: heuristic score = %d", heuristic_score)

    if heuristic_score >= SKIP_REVIEW_THRESHOLD:
        result["final_score"] = heuristic_score
        result["skipped"].append(f"review: heuristic score {heuristic_score} >= {SKIP_REVIEW_THRESHOLD}")
        logger.info("Quality pipeline: skipping review (score %d >= %d)", heuristic_score, SKIP_REVIEW_THRESHOLD)
        return result

    # ---- Stage 2: AI Review (cross-model) ----
    plan_h = _plan_hash(plan)
    cached_review = cache_get("quality_review", plan_h)

    if cached_review is not None:
        review = cached_review
        result["models_used"]["review"] = "cached"
        logger.info("Quality pipeline: using cached review")
    else:
        review_model = _pick_review_model(generator_model)
        review = await _run_ai_review(plan, review_model, db)
        if review:
            cache_set("quality_review", plan_h, review, ttl=REVIEW_CACHE_TTL)
            result["models_used"]["review"] = review_model
        else:
            result["skipped"].append("review: AI review failed")
            result["final_score"] = heuristic_score
            return result

    result["review"] = review
    result["stages_run"].append("review")

    # Check if refinement needed
    failing_dims = review.get("dimensions_below_threshold", [])
    if not failing_dims:
        # Extract from scores
        for dim_key in ["blooms_progression", "theory_practice_ratio", "project_density",
                        "assessment_quality", "completeness", "difficulty_calibration",
                        "industry_alignment", "freshness", "prerequisites_clarity",
                        "real_world_readiness"]:
            dim_data = review.get(dim_key, {})
            if isinstance(dim_data, dict) and dim_data.get("score", 10) < SKIP_REFINE_THRESHOLD:
                failing_dims.append(dim_key)

    if not failing_dims:
        result["final_score"] = heuristic_score
        result["skipped"].append("refine: all dimensions >= threshold")
        logger.info("Quality pipeline: skipping refinement (all dimensions pass)")
        return result

    # ---- Stage 3: Refinement (Claude for many issues, Gemini for few) ----
    critical_fixes = review.get("critical_fixes", [])
    if not critical_fixes:
        result["final_score"] = heuristic_score
        result["skipped"].append("refine: no critical fixes identified")
        return result

    # Determine which weeks need fixing
    fix_week_nums = list(set(f.get("week", 0) for f in critical_fixes if f.get("week")))
    if not fix_week_nums:
        result["final_score"] = heuristic_score
        result["skipped"].append("refine: no specific weeks identified")
        return result

    # Pick refinement model based on severity
    if len(failing_dims) >= CLAUDE_THRESHOLD:
        refine_model = "claude"
        logger.info("Quality pipeline: using Claude for %d failing dimensions", len(failing_dims))
    else:
        refine_model = "gemini"
        logger.info("Quality pipeline: using Gemini for %d failing dimensions (minor)", len(failing_dims))

    refined_plan = await _run_refinement(plan, critical_fixes, fix_week_nums, refine_model, db)

    if refined_plan:
        result["plan"] = refined_plan
        result["refined_weeks"] = fix_week_nums
        result["models_used"]["refine"] = refine_model
        result["stages_run"].append("refine")
    else:
        result["skipped"].append("refine: refinement call failed, keeping original")

    # ---- Stage 4: Validate ----
    final_score = _quick_heuristic_score(result["plan"])
    result["final_score"] = final_score
    result["stages_run"].append("validate")

    if final_score < heuristic_score:
        # Refinement made it worse — revert
        result["plan"] = plan
        result["final_score"] = heuristic_score
        result["skipped"].append(f"validate: refinement regressed ({final_score} < {heuristic_score}), reverted")
        logger.warning("Quality pipeline: refinement regressed (%d < %d), reverting", final_score, heuristic_score)
    else:
        logger.info("Quality pipeline: improved %d → %d (+%d)", heuristic_score, final_score, final_score - heuristic_score)

    return result


def _quick_heuristic_score(plan: dict) -> int:
    """Fast heuristic score without DB access (subset of quality_scorer)."""
    from app.curriculum.loader import PlanTemplate
    try:
        tpl = PlanTemplate(**plan)
    except Exception:
        return 0

    score = 100
    import re

    # Structure checks
    expected_weeks = tpl.duration_months * 4
    if tpl.total_weeks < expected_weeks * 0.8:
        score -= 15

    empty_weeks = sum(1 for m in tpl.months for w in m.weeks if not w.focus and not w.deliv)
    score -= min(20, empty_weeks * 5)

    no_resource_weeks = sum(1 for m in tpl.months for w in m.weeks if not w.resources)
    score -= min(15, no_resource_weeks * 5)

    # Checklist vagueness
    vague_patterns = [r"^understand\b", r"^learn\b", r"^know\b", r"^study\b",
                      r"^read about\b", r"^explore\b", r"^review\b", r"^familiarize\b"]
    all_checks = [c for m in tpl.months for w in m.weeks for c in w.checks]
    if all_checks:
        vague_count = sum(1 for c in all_checks if any(re.match(p, c.strip(), re.IGNORECASE) for p in vague_patterns))
        vague_pct = vague_count / len(all_checks) * 100
        score -= min(25, int(vague_pct * 0.5))

    # Resource diversity
    from urllib.parse import urlparse
    urls = [r.url for m in tpl.months for w in m.weeks for r in w.resources]
    if urls:
        domains = set()
        for u in urls:
            try:
                h = urlparse(u).hostname or ""
                if h.startswith("www."):
                    h = h[4:]
                domains.add(h)
            except Exception:
                pass
        if len(domains) < 3:
            score -= 10

    return max(0, min(100, score))


def _pick_review_model(generator_model: str) -> str:
    """Pick a different model for cross-review."""
    from app.config import get_settings
    settings = get_settings()

    # Priority: Gemini for review (good at analysis), then Groq
    if "gemini" not in generator_model.lower() and settings.gemini_api_key:
        return "gemini"
    if "groq" not in generator_model.lower() and "llama" not in generator_model.lower() and settings.groq_api_key:
        return "groq"
    if settings.gemini_api_key:
        return "gemini"
    if settings.groq_api_key:
        return "groq"
    return "mistral"


async def _run_ai_review(plan: dict, model_name: str, db: AsyncSession | None) -> dict | None:
    """Run AI quality review on a curriculum."""
    prompt_template = REVIEW_PROMPT_PATH.read_text(encoding="utf-8")
    # Compact JSON to save tokens
    plan_json = json.dumps(plan, separators=(",", ":"))
    prompt = prompt_template.format(plan_json=plan_json)

    try:
        if model_name == "gemini":
            from app.ai.gemini import complete
            result = await complete(prompt, json_response=True)
        elif model_name == "groq":
            from app.ai.groq import complete
            result = await complete(prompt, json_response=True)
        else:
            from app.ai.provider import complete as ai_complete
            result, _ = await ai_complete(prompt, json_response=True,
                                          task="quality_review", db=db)

        if isinstance(result, str):
            result = json.loads(result)

        # Log usage
        if db is not None:
            from app.ai.health import log_usage
            await log_usage(db, model_name, model_name, "quality_review", "ok")

        return result
    except Exception as e:
        logger.error("AI review failed (%s): %s", model_name, e)
        if db is not None:
            from app.ai.health import log_usage
            await log_usage(db, model_name, model_name, "quality_review", "error",
                           error_message=str(e))
        return None


async def _run_refinement(
    plan: dict,
    critical_fixes: list[dict],
    fix_week_nums: list[int],
    model_name: str,
    db: AsyncSession | None,
) -> dict | None:
    """Run refinement on broken weeks only (surgical fix)."""
    # Extract only the failing weeks from the plan
    failing_weeks = []
    month_context = ""
    for m in plan.get("months", []):
        for w in m.get("weeks", []):
            if w.get("n") in fix_week_nums:
                failing_weeks.append(w)
                month_context = f"{m.get('month', '?')}"

    if not failing_weeks:
        return None

    prompt_template = REFINE_PROMPT_PATH.read_text(encoding="utf-8")
    prompt = prompt_template.format(
        failing_weeks_json=json.dumps(failing_weeks, separators=(",", ":")),
        critical_fixes_json=json.dumps(critical_fixes, separators=(",", ":")),
        topic=plan.get("title", ""),
        level=plan.get("level", ""),
        month_context=month_context,
        duration_months=plan.get("duration_months", 6),
    )

    try:
        if model_name == "claude":
            from app.ai.anthropic import complete
            fixed_weeks = await complete(prompt, json_response=True)
        elif model_name == "gemini":
            from app.ai.gemini import complete
            fixed_weeks = await complete(prompt, json_response=True)
        else:
            from app.ai.provider import complete as ai_complete
            fixed_weeks, _ = await ai_complete(prompt, json_response=True,
                                               task="quality_refine", db=db)

        if isinstance(fixed_weeks, str):
            fixed_weeks = json.loads(fixed_weeks)

        # Log usage
        if db is not None:
            from app.ai.health import log_usage
            weeks_str = ",".join(str(n) for n in fix_week_nums)
            await log_usage(db, model_name, model_name, "quality_refine", "ok",
                           subtask=f"weeks:{weeks_str}")

        # Merge fixed weeks back into the plan
        if not isinstance(fixed_weeks, list):
            logger.warning("Refinement returned non-list: %s", type(fixed_weeks))
            return None

        patched = json.loads(json.dumps(plan))  # deep copy
        fixed_by_num = {w["n"]: w for w in fixed_weeks if isinstance(w, dict) and "n" in w}

        for m in patched.get("months", []):
            for i, w in enumerate(m.get("weeks", [])):
                if w.get("n") in fixed_by_num:
                    m["weeks"][i] = fixed_by_num[w["n"]]

        logger.info("Refinement: patched %d weeks via %s", len(fixed_by_num), model_name)
        return patched

    except Exception as e:
        logger.error("Refinement failed (%s): %s", model_name, e)
        if db is not None:
            from app.ai.health import log_usage
            await log_usage(db, model_name, model_name, "quality_refine", "error",
                           error_message=str(e))
        return None
