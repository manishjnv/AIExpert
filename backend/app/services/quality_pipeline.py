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
- Batch API: 5+ refinements submitted as single batch for 50% Claude discount
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
SKIP_REVIEW_THRESHOLD = 92      # Heuristic score above which we skip AI review
SKIP_REFINE_THRESHOLD = 8       # All dimensions >= this → skip refinement
PRO_THRESHOLD = 3               # Use Gemini Pro only if >= this many dimensions fail (else Flash)
REVIEW_CACHE_TTL = 86400 * 30   # 30 days


def _plan_hash(plan: dict) -> str:
    """Structural fingerprint of a plan for cache keying.

    Uses the content that matters for quality review (title, level, weeks,
    focus, deliv, check texts, resource URLs) — ignoring whitespace, key
    order, and non-content metadata. Trivial edits hit the cache instead of
    paying for a fresh review.
    """
    def _norm_str(s):
        return " ".join(s.split()).strip().lower() if isinstance(s, str) else ""

    fingerprint = {
        "title": _norm_str(plan.get("title", "")),
        "goal": _norm_str(plan.get("goal", "")),
        "level": _norm_str(plan.get("level", "")),
        "duration_months": plan.get("duration_months"),
        "weeks": [],
    }
    for m in plan.get("months", []) or []:
        for w in m.get("weeks", []) or []:
            fingerprint["weeks"].append({
                "n": w.get("n"),
                "hours": w.get("hours"),
                "focus": sorted(_norm_str(x) for x in (w.get("focus") or [])),
                "deliv": sorted(_norm_str(x) for x in (w.get("deliv") or [])),
                "checks": sorted(_norm_str(x) for x in (w.get("checks") or [])),
                "resource_urls": sorted(
                    _norm_str((r or {}).get("url", ""))
                    for r in (w.get("resources") or []) if isinstance(r, dict)
                ),
            })
    raw = json.dumps(fingerprint, sort_keys=True, separators=(",", ":"))
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

    # ---- Stage 0: Deterministic pre-fix (free, no LLM) ----
    plan, prefix_fixes = _auto_fix(plan)
    if prefix_fixes:
        result["stages_run"].append("prefix")
        result["models_used"]["prefix"] = "local"
        result["plan"] = plan
        logger.info("Quality pipeline: deterministic pre-fix applied — %s",
                    ", ".join(f"{k}={v}" for k, v in prefix_fixes.items()))

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

    # Heuristic diagnostics — pattern-specific failures the AI review won't see.
    # These are merged into critical_fixes so the refiner knows exactly what to rewrite.
    heuristic_fixes, heuristic_weeks = _heuristic_diagnostics(plan)
    if heuristic_fixes:
        logger.info("Quality pipeline: %d heuristic fix(es) added — weeks %s",
                    len(heuristic_fixes), heuristic_weeks)

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

    if not failing_dims and not heuristic_fixes:
        result["final_score"] = heuristic_score
        result["skipped"].append("refine: all dimensions >= threshold and no heuristic fixes")
        logger.info("Quality pipeline: skipping refinement (all dimensions pass)")
        return result

    # ---- Stage 3: Refinement (Claude for many issues, Gemini for few) ----
    critical_fixes = list(review.get("critical_fixes", []) or []) + heuristic_fixes

    if not critical_fixes:
        result["final_score"] = heuristic_score
        result["skipped"].append("refine: no critical fixes identified")
        return result

    # Determine which weeks need fixing (union of AI + heuristic)
    fix_week_nums = sorted({f.get("week", 0) for f in critical_fixes if f.get("week")} | set(heuristic_weeks))
    # Cap payload so the refiner's output fits in the token budget.
    # Last-month weeks and vague-verb weeks are the highest signal — prioritise those.
    MAX_WEEKS_PER_REFINE = 6
    if len(fix_week_nums) > MAX_WEEKS_PER_REFINE:
        logger.info("Quality pipeline: capping refine from %d to %d weeks (payload limit)",
                    len(fix_week_nums), MAX_WEEKS_PER_REFINE)
        fix_week_nums = fix_week_nums[-MAX_WEEKS_PER_REFINE:]  # keep latest weeks (last-month priority)
    if not fix_week_nums:
        result["final_score"] = heuristic_score
        result["skipped"].append("refine: no specific weeks identified")
        return result

    # Pick refinement model based on WHAT is failing, not just HOW MANY.
    # - Pattern-fixable failures (action verbs, measurability, vague verbs, resource
    #   counts) are mechanical — Gemini Flash handles them cheaply and reliably.
    # - Reasoning-heavy failures (Bloom's progression, prerequisites, industry
    #   alignment, difficulty calibration) need deeper thinking — Gemini Pro.
    # This routes ~50% of would-be-Pro calls down to Flash (saves ~$0.02/call).
    REASONING_DIMS = {
        "blooms_progression",
        "difficulty_calibration",
        "prerequisites_clarity",
        "industry_alignment",
        "freshness",
        "real_world_readiness",
    }
    PATTERN_DIMS = {
        "assessment_quality",   # action verbs, measurability
        "completeness",
        "project_density",
        "theory_practice_ratio",
        "deliverable_quality",
        "resource_diversity",
    }
    reasoning_failing = [d for d in failing_dims if d in REASONING_DIMS]
    pattern_failing = [d for d in failing_dims if d in PATTERN_DIMS]

    # Pro if: 2+ reasoning-heavy dims fail, OR severity total is very high (4+)
    severity = len(failing_dims) + (1 if heuristic_fixes else 0)
    use_pro = len(reasoning_failing) >= 2 or severity >= 4

    if use_pro:
        refine_model = "gemini-pro"
        logger.info(
            "Quality pipeline: Gemini Pro — reasoning=%s pattern=%s heuristic=%s",
            reasoning_failing, pattern_failing, bool(heuristic_fixes),
        )
    else:
        refine_model = "gemini"
        logger.info(
            "Quality pipeline: Gemini Flash — %d dim(s) failing, all pattern-fixable "
            "(reasoning=%s pattern=%s heuristic=%s)",
            severity, reasoning_failing, pattern_failing, bool(heuristic_fixes),
        )

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

    # Semantic guardrail — reject refines that either did nothing or hallucinated.
    # Only runs if the plan actually changed (avoids a wasted embedding call).
    if "refine" in result["stages_run"] and result["plan"] is not plan:
        try:
            sim = await _semantic_similarity(plan, result["plan"], db)
            if sim is not None:
                result["similarity"] = round(sim, 4)
                if sim > 0.98:
                    result["plan"] = plan
                    result["final_score"] = heuristic_score
                    result["skipped"].append(
                        f"validate: refinement ~identical (sim={sim:.3f}), reverted"
                    )
                    logger.warning(
                        "Quality pipeline: refine produced near-identical plan (sim=%.3f), reverting",
                        sim,
                    )
                elif sim < 0.50:
                    result["plan"] = plan
                    result["final_score"] = heuristic_score
                    result["skipped"].append(
                        f"validate: refinement too divergent (sim={sim:.3f}), possible hallucination, reverted"
                    )
                    logger.warning(
                        "Quality pipeline: refine diverged too much (sim=%.3f), possible hallucination, reverting",
                        sim,
                    )
        except Exception as e:
            # Embedding guardrail is best-effort; never block the pipeline on it.
            logger.warning("Quality pipeline: semantic guardrail failed: %s", e)

    if result["final_score"] < heuristic_score:
        # Refinement made it worse — revert
        result["plan"] = plan
        result["final_score"] = heuristic_score
        result["skipped"].append(f"validate: refinement regressed ({final_score} < {heuristic_score}), reverted")
        logger.warning("Quality pipeline: refinement regressed (%d < %d), reverting", final_score, heuristic_score)
    else:
        logger.info("Quality pipeline: improved %d → %d (+%d)", heuristic_score, result["final_score"], result["final_score"] - heuristic_score)

    return result


