# Handoff

> This file is rewritten at the end of every session. It is the first thing the next session reads after CLAUDE.md. Keep it short. If you write more than 50 lines, you are writing a diary — this is a handoff.

## Current state as of 2026-04-10

**Last worked on:** Phase 2 complete (Tasks 2.1–2.4)
**Branch:** master
**Commit:** df17e2f

## What got done this session

- 2.1: async DB engine (db.py) with WAL + foreign_keys pragmas, init_db/close_db lifecycle, get_db() dependency
- 2.2: All 10 ORM models matching DATA_MODEL.md with PrimaryKey + Timestamp mixins
- 2.3: Alembic wired to Base.metadata, initial migration generated and verified
- 2.4: /api/learner-count wired to real DB query (SELECT count(*) FROM users), 60s cache
- Dockerfile updated to include tests/ and pytest.ini
- Deployed to VPS — had to fix /srv/roadmap/data/ permissions (chmod 777) for container's app user

## What is in progress (not committed)

- Nothing

## Decisions made

- data/ dir on VPS needs 777 permissions since container runs as non-root `app` user
- Tests use in-memory SQLite with StaticPool for async compatibility
- Module-level engine/session_factory are None until init_db() — import via `app.db` module reference

## Tests

**Passing:** 5 automated (test_db: insert/read, WAL, FK; test_models: create_all, FK enforcement)
**Failing:** none
**New tests added:** tests/test_db.py (3), tests/test_models.py (2)

## Blockers

- None

## Open questions for the user

- None

## Next action

Phase 3 Task 3.1 from docs/TASKS.md — JWT helpers (issue_token, verify_token, revoke).

---

## Session history (append-only, short)

| Date       | Phase.Task | Summary                                                    |
|------------|------------|------------------------------------------------------------|
| 2026-04-10 | Phase 1    | Structure flatten, doc fixes, Phase 1 complete (1.1-1.5)   |
| 2026-04-10 | Phase 2    | DB engine, ORM models, Alembic migration, learner count    |
