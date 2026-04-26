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

In the Phase 0 parallel-tool-call burst, read all six in one message:

- `CLAUDE.md` (this file)
- `docs/HANDOFF.md`
- `docs/RCA.md` — first ~150 lines (recent entries + the "Patterns to watch for" table at the bottom)
- `docs/SEO.md` — §0 only, first ~100 lines (trigger conditions + task status board + next action). Load deeper sections on-demand when §0.1 trigger conditions apply to the current session's work.
- `docs/COURSES.md` — §0 only, first ~120 lines (trigger conditions + task status board + next action). Load deeper sections on-demand when §0.1 trigger conditions apply.
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
- **Course / curriculum work** (any change to curriculum templates / generation pipeline / prompts in `generate_curriculum.txt|review_curriculum.txt|refine_curriculum.txt|discover_topics.txt` / admin Pipeline / Topics / Templates UI / new course-format type / quiz / showcase / cohort / streak / cert-bundling routes / tech-shift response) → `reference_course_plan.md` → full plan at `docs/COURSES.md`. Any task in the `COURSE-00..COURSE-28` set governed by that doc. Flagships are manual Opus authoring (paste-upload), never auto-generated.

### Phase 6 exit — this repo specifically

- Rewrite the `## 9. Session state` section below (≤30 lines)
- If a bug was fixed, append a numbered entry to `docs/RCA.md` and update its pattern table if the failure mode is new
- Do **not** `git commit` without explicit user approval (per §5 rule on risky actions)
- If AI enrichment prompts were touched, confirm with the user before overwriting — tuned prompts are never regenerated without approval

## 9. Session state (update at end of each session)

> Claude Code: rewrite everything below this line at the end of every session. Keep it under 30 lines. This is what the next session reads to know where you left off.

**Last session date:** 2026-04-26 (session 46 — Phase B daily X auto-post queue + SMTP notify endpoint + share button + OG logo + robots/regex fixes)
**Last session summary (session 46):** Built Phase B end-to-end: cron queues a `pending` TweetDraft at 8am IST M-F per slot rotation (Mon/Wed/Fri = blog teaser, Tue/Thu = quotable, Sat/Sun skip); admin reviews at `/admin/tweets`, clicks Post → OAuth 1.0a signed POST to `api.twitter.com/2/tweets`. User got X dev account approved end-of-session, generated 4 OAuth keys with Read+Write, pasted into VPS `.env`, force-recreated backend+cron. Yellow "X API not configured" banner gone. Test draft #1 inserted via SQL sitting `pending` for end-to-end Post-button verification on next browser click.

