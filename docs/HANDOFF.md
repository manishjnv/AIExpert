# Handoff

> This file is rewritten at the end of every session. Read after CLAUDE.md.

## Current state as of 2026-04-13 (session 8)

**Last worked on:** Site-wide gamification + branding + UX polish on top of the now-shipped certificate system.
**Branch:** master
**Live site:** https://automateedge.cloud
**Alembic head:** b3f5a9e21c04 (no new migrations this session)

### Session 8 — what shipped (2026-04-13)

**Certificate polish (post-session-7 fixes)**
- weasyprint 62.3 → 63.1 + pydyf 0.11.0 pin (PDF render crashed on the old combo)
- nginx `/verify/` location block — public verify page was 404'ing at the edge
- PDF layout: drop "0 GitHub repositories" + Projects stat when `repos_linked==0`; widen stats gap 18→28mm; shrink QR 30→26mm; reduce title/name sizes so 2-line wraps stay clean
- No-cache headers on `/verify` and `/api/certificates/{id}/pdf` so template updates don't get stuck behind stale browser cache
- Empty-state card on `/account` My Certificates so the section is always visible (was hidden when `len(certs)==0` — looked like the feature was missing)
- Lookup form at `/verify` (GET `/verify`, `/verify/`, `/verify/lookup?id=…`) — accepts bare ID, lowercase, or a full URL paste. Footer link on cert page points to `/verify` now (was broken `/verify/…`)
- Modules section on verify HTML: per-month cards with title + tagline + amber topic chips; PDF keeps a single small "Modules" line + "Full topic breakdown at …" pointer to the rich page
- E2E integration tests: `tests/test_certificates_e2e.py` covers enroll → bulk-complete → PATCH issues cert → list → real WeasyPrint PDF (asserts %PDF magic) → /verify HTML + OG SVG → share counter → ownership 404 → revoked 410 → rate-limit 60/IP/hr

**Leaderboard — full gamification (real DB-derived numbers, no fakes)**
- Layout: `max-width 1100px → 100%` with clamped padding (`clamp(20px, 4vw, 64px)` + `6vw` ≥1600px).
- New stat cards: Total XP, Projects Built, Certificates, Top Streak, Graduated
- XP formula: `tasks*10 + distinct_repos*50 + streak_weeks*20 + cert_completion*500/distinction*750/honors*1000`
- 7 tier ladder with colored chips (Apprentice 🥚 → Learner 📘 → Practitioner 🛠️ → Builder 🚀 → Engineer 💎 → Architect 👑 → AI Guru 🧙); chip on each row + mini XP bar to next tier + "N,NNN XP → next tier" caption
- Achievement pills: 🎯 First Task, 📚 50 / 📖 250 Tasks, 🎓 First Cert, 💎 Triple Crown, 🏆 Honors, 🚀 5 / ⭐ 15 Repos, 🔥 Nw Streak, 🔥🔥 10w+ Hot Streak
- "TOP X%" percentile pill (only for top 10 and top 25 thresholds)
- Collapsible "How ranking & XP work" help panel above table — documents every rule so learners can see exactly how to climb
- New columns: **Tier** + **XP** + **Last Active** (color-coded recency from `MAX(progress.completed_at, repo_links.linked_at)`: green ≤ 48h, amber ≤ 1w, muted older)
- **Repos** column now counts **DISTINCT (owner, name)** via subquery — same repo linked to multiple weeks = 1 repo; XP bonus credits each unique repo once
- Subtitle line rewrite: `Joined Apr 2026 · Studying: AI Generalist · Month 2 of 6 · 249 tasks`. Fallbacks: `Between courses` (no active plan) / `New learner` (no plans at all). "Not enrolled yet" was insulting for a learner with 249 lifetime tasks.
- Plan + Current Progress columns dropped (redundant now that XP ranks everything; current plan rests in the subtitle)

