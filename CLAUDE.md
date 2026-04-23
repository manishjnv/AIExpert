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

**Last session date:** 2026-04-23 (session 35 — SEO-12 + SEO-15 + SEO-16 + SEO-17 completions; content-heavy SEO tracks deferred)
**Last session summary (session 35):** Shipped the remaining mechanical SEO tasks. All structural + schema SEO is now complete; the only unfinished items are user-action-blocked (SEO-00, SEO-01) or content-heavy multi-session work (SEO-19/20/21/25/26) that warrants a scoped plan before execution.

- **SEO-12 — EducationalOccupationalCredential JSON-LD on `/verify/{id}`** (`4af9f7c`). Added `<script type="application/ld+json">` block to the `/verify/{id}` render path in [backend/app/routers/verify.py](backend/app/routers/verify.py). Populates name (tier_label + course_title), credentialCategory="certificate", educationalLevel (capitalized), recognizedBy (AutomateEdge Organization + base URL), dateCreated (ISO-8601 from cert.issued_at), about (Thing with course_title), url. Null keys filtered. Emitted even on revoked-cert pages — schema describes the record, not current validity state.
- **SEO-15 — Visible FAQ section** (same commit). Added `<section id="faq" class="faq-section">` to [frontend/index.html](frontend/index.html) after SCAFFOLD:END (survives JS hydration — scaffold-removal targets only `[data-roadmap-scaffold]`). 12 `<details>` / `<summary>` entries match the existing FAQPage JSON-LD near line 839 verbatim. CSS added to single-file `<style>` per site design system (dark cards, gold open-state accent, IBM Plex Sans). Google's "schema must be visible" requirement for FAQPage rich results now satisfied.
- **SEO-16 — Brotli** ✅ via Cloudflare edge. `curl -I -H 'Accept-Encoding: br' https://automateedge.cloud/` confirms `Content-Encoding: br`, `Server: cloudflare`. Origin nginx config unchanged — swapping nginx:alpine for an ngx_brotli-compiled image carries directive-incompatibility risk for ~15% marginal savings CF already delivers.
- **SEO-17 — font-display:swap + WebP** ✅ already satisfied. All Google Fonts URLs across [frontend/index.html](frontend/index.html), [frontend/nav.css](frontend/nav.css), [frontend/account.html](frontend/account.html), [backend/app/templates/blog/post.html](backend/app/templates/blog/post.html), and the 6 backend routers (admin, admin_jobs, blog, jobs, pipeline, public_profile) carry `&display=swap`. Site has no raster above-fold imagery; favicon is inline SVG data URI. Nothing to WebP-ify.
- **Tests (+3)** in [backend/tests/test_seo_verify_faq.py](backend/tests/test_seo_verify_faq.py). Parses live credential JSON-LD asserting every field (name, credentialCategory, educationalLevel, recognizedBy, dateCreated ISO-8601, about, url); confirms schema emits on revoked pages; walks FAQPage JSON-LD and asserts every Question.name renders as visible `<summary>` inside the FAQ section. Setup resets `verify._view_budget` / `_view_dedup` so test_certificates_e2e's rate-limit drain doesn't 429 these.

**Tests passing:** 493 local (was 490; +3 net). Same pre-existing `test_ashby_skips_unlisted_jobs` Windows asyncio failure, 1 skipped (aiosmtplib env-broken locally).

**SEO status board — all structural + schema P0/P1/P2 done:**
- ✅ SEO-02 (sub-sitemaps), SEO-03 (head), SEO-04 (SSR scaffold), SEO-05 (Course+ItemList+FAQPage JSON-LD), SEO-06 (Article), SEO-07 (IndexNow), SEO-08 (Breadcrumb), SEO-09 (RSS), SEO-10 (SSR pagination), SEO-11 (OG generator), SEO-12 (EduOccCred), SEO-13 (canonicals), SEO-15 (FAQ visible), SEO-16 (Brotli via CF), SEO-17 (font-display / no imagery)
- 🟡 SEO-00 (GSC+Bing verified, sitemaps submitted 2026-04-23; 7-day baseline metric awaits data), SEO-01 (origin robots deployed; Cloudflare Managed robots override = user action)
- 🔒 SEO-14 (needs /search endpoint), SEO-18 (gated on Lighthouse), SEO-22 (no video embeds yet), SEO-23 (≥5 testimonials)
- ⏳ Content-heavy, deferred: SEO-19 (10 /vs pages), SEO-20 (30 per-track quintet), SEO-21 (pillar blog cluster + validator), SEO-24 (ItemList dep on SEO-20), SEO-25 (E-E-A-T allowlist, dep on SEO-21), SEO-26 (/start quiz — new feature)

**Still blocked on user action:** (1) Cloudflare Managed robots.txt override (SEO-01), (2) 7-day GSC/Bing baseline capture (SEO-00), (3) 101 "Other" drafts admin triage (session 29).

**Next action:** content-heavy tracks each need scope alignment before executing. Recommend SEO-19 first (10 programmatic `/vs/{a}-vs-{b}` pages = biggest long-tail unlock per SERP recon in §5.1; template + `comparisons.json` data file, not freeform writing). SEO-21 pillar cluster is truly multi-day writing work. SEO-26 `/start` quiz is a product feature needing product decisions. Propose scope per track when user is ready.
**Open questions for the user:** Which content-heavy track to prioritize next — SEO-19 (programmatic comparisons, ~1 session) or defer all content work until the GSC 7-day baseline lands so we can target with data?

**Agent-utilization footer:**

- Opus: Phase 0 reads (CLAUDE.md + HANDOFF via §9 + SEO.md §0), scope audit of remaining 11 SEO tasks (which are blocked / shippable / content-heavy), verify.py deep read for JSON-LD insertion point, frontend/index.html scaffold + existing FAQPage JSON-LD discovery (12 Qs already embedded without visible counterpart), live CF Brotli check, codebase-wide font-display:swap grep audit (13 URL sites, 100% conformant), SEO-12 + SEO-15 implementation (~70 LOC index.html FAQ + CSS + ~25 LOC verify.py JSON-LD + 171 LOC tests), 493-test suite verification, commit + noreply-amend + push, VPS git pull + backend rebuild + 4-URL live validation (FAQ section count, 12 summaries, JSON-LD parse), docs updates.
- Sonnet: n/a — both shippable tasks were small, well-specified, in hot cache. Per global playbook "don't delegate when self-executing is faster."
- Haiku: n/a — no multi-file sweeps beyond the single font-display grep.
- codex:rescue: n/a — no load-bearing paths touched. verify.py is SSR credential display (HMAC signature check unchanged; only added read-only JSON-LD emit). frontend/index.html FAQ is static HTML + CSS.
