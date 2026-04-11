# Handoff

> This file is rewritten at the end of every session. Read after CLAUDE.md.

## Current state as of 2026-04-11

**Last worked on:** P1 pipeline + P2 UX + security + unified nav + account page + admin UI
**Branch:** master
**Live site:** https://automateedge.cloud

## What got done this session (2026-04-11)

### P1: Auto Curriculum Pipeline (complete)

- DB models: `CurriculumSettings` (singleton config), `DiscoveredTopic` (lifecycle state machine: pending → approved → generating → generated | rejected)
- Alembic migration `d4a1c8e92f3b` — applied on VPS
- **Auto-discovery service** (`services/topic_discovery.py`): AI researches trending topics via Gemini/Groq, triage filter (cheap classifier), dedup via normalized_name
- **Batch generation** (`services/batch_generator.py`): 5 variants per approved topic (3mo/6mo × beginner/intermediate/advanced)
- **Content refresh** (`services/content_refresh.py`): HTTP HEAD link health checks (SSRF-safe), AI currency review
- **AI cache** (`services/ai_cache.py`): file-based JSON cache with TTL
- **Token budget** (`services/budget.py`): 3-tier enforcement (<80% ok, 80-90% warning, 90-100% fallback, ≥100% hard stop)
- **Background scheduler** (`services/pipeline_scheduler.py`): 6-hour check interval, configurable frequency
- **Admin pipeline UI** (`routers/pipeline.py`): 3 pages (dashboard with trigger buttons, topics management with approve/reject, settings configuration)
- **Prompts**: discover_topics.txt, triage_topic.txt, review_currency.txt
- All follows AI Enrichment + Normalization blueprints

### P2: User Experience (complete)

- **3-step plan picker**: Topic → Duration → Level → Preview with stats before enrollment. Dynamically groups templates, skips steps with only one option.
- **Course history** in profile/account: all past plans with progress bars, dates, status
- **Profile modal fix**: only closes on X button (not background click)
- **Profile modal replaced** with full `/account` page (see below)

### Security Hardening (Codex audit — 5 issues found and fixed)

- **SSRF** (High): blocked RFC-1918/link-local/metadata IPs in link checker, disabled redirect following
- **CSRF** (Medium): strict hostname comparison, reject missing Origin/Referer
- **Settings validation** (Medium): Pydantic model with type/range/enum constraints
- **Prompt injection** (Medium ×2): truncate + sanitize DB strings before AI prompt interpolation
- **Pagination** (Low): topics API limited to 50/page

### Account Page (new)

- Replaced cramped profile modal with full `/account` page
- Two-column layout: left (profile card, current plan with progress ring, profile form, connections, save) + right (preferences, course history timeline, export/delete)
- **Inline plan switcher**: expands below current plan section, shows all templates as cards, confirm before switching
- **Plan switch rate limit**: 10/day per user (429 if exceeded)
- Served as static HTML via nginx (`frontend/account.html`)

### Unified Navigation (major refactor)

- Created shared `frontend/nav.js` + `frontend/nav.css` — included on every page
- **Main nav** (always visible): Home, Leaderboard, Account, Admin (admins only), Sign Out
- **Admin sub-nav** (only on `/admin/*`): Dashboard, Users, Templates, Pipeline, Topics, Settings — darker bar below main nav
- Active page highlighted with gold underline
- Auth-required pages show auth links immediately (no flash of Sign In)
- Removed 5 different inline navs from index.html, account.html, public_profile.py, admin.py, pipeline.py
- Removed CSS conflicts (global `a` color overrides, duplicate `.topnav` responsive rules)
- **Actions removed from nav**: Export Learning Plan → home page stats row, Switch Plan → account page only

### Admin UI Improvements

- Matched main site header: Fraunces/IBM Plex fonts, sticky glassmorphism navbar, SVG logo
- Full-width layout (removed max-width constraints)
- Created `docs/ADMIN_PAGES.md` — comprehensive reference for all 7 admin pages

### Bug Fixes

