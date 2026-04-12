# Handoff

> This file is rewritten at the end of every session. Read after CLAUDE.md.

## Current state as of 2026-04-12 (session 5)

**Last worked on:** Template persistence, 15-dim scorer, quality gate, proposals page, clickable admin, content lifecycle
**Branch:** master
**Live site:** https://automateedge.cloud

## What got done this session (2026-04-12, session 5)

### 1. Template Volume Mount (CRITICAL fix)
- `docker-compose.yml`: `./data/templates:/app/app/curriculum/templates` volume for backend + cron
- `Dockerfile`: seed templates layer + startup seeding logic
- Templates now persist across container rebuilds

### 2. Quality Scorer — 15 Dimensions (was 5)
- 10 new heuristic dimensions (all regex, zero AI cost): Bloom's progression, theory/practice ratio, project density, assessment quality, completeness, difficulty calibration, industry alignment, freshness, prerequisites clarity, real-world readiness
- Scorer calibration: Bloom's strips "Reviewed:" prefixes, project keywords include checks, completeness adjusted for specialized topics, links excluded when unchecked, plateau threshold relaxed
- Pipeline quality table shows all 15 bar charts

### 3. Quality Gate — Publish Model
- `_meta.json` manifest tracks draft/published status per template
- User-facing `/api/templates` returns published only (score >= 90)
- 3 generalist templates grandfathered (always published)
- Publish/Unpublish buttons on Pipeline quality table
- Templates admin page: Status + Quality + Subscribers columns

### 4. Gemini 2.5 Migration
- Model updated from `gemini-2.0-flash-lite` (deprecated) to `gemini-2.5-flash`
- Thinking disabled (`thinkingBudget: 0`), multi-part response handling, code block extraction
- All providers bumped to 8192 max_tokens + 60s timeout for generation

### 5. Content Lifecycle (Proposals + Auto-unpublish)
- Proposals page (`/admin/pipeline/proposals`): view, approve, reject quarterly sync proposals
- Auto-unpublish: content refresh unpublishes templates when AI currency score < 40
- Refine Existing button on Pipeline page: runs AI review+refine on templates below 90

### 6. Clickable Admin (Templates + Topics)
- Template detail page (`/admin/templates/{key}`): full curriculum view with months, weeks, resources, deliverables, checklists
- Template names clickable in Templates table + Pipeline quality table
- Topic detail modal: full justification, evidence sources, approve/reject buttons
- Workflow banner on Topics page explaining the pipeline

### 7. UI Fixes
- Restored connection badges (GitHub/LinkedIn/Google) in nav — lost during unified nav refactor
- Fixed "Loading plan..." stuck — `planBadge` element was missing, crashing eyebrow update
- Badges left-aligned next to logo

### 8. Claude Batch API + Gemini Structured Schemas
- `ai/anthropic.py`: `create_batch()`, `poll_batch()`, `get_batch_results()`
- `ai/schemas.py`: `PLAN_TEMPLATE_SCHEMA` + `QUALITY_REVIEW_SCHEMA` (disabled pending Gemini 2.5 testing)
- Batch refinement: `create_batch_refinement()` + `apply_batch_results()` for 50% discount on 5+ items

## Credentials status

| Credential | Status |
|-----------|--------|
| Gemini | gemini-2.5-flash on VPS, thinking disabled |
| Groq | On VPS, 8192 max_tokens |
| Cerebras | On VPS, 8192 max_tokens |
| Mistral | On VPS, 8192 max_tokens |
| Sambanova | On VPS, 8192 max_tokens |
| DeepSeek | 402 insufficient balance |
| Anthropic | On VPS, prompt caching + batch API, refinement only |
| SMTP (Resend) | Verified, DKIM active |

## Tests

**Passing:** 88 (2 repo tests flaky from GitHub API rate limit)

## Templates on disk (5)

| Template | Composite Score | Status |
|----------|----------------|--------|
| generalist_12mo_beginner | 89 | Published (grandfathered) |
| generalist_6mo_intermediate | 92 | Published (grandfathered) |
| generalist_3mo_intermediate | 89 | Published (grandfathered) |
| multimodal_few_shot_learning_3mo_intermediate | 87 | Draft |
| multimodal_few_shot_learning_3mo_beginner | 87 | Draft |

## Topics (12 in DB)

- 10 generated (errors cleared, ready for re-generation later)
- 1 pending (Agentic AI and Tool-Using LLMs)
- Topic #5 (Adversarial Robustness) was the only clean 5/5 generation

## Session 6 additions (2026-04-12)

### OpenAI embeddings for semantic topic dedup
- New: `backend/app/ai/openai_embeddings.py` — `embed()`, cosine sim, pack/unpack float32 vectors, cache 90d, cost-limit gate
- New: `backend/app/ai/pricing.py` — central price table, `compute_cost()`, `check_cost_limit()`, `CostLimitExceeded`
- New migration `f9b2c3d47a18`: adds `discovered_topics.embedding` (LargeBinary) + `ai_cost_limit` table
- Dedup now 2-stage: exact normalized_name → semantic cosine ≥0.88 via `text-embedding-3-small`
- Config: `OPENAI_API_KEY`, `OPENAI_EMBEDDING_MODEL=text-embedding-3-small`, `topic_dedup_similarity_threshold=0.88`

### AI Usage admin widget (cost + caps)
- `/admin/pipeline/ai-usage` now shows Today / 7d / 30d cost cards
- Per-provider cost column in usage table
- Per-call cost in Recent Calls table
- New "Daily Cost Caps" form — admin can set `daily_cost_usd` + `daily_token_limit` per provider (or `*` for all models)
- Endpoints: `POST /api/ai-usage/set-limit`, `POST /api/ai-usage/delete-limit`
- Caps enforced via `check_cost_limit()` inside paid-provider clients (currently wired into `openai_embeddings.embed()`)

### Needs follow-up
- Wire `check_cost_limit("anthropic", model)` into `app.ai.anthropic.complete()` before API call
- After `docker compose exec backend alembic upgrade head` runs the new migration, admin can configure caps live

## Next session priorities

1. **Re-run generation** for topics with missing variants (when rate limits allow)
2. **Approve topic #11** (Agentic AI) and generate
3. **Run Content Refresh** to check links + currency scores
4. **Test Gemini structured output schemas** with 2.5-flash
5. **Wire batch refinement into admin UI** — button when 5+ templates below threshold
6. **URL validation during generation** — catch hallucinated URLs before saving

---

## Session history

| Date | Summary |
|------|---------|
| 2026-04-10 | Phases 1-12 built, tested, deployed. OAuth, OTP, PDF, admin. |
| 2026-04-10 | Launch: OAuth fix, email config, docs, credential setup. |
| 2026-04-11 | AI features, nav/UX, email reminders, leaderboard, blueprints. |
| 2026-04-11 | P1 pipeline, P2 UX, security hardening, unified nav, account page. |
| 2026-04-11 | P1 live test, 4 new AI providers, Resend email, AI usage dashboard. |
| 2026-04-12 | AI quality pipeline, Gemini optimizations, Claude refinement, scoring engine. |
| 2026-04-12 | Template persistence, 15-dim scorer, quality gate, proposals, clickable admin. |
