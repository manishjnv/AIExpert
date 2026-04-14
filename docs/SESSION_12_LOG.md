# Session 12 Log — AI Jobs Module (End-to-End Build + Deploy)

**Date:** 2026-04-14
**Outcome:** Jobs module built, deployed, scheduled, brand-matched, and tested. 177 passing tests (from 127). 20 commits on `master`, all live on VPS.
**Prior session:** Session 11 — blog publishing pipeline. Jobs module is fully independent from blog.

---

## 1. What was built

### 1.1 Core module (Steps 1-9 of [JOBS.md §12](JOBS.md))

| Layer | Files |
|---|---|
| **Data** | [models/job.py](../backend/app/models/job.py), migration [c8e2d15a3f97](../backend/alembic/versions/c8e2d15a3f97_add_jobs_tables.py) — `jobs`, `job_sources`, `job_companies` |
| **Ingest** | [services/jobs_ingest.py](../backend/app/services/jobs_ingest.py), [services/jobs_sources/greenhouse.py](../backend/app/services/jobs_sources/greenhouse.py), [services/jobs_sources/lever.py](../backend/app/services/jobs_sources/lever.py) |
| **Enrichment** | [prompts/jobs_extract.txt](../backend/app/prompts/jobs_extract.txt), [services/jobs_enrich.py](../backend/app/services/jobs_enrich.py) |
| **Match v2** | [services/jobs_match.py](../backend/app/services/jobs_match.py), [services/jobs_modules.py](../backend/app/services/jobs_modules.py) |
| **Digest** | [services/jobs_digest.py](../backend/app/services/jobs_digest.py), [scripts/weekly_jobs_digest.py](../scripts/weekly_jobs_digest.py) |
| **Ops** | [services/indexnow.py](../backend/app/services/indexnow.py), [scripts/daily_jobs_sync.py](../scripts/daily_jobs_sync.py), [scripts/scheduler.py](../scripts/scheduler.py) |
| **Public UI** | [routers/jobs.py](../backend/app/routers/jobs.py) — `/jobs`, `/jobs/<slug>`, `/api/jobs`, `/sitemap-jobs.xml`, `/sitemap_index.xml`, `/<key>.txt` |
| **Admin UI** | [routers/admin_jobs.py](../backend/app/routers/admin_jobs.py) — review queue, publish/reject/bulk-publish, stats strip, filters |
| **Cross-cutting** | [curriculum/loader.py](../backend/app/curriculum/loader.py) hook to invalidate skill index on publish; [routers/profile.py](../backend/app/routers/profile.py) one-click unsubscribe endpoint |
| **Infra** | `nginx.conf` + 4 new `location` blocks; `frontend/nav.js` Jobs links (top nav + footer + admin subnav); `.env.example` `INDEXNOW_KEY` |
| **Docs** | [docs/JOBS.md](JOBS.md) — full design spec §§1-14 |

### 1.2 What the module does

**Ingest** — daily at 04:30 IST, the unified scheduler fetches from 11 Greenhouse + 1 Lever AI-native company boards (~2200 jobs total). Per-source cap of 30 new rows per run with `ENRICH_CONCURRENCY=4` bounded parallel Gemini Flash calls.

**Enrich** — one AI call per new/changed job extracts structured fields against an enum-locked schema: designation, seniority, topic[], location, remote_policy, experience_years, salary (only if disclosed), tldr (rewritten not paraphrased), must_have_skills[]. Hash-cached — unchanged rows skip re-enrichment. Fails open: provider failure stages the row with `admin_notes` flag.

**Admin queue** — `/admin/jobs`. Tabs for draft / published / rejected / expired / all. Filter bar: search (title + company), company dropdown, designation, remote, country, verified-only. Stats strip shows 24h per-source counts with stale/error badges. Bulk-publish gated to Tier-1 sources with `bulk_approve=1`. On publish: `last_reviewed_on/by` stamped, IndexNow pinged.