def _plan_fingerprint_text(plan: dict) -> str:
    """Flatten a plan into a short semantic fingerprint for embedding.

    Concat of all focus areas + checklist items, separated. Stable ordering.
    Truncated to the OpenAI embedding token-ish limit.
    """
    parts: list[str] = []
    for m in plan.get("months", []) or []:
        for w in m.get("weeks", []) or []:
            parts.extend([s for s in (w.get("focus") or []) if isinstance(s, str)])
            parts.extend([s for s in (w.get("checks") or []) if isinstance(s, str)])
    text = " | ".join(parts)
    # text-embedding-3-small allows 8191 tokens; ~4 chars per token means
    # ~32k chars is safe. Our fingerprint is usually well under that.
    return text[:28000]


# Soft circuit-breaker for the OpenAI embedding guardrail — if it fails 3 times
# in a row, skip for 5 minutes instead of hammering. Reset on first success.
_embedding_health = {"consecutive_failures": 0, "skip_until": 0.0}
_EMBEDDING_FAIL_THRESHOLD = 3
_EMBEDDING_COOLDOWN_SECS = 300


async def _semantic_similarity(plan_a: dict, plan_b: dict, db) -> float | None:
    """Cosine similarity between two plans' focus+checks fingerprints.

    Returns None if OpenAI embeddings are unavailable or in cooldown.
    """
    import time as _time
    if _time.time() < _embedding_health["skip_until"]:
        logger.debug("Semantic guardrail in cooldown, skipping")
        return None

    try:
        from app.ai.openai_embeddings import embed, cosine_similarity
    except Exception:
        return None

    text_a = _plan_fingerprint_text(plan_a)
    text_b = _plan_fingerprint_text(plan_b)
    if not text_a or not text_b:
        return None

    try:
        vecs = await embed([text_a, text_b], db=db, task="embedding",
                           subtask="quality_guardrail")
    except Exception as e:
        _embedding_health["consecutive_failures"] += 1
        if _embedding_health["consecutive_failures"] >= _EMBEDDING_FAIL_THRESHOLD:
            _embedding_health["skip_until"] = _time.time() + _EMBEDDING_COOLDOWN_SECS
            logger.warning(
                "Semantic guardrail: %d consecutive failures, cooling down for %ds",
                _embedding_health["consecutive_failures"], _EMBEDDING_COOLDOWN_SECS,
            )
        else:
            logger.info("Semantic guardrail failed (%s)", type(e).__name__)
        return None

    _embedding_health["consecutive_failures"] = 0
    _embedding_health["skip_until"] = 0.0

    if len(vecs) != 2:
        return None
    return cosine_similarity(vecs[0], vecs[1])


