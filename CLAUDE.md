# CLAUDE.md — Project Memory for Claude Code

> **Claude Code: read this file at the start of every session.** It is the single source of truth for what this project is, how it is structured, and how to work on it. Update the "Session state" section at the end of every session before you hand off.

## 1. Project identity

**Name:** AI Roadmap Platform
**Purpose:** A web platform that gives anyone a personalized, AI-curated 3-to-12-month study plan to learn AI from scratch. Users track their progress, link their practice work via GitHub, get AI-powered evaluations of their repositories, and share milestones on LinkedIn. The curriculum auto-refreshes every 3 months by pulling trending topics from top universities and practitioner sources.

**Why it exists:** Existing roadmaps (roadmap.sh, coursera, etc.) are static, one-size-fits-all, and get stale within months in the AI field. This platform stays current and gives personal feedback.

**Audience:** Working developers, CS students, and career changers who want a serious, accountable study plan.

## 2. Current status

**Phase:** 0 — planning complete, scaffolding ready, no application code written yet.
**What exists:** This repo with documentation and config scaffolding. A working static tracker HTML (`frontend/index.html` from earlier iteration) is the visual starting point for the frontend.
**What does not exist yet:** Everything in `backend/app/` beyond `main.py` and `config.py`. All API endpoints. All frontend integration with the backend. All AI integrations. All GitHub integration.

**Next thing to build:** See `docs/TASKS.md` → Phase 1.

## 3. Tech stack (chosen, do not change without discussion)

- **Backend:** Python 3.12 + FastAPI + SQLAlchemy 2.0 + SQLite (async via aiosqlite)
- **Auth:** Authlib for Google OAuth2; custom email OTP via SMTP; JWT sessions (httpOnly cookies)
- **Frontend:** Vanilla JS + ES modules, incrementally built on top of the existing single-file tracker. No SPA framework unless explicitly decided.
- **AI integration:** Google Gemini API (free tier) primary, Groq free tier fallback. No paid APIs.
- **GitHub integration:** GitHub OAuth App + direct REST calls via httpx
- **Database:** SQLite file at `/data/app.db` (mounted volume), migrations via Alembic
- **Deployment:** Docker Compose on a VPS, behind the user's existing reverse proxy
- **Email:** Brevo free tier (300 emails/day) or Resend free tier (3,000/month) via SMTP

**Rationale for each choice lives in `docs/ARCHITECTURE.md`.** Don't re-debate these unless something is genuinely blocking.

## 4. Repository layout

```
.
├── CLAUDE.md                  ← you are here, read first every session
├── README.md                  ← human overview
├── .env.example               ← template; real .env is git-ignored
├── .gitignore
├── docker-compose.yml         ← full stack: backend + nginx + cron
├── docs/
│   ├── PRD.md                 ← product requirements (what to build)
│   ├── ARCHITECTURE.md        ← technical architecture (how it fits together)
│   ├── DATA_MODEL.md          ← database schema
│   ├── API_SPEC.md            ← REST endpoints
│   ├── TASKS.md               ← phased backlog with acceptance criteria
│   ├── HANDOFF.md             ← living session state (update each session)
│   ├── SECURITY.md            ← security rules, threat model, checklist
│   ├── AI_INTEGRATION.md      ← free AI provider setup + prompts
│   └── DEPLOYMENT.md          ← VPS deployment workflow
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py            ← FastAPI entrypoint (skeleton exists)
│       ├── config.py          ← env-driven settings (skeleton exists)
│       ├── db.py              ← async SQLAlchemy session (not yet)
│       ├── models/            ← ORM models (not yet)
│       ├── routers/           ← API routers per resource (not yet)
│       ├── services/          ← business logic (not yet)
│       ├── auth/              ← OAuth + OTP + JWT (not yet)
│       └── ai/                ← Gemini/Groq wrappers (not yet)
├── frontend/
│   └── index.html             ← starting point; progressively enhanced
├── scripts/
│   └── quarterly-sync.py      ← curriculum refresh cron (stub exists)
└── pb_hooks/                  ← reserved; currently unused
```

## 5. Critical rules for Claude Code

These are non-negotiable. If a rule conflicts with a user request, surface the conflict and ask — do not silently violate.

