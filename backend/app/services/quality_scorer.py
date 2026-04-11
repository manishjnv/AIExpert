"""
Template quality scoring engine.

Scores each curriculum template on 15 dimensions:

Original 5:
1. Structure (completeness of fields, week count, hours)
2. Resource diversity (unique domains, reputable sources)
3. Checklist specificity (verifiable items vs vague ones)
4. Progression logic (week titles flow logically)
5. Link health (% of working URLs from LinkHealth table)

New 10 (regex-based, no AI cost):
6. Bloom's taxonomy progression (cognitive level advancement)
7. Theory-to-practice ratio (resource type classification)
8. Project density (deliverable analysis)
9. Assessment quality (tiered rubric classification)
10. Completeness (essential topic coverage)
11. Difficulty calibration (smooth progression detection)
12. Industry alignment (modern tool/framework coverage)
13. Freshness (deprecated tech detection)
14. Prerequisites clarity (dependency chain validation)
15. Real-world readiness (portfolio/production signals)

Returns a composite score 0-100 per template.
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

# Bloom's taxonomy verb classification (ordered by cognitive level)
BLOOMS_LEVELS = {
    "remember": [
        r"^list\b", r"^define\b", r"^name\b", r"^identify\b", r"^recall\b",
        r"^recognize\b", r"^describe\b", r"^state\b", r"^memorize\b",
    ],
    "understand": [
        r"^explain\b", r"^summarize\b", r"^interpret\b", r"^classify\b",
        r"^compare\b", r"^discuss\b", r"^distinguish\b", r"^understand\b",
        r"^learn\b", r"^study\b", r"^read\b", r"^explore\b",
    ],
    "apply": [
        r"^implement\b", r"^use\b", r"^execute\b", r"^apply\b", r"^solve\b",
        r"^demonstrate\b", r"^compute\b", r"^run\b", r"^install\b", r"^set up\b",
        r"^configure\b", r"^write\b", r"^code\b", r"^practice\b",
    ],
    "analyze": [
        r"^analyze\b", r"^debug\b", r"^compare\b", r"^test\b", r"^profile\b",
        r"^benchmark\b", r"^diagnose\b", r"^inspect\b", r"^examine\b",
        r"^differentiate\b", r"^experiment\b", r"^investigate\b",
    ],
    "evaluate": [
        r"^evaluate\b", r"^assess\b", r"^critique\b", r"^justify\b",
        r"^measure\b", r"^validate\b", r"^select\b", r"^choose\b",
        r"^optimize\b", r"^tune\b", r"^score\b",
    ],
    "create": [
        r"^build\b", r"^design\b", r"^create\b", r"^develop\b", r"^deploy\b",
        r"^architect\b", r"^produce\b", r"^construct\b", r"^compose\b",
        r"^invent\b", r"^train\b", r"^fine-tune\b", r"^ship\b", r"^launch\b",
    ],
}
BLOOMS_LEVEL_ORDER = ["remember", "understand", "apply", "analyze", "evaluate", "create"]

# Resource type classification for theory-practice ratio
PRACTICE_URL_PATTERNS = [
    r"github\.com", r"kaggle\.com", r"colab\.research\.google",
    r"jupyter", r"notebook", r"replit\.com", r"codepen\.io",
    r"leetcode", r"hackerrank", r"exercism",
]
PRACTICE_NAME_PATTERNS = [
    r"lab\b", r"exercise\b", r"project\b", r"hands-on", r"tutorial",
    r"notebook\b", r"workshop\b", r"practice\b", r"coding\b", r"implementation",
    r"build\b", r"walkthrough", r"practical",
]
THEORY_NAME_PATTERNS = [
    r"lecture\b", r"reading\b", r"paper\b", r"textbook\b", r"theory\b",
    r"concept\b", r"overview\b", r"introduction\b", r"survey\b",
]

# Essential AI topics by level
ESSENTIAL_TOPICS = {
    "beginner": [
        "python", "math", "linear algebra", "statistics", "machine learning",
        "neural network", "deep learning", "data", "ethics",
    ],
    "intermediate": [
        "machine learning", "deep learning", "nlp", "computer vision",
        "deployment", "mlops", "testing", "data pipeline", "ethics",
        "transformer", "fine-tun",
    ],
    "advanced": [
        "transformer", "reinforcement learning", "distributed",
        "optimization", "research", "production", "scaling",
        "architecture", "deployment", "ethics",
    ],
}

# Modern industry tools/frameworks
INDUSTRY_TOOLS = [
    "pytorch", "tensorflow", "hugging ?face", "langchain", "llama",
    "docker", "kubernetes", "mlflow", "wandb", "weights.*biases",
    "fastapi", "flask", "streamlit", "gradio", "aws", "gcp", "azure",
    "git", "ci/cd", "dvc", "airflow", "spark", "ray",
    "onnx", "triton", "vllm", "openai", "anthropic",
]

# Deprecated/outdated technology markers
DEPRECATED_MARKERS = [
    r"tensorflow\s*1\b", r"tf\.session", r"keras\.layers\.",
    r"python\s*2\b", r"caffe\b", r"theano\b",
    r"gpt-?2\b", r"bert-?base\b",
    r"sklearn\.cross_validation\b",
    r"pandas\.panel\b", r"matplotlib\.pylab\b",
]

# Project/deliverable quality markers
PROJECT_KEYWORDS = [
    r"build\b", r"create\b", r"deploy\b", r"implement\b", r"develop\b",
    r"train\b.*model", r"fine-tune\b", r"ship\b", r"launch\b",
    r"end-to-end", r"full.*pipeline", r"production",
    r"portfolio", r"real-world", r"dataset",
]

# Portfolio/production-readiness markers
READINESS_MARKERS = [
    r"portfolio", r"production", r"deploy", r"ci/cd", r"monitor",
    r"resume", r"interview", r"case study", r"design decision",
    r"trade-?off", r"scalab", r"real.?world", r"industry",
    r"client", r"stakeholder", r"a/b test", r"business",
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


def _classify_bloom_level(text: str) -> str:
    """Classify a checklist item by Bloom's taxonomy level."""
    text_lower = text.strip().lower()
    for level in reversed(BLOOMS_LEVEL_ORDER):  # check highest first
        for pat in BLOOMS_LEVELS[level]:
            if re.match(pat, text_lower):
                return level
    # Default: if starts with action verb not in our list, assume "apply"
    if re.match(r"^[a-z]", text_lower):
        return "apply"
    return "understand"


