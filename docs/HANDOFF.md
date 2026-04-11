# Handoff

> This file is rewritten at the end of every session. Read after CLAUDE.md.

## Current state as of 2026-04-11

**Last worked on:** P1 (Auto Curriculum Pipeline) + P2 (User Experience) + Security hardening + Admin UI
**Branch:** master
**Live site:** https://automateedge.cloud

## What got done this session (2026-04-11, evening)

### P1: Auto Curriculum Pipeline (complete)
- DB models: `CurriculumSettings` (singleton config), `DiscoveredTopic` (lifecycle state machine)
- Alembic migration `d4a1c8e92f3b` — applied on VPS
- Auto-discovery service: AI researches trending topics (Gemini/Groq), triage filter, dedup
- Batch generation: 5 variants per approved topic (3mo/6mo x beginner/intermediate/advanced)
- Content refresh: link health checks (SSRF-safe) + AI currency review
- File-based AI cache + token budget enforcement (3-tier system)
- Background scheduler (6-hour check interval, configurable frequency)
- Admin pipeline UI: 3 pages (dashboard, topics, settings) with manual trigger buttons
- All follows AI Enrichment + Normalization blueprints

### P2: User Experience (complete)
- 3-step plan picker: Topic → Duration → Level → Preview with stats
- Course history in profile modal (all plans with progress bars)
- Profile modal only closes on X button (not background click)

### Security hardening (Codex audit)
- SSRF: blocked private IPs/metadata in link checker, disabled redirects
- CSRF: strict hostname comparison, reject missing Origin/Referer
- Input validation: Pydantic model for settings API
- Prompt injection: sanitized DB strings in AI prompts
- Pagination: topics API limited to 50/page

### Admin UI improvements
- Unified nav across all admin pages (6 links)
- Matched main site header: Fraunces/IBM Plex fonts, sticky glassmorphism navbar, SVG logo
- Created docs/ADMIN_PAGES.md — comprehensive reference for all 7 admin pages

### Infrastructure
- GitHub MCP server configured (.mcp.json, gitignored)
- RCA log updated (entries 011-015)
- Memory updated: agent strategy, RCA rules, GitHub MCP, Codex contributions

## Credentials status

| Credential | Status |
|-----------|--------|
| SMTP App Password | Rotated (prrw...) |
| Groq API Key | Rotated (gsk_PWf...) |
| Google OAuth | Safe (never in git) |
| Gemini API | Spend-capped (PersonalAI project) |
| JWT Secret | Safe |
| GitHub MCP Token | gho_ OAuth from gh CLI (in .mcp.json, gitignored) |

## Tests

**Passing:** 90 automated
**Failing:** none (new pipeline code has no tests yet — Codex test gap analysis failed to read files)

## Next session priorities

1. **Test P1 live** — Run Discovery Now from admin pipeline, approve topics, generate templates
2. **P3: Email** — Check SPF propagation, possibly add DKIM
3. **P4: Content** — Generate specialist templates (NLP, CV, MLOps) via pipeline
4. **Future:** AI News Feed, AI Job Board

## Key files changed

| File | Change |
|------|--------|
| `backend/app/models/curriculum.py` | Added CurriculumSettings, DiscoveredTopic |
| `backend/app/services/topic_discovery.py` | NEW — AI topic discovery |
| `backend/app/services/batch_generator.py` | NEW — template generation |
| `backend/app/services/content_refresh.py` | NEW — link health + currency review |
| `backend/app/services/budget.py` | NEW — token budget enforcement |
| `backend/app/services/ai_cache.py` | NEW — file-based AI cache |
| `backend/app/services/pipeline_scheduler.py` | NEW — background scheduler |
| `backend/app/routers/pipeline.py` | NEW — pipeline admin API + UI (3 pages) |
| `backend/app/routers/admin.py` | Updated nav, fonts, header |
| `backend/app/routers/profile.py` | Added plan_history to profile response |
| `frontend/index.html` | 3-step plan picker, course history, modal fix |
| `docs/ADMIN_PAGES.md` | NEW — admin pages reference |
| `docs/RCA.md` | Entries 011-015 |

---

## Session history

| Date       | Summary |
|------------|---------|
| 2026-04-10 | Phases 1-12 built, tested, deployed. OAuth, OTP, PDF, admin. |
| 2026-04-10 | Launch: OAuth fix, email config, docs, credential setup. |
| 2026-04-11 | AI features live, nav/UX redesign, email reminders, leaderboard, dynamic templates, blueprints. |
| 2026-04-11 | P1 pipeline + P2 UX + security hardening + admin UI + GitHub MCP. |