1. **Never commit secrets.** Anything that looks like a key, token, password, client secret, webhook URL with embedded auth, or personal identifier goes in `.env`, never in code. Before every `git commit`, grep the staged diff for the strings `sk-`, `gh[pousr]_`, `AIza`, `GOCSPX`, `smtp`, `password`, `secret`, `key=`. If you find any, stop and ask the user.

2. **No placeholder secrets that look real.** Use obvious placeholders like `YOUR_KEY_HERE` or `changeme` — never realistic-looking random strings that someone might assume are real leaked credentials.

3. **SQLAlchemy ORM only.** Never construct SQL via string concatenation. Never use `text()` with user input. Always parameterize.

4. **Every endpoint that mutates state requires authentication.** The only unauthenticated endpoints are: `GET /` (frontend), `GET /api/health`, `GET /api/learner-count`, `POST /api/auth/google/callback`, `POST /api/auth/otp/request`, `POST /api/auth/otp/verify`, and static assets. Everything else checks `current_user` via the JWT dependency.

5. **Rate limit every auth endpoint.** OTP request, OTP verify, Google callback — all rate limited per IP via slowapi. Defaults: 5 requests / 15 minutes for OTP request.

6. **Use async throughout.** FastAPI + async SQLAlchemy + httpx (not requests). Never block the event loop. No sync DB calls inside endpoint handlers.

7. **AI evaluation never reveals secrets.** When sending a GitHub repo summary to an LLM, strip any file that looks like an env file, a config with keys, or a secrets file before sending. There is a helper for this in `backend/app/ai/sanitize.py` (to be built in Phase 4) — use it.

8. **Keep the frontend runnable standalone.** The single `frontend/index.html` must still work when opened directly from the filesystem in "local-only" mode, exactly like the original tracker. Progressive enhancement only — never break the fallback.

9. **Do not invent new dependencies without checking.** The approved dependency list lives in `backend/requirements.txt`. If you think you need a new package, ask first. Keep the footprint tight — this runs on a small VPS.