def score_blooms_progression(tpl: PlanTemplate) -> dict:
    """Score Bloom's taxonomy progression — cognitive levels should increase over time (0-100)."""
    issues = []
    months_levels = []

    for m in tpl.months:
        month_levels = []
        for w in m.weeks:
            for check in w.checks:
                level = _classify_bloom_level(check)
                month_levels.append(BLOOMS_LEVEL_ORDER.index(level))
        if month_levels:
            months_levels.append(sum(month_levels) / len(month_levels))
        else:
            months_levels.append(0)

    if len(months_levels) < 2:
        return {"score": 50, "issues": ["Not enough months to assess progression"]}

    score = 70  # base

    # Check that average level increases across months
    increases = 0
    decreases = 0
    for i in range(1, len(months_levels)):
        if months_levels[i] > months_levels[i - 1]:
            increases += 1
        elif months_levels[i] < months_levels[i - 1] - 0.3:  # small tolerance
            decreases += 1

    if increases >= len(months_levels) - 2:
        score += 20  # strong progression
    elif decreases > len(months_levels) // 2:
        score -= 25
        issues.append("Cognitive level decreases in later months")

    # First month should be mostly remember/understand/apply (level 0-2)
    if months_levels[0] > 3:
        issues.append("First month uses high-level verbs before foundations are set")
        score -= 10

    # Last month should be mostly analyze/evaluate/create (level 3-5)
    if months_levels[-1] < 2.5:
        issues.append("Final month still uses low-level verbs (should be Create/Evaluate)")
        score -= 15

    # Check for stuck-at-understand problem
    all_levels = []
    for m in tpl.months:
        for w in m.weeks:
            for check in w.checks:
                all_levels.append(_classify_bloom_level(check))
    level_counts = Counter(all_levels)
    understand_pct = (level_counts.get("understand", 0) + level_counts.get("remember", 0)) / max(1, len(all_levels))
    if understand_pct > 0.5:
        issues.append(f"{int(understand_pct*100)}% of items are Remember/Understand level")
        score -= 10

    return {"score": max(0, min(100, score)), "issues": issues}