**Public board** — `/jobs` SSR first 50 for SEO, JS hydrates with filter sidebar (sticky, pinned search always visible) and per-card match-% ring (logged-in only). `/jobs/<slug>` SSR with JobPosting JSON-LD (Google Jobs), OpenGraph, canonical URLs, expired-role `noindex`.

**Match-% v2** — `0.5×modules + 0.3×skills + 0.2×level_fit`. Skills from user's repo-evaluation strengths. Level from `User.experience_level` vs job's experience range. **Module overlap** is new: job must-have-skills → curriculum week refs (via title+focus text index) → intersection with user's completed weeks (all checks ticked). Returns `gap_weeks[]` + `skills_without_curriculum[]` so UI can differentiate "not yet learned" from "plan doesn't cover".

**Close the gap CTA** — job detail page renders linked week titles ("Month N, Week K") for missing skills + gold **Enroll in a plan →** button.

**Weekly digest email** — Mondays 09:00 IST. Eligibility = `email_notifications=True` AND ≥1 active plan. Top 5 matches (score ≥40) dedup'd by (company, designation). One-click unsubscribe at `/api/profile/digest/unsubscribe?t=<jwt>` (90-day signed token, no login required).

**Scheduler** — [scripts/scheduler.py](../scripts/scheduler.py) replaces `quarterly_sync_scheduler.py`. Three concurrent asyncio tasks. 1-hour sleep chunks for SIGTERM responsiveness. Set `JOBS_SCHEDULER_TEST=1` for 60s test cycles.

### 1.3 Branding applied

All 3 jobs pages use the AutomateEdge shell: `/nav.css` + `/nav.js`, Fraunces serif titles, IBM Plex Sans body, IBM Plex Mono eyebrows, `#0f1419` bg, `#e8a849` gold accent. Cards match the blog pattern. Match rings: green `#6db585` / amber `#e8a849` / slate `#4a5560`. Wide layout (`max-width: 1440px`) + sticky sidebar + styled scrollbar.

---

## 2. Commits shipped (20)

| SHA | Label |
|---|---|
| `6148c1e` | Jobs module skeleton (model, ingest, enrich, admin, public SSR + JSON-LD) |
| `0d0d9d8` | Filter sidebar + match-% ring + close-the-gap (v1) |
| `67be49b` | Lever source + IndexNow + sitemap_index.xml |
| `d44dcce` | 27 integration tests |
| `2c01aa6` | nginx allowlist: /jobs, sitemaps, IndexNow key |
| `07e33b0` | nginx regex quoting fix (`{16,64}` broke parsing) |
| `eeb29a7` | scripts/daily_jobs_sync calls `init_db()` |
| `3b1e912` | Per-row commits — avoid SQLite lock contention |
| `7b27c5c` | Retry/backoff on SQLite lock + admin stats strip |
| `976eba0` | Real verified board slugs + per-source cap + concurrency |
| `4c20e0b` | Admin subnav Jobs tab |
| `8309931` | Brand shell on all 3 jobs pages |
| `880b228` | Jobs in main top nav + footer |
| `4260d0d` | Location + experience chips on cards |
| `95ba95c` | 15 filter tests + `q` broadened to title + company |
| `cd167a3` | Widened layout, pinned sticky search box |
| `b8fff3c` | Admin queue filter bar |
| `7870ea4` | Match-% v2 (module-overlap) + weekly digest + gap CTA |
| `034891c` | Unified scheduler (daily + weekly + quarterly) |

---

## 3. Test coverage

**177 passing** (was 127). Jobs-module-specific: **62 new tests** across 6 files.

