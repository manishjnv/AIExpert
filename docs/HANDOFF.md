# Handoff

> This file is rewritten at the end of every session. Read after CLAUDE.md.

## Current state as of 2026-04-11 (session 3)

**Last worked on:** AI usage dashboard, circuit breaker, normalization pipeline, Resend email, 4 new AI providers, admin UI overhaul
**Branch:** master
**Live site:** https://automateedge.cloud

## What got done this session (2026-04-11, session 3)

### P1 Pipeline — Tested Live
- Discovery: 11 topics discovered (10 via Groq, 1 via Mistral)
- Batch generation: 28 templates generated across 10 topics
- Circuit breaker correctly cascaded through 6 providers
- Discovery default changed from 10 to 1 topic (quality-first)

### 4 New AI Providers
- Cerebras (llama3.1-8b), Mistral (mistral-small-latest), DeepSeek (deepseek-chat), Sambanova (Meta-Llama-3.3-70B-Instruct)
- 6-provider fallback chain: Gemini → Groq → Cerebras → Mistral → DeepSeek → Sambanova
- Streaming support for all 6 via shared `_stream_openai_compat()` helper
- Provider fixes: Cerebras model retired, Mistral JSON parsing, max_tokens 2048→4096
- Anthropic/Claude key on VPS (reserved, not in fallback chain)

### AI Usage Dashboard (`/admin/pipeline/ai-usage`)
- Provider health cards with human-readable status (Working/Cooling down/Down + plain-English reasons)
- Usage by Provider table (calls, success rate, avg speed)
- Usage by Task table (per task+subtask breakdown)
- Recent Calls log (last 50, friendly status badges)
- Circuit breaker: 402/404 = permanent unavailable, 429 = 60s cooldown, Reset button

### AIUsageLog DB Model + Migration
- New `ai_usage_log` table: provider, model, task, subtask, status, error, tokens, latency
- Migration `e7b3a1f45c2d` — applied on VPS
- Logged from provider.py on every AI call (discovery, generation tasks pass db+task+subtask)

### Pipeline Page Overhaul (`/admin/pipeline/`)
- Actions at top (Discover, Generate, Refresh) with human-readable result messages
- Pipeline Status section below (loaded from /api/normalization)
- 10 Pipeline Stages reference with AI markers (gold "AI" label + token costs)
- Color-coded: Gold=cleanup, Blue=AI enrichment, Green=process, Red=maintenance
- Normalization page merged into Pipeline (separate page redirects 301)

### P3 Email — Resend SMTP
- Switched from Gmail SMTP to Resend (port 465/SSL, DKIM signed)
- Domain verified: automateedge.cloud (auto-configured via Cloudflare)
- "via gmail.com" fixed on platform emails (OTP, reminders, contact form)
- Added SMTP_USE_TLS config for SSL vs STARTTLS

### Admin UI Overhaul
- **Dashboard** (`/admin/`): platform overview — users, enrolled, templates, topics, broken links, recent signups, quick actions
- **Users** (`/admin/users`): detailed user activity — logins today/week, sessions, anonymous visitors, auth breakdown + table with Location (geo-lookup), Device, IP, Plan, Last Login
- No overlap between Dashboard and Users
- Anonymous visitor tracking via middleware (public page hits without auth cookie)
- Favicon (SVG) on all pages via nav.js auto-injection

### Bug Fixes
- Users page crash: `sess.ip` without null check for users with no sessions
- nginx timeout: admin routes 600s for pipeline operations
- Week schema: default values for optional fields (prevents AI validation failures)

## Credentials status

| Credential | Status |
|-----------|--------|
| SMTP (Resend) | re_... key on VPS, domain verified, DKIM active |
| Gemini API | On VPS, rate-limited (free tier) |
| Groq API | On VPS, rate-limited (free tier) |
| Cerebras API | On VPS, working (llama3.1-8b) |
| Mistral API | On VPS, working |
| DeepSeek API | On VPS, 402 insufficient balance |
| Sambanova API | On VPS, working |
| Anthropic API | On VPS, NOT wired up (reserved) |
| Google OAuth | Safe |
| JWT Secret | Safe |

## Tests

**Passing:** 88 (2 repo tests flaky from GitHub API rate limit — not our code)
**Failing:** 2 flaky (test_repos — GitHub API rate limited in CI)

## Key files changed this session

| File | Change |
|------|--------|
| `backend/app/ai/cerebras.py` | NEW — Cerebras provider |
| `backend/app/ai/mistral.py` | NEW — Mistral provider |
| `backend/app/ai/deepseek.py` | NEW — DeepSeek provider |
| `backend/app/ai/sambanova.py` | NEW — Sambanova provider |
| `backend/app/ai/health.py` | NEW — circuit breaker + usage logging |
| `backend/app/ai/provider.py` | 6-provider fallback + circuit breaker + usage logging |
| `backend/app/ai/stream.py` | 6-provider streaming + circuit breaker |
| `backend/app/models/curriculum.py` | AIUsageLog model, discovery default 1 |
| `backend/app/routers/pipeline.py` | AI Usage page, normalization API, pipeline stages |
| `backend/app/routers/admin.py` | Dashboard + Users overhaul |
| `backend/app/main.py` | Anonymous visitor tracking middleware |
| `backend/app/config.py` | 4 new providers + anthropic + smtp_use_tls |
| `backend/app/services/email_sender.py` | Configurable TLS |
| `backend/app/services/weekly_reminder.py` | Configurable TLS |
| `backend/app/routers/contact.py` | Configurable TLS |
| `backend/app/curriculum/loader.py` | Week schema defaults |
| `frontend/nav.js` | Favicon injection, AI Usage nav link |
| `frontend/favicon.svg` | NEW — SVG favicon |
| `nginx.conf` | Admin 600s timeout, favicon route |
| `.env.example` | All new providers + Resend |
| `alembic/.../e7b3a1f45c2d_...py` | NEW — ai_usage_log migration |

## Next session priorities

1. **Re-run generation** for remaining 2 topics (rate limits reset)
2. **Review template quality** — check AI-generated curricula content
3. **Wire up Anthropic/Claude** for curriculum gen (needs user approval)
4. **Top up DeepSeek** or remove from chain (402)
5. **P4: Specialist templates** — NLP, CV, MLOps via pipeline
6. **Future:** AI News Feed, AI Job Board

---

## Session history

| Date | Summary |
|------|---------|
| 2026-04-10 | Phases 1-12 built, tested, deployed. OAuth, OTP, PDF, admin. |
| 2026-04-10 | Launch: OAuth fix, email config, docs, credential setup. |
| 2026-04-11 | AI features live, nav/UX redesign, email reminders, leaderboard, dynamic templates, blueprints. |
| 2026-04-11 | P1 pipeline + P2 UX + security hardening + unified nav + account page + admin UI. 20+ commits. |
| 2026-04-11 | P1 live test, 4 new AI providers, Resend email, AI usage dashboard, circuit breaker, admin overhaul. |
