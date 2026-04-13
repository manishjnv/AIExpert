# AI Quality Pipeline

End-to-end lifecycle of a curriculum template — from discovery to publish. Every stage, every model, every guardrail, every cost-saving measure currently in production.

## Pipeline stages at a glance

```
┌────────────────────────────────────────────────────────────────────────┐
│ DISCOVERY        (AI finds trending topics)                            │
│ ├─ TRIAGE        (cheap free-tier classifier filters 80%)              │
│ ├─ EMBED+DEDUP   (OpenAI vectors reject semantic near-duplicates)      │
│ └─ → discovered_topics table                                           │
├────────────────────────────────────────────────────────────────────────┤
│ ADMIN REVIEW  (or auto-approve from Pipeline Settings)                 │
│ └─ → status: approved                                                  │
├────────────────────────────────────────────────────────────────────────┤
│ GENERATION       (Gemini 2.5 Flash + JSON schema)                      │
│ ├─ Per approved topic × duration × level                               │
│ └─ → template JSON written to data/templates/                          │
├────────────────────────────────────────────────────────────────────────┤
│ QUALITY PIPELINE (per template)                                        │
│ ├─ STAGE 0 · Prefix    local auto-fix (dedup, whitespace, hours)       │
│ ├─ STAGE 1 · Score     heuristic 0–100                                 │
│ ├─ STAGE 2 · Review    Gemini cross-model, cached 30d                  │
│ ├─ STAGE 3 · Refine    Gemini Flash (patterns) or Pro (reasoning)      │
│ └─ STAGE 4 · Validate  heuristic + semantic guardrail                  │
├────────────────────────────────────────────────────────────────────────┤
│ ADMIN PUBLISH  (score ≥ 90 required)                                   │
│ └─ → users can enrol                                                   │
├────────────────────────────────────────────────────────────────────────┤
│ REFRESH          (scheduled; link health + content currency)           │
│ └─ → flags stale templates for re-refine                               │
└────────────────────────────────────────────────────────────────────────┘
```

## Stage-by-stage contract

### Stage 0 — Prefix (deterministic auto-fix)

Runs before any LLM call. Mechanical cleanups that cost nothing.

- Dedup checklist items within a week (case-insensitive).
- Dedup resources by URL.
- Strip whitespace on all strings.
- Normalise missing/zero `hours` to default 16.
- Normalise missing/zero resource `hrs` to 4.
- Sequential week numbering (1..N) across months.
- Drop empty strings, skip malformed items.

**Reports** in `stages_run` as `"prefix"` with `models_used.prefix = "local"`. Skipped cleanly when no fixes needed.

Code: [_auto_fix()](backend/app/services/quality_pipeline.py).

### Stage 1 — Heuristic Score

Fast pattern-based scorer. No LLM, no DB. Mirrors the full 15-dim scorer on the cheap.

Penalties:

| Pattern | Penalty |
|---|---|
| `total_weeks < 80%` of expected | −10 |
| Empty weeks (no focus, no deliv) | up to −15 |
| Weeks with zero resources | up to −10 |
| Checklist items with vague verbs ("Understand", "Learn") | up to −20 |
| Last month < 30% Create-level verbs (Build, Design, Deploy, Train…) | −10 |
| No "advanced" verbs in last month | −5 |
| Measurable criteria (%/F1/accuracy) < 10% of checks | −5 |
| Resource-URL domain diversity < 3 | −5 |

Code: [_quick_heuristic_score()](backend/app/services/quality_pipeline.py).

**Short-circuit:** if heuristic ≥ `SKIP_REVIEW_THRESHOLD` (92) → pipeline returns immediately. No AI calls.

### Stage 2 — AI Review (cross-model)

Gemini reviews the template across **15 quality dimensions** — see [review_curriculum.txt](backend/app/prompts/review_curriculum.txt). Returns a structured JSON with:
- per-dimension score (1–10)
- `dimensions_below_threshold`
- `critical_fixes` (week-targeted action items)

**Cost optimisations:**

1. **Structured output with JSON schema** ([QUALITY_REVIEW_SCHEMA](backend/app/ai/schemas.py)) — guarantees valid JSON, eliminates retry loops.
2. **System-instruction separation** — Gemini caches the ~800-token rubric across calls.
3. **Compact JSON** (`separators=(",",":")`) in prompt body.
4. **Cross-model** — uses Gemini even if Gemini generated the plan (review and generator models are decoupled).
5. **Result cache** — 30-day TTL keyed on the **structural fingerprint** of the plan (normalised title/level + sorted focus/checks/URLs). Trivial edits hit cache.

Code: [_run_ai_review()](backend/app/services/quality_pipeline.py).

### Stage 3 — Refinement

Surgically rewrites *only* the weeks identified as weak. The full plan is never sent for rewrite.