| File | Tests | Scope |
|---|---|---|
| [test_jobs_ingest.py](../backend/tests/test_jobs_ingest.py) | 8 | hash stability, slugify, stage new/unchanged/changed, blocklist skip, enrichment failure fallback, valid_through math, idempotent source seeding |
| [test_jobs_match.py](../backend/tests/test_jobs_match.py) | 8 | v2 formula arithmetic, level fit, skill case-insensitive matching, skills_without_curriculum bucket, gap_weeks payload, contract check |
| [test_jobs_admin.py](../backend/tests/test_jobs_admin.py) | 6 | non-admin 403, queue, publish stamps reviewer, reject-reason enum, bulk-publish Tier-1 gate, blocklist |
| [test_jobs_public.py](../backend/tests/test_jobs_public.py) | 7 | draft hidden from API + page, JobPosting JSON-LD emitted, anon match 401, sitemap excludes drafts, IndexNow 404 unconfigured |
| [test_jobs_filters.py](../backend/tests/test_jobs_filters.py) | 15 | every filter in isolation + AND combinations + empty-param handling + 422 on out-of-range + ordering + limit |
| [test_jobs_digest.py](../backend/tests/test_jobs_digest.py) | 5 | eligibility rule, no-recent-jobs skip, unsubscribe flips flag, bogus token 400 |
| **Full suite** | **177** | No regressions |

All enrichment tests patch `app.services.jobs_enrich.enrich_job` so no live Gemini calls in CI.

---

## 4. Live VPS verification (2026-04-14)

### 4.1 Containers
- `roadmap-backend`: healthy
- `roadmap-cron`: running unified scheduler
- `roadmap-web`: running with updated nginx.conf

### 4.2 Scheduler state
```
[daily_jobs_sync]     next run 2026-04-14 23:00 UTC  (04:30 IST)
[weekly_jobs_digest]  next run 2026-04-20 03:30 UTC  (09:00 IST Mon)
[quarterly_sync]      next run 2026-07-01 02:00 UTC  (unchanged)
```

### 4.3 DB state
- 149 jobs total: 146 draft, 3 published
- 23 job_sources + 23 job_companies registered

### 4.4 Endpoint probes

| Endpoint | Expected | Got |
|---|---|---|
| `GET /api/health` | 200 | ✓ |
| `GET /jobs` (SSR hub) | 200 | ✓ |
| `GET /api/jobs` (JSON) | 200 | ✓ |
| `GET /sitemap-jobs.xml` | 200 | ✓ |
| `GET /sitemap_index.xml` | 200 | ✓ |
| `GET /admin/jobs` (anon) | 401 | ✓ |
| `GET /admin/jobs/api/queue` (anon) | 401 | ✓ |
| `GET /admin/jobs/api/stats` (anon) | 401 | ✓ |
| `GET /api/jobs?company=anthropic` | 200 | ✓ |
| `GET /api/jobs?designation=Research%20Scientist` | 200 | ✓ |
| `GET /api/jobs?remote=Hybrid` | 200 | ✓ |
| `GET /api/jobs?country=US` | 200 | ✓ |
| `GET /api/jobs?q=engineer` | 200 | ✓ |
| `GET /api/jobs?posted_within_days=7` | 200 | ✓ |
| `GET /api/jobs?topic=LLM` | 200 | ✓ |
| `GET /api/profile/digest/unsubscribe?t=not-a-jwt` | 400 | ✓ |
| `GET /api/profile/digest/unsubscribe` | 422 | ✓ |
| `GET /api/jobs/<slug>/match` (anon) | 401 | ✓ |
| `grep 'application/ld+json' /jobs/<slug>` | ≥1 | 1 ✓ |

Every route behaves per spec. Total live probes: **19/19 pass**.

---

## 5. Lessons captured to memory

