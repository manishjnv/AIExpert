# Handoff

> This file is rewritten at the end of every session. It is the first thing the next session reads after CLAUDE.md. Keep it short. If you write more than 50 lines, you are writing a diary — this is a handoff.

## Current state as of 2026-04-10

**Last worked on:** Phase 7 complete (Tasks 7.1–7.7)
**Branch:** master
**Commit:** see git log

## What got done this session

- 7.1: Secret sanitizer (filename exclusion + content pattern matching + redaction)
- 7.2: Gemini client (REST API, free tier, JSON response mode)
- 7.3: Groq fallback client (same interface as Gemini)
- 7.4: Provider router (Gemini → Groq fallback with exponential backoff)
- 7.5: Evaluation service (GitHub content fetch, sanitize, prompt, AI call, store)
- 7.6: POST /api/evaluate + GET /api/evaluations endpoints with 24h cooldown
- 7.7: Frontend evaluation UI (Evaluate button, loading state, score gauge, strengths/improvements)
- Codex security review completed

## What is in progress (not committed)

- Nothing

## Decisions made

- Prompt template at backend/app/prompts/evaluate.txt (not in code)
- Max 10 files, 8000 chars each sent to AI for evaluation
- Binary/image files excluded from content fetch
- 24h cooldown per repo per user for evaluations

## Tests

**Passing:** 69 automated
**Failing:** none
**New tests:** test_ai (15 — sanitizer + provider mocked + fallback)

## Blockers

- None

## Open questions for the user

- None

## Next action

Phase 8 Task 8.1 from docs/TASKS.md — AI chat (SSE endpoint).

---

## Session history (append-only, short)

| Date       | Phase.Task | Summary                                                    |
|------------|------------|------------------------------------------------------------|
| 2026-04-10 | Phase 1    | Structure flatten, doc fixes, Phase 1 complete (1.1-1.5)   |
| 2026-04-10 | Phase 2    | DB engine, ORM models, Alembic migration, learner count    |
| 2026-04-10 | Phase 3    | Full auth: JWT, Google OAuth, OTP, cleanup, me/logout      |
| 2026-04-10 | Phase 4    | Plan templates, enrollment, progress, migration, FE sync   |
| 2026-04-10 | Phase 5    | Profile CRUD, plan picker UI, 3 templates (3mo/6mo/12mo)   |
| 2026-04-10 | Phase 6    | GitHub repo linking — client, endpoints, frontend UI       |
| 2026-04-10 | Phase 7    | AI evaluation — sanitizer, Gemini/Groq, eval service, UI   |