**Inputs:**
- `failing_weeks`: the subset of week objects targeted.
- `critical_fixes`: review-identified issues **+ heuristic diagnostics** (pattern-specific instructions like *"Rewrite 6 checks in weeks [9,10,11,12] to start with Build/Design/Deploy — last month only has 2/20 (10%) Create-level verbs"*).

**Heuristic diagnostics** — this is the key unlock for free-model refinement. Without pattern-specific instructions, review AI identifies high-level dimensions but refinement AI doesn't know which exact week/items to fix. Code: [_heuristic_diagnostics()](backend/app/services/quality_pipeline.py) surfaces:
- Vague verbs per week (with example items)
- Last-month Create-verb count vs threshold
- Measurability count across the plan

Then merges into `critical_fixes` so the refiner has precise targets.

**Payload cap:** max 6 weeks per call. Prioritises latest weeks (last-month Create-verb fixes always survive the cap).

**Model routing — smart dispatch, not just severity count:**

```
REASONING_DIMS = {blooms_progression, difficulty_calibration,
                  prerequisites_clarity, industry_alignment,
                  freshness, real_world_readiness}
PATTERN_DIMS   = {assessment_quality, completeness, project_density,
                  theory_practice_ratio, deliverable_quality,
                  resource_diversity}

use_pro if:
    len(reasoning_failing) >= 2    OR
    total severity (failing_dims + heuristic_fixes) >= 4
```

Pattern-fixable failures route to **Gemini Flash** even when many dims fail — they're mechanical, Flash handles them reliably at 15× lower cost than Pro.

**Providers (in dispatch order):**

| Dispatch | Provider | Model | Cost (in/out per 1M) |
|---|---|---|---|
| `gemini-pro` | Gemini | `gemini-2.5-pro` | $1.25 / $5.00 |
| `gemini` | Gemini | `gemini-2.5-flash` | $0.075 / $0.30 |
| `claude` (dormant) | Anthropic | `claude-sonnet-4-6` | $3.00 / $15.00 |

Claude path retained but unused by default — Anthropic Tier 1 requires $40 cumulative spend for reliable API access, so we use Gemini Pro as the quality ceiling instead.

**Token budget:** `quality_refine` = 16 384 output tokens (raised from 4 096 to prevent JSON truncation on multi-week refines).

Code: [_run_refinement()](backend/app/services/quality_pipeline.py).

### Stage 4 — Validate

After refine, two checks gate acceptance:

1. **Heuristic regression** — if `new_score < old_score`, revert to original.
2. **Semantic guardrail** (OpenAI embeddings) — cosine similarity between original and refined plan fingerprints:
   - `sim > 0.98` → refine produced near-identical output, **reject as wasted call**.
   - `sim 0.50–0.98` → normal edit, accept.
   - `sim < 0.50` → refine diverged too much, **possible hallucination**, reject.

Embedding cost: ~$0.00004 per check. Catches ~10–15% of otherwise-wasted refines worth $0.02–0.04 each.

Best-effort: if OpenAI fails, the guardrail is skipped and the pipeline proceeds without blocking.

Code: [_semantic_similarity()](backend/app/services/quality_pipeline.py), [_plan_fingerprint_text()](backend/app/services/quality_pipeline.py).

## Provider matrix

| Stage | Primary | Fallback(s) | Rationale |
|---|---|---|---|
| Discovery | Gemini Flash | provider chain | Structured output, schema-enforced |
| Triage | Groq Llama | Cerebras → Mistral → pass-through | Free, fast classification; cascading fallback on rate limit |
| Embedding | OpenAI `text-embedding-3-small` | — | Best $/quality for embeddings ($0.02/1M) |
| Generation | Gemini Flash + JSON schema | provider chain | Guaranteed schema, cached system prompt |
| Review | Gemini Flash | Groq | Structured output, cached rubric |
| Refine — pattern | Gemini Flash | none | Mechanical fixes, free tier |
| Refine — reasoning | Gemini Pro | Gemini Flash | Deep reasoning; ~1.5× cheaper than Claude |
| Validate — heuristic | local Python | — | Free |
| Validate — semantic | OpenAI embeddings | skip on error | Guardrail, best-effort |

## Cost optimisations in effect

### Gemini

1. ✅ `gemini-2.5-flash` default (over 1.5-flash; same price, better reasoning).
2. ✅ Structured output with JSON schema — no parse-retry loops.
3. ✅ `thinkingConfig.thinkingBudget = 0` — disables thinking tokens, saves ~30% output cost on 2.5 models.
4. ✅ System-instruction separation — Gemini auto-caches stable system prompts.
5. ✅ Right-sized `maxOutputTokens` per task (1 k chat → 16 k refine).
6. ✅ Compact JSON bodies (no whitespace overhead).
7. ✅ Structural-fingerprint review cache (30-day TTL).
8. ✅ Send only failing weeks to refiner (never full plan).
9. ✅ Heuristic-first gate — skip AI review entirely when heuristic ≥ 92.
10. ✅ Pattern-dim failures route to Flash, not Pro.
11. ✅ Temperature 0.3 — deterministic enough to avoid regeneration churn.