def _quick_heuristic_score(plan: dict) -> int:
    """Fast heuristic score without DB access — mirrors the full 15-dim scorer.

    Must correlate with the full scorer so the pipeline doesn't skip
    templates that actually need refinement.
    """
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
        score -= 10

    empty_weeks = sum(1 for m in tpl.months for w in m.weeks if not w.focus and not w.deliv)
    score -= min(15, empty_weeks * 5)

    no_resource_weeks = sum(1 for m in tpl.months for w in m.weeks if not w.resources)
    score -= min(10, no_resource_weeks * 3)

    # Checklist vagueness (assessment quality proxy)
    vague_patterns = [r"^understand\b", r"^learn\b", r"^know\b", r"^study\b",
                      r"^read about\b", r"^explore\b", r"^review\b", r"^familiarize\b"]
    all_checks = [c for m in tpl.months for w in m.weeks for c in w.checks]
    if all_checks:
        vague_count = sum(1 for c in all_checks if any(re.match(p, c.strip(), re.IGNORECASE) for p in vague_patterns))
        vague_pct = vague_count / len(all_checks) * 100
        score -= min(20, int(vague_pct * 0.4))

    # Bloom's progression proxy — check if last month uses high-level verbs
    create_verbs = [r"^build\b", r"^design\b", r"^create\b", r"^deploy\b",
                    r"^develop\b", r"^train\b", r"^fine-tune\b", r"^architect\b"]
    if tpl.months:
        last_checks = [c for w in tpl.months[-1].weeks for c in w.checks]
        if last_checks:
            create_count = sum(1 for c in last_checks
                             if any(re.match(v, c.strip(), re.IGNORECASE) for v in create_verbs))
            create_pct = create_count / len(last_checks)
            if create_pct < 0.3:
                score -= 10  # Last month should be mostly Create/Evaluate level

    # Difficulty calibration proxy — check for cognitive cliffs
    if len(tpl.months) >= 3:
        first_vague = sum(1 for c in (w.checks for w in tpl.months[0].weeks for c in [c for c in w]) if True) if False else 0
        # Simplified: just check last month has harder content than first
        first_text = " ".join(c for w in tpl.months[0].weeks for c in w.checks).lower()
        last_text = " ".join(c for w in tpl.months[-1].weeks for c in w.checks).lower()
        basic_words = sum(1 for w in ["define", "list", "identify", "describe"] if w in first_text)
        advanced_words = sum(1 for w in ["deploy", "design", "optimize", "evaluate", "build"] if w in last_text)
        if advanced_words < 2:
            score -= 5  # Last month should use advanced verbs

    # Measurability proxy — check for numbers in checklist items
    if all_checks:
        has_numbers = sum(1 for c in all_checks if re.search(r'\d+%|\d+\s*(accuracy|f1|auc)', c.lower()))
        if has_numbers < len(all_checks) * 0.1:
            score -= 5  # Less than 10% of items have measurable criteria

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
            score -= 5

    return max(0, min(100, score))


