# Handoff

> This file is rewritten at the end of every session. Read after CLAUDE.md.

## Current state as of 2026-04-12 (session 5)

**Last worked on:** Template volume persistence, 15-dimension quality scorer, Gemini structured output schemas, Claude Batch API
**Branch:** master
**Live site:** https://automateedge.cloud

## What got done this session (2026-04-12, session 5)

### 1. Template Volume Mount (CRITICAL fix)
- `docker-compose.yml`: Added `./data/templates:/app/app/curriculum/templates` volume for both backend and cron services
- `Dockerfile`: Added seed template copy to `/app/seed_templates`, startup logic seeds empty volume from built-in templates
- `data/templates/`: Seeded with 3 generalist templates locally
- **Result:** Generated templates now persist across container rebuilds

### 2. Quality Scorer — 15 Dimensions (was 5)
- `quality_scorer.py`: Added 10 new heuristic dimensions (all regex, zero AI cost):
  - Bloom's taxonomy progression (verb classification across months)
  - Theory-to-practice ratio (resource URL/name classification)
  - Project density (deliverable keyword analysis)
  - Assessment quality (measurable outcome detection)
  - Completeness (essential topic coverage by level)
  - Difficulty calibration (cliff/plateau detection)
  - Industry alignment (modern tool coverage)
  - Freshness (deprecated tech detection)
  - Prerequisites clarity (dependency chain validation)
  - Real-world readiness (portfolio/production markers)
- Updated composite weights to distribute across 15 dimensions (content > infrastructure)

### 3. Gemini Structured Output Schemas
- `ai/schemas.py`: NEW — defines `PLAN_TEMPLATE_SCHEMA` and `QUALITY_REVIEW_SCHEMA` in Gemini's OpenAPI format
- `provider.py`: Passes `PLAN_TEMPLATE_SCHEMA` to Gemini when task=generation (guarantees valid JSON shape, eliminates retry loops)
- `quality_pipeline.py`: Passes `QUALITY_REVIEW_SCHEMA` to Gemini review calls

### 4. Claude Batch API (50% discount)
- `ai/anthropic.py`: Added `create_batch()`, `poll_batch()`, `get_batch_results()` for Message Batches API
- `quality_pipeline.py`: Added `create_batch_refinement()` and `apply_batch_results()` for bulk refinement
- Threshold: 5+ items triggers batch mode (otherwise individual calls)

## Credentials status

| Credential | Status |
|-----------|--------|
| SMTP (Resend) | Verified, DKIM active |
| Gemini | On VPS, context caching + structured output enabled |
| Groq | On VPS, max_tokens bumped to 4096 |
| Cerebras | On VPS, llama3.1-8b |
| Mistral | On VPS, JSON code block parsing |
| DeepSeek | 402 insufficient balance |
| Sambanova | On VPS, 4096 max_tokens |
| Anthropic | On VPS, prompt caching + batch API, refinement only |

## Tests

**Passing:** 88 (2 repo tests flaky from GitHub API rate limit)

## Key files created/changed this session

| File | Change |
|------|--------|
| `docker-compose.yml` | Template volume mount for backend + cron |
| `backend/Dockerfile` | Seed templates layer + startup seeding logic |
| `backend/app/services/quality_scorer.py` | 10 new scoring dimensions (15 total) |
| `backend/app/ai/schemas.py` | NEW — Gemini structured output schemas |
| `backend/app/ai/provider.py` | Wire generation schema to Gemini |
| `backend/app/services/quality_pipeline.py` | Review schema + batch refinement API |
| `backend/app/ai/anthropic.py` | Batch API (create, poll, results) |

## Next session priorities

1. **Deploy to VPS** — `git pull && docker compose up -d --build` (seed templates auto-created)
2. **Run full generation cycle** on live: discovery → approve → generate with quality pipeline
3. **Verify quality scores** in admin UI with new 15-dimension scorer
4. **Wire batch refinement into admin UI** — "Batch Refine" button when 5+ templates below threshold
5. **URL validation during generation** — catch hallucinated URLs before saving
6. **Admin UI for batch status** — show batch progress, apply results

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
| 2026-04-12 | Template persistence, 15-dim scorer, Gemini schemas, Claude Batch API. |
