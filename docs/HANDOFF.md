# Handoff

> This file is rewritten at the end of every session. It is the first thing the next session reads after CLAUDE.md. Keep it short. If you write more than 50 lines, you are writing a diary — this is a handoff.

## Current state as of 2026-04-10

**Last worked on:** Phase 1 complete (Tasks 1.1–1.5)
**Branch:** master
**Commit:** see git log

## What got done this session

- Flattened starter-kit/ to repo root (was causing path mismatches)
- Added .gitattributes for LF line endings
- Fixed docker-compose.yml (removed deprecated version key)
- Fixed requirements.txt (httpx-mock -> pytest-httpx, removed unused passlib)
- Fixed cross-doc inconsistencies (deliverable_met, DELETE body, task assignments)
- Phase 1 complete: FastAPI app, config, /api/health, /api/learner-count, Dockerfile, compose, nginx, frontend
- Added HTTPException handler matching API_SPEC error format
- Verified locally: docker compose up -> all endpoints return expected responses, frontend loads

## What is in progress (not committed)

- Nothing

## Decisions made

- Local Docker is for testing only; production deployment target is VPS (72.61.227.64)
- VPS port 8080 is taken by AccessBridge — must use a different port when deploying
- Caddy (ti-platform) handles TLS on 80/443 — add a Caddyfile entry for the roadmap subdomain

## Tests

**Passing:** Manual — /api/health, /api/learner-count, frontend at /, 404 error format
**Failing:** n/a
**New tests added:** none (Phase 1 has no automated tests per TASKS.md)

## Blockers

- None

## Open questions for the user

- None

## Next action

Phase 2 Task 2.1 from docs/TASKS.md — async DB engine setup with WAL mode and foreign keys pragma.

---

## Session history (append-only, short)

| Date       | Phase.Task | Summary                                                    |
|------------|------------|------------------------------------------------------------|
| 2026-04-10 | Phase 1    | Structure flatten, doc fixes, Phase 1 complete (1.1-1.5)   |