def _auto_fix(plan: dict) -> tuple[dict, dict]:
    """Deterministic pre-fix pass — mechanical cleanups that don't need an LLM.

    Handles issues that degrade quality scores but are safe to fix programmatically:
    - Dedup checklist items within a week (case-insensitive)
    - Dedup resources by URL within a week
    - Strip whitespace on all strings
    - Normalize missing/zero hours to default 16
    - Ensure week numbers are sequential 1..N

    Returns (fixed_plan, summary_of_fixes).
    """
    import copy
    p = copy.deepcopy(plan)
    fixes = {
        "checks_deduped": 0,
        "resources_deduped": 0,
        "hours_defaulted": 0,
        "weeks_renumbered": 0,
        "strings_trimmed": 0,
    }

    week_counter = 0
    for m in p.get("months", []) or []:
        for w in m.get("weeks", []) or []:
            week_counter += 1

            # Sequential week numbering
            if w.get("n") != week_counter:
                w["n"] = week_counter
                fixes["weeks_renumbered"] += 1

            # Normalize hours
            hrs = w.get("hours")
            if not isinstance(hrs, int) or hrs <= 0:
                w["hours"] = 16
                fixes["hours_defaulted"] += 1

            # Trim strings in focus/deliv/checks
            for field in ("focus", "deliv", "checks"):
                items = w.get(field) or []
                trimmed = []
                for it in items:
                    if isinstance(it, str):
                        s = it.strip()
                        if s != it:
                            fixes["strings_trimmed"] += 1
                        if s:
                            trimmed.append(s)
                w[field] = trimmed

            # Dedup checks (case-insensitive)
            checks = w.get("checks") or []
            seen_lower = set()
            deduped = []
            for c in checks:
                key = c.lower()
                if key in seen_lower:
                    fixes["checks_deduped"] += 1
                    continue
                seen_lower.add(key)
                deduped.append(c)
            w["checks"] = deduped

            # Dedup resources by URL
            resources = w.get("resources") or []
            seen_urls = set()
            deduped_res = []
            for r in resources:
                if not isinstance(r, dict):
                    continue
                url = (r.get("url") or "").strip().rstrip("/")
                if not url:
                    continue
                if url in seen_urls:
                    fixes["resources_deduped"] += 1
                    continue
                seen_urls.add(url)
                r["url"] = url
                # Trim name and hrs
                if isinstance(r.get("name"), str):
                    r["name"] = r["name"].strip()
                hrs_r = r.get("hrs")
                if not isinstance(hrs_r, int) or hrs_r <= 0:
                    r["hrs"] = 4
                deduped_res.append(r)
            w["resources"] = deduped_res

    # Only report counts that are non-zero
    non_zero = {k: v for k, v in fixes.items() if v}
    return p, non_zero


