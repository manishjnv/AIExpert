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

## 8. Session state (update at end of each session)

> Claude Code: rewrite everything below this line at the end of every session. Keep it under 30 lines. This is what the next session reads to know where you left off.

**Last session date:** 2026-04-14 (session 12)
**Last session summary (session 12):** AI Jobs module — built, deployed, scheduled, brand-matched. 20 commits on master, all live on VPS. Full detail in [docs/SESSION_12_LOG.md](docs/SESSION_12_LOG.md). Shape: `jobs`+`job_sources`+`job_companies` tables (migration c8e2d15a3f97); daily ingest (11 Greenhouse + 1 Lever, per-source cap 30, concurrency 4, SQLite lock retry/backoff, hash dedup, fail-open enrichment); Gemini Flash enrichment with enum-locked schema; admin `/admin/jobs` with filter bar (search/company/designation/remote/country/verified-only), status tabs, bulk-publish Tier-1 gate, 24h stats strip; public `/jobs` + `/jobs/<slug>` SSR with JobPosting JSON-LD + sticky sidebar + pinned search + wide 1440px layout; **match-% v2** = 0.5×modules+0.3×skills+0.2×level (modules-overlap from published-template skill-token index, returns `gap_weeks[]` + `skills_without_curriculum[]`); **close-the-gap CTA** linked missing-skill weeks + Enroll button; **weekly digest** (Mon 09:00 IST, opt-in via `email_notifications`, top-5 matches dedup'd, signed JWT one-click unsub at `/api/profile/digest/unsubscribe`); **unified scheduler** `scripts/scheduler.py` replaces `quarterly_sync_scheduler` (daily + weekly + quarterly as asyncio tasks). 7 of 10 original GH slugs + 4 of 5 Lever slugs were 404; probed + replaced with Anthropic, Scale, Databricks, xAI, DeepMind, Cerebras, SambaNova, Together, Moveworks, Figure, Inflection, Mistral. Brand shell (nav.css + Fraunces/IBM Plex) on all 3 jobs pages; Jobs link in main topnav + footer + admin subnav. Four memory entries added (sqlite writer sessions, scripts init_db, nginx allowlist, jobs module). 62 new tests across 6 files; **177 total passing** (was 127). Live VPS: 19/19 endpoint probes green; 149 jobs staged (146 draft + 3 published); scheduler shows next runs 2026-04-14 23:00 UTC / 2026-04-20 03:30 UTC / 2026-07-01 02:00 UTC.
**Key commits (session 12):** 6148c1e (skeleton), 0d0d9d8 (filters + match v1), 67be49b (Lever + IndexNow + sitemap_index), d44dcce (27 tests), 2c01aa6/07e33b0 (nginx), 3b1e912 (per-row commits), 7b27c5c (retry/backoff + stats strip), 976eba0 (real slugs + cap + concurrency), 8309931 (brand shell), 880b228 (nav links), 4260d0d (location/exp chips), 95ba95c (15 filter tests), cd167a3 (wide layout + sticky search), b8fff3c (admin filter bar), 7870ea4 (match v2 + digest + gap CTA), 034891c (unified scheduler).

**Prior session 11 summary:** Complete blog publishing system. JSON pipeline: admin titles → `/admin/blog` generates Claude Opus prompt with 25-item self-check → paste into Claude.ai Max (Opus 4.6) → downloadable JSON artifact → upload (file picker or paste) → ~25-check validator (schema + 45-pattern banned-terms scan + voice heuristics) → save draft → full-field editor with hero image upload to `/data/blog/assets/` → preview at `/admin/blog/<slug>/preview` with amber banner → publish (stamps reviewer + date) → live at `/blog/<slug>`. Public: `/blog` index with empty-state, `/blog/<slug>` with 720px reading width + 300px sticky sidebar (More posts + auto-built Contents TOC with scroll-spy + LinkedIn/X share) + bottom prev/next cards + More-posts grid + breadcrumb. Blog link in main topnav + footer + admin subnav. Legacy post-01 has non-destructive hide-flag at `/data/blog/_legacy.json`. Three docs: `docs/blog/{STYLE,ADMIN_GUIDE,SYSTEM}.md`. Chat prompt updated so mentor knows blog + leaderboard + certificates. Zero backend AI spend — Claude Max does the writing, backend only validates + renders.
**Key commits (session 11):** 073ae5d, 5a2c1af, d7a392d, c8c7ac4, 67c5c46, 2f40884, c6c2f59, 24a8311, cc6de9a, dfdf2ee, 38f93f0.

**Prior session 9 summary:** Survival-mode shipping — 4 highest-leverage items from the session-8 post-mortem. **T1 (aef7a17):** auto-publish disabled site-wide. `publish_template()` now requires `admin_name`; auto_publish=true on manual upload is accepted for back-compat but template stays draft. Every publish stamps `last_reviewed_on` + `last_reviewed_by` into `_meta.json`; Templates admin page shows "reviewed YYYY-MM-DD by <name>" under the badge. 6 tests in test_publish_gate.py. **T2 (5de7fd0):** Coursera affiliate URL rewriter. New `app/services/affiliate.py` + `COURSERA_AFFILIATE_ID` env var (default empty = no-op). On authenticated plan endpoints only, coursera.org/{learn,specializations}/* URLs get `?irclickid=<affiliate_id>-<16hex>` appended. Idempotent, urlparse-safe, deepcopy. NOT applied on public_profile/share/verify. 12 unit tests. **T4 (61c847b + 6d975fc):** fixed 7 failing tests. test_ai mocks now patch `app.ai.gemini.complete` / `app.ai.groq.complete` (provider uses dynamic __import__). test_plans::re_enroll switches templates. test_plans + test_e2e_smoke migrate tests expect 204 guardrail. test_certificates_e2e skips PDF render on hosts without cairo/pango. `.github/workflows/ci.yml` added: Python 3.12, Ubuntu, cairo/pango apt, pytest on push-to-master + every PR. **T5 (731e0bc):** blog post `docs/blog/01-building-automateedge-solo.md` (~1500 words) + new `/blog/01` route in `app/routers/blog.py` with OG/Twitter meta. Footer link inserted between Leaderboard and Verify Credential. README rewritten with real pitch, screenshot placeholders, contribution instructions. All 5 commits on master, deploys pending (user-driven).

**Prior session 8 summary (2026-04-13):** Certificate polish + site-wide gamification + brand push. Cert flow: PDF weasyprint 62.3→63.1+pydyf 0.11 (PDF bug); nginx `/verify/` proxy added; empty-state on /account; render fixes (28mm stat gap, drop "0 repos" body + Projects stat, no-cache headers, /verify paste-form at /verify with URL pasting accepted, footer link to `/verify`); modules + per-module chips on verify HTML; module titles line on PDF. Leaderboard gamified: XP (task=10, repo=50, cert 500/750/1000, +20/streak-week), 7 tiers Apprentice→AI Guru with colored chips + progress bar to next, achievement pills (First Task, Triple Crown, Honors, 5/15 Repos, 4w/10w streak), TOP % badge, full-width layout, Last Active column, distinct-repo count, "Studying: X · Month N of M" subtitle + "Between courses"/"New learner" fallbacks, collapsible help legend. Brand: nav wordmark "AutomateEdge" + "AI Learning Roadmap" tagline (plan dropped from nav). Global footer in nav.js (DOMContentLoaded deferred to avoid top-of-page bug) — Contact link preserves existing modal→POST /api/contact→Resend pipeline via `/#contact` hash. Scroll-top button redesigned amber + pulse halo. Collapsible week cards (completed default collapsed), 2-col resource grid (video vs docs+practice, URL-regex classified), 2-col checklist, status pills. New `summary` field on PlanTemplate (backfilled + generator prompts updated); `6 resources/week, 3 video + 3 non-video` mandated in both prompts. Chat system prompt now personalised by experience_level + learning_goal. `--ink-soft` contrast 2.4:1→7:1 for WCAG AA. SMTP_FROM_NAME + contact subject changed to "AutomateEdge".
**Tests passing:** 177 (+1 skipped on weasyprint-less hosts)
**Tests failing:** 0
**Blockers:** None.
**Next action:** (1) Admin to review + publish more drafts at `/admin/jobs` (only 3 of 149 published). (2) Submit `https://automateedge.cloud/sitemap_index.xml` to Google Search Console. (3) Set `INDEXNOW_KEY` in VPS `.env` (`openssl rand -hex 16`) + restart backend to enable Bing/Yandex pings on publish. (4) Re-verify Greenhouse/Lever board slugs quarterly (Anthropic/Scale/Databricks/xAI/DeepMind/Cerebras/SambaNova/Together/Moveworks/Figure/Inflection + Mistral on Lever). (5) Deferred from session 9: admin revoke UI for certs; Tier-2 leaderboard features.
**Open questions for the user:** None.