- **RCA 015**: Leaderboard didn't show users with public_profile=true but no plan enrolled
- **Admin nav mismatch**: admin.py and pipeline.py had different nav links — unified

### Infrastructure

- GitHub MCP server configured (`.mcp.json`, gitignored)
- RCA log updated (entries 011-015)
- Memory updated: agent strategy, RCA rules, GitHub MCP, unified nav pattern, additional AI APIs

### Documentation

- `docs/ADMIN_PAGES.md` — all 7 admin pages documented
- `docs/HANDOFF.md` — this file
- `docs/RCA.md` — entries 011-015 (SSRF, CSRF, validation, prompt injection, leaderboard)
- CLAUDE.md session state updated
- Memory: pending tasks updated (P1, P2 marked complete)

## Credentials status

| Credential | Status |
|-----------|--------|
| SMTP App Password | Rotated (prrw...) |
| Groq API Key | Rotated (gsk_PWf...) |
| Google OAuth | Safe (never in git) |
| Gemini API | Spend-capped (PersonalAI project) |
| JWT Secret | Safe |
| GitHub MCP Token | gho_ OAuth from gh CLI (in .mcp.json, gitignored) |
| Sambanova API | Key available, not yet on VPS |
| Cerebras API | Key available, not yet on VPS |
| Mistral API | Key available, not yet on VPS |
| DeepSeek API | Key available, not yet on VPS |

## Tests

**Passing:** 90 automated
**Failing:** none
**Gap:** New pipeline code (P1) has no tests — Codex test gap analysis failed to read files

## Key files changed this session

| File | Change |
|------|--------|
| `backend/app/models/curriculum.py` | Added CurriculumSettings, DiscoveredTopic |
| `backend/app/services/topic_discovery.py` | NEW — AI topic discovery |
| `backend/app/services/batch_generator.py` | NEW — template generation |
| `backend/app/services/content_refresh.py` | NEW — link health + currency review |
| `backend/app/services/budget.py` | NEW — token budget enforcement |
| `backend/app/services/ai_cache.py` | NEW — file-based AI cache |
| `backend/app/services/pipeline_scheduler.py` | NEW — background scheduler |
| `backend/app/routers/pipeline.py` | NEW — pipeline admin API + UI |
| `backend/app/routers/admin.py` | Updated nav, fonts, header |
| `backend/app/routers/profile.py` | Added plan_history to profile response |
| `backend/app/routers/plans.py` | Added 10/day plan switch rate limit |
| `backend/app/routers/public_profile.py` | Fixed leaderboard filter, nav, CSS |
| `frontend/index.html` | 3-step picker, unified nav, export button |
| `frontend/account.html` | NEW — full account settings page |
| `frontend/nav.js` | NEW — shared navigation logic |
| `frontend/nav.css` | NEW — shared navigation styles |
| `nginx.conf` | Added /account route, .js/.css serving |
| `docs/ADMIN_PAGES.md` | NEW — admin pages reference |
| `docs/RCA.md` | Entries 011-015 |
| `alembic/versions/d4a1c8e92f3b_...py` | NEW — curriculum tables migration |

## Next session priorities

1. **Test P1 live** — Run Discovery from admin pipeline, approve topics, generate templates
2. **Add new AI providers** — Sambanova, Cerebras, Mistral, DeepSeek keys to VPS .env, add provider wrappers
3. **P3: Email** — Check SPF propagation, possibly add DKIM
4. **P4: Content** — Generate specialist templates (NLP, CV, MLOps) via pipeline
5. **Tests** — Write tests for pipeline services
6. **Future:** AI News Feed, AI Job Board

---

## Session history

| Date | Summary |
|------|---------|
| 2026-04-10 | Phases 1-12 built, tested, deployed. OAuth, OTP, PDF, admin. |
| 2026-04-10 | Launch: OAuth fix, email config, docs, credential setup. |
| 2026-04-11 | AI features live, nav/UX redesign, email reminders, leaderboard, dynamic templates, blueprints. |
| 2026-04-11 | P1 pipeline + P2 UX + security hardening + unified nav + account page + admin UI. 20+ commits. |