def _heuristic_diagnostics(plan: dict) -> tuple[list[dict], list[int]]:
    """Return actionable fixes for heuristic-detectable failures.

    The AI review is blind to very specific pattern rules (action verbs in
    last month, measurable numeric criteria, vague verbs). This surfaces them
    as concrete instructions for the refiner so free models can target them.

    Returns (critical_fixes, fix_week_nums).
    """
    from app.curriculum.loader import PlanTemplate
    import re
    try:
        tpl = PlanTemplate(**plan)
    except Exception:
        return [], []

    fixes: list[dict] = []
    weeks: set[int] = set()

    vague_patterns = [r"^understand\b", r"^learn\b", r"^know\b", r"^study\b",
                      r"^read about\b", r"^explore\b", r"^review\b", r"^familiarize\b"]
    create_verbs = [r"^build\b", r"^design\b", r"^create\b", r"^deploy\b",
                    r"^develop\b", r"^train\b", r"^fine-tune\b", r"^architect\b"]
    measurable_re = re.compile(r"\d+\s*%|\d+\s*(accuracy|f1|auc|precision|recall|mAP|BLEU|ROUGE|req/s|qps|ms)", re.I)

    # 1. Vague verbs — per week
    for m in tpl.months:
        for w in m.weeks:
            vague_in_week = [c for c in w.checks
                             if any(re.match(p, c.strip(), re.I) for p in vague_patterns)]
            if vague_in_week:
                weeks.add(w.n)
                fixes.append({
                    "week": w.n,
                    "issue": "vague_verbs",
                    "detail": f"Week {w.n} has {len(vague_in_week)} check(s) starting with vague verbs "
                              f"(Understand/Learn/Study/Explore). Rewrite each to start with a concrete "
                              f"action verb (Implement/Build/Train/Deploy/Benchmark/Write/Evaluate). "
                              f"Examples to fix: {vague_in_week[:2]}",
                    "priority": "high",
                })

    # 2. Last-month Create verbs
    if tpl.months:
        last_m = tpl.months[-1]
        last_checks = [c for w in last_m.weeks for c in w.checks]
        if last_checks:
            create_count = sum(1 for c in last_checks
                               if any(re.match(v, c.strip(), re.I) for v in create_verbs))
            create_pct = create_count / len(last_checks)
            if create_pct < 0.30:
                needed = max(0, int(len(last_checks) * 0.30) - create_count)
                last_week_nums = [w.n for w in last_m.weeks]
                for wn in last_week_nums:
                    weeks.add(wn)
                fixes.append({
                    "week": last_week_nums[0] if last_week_nums else 0,
                    "applies_to_weeks": last_week_nums,
                    "issue": "blooms_last_month_create_verbs",
                    "detail": f"Last month only {create_count}/{len(last_checks)} ({create_pct*100:.0f}%) "
                              f"of checklist items start with a Create-level verb "
                              f"(Build/Design/Deploy/Train/Fine-tune/Develop/Architect). "
                              f"Rewrite at least {needed} more checks across weeks "
                              f"{last_week_nums} to start with these verbs. "
                              f"The last month must demonstrate shipping (Bloom's Create level).",
                    "priority": "high",
                })

    # 3. Measurable criteria across all checks
    all_checks = [(m, w, c) for m in tpl.months for w in m.weeks for c in w.checks]
    if all_checks:
        measurable_count = sum(1 for _, _, c in all_checks if measurable_re.search(c))
        measurable_pct = measurable_count / len(all_checks)
        if measurable_pct < 0.10:
            needed = max(0, int(len(all_checks) * 0.10) - measurable_count)
            # Target a small sampling of weeks across the plan — keep the
            # refinement payload small enough for the model's output budget.
            sample_week_nums = sorted({w.n for m in tpl.months for w in m.weeks})[:3]
            for wn in sample_week_nums:
                weeks.add(wn)
            fixes.append({
                "week": sample_week_nums[0] if sample_week_nums else 0,
                "applies_to_weeks": sample_week_nums,
                "issue": "measurable_criteria",
                "detail": f"Only {measurable_count}/{len(all_checks)} ({measurable_pct*100:.1f}%) "
                          f"checklist items include measurable numeric criteria. "
                          f"Rewrite at least {needed} more checks across the plan to include a "
                          f"quantified threshold. Examples: 'Train a CNN achieving >85% accuracy "
                          f"on CIFAR-10', 'Build an API handling 100 req/s with p99 < 200ms', "
                          f"'Fine-tune with F1 > 0.7 on test set', 'Write tests with >80% coverage'.",
                "priority": "high",
            })

    return fixes, sorted(weeks)


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

    # Split into system instruction (reusable, cached) + user content (varies)
    # This is a major cost saver: Gemini caches system instructions across calls.
    # The review rubric (~800 tokens) is the same for every template — only the
    # curriculum JSON changes per call.
    system_part = prompt_template.split("CURRICULUM TO REVIEW:")[0]
    user_part = "CURRICULUM TO REVIEW:\n" + plan_json

    try:
        if model_name == "gemini":
            from app.ai.gemini import complete, GeminiError
            from app.ai.schemas import QUALITY_REVIEW_SCHEMA
            # Try structured output first (guarantees valid schema — no retry loops)
            try:
                result = await complete(
                    user_part, json_response=True,
                    task="quality_review",
                    system_instruction=system_part,
                    json_schema=QUALITY_REVIEW_SCHEMA,
                )
            except GeminiError as e:
                # If the schema is rejected (e.g. model doesn't support it), fall back
                logger.warning("Gemini schema review failed, retrying without schema: %s", e)
                result = await complete(
                    user_part, json_response=True,
                    task="quality_review",
                    system_instruction=system_part,
                )
        elif model_name == "groq":
            from app.ai.groq import complete
            result = await complete(prompt, json_response=True)
        else:
            from app.ai.provider import complete as ai_complete
            result, _ = await ai_complete(prompt, json_response=True,
                                          task="quality_review", db=db)

        if isinstance(result, str):
            result = json.loads(result)

        # Log usage with actual token count
        if db is not None:
            from app.ai.health import log_usage
            from app.config import get_settings as _s
            tokens = 0
            if model_name == "gemini":
                from app.ai.gemini import _last_usage as _gem_u
                tokens = int((_gem_u or {}).get("total_tokens", 0))
                prov, mdl = "gemini", _s().gemini_model
            elif model_name == "groq":
                prov, mdl = "groq", _s().groq_model
            else:
                prov, mdl = model_name, model_name
            if tokens == 0:
                tokens = max(1, len(prompt) // 4)
            await log_usage(db, prov, mdl, "quality_review", "ok",
                           tokens_estimated=tokens)

        return result
    except Exception as e:
        logger.error("AI review failed (%s): %s", model_name, e)
        if db is not None:
            from app.ai.health import log_usage
            from app.config import get_settings as _s
            if model_name == "gemini":
                prov, mdl = "gemini", _s().gemini_model
            elif model_name == "groq":
                prov, mdl = "groq", _s().groq_model
            else:
                prov, mdl = model_name, model_name
            await log_usage(db, prov, mdl, "quality_review", "error",
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

    # Split prompt: system rules (cacheable) vs user content (varies)
    system_rules = prompt_template.split("WEEKS THAT NEED FIXING:")[0]
    user_content = f"WEEKS THAT NEED FIXING:\n{json.dumps(failing_weeks, separators=(',', ':'))}\n\nISSUES TO FIX:\n{json.dumps(critical_fixes, separators=(',', ':'))}\n\nCONTEXT:\n- Topic: {plan.get('title', '')}\n- Level: {plan.get('level', '')}\n- Month: {month_context} of {plan.get('duration_months', 6)}"

    try:
        if model_name == "claude":
            # Retained for when Anthropic credits are available; no longer default.
            from app.ai.anthropic import complete
            fixed_weeks = await complete(
                user_content, json_response=True,
                system_prompt=system_rules,
                db=db, task="quality_refine",
                subtask=plan.get("title", "")[:50] or None,
            )
        elif model_name == "gemini-pro":
            from app.ai.gemini import complete, GeminiRateLimited, GeminiError
            from app.config import get_settings as _get_settings
            try:
                fixed_weeks = await complete(
                    user_content, json_response=True,
                    task="quality_refine",
                    system_instruction=system_rules,
                    model=_get_settings().gemini_pro_model,
                )
            except (GeminiRateLimited, GeminiError) as e:
                # Pro has ~2 RPM on free tier; on rate-limit or any transient
                # error, fall back to Flash. Flash has 15 RPM and handles most
                # patterns fine — losing some reasoning depth beats losing the
                # whole refine call.
                logger.warning(
                    "Gemini Pro refine failed (%s) — falling back to Flash",
                    type(e).__name__,
                )
                fixed_weeks = await complete(
                    user_content, json_response=True,
                    task="quality_refine",
                    system_instruction=system_rules,
                )
                # Adjust model_name so usage logging reflects what actually ran.
                model_name = "gemini"
        elif model_name == "gemini":
            from app.ai.gemini import complete
            fixed_weeks = await complete(
                user_content, json_response=True,
                task="quality_refine",
                system_instruction=system_rules,
            )
        else:
            from app.ai.provider import complete as ai_complete
            fixed_weeks, _ = await ai_complete(prompt, json_response=True,
                                               task="quality_refine", db=db)

        if isinstance(fixed_weeks, str):
            fixed_weeks = json.loads(fixed_weeks)

        # Log usage — map logical model_name to (provider, model_id) correctly.
        if db is not None:
            from app.ai.health import log_usage
            from app.config import get_settings as _s
            tokens = 0
            if model_name in ("gemini-pro", "gemini"):
                from app.ai.gemini import _last_usage as _gem_u
                tokens = int((_gem_u or {}).get("total_tokens", 0))
            if model_name == "gemini-pro":
                prov, mdl = "gemini", _s().gemini_pro_model
            elif model_name == "gemini":
                prov, mdl = "gemini", _s().gemini_model
            elif model_name == "claude":
                prov, mdl = "anthropic", _s().anthropic_model
            else:
                prov, mdl = model_name, model_name
            if tokens == 0:
                tokens = max(1, len(prompt) // 4)
            weeks_str = ",".join(str(n) for n in fix_week_nums)
            await log_usage(db, prov, mdl, "quality_refine", "ok",
                           subtask=f"weeks:{weeks_str}",
                           tokens_estimated=tokens)

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
            from app.config import get_settings as _s
            if model_name == "gemini-pro":
                prov, mdl = "gemini", _s().gemini_pro_model
            elif model_name == "gemini":
                prov, mdl = "gemini", _s().gemini_model
            elif model_name == "claude":
                prov, mdl = "anthropic", _s().anthropic_model
            else:
                prov, mdl = model_name, model_name
            await log_usage(db, prov, mdl, "quality_refine", "error",
                           error_message=str(e))
        return None


# ---- Refine existing templates on disk ----


async def refine_existing_templates(db: AsyncSession | None = None) -> dict:
    """Run the quality pipeline (review → refine → validate) on all saved templates.

    Improves templates that score below the publish threshold.
    Returns summary of what was improved.
    """
    from app.curriculum.loader import (
        list_templates, load_template, PUBLISH_THRESHOLD,
        update_quality_score,
    )
    from app.services.curriculum_generator import save_curriculum_draft

    keys = list_templates()
    results = []
    improved = 0
    skipped = 0
    failed = 0

    for key in keys:
        try:
            tpl = load_template(key)
            plan = json.loads(tpl.model_dump_json())

            # Score first
            original_score = _quick_heuristic_score(plan)
            if original_score >= PUBLISH_THRESHOLD:
                skipped += 1
                results.append({"key": key, "status": "skipped", "score": original_score,
                                "reason": f"Already {original_score} >= {PUBLISH_THRESHOLD}"})
                update_quality_score(key, original_score)
                continue

            # Run the full pipeline
            qr = await run_quality_pipeline(plan, "unknown", db)
            final_score = qr["final_score"]
            update_quality_score(key, final_score)

            if qr["plan"] != plan and final_score > original_score:
                # Save the improved version
                await save_curriculum_draft(qr["plan"])
                improved += 1
                results.append({
                    "key": key, "status": "improved",
                    "score_before": original_score, "score_after": final_score,
                    "stages": qr["stages_run"], "models": qr["models_used"],
                })
                logger.info("Refined %s: %d -> %d", key, original_score, final_score)
            else:
                skipped += 1
                skipped_reasons = qr.get("skipped", [])
                results.append({
                    "key": key, "status": "no_improvement",
                    "score": final_score, "skipped": skipped_reasons,
                })

        except Exception as e:
            failed += 1
            results.append({"key": key, "status": "error", "error": str(e)})
            logger.error("Failed to refine %s: %s", key, e)

    return {
        "status": "ok",
        "total": len(keys),
        "improved": improved,
        "skipped": skipped,
        "failed": failed,
        "results": results,
    }


# ---- Claude Batch API for bulk refinement (50% discount) ----

BATCH_THRESHOLD = 5  # Use batch API when 5+ refinements queued


async def create_batch_refinement(
    items: list[dict],
    db: AsyncSession | None = None,
) -> str:
    """Submit multiple refinement tasks as a Claude Batch for 50% discount.

    Args:
        items: List of dicts, each with:
            - plan: dict (full curriculum)
            - critical_fixes: list[dict] (from review)
            - fix_week_nums: list[int]
            - template_key: str (for matching results)

    Returns:
        batch_id: str — poll with poll_batch_refinement()
    """
    from app.ai.anthropic import create_batch

    prompt_template = REFINE_PROMPT_PATH.read_text(encoding="utf-8")
    system_rules = prompt_template.split("WEEKS THAT NEED FIXING:")[0]

    requests = []
    for item in items:
        plan = item["plan"]
        critical_fixes = item["critical_fixes"]
        fix_week_nums = item["fix_week_nums"]

        failing_weeks = []
        for m in plan.get("months", []):
            for w in m.get("weeks", []):
                if w.get("n") in fix_week_nums:
                    failing_weeks.append(w)

        user_content = (
            f"WEEKS THAT NEED FIXING:\n{json.dumps(failing_weeks, separators=(',', ':'))}\n\n"
            f"ISSUES TO FIX:\n{json.dumps(critical_fixes, separators=(',', ':'))}\n\n"
            f"CONTEXT:\n- Topic: {plan.get('title', '')}\n"
            f"- Level: {plan.get('level', '')}\n"
            f"- Duration: {plan.get('duration_months', 6)} months"
        )

        requests.append({
            "custom_id": item["template_key"],
            "prompt": user_content,
            "system_prompt": system_rules,
            "max_tokens": 4096,
        })

    batch_id = await create_batch(requests)

    if db is not None:
        from app.ai.health import log_usage
        await log_usage(db, "claude", "claude-batch", "quality_refine_batch", "ok",
                       subtask=f"{len(items)} items")

    logger.info("Created batch refinement %s with %d items", batch_id, len(items))
    return batch_id


async def apply_batch_results(
    batch_id: str,
    items: list[dict],
    db: AsyncSession | None = None,
) -> dict:
    """Fetch and apply batch refinement results.

    Args:
        batch_id: The batch ID from create_batch_refinement()
        items: Same list passed to create_batch_refinement() (for matching)

    Returns:
        {"applied": int, "failed": int, "results": [...]}
    """
    from app.ai.anthropic import get_batch_results
    from app.services.curriculum_generator import save_curriculum_draft

    results = await get_batch_results(batch_id)
    items_by_key = {item["template_key"]: item for item in items}

    applied = 0
    failed = 0
    details = []

    for result in results:
        key = result["custom_id"]
        item = items_by_key.get(key)
        if not item:
            continue

        if result["error"]:
            failed += 1
            details.append({"key": key, "status": "error", "error": result["error"]})
            continue

        fixed_weeks = result["result"]
        if not isinstance(fixed_weeks, list):
            failed += 1
            details.append({"key": key, "status": "error", "error": "Non-list response"})
            continue

        # Merge fixed weeks back into the plan
        plan = item["plan"]
        patched = json.loads(json.dumps(plan))
        fixed_by_num = {w["n"]: w for w in fixed_weeks if isinstance(w, dict) and "n" in w}

        for m in patched.get("months", []):
            for i, w in enumerate(m.get("weeks", [])):
                if w.get("n") in fixed_by_num:
                    m["weeks"][i] = fixed_by_num[w["n"]]

        # Validate improvement
        original_score = _quick_heuristic_score(plan)
        new_score = _quick_heuristic_score(patched)

        if new_score >= original_score:
            await save_curriculum_draft(patched)
            applied += 1
            details.append({
                "key": key, "status": "applied",
                "score_change": f"{original_score} → {new_score}",
            })
        else:
            failed += 1
            details.append({
                "key": key, "status": "reverted",
                "reason": f"Score regressed: {original_score} → {new_score}",
            })

    logger.info("Batch %s applied: %d succeeded, %d failed", batch_id, applied, failed)
    return {"applied": applied, "failed": failed, "results": details}
