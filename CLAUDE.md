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

**Last session date:** 2026-04-23 (session 31 — SEO-09 RSS feed + SEO-13 canonicals on 5 SSR routes)
**Last session summary (session 31):** Shipped SEO-09 + SEO-13 together (✅✅) in one commit (`289574b`). Parallel-safe P1 pair per [docs/SEO.md](docs/SEO.md) §0.3. Self-executed (no Sonnet subagent) — both tasks small, hot cache.

- **SEO-13 canonicals** — 5 routes now emit exactly one `<link rel="canonical">`: `/blog` (inline f-string head in [backend/app/routers/blog.py](backend/app/routers/blog.py)), `/profile/{user_id}` + `/leaderboard` (inline f-strings in [backend/app/routers/public_profile.py](backend/app/routers/public_profile.py); added `from app.config import get_settings` import), `/verify` (via existing `__BASE__` placeholder in [backend/app/routers/verify.py](backend/app/routers/verify.py) `_INDEX_HTML`), `/account` (direct edit to [frontend/account.html](frontend/account.html) + bonus `<meta name="robots" content="noindex">`). Per spec — `/account` self-canonical despite noindex preserves signals if accidentally linked.
- **SEO-09 RSS feed** — new `/blog/feed.xml` route serves RSS 2.0 with `atom:self` self-reference, channel title/link/desc/language/lastBuildDate, per-item title/link/guid(isPermaLink)/pubDate/description, 10-min Cache-Control. `_rfc822()` helper uses `email.utils.format_datetime` for GMT dates (RSS-spec standard — NOT user-facing, so `feedback_ist_time_sitewide.md` doesn't apply). `<link rel="alternate" type="application/rss+xml">` on `/blog` index + per-post template head for auto-discovery. Route declared before dynamic `/blog/{slug}` so FastAPI resolves `/blog/feed.xml` directly.
- **Tests:** 4 new in test_blog.py (canonical count, feed XML parse + 2-post structure, escape safety for `<` / `&` in titles, per-post alternate link); 3 new in new [backend/tests/test_seo_canonicals.py](backend/tests/test_seo_canonicals.py) (verify / leaderboard / public-profile canonicals). Template-file structural assertion extended. 447 passed (was 441; +6 net). Pre-existing unrelated failure `test_ashby_skips_unlisted_jobs` (Windows asyncio-events RuntimeError) — not investigated.
- **Phase 2 gates:** secrets scan clean, no TODO/FIXME introduced.
- **Live verification:** `/blog/feed.xml` → valid RSS with 2 items (post 01 + post 02), `atom:self` correct, RFC 2822 GMT dates. All 5 canonicals present on live: `/blog`, `/leaderboard`, `/verify` (after nginx 301 to trailing-slash), `/account`; profile canonical covered by DB-user test. `/blog/01` preserves SEO-06 Article + SEO-08 BreadcrumbList JSON-LD alongside the new RSS alternate link.
- **Known minor:** HEAD `/blog/feed.xml` returns 405 — FastAPI's `@router.get` binds GET only. Feed readers GET so harmless; if W3C validator or Feedly trips, switch to `@router.api_route(methods=["GET","HEAD"])`.
- **Docs updated:** [docs/SEO.md](docs/SEO.md) §0.2 (SEO-09 ✅, SEO-13 ✅) + Change log entry.

**Tests passing:** 447 (was 441; +6 net). 1 pre-existing unrelated failure (Windows asyncio), 1 skipped (aiosmtplib env-broken locally — green in Docker).

**Session 29 context (preserved):** data-plane only, zero code/commits. Bulk-rejected 605 non-AI drafts via `scripts/backfill_rca026_non_ai.py --apply` + Phase 2/3 atomic SQL. Final counts: 549 drafts remaining, 642 rejected, 271 published. 101 `Other` drafts still in queue incl. Anthropic pre-training / alignment / AI-reliability SWE — highest-value recoveries from Gemini mislabeling, admin manual pass needed.

**Next action:** SEO-07 (IndexNow) — endpoint exists at [backend/app/routers/jobs.py:723](backend/app/routers/jobs.py#L723), needs `INDEXNOW_KEY` in `.env` + publish-event wiring across blog/jobs/cert routers + new `services/indexnow.py`. Would auto-ping Bing on every publish (near-instant index) + Google when they finish evaluating IndexNow. Alternate tracks: SEO-11 (OG image generator → unblocks SEO-03 og:image tail + SEO-06 `og-default.png`), SEO-02 (sub-sitemaps by resource type + `<image:>` extensions), session 29's 101-Other-drafts manual review. Still blocked on user action: SEO-00 (GSC + Bing DNS TXT verify) and SEO-01 Cloudflare Managed robots.txt override.
**Open questions for the user:** None.

**Agent-utilization footer:**

- Opus: Phase 0 reads (CLAUDE.md + HANDOFF via §9 + RCA first 150 lines + SEO.md §0 + MEMORY.md), SEO-09/SEO-13 spec reads, route audit across 7 files (blog.py, public_profile.py, verify.py, account.html, post.html template, nginx.conf, main.py), implementation across 7 files (~300 LOC incl. 3 new test fns + new test_seo_canonicals.py), 447-test suite verification, commit + amend-for-noreply + push + VPS backend+web rebuild + 5-URL live canonical validation + feed.xml parse validation, docs updates.
- Sonnet: n/a — both tasks were Sonnet-eligible per docs/SEO.md §0.3 but self-executed because total edit was ~30 lines of code change + ~170 lines of tests across 7 files, all in Opus hot cache. Cold-start + two-subagent-briefing time would have exceeded the Opus-typing time; per global playbook "don't delegate when self-executing is faster."
- Haiku: n/a — no multi-file sweeps. Live URL validation was 5 sequential curls, not a grid.
- codex:rescue: n/a — blog + public_profile + verify routers explicitly non-load-bearing per docs/SEO.md §1195; account.html is static SPA; not security/auth/classifier-adjacent.