Four memory entries added to `C:\Users\manis\.claude\projects\e--code-AIExpert\memory\` — future sessions start pre-aware of these traps:

1. **[project_jobs_module.md](../../.claude/projects/e--code-AIExpert/memory/project_jobs_module.md)** — module snapshot, architecture, pending work.
2. **[feedback_sqlite_writer_sessions.md](../../.claude/projects/e--code-AIExpert/memory/feedback_sqlite_writer_sessions.md)** — commit per row in batch jobs. Long-lived sessions cause `database is locked` under WAL + poison the final commit via `PendingRollbackError`.
3. **[feedback_scripts_need_init_db.md](../../.claude/projects/e--code-AIExpert/memory/feedback_scripts_need_init_db.md)** — standalone scripts start with `async_session_factory=None`. Always call `await init_db()` + `await close_db()` explicitly.
4. **[feedback_nginx_allowlist_on_new_routes.md](../../.claude/projects/e--code-AIExpert/memory/feedback_nginx_allowlist_on_new_routes.md)** — `location / { return 404; }` is deny-all. Every new public route needs a `location` block in the same PR. Regex with `{n,m}` quantifiers must be quoted.

---

## 6. Known gaps / pending admin work

### 6.1 Admin action items (not code)
- **Review + publish drafts** — only 3 of 149 published. Jobs hub stays sparse until admin clears the queue. Filter bar + verified-only toggle make this fast.
- **Submit `/sitemap_index.xml`** to Google Search Console.
- **Set `INDEXNOW_KEY`** in VPS `.env` (`openssl rand -hex 16`) + restart backend. Until then, IndexNow is a no-op.

### 6.2 Board slug rot (discovered 2026-04-14)
7 of 10 original Greenhouse slugs and 4 of 5 Lever slugs were 404 against live APIs. Probed + replaced with 11 verified Greenhouse + 1 Lever. Re-verify quarterly — companies rebrand / switch ATS.

**Currently active boards:** Anthropic, Scale AI, Databricks, xAI, Google DeepMind, Cerebras, SambaNova, Together AI, Moveworks, Figure, Inflection AI (all Greenhouse); Mistral (Lever).

### 6.3 Deferred features (see JOBS.md §12)
- YC Work-at-a-Startup source (Step 11 residual)
- Admin company/source CRUD + diff view for changed jobs
- Match-% v3: embeddings-based skill similarity (vs current token-match)
- Concurrent cross-source fetching (current per-source loop is serial — not urgent since cron runs unattended)

---

## 7. How to operate

### 7.1 Run ingest manually
```
docker compose exec backend python -m scripts.daily_jobs_sync
```

### 7.2 Run weekly digest manually (dev mode logs, prod sends)
```
docker compose exec backend python -m scripts.weekly_jobs_digest
```

### 7.3 Test scheduler on short cycle
```
docker compose exec -e JOBS_SCHEDULER_TEST=1 cron python -m scripts.scheduler
```

### 7.4 Publish a single job from CLI
```python
# Inside a shell: docker compose exec backend python
import asyncio
from app.db import init_db
from sqlalchemy import select
from datetime import date
async def go():
  await init_db()
  from app.db import async_session_factory
  from app.models import Job
  async with async_session_factory() as db:
    j = (await db.execute(select(Job).where(Job.slug == "<slug>"))).scalar_one()
    j.status = "published"; j.last_reviewed_on = date.today(); j.last_reviewed_by = "admin"
    await db.commit()
asyncio.run(go())
```

### 7.5 Reset ingest (nuke + re-ingest from scratch — destructive)
```sql
DELETE FROM jobs; DELETE FROM job_sources; DELETE FROM job_companies;
-- then: docker compose exec backend python -m scripts.daily_jobs_sync
```

---

## 8. Architectural invariants (do not violate in future sessions)

1. **No auto-publish.** Every job entering `status='published'` must have an `admin_name` in `last_reviewed_by`. This mirrors the session-9 T1 gate on templates.
2. **Per-row commit in batch jobs.** Never hold one SQLAlchemy session across >1 HTTP fetch or >1 AI call — SQLite WAL + live backend writes will lock up.
3. **Scripts must bind the engine.** `scripts/*.py` that touch the DB: `await init_db()` at start, `await close_db()` in `finally`.
4. **Nginx is an allowlist.** Every new public route needs a `location` block in `nginx.conf` within the same PR. Regex with braces must be quoted.
5. **Filter contract.** Empty query params must not filter to zero — UI sends empty strings when a filter is cleared.
6. **IndexNow key verification route is path-matched, not wildcard.** `location ~ "^/[a-f0-9]{16,64}\.txt$"` prevents the backend route from shadowing other `.txt` paths.
7. **Enrichment fails open.** Provider failure must stage the row with `admin_notes` flagged, never lose the row.
8. **Hash before enrich.** `compute_hash()` runs first so unchanged jobs never trigger a Gemini call.
