# AI Jobs Classification — Defense Layers

> **Status:** all 10 layers shipped (RCA-026 + Waves 1–5 #18) and live in production as of 2026-04-16.
> **Goal:** zero false positives in AI classification (bias toward rejection over inclusion).
> **Audience:** developers extending the system. Admin-facing instructions live at `/admin/jobs-guide`.

---

## Why this document exists

Before the RCA-026 fix, a PhonePe **"Manager, Legal"** job was ingested and stamped `Topic = ["Applied ML"]` because the JD said *"LLB / LLM from a recognized university"* — Gemini Flash mistook the law degree for **L**arge **L**anguage **M**odel. After investigation we found 268+ historical false positives across Tier-1 sources (Anthropic, Databricks, xAI, Cerebras, etc.) — sales execs, legal counsel, recruiters, designers, all wrongly tagged with AI topics.

Five iterative waves of defense were shipped over one session. Each wave addressed a specific failure mode discovered while measuring the previous one. This document is the source of truth for what each layer does, **why** it exists, and where it lives in the code.

---

## The 10 layers, in pipeline order

```
RawJob
  │
  ▼
[1] is_non_ai_title()                          ──┐
  │                                              │
  ▼                                              │  Pre-enrichment gates
[2] has_non_ai_jd_signals()                    ──┤  (skip Gemini call entirely)
  │                                              │
  ▼                                              │
[3] is_bare_verb_title() + intensity gate     ──┘
  │
  ▼
Gemini Flash enrichment (Tier-1 full / Tier-2 lite)
  │
  ▼
[4] AI-intensity score      ─── informs [2] & [3]
[5] Self-rejection prompts  ─── inside the Gemini call
[6] Evidence-span validation                   ──┐
  │                                              │
  ▼                                              │  Post-enrichment validators
[7] Topic-anchor check                         ──┤  (Gemini lied / over-reached)
  │                                              │
  ▼                                              │
[8] Designation↔topic consistency              ──┘
  │
  ▼
Job staged as draft
  │
  ▼
[9] Per-source rejection-rate alarm    (end of daily ingest cron)
[10] Weekly Opus audit                  (Mon 04:30 UTC, manual via Claude Code)
```

---

## Layer reference

### Layer 1 — `is_non_ai_title()` — title pre-filter
**File:** [`backend/app/services/jobs_ingest.py`](../backend/app/services/jobs_ingest.py) — `_NON_AI_TITLE_PATTERNS` + `is_non_ai_title()`

**What it does:** substring match (case-insensitive) against ~120 patterns covering 21 non-AI categories. Catches obvious cases like *"Sales Manager"*, *"Legal Counsel"*, *"Recruiter"*, *"Office Manager"*, *"UX Designer"*, *"Tax Analyst"*, etc.

**The 21 categories** (from RCA-026 + Wave 1 #1):
- Business / operations (sales mgr, account exec, customer success)
- Sales engineering / pre-sales
- Partnerships / business development
- Program / project management (TPM, Chief of Staff)
- Legal / compliance (legal counsel, contracts manager, legal manager, manager-comma-legal)
- Finance / accounting / payroll / RevOps / IR
- HR / recruiting / benefits administration / KYC
- Marketing (general + product marketing / growth / demand-gen)
- Policy / governance / AI ethicist
- Community / DevRel (non-code)
- Technical writing / UX writing
- Training / education / curriculum design
- Design (UX/UI/product/visual designer, UX researcher)
- Cybersecurity (AppSec / InfoSec / SOC analyst — non-AI-safety)
- IT / workplace tech / help desk
- Creative / video / podcast production
- Clinical / medical reviewer
- Localization / translation
- Physical security / facilities
- Vendor / strategic sourcing
- Customer Solutions Architect (sales-side) / TAM

**Why substring not regex:** simple, fast, easy to audit. Patterns include leading/trailing space where needed (e.g. `" hr manager"` to avoid matching `"chr managers"`).

**Tradeoff:** misses titles with creative formatting (e.g., *"Manager, Sales Development"* — comma breaks the substring `"sales manager"`). Layer 3 catches those.

---

### Layer 2 — `has_non_ai_jd_signals()` — JD body cluster scanner
**File:** [`backend/app/services/jobs_ingest.py`](../backend/app/services/jobs_ingest.py) — `_NON_AI_JD_SIGNALS` + `has_non_ai_jd_signals()`

**What it does:** two-gate rule on the JD body:
1. **≥2 hits** from non-AI cluster signals (~80 terms across 9 clusters: legal, HR/finance/KYC, sales/GTM, marketing, recruiting, design/UX, finance/accounting, IT/support, creative, policy)
2. **AND** AI-intensity score < 5 (Layer 4)

If both true → auto-skip enrichment with `admin_notes = "auto-skipped: non-AI JD content (cluster + low intensity)"`.

**Why two gates:** a real AI Engineer JD might mention "NDA" or "MSA" once in passing (employment terms). Single-term match would over-reject. ≥2 cluster hits indicates the JD is *structurally* about that domain, not just mentioning it.

**Why intensity score check:** an AI Solutions Architect JD might mention "commercial contracts" (1 legal hit) and "MSA" (2nd hit) but its body is full of AI signals. Intensity ≥5 keeps it safe.

---

### Layer 3 — `is_bare_verb_title()` + intensity gate — bare-verb leadership titles
**File:** [`backend/app/services/jobs_ingest.py`](../backend/app/services/jobs_ingest.py) — `_BARE_VERB_TITLE_RE` + `_AI_TITLE_ANCHOR_RE` + `is_bare_verb_title()`

**What it does:** detects titles starting with `Manager` / `Director` / `Lead` / `Head of` / `VP` / `Chief` (with optional `Senior`/`Principal`/`Staff` prefix) that contain **no** AI anchor word (`ai`, `ml`, `machine learning`, `deep learning`, `llm`, `nlp`, `cv`, `computer vision`, `data`, `research`, `applied`, `model`, `robotics`, `safety`, `alignment`, `inference`, `mlops`, `generative`, `genai`, `engineering`).

Combined with intensity score < 5 → auto-skip.

**Catches:**
- `"Manager, Sales Development (Startups & Commercial)"` — Layer 1 misses (no `"sales manager"` substring)
- `"Director, Strategic Sourcing"`
- `"Head of Programmatic Outcomes — Partners"`
- `"VP, Finance"`
- `"Chief of Staff"`

**Doesn't fire on:**
- `"Engineering Manager"` (doesn't START with Manager)
- `"Manager, AI Safety"` (has `ai` anchor)
- `"Director of Engineering"` at Anthropic (has `engineering` anchor; even if it did fire, JD intensity ≥5 prevents skip)
- `"Senior ML Engineer"` (not a bare-verb title)

---

### Layer 4 — `compute_ai_intensity()` — three-tier weighted score
**File:** [`backend/app/services/jobs_ingest.py`](../backend/app/services/jobs_ingest.py) — `_AI_STRONG_PATTERNS` / `_AI_MEDIUM_PATTERNS` / `_AI_WEAK_PATTERNS` + `compute_ai_intensity()`

**What it does:** sum-of-weights score; threshold = **5**.

| Tier | Weight | Examples | Count |
|---|---|---|---|
| STRONG | 3 | `pytorch`, `fine-tuning`, `rlhf`, `machine learning`, `large language model`, `retrieval augmented`, `mlops`, `gpt-4`, `claude api` | ~110 |
| MEDIUM | 2 | `\bllm\b`, `\brag\b`, `\bagents?\b`, `\bgpus?\b`, `ml engineer`, `applied ml` | ~12 |
| WEAK | 1 | `ai-powered`, `ai-driven`, `ai products`, `using ai` | ~6 |

**Critical design choices:**

1. **Word-boundary regex** (`\bllm\b`) — substring matching was the root of the original RCA-026 bug. `"shopping"` matched `"ppo"`, `"fragment"` matched `"rag"`, `"fulfillment"` matched `"llm"`. Fixed in Wave 2 #6.
2. **Per-JD dedup** — each pattern counts AT MOST ONCE regardless of occurrence count. Boilerplate that repeats `"AI-powered"` 10 times scores 1, not 10. Wave 2 #9.
3. **Boilerplate stripping** — `_strip_company_boilerplate()` removes `"About Anthropic"` / `"Our mission"` / `"Why join us"` sections before scoring. AI lab JDs uniformly open with `"Anthropic's mission is to build safe AI..."` — that paragraph contains AI terms regardless of role. Wave 2 #10.
4. **Requirement-phrase neutralizer** — `_neutralize_requirement_phrases()` strips `"experience with X"` / `"familiarity with X"` / `"knowledge of X"` / `"background in X"` / `"proficiency in X"` spans up to 80 chars. These describe what the candidate must KNOW, not what they DO. Critical for catching recruiters/marketers/sales engineers who need AI literacy in requirements but don't perform AI work. Wave 3 #12.
5. **Brand-name disambiguation** — bare `Claude` / `Gemini` / `OpenAI` / `Anthropic` do NOT count (people's names, zodiac signs, company-name boilerplate). Qualified forms required: `Claude API`, `Claude Sonnet`, `OpenAI API`, etc. `BERT` excluded entirely (Albert/Bert collision). `ACL` excluded (access control list).

**Calibration data:**
- Real ML Engineer JD: scores 18-30
- Anthropic Research Scientist: scored 24
- Office Manager at AI lab: scored 0 (after boilerplate strip)
- PhonePe Manager Legal: scored 0
- Recruiter with "experience with ML" requirements only: scored 0 (after requirement-phrase strip)

---

### Layer 5 — Self-rejection rules in system prompts
**Files:** [`backend/app/prompts/jobs_extract_system.txt`](../backend/app/prompts/jobs_extract_system.txt), [`backend/app/prompts/jobs_extract_lite_system.txt`](../backend/app/prompts/jobs_extract_lite_system.txt)

**What it does:** instructs Gemini to return `topic: []` and `designation: "Other"` when the role's primary function is one of 21 non-AI categories — *even at AI-first companies*.

Key clauses:
- "Recruiters who source ML candidates, marketers who position AI products, sales engineers who demo AI APIs, and policy analysts who study AI regulation all need AI knowledge but do not perform AI work."
- *"Experience with ML/AI"* as a job REQUIREMENT does not make a role AI."
- "Bare Manager/Director/Lead/Head/VP titles without explicit AI anchor must self-reject."
- "When uncertain, prefer `topic: []` over guessing. Empty is correct."

**Why instruct rather than rely solely on validators:** prompt-level rules cost ~0.1¢ per call (one-time prompt token cost) but reduce the chance Gemini ever produces wrong output. Cheaper than rejecting downstream.

---

### Layer 6 — `_validate_topic_with_evidence()` — evidence-span validation (Wave 5 #18)
**File:** [`backend/app/services/jobs_enrich.py`](../backend/app/services/jobs_enrich.py) — `_TOPIC_FORBIDDEN_EVIDENCE` + `_validate_topic_with_evidence()`

**What it does:** new prompt schema requires Gemini to return topics as objects with an `evidence` field:

```json
"topic": [
  {"name": "LLM", "evidence": "fine-tune large language models with RLHF"},
  {"name": "Applied ML", "evidence": "deploy production ML models for ranking"}
]
```

Validator checks for each entry:
1. **Evidence is a verbatim substring of the JD** (anti-hallucination — Gemini sometimes invents quotes)
2. **Length 8–200 chars** (specific enough; not whole paragraphs)
3. **Evidence does NOT match per-topic forbidden patterns:**
   - **`LLM`:** `LLB`, `LL.B`, `LL.M from/degree/in`, `Master of Laws`, `PQE`, `post-qualification experience`, `law firm`, `law school`, `legal counsel`, `contract drafting`, `bar council`, `advocate`
   - **`Safety`:** `workplace safety`, `building security`, `physical security`, `fire safety`, `product compliance`, `occupational safety`, `safety officer/manager`
   - **`Research`:** `user research`, `market research`, `customer research`, `ux research`, `competitive research`
   - **`Applied ML`:** leading `AI-powered/-driven/-first/-native/-enabled` (marketing-only mention)

**Backwards compatible** — accepts both new object[] format and legacy string[] format. If Gemini returns old format (cached responses, prompt errors), validator degrades gracefully.

**Storage unchanged** — DB stores topic as flat string array; evidence is verified at validation time but not persisted.

---

### Layer 7 — `_enforce_topic_anchors()` — JD anchor requirement
**File:** [`backend/app/services/jobs_enrich.py`](../backend/app/services/jobs_enrich.py) — `_TOPIC_ANCHORS` + `_enforce_topic_anchors()`

**What it does:** independently verifies each assigned topic has at least one **anchor phrase** somewhere in the JD body. 15 topics, each with 5–15 multi-word anchor phrases.

Examples:
- `LLM` anchors: `large language model`, `fine-tun`, `prompt engineer`, `openai api`, `claude api`, `gpt-4`, `foundation model`, `transformer architecture`, `llama`, `mistral`
- `CV` anchors: `computer vision`, `image classification`, `object detection`, `image segmentation`, `vision transformer`, `opencv`, `yolo`
- `MLOps` anchors: `mlops`, `ml platform`, `model registry`, `kubeflow`, `mlflow`, `feature store`, `model serving`, `deployment pipeline`

**Why redundant with Layer 6?** Belt-and-suspenders. Layer 6 verifies Gemini's chosen evidence is valid; Layer 7 verifies the *topic itself* has independent justification in the JD. A Gemini hallucination that picks the right evidence but the wrong topic name would slip past Layer 6 alone.

---

### Layer 8 — `_enforce_designation_topic_consistency()` — structural rule
**File:** [`backend/app/services/jobs_enrich.py`](../backend/app/services/jobs_enrich.py)

**What it does:**
- `designation == "Other"` → force `topic = []`. (If Gemini admits the role isn't a core AI role, AI topics are inconsistent.)
- `designation in {AI Developer Advocate, AI Solutions Architect, AI Product Manager, Prompt Engineer}` → cap `topic` to 1 item. (These are AI-adjacent; Gemini over-assigns multi-topic to them.)

**Caught the most stealthy false positives** — Gemini self-contradictions where it correctly marked a role as `Other` but still listed 2-3 AI topics out of habit.

---

### Layer 9 — `check_source_rejection_rates()` — auto-disable noisy sources
**File:** [`backend/app/services/jobs_ingest.py`](../backend/app/services/jobs_ingest.py)

**What it does:** runs at end of every daily ingest. For each enabled source, calculates rejection rate over last 30 days (statuses in `{rejected, published, expired}` — drafts excluded).

Auto-disables (`JobSource.enabled = 0`) when:
- Reviewed sample ≥ 20 rows (avoids flapping on small samples)
- Reject rate ≥ 40%

Stamps `JobSource.last_run_error = "auto-disabled: 75% reject rate (15/20 over 30d)"`.

Already-disabled sources are not re-disabled (preserves probe-disable reasons from `jobs_sources/probe.py`).

**Tunable constants:** `REJECTION_RATE_WINDOW_DAYS=30`, `REJECTION_RATE_MIN_SAMPLE=20`, `REJECTION_RATE_THRESHOLD=0.40`.

---

### Layer 10 — Weekly Opus audit (no API spend)
**Files:**
- [`scripts/select_audit_sample.py`](../scripts/select_audit_sample.py) — selection cron
- [`backend/app/routers/admin_jobs.py`](../backend/app/routers/admin_jobs.py) — `/api/audit-pending` + `/api/audit-submit`
- [`scripts/scheduler.py`](../scripts/scheduler.py) — `weekly_audit_select_loop` (Mon 04:30 UTC)

**What it does:** weekly cron picks 1% of Tier-1 published jobs (clamped 1–20), stamps `Job.data["audit"] = {selected_at, status: "pending"}`. Skips rows reviewed within 90-day cooldown.

Admin sees amber banner in `/admin/jobs`: *"N pending Opus audit [COPY PROMPT]"*. Click copies a Claude Code prompt to clipboard. Admin pastes into VS Code (Claude Max — no API spend), gets back JSON verdicts, POSTs to `/api/audit-submit`.

Disagreements stamp `OPUS-AUDIT mismatch (date): notes` on `admin_notes`.

**Cost:** $0. Claude Max is a fixed monthly subscription.

**Why manual not automated:** the user explicitly requested no API spend. The signal is slow-drift detection — weekly review cadence is more than enough.

---

## Configuration / tunable thresholds

All in [`backend/app/services/jobs_ingest.py`](../backend/app/services/jobs_ingest.py):

```python
PER_SOURCE_NEW_CAP = 30          # Max new jobs enriched per source per run
ENRICH_CONCURRENCY = 4           # Bounded parallelism for enrichment
MISSING_STREAK_THRESHOLD = 2     # Daily runs absent before auto-expire
AI_INTENSITY_THRESHOLD = 5       # Layer 4 gate
REJECTION_RATE_WINDOW_DAYS = 30  # Layer 9 lookback
REJECTION_RATE_MIN_SAMPLE = 20   # Layer 9 min reviewed rows
REJECTION_RATE_THRESHOLD = 0.40  # Layer 9 reject % to auto-disable
```

In [`scripts/select_audit_sample.py`](../scripts/select_audit_sample.py):

```python
DEFAULT_SAMPLE_PCT = 0.01        # Layer 10 — 1% of Tier-1 published
MIN_SAMPLE = 1                   # Always pick at least 1
MAX_SAMPLE = 20                  # Hard cap per audit run
DEFAULT_COOLDOWN_DAYS = 90       # Don't re-audit within 90d
```

---

## Where each layer fires (lifecycle)

| Phase | Layer | Triggers |
|---|---|---|
| Ingest pre-filter (in `_stage_one`) | 1, 2, 3 | Skip Gemini call entirely |
| Inside Gemini call | 5 | Prompt rule — Gemini self-rejects |
| Post-enrichment validators (in `_validate` / `enrich_job_lite`) | 6, 7, 8 | Strip topics; force consistency |
| Post-ingest cron tail | 9 | Auto-disable noisy sources |
| Weekly cron + admin UI | 10 | Manual Opus audit via Claude Code |

Layer 4 is invoked by Layers 2, 3 (gates) and exposed via `/admin/jobs/api/summary-stats` for the intensity histogram (Wave 4 #15).

---

## Tests

All in [`backend/tests/test_jobs_cost_opt.py`](../backend/tests/test_jobs_cost_opt.py).

| Test class | Covers | Count |
|---|---|---|
| `TestNonAITitleFilter` | Layer 1 — original + RCA-026 cases | ~17 |
| `TestNonAIJDSignals` | Layer 2 — original PhonePe legal pattern | 5 |
| `TestWave1TitlePatterns` | Layer 1 — 21 new categories | 33 |
| `TestNonAIClusterExpansion` | Layer 2 — Wave 3 cluster additions | 9 |
| `TestRequirementPhraseNeutralizer` | Layer 4 — Wave 3 #12 | 8 |
| `TestBareVerbTitleGate` | Layer 3 — pure-function tests | 16 |
| `TestAIIntensityScoring` | Layer 4 — score correctness | 15 |
| `TestBoilerplateStripping` | Layer 4 — Wave 2 #10 | 6 |
| `TestHasNonAIJDSignalsWithIntensity` | Layer 2 ↔ 4 interaction | 6 |
| `TestEvidenceSpanValidation` | Layer 6 — Wave 5 #18 | 16 |
| `TestTopicAnchors` | Layer 7 | 10 |
| `TestDesignationTopicConsistency` | Layer 8 | 6 |
| Rejection-rate alarm tests | Layer 9 | 4 |
| Audit sample tests | Layer 10 | 4 |
| `_stage_one` integration tests | Layers 1+2+3 wiring | ~5 |

**Total: 16 test classes / ~160 tests dedicated to this defense system.**
**Pass rate: 426/426 on full backend suite as of 2026-04-16.**

---

## Backfill

[`scripts/backfill_rca026_non_ai.py`](../scripts/backfill_rca026_non_ai.py) — applies Layers 1, 2, 3 against historical rows. Idempotent: re-runs skip already-marked rows.

```bash
# Dry-run (lists what would change)
python scripts/backfill_rca026_non_ai.py --dry-run

# Apply (clears topic, stamps admin_notes)
python scripts/backfill_rca026_non_ai.py --apply

# Include published rows (default = drafts only)
python scripts/backfill_rca026_non_ai.py --apply --all-statuses
```

**Cumulative impact across all waves:** 268 historical false positives silenced.

---

## Adding a new defense layer

If a new failure pattern appears:

1. **Find which existing layer is closest.** Most failures fit one of the 10. Add patterns/anchors there before adding a layer.
2. **Add 5+ tests covering the new pattern AND a regression guard** (a real AI role with similar surface text that must NOT be filtered). The regression guard is what stops new layers from being too aggressive.
3. **Update the relevant constants section in this doc.**
4. **Run the backfill in `--dry-run` mode first** — see how many historical rows would be affected. If thousands, the new rule is too aggressive.
5. **Log an RCA entry** in [`docs/RCA.md`](RCA.md) with symptom / root cause / fix / prevention. RCA-026 is the template.

---

## Open issues / future work (not yet implemented)

- **Wave 5 #19 (two-stage classifier):** insert a cheap Gemini YES/NO gate before full enrichment. Cost-benefit currently unfavorable post-Waves 1–5; revisit if drift detection (Layers 9, 10) reveals new failure patterns.
- **Sales-cluster expansion:** the non-AI cluster scanner is tuned for legal/HR/finance. A "Sales Development" JD with no legal/HR words but heavy GTM jargon might still reach enrichment. Wave 3 #11 added some sales terms but the gap could widen.
- **Embedding-based similarity check:** could compare each JD against a corpus of known AI/non-AI JDs. Out of scope for now (overengineering — current rule-based system is precise enough).