def score_theory_practice_ratio(tpl: PlanTemplate) -> dict:
    """Score theory-to-practice ratio — target ~30% theory, 70% practice (0-100)."""
    practice_count = 0
    theory_count = 0
    total = 0

    for m in tpl.months:
        for w in m.weeks:
            for r in w.resources:
                total += 1
                name_lower = r.name.lower()
                url_lower = r.url.lower()

                is_practice = (
                    any(re.search(p, url_lower) for p in PRACTICE_URL_PATTERNS) or
                    any(re.search(p, name_lower) for p in PRACTICE_NAME_PATTERNS)
                )
                is_theory = any(re.search(p, name_lower) for p in THEORY_NAME_PATTERNS)

                if is_practice:
                    practice_count += 1
                elif is_theory:
                    theory_count += 1
                else:
                    # Neutral — split 50/50
                    practice_count += 0.5
                    theory_count += 0.5

    if total == 0:
        return {"score": 0, "issues": ["No resources to analyze"]}

    practice_pct = round(practice_count / total * 100)
    theory_pct = round(theory_count / total * 100)

    # Ideal: 60-80% practice
    score = 70
    if 60 <= practice_pct <= 80:
        score = 95
    elif 50 <= practice_pct < 60:
        score = 80
    elif practice_pct < 40:
        score = max(30, 70 - (40 - practice_pct))

    issues = []
    if practice_pct < 50:
        issues.append(f"Only {practice_pct}% practice resources (target: 60-80%)")
    if theory_pct > 50:
        issues.append(f"{theory_pct}% theory-heavy (lectures/readings)")

    return {
        "score": max(0, min(100, score)),
        "issues": issues,
        "practice_pct": practice_pct,
        "theory_pct": theory_pct,
    }


