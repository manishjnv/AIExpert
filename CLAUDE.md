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

**Last session date:** 2026-04-16 (session 13)
**Last session summary (session 13):** Jobs module quality, reliability, India expansion, and observability. 8 commits on master, all live on VPS. Full detail in [docs/SESSION_13_LOG.md](docs/SESSION_13_LOG.md). **Source expansion:** 12 → 25 boards (added PhonePe, Groww on Greenhouse; CRED, Mindtickle on Lever; new Ashby ATS module with 9 boards including Sarvam AI — India AI lab). All 25 probed live. **Early-expiry:** 3-mechanism closed loop — `missing_streak ≥ 2` for source-removed roles (2-day grace), `valid_through < today` flip (was render-only, now status flip), slug-probe auto-disable after 3 consecutive failures. **Summary card:** LLM-generated `data.summary` (headline_chips, comp_snapshot, responsibilities, must_haves, benefits, watch_outs) with 4-block color-coded render; Opus-via-Max worker pattern (`/summarize-jobs` slash command, export + import scripts, version-stamped prompt at `app/prompts/jobs_summary_claude.txt`); rule-based de-fluffer (`app/services/jobs_readable.py`) as fallback chain. **Bugfixes:** module grounding (`_get_module_slugs` → `list_published()` instead of phantom `PlanVersion.status`); API-key redaction filter (`app/logging_redact.py`); `/api/stats` route shadow. **Quality loop:** rejection feedback injected into enrichment prompt per source; per-source `publish_rate_45d` + `top_reject_reasons_45d` in admin stats table with color-coded chips. **Admin UX:** preview links on every queue row; city filter on both admin + public; expired-tab sub-filter (source_removed vs date_based); highlights grid + structured skills block on job detail page.
**Key commits (session 13):** cd82152 (auto-expire missing), bc3deb7 (expired sub-filter), 252563c (city filter + locations), 5cd32f8 (preview + highlights), 7550c19+983da2b+cc32dcc (JD de-fluffer), 5b3f310 (summary card + backfill), 792d4df (India + Ashby + probe + date-expiry), 5abda91 (Opus worker), 32c7511 (module fix + redaction), 5d7ed0f (feedback + publish-rate).
**Tests passing:** 210 (+1 skipped on weasyprint-less hosts)
**Tests failing:** 0
**Blockers:** None.

**Prior session 12 summary:** AI Jobs module — built, deployed, scheduled, brand-matched. 20 commits on master. `jobs`+`job_sources`+`job_companies` tables; daily ingest (Greenhouse + Lever, per-source cap 30, concurrency 4); Gemini Flash enrichment; admin `/admin/jobs` with filter bar + bulk-publish; public `/jobs` SSR + JobPosting JSON-LD; match-% v2; weekly digest; unified scheduler. 177 passing.

**Prior session 11 summary:** Complete blog publishing system. JSON pipeline + Claude Max editorial flow. Zero backend AI spend.

**Next action:** (1) **Rotate Gemini API key** — leaked in session transcript, redaction filter prevents future leaks but old key must be rotated. (2) **Admin to review + publish drafts** at `/admin/jobs` (4 of 752 published). Run `/summarize-jobs --status draft --limit 50` before publishing to upgrade summary quality. (3) **Cost optimization** — implement Phase 14 in TASKS.md: prompt caching (§14.1), pre-filter non-AI titles (§14.2), tier enrichment (§14.3), cap JD 4000 (§14.4), drop Flash summary (§14.5). Projected savings: $18/mo → $3/mo. (4) Submit `sitemap_index.xml` to Google Search Console if not done. (5) Set `INDEXNOW_KEY` in `.env`. (6) Deferred: admin revoke UI for certs; Tier-2 leaderboard features.
**Open questions for the user:** None.