### OpenAI

1. ✅ `text-embedding-3-small` over `-large` (85% cheaper, negligible quality diff for topic dedup / semantic similarity).
2. ✅ Embedding-only — never in generation chain.
3. ✅ 90-day embedding cache (embeddings are deterministic by text+model).
4. ✅ Batch embedding calls where possible.

### Free-tier providers

1. ✅ Groq / Cerebras / Mistral for triage (cascading fallback on 429).
2. ✅ Circuit breaker on permanent errors (402, 404).

## Failure modes & what the pipeline does

| Failure | Detected by | Action |
|---|---|---|
| Gemini review JSON invalid | `json.loads` exception | Retry without schema once; else skip review |
| Gemini refine output truncated | `finishReason == MAX_TOKENS` | Log warning; output likely invalid JSON; refine skipped |
| Gemini refine produces non-list | isinstance check | Return None; validate stage uses original plan |
| Refinement score regressed | heuristic re-score | Revert to original |
| Refinement ~identical (sim > 0.98) | embedding guardrail | Revert to original, log as wasted call |
| Refinement hallucination (sim < 0.50) | embedding guardrail | Revert to original, flag for admin |
| Anthropic 402 / 4xx | HTTP status | Log usage with status=error; Gemini Pro used instead |
| Groq rate limit | HTTP 429 | Cascade: Cerebras → Mistral → pass-through |
| All providers fail | exception chain | Fail open; triage returns None (pass-through) |

## Admin-triggered entry points

| Action | Endpoint | Effect |
|---|---|---|
| Generate new template | `POST /admin/api/generate-template` | Generation → full quality pipeline |
| Refine all below 90 | `POST /admin/pipeline/api/run-refine` | Quality pipeline for each sub-90 template |
| Refine single template | `POST /admin/pipeline/api/refine-one/{key}` | Quality pipeline for one template (for UI per-row Refine button) |
| Check quality | `POST /admin/pipeline/api/quality/{key}/publish` | Scores, auto-publishes if ≥ 90 |
| Publish | same endpoint | Same, just explicit intent |
| Unpublish | `POST /admin/pipeline/api/quality/{key}/unpublish` | Move back to draft |

## Observability

- **Usage by Provider / by Task** — `/admin/pipeline/ai-usage` aggregates `ai_usage_log`.
- **Cost per Template** — attributes spend via subtask substring match. Find templates that cost more than they're worth.
- **Recent Calls** — last 50 `ai_usage_log` rows with full tooltip.
- **Reconciliation** — nightly sync from OpenAI + Anthropic Usage APIs vs local estimates.
- **Quality pipeline logs** — search by `roadmap.quality_pipeline` logger name.

## Schemas & prompts

- [generate_curriculum.txt](backend/app/prompts/generate_curriculum.txt) — generation prompt with level-calibrated weekly load, Bloom's taxonomy, action-verb rules, resource-quality rules.
- [review_curriculum.txt](backend/app/prompts/review_curriculum.txt) — 15-dim scoring rubric.
- [refine_curriculum.txt](backend/app/prompts/refine_curriculum.txt) — surgical rewrite rules; now explicitly honours heuristic-diagnostic `detail` fields.
- [PLAN_TEMPLATE_SCHEMA](backend/app/ai/schemas.py) — structured output schema for generation.
- [QUALITY_REVIEW_SCHEMA](backend/app/ai/schemas.py) — structured output schema for review.

## Thresholds (constants)

Defined in [quality_pipeline.py](backend/app/services/quality_pipeline.py):

```python
SKIP_REVIEW_THRESHOLD = 92    # heuristic above this → skip AI entirely
SKIP_REFINE_THRESHOLD = 8     # per-dim score above this → not considered failing
PRO_THRESHOLD = 3             # total severity above this → consider Pro
REVIEW_CACHE_TTL = 86400*30   # 30 days
MAX_WEEKS_PER_REFINE = 6      # payload cap for refine calls
PUBLISH_THRESHOLD = 90        # admin cannot publish below this
```

Changing any of these shifts the cost/quality tradeoff.

## Estimated per-template cost (current config)

| Scenario | Generation | Review | Refine | Validate | Total |
|---|---|---|---|---|---|
| Happy path (heuristic ≥ 92) | $0.003 | skip | skip | $0 | **~$0.003** |
| Typical (Flash refine, pattern fixes) | $0.003 | $0.003 | $0.002 | $0.00004 | **~$0.008** |
| Heavy refine (Pro) | $0.003 | $0.003 | $0.040 | $0.00004 | **~$0.046** |
| Cache hit on review | $0.003 | **$0** | $0.002 | $0.00004 | **~$0.005** |

Break-even vs Claude: was ~$0.07 per template in the Claude-era heavy-refine path; Gemini Pro brings that to ~$0.046 (~35% cheaper), Flash-only paths are 90%+ cheaper.