def score_project_density(tpl: PlanTemplate) -> dict:
    """Score project density — what % of weeks have buildable deliverables (0-100)."""
    weeks_with_projects = 0
    total_weeks = 0

    for m in tpl.months:
        for w in m.weeks:
            total_weeks += 1
            # Check deliverables for project keywords
            all_text = " ".join(w.deliv + w.focus).lower()
            has_project = any(re.search(p, all_text) for p in PROJECT_KEYWORDS)
            if has_project:
                weeks_with_projects += 1

    if total_weeks == 0:
        return {"score": 0, "issues": ["No weeks"]}

    density_pct = round(weeks_with_projects / total_weeks * 100)

    # Target: 60%+ weeks should have a project/deliverable
    if density_pct >= 60:
        score = 90 + min(10, (density_pct - 60) // 4)
    elif density_pct >= 40:
        score = 70 + (density_pct - 40)
    else:
        score = max(20, density_pct * 1.5)

    issues = []
    if density_pct < 50:
        issues.append(f"Only {density_pct}% of weeks have project deliverables (target: 60%+)")
    if density_pct < 30:
        issues.append("Most weeks lack hands-on building — curriculum is too passive")

    return {
        "score": int(max(0, min(100, score))),
        "issues": issues,
        "project_weeks": weeks_with_projects,
        "total_weeks": total_weeks,
        "density_pct": density_pct,
    }


def score_assessment_quality(tpl: PlanTemplate) -> dict:
    """Score assessment quality — measurable/quantifiable checklist items (0-100)."""
    measurable = 0
    vague = 0
    total = 0

    # Measurable patterns: contain numbers, specific outcomes, concrete artifacts
    measurable_patterns = [
        r"\d+%", r"\d+\s*(accuracy|precision|recall|f1|auc)",
        r"achieve\b", r"reach\b.*\d", r"score\b.*\d",
        r"working\b", r"functional\b", r"passing\b.*test",
        r"deploy", r"submit", r"publish", r"push.*git",
        r"complete\b.*project", r"build\b.*\b(app|model|pipeline|api|dashboard)",
        r"train\b.*model", r"accuracy", r"benchmark",
    ]

    for m in tpl.months:
        for w in m.weeks:
            for check in w.checks:
                total += 1
                check_lower = check.lower()
                is_measurable = any(re.search(p, check_lower) for p in measurable_patterns)
                is_vague = any(re.match(p, check_lower.strip()) for p in VAGUE_PATTERNS)

                if is_measurable:
                    measurable += 1
                elif is_vague:
                    vague += 1

    if total == 0:
        return {"score": 0, "issues": ["No checklist items"]}

    measurable_pct = round(measurable / total * 100)
    vague_pct = round(vague / total * 100)

    score = 50 + int(measurable_pct * 0.4) - int(vague_pct * 0.3)

    issues = []
    if measurable_pct < 30:
        issues.append(f"Only {measurable_pct}% items have measurable outcomes")
    if vague_pct > 30:
        issues.append(f"{vague_pct}% items are vague ('Learn about...', 'Understand...')")

    return {
        "score": max(0, min(100, score)),
        "issues": issues,
        "measurable_pct": measurable_pct,
        "vague_pct": vague_pct,
    }


def score_completeness(tpl: PlanTemplate) -> dict:
    """Score topic completeness — does curriculum cover essential AI topics for its level? (0-100)."""
    level = tpl.level.lower()
    required_topics = ESSENTIAL_TOPICS.get(level, ESSENTIAL_TOPICS["beginner"])

    # Gather all text from the template
    all_text = ""
    for m in tpl.months:
        all_text += f" {m.label} {m.title} {m.tagline} {m.checkpoint}"
        for w in m.weeks:
            all_text += f" {w.t} " + " ".join(w.focus) + " " + " ".join(w.deliv)
            all_text += " " + " ".join(w.checks)
            all_text += " " + " ".join(r.name for r in w.resources)
    all_text = all_text.lower()

    covered = []
    missing = []
    for topic in required_topics:
        if re.search(topic, all_text):
            covered.append(topic)
        else:
            missing.append(topic)

    coverage_pct = round(len(covered) / len(required_topics) * 100) if required_topics else 100
    score = coverage_pct

    issues = []
    if missing:
        issues.append(f"Missing essential topics: {', '.join(missing[:5])}")
    if coverage_pct < 70:
        issues.append(f"Only {coverage_pct}% of essential {level}-level topics covered")

    return {
        "score": score,
        "issues": issues,
        "covered": covered,
        "missing": missing,
        "coverage_pct": coverage_pct,
    }


def score_difficulty_calibration(tpl: PlanTemplate) -> dict:
    """Score difficulty calibration — smooth progression without cognitive cliffs (0-100)."""
    issues = []
    score = 80

    # Classify each week's difficulty by its bloom level + topic complexity
    week_difficulties = []
    for m in tpl.months:
        for w in m.weeks:
            levels = [BLOOMS_LEVEL_ORDER.index(_classify_bloom_level(c)) for c in w.checks] if w.checks else [2]
            avg_level = sum(levels) / len(levels)
            # Factor in hours (more hours = harder)
            difficulty = avg_level + (w.hours - 12) * 0.1
            week_difficulties.append(difficulty)

    if len(week_difficulties) < 3:
        return {"score": 70, "issues": ["Too few weeks to assess calibration"]}

    # Detect jumps: a jump > 2 levels between consecutive weeks is a cliff
    cliffs = []
    for i in range(1, len(week_difficulties)):
        jump = week_difficulties[i] - week_difficulties[i - 1]
        if jump > 1.8:
            cliffs.append(i + 1)  # 1-indexed week number

    if cliffs:
        score -= min(30, len(cliffs) * 10)
        issues.append(f"Difficulty cliffs at weeks {cliffs[:4]} (sudden jump in complexity)")

    # Detect plateaus: 4+ consecutive weeks at same level
    plateau_count = 0
    streak = 1
    for i in range(1, len(week_difficulties)):
        if abs(week_difficulties[i] - week_difficulties[i - 1]) < 0.3:
            streak += 1
            if streak >= 4:
                plateau_count += 1
        else:
            streak = 1

    if plateau_count > 0:
        score -= 10
        issues.append(f"Difficulty plateaus detected ({plateau_count} stretches of 4+ flat weeks)")

    # Overall should trend upward
    if len(week_difficulties) >= 4:
        first_quarter = sum(week_difficulties[:len(week_difficulties)//4]) / (len(week_difficulties)//4)
        last_quarter = sum(week_difficulties[-(len(week_difficulties)//4):]) / (len(week_difficulties)//4)
        if last_quarter <= first_quarter:
            score -= 15
            issues.append("Difficulty doesn't increase from start to end")
        elif last_quarter - first_quarter > 0.5:
            score += 10

    return {"score": max(0, min(100, score)), "issues": issues}


def score_industry_alignment(tpl: PlanTemplate) -> dict:
    """Score industry alignment — covers modern tools and frameworks that jobs require (0-100)."""
    all_text = ""
    for m in tpl.months:
        all_text += f" {m.label} {m.title} {m.checkpoint}"
        for w in m.weeks:
            all_text += f" {w.t} " + " ".join(w.focus) + " " + " ".join(w.deliv)
            all_text += " " + " ".join(r.name for r in w.resources)
            all_text += " " + " ".join(r.url for r in w.resources)
    all_text = all_text.lower()

    found_tools = []
    for tool in INDUSTRY_TOOLS:
        if re.search(tool, all_text):
            found_tools.append(tool.replace("\\s*", "").replace("\\b", "").replace("?", ""))

    # Score based on coverage (expect at least 8 for intermediate+)
    level = tpl.level.lower()
    if level == "beginner":
        expected = 5
    elif level == "advanced":
        expected = 12
    else:
        expected = 8

    coverage = min(1.0, len(found_tools) / expected)
    score = int(60 + coverage * 40)

    issues = []
    if len(found_tools) < expected // 2:
        issues.append(f"Only {len(found_tools)} industry tools/frameworks mentioned (expected ~{expected})")
    if not any(re.search(r"docker|kubernetes|mlflow|ci/cd", all_text)):
        if level != "beginner":
            issues.append("No MLOps/deployment tooling (Docker, K8s, MLflow, CI/CD)")

    return {
        "score": max(0, min(100, score)),
        "issues": issues,
        "tools_found": found_tools[:15],
        "tool_count": len(found_tools),
    }


def score_freshness(tpl: PlanTemplate) -> dict:
    """Score freshness — detect deprecated or outdated technology references (0-100)."""
    all_text = ""
    for m in tpl.months:
        for w in m.weeks:
            all_text += f" {w.t} " + " ".join(w.focus) + " " + " ".join(w.checks)
            all_text += " " + " ".join(r.name for r in w.resources)
            all_text += " " + " ".join(r.url for r in w.resources)
    all_text = all_text.lower()

    deprecated_found = []
    for marker in DEPRECATED_MARKERS:
        matches = re.findall(marker, all_text)
        if matches:
            deprecated_found.extend(matches[:2])

    score = 100 - min(50, len(deprecated_found) * 15)

    issues = []
    if deprecated_found:
        issues.append(f"Deprecated references: {', '.join(deprecated_found[:5])}")

    # Bonus for mentioning current tech (2024-2026 era)
    current_markers = [r"llm", r"gpt-?4", r"claude", r"llama", r"mistral", r"rag\b",
                       r"vector.*db", r"langchain", r"agent", r"fine-?tun"]
    current_found = sum(1 for m in current_markers if re.search(m, all_text))
    if current_found >= 3:
        score = min(100, score + 10)
    elif current_found == 0 and tpl.level.lower() != "beginner":
        issues.append("No mention of current AI trends (LLMs, RAG, agents, fine-tuning)")
        score -= 10

    return {
        "score": max(0, min(100, score)),
        "issues": issues,
        "deprecated_refs": deprecated_found[:5],
        "current_tech_count": current_found,
    }


def score_prerequisites_clarity(tpl: PlanTemplate) -> dict:
    """Score prerequisites clarity — do later weeks build on earlier ones logically? (0-100)."""
    issues = []
    score = 75

    # Build a map of when topics are first introduced
    topic_first_seen = {}
    for m in tpl.months:
        for w in m.weeks:
            week_text = (w.t + " " + " ".join(w.focus)).lower()
            for topic in ["python", "math", "linear algebra", "calculus", "statistics",
                          "probability", "numpy", "pandas", "neural network",
                          "deep learning", "cnn", "rnn", "transformer", "nlp",
                          "reinforcement learning", "deployment", "docker"]:
                if topic in week_text and topic not in topic_first_seen:
                    topic_first_seen[topic] = w.n

    # Check common prerequisite chains
    prereq_chains = [
        ("python", "numpy"),
        ("python", "pandas"),
        ("linear algebra", "neural network"),
        ("neural network", "deep learning"),
        ("neural network", "cnn"),
        ("neural network", "rnn"),
        ("deep learning", "transformer"),
        ("python", "deployment"),
    ]

    violations = 0
    for prereq, dependent in prereq_chains:
        prereq_week = topic_first_seen.get(prereq, 0)
        dependent_week = topic_first_seen.get(dependent, 0)
        if prereq_week > 0 and dependent_week > 0 and dependent_week < prereq_week:
            violations += 1
            if violations <= 3:
                issues.append(f"'{dependent}' (week {dependent_week}) appears before '{prereq}' (week {prereq_week})")

    if violations == 0:
        score += 15
    else:
        score -= min(30, violations * 10)

    # Check if the template specifies prerequisites in early weeks
    first_weeks_text = ""
    for m in tpl.months[:1]:
        for w in m.weeks:
            first_weeks_text += " ".join(w.focus).lower() + " " + w.t.lower()

    if any(kw in first_weeks_text for kw in ["setup", "install", "prerequisite", "foundation", "basics"]):
        score += 10

    return {"score": max(0, min(100, score)), "issues": issues, "violations": violations}


def score_real_world_readiness(tpl: PlanTemplate) -> dict:
    """Score real-world readiness — portfolio projects, production patterns, career prep (0-100)."""
    all_text = ""
    for m in tpl.months:
        all_text += f" {m.label} {m.title} {m.tagline} {m.checkpoint}"
        for w in m.weeks:
            all_text += f" {w.t} " + " ".join(w.focus) + " " + " ".join(w.deliv)
            all_text += " " + " ".join(w.checks)
    all_text = all_text.lower()

    readiness_hits = 0
    for marker in READINESS_MARKERS:
        if re.search(marker, all_text):
            readiness_hits += 1

    # Score: need at least 5 readiness markers for high score
    score = min(100, 40 + readiness_hits * 8)

    issues = []
    if readiness_hits < 3:
        issues.append("Few real-world readiness markers (portfolio, deployment, production)")
    if not re.search(r"portfolio|resume|interview", all_text):
        issues.append("No career-prep content (portfolio building, resume, interview prep)")
    if not re.search(r"deploy|production|ship|launch", all_text):
        issues.append("No deployment/production content")

    return {
        "score": max(0, min(100, score)),
        "issues": issues,
        "readiness_markers": readiness_hits,
    }


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
    """Compute composite quality score for a template across 15 dimensions."""
    # Original 5 dimensions
    structure = score_structure(tpl)
    resources = score_resource_diversity(tpl)
    checklist = score_checklist_specificity(tpl)
    progression = score_progression(tpl)
    links = await score_link_health(tpl, db)

    # New 10 dimensions (all regex-based, zero AI cost)
    blooms = score_blooms_progression(tpl)
    theory_practice = score_theory_practice_ratio(tpl)
    project_density = score_project_density(tpl)
    assessment = score_assessment_quality(tpl)
    completeness = score_completeness(tpl)
    difficulty = score_difficulty_calibration(tpl)
    industry = score_industry_alignment(tpl)
    freshness = score_freshness(tpl)
    prerequisites = score_prerequisites_clarity(tpl)
    readiness = score_real_world_readiness(tpl)

    # Weighted composite (15 dimensions, weights sum to 1.0)
    # Structure/links are infrastructure; content quality dimensions get more weight
    composite = round(
        structure["score"] * 0.08 +
        resources["score"] * 0.06 +
        checklist["score"] * 0.05 +
        progression["score"] * 0.05 +
        links["score"] * 0.06 +
        blooms["score"] * 0.10 +
        theory_practice["score"] * 0.10 +
        project_density["score"] * 0.10 +
        assessment["score"] * 0.08 +
        completeness["score"] * 0.10 +
        difficulty["score"] * 0.07 +
        industry["score"] * 0.07 +
        freshness["score"] * 0.05 +
        prerequisites["score"] * 0.06 +
        readiness["score"] * 0.07
    )

    all_issues = (
        [f"[Structure] {i}" for i in structure["issues"]] +
        [f"[Resources] {i}" for i in resources["issues"]] +
        [f"[Checklist] {i}" for i in checklist["issues"]] +
        [f"[Progression] {i}" for i in progression["issues"]] +
        [f"[Links] {i}" for i in links["issues"]] +
        [f"[Bloom's] {i}" for i in blooms["issues"]] +
        [f"[Theory/Practice] {i}" for i in theory_practice["issues"]] +
        [f"[Projects] {i}" for i in project_density["issues"]] +
        [f"[Assessment] {i}" for i in assessment["issues"]] +
        [f"[Completeness] {i}" for i in completeness["issues"]] +
        [f"[Difficulty] {i}" for i in difficulty["issues"]] +
        [f"[Industry] {i}" for i in industry["issues"]] +
        [f"[Freshness] {i}" for i in freshness["issues"]] +
        [f"[Prerequisites] {i}" for i in prerequisites["issues"]] +
        [f"[Readiness] {i}" for i in readiness["issues"]]
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
            "blooms_progression": blooms["score"],
            "theory_practice": theory_practice["score"],
            "project_density": project_density["score"],
            "assessment_quality": assessment["score"],
            "completeness": completeness["score"],
            "difficulty_calibration": difficulty["score"],
            "industry_alignment": industry["score"],
            "freshness": freshness["score"],
            "prerequisites_clarity": prerequisites["score"],
            "real_world_readiness": readiness["score"],
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
            "practice_pct": theory_practice.get("practice_pct", 0),
            "project_density_pct": project_density.get("density_pct", 0),
            "measurable_pct": assessment.get("measurable_pct", 0),
            "completeness_pct": completeness.get("coverage_pct", 0),
            "missing_topics": completeness.get("missing", []),
            "industry_tools": industry.get("tools_found", []),
            "deprecated_refs": freshness.get("deprecated_refs", []),
            "prereq_violations": prerequisites.get("violations", 0),
            "readiness_markers": readiness.get("readiness_markers", 0),
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