**Branding push**
- Top-left nav wordmark: Logo + **AutomateEdge** (Fraunces 20px amber) + `AI LEARNING ROADMAP` subline (mono caps). Plan title removed from nav (hero owns it).
- Eyebrow on home: `Welcome, Manish · 7% complete` (dropped redundant plan title — was saying the same thing 3 times across nav + eyebrow + h1)
- Hero H1 stacked: topic primary + `SIX MONTHS · ADVANCED` meta line + course summary. Drops the inline `Three Months. AI Generalist.` style.
- PlanTemplate schema: new optional `summary` field (40–80 word plain-English course description). Backfilled on the 3 generalist templates; both generation prompts (`generate_curriculum.txt` auto + `claude_opus_manual.txt` admin upload) updated to emit it.
- Global footer rendered via `nav.js` (DOMContentLoaded-deferred so it doesn't get stranded at top of page on backend-rendered pages). Brand-first: AutomateEdge wordmark + `AI Learning Roadmap · A free, self-paced platform for anyone learning modern AI.` (broadened from "for AI/ML engineers"). Pill-style amber-outlined links: About · Leaderboard · Verify Credential · Contact · Source Code.
- Contact link preserves existing modal → POST `/api/contact` → Resend + Cloudflare email pipeline; navigates via `/#contact` hash from non-home pages. (An earlier pass mistakenly converted it to mailto — regression reverted same session.)
- Email identity: contact subject `[AI Roadmap] Contact from X` → `[AutomateEdge] Contact from X`. SMTP_FROM_NAME `"AI Roadmap"` → `"AutomateEdge"` in config, .env.example, and prod `.env`.

**AI chat personalisation**
- Chat system prompt now includes a LEARNER PROFILE block sourced from `user.experience_level` + `user.learning_goal` (were collected but unused). Model calibrates depth to level and anchors examples to the stated goal (SOC manager → security/anomaly examples). Anon visitors and users with blank fields get the unchanged prompt.

**Week card UX**
- Native `<details>` collapsible week cards; completed weeks collapse by default, others open. Summary always shows Week N · title · status pill (✓ Complete / X/Y · NN% / Not started) · hours · ▾
- Top Resources 2-column: left `▶ Video Courses`, right `📄 Docs & Practice`. URL-regex classifier: `/youtube\.com|youtu\.be|vimeo\.com|coursera\.org\/(learn|specializations)|fast\.ai|deeplearning\.ai\/(courses|short-courses|programs)|udacity\.com|khanacademy\.org/`. Falls back to single column when week has only one type.
- Checklist 2-column grid (1 col < 720px)
- Both generation prompts now mandate **exactly 6 resources/week, split 3 video + 3 non-video**, with the classifier regex quoted in-prompt so the model picks URLs on the correct side.

**UI polish**
- `--ink-soft` contrast bumped from `#4a5260` (2.4:1) to `#94a3b8` (7:1) — passes WCAG AA; every secondary label/email/meta-line lifts together
- Toggle labels on /account switched to `--serif` 15px to match the other content-card brand typography
- Top-nav link alignment tightened (gap 2→4px, padding 10×16, explicit inline-flex line-height so the active underline doesn't shift rows 1px down)
- Scroll-to-top button (bottom-left) rebuilt: amber fill, 48×48, gold halo ring, 2.4s pulse animation, hover-lift — impossible to miss

**Commits this session (2026-04-13, session 8)**
PDF/verify fixes: `8810b4e`, `c76c84f`, `bc5672a`, `b2fa50a`, `2bf9b0b`, `f1ee2bb`, `8cc6d92`, `bb563f3`, `28e82e0`, `871ef0a`, `31c097f`  ·  Leaderboard gamification: `f935d49`, `42c1564`, `80cc6da`, `0782701`, `6d6afe1`, `4c59f7a`, `2e6dd21`  ·  Branding + footer: `32bcc8c`, `2a7ca8e`, `327002e`, `6932329`, `eb24b7c`, `51e544b`, `6ea6b62`, `6f677ea`  ·  UX: `45573d4`, `529a201`, `946d653`, `27f9c15`, `58d9a4e`  ·  This-turn: email identity (pending commit).

---

## Prior sessions (pre-session-8)

## Current state as of 2026-04-12 (session 7 — legacy)

**Last worked on:** Cost-tracking system — OpenAI embeddings dedup, admin usage dashboard, provider-authoritative spend sync, proactive alerts
**Branch:** master (HEAD: 9cfc8ea)
**Live site:** https://automateedge.cloud
**Alembic head:** d5a61f8e93c4

## Session 7 (2026-04-12) — Cost tracking system

### 1. OpenAI embeddings for semantic topic dedup
- `backend/app/ai/openai_embeddings.py`: `embed()` with 90d cache + cost-cap gate
- `backend/app/ai/pricing.py`: central price table + `compute_cost()` + `check_cost_limit()` + `CostLimitExceeded` + `PROVIDER_INFO` reference dict
- Migration `f9b2c3d47a18`: `discovered_topics.embedding` (LargeBinary) + `ai_cost_limit` table
- 2-stage topic dedup: exact normalized_name → cosine ≥0.88 via text-embedding-3-small

### 2. AI Usage admin dashboard
- Cost cards: Today / Last 7d / Last 30d (computed from `ai_usage_log × pricing`)
- "Tokens this month" card (real, was previously fake from stale counter)
- **Provider Caps & Balances** 8-col table with inline-editable Balance and Current $ cap (click → type → Enter/blur autosaves)
- "Apply all recommended caps" button for first-time setup
- Per-provider daily $ cap enforcement (OpenAI embeddings + Anthropic refinement)

### 3. Persistent usage analytics
- `/api/ai-usage/analytics` returns: all-time per model, monthly (12mo), daily (30d), top tasks by cost, 7d-vs-prior-7d trend, failure rate per provider
- Source: `ai_usage_log` with real token counts from API responses (Gemini `usageMetadata`, OpenAI-compat `usage.total_tokens`, Anthropic `usage.input/output_tokens`, OpenAI embeddings `resp.usage.total_tokens`)

### 4. Provider-authoritative daily spend sync (Layer 2)
- Migration `c7d19e8a4f63`: `provider_daily_spend` table
- `services/provider_usage_sync.py`: `sync_openai()`, `sync_anthropic()`, `run_daily_sync()`, `archive_old_usage_logs()`
- OpenAI via `/v1/organization/usage/completions` + `/embeddings` (admin key)
- Anthropic via `/v1/organizations/usage_report/messages` + `cost_report` (admin key)
- Gemini honestly not synced (no public usage API)
- Daily cron in `pipeline_scheduler` + manual Sync now button
- Reconciliation section shows drift vs local estimate (>10% red, >3% amber)

### 5. Proactive admin alerts
- Migration `d5a61f8e93c4`: `admin_alert` table
- `services/cost_alerts.py`: 3 rules — `cap_breach`, `balance_low` (runway <15d), `pricing_drift` (>20%)
- Banner at top of `/ai-usage` with severity icon + dismiss button
- Auto-resolve when condition clears

### 6. Admin-editable provider balance
- Migration `a3e8d51c7b42`: `provider_balance` table, seeded with defaults
- Static metadata (price, model, purpose) stays in `PROVIDER_INFO`
- Dynamic fields (balance, rec cap) in DB, editable via UI

### 7. CLAUDE.md rules added
- **#11** AI efficiency checklist mandatory on every AI call (memory: `feedback_ai_efficiency.md`)
- **#12** OpenAI embeddings-only scope lock (memory: `reference_openai_usage.md`)

### 8. Infrastructure polish
- All 5 OpenAI-compat providers now share `ai/limits.py` for right-sized max_tokens per task
- All providers capture actual token usage via module-level `_last_usage` dict
- Gemini structured output schemas enabled for generation + quality review (with graceful fallback)
- Claude calls now gated by cost caps + log actual input+output tokens

## Credentials status

| Credential | Status |
|-----------|--------|
| OpenAI regular (`OPENAI_API_KEY`) | Live on VPS — $10 balance |
| OpenAI admin (`OPENAI_ADMIN_API_KEY`) | Live on VPS — Usage API working |
| Anthropic regular (`ANTHROPIC_API_KEY`) | Live on VPS — $10 balance |
| Anthropic admin (`ANTHROPIC_ADMIN_API_KEY`) | Live on VPS — Usage API working |
| Gemini (`GEMINI_API_KEY`) | Live on VPS — ₹1000 (~$12) balance, paid tier |
| Groq / Cerebras / Mistral / Sambanova | Free tier |
| DeepSeek | 402 insufficient balance (disabled) |

⚠ **Rotate these — exposed in chat during this session:**
- `sk-proj-UOr06u...` (OpenAI regular)
- `sk-admin-g8KJK...` (OpenAI admin)
- `sk-ant-admin01-PBnpR...` (Anthropic admin)

## Deploy process (documented in memory: `feedback_deploy_rebuild.md`)

**Backend code changes require full rebuild**, not `restart`, because `/app` is baked into the image (only `./data`, `./scripts`, `./data/templates` are bind-mounted).

```bash
# From local machine after committing + pushing
ssh a11yos-vps
cd /srv/roadmap
git pull origin master
docker compose build backend
docker compose up -d --force-recreate backend
docker compose exec -T backend alembic upgrade head  # if there's a new migration
```

One-liner:
```bash
ssh a11yos-vps "cd /srv/roadmap && git pull && docker compose build backend && docker compose up -d --force-recreate backend && docker compose exec -T backend alembic upgrade head"
```

**Env var changes (new keys in .env):** safer to `up -d --force-recreate` than `restart` — `env_file` is re-read on container creation, not on restart.

## What got done this session (2026-04-12, session 5)

### 1. Template Volume Mount (CRITICAL fix)
- `docker-compose.yml`: `./data/templates:/app/app/curriculum/templates` volume for backend + cron
- `Dockerfile`: seed templates layer + startup seeding logic
- Templates now persist across container rebuilds

### 2. Quality Scorer — 15 Dimensions (was 5)
- 10 new heuristic dimensions (all regex, zero AI cost): Bloom's progression, theory/practice ratio, project density, assessment quality, completeness, difficulty calibration, industry alignment, freshness, prerequisites clarity, real-world readiness
- Scorer calibration: Bloom's strips "Reviewed:" prefixes, project keywords include checks, completeness adjusted for specialized topics, links excluded when unchecked, plateau threshold relaxed
- Pipeline quality table shows all 15 bar charts

### 3. Quality Gate — Publish Model
- `_meta.json` manifest tracks draft/published status per template
- User-facing `/api/templates` returns published only (score >= 90)
- 3 generalist templates grandfathered (always published)
- Publish/Unpublish buttons on Pipeline quality table
- Templates admin page: Status + Quality + Subscribers columns

### 4. Gemini 2.5 Migration
- Model updated from `gemini-2.0-flash-lite` (deprecated) to `gemini-2.5-flash`
- Thinking disabled (`thinkingBudget: 0`), multi-part response handling, code block extraction
- All providers bumped to 8192 max_tokens + 60s timeout for generation

### 5. Content Lifecycle (Proposals + Auto-unpublish)
- Proposals page (`/admin/pipeline/proposals`): view, approve, reject quarterly sync proposals
- Auto-unpublish: content refresh unpublishes templates when AI currency score < 40
- Refine Existing button on Pipeline page: runs AI review+refine on templates below 90

### 6. Clickable Admin (Templates + Topics)
- Template detail page (`/admin/templates/{key}`): full curriculum view with months, weeks, resources, deliverables, checklists
- Template names clickable in Templates table + Pipeline quality table
- Topic detail modal: full justification, evidence sources, approve/reject buttons
- Workflow banner on Topics page explaining the pipeline

### 7. UI Fixes
- Restored connection badges (GitHub/LinkedIn/Google) in nav — lost during unified nav refactor
- Fixed "Loading plan..." stuck — `planBadge` element was missing, crashing eyebrow update
- Badges left-aligned next to logo

### 8. Claude Batch API + Gemini Structured Schemas
- `ai/anthropic.py`: `create_batch()`, `poll_batch()`, `get_batch_results()`
- `ai/schemas.py`: `PLAN_TEMPLATE_SCHEMA` + `QUALITY_REVIEW_SCHEMA` (disabled pending Gemini 2.5 testing)
- Batch refinement: `create_batch_refinement()` + `apply_batch_results()` for 50% discount on 5+ items

## Credentials status

| Credential | Status |
|-----------|--------|
| Gemini | gemini-2.5-flash on VPS, thinking disabled |
| Groq | On VPS, 8192 max_tokens |
| Cerebras | On VPS, 8192 max_tokens |
| Mistral | On VPS, 8192 max_tokens |
| Sambanova | On VPS, 8192 max_tokens |
| DeepSeek | 402 insufficient balance |
| Anthropic | On VPS, prompt caching + batch API, refinement only |
| SMTP (Resend) | Verified, DKIM active |

## Tests

**Passing:** 88 (2 repo tests flaky from GitHub API rate limit)

## Templates on disk (5)

| Template | Composite Score | Status |
|----------|----------------|--------|
| generalist_12mo_beginner | 89 | Published (grandfathered) |
| generalist_6mo_intermediate | 92 | Published (grandfathered) |
| generalist_3mo_intermediate | 89 | Published (grandfathered) |
| multimodal_few_shot_learning_3mo_intermediate | 87 | Draft |
| multimodal_few_shot_learning_3mo_beginner | 87 | Draft |

## Topics (12 in DB)

- 10 generated (errors cleared, ready for re-generation later)
- 1 pending (Agentic AI and Tool-Using LLMs)
- Topic #5 (Adversarial Robustness) was the only clean 5/5 generation

## Prior session notes merged into Session 7 above

## Next session priorities (continued from session 7)

1. **Re-run generation** for topics with missing variants (when rate limits allow)
2. **Approve topic #11** (Agentic AI) and generate
3. **Run Content Refresh** to check links + currency scores
4. **Test Gemini structured output schemas** with 2.5-flash
5. **Wire batch refinement into admin UI** — button when 5+ templates below threshold
6. **URL validation during generation** — catch hallucinated URLs before saving

---

## Session history

| Date | Summary |
|------|---------|
| 2026-04-10 | Phases 1-12 built, tested, deployed. OAuth, OTP, PDF, admin. |
| 2026-04-10 | Launch: OAuth fix, email config, docs, credential setup. |
| 2026-04-11 | AI features, nav/UX, email reminders, leaderboard, blueprints. |
| 2026-04-11 | P1 pipeline, P2 UX, security hardening, unified nav, account page. |
| 2026-04-11 | P1 live test, 4 new AI providers, Resend email, AI usage dashboard. |
| 2026-04-12 | AI quality pipeline, Gemini optimizations, Claude refinement, scoring engine. |
| 2026-04-12 | Template persistence, 15-dim scorer, quality gate, proposals, clickable admin. |
