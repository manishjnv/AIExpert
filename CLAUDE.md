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

**Last session date:** 2026-04-23 (session 37 — jobs-rejection hardening + admin UX polish + scope-locked next slice)
**Last session summary (session 37):** Two ship threads + one memory fix + one scope-planning handshake. Admin queue state changed dramatically mid-session (drafts 549 → 36; admin published 513 in flight, rejected held steady at 642 — sticky working).

- **Thread A — sticky off_topic rejection + 636-row tombstone slim** (`2aded60`, slim via live SQL; earlier §9 entry as "session 33" preserved in git log `160d8d4`). [jobs_ingest.py:596-606](backend/app/services/jobs_ingest.py) now absorbs hash changes on `status='rejected' AND reject_reason='off_topic'` rows instead of flipping them to draft; skips re-enrichment entirely, returns `"rejected_sticky"`. Prod UPDATE slimmed `data='{}'` on 636 off_topic tombstones (4.98 MB reclaimed); denormalized columns + dedup fields preserved. Manual rejects (reject_reason IS NULL) + other reason codes keep old flip-to-draft semantics. +2 tests. End-to-end verification by simulated re-ingest on id=953 — hash absorbed, status stayed rejected, enrichment never called. codex:rescue returned empty both attempts — self-audited (4 reject_reason write sites all admin-validated; all `.data` readers handle `{}`; feedback-loop at `jobs_enrich.py:133` inflates off_topic signal for ~45d, directionally safe).
- **Thread B — admin UX polish for jobs review queue** (`8ea4953`, `55e7ef4`). (1) `#<id>` chip clickable + `/admin/jobs?id=<n>` deep-link + placeholder advertises ID search ("Search title, company, or ID…"). (2) `toggleAll` caps at `BULK_LIMIT=100` to match server cap at [admin_jobs.py:337](backend/app/routers/admin_jobs.py#L337); live `#bulk-cap-note` shows `N of M selected` + amber-warns at cap. Hand-selected >100 guarded with clear client-side message. Dropped stale "can be undone via the Rejected tab" copy from bulk-reject confirm.
- **Memory fix (local, not committed):** [reference_vps.md](file:///C:/Users/manis/.claude/projects/E--code-AIExpert/memory/reference_vps.md) now explicitly documents public domain as `https://automateedge.cloud` and SSH alias `a11yos-vps` is NOT a domain. Guards against my mid-session `learnai.a11yo.com` hallucination. Canonical domain references stay in `reference_platform_config.md:10`, `project_pending_tasks.md:63`.

**Admin queue snapshot at close:** 36 drafts / 784 published / 642 rejected. All 36 drafts have Opus summaries, all from Tier-2 sources (no bulk-approve): mindtickle 13, replit 11, phonepe 8, cred 3, groww 1. 7 rows with designation="Other" are highest-value human-review candidates.

**Session 36 (SEO-19 ten /vs comparison pages, `a30890a`) ships preserved in git log.** 529 tests / 493 before session 37 +2 from sticky-reject = 495 base for next session. Same pre-existing `test_ashby_skips_unlisted_jobs` Windows asyncio failure, 1 skipped aiosmtplib.

**Still blocked on user action:** (1) Cloudflare Managed robots.txt override (SEO-01), (2) 7-day GSC/Bing baseline (SEO-00), (3) 7 "Other" drafts admin triage (shrunk from 101 by today's publish sweep).

**Next action — scope-locked for Session 38:** Tier 1 user-facing jobs features — ranked feed + match % chip in `/jobs` listing cards + saved jobs. User confirmed phasing before `/clear`. One new table `user_saved_jobs(user_id FK, job_id FK, saved_at, note TEXT?)`, unique (user_id, job_id). Backend: `POST/DELETE /api/jobs/{slug}/save`, `GET /api/account/saved-jobs`, extend `/api/jobs` with `rank_by=match` (auth-gated, reuses [jobs_match.py](backend/app/services/jobs_match.py)), auth-gated match score in list `_public_view`. Frontend: Save ★ button on every card + detail page, match chip on cards when logged in, new /account "Saved jobs" section. Tests: save/unsave, ranked-feed ordering, anon fallback (date sort), cross-user isolation. ~400–600 LOC across ~6 files. Alembic migration = load-bearing — Opus line-by-line diff review in Phase 3.

**Queued after Session 38 (user approved 5-session phasing):** S39 — company pages at `/companies/{slug}` + apply-click tracking. S40 — email alerts (preferences + cron + Brevo + unsub tokens). S41 — Tier 3 polish: jobs RSS, similar-jobs, topic-index move off post-query. S42 — salary filter + compare view (after data-coverage review on `employment.salary.disclosed`). User can redirect at any session boundary.

**Open questions for the user:** None.

**Agent-utilization footer:**

- Opus: Phase 0 reads (CLAUDE.md §8 + HANDOFF §9 + RCA 001-028 + jobs_ingest.py + models/job.py + admin_jobs.py rejection block + jobs_enrich.py feedback loop + VALID_REJECT_REASONS audit + jobs.py/jobs_match.py for scope-planning), 4 git commits (sticky-reject + ID-chip-deep-link + bulk-cap + Session 37 handoff) each with noreply-amend pattern, VPS rebuilds × 3, live verification per commit, memory file correction after domain hallucination, admin queue state introspection, phased scope plan aligned with user before clear.
- Sonnet: n/a — every slice was ≤30 LOC of code + hot-cache per global playbook "don't delegate when self-executing is faster."
- Haiku: n/a — no multi-file sweeps warranted a subagent round-trip.
- codex:rescue: **called but non-responsive** (twice, empty / acknowledgement-only) for the classifier-adjacent sticky-reject change. Self-audited via direct grep/read against 5 concerns. Rescue tooling needs revisit before the next classifier-path change — flagged here rather than silently proceeding.