10. **Update `docs/HANDOFF.md` at the end of every session.** This is how the next session (yours or another developer's) knows where to resume.

11. **Read `docs/RCA.md` at the START of every session** before writing any code. Scan the most recent 5 entries and the "Patterns to watch for" table at the bottom — they encode real mistakes this codebase has already paid for. After fixing any bug or security defect, add a new numbered entry with symptom / root cause / fix (with file+line link) / prevention rule, and update the pattern table if the failure mode is new.

12. **Follow the orchestration playbook in §8** for any change touching 2+ files or any path flagged load-bearing (`backend/app/ai/`, `backend/app/auth/`, `jobs_ingest/`, `jobs_enrich/`, `backend/alembic/versions/`). Generic phases + routing live in the global `~/.claude/CLAUDE.md`; this repo's overlay is §8 below. Use `/orchestrate` to trigger Phase 0 explicitly.

## 6. Quick commands

```bash
# Local dev
docker compose up -d                              # bring the stack up
docker compose logs -f backend                    # tail backend logs
docker compose exec backend alembic upgrade head  # run migrations
docker compose exec backend pytest                # run tests

# Deploy (when ready)
git push origin main                              # triggers webhook / manual pull on VPS
ssh vps "cd /srv/roadmap && git pull && docker compose up -d --build backend"
```

## 7. Working style

- **Small, reviewable changes.** One feature slice per session, not sprawling rewrites.
- **Write the test first when the logic is non-trivial.** Skip tests for throwaway UI polish.
- **Ask before deleting files.** Never delete a file you did not create in the same session without explicit approval.
- **Prefer editing over rewriting.** If a file exists and works, extend it; don't replace it wholesale.
- **When a spec doc is ambiguous, propose an interpretation, then update the doc.** Don't silently choose.

## 8. Orchestration playbook (project overlay)

The generic playbook — routing table, Phase 0–6 flow, hard rules — lives in `~/.claude/CLAUDE.md` (global). This section is the repo-specific overlay. When a rule here conflicts with the global playbook, **this one wins**. Trigger the full flow explicitly with `/orchestrate`.

### Phase 0 reads (exact paths for this repo)

In the Phase 0 parallel-tool-call burst, read all five in one message:

- `CLAUDE.md` (this file)
- `docs/HANDOFF.md`
- `docs/RCA.md` — first ~150 lines (recent entries + the "Patterns to watch for" table at the bottom)
- `docs/SEO.md` — §0 only, first ~100 lines (trigger conditions + task status board + next action). Load deeper sections on-demand when §0.1 trigger conditions apply to the current session's work.
- `C:\Users\manis\.claude\projects\e--code-AIExpert\memory\MEMORY.md`

### Load-bearing paths (require Opus diff review + worktree isolation)

Any Sonnet/Haiku subagent editing these paths MUST be spawned with `isolation: "worktree"`, and you MUST review the diff line-by-line in Phase 3:

- `backend/app/ai/` — provider clients, prompt construction, sanitizer (secrets-stripping before LLM send)
- `backend/app/auth/` — Google OAuth, email OTP, JWT, session cookies, rate limiting
- `jobs_ingest/` and `jobs_enrich/` — the 10-layer classifier defense (see [docs/JOBS_CLASSIFICATION.md](docs/JOBS_CLASSIFICATION.md))
- `backend/alembic/versions/` — schema migrations (irreversible in prod)
- Anything that constructs or edits an **AI enrichment / evaluation prompt** — never regenerate these from scratch without explicit user approval (prompts are tuned assets, not boilerplate)

### Memory entries to actively consult (do not re-derive)

Before proposing changes in the relevant area, pull the matching memory entry from `MEMORY.md`:

- **Classifier work** → `feedback_classification_bias.md` (false-positives never acceptable; don't propose Wave 5 #19 without drift evidence)
- **Long-running DB writes** → `feedback_sqlite_writer_sessions.md` (commit per row; WAL clash with live backend)
- **New HTTP route** → `feedback_nginx_allowlist_on_new_routes.md` (update `nginx.conf` in same PR)
- **Editorial AI output** → `feedback_opus_for_editorial.md` (Flash can't match Opus editorial quality; tiered strategy)
- **Any new logger/httpx caller** → `feedback_redact_api_keys.md` (install `_redacting_filter` at entrypoints)
- **Deployments** → `feedback_deploy_rebuild.md` (`restart` doesn't pick up code; build + force-recreate)
- **Standalone scripts** → `feedback_scripts_need_init_db.md` (call `init_db()` / `close_db()` explicitly)
- **SEO work** (any `<head>` / sitemap / robots / JSON-LD / nginx SEO directive / new public route / blog publish / OG image) → `reference_seo_plan.md` → full plan at `docs/SEO.md`. Any task in the `SEO-00..SEO-26` set governed by that doc. Do not free-style schema or ship ad-hoc SEO changes — follow the sequenced tasks.

### Phase 6 exit — this repo specifically

- Rewrite the `## 9. Session state` section below (≤30 lines)
- If a bug was fixed, append a numbered entry to `docs/RCA.md` and update its pattern table if the failure mode is new
- Do **not** `git commit` without explicit user approval (per §5 rule on risky actions)
- If AI enrichment prompts were touched, confirm with the user before overwriting — tuned prompts are never regenerated without approval

## 9. Session state (update at end of each session)

> Claude Code: rewrite everything below this line at the end of every session. Keep it under 30 lines. This is what the next session reads to know where you left off.

**Last session date:** 2026-04-23 (session 34 — SEO-10 SSR jobs hub pagination)
**Last session summary (session 34):** Shipped SEO-10 end-to-end (`1d40c2d`) + docs. Live on VPS.

- **SEO-10 — /jobs?page=N.** [backend/app/routers/jobs.py](backend/app/routers/jobs.py) `jobs_index` now accepts `page: int = Query(1, ge=1, le=1000)`. Single COUNT(*) query → total_pages. Out-of-range → 404, ≤0/non-int → 422. Page-1 canonicals to `/jobs` (no query string) so it doesn't compete with `/jobs?page=1`; page-2+ canonical to `/jobs?page=N`. `<link rel="prev">` / `<link rel="next">` in `<head>` when applicable; prev at page=2 points to `/jobs` (matches canonical). `<title>` + description gain "Page N of M" on subpages for unique SERP snippets. Footer `<nav class="pagination">` renders numbered links with ellipsis (`_paginate_numbers` helper — small totals return all, large bracket current ±2 with 1 / ellipsis / … / total). Current page rendered as `<strong aria-current="page">`.
- **JS hydration guard.** When `?page=` is in URL, `_HUB_JS` skips the auto-`loadJobs()` call on mount — SSR-rendered cards stay visible until user applies a filter. Prevents Googlebot-visible SSR from being overwritten by the JS default 7-day filter.
- **Sitemap enumeration.** [backend/app/routers/seo.py](backend/app/routers/seo.py) `sitemap-pages.xml` now includes `/jobs?page=2..total_pages` (priority 0.6) alongside canonical `/jobs`. Never includes `page=1` (would alias the canonical).
- **CSS** — `.pagination` styles added to `_HUB_CSS`. Dark bg, gold-accent current page, mono font per site design system; responsive wrap.
- **Tests (+10)** in new [backend/tests/test_jobs_pagination.py](backend/tests/test_jobs_pagination.py). SSR: canonical rules, rel=prev/next, page-bounds → 404/422, title uniqueness. UI: footer visible multi-page, hidden single-page. Sitemap: enumerates page 2..N, excludes page=1. Helper unit tests for `_paginate_numbers`.
- **Live verification:** 271 published jobs → 6 pages. `/jobs` (page 1): no rel=prev, rel=next → page 2. `/jobs?page=6` (last): rel=prev → page 5, no rel=next, title "Page 6 of 6". `/jobs?page=99` → GET 404. `/jobs?page=0` → GET 422. Sitemap: 6 jobs URLs (canonical + 5 paginated).
- **nginx:** no change — `location = /jobs` is exact-match; query strings proxy through.
- **Phase 2 gates:** secrets scan clean, no TODO/FIXME introduced. No load-bearing paths touched.

**Tests passing:** 490 local (was 480; +10 net). Same pre-existing `test_ashby_skips_unlisted_jobs` Windows asyncio failure, 1 skipped (aiosmtplib env-broken locally).

**Session 33 (preserved):** sticky off_topic rejection ([jobs_ingest.py:_stage_one](backend/app/services/jobs_ingest.py) early-return when `existing.status='rejected' AND reject_reason='off_topic'`) + prod data slim (636 tombstones → `data='{}'`, reclaimed 4.98 MB). 549 draft / 642 rejected / 271 published. 101 `Other` drafts still in admin queue (session 29 carry-over).

**Still blocked on user action:** (1) Cloudflare Managed robots.txt override (SEO-01), (2) GSC/Bing 7-day baseline data (SEO-00 🟡), (3) 101 Other drafts admin triage.

**Next action:** SEO-12 (`EducationalOccupationalCredential` JSON-LD on `/verify/{id}`) — last standalone P1 schema task. Alternates: SEO-15 (FAQPage on roadmap, P2 but easy rich-result) · SEO-19 (10 programmatic `/vs/{a}-vs-{b}` pages, content-heavy) · session 29's 101-Other-drafts manual triage.
**Open questions for the user:** None.

**Agent-utilization footer:**

- Opus: Phase 0 reads (CLAUDE.md + HANDOFF via §9 + SEO.md §0 + MEMORY.md — RCA not re-read, session 33 entry fresh), SEO-10 spec read, jobs.py handler audit (60-250 + 795-985), seo.py + nginx.conf + _HUB_JS review, implementation (jobs.py +80 LOC core + pagination helper + CSS + JS guard, seo.py +8 LOC, test_jobs_pagination.py +197 LOC, 10 new tests), 490-test suite verification, commit + noreply-amend + push, VPS git pull + backend rebuild + 9-URL live validation (canonical rules × 3 pages, edge cases × 3, sitemap parse).
- Sonnet: n/a — straightforward spec, all edits in hot cache (jobs.py already warm from sessions 32 + session 31 canonicals work, seo.py warm from session 32 Track B). Per global playbook "don't delegate when self-executing is faster."
- Haiku: n/a — live validation was 6 sequential curls + 3 GET code checks, not a multi-source grid.
- codex:rescue: n/a — no load-bearing path touched. `routers/jobs.py` SSR + query param handling is non-security; COUNT query is a single ORM expression (no SQL concatenation per §5 rule 3); canonical logic is pure string arithmetic.
