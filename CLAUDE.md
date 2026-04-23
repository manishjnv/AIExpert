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

**Last session date:** 2026-04-23 (session 32 — HEAD-accept + SEO-11 OG generator + SEO-02 sub-sitemaps + SEO-07 IndexNow wiring + INDEXNOW_KEY VPS provision)
**Last session summary (session 32):** Three tracks shipped and deployed in sequence (`89af6fa`, `2860011`, `b91c45e`). User pre-approved "all 3" after the plan was stated. Live on VPS (backend + web rebuilt).

- **Track A — HEAD-accept fix** (`89af6fa`). Flipped `@router.get` → `@router.api_route(methods=["GET","HEAD"])` on `/sitemap_index.xml` + `/sitemap-jobs.xml` + `/blog/feed.xml`. Some third-party SEO validators (and possibly Bing Webmaster) probe with HEAD before GET; previous binding returned 405. +3 tests.
- **Track C — SEO-11 OG image generator** (`2860011`). New `backend/app/services/og_render.py` + `backend/app/routers/og.py`. Routes: `/og/course/generalist.png`, `/og/roadmap/{track}.png` (generalist/ai-engineer/ml-engineer/data-scientist), `/og/blog/{slug}.png`, `/og/jobs/{slug}.png`. 1200×630 PNG, dark `#0f1419` / gold `#e8a849` / bone `#e8e4d8`, DejaVu Sans via `fonts-dejavu-core` already in Dockerfile — no host-font dep. Disk cache at `/data/og-cache/{type}/{id}.png` with `X-Cache: HIT` on second request. `Pillow==11.0.0` added explicitly (was transitively via `qrcode[pil]`). Meta-tag wiring: `frontend/index.html` → `/og/course/generalist.png` + `twitter:card=summary_large_image`; blog index + per-post Article → `/og/blog/{slug}.png`; jobs hub + per-job → `/og/jobs/{slug}.png`. nginx regex `^/og/(course|roadmap|blog|jobs)/[a-z0-9][a-z0-9-]{0,120}\.png$`. +14 tests. Deferred per spec: `/og/week/*` (awaits SEO-04), `/og/vs/*` (awaits SEO-19), `/og/cert/*` (existing PDF pipeline).
- **Track B — SEO-02 sub-sitemap split** (`b91c45e`). New `backend/app/routers/seo.py` with 4 children: `/sitemap-blog.xml`, `/sitemap-pages.xml`, `/sitemap-certs.xml`, `/sitemap-profiles.xml`. `/sitemap_index.xml` now lists all 5 children with per-entry `<lastmod>`. Existing `/sitemap-jobs.xml` extended with `xmlns:image` + `<image:image>` per job. All 271 jobs carry their `/og/jobs/*.png` reference. `sitemap-profiles.xml` strictly gated on `User.public_profile=True` (pytest enforces — SEO-02 acceptance #5). `sitemap-certs.xml` excludes `revoked_at IS NOT NULL`. nginx regex `^/sitemap-(jobs|blog|pages|certs|profiles)\.xml$` replaces literal `sitemap-jobs.xml` block. +7 tests.
- **Track D — SEO-07 IndexNow activation** (`d34a22d`). VPS `.env` gained `INDEXNOW_KEY=da644d9738c272503eb10a09c1feb9d7` via root SSH (user authorized "you have access to ssh do it"); `/da644d9738c272503eb10a09c1feb9d7.txt` verified live. Jobs publish/bulk-publish already called `ping_async` from session 12; this track added the two missing paths: `backend/app/routers/admin.py` POST `/admin/api/blog/publish` → pings `/blog/{slug}`, `backend/app/services/certificates.py` `check_and_issue` new-cert branch → pings `/verify/{credential_id}` (upgrade branch skipped — URL already pinged on initial issue). `ping_async` no-ops silently when key empty, so CI/dev safe. +7 tests in `backend/tests/test_indexnow.py` (unit: noop branches + payload shape + 4xx/network-error swallow; wiring: blog publish + cert issue trigger ping with correct URL).
- **Phase 2 gates:** secrets scan clean all 3 commits, no TODO/FIXME introduced.
- **Live verification:** `/sitemap_index.xml` → 5 children with 2026-04-23 lastmod. `/sitemap-pages.xml` → 4 URLs, home carries `<image:image>` for course OG. `/sitemap-jobs.xml` → 271 URLs, 271 with `<image:image>`. HEAD on `/sitemap_index.xml` + `/blog/feed.xml` → 200. OG cards: course (31KB), blog/01 (40KB), roadmap/generalist (29KB), a live jobs slug (36KB) — all `image/png`, 1200×630 confirmed via Pillow.
- **Docs updated:** [docs/SEO.md](docs/SEO.md) §0.2 (SEO-02 ✅, SEO-03 ✅, SEO-11 ✅).

**Tests passing:** 480 local (was 447; +33 net: 3 HEAD + 14 OG + 7 sub-sitemap + 7 IndexNow + 2 adjacent pickups). Same pre-existing failure `test_ashby_skips_unlisted_jobs` (Windows asyncio), 1 skipped (aiosmtplib env-broken locally — green in Docker).

**Session 29 context (preserved):** 101 `Other` drafts still in admin queue incl. Anthropic pre-training / alignment / AI-reliability SWE — admin manual pass needed.

**Still blocked on user action:**
1. Cloudflare Managed robots.txt override (SEO-01)
2. GSC + Bing sitemap submission ✅ done 2026-04-23; 7-day baseline still pending data (SEO-00 remains 🟡)
3. 101 "Other" drafts admin-queue triage (session 29 carry-over)

**Next action:** SEO-10 (SSR jobs hub pagination + rel=prev/next) — the last P1 structural gap in the crawl path; after that, all P0 + P1 structural work is done and the remaining tracks are content (SEO-19/20/21/24/25) and polish (SEO-12/15/17). Alternate tracks: SEO-12 (`EducationalOccupationalCredential` JSON-LD on `/verify/{id}`) · SEO-15 (FAQPage on roadmap) · SEO-19 (10 programmatic `/vs/{a}-vs-{b}` pages).
**Open questions for the user:** None.

**Agent-utilization footer:**

- Opus: Phase 0 reads + SEO-02/11/07 spec reads, route + model audit across 10 files (blog.py, jobs.py, admin.py, main.py, user.py, plan.py, certificate.py, certificates.py, requirements.txt, nginx.conf). Four code commits: Track A HEAD fix (4 files, ~40 LOC incl. 3 tests), Track C SEO-11 OG generator (10 files, ~570 LOC incl. 14 tests + new og_render.py + og.py + Pillow dep), Track B SEO-02 sub-sitemaps (5 files, ~375 LOC incl. 7 tests + new seo.py + image extension + index refactor), Track D SEO-07 IndexNow wiring (3 files, ~270 LOC incl. 7 tests). Plus one docs commit. SSH ops to VPS: generated INDEXNOW_KEY in-flight (never echoed to my context until verified live via `/{key}.txt`), appended to `.env`, two backend rebuilds, one web force-recreate, 10+ URL live validation.
- Sonnet: n/a — Track B was Sonnet-eligible per docs/SEO.md §0.3 but self-executed (hot cache advantage). Track D wiring spec was small/mechanical but also self-executed (8 LOC of code + 250 LOC of tests, cache-warm).
- Haiku: n/a — live validation was small-grid curls with Pillow dimension checks, not worth farming.
- codex:rescue: n/a — no load-bearing paths touched. `routers/seo.py`, `routers/og.py`, `services/indexnow.py` (pre-existing) are non-security SSR. `services/certificates.py` was touched but the addition is 5 lines of post-commit notification (not cert signing / HMAC / tier logic) — out of the security-sensitive zone per docs/SEO.md §0.3 load-bearing list.
