"""Jobs ingest orchestrator.

Pipeline: fetch → normalize → hash → dedup → enrich → stage as draft.
Always stages as `status='draft'`. Only admin actions can flip to published.
See docs/JOBS.md §4.

Enrichment (Step 3) is called via `enrich_job()` — if it fails, the row is
still staged with a minimal payload and flagged via admin_notes for review.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import re
import secrets
from datetime import date, datetime, timedelta
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

import app.db as _db
from app.models import Job, JobCompany, JobSource
from app.services.jobs_sources import RawJob
from app.services.jobs_sources.ashby import ASHBY_BOARDS, fetch_all as ash_fetch_all
from app.services.jobs_sources.greenhouse import GREENHOUSE_BOARDS, fetch_all as gh_fetch_all
from app.services.jobs_sources.lever import LEVER_BOARDS, fetch_all as lv_fetch_all

logger = logging.getLogger("roadmap.jobs.ingest")

# Default lifespan before a job auto-expires, per docs/JOBS.md §7.6.
VALID_FOR_DAYS = 45

# Max new jobs enriched per source per run. Anthropic + Databricks alone list
# 1200+ roles combined; enriching all in one run (~7s/Gemini call) would take
# hours. Capping means heavy boards take a few days to fully catch up, which
# is fine — newest-first ordering surfaces recent posts fast.
PER_SOURCE_NEW_CAP = 30

# Bounded parallelism for enrichment. Gemini Flash free tier allows ~15 RPM;
# 4 concurrent calls average 3-4s/call wall time and stay well under limits.
ENRICH_CONCURRENCY = 4

# Consecutive daily runs a published job may be absent from its source feed
# before auto-expiring. 2 = one grace day absorbs transient ATS API blips.
# See docs/JOBS.md §7.6 and docs/TASKS.md Phase 13.
MISSING_STREAK_THRESHOLD = 2

# ---------------------------------------------------------------- pre-filter

# Titles matching these patterns are almost certainly non-AI roles and should
# skip enrichment entirely. They still get staged as draft with admin_notes so
# admin can override manually. Patterns are case-insensitive substring matches
# against the raw title. Keep this list tight — false positives waste admin time;
# false negatives only waste a cheap Flash call.
_NON_AI_TITLE_PATTERNS: list[str] = [
    # Business / operations
    "sales manager", "sales director", "sales representative", "account executive",
    "account manager", "business development representative", "bdr ",
    "customer success", "customer support", "customer service",
    "office manager", "office coordinator", "executive assistant",
    "administrative assistant", "receptionist", "facilities",
    # Sales engineering / pre-sales (jargon-heavy but role is sales)
    "sales engineer", "pre-sales", "presales", "solutions engineer",
    "field engineer", "customer solutions architect", "technical account manager",
    # Partnerships / business development
    "business development manager", "business development director",
    "head of business development", "strategic partnerships",
    "partnerships manager", "partnerships lead", "alliance manager",
    # Program / project management (coordination roles)
    "program manager", "technical program manager", " tpm ",
    "chief of staff", "project manager", "portfolio manager",
    # Legal / finance / HR
    "legal counsel", "general counsel", "paralegal", "attorney",
    "legal manager", "manager, legal", "manager - legal", "manager-legal",
    "legal associate", "legal analyst", "legal specialist", "legal operations",
    "legal affairs", "corporate counsel", "contracts manager", "contract manager",
    "compliance manager", "compliance officer", "compliance analyst",
    "chief legal officer", "head of legal", "vp, legal", "vp legal",
    "tax manager", "tax analyst", "accountant", "accounting",
    "financial analyst", "fp&a", "controller", "accounts payable",
    "accounts receivable", "payroll", "compensation analyst",
    "recruiter", "recruiting coordinator", "talent acquisition",
    "human resources", " hr manager", " hr business partner",
    "benefits administration", "benefits manager", "benefits analyst",
    "merchant kyc", "kyc analyst", "kyc specialist", "merchant onboarding",
    # Finance specializations / IR / RevOps
    "investor relations", "revenue operations", "revops",
    "treasury manager", "audit manager",
    # Marketing (non-technical)
    "content writer", "copywriter", "social media manager",
    "event manager", "event coordinator", "public relations",
    "communications manager", "brand manager",
    # Marketing specializations (often AI-jargon-heavy, role is marketing)
    "product marketing", "growth manager", "demand generation",
    "demand gen", "field marketing", "lifecycle marketing",
    # Policy / governance / ethics (AI labs hire these)
    "policy analyst", "policy manager", "ai ethicist", "governance manager",
    "public policy", "policy advisor",
    # Community / DevRel (non-code) / technical writing
    "community manager", "community lead",
    "technical writer", "ux writer", "documentation lead",
    # Training / education
    "instructor", "curriculum designer", "teaching assistant",
    "learning and development", " l&d ",
    # Design (AI-product designers — design is the job, not AI)
    "ux designer", "ui designer", "product designer", "visual designer",
    "ux researcher", "graphic designer",
    # Cybersecurity (not AI safety)
    "application security", "appsec", "infosec", "soc analyst",
    "security operations engineer",
    # IT / workplace
    "it support", "help desk", "helpdesk", "workplace engineer",
    "systems administrator", "it administrator",
    # Creative / video / podcast
    "video producer", "creative director", "podcast producer",
    "motion designer", "video editor",
    # Clinical / medical (domain SMEs for AI annotation)
    "clinical reviewer", "medical writer", "clinical specialist",
    "medical reviewer",
    # Localization (translation/linguistic ops, not computational linguistics)
    "localization manager", "localization lead", "translation manager",
    # Physical security
    "physical security", "security officer", "building operations",
    # Vendor / sourcing
    "vendor manager", "sourcing manager", "strategic sourcing",
    # Supply chain / logistics
    "supply chain", "logistics", "warehouse", "procurement",
    "inventory manager",
]

# Tier-2 boards: non-AI-native companies where most listings are non-AI roles.
# These get lightweight enrichment (no nice_to_have, no modules, no desc rewrite)
# to save ~40% tokens per call. Full enrichment runs on-demand when admin publishes.
# AI-native companies (Anthropic, Scale, xAI, Cohere, etc.) stay Tier-1 = full enrichment.
TIER2_SOURCES: set[str] = {
    "greenhouse:phonepe", "greenhouse:groww",
    "lever:cred", "lever:mindtickle",
    "ashby:notion", "ashby:replit",
}


def is_non_ai_title(title: str) -> bool:
    """Return True if the title matches a known non-AI pattern.

    Used to skip enrichment (saves ~$0.0004/job) on roles that would be
    rejected by admin anyway. The row is still staged so admin can override.
    """
    t = title.lower()
    return any(pat in t for pat in _NON_AI_TITLE_PATTERNS)


# JD-body cluster of terms that strongly indicate non-AI domains (law, HR,
# procurement, finance). A job hitting >=2 of these AND low AI-intensity
# score (Wave 2) is almost certainly a false positive like PhonePe
# "Manager, Legal" where "LLB / LLM from a recognized university" tricked
# the enricher into tagging it as "Applied ML". See RCA-026.
_NON_AI_JD_SIGNALS: tuple[str, ...] = (
    # Legal
    "llb", "ll.b", "ll.m", "pqe", "post-qualification experience",
    "bar council", "indian contract act", "indian penal code",
    "law firm", "law school", "master of laws", "advocate",
    "procurement contracts", "commercial contracts", "contract drafting",
    "contract negotiation", "legal counsel", "legal advisory",
    "redlining", "msa ", "nda ", "sla ",
    # HR / benefits / KYC / finance
    "payroll processing", "benefits administration", "kyc verification",
    "kyc analyst", "merchant onboarding", "onboarding specialist",
    "bookkeeping", "gst filing", "tds ",
    # Wave 3 #11 — sales / GTM cluster
    "sales quota", "quota-carrying", "pipeline generation", "close deals",
    "sales cycle", "win rate", "commission plan", "annual recurring revenue",
    "monthly recurring revenue", "sales target",
    # Marketing / growth cluster (skip generic "campaign" — too overloaded)
    "brand voice", "content calendar", "paid media", "demand generation",
    "marketing funnel", "campaign performance", "go-to-market strategy",
    "marketing qualified lead", "lifecycle marketing",
    # Recruiting cluster
    "candidate pipeline", "sourcing candidates", "linkedin recruiter",
    "offer letter", "interview panel", "applicant tracking",
    "headhunt", "talent pipeline",
    # Design / UX cluster (Figma is the dead-giveaway tool)
    "figma", "wireframes", "design system", "usability testing",
    "user research", "design critique", "interaction design",
    # Finance / accounting cluster
    "gaap", "ifrs", "month-end close", "journal entries", "balance sheet",
    "audit committee", "treasury management",
    # IT / customer-support cluster
    "ticket queue", "zendesk", "intercom", "jira service",
    "sla response", "escalation path", "service desk",
    # Creative / video cluster
    "adobe premiere", "final cut pro", "storyboard", "video editing",
    "podcast production", "brand identity", "motion graphics",
    # Policy / governance cluster
    "white paper", "regulatory sandbox", "policy brief",
    "stakeholder engagement", "government affairs", "regulatory filing",
)


# ---------------------------------------------------------------- Wave 2: AI-intensity scoring
#
# Replaces the old binary _AI_JD_SIGNALS substring check. The substring
# approach mis-scored "ppo" against "shopping", "vit" against "activity",
# "rag" against "fragment" — inflating the AI signal of non-AI JDs.
#
# New model: weighted three-tier score with word-boundary regex.
# - STRONG (3 pts): AI-specific terms with no non-AI meaning ("pytorch",
#   "fine-tuning", "rlhf", "machine learning", "neural networks").
# - MEDIUM (2 pts): Ambiguous alone; need cluster context ("llm" — Master
#   of Laws degree, "rag" — fragment, "agent" — hiring agent).
# - WEAK   (1 pt):  Generic AI mentions in marketing/boilerplate copy
#   ("AI-powered", "AI-driven", "using AI"). Won't carry a JD alone.
#
# Each pattern matches AT MOST ONCE per JD (per-JD dedup) — boilerplate
# repeating "AI" 10 times can't inflate the score.
#
# Threshold: score >= 5 to qualify as AI. One STRONG + one MEDIUM = 5.
# Two STRONG = 6. One STRONG alone = 3 (insufficient — needs corroboration).

_AI_STRONG_PATTERNS: tuple[str, ...] = (
    # Core ML techniques (multi-word, no ambiguity)
    r"\bmachine learning\b",
    r"\bdeep learning\b",
    r"\bgenerative ai\b",
    r"\bgenai\b",
    r"\bgen[- ]ai\b",
    r"\bneural networks?\b",
    r"\breinforcement learning\b",
    r"\bnatural language processing\b",
    r"\bcomputer vision\b",
    r"\btransfer learning\b",
    r"\bfew[- ]shot learning\b",
    r"\bzero[- ]shot learning\b",
    r"\bin[- ]context learning\b",
    # Foundation-model vocabulary
    r"\blarge language models?\b",
    r"\blanguage models?\b",
    r"\bfoundation models?\b",
    r"\btransformer (?:model|architecture|layer)s?\b",
    r"\battention mechanism\b",
    r"\bmixture of experts\b",
    r"\bcontext window\b",
    r"\btokeniz(?:er|ation)\b",
    # Training & optimization
    r"\bfine[- ]tuning\b",
    r"\bpretraining\b", r"\bpre[- ]training\b",
    r"\bpost[- ]training\b",
    r"\binstruction tuning\b",
    r"\brlhf\b",
    r"\bdpo\b",
    r"\bsupervised fine[- ]tun\w*",
    r"\bknowledge distillation\b",
    r"\bmodel quantization\b",
    r"\bmodel training\b",
    r"\btraining loop\b",
    r"\bgradient descent\b",
    r"\bbackpropagation\b",
    r"\bloss function\b",
    r"\bcross[- ]entropy\b",
    # Inference & serving
    r"\bmodel inference\b",
    r"\binference latency\b",
    r"\binference throughput\b",
    r"\binference engine\b",
    r"\binference server\b",
    r"\bbatch(?:ed)? inference\b",
    r"\bonline inference\b",
    r"\bmodel serving\b",
    r"\bmodel deployment\b",
    r"\bmodel registry\b",
    r"\bmodel weights\b",
    # RAG / agents / prompt
    r"\bretrieval[- ]augmented\b",
    r"\bvector databases?\b",
    r"\bvector stores?\b",
    r"\bembedding models?\b",
    r"\bprompt engineering\b",
    r"\bchain of thought\b",
    r"\bfunction calling\b",
    r"\bmulti[- ]agent\b",
    r"\bagentic\b",
    r"\bconstitutional ai\b",
    # MLOps & platform
    r"\bmlops\b",
    r"\bml ops\b",
    r"\bml platforms?\b",
    r"\bdistributed training\b",
    r"\bmulti[- ]gpu\b",
    r"\btensor parallel\b",
    r"\bpipeline parallel\b",
    r"\bdata parallel\b",
    r"\bdeepspeed\b",
    r"\bmegatron\b",
    r"\bfsdp\b",
    r"\bnccl\b",
    r"\bcuda kernel\b",
    r"\bkubeflow\b",
    r"\bmlflow\b",
    r"\bfeature store\b",
    r"\bsagemaker\b",
    r"\bvertex ai\b",
    # Frameworks (brand names — high precision)
    r"\bpytorch\b",
    r"\btensorflow\b",
    r"\bjax\b",
    r"\bhugging[- ]?face\b",
    r"\blangchain\b",
    r"\bllamaindex\b",
    # Models / brand APIs (qualified to avoid bare-name false matches)
    r"\bopenai (?:api|models?|platform)\b",
    r"\banthropic api\b",
    r"\bclaude api\b",
    r"\bgemini api\b",
    r"\bgpt-[345]\b",
    r"\bclaude (?:sonnet|opus|haiku)\b",
    r"\bllama[- ]?\d+\b",
    r"\bmistral (?:large|medium|small|7b|ai)\b",
    r"\bstable diffusion\b",
    r"\bdall-?e\b",
    # Research signals
    r"\bresearch papers?\b",
    r"\barxiv\b",
    r"\bpeer[- ]reviewed\b",
    r"\bneurips\b", r"\bicml\b", r"\biclr\b",
    r"\bemnlp\b", r"\bcvpr\b", r"\baaai\b",
    r"\bempirical research\b",
    r"\bablation stud(?:y|ies)\b",
    # Safety (qualified — bare "alignment"/"safety" too generic)
    r"\bai safety\b",
    r"\bai alignment\b",
    r"\bmechanistic interpretability\b",
    r"\binterpretability\b",
    # Inference hardware (AI-specific contexts only)
    r"\binference cluster\b",
    r"\bgpu cluster\b",
    r"\btpu pod\b",
)

_AI_MEDIUM_PATTERNS: tuple[str, ...] = (
    r"\bllm\b",          # Master of Laws ambiguity
    r"\brag\b",          # Cleaning rag, rag time, fragment
    r"\bagents?\b",      # Hiring agent, escrow agent
    r"\bgpus?\b",        # Generic infra mention
    r"\bnlp\b",          # National pension liability and similar
    r"\bml engineer\b",
    r"\bdata scientist\b",
    r"\bai engineer\b",
    r"\bresearch scientist\b",
    r"\bapplied ml\b",
    r"\btraining data\b",
    r"\bmodel evaluation\b",
)

_AI_WEAK_PATTERNS: tuple[str, ...] = (
    r"\bai[- ](?:powered|driven|first|native|enabled)\b",
    r"\bml[- ](?:driven|powered|enabled)\b",
    r"\busing (?:ai|ml)\b",
    r"\b(?:ai|ml)[- ]based\b",
    r"\b(?:ai|ml) (?:products?|tools?|platforms?)\b",
)

# Compile regex patterns once at module load (perf — JD scoring is hot path).
_AI_STRONG_RE = tuple(re.compile(p, re.IGNORECASE) for p in _AI_STRONG_PATTERNS)
_AI_MEDIUM_RE = tuple(re.compile(p, re.IGNORECASE) for p in _AI_MEDIUM_PATTERNS)
_AI_WEAK_RE = tuple(re.compile(p, re.IGNORECASE) for p in _AI_WEAK_PATTERNS)

AI_INTENSITY_THRESHOLD = 5  # min score to qualify a JD as AI-relevant

# Boilerplate sections (company mission, "About <Company>", "Why join us")
# get stripped before scoring. Critical for AI labs where every JD opens
# with "Anthropic's mission is to build safe AI…" — a mission paragraph
# that contains AI terms shouldn't elevate a non-AI role's intensity.
_BOILERPLATE_PATTERNS = (
    re.compile(
        r"\babout (?:anthropic|openai|databricks|cerebras|deepmind|cohere"
        r"|hugging\s?face|the company|us|our (?:company|team|firm|mission))\b"
        r".*?(?=\b(?:about the role|the role|in this role|role overview"
        r"|responsibilities|key responsibilities|what you[' ]ll do"
        r"|what you do|requirements|qualifications|must[- ]haves?)\b|\Z)",
        re.I | re.S,
    ),
    re.compile(
        r"\bour mission\b.*?(?=\b(?:about the role|the role|in this role"
        r"|role overview|responsibilities|key responsibilities"
        r"|what you[' ]ll do|requirements|qualifications)\b|\Z)",
        re.I | re.S,
    ),
    re.compile(
        r"\bwhy (?:join|work at|anthropic|openai|us)\b"
        r".*?(?=\b(?:about the role|the role|in this role|role overview"
        r"|responsibilities|key responsibilities|what you[' ]ll do"
        r"|requirements|qualifications)\b|\Z)",
        re.I | re.S,
    ),
)


def _strip_company_boilerplate(jd_text: str) -> str:
    """Remove company-mission and "about us" sections before AI scoring.

    AI lab JDs uniformly open with "About Anthropic — Anthropic's mission
    is to build safe AI…" — that paragraph contains AI terms regardless
    of the role being hired for. Stripping prevents non-AI roles at AI
    labs from inheriting their employer's AI vocabulary.
    """
    out = jd_text
    for pat in _BOILERPLATE_PATTERNS:
        out = pat.sub(" ", out)
    return out


# Wave 3 #12 — requirement-phrase neutralizer.
# "Experience with ML", "Familiarity with LLMs", "Knowledge of PyTorch" —
# these describe what the candidate must KNOW, not what they DO. A
# recruiter sourcing ML candidates needs ML literacy as a requirement,
# but the actual work is talent acquisition. Strip these spans before
# scoring AI-intensity so requirement chatter doesn't elevate non-AI roles.
#
# Surgical strip: only the immediate clause (up to next sentence end /
# semicolon / newline / 80 chars). A real ML Engineer JD has many AI
# signals OUTSIDE requirement phrases (responsibilities, "you'll build...",
# project descriptions) and stays well above threshold.
_REQUIREMENT_PHRASE = re.compile(
    r"\b(?:experience|familiarity|comfortable(?:\s+working)?|exposure"
    r"|knowledge|background|understanding|proficien(?:cy|t))\s+"
    r"(?:with|in|of|using)\s+[^.;\n]{0,80}",
    re.IGNORECASE,
)


def _neutralize_requirement_phrases(text: str) -> str:
    """Strip 'experience with X' style requirement phrases before AI scoring."""
    return _REQUIREMENT_PHRASE.sub(" ", text)


def compute_ai_intensity(jd_text: str) -> int:
    """Three-tier weighted AI-intensity score for a JD body.

    Returns sum(strong x3 + medium x2 + weak x1). Each pattern counts at
    most once per JD (dedup) — repeated boilerplate cannot inflate.

    Score >= AI_INTENSITY_THRESHOLD (5) qualifies a JD as AI-relevant.
    Below threshold ⇒ JD is not concrete-AI work even if it mentions AI.
    """
    text = _strip_company_boilerplate(jd_text)
    text = _neutralize_requirement_phrases(text)  # Wave 3 #12
    score = 0
    for r in _AI_STRONG_RE:
        if r.search(text):
            score += 3
    for r in _AI_MEDIUM_RE:
        if r.search(text):
            score += 2
    for r in _AI_WEAK_RE:
        if r.search(text):
            score += 1
    return score


# Wave 3 #13 — bare-verb title gate.
# Titles starting with Manager / Director / Lead / Head / VP / Chief that
# contain NO AI anchor word are likely coordination/business roles. Many
# of these slip past the substring-based _NON_AI_TITLE_PATTERNS list (e.g.,
# "Manager, Sales Development" doesn't contain "sales manager"). Combined
# with low JD intensity, they get auto-skipped as non-AI.
_BARE_VERB_TITLE_RE = re.compile(
    r"^(?:senior\s+|principal\s+|staff\s+|sr\.?\s+|jr\.?\s+|associate\s+"
    r"|lead\s+|head\s+|deputy\s+|interim\s+)?"
    r"(?:manager|director|lead|head\s+of|vp|vice\s+president|chief)\b",
    re.IGNORECASE,
)
_AI_TITLE_ANCHOR_RE = re.compile(
    r"\b(?:ai|ml|machine\s+learning|deep\s+learning|llm|nlp|cv"
    r"|computer\s+vision|data|research|applied|model|robotics|safety"
    r"|alignment|inference|mlops|generative|gen[- ]?ai|engineering)\b",
    re.IGNORECASE,
)


def is_bare_verb_title(title: str) -> bool:
    """Return True for titles like 'Manager, Sales Development' that start
    with a leadership verb but contain no AI/ML/data/research anchor word.

    Used in conjunction with low JD intensity to auto-skip coordination
    roles that fall through the explicit title pattern list.
    """
    t = (title or "").strip()
    if not _BARE_VERB_TITLE_RE.match(t):
        return False
    return not _AI_TITLE_ANCHOR_RE.search(t)


def has_non_ai_jd_signals(jd_html: str) -> bool:
    """Return True if the JD body looks like a non-AI role.

    Wave 2 evolution of the original two-gate rule:
      (a) >=2 distinct legal/HR/finance cluster hits, AND
      (b) AI-intensity score < AI_INTENSITY_THRESHOLD (5).

    The intensity score replaces the old "any AI substring" guard. The
    old check failed open on substring noise — "shopping" matched "ppo",
    "fragment" matched "rag", "Albert" matched "bert". The new gate uses
    word-boundary regex with weighted scoring so a JD must show genuine
    AI work content (one strong + one medium, or two strong terms) to
    overcome a non-AI cluster.
    """
    text = jd_html.lower()
    non_ai_hits = sum(1 for sig in _NON_AI_JD_SIGNALS if sig in text)
    if non_ai_hits < 2:
        return False
    if compute_ai_intensity(jd_html) >= AI_INTENSITY_THRESHOLD:
        return False
    return True


# ---------------------------------------------------------------- helpers

def compute_hash(raw: RawJob) -> str:
    """Stable hash for change detection + cross-source dedup."""
    parts = [
        raw["title_raw"].strip().lower(),
        raw["company_slug"].strip().lower(),
        raw["location_raw"].strip().lower(),
        raw["jd_html"].strip(),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def slugify(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.lower()).strip("-")
    return re.sub(r"-+", "-", s)[:80]


def build_slug(title: str, company_slug: str) -> str:
    short = secrets.token_hex(2)  # 4-char stable-ish suffix; uniqueness enforced below
    return f"{slugify(title)}-at-{slugify(company_slug)}-{short}"


# ---------------------------------------------------------------- source registry

async def ensure_source_rows() -> None:
    """Upsert JobSource rows for every hardcoded source. Idempotent.

    Sources in TIER2_SOURCES (non-AI-native companies) get tier=2, bulk_approve=0,
    and their JobCompany.verified=0. Bulk-publish and the green T1 chip are both
    gated on verified/tier=1, so this keeps mixed-role boards (PhonePe, Groww, …)
    out of the fast path — they require per-row review regardless of the
    lite-enrichment path already taken in _stage_one.
    """
    registry: list[tuple[str, str, list[tuple[str, str]]]] = [
        ("greenhouse", "Greenhouse", GREENHOUSE_BOARDS),
        ("lever", "Lever", LEVER_BOARDS),
        ("ashby", "Ashby", ASHBY_BOARDS),
    ]

    async def _op() -> None:
        async with _db.async_session_factory() as db:
            for kind, label_suffix, boards in registry:
                for board_slug, company_name in boards:
                    key = f"{kind}:{board_slug}"
                    is_tier2 = key in TIER2_SOURCES
                    existing = (await db.execute(select(JobSource).where(JobSource.key == key))).scalar_one_or_none()
                    if not existing:
                        db.add(JobSource(
                            key=key, kind=kind,
                            label=f"{company_name} ({label_suffix})",
                            tier=2 if is_tier2 else 1,
                            enabled=1,
                            bulk_approve=0 if is_tier2 else 1,
                        ))
                    has_co = (await db.execute(select(JobCompany).where(JobCompany.slug == board_slug))).scalar_one_or_none()
                    if not has_co:
                        db.add(JobCompany(slug=board_slug, name=company_name, verified=0 if is_tier2 else 1))
            await db.commit()

    await _retry_db(_op, "ensure_source_rows")


# ---------------------------------------------------------------- core ingest

async def _stage_one(raw: RawJob, source_key: str, db) -> str:
    """Stage one RawJob. Returns one of: 'new', 'unchanged', 'changed', 'skipped_blocked', 'rejected_sticky'."""
    job_hash = compute_hash(raw)

    # Blocklist check.
    co = (await db.execute(select(JobCompany).where(JobCompany.slug == raw["company_slug"]))).scalar_one_or_none()
    if co and co.blocklisted:
        return "skipped_blocked"

    existing = (await db.execute(
        select(Job).where(Job.source == source_key, Job.external_id == raw["external_id"])
    )).scalar_one_or_none()

    if existing and existing.hash == job_hash:
        return "unchanged"

    # Sticky off_topic tombstone: the classifier already decided this is non-AI
    # and admin confirmed by not overriding. Absorb the hash change so we don't
    # re-evaluate every run, but DON'T re-enrich (waste Gemini tokens on a
    # rejected row) or flip to draft (re-queues admin work). Manual rejects
    # (reject_reason IS NULL) still flow through the normal path so admin gets
    # another look if the JD changes meaningfully.
    if existing and existing.status == "rejected" and existing.reject_reason == "off_topic":
        existing.hash = job_hash
        existing.source_url = raw["source_url"]
        return "rejected_sticky"

    # Pre-filter: skip enrichment for titles that are obviously non-AI.
    # Row is still staged (admin can override), but no Gemini call is made.
    if is_non_ai_title(raw["title_raw"]):
        enriched = _minimal_enrichment(raw)
        enrich_error = "auto-skipped: non-AI title"
        logger.debug("pre-filtered non-AI title: %s (%s)", raw["title_raw"], source_key)
    elif has_non_ai_jd_signals(raw["jd_html"]):
        # JD body is saturated with non-AI cluster terms (legal/HR/finance/sales/
        # marketing/design/recruiting/IT/creative/policy) and has low AI intensity.
        # Title alone wouldn't have caught it. See RCA-026, Wave 3 #11.
        enriched = _minimal_enrichment(raw)
        enrich_error = "auto-skipped: non-AI JD content (cluster + low intensity)"
        logger.debug("pre-filtered non-AI JD: %s (%s)", raw["title_raw"], source_key)
    elif is_bare_verb_title(raw["title_raw"]) and compute_ai_intensity(raw["jd_html"]) < AI_INTENSITY_THRESHOLD:
        # Wave 3 #13: bare leadership-verb title (Manager/Director/Lead/Head/VP)
        # without AI anchor word AND JD has no concrete AI work content.
        # Catches "Manager, Sales Development", "Director, Strategic Sourcing",
        # etc. that escape the explicit title pattern list.
        enriched = _minimal_enrichment(raw)
        enrich_error = "auto-skipped: bare-verb title without AI work in JD"
        logger.debug("pre-filtered bare-verb title: %s (%s)", raw["title_raw"], source_key)
    elif source_key in TIER2_SOURCES:
        # Tier-2 boards get lightweight enrichment — fewer fields, shorter JD,
        # smaller prompt. Full enrichment deferred to publish time.
        try:
            from app.services.jobs_enrich import enrich_job_lite
            enriched = await enrich_job_lite(raw, db=db)
            enrich_error = "tier2-lite: full enrichment on publish"
        except Exception as exc:
            logger.exception("lite enrichment failed for %s/%s: %s", source_key, raw["external_id"], exc)
            enriched = _minimal_enrichment(raw)
            enrich_error = f"lite enrichment failed: {exc}"
    else:
        # Enrich (best-effort; see jobs_enrich). Minimal fallback keeps row stageable.
        try:
            from app.services.jobs_enrich import enrich_job
            enriched = await enrich_job(raw, source_key=source_key, db=db)
            enrich_error = None
        except Exception as exc:  # never break ingest on enrichment failure
            logger.exception("enrichment failed for %s/%s: %s", source_key, raw["external_id"], exc)
            enriched = _minimal_enrichment(raw)
            enrich_error = f"enrichment failed: {exc}"

    posted_on = _parse_date(raw["posted_on"])
    valid_through = posted_on + timedelta(days=VALID_FOR_DAYS)

    # Build denormalized columns from enriched payload.
    country = (enriched.get("location") or {}).get("country")
    remote_policy = (enriched.get("location") or {}).get("remote_policy")
    designation = enriched.get("designation") or "Other"
    verified = 1 if (co and co.verified) else 0

    if existing:
        existing.hash = job_hash
        existing.status = "draft"          # back to draft on any change — re-review
        existing.posted_on = posted_on
        existing.valid_through = valid_through
        existing.title = raw["title_raw"]
        existing.designation = designation
        existing.country = country
        existing.remote_policy = remote_policy
        existing.verified = verified
        existing.data = enriched
        existing.source_url = raw["source_url"]
        existing.admin_notes = enrich_error
        return "changed"

    job = Job(
        source=source_key,
        external_id=raw["external_id"],
        source_url=raw["source_url"],
        hash=job_hash,
        status="draft",
        posted_on=posted_on,
        valid_through=valid_through,
        slug=build_slug(raw["title_raw"], raw["company_slug"]),
        title=raw["title_raw"],
        company_slug=raw["company_slug"],
        designation=designation,
        country=country,
        remote_policy=remote_policy,
        verified=verified,
        data=enriched,
        admin_notes=enrich_error,
    )
    db.add(job)
    return "new"


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except Exception:
        return date.today()


def _minimal_enrichment(raw: RawJob) -> dict[str, Any]:
    """Fallback payload when the AI enricher is unavailable. Admin sees a flag
    in admin_notes and can fix fields manually before publishing."""
    return {
        "title_raw": raw["title_raw"],
        "designation": "Other",
        "seniority": "Unknown",
        "topic": [],
        "company": {"name": raw["company"], "slug": raw["company_slug"]},
        "location": {"country": None, "city": None, "remote_policy": None, "regions_allowed": []},
        "employment": {"job_type": "Full-time", "shift": "Unknown"},
        "description_html": raw["jd_html"][:20000],
        "tldr": "",
        "must_have_skills": [],
        "nice_to_have_skills": [],
        "roadmap_modules_matched": [],
        "apply_url": raw["source_url"],
    }


def _is_transient_db_error(exc: OperationalError) -> bool:
    """True for SQLite errors that typically clear on a short backoff.

    'database is locked' / 'database table is locked' — another writer holds
    the WAL reserved-writer slot. 'unable to open database file' — a fresh
    connection raced with concurrent WAL/journal file creation (the cron
    container vs. live backend, per the 2026-04-21 daily_jobs_sync outage).
    All three clear within milliseconds; none indicate a persistent failure.
    """
    msg = str(exc).lower()
    return (
        "database is locked" in msg
        or "database table is locked" in msg
        or "unable to open database file" in msg
    )


async def _retry_db(
    op: Callable[[], Awaitable[Any]],
    label: str,
    max_attempts: int = 4,
) -> Any:
    """Call ``op()`` with exponential backoff on transient SQLite errors."""
    for attempt in range(max_attempts):
        try:
            return await op()
        except OperationalError as exc:
            if not _is_transient_db_error(exc):
                raise
            if attempt == max_attempts - 1:
                logger.warning("db op %r failed after %d attempts: %s",
                               label, max_attempts, str(exc)[:200])
                raise
            delay = 0.2 * (2 ** attempt) + random.uniform(0, 0.1)
            logger.info("db op %r transient error, retrying in %.2fs (attempt %d/%d)",
                        label, delay, attempt + 1, max_attempts)
            await asyncio.sleep(delay)
    raise RuntimeError("unreachable")


async def _stage_with_retry(raw: RawJob, source_key: str, max_attempts: int = 4) -> str:
    """Stage one row with retry+backoff on transient SQLite errors.

    SQLite WAL allows concurrent reads but only one writer at a time. The live
    backend writing session cookies / progress can briefly hold the lock, and
    aiosqlite connection open can race with WAL creation. A short exponential
    backoff (0.2s, 0.4s, 0.8s) clears both classes of error.
    """
    for attempt in range(max_attempts):
        try:
            async with _db.async_session_factory() as db:
                result = await _stage_one(raw, source_key, db)
                await db.commit()
                return result
        except OperationalError as exc:
            if not _is_transient_db_error(exc):
                raise
            if attempt == max_attempts - 1:
                logger.warning("db transient error after %d attempts for %s/%s — giving up",
                               max_attempts, source_key, raw.get("external_id"))
                raise
            delay = 0.2 * (2 ** attempt) + random.uniform(0, 0.1)
            logger.info("db transient error, retrying %s/%s in %.2fs (attempt %d/%d)",
                        source_key, raw.get("external_id"), delay, attempt + 1, max_attempts)
            await asyncio.sleep(delay)
    return "errors"  # unreachable — raised above


# ---------------------------------------------------------------- auto-expire

async def _auto_expire_past_valid_through(stats: dict) -> None:
    """Flip published jobs whose valid_through has elapsed to expired.

    Without this, a job whose `posted_on + 45d` has passed remained
    status=published forever and only rendered the "closed" banner via the
    is_expired check at render time — but it kept appearing in /api/jobs
    and the sitemap. This pass fixes the underlying status.
    """
    async def _op() -> None:
        async with _db.async_session_factory() as db:
            today = date.today()
            stmt = select(Job).where(
                Job.status == "published",
                Job.valid_through.is_not(None),
                Job.valid_through < today,
            )
            rows = (await db.execute(stmt)).scalars().all()
            for job in rows:
                job.status = "expired"
                data = dict(job.data or {})
                meta = dict(data.get("_meta") or {})
                meta.setdefault("expired_reason", "date_based")
                meta.setdefault("expired_on", today.isoformat())
                data["_meta"] = meta
                job.data = data
                stats["auto_expired"] = stats.get("auto_expired", 0) + 1
            if rows:
                logger.info("date-expired %d jobs (valid_through past)", len(rows))
            await db.commit()

    try:
        await _retry_db(_op, "auto_expire_past_valid_through")
    except Exception as exc:
        logger.exception("date-based auto-expire failed: %s", exc)


async def _auto_expire_missing(by_source: dict[str, list[RawJob]], stats: dict) -> None:
    """Flip `published` jobs to `expired` when their ATS listing disappears.

    Greenhouse/Lever give no explicit "role filled" signal — a closed posting
    simply drops from the feed. We track `data._meta.missing_streak` per job
    and flip once the streak hits MISSING_STREAK_THRESHOLD. One grace day
    absorbs transient API blips without falsely expiring live roles.

    Only runs against boards that returned ≥1 row this pass — a source that
    yielded zero rows is treated as an outage, not a mass fill.
    """
    for source_key, rows in by_source.items():
        if not rows:
            logger.warning("source %s returned 0 rows — skipping auto-expire", source_key)
            continue
        seen_ids = {r["external_id"] for r in rows}

        async def _op(sk: str = source_key, ids: set[str] = seen_ids) -> None:
            async with _db.async_session_factory() as db:
                stmt = select(Job).where(Job.source == sk, Job.status == "published")
                published = (await db.execute(stmt)).scalars().all()
                for job in published:
                    data = dict(job.data or {})
                    meta = dict(data.get("_meta") or {})
                    if job.external_id in ids:
                        if meta.get("missing_streak"):
                            meta["missing_streak"] = 0
                            data["_meta"] = meta
                            job.data = data
                        continue
                    streak = int(meta.get("missing_streak", 0)) + 1
                    meta["missing_streak"] = streak
                    if streak >= MISSING_STREAK_THRESHOLD:
                        job.status = "expired"
                        meta["expired_reason"] = "source_removed"
                        meta["expired_on"] = date.today().isoformat()
                        stats["auto_expired"] = stats.get("auto_expired", 0) + 1
                        logger.info("auto-expired %s/%s after %d missed runs",
                                    sk, job.external_id, streak)
                    data["_meta"] = meta
                    job.data = data
                await db.commit()

        try:
            await _retry_db(_op, f"auto_expire_missing[{source_key}]")
        except Exception as exc:
            logger.exception("auto-expire failed for %s: %s", source_key, exc)


# ---------------------------------------------------------------- entry point

async def run_daily_ingest() -> dict[str, int]:
    """Run the full daily ingest. Returns stats dict (for admin banner + logs).

    Uses a fresh session per job so: (a) SQLite WAL writes stay short and
    don't collide with the live backend, (b) one failed row can't rollback
    the whole batch. Per-source fetch remains inside one transaction is OK
    because fetch is read-only HTTP.
    """
    await ensure_source_rows()
    # Probe every board first; auto-disable degraded ones so the fetch loop
    # doesn't waste a slot on a known-dead slug. Probe is cheap (parallel
    # GETs, ~1s wall time for ~30 boards) and writes JobSource.last_run_error.
    from app.services.jobs_sources.probe import probe_all
    probe_results = {}
    try:
        probe_results = await probe_all()
    except Exception as exc:
        logger.warning("probe pass failed (continuing with fetch): %s", exc)
    disabled_keys = {k for k, v in probe_results.items() if not v.get("enabled", True)}
    if disabled_keys:
        logger.info("skipping %d disabled boards: %s", len(disabled_keys), sorted(disabled_keys))

    stats = {"fetched": 0, "new": 0, "changed": 0, "unchanged": 0,
             "skipped": 0, "errors": 0, "disabled_skipped": len(disabled_keys)}

    fetchers = [
        ("greenhouse", GREENHOUSE_BOARDS, gh_fetch_all),
        ("lever", LEVER_BOARDS, lv_fetch_all),
        ("ashby", ASHBY_BOARDS, ash_fetch_all),
    ]
    sem = asyncio.Semaphore(ENRICH_CONCURRENCY)

    # Group fetched jobs per source so we can apply the cap to genuinely NEW
    # rows only (unchanged/existing rows are cheap — no enrichment call).
    by_source: dict[str, list[RawJob]] = {}
    for _kind, _boards, fetch in fetchers:
        async for source_key, raw in fetch():
            if source_key in disabled_keys:
                continue
            stats["fetched"] += 1
            by_source.setdefault(source_key, []).append(raw)

    async def _process(raw: RawJob, source_key: str, new_budget: list[int]) -> str | None:
        # Skip enrichment entirely if this row already exists unchanged.
        async with _db.async_session_factory() as db:
            job_hash = compute_hash(raw)
            existing = (await db.execute(
                select(Job).where(Job.source == source_key, Job.external_id == raw["external_id"])
            )).scalar_one_or_none()
            if existing and existing.hash == job_hash:
                return "unchanged"

        # Genuinely new or changed — respect the per-source budget.
        if new_budget[0] <= 0:
            return "deferred"
        new_budget[0] -= 1
        async with sem:
            return await _stage_with_retry(raw, source_key)

    stats["deferred"] = 0
    for source_key, rows in by_source.items():
        budget = [PER_SOURCE_NEW_CAP]
        # Process serially by source so cap logic stays deterministic, but
        # enrichment itself is parallel via the semaphore inside _stage.
        tasks = [asyncio.create_task(_process(r, source_key, budget)) for r in rows]
        for t in asyncio.as_completed(tasks):
            try:
                result = await t
                if result is None:
                    continue
                key = "skipped" if result == "skipped_blocked" else result
                stats[key] = stats.get(key, 0) + 1
            except Exception as exc:
                logger.exception("ingest error in %s: %s", source_key, exc)
                stats["errors"] += 1

    # Auto-expire pass: published jobs whose external_id vanished from the
    # source feed for N consecutive runs. Guards against mass-expire on a
    # transient source outage by only inspecting boards that returned ≥1 row.
    stats["auto_expired"] = 0
    await _auto_expire_missing(by_source, stats)
    # Date-based: flip published rows whose valid_through has elapsed.
    await _auto_expire_past_valid_through(stats)

    # Stamp JobSource.last_run_* in a short final transaction.
    async def _stamp_op() -> None:
        async with _db.async_session_factory() as db:
            now = datetime.utcnow()
            for kind, boards, _ in fetchers:
                for board_slug, _ in boards:
                    key = f"{kind}:{board_slug}"
                    src = (await db.execute(select(JobSource).where(JobSource.key == key))).scalar_one_or_none()
                    if src:
                        src.last_run_at = now
            await db.commit()

    try:
        await _retry_db(_stamp_op, "stamp_last_run_at")
    except Exception as exc:
        logger.warning("failed to stamp JobSource.last_run_at: %s", exc)

    # Wave 4 #14: auto-disable sources whose admin-rejection rate exceeds
    # threshold. Catches drifting sources that start emitting non-AI roles
    # before the admin queue gets buried. PhonePe-RCA-026 in hindsight.
    try:
        auto_disabled = await check_source_rejection_rates()
        stats["auto_disabled_high_reject"] = len(auto_disabled)
        for src, rej, total, rate in auto_disabled:
            logger.warning(
                "auto-disabled source %s: %d/%d rejected (%.0f%%) — exceeds threshold",
                src, rej, total, rate * 100,
            )
    except Exception as exc:
        logger.warning("rejection-rate check failed (non-fatal): %s", exc)
        stats["auto_disabled_high_reject"] = 0

    logger.info("jobs ingest complete: %s", stats)
    return stats


# ---------------------------------------------------------------- Wave 4 #14
# Per-source rejection-rate alarm.
#
# When admin keeps rejecting drafts from a source as "off-topic" or "non-AI",
# that source is drifting and should be paused for review. The check runs at
# the end of every daily ingest and auto-disables sources exceeding the
# rejection-rate threshold over a recent window. Admin can re-enable from
# /admin/jobs/api/sources after fixing the underlying issue.
#
# Defaults tuned for our scale: 30-day window, min 20 reviewed rows
# (rejected+published+expired) to avoid flapping on small samples,
# threshold 40%.

REJECTION_RATE_WINDOW_DAYS = 30
REJECTION_RATE_MIN_SAMPLE = 20
REJECTION_RATE_THRESHOLD = 0.40


async def check_source_rejection_rates(
    window_days: int = REJECTION_RATE_WINDOW_DAYS,
    min_sample: int = REJECTION_RATE_MIN_SAMPLE,
    threshold: float = REJECTION_RATE_THRESHOLD,
) -> list[tuple[str, int, int, float]]:
    """Find sources with high admin-rejection rates and auto-disable them.

    Window: jobs whose updated_at is within `window_days` AND whose status
    is one of (rejected/published/expired) — i.e. admin has acted on them.
    Drafts are excluded — not yet reviewed.

    Returns list of (source_key, rejected_count, reviewed_total, reject_rate)
    for sources that were disabled in this call. Already-disabled sources
    are not touched (no double-stamping over probe-disable reasons).
    """
    from sqlalchemy import func as _func
    cutoff = datetime.utcnow() - timedelta(days=window_days)
    disabled: list[tuple[str, int, int, float]] = []
    async with _db.async_session_factory() as db:
        stmt = (
            select(Job.source, Job.status, _func.count(Job.id))
            .where(
                Job.updated_at >= cutoff,
                Job.status.in_(["rejected", "published", "expired"]),
            )
            .group_by(Job.source, Job.status)
        )
        rows = (await db.execute(stmt)).all()
        per_source: dict[str, dict[str, int]] = {}
        for src, status, n in rows:
            per_source.setdefault(src, {})[status] = n

        for src, counts in per_source.items():
            rejected = counts.get("rejected", 0)
            published = counts.get("published", 0)
            expired = counts.get("expired", 0)
            reviewed_total = rejected + published + expired
            if reviewed_total < min_sample:
                continue
            reject_rate = rejected / reviewed_total
            if reject_rate < threshold:
                continue
            src_row = (await db.execute(
                select(JobSource).where(JobSource.key == src)
            )).scalar_one_or_none()
            if src_row is None or not src_row.enabled:
                continue
            src_row.enabled = 0
            src_row.last_run_error = (
                f"auto-disabled: {int(reject_rate * 100)}% reject rate "
                f"({rejected}/{reviewed_total} over {window_days}d)"
            )
            disabled.append((src, rejected, reviewed_total, reject_rate))
        if disabled:
            await db.commit()
    return disabled
