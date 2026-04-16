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

**Last session date:** 2026-04-16 (session 17 — Waves 1–5 #18 complete + admin docs)
**Last session summary (session 17):** Shipped 10-layer AI-classification defense system eliminating the LLM-as-law-degree class of false positives. Total: **268 historical false positives backfilled**, **426/426 backend tests passing**, **115 new tests** in `test_jobs_cost_opt.py`. Full developer reference at [docs/JOBS_CLASSIFICATION.md](docs/JOBS_CLASSIFICATION.md); admin-facing sections #7+#8 added to `/admin/jobs-guide`.

- **RCA-026** (prior session): foundation 4-layer fix. 141 rows backfilled.
- **Wave 1** (`4792d8f`): +50 title patterns (21 new "needs AI knowledge but isn't AI" categories), `_TOPIC_ANCHORS` map, `_enforce_topic_anchors`, `_enforce_designation_topic_consistency`, SELF-REJECTION prompt block. +86 rows.
- **Wave 2** (`a4dee0a`): three-tier weighted intensity scoring (`_AI_STRONG`/`_MEDIUM`/`_WEAK`), word-boundary regex, per-JD dedup, `_strip_company_boilerplate`. Threshold=5. +2 rows.
- **Wave 3** (`2255064`, `e36078e`): non-AI cluster expansion (sales/marketing/recruiting/design/finance/IT/creative/policy), `_neutralize_requirement_phrases` ("experience with ML"), `is_bare_verb_title` gate. +39 rows.
- **Wave 4** (`fc9ed5c`, `fc670bc`): `check_source_rejection_rates` auto-disable >40% reject; AI-intensity histogram in `/admin/jobs/api/summary-stats`; **Opus audit via Claude Code** — weekly cron picks 1% Tier-1 published, admin sees amber banner with COPY PROMPT button, pastes into VS Code Claude Max ($0 spend), POSTs verdicts to `/api/audit-submit`.
- **Wave 5 #18** (`1610cee`): evidence-span topic validation — Gemini must cite JD substring for each topic; validator verifies in-JD + checks per-topic forbidden patterns (LLB→LLM, workplace safety→Safety, user research→Research, AI-powered→Applied ML). Backwards-compat with old string[] format.
- **Wave 5 #19** (two-stage classifier): NOT shipped — cost-benefit unfavorable post-Waves 1–5; revisit only if Wave 4 observability surfaces new failure patterns.
- **Post-cleanup** (`4a79082`): RCA-027 structural fix — migrated 313-line `_JOBS_GUIDE_HTML` f-string to Jinja2 template (`backend/app/templates/admin/jobs_guide.html`); legacy f-string fully removed (no compat shim); 4 new tests; bumped `PROMPT_VERSION` to `2026-04-16.2` queuing 966 rows for editorial-uplift via `/summarize-jobs` (Claude Max, $0 API spend); HANDOFF.md cleaned of stale carry-overs.

**Tests passing:** 431 backend tests. **Tests failing:** 0 new (1 pre-existing unrelated `test_skills_with_no_curriculum_match` fails on parent commits too).
**Blockers:** None. All work shipped, deployed (HEAD `4a79082`), tested, documented.

**Next action:** (1) **Measure for 1–2 weeks** — Wave 4 #14/15/16 surface drift automatically; admin reviews Opus audit weekly. (2) If new patterns emerge, revisit Wave 5 #19 or extend an existing layer per [docs/JOBS_CLASSIFICATION.md](docs/JOBS_CLASSIFICATION.md) "Adding a new defense layer". (3) Optional editorial uplift: `/summarize-jobs` to regenerate the 966 stale-version summaries via Claude Max ($0 spend, manual paste cycle). (4) Tiny outstanding admin chores (no blockers): submit sitemap to GSC, set `INDEXNOW_KEY` in `.env`.
**Open questions for the user:** None.
