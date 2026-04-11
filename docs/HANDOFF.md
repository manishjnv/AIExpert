# Handoff

> This file is rewritten at the end of every session. Read after CLAUDE.md.

## Current state as of 2026-04-12 (session 4)

**Last worked on:** AI quality pipeline, Gemini cost optimizations, Claude refinement, admin UI readability, quality scoring engine
**Branch:** master
**Live site:** https://automateedge.cloud

## What got done this session (2026-04-12, session 4)

### AI Quality Pipeline (Generate → Review → Refine → Validate)
- `quality_pipeline.py`: full orchestration — generate via free providers, cross-model AI review (Gemini), surgical Claude refinement, heuristic validation
- Improved generation prompt: Bloom's taxonomy, action verbs, theory-practice split, resource diversity, completeness, level calibration
- Review prompt: 10-dimension quality audit (Bloom's, theory-practice, project density, assessment, completeness, difficulty, industry, freshness, prerequisites, readiness)
- Refine prompt: surgical week fixes with exact schema requirements
- Skip logic: skip review if score ≥ 85, skip refine if all dims ≥ 7, Claude only if ≥ 3 dims fail
- Auto-revert if refinement regresses quality score
- Wired into `curriculum_generator.py` with `quality_check=True` flag

### Gemini Cost Optimizations
- Context caching: system instructions in `systemInstruction` field, auto-cached across calls
- Right-sized tokens: per-task maxOutputTokens (chat=1024, triage=512, generation=8192)
- Right-sized timeouts: generation=90s, review=60s, chat=30s
- Structured output: `responseSchema` support ready (guarantees valid JSON)
- Task parameter passed from provider.py to Gemini for right-sizing

### Claude Integration
- `ai/anthropic.py`: Messages API client with prompt caching (`cache_control: ephemeral`)
- Used ONLY for quality pipeline refinement (not in fallback chain)
- System prompt cached for ~90% input token discount on repeated calls

### Quality Scoring Engine
- `quality_scorer.py`: 5 heuristic dimensions (structure, resources, checklist, progression, links)
- API: `GET /admin/pipeline/api/quality` (all templates) and `GET /admin/pipeline/api/quality/{key}` (single)
- Visual table on Pipeline page with per-dimension bar charts, detail stats, issues

### Admin UI Readability Fix
- Fixed 37 instances of unreadable `#4a5260` color → `#8a92a0` across 3 files
- Fixed 31 instances of tiny `10px/11px` font → `12px` across 3 files
- Global CSS: body line-height 1.6, paragraph color `#b0aaa0`, table cell color `#d0cbc2`
- Pipeline Settings: full-width layout, 3-column grid

### Pipeline Stages Reference
- 10 stages with AI markers (gold "AI" label + token cost estimates)
- Color-coded: Gold=cleanup, Blue=AI enrichment, Green=process, Red=maintenance

## Credentials status

| Credential | Status |
|-----------|--------|
| SMTP (Resend) | Verified, DKIM active |
| Gemini | On VPS, context caching enabled |
| Groq | On VPS, max_tokens bumped to 4096 |
| Cerebras | On VPS, llama3.1-8b |
| Mistral | On VPS, JSON code block parsing |
| DeepSeek | 402 insufficient balance |
| Sambanova | On VPS, 4096 max_tokens |
| Anthropic | On VPS, prompt caching, refinement only |

## Tests

**Passing:** 88 (2 repo tests flaky from GitHub API rate limit)

## Key files created/changed this session

| File | Change |
|------|--------|
| `backend/app/ai/anthropic.py` | NEW — Claude API client with prompt caching |
| `backend/app/ai/gemini.py` | REWRITTEN — 5 cost optimizations |
| `backend/app/ai/provider.py` | Passes task to Gemini for right-sizing |
| `backend/app/services/quality_pipeline.py` | NEW — Generate→Review→Refine→Validate |
| `backend/app/services/quality_scorer.py` | NEW — 5-dimension heuristic scoring |
| `backend/app/services/curriculum_generator.py` | Wired with quality pipeline |
| `backend/app/prompts/generate_curriculum.txt` | REWRITTEN — Bloom's, action verbs, completeness |
| `backend/app/prompts/review_curriculum.txt` | NEW — 10-dimension review rubric |
| `backend/app/prompts/refine_curriculum.txt` | NEW — surgical week fix prompt |
| `backend/app/routers/pipeline.py` | Quality API, normalization merged, stages, readability |
| `backend/app/routers/admin.py` | Dashboard/Users separation, readability |

## CRITICAL: Known issue — template volume mount

Generated templates are stored inside the container at `/app/app/curriculum/templates/`.
They are LOST on every `docker compose up --build`. Need to add a volume mount in
`docker-compose.yml` to persist templates across rebuilds. This is the #1 priority for next session.

## Next session priorities

1. **Fix template volume mount** — add volume in docker-compose.yml
2. **Run full generation cycle** with quality pipeline active
3. **Implement 10 new heuristic scoring dimensions** (Bloom's, theory-practice, etc.)
4. **Claude Batch API** for bulk refinement (50% discount)
5. **Gemini structured output schemas** for PlanTemplate
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