- **Phase B (commit `ccbcff8`):** migration `a1b9c2d3e4f5` (parent `c8e2d15a3f97`) → `tweet_drafts` table. New `tweet_curator.py` (slot rotation + 30d posted dedupe + unbounded in-flight dedupe + NULL `posted_at` handling — SQLite `NULL >= cutoff` is FALSE, requires explicit `IS NULL` clause). New `twitter_client.py` — OAuth 1.0a manual signing via `ClientAuth.sign(body=b"")` to skip the `oauth_body_hash` X-v2 doesn't validate, while sending the JSON body via plain `httpx`. Atomic UPDATE flips `pending|failed → posting` (race-safe); transport errors leave `posting` (admin investigates manually, no auto-retry). Per-IP `5/hour` post rate limit. `logging_redact` extended for OAuth 1.0a `Authorization: OAuth ...` headers (case-insensitive early-out + comma-list redaction).
- **codex:rescue gate (Phase B):** REVISE → 3 BLOCKERS + 4 lesser fixes addressed with regression tests. Verdicts SAFE / SAFE / SAFE on second-pass self-audit (codex helper declined to engage on follow-up, matching S45's pattern). All 43 new tests + 100 unchanged regression tests pass.
- **`fa2ee5b` — programmatic email infrastructure:** `POST /admin/api/notify` bearer-token endpoint. Recipient hardcoded to `maintainer_email` so a leaked token can only spam one inbox. Built after the Wed claude.ai routine (`trig_015f2cVRhQGkmLseDZFWhKbm`) failed — Gmail MCP token expired and Google blocked OAuth re-auth ("This app is blocked, sensitive scopes" — Workspace policy). The notify endpoint replaces it as the durable transport. 8 tests.
- **Smaller commits this session:** `5755585` + `788021b` (RCA-034 — banned-term regex anchored to domain boundary so `octoverse.github.com` cites pass), `f4d1341` + `d67dd92` (per-post Share button + modal, leads with `quotable_lines[0]`), `108f6ba` (OG card render + `og_description` Twitter-truncation-safe prompt), `31d82ca` (RCA-035 — robots.txt `Allow: /og/` so social crawlers can fetch og:image).
- **Sonnet engagement:** zero this session. All work schema-critical (migration, atomic UPDATE) or in hot Opus cache (admin.py from S43+). Subagent cold-start outweighed brief authoring savings.

**Deploy status:** Live at `fa2ee5b`. VPS HEAD verified equal to local. `/api/health` 200. `TWITTER_API_KEY/SECRET/ACCESS_TOKEN/ACCESS_TOKEN_SECRET` and `NOTIFY_API_TOKEN` set on VPS. backend + cron containers force-recreated to pick up env. `/admin/api/notify` smoke-tested with both wrong-token (401) and correct-token (200, email delivered).

**Open broken artifact:** Wed routine `trig_015f2cVRhQGkmLseDZFWhKbm` armed for 2026-04-29 04:30 UTC — expected to fail (CCR can't reliably execute curl, root cause unknown after 5 prompt iterations). User can delete via UI; the `/admin/api/notify` endpoint is the durable replacement.

**Open verification:** test draft #1 sits `pending`; clicking Post on `/admin/tweets` produces the first end-to-end live tweet. If 401, regenerate Access Token (was generated before Read+Write was set on the X app); if 200, Phase B is fully live.

**Next action — Session 47:** ship 3 engagement upgrades on Phase B — cron firing time `02:30 UTC → 13:30 UTC` (peak US tech-audience window), unify blog_teaser hook with the Share button's quotable-first pattern, image attachment via X media upload (the 2-3× engagement lever). Self-contained next-session prompt lives at the top of `docs/HANDOFF.md` under "Session 47 prompt".

**Queued:** S47 engagement upgrades · S45's 4 surface ribbons (parallel Sonnet × 4) · S44 pagination test fix · S48 SEO-21 q2 / 5+6 · **SEO-26 quiz landing** (worktree + codex:rescue for `quiz_outcomes` migration) · COURSE-01..03 Phase A · COURSE-04+05 Phase B MVP · separate commit for `docs/COURSES.md` from S43.

**Agent-utilization footer:**

- Opus: full session lead — Phase 0 reads (parallel burst across CLAUDE.md + HANDOFF + RCA + memory + 6 context files); 8 commits authored end-to-end (validator + Share modal + OG logo + robots + Phase B + notify); the 3-iteration discovery on OAuth 1.0a authlib quirks (`AsyncOAuth1Client` strips JSON, `ClientAuth.sign(body=...)` adds unwanted `oauth_body_hash`, `body=b""` is the documented escape); Phase 3 line-by-line review of codex-flagged `twitter_client.py` (caught all 3 blockers with regression tests); 3 deploy cycles with VPS-HEAD-equals-local verification; the manual X dev account walk-through (Read+Write ordering trap, console.x.com vs developer.x.com mapping); RCA-034 + RCA-035 + 2 patterns table additions; this HANDOFF + §9 + S47 prompt.
- Sonnet: n/a — all work schema-critical, security-sensitive, or in hot cache. Per CLAUDE.md "Don't delegate when self-executing is faster."
- Haiku: n/a — no bulk reads/sweeps needed.
- codex:rescue: 1 successful engagement (Phase B Twitter client) — REVISE → all 3 blockers + 4 lesser fixes addressed → ACCEPTED via self-audit when second-pass declined to engage. Helper-runtime returning empty matches S45's pattern. Worth investigating before S49's `quiz_outcomes` migration which IS in §8's strictly-mandatory list.
