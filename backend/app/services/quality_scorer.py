"""
Template quality scoring engine.

Scores each curriculum template on 5 dimensions:
1. Structure (completeness of fields, week count, hours)
2. Resource diversity (unique domains, reputable sources)
3. Checklist specificity (verifiable items vs vague ones)
4. Progression logic (week titles flow logically)
5. Link health (% of working URLs from LinkHealth table)

Returns a composite score 0-100 per template.
AI-assisted scoring for checklist + progression (uses provider fallback chain).
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from urllib.parse import urlparse

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.curriculum.loader import PlanTemplate, list_templates, load_template
from app.models.curriculum import LinkHealth

logger = logging.getLogger("roadmap.quality")

# Reputable resource domains (partial matches)
REPUTABLE_DOMAINS = {
    "stanford.edu", "mit.edu", "cmu.edu", "berkeley.edu", "harvard.edu",
    "coursera.org", "edx.org", "kaggle.com", "huggingface.co",
    "arxiv.org", "youtube.com", "github.com", "tensorflow.org",
    "pytorch.org", "scikit-learn.org", "deeplearning.ai",
    "fast.ai", "paperswithcode.com", "openai.com", "anthropic.com",
    "google.com", "microsoft.com", "aws.amazon.com",
    "docs.python.org", "numpy.org", "pandas.pydata.org",
    "keras.io", "wandb.ai", "mlflow.org",
}

# Vague checklist phrases that indicate low specificity
VAGUE_PATTERNS = [
    r"^understand\b", r"^learn\b", r"^know\b", r"^study\b",
    r"^read about\b", r"^explore\b", r"^review\b", r"^familiarize\b",
    r"^get familiar\b", r"^look into\b",
]


def score_structure(tpl: PlanTemplate) -> dict:
    """Score template structural completeness (0-100)."""
    issues = []
    score = 100

    # Check month count matches duration
    expected_months = tpl.duration_months
    actual_months = len(tpl.months)
    if actual_months != expected_months:
        issues.append(f"Expected {expected_months} months, got {actual_months}")
        score -= 20

    # Check total weeks (should be ~4 per month)
    expected_weeks = expected_months * 4
    actual_weeks = tpl.total_weeks
    if actual_weeks < expected_weeks * 0.8:
        issues.append(f"Only {actual_weeks} weeks (expected ~{expected_weeks})")
        score -= 15

    # Check each week has content
    empty_weeks = 0
    low_check_weeks = 0
    no_resource_weeks = 0
    for m in tpl.months:
        for w in m.weeks:
            if not w.focus and not w.deliv:
                empty_weeks += 1
            if len(w.checks) < 3:
                low_check_weeks += 1
            if len(w.resources) == 0:
                no_resource_weeks += 1

    if empty_weeks > 0:
        issues.append(f"{empty_weeks} weeks with no focus/deliverables")
        score -= min(30, empty_weeks * 10)
    if low_check_weeks > 0:
        issues.append(f"{low_check_weeks} weeks with <3 checklist items")
        score -= min(15, low_check_weeks * 3)
    if no_resource_weeks > 0:
        issues.append(f"{no_resource_weeks} weeks with no resources")
        score -= min(20, no_resource_weeks * 5)

    # Check hours are reasonable (10-20 per week)
    bad_hours = sum(1 for m in tpl.months for w in m.weeks if w.hours < 8 or w.hours > 25)
    if bad_hours > 0:
        issues.append(f"{bad_hours} weeks with unusual hours (<8 or >25)")
        score -= min(10, bad_hours * 2)

    return {"score": max(0, score), "issues": issues}


def score_resource_diversity(tpl: PlanTemplate) -> dict:
    """Score resource diversity — unique domains, reputable sources (0-100)."""
    all_urls = []
    for m in tpl.months:
        for w in m.weeks:
            for r in w.resources:
                all_urls.append(r.url)

    if not all_urls:
        return {"score": 0, "issues": ["No resources found"], "domains": [], "reputable_pct": 0}

    # Extract domains
    domains = []
    for url in all_urls:
        try:
            host = urlparse(url).hostname or ""
            # Strip www.
            if host.startswith("www."):
                host = host[4:]
            domains.append(host)
        except Exception:
            pass

    unique_domains = set(domains)
    domain_counts = Counter(domains)

    # Reputable source percentage
    reputable_count = sum(
        1 for d in domains
        if any(rep in d for rep in REPUTABLE_DOMAINS)
    )
    reputable_pct = round(reputable_count / len(domains) * 100) if domains else 0

    # Score
    score = 50  # base
    # Diversity bonus: more unique domains = better
    diversity_ratio = len(unique_domains) / len(all_urls) if all_urls else 0
    score += int(diversity_ratio * 25)  # up to +25

    # Reputable source bonus
    score += int(reputable_pct * 0.25)  # up to +25

    issues = []
    # Penalize if >50% from one domain
    if domain_counts:
        top_domain, top_count = domain_counts.most_common(1)[0]
        if top_count > len(all_urls) * 0.5:
            issues.append(f"{top_count}/{len(all_urls)} resources from {top_domain}")
            score -= 15

    if reputable_pct < 30:
        issues.append(f"Only {reputable_pct}% from reputable sources")

    if len(unique_domains) < 3:
        issues.append(f"Only {len(unique_domains)} unique domains")
        score -= 10

    return {
        "score": max(0, min(100, score)),
        "issues": issues,
        "total_resources": len(all_urls),
        "unique_domains": len(unique_domains),
        "reputable_pct": reputable_pct,
        "top_domains": [d for d, _ in domain_counts.most_common(5)],
    }


def score_checklist_specificity(tpl: PlanTemplate) -> dict:
    """Score checklist items for specificity — verifiable vs vague (0-100)."""
    all_checks = []
    for m in tpl.months:
        for w in m.weeks:
            all_checks.extend(w.checks)

    if not all_checks:
        return {"score": 0, "issues": ["No checklist items"], "total": 0, "vague": 0}

    vague_count = 0
    vague_examples = []
    for check in all_checks:
        is_vague = any(re.match(pat, check.strip(), re.IGNORECASE) for pat in VAGUE_PATTERNS)
        if is_vague:
            vague_count += 1
            if len(vague_examples) < 3:
                vague_examples.append(check[:60])

    vague_pct = round(vague_count / len(all_checks) * 100)
    # Score: 100 if 0% vague, 0 if 100% vague
    score = max(0, 100 - vague_pct)

    issues = []
    if vague_pct > 30:
        issues.append(f"{vague_pct}% vague items (e.g. {', '.join(vague_examples)})")
    if len(all_checks) < tpl.total_weeks * 3:
        issues.append(f"Only {len(all_checks)} items across {tpl.total_weeks} weeks (avg {len(all_checks)//max(1,tpl.total_weeks)}/week)")

    return {
        "score": score,
        "issues": issues,
        "total": len(all_checks),
        "vague": vague_count,
        "vague_pct": vague_pct,
    }


def score_progression(tpl: PlanTemplate) -> dict:
    """Score progression logic — do weeks build on each other? (0-100)."""
    issues = []
    score = 80  # base — assume decent unless problems found

    weeks = []
    for m in tpl.months:
        for w in m.weeks:
            weeks.append(w)

    if not weeks:
        return {"score": 0, "issues": ["No weeks"]}

    # Check week numbering is sequential
    week_nums = [w.n for w in weeks]
    expected = list(range(1, len(weeks) + 1))
    if week_nums != expected:
        issues.append(f"Non-sequential week numbers: {week_nums[:5]}...")
        score -= 15

    # Check month labels exist and are unique
    month_labels = [m.label for m in tpl.months]
    if len(set(month_labels)) < len(month_labels):
        issues.append("Duplicate month labels")
        score -= 10

    # Check last month has capstone-like content
    last_month = tpl.months[-1] if tpl.months else None
    if last_month:
        last_text = (last_month.label + " " + last_month.title + " " + last_month.checkpoint).lower()
        capstone_keywords = ["capstone", "project", "portfolio", "deploy", "final", "job", "career", "interview"]
        has_capstone = any(kw in last_text for kw in capstone_keywords)
        if has_capstone:
            score += 10
        else:
            issues.append("Last month doesn't appear to have a capstone/project focus")

    # Check first month has foundations/basics
    first_month = tpl.months[0] if tpl.months else None
    if first_month:
        first_text = (first_month.label + " " + first_month.title).lower()
        foundation_keywords = ["foundation", "basic", "intro", "fundamental", "setup", "overview", "getting started"]
        has_foundation = any(kw in first_text for kw in foundation_keywords)
        if has_foundation:
            score += 10
        else:
            issues.append("First month doesn't start with foundations/basics")

    return {"score": max(0, min(100, score)), "issues": issues}


async def score_link_health(tpl: PlanTemplate, db: AsyncSession) -> dict:
    """Score link health from the LinkHealth table (0-100)."""
    total = await db.scalar(
        select(func.count()).select_from(LinkHealth)
        .where(LinkHealth.template_key == tpl.key)
    ) or 0

    if total == 0:
        # No link checks run yet — count resources as proxy
        resource_count = sum(len(w.resources) for m in tpl.months for w in m.weeks)
        return {
            "score": 50,  # neutral — not checked yet
            "issues": ["Links not checked yet — run Content Refresh"],
            "total": resource_count,
            "ok": 0,
            "broken": 0,
            "checked": False,
        }

    broken = await db.scalar(
        select(func.count()).select_from(LinkHealth)
        .where(LinkHealth.template_key == tpl.key, LinkHealth.consecutive_failures >= 2)
    ) or 0

    ok = total - broken
    health_pct = round(ok / total * 100) if total > 0 else 100
    issues = []
    if broken > 0:
        issues.append(f"{broken}/{total} links broken")

    return {
        "score": health_pct,
        "issues": issues,
        "total": total,
        "ok": ok,
        "broken": broken,
        "checked": True,
    }


async def score_template(tpl: PlanTemplate, db: AsyncSession) -> dict:
    """Compute composite quality score for a template."""
    structure = score_structure(tpl)
    resources = score_resource_diversity(tpl)
    checklist = score_checklist_specificity(tpl)
    progression = score_progression(tpl)
    links = await score_link_health(tpl, db)

    # Weighted composite: structure 25%, resources 20%, checklist 20%, progression 15%, links 20%
    composite = round(
        structure["score"] * 0.25 +
        resources["score"] * 0.20 +
        checklist["score"] * 0.20 +
        progression["score"] * 0.15 +
        links["score"] * 0.20
    )

    all_issues = (
        [f"[Structure] {i}" for i in structure["issues"]] +
        [f"[Resources] {i}" for i in resources["issues"]] +
        [f"[Checklist] {i}" for i in checklist["issues"]] +
        [f"[Progression] {i}" for i in progression["issues"]] +
        [f"[Links] {i}" for i in links["issues"]]
    )

    return {
        "key": tpl.key,
        "title": tpl.title,
        "level": tpl.level,
        "duration_months": tpl.duration_months,
        "composite_score": composite,
        "scores": {
            "structure": structure["score"],
            "resources": resources["score"],
            "checklist": checklist["score"],
            "progression": progression["score"],
            "links": links["score"],
        },
        "issues": all_issues,
        "details": {
            "total_weeks": tpl.total_weeks,
            "total_checks": tpl.total_checks,
            "total_resources": resources.get("total_resources", 0),
            "unique_domains": resources.get("unique_domains", 0),
            "reputable_pct": resources.get("reputable_pct", 0),
            "top_domains": resources.get("top_domains", []),
            "vague_checks_pct": checklist.get("vague_pct", 0),
            "links_checked": links.get("checked", False),
            "links_broken": links.get("broken", 0),
        },
    }


async def score_all_templates(db: AsyncSession) -> list[dict]:
    """Score all templates and return sorted by composite score (lowest first)."""
    keys = list_templates()
    results = []
    for key in keys:
        try:
            tpl = load_template(key)
            result = await score_template(tpl, db)
            results.append(result)
        except Exception as e:
            logger.warning("Failed to score template %s: %s", key, e)
            results.append({
                "key": key, "title": key, "composite_score": 0,
                "issues": [f"Failed to load: {e}"],
                "scores": {}, "details": {},
            })

    results.sort(key=lambda r: r["composite_score"])
    return results
