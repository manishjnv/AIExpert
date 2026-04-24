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

**Last session date:** 2026-04-24 (session 39 — SEO-21 first pillar post + template wire-up)
**Last session summary (session 39):** One commit. Authored the first pillar post at `/blog/ai-engineer-vs-ml-engineer` (q6 — most beatable SERP per SEO.md §5.1) and closed the SEO-21 template gap so pillar rich-results actually ship.

- **Pillar post authored:** [docs/blog/03-ai-engineer-vs-ml-engineer.json](docs/blog/03-ai-engineer-vs-ml-engineer.json) — 3134 words, 50-word featured-snippet first paragraph, 10 H2s, 46 internal links (all 12 AI/ML track section pages, /jobs, /blog/01-02, /vs/ai-engineer-vs-ml-engineer, /roadmap hub, /), 7 trusted citations (Stanford AI Index, BLS, arXiv, Hugging Face, OpenAI platform docs, PyTorch, Papers with Code), 10 FAQs from PAA, 1 seven-dimension comparison table, 4 DefinedTerms. Validator: `ok=True, 0 errors`, 2 editorial warnings (8 paragraphs >4 sentences, 10 sentences >30 words — judgment calls, not publish blockers).
- **Template wire-up (SEO-21 foundation closure):** [backend/app/templates/blog/post.html](backend/app/templates/blog/post.html) now emits FAQPage + DefinedTermSet JSON-LD conditional on `payload.faqs` / `payload.defined_terms`. [backend/app/routers/blog.py:443](backend/app/routers/blog.py#L443) threads both fields from payload into `_render_post`. Without this the pillar validator's `schemas: ["Article","FAQPage","DefinedTerm"]` was a claim with no emission — rich-result gap plugged. Render test: 4 JSON-LD blocks (Article + BreadcrumbList + FAQPage[10] + DefinedTermSet[4]) all parse as valid JSON.
- **Allowed-tag expansion:** [backend/app/services/blog_publisher.py:87](backend/app/services/blog_publisher.py#L87) — `_ALLOWED_TAGS` gains `table/thead/tbody/tr/th/td`. Pillar posts with `comparative: true` require a `<table>`; pre-fix, every pillar post threw a non-standard-tag warning on the table family. Browser-native, zero XSS risk under admin-controlled body_html.
- **Tests:** 65 blog tests pass, 0 regressions (full suite not re-run — changes are tight + additive).

**Deploy status:** NOT yet deployed. Commit local. Live publish also pending — pillar post is an authoring archive at `docs/blog/03-*.json`; admin must paste into `/admin/blog` → draft → review → publish (IndexNow ping auto-fires on publish). Deploy required before publish: `git pull && docker compose up -d --build --force-recreate backend` (template + router + validator changes all need the rebuild).

**Next action — Session 40:** Second pillar post `/blog/learn-ai-without-cs-degree-2026` (q7 — Quora currently in top 3, thin SERP). Schema stack: Article + FAQPage + HowTo (skip Review — still blocked on ≥5 real testimonials). Same validator, same ~3000-word target.

**Queued:** S41 post 3 (`ai-roadmap-2026-whats-changed`, q2) · S42 post 4 + full SEO-22 wire-up (template render of VideoObject JSON-LD when `videos[]` present) · S43 posts 5 + 6 · **S44 SEO-26 quiz landing** (worktree + codex:rescue for `quiz_outcomes` Alembic migration).

**Open questions for user:** (1) Deploy + publish session 39 now, or batch with S40 for a single deploy + two-post drop? (2) Split the 2 remaining editorial warnings in post 03 (paragraph/sentence length) to hit zero-warning compliance per SEO-21 spec, or accept as dense-pillar judgment? (3) Tier-1 user-facing jobs features (saved jobs, match chip) remain queued after the pillar-post batch — confirm or interleave?

**Agent-utilization footer:**

- Opus: Phase 0 reads (CLAUDE.md §8 + §9 + SEO.md §0 + trusted_sources.json + blog_validator.py + blog_publisher.py + post.html + existing post 02 JSON); VPS deploy verification via SSH + live curl probes (confirmed session 38 shipped); template + router wire-up (~20 LOC); pillar-post authoring (3134 words, 10 H2s, 46 internal links, 7 citations, 10 FAQs, 4 DefinedTerms — single editorial pass with 3 tightening edits); local validator + JSON-LD render verification; Phase 2 gates (secrets + TODO, both clean) + HANDOFF/SEO.md updates + §9 rewrite.
- Sonnet: n/a — single-author editorial work, no mechanical fan-out eligible.
- Haiku: n/a — 2-call VPS verification cheaper as direct Opus tool calls than spawning a sweeper.
- codex:rescue: **deferred** — template emits client-facing JSON-LD, admin-only publish still gates content (no auth, no AI-classifier, no Alembic, no jobs_ingest/enrich). Engagement point remains S44 (SEO-26 `quiz_outcomes` migration).
