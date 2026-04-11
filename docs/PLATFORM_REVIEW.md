# AI Roadmap Platform — Comprehensive Review

**Date:** April 11, 2026
**Reviewer:** Claude (AI-assisted audit)
**Scope:** Implementation status, pending features, improvements, and free AI model opportunities

---

## 1. Implementation Status

### Fully Implemented (Phases 1–12 + Post-Launch)

| Area | What's Built | Quality Assessment |
|------|-------------|-------------------|
| **Skeleton & Stack** | FastAPI + Docker Compose + nginx | Production-ready, 3-container architecture |
| **Database** | 12 tables, async SQLAlchemy 2.0, WAL mode, 5 Alembic migrations | Solid schema, proper relationships |
| **Auth** | Google OAuth (Authlib) + Email OTP + JWT sessions | Well-secured: hashed OTPs, rate limiting, server-side session revocation |
| **Plans & Progress** | Enrollment, progress tracking, anonymous→signed-in migration | Debounced saves, localStorage fallback |
| **Profiles** | CRUD, export, delete cascade, plan history | GDPR-ready data export |
| **GitHub Integration** | Repo linking, validation, content fetching | Handles 404/403 gracefully |
| **AI Evaluation** | Gemini→Groq fallback, secret sanitization, 24h cooldown | Robust sanitizer, 20KB cap |
| **AI Chat** | SSE streaming, week-scoped context, 20 msg/hr rate limit | Stateless, clean architecture |
| **LinkedIn Sharing** | Public milestone pages, dynamic SVG OG images | Good social preview support |
| **Admin Panel** | 7 pages: dashboard, users, proposals, pipeline (3), settings | Server-rendered Jinja2, unified nav |
| **Quarterly Sync** | Cron container, curated source fetching, AI proposal generation | Generates markdown proposals for review |
| **Auto Curriculum Pipeline (P1)** | Topic discovery, triage, batch generation, content refresh, budget tracking | Most sophisticated component — follows enrichment & normalization blueprints |
| **UX (P2)** | 3-step plan picker, course history, profile modal | Clean progressive enhancement |
| **Security Hardening** | SSRF blocking, CSRF checks, input validation, prompt injection guards | Codex audit — 5 issues fixed |

**Test Coverage:** 90 automated tests passing across 20 test files, 0 failures.

**Live Deployment:** https://automateedge.cloud (Docker Compose on VPS, Caddy TLS, Cloudflare DNS)

---

## 2. Pending Features & Gaps

### Explicitly Planned but Not Yet Done

| Item | Priority | Notes |
|------|----------|-------|
| **P1 live testing** | HIGH | Discovery pipeline built but never run end-to-end in production. Must trigger "Run Discovery Now" from admin, approve topics, generate templates. |
| **Email SPF/DKIM (P3)** | HIGH | SPF propagation needs checking; DKIM not configured yet. Without these, OTP emails may land in spam. |
| **Specialist templates (P4)** | MEDIUM | Only generalist templates exist. NLP, CV, MLOps, GenAI specialist tracks are planned but not generated. |
| **Pipeline tests** | MEDIUM | Handoff explicitly notes "new pipeline code has no tests yet." The topic discovery, batch generator, content refresh, budget, and cache services are untested. |
| **CI/CD** | MEDIUM | No automated CI pipeline. Tests run locally only. A GitHub Actions workflow would catch regressions. |
| **Offline sync** | LOW | PRD mentions "ticks save to localStorage and sync when connection returns" — unclear if the reconnection sync is fully implemented. |

### PRD Features Not Fully Addressed

| PRD Feature | Status | Gap |
|-------------|--------|-----|
| **F6: Broken link detection** | Partial | Content refresh service exists but weekly cron for resource URL checking isn't clearly wired. |
| **F12: Old vs new topic comparison** | Partial | `addedIn`, `revision`, `outdated` fields exist in plan templates but the "X new topics since your last visit" banner and dismissal logic aren't confirmed in the frontend. |
| **F7: Capstone celebration** | Unclear | PRD specifies "completing all weeks triggers a capstone celebration state" — not confirmed in frontend code. |
| **F14: Per-week completion rates** | Partial | Admin dashboard has aggregate stats but per-week completion heatmap not confirmed. |

### Deferred (v2 Backlog, from PRD "Not in Scope")

These were explicitly deferred but worth tracking for future planning: email/push notifications, gamification (badges, streaks, XP), social features (leaderboards, comments), multi-language support, WCAG AAA accessibility audit, mobile native apps.

---

## 3. Scope of Improvement

### Architecture & Performance

**3.1 Database scaling path.** SQLite is fine for early traction but will bottleneck at ~100 concurrent writers. Plan a migration path to PostgreSQL before hitting 1,000 active users. The async SQLAlchemy setup makes this a config change — prepare an Alembic migration and test it early.

**3.2 Connection pooling.** The Gemini and Groq clients create a new `httpx.AsyncClient` per request (`async with httpx.AsyncClient()`). A shared client with connection pooling would reduce latency by 50-100ms per AI call and avoid TCP connection overhead.

**3.3 Background task robustness.** The pipeline scheduler uses `asyncio.sleep` in a loop. If the process crashes mid-discovery, there's no recovery. Consider adding a `last_run_status` column to `CurriculumSettings` and a startup check that resumes incomplete runs.

**3.4 Caching layer.** The file-based AI cache is functional but fragile (no TTL cleanup, no size limits). A lightweight Redis instance or even SQLite-backed cache with automatic eviction would be more reliable.

### Code Quality

**3.5 Missing pipeline tests.** This is the highest-priority code quality gap. The topic discovery, batch generator, and content refresh services are the most complex code in the system and have zero test coverage. At minimum, add unit tests with mocked AI responses.

**3.6 Error granularity in provider.** The provider router catches `GeminiError` as a single class. Distinguishing between "invalid API key" (401, permanent) and "server error" (500, transient) would prevent wasting retry attempts on non-retryable failures.

**3.7 Structured logging.** The codebase uses `logger.info/warning/error` with string formatting. Switching to structured logging (JSON format) would make log parsing via `scripts/ai-usage-report.py` more reliable and enable better observability.

### Security

**3.8 JWT secret rotation.** There's no mechanism for rotating the JWT secret without invalidating all sessions. Consider a dual-secret approach where the verifier accepts either the current or previous secret during a rotation window.

**3.9 Rate limiting persistence.** Slowapi rate limits are in-memory. A backend restart resets all rate limits. For a single-instance deployment this is acceptable, but note it as a known limitation.

**3.10 Content Security Policy.** The frontend loads from nginx but there's no CSP header configured. Adding a strict CSP would protect against XSS.

### User Experience

**3.11 Mobile responsiveness.** The single-file frontend uses CSS custom properties and a responsive grid, but no confirmation of testing on mobile devices. The chat panel, plan picker modal, and evaluation display should be tested on small screens.

**3.12 Accessibility.** WCAG AA compliance is the default target per the PRD, but no accessibility audit has been performed. Screen reader testing, keyboard navigation, and color contrast checks are needed.

**3.13 Progressive Web App.** Adding a service worker and manifest would enable offline access to the curriculum (read-only) and push notifications (v2 feature).

---

## 4. Free AI Model Alternatives & Opportunities

### Current Setup

| Role | Provider | Model | Free Limits |
|------|----------|-------|-------------|
| Primary | Google Gemini | 1.5 Flash | 15 RPM, 1.5K req/day, 1M tokens/min |
| Fallback | Groq | LLaMA 3.3 70B | 30 RPM, no daily cap |
| Quarterly sync | Google Gemini | 1.5 Pro | 2 RPM, 50 req/day |

### Recommended Additions (Zero Cost, High Value)

**4.1 Cerebras — Add as a fast evaluation fallback**

Cerebras offers 1M free tokens/day with an OpenAI-compatible API and inference speeds of ~2,600 tokens/sec (faster than Groq). Models include LLaMA 3.1 8B and 70B. Since your Groq client already uses the OpenAI chat completions format, integrating Cerebras would be a near-copy of `groq.py` with a different base URL and API key. This gives you a 3-provider chain: Gemini → Groq → Cerebras.

**Integration effort:** ~30 minutes. Copy `groq.py` → `cerebras.py`, change the URL to `https://api.cerebras.ai/v1/chat/completions`, add `CEREBRAS_API_KEY` to config.

**4.2 SambaNova — Best for deep code evaluation**

SambaNova provides persistent free access to LLaMA 3.3 70B and LLaMA 3.1 405B (the largest open model). The 405B model would give significantly better code evaluation quality for the `POST /api/evaluate` endpoint. OpenAI-compatible API. Rate limited to 10-30 RPM.

**Use case:** Route evaluation requests specifically to SambaNova's 405B model for higher accuracy, while keeping Gemini Flash for chat (where speed matters more than depth).

**4.3 Mistral — Good for topic discovery**

Mistral's La Plateforme offers 1 billion free tokens/month (with data-sharing opt-in). Their Codestral model is strong for technical content analysis. The generous token budget makes it ideal for the quarterly curriculum discovery pipeline, which involves processing large amounts of source material.

**Trade-off:** Requires opting into Mistral's data-sharing policy for the free tier. For curriculum research (not user PII), this is acceptable.

**4.4 DeepSeek — Budget-friendly supplementary provider**

DeepSeek offers 5M free tokens with their V3 and R1 models. The R1 "reasoning" model is particularly strong for structured analysis tasks like code evaluation. OpenAI-compatible API with no rate limits on the free tier.

**Use case:** Use DeepSeek R1 as a secondary evaluation provider when you want a "second opinion" on code quality, or as a fallback when all other providers are rate-limited.

### About OpenClaw AI

OpenClaw is an open-source autonomous agent framework, not a model provider. It orchestrates calls to other AI models (similar to LangChain/CrewAI). It's not directly useful here since your provider abstraction already handles model routing. However, if you later build more complex AI workflows (multi-step evaluation pipelines, agent-based curriculum generation), OpenClaw could be worth evaluating as an orchestration layer.

### Recommended Provider Strategy (Updated)

```
Code Evaluation:   Gemini Flash → SambaNova 405B → Groq 70B → Cerebras
Chat Assistant:    Gemini Flash → Groq 70B → Cerebras (speed priority)
Topic Discovery:   Mistral (1B tokens/month) → Gemini Flash
Triage Classifier: Groq 8B (cheapest/fastest) → Cerebras 8B
Quarterly Sync:    Gemini Pro → DeepSeek R1 (reasoning model)
```

This gives you 5 free providers with independent rate limits, making it nearly impossible to hit a complete outage. Total daily free capacity would exceed 5M tokens — enough for thousands of evaluations and chat messages.

### Implementation Priority

| Change | Effort | Impact | Priority |
|--------|--------|--------|----------|
| Add Cerebras as 3rd fallback | 30 min | High resilience | P1 |
| Route evaluations to SambaNova 405B | 1 hour | Better eval quality | P1 |
| Add Mistral for discovery pipeline | 1 hour | 1B tokens/month for research | P2 |
| Add DeepSeek R1 for quarterly sync | 1 hour | Better reasoning for proposals | P2 |
| Refactor provider.py for N providers | 2 hours | Cleaner multi-provider routing | P2 |

---

## 5. Summary of Recommendations

**Immediate (this week):**
1. Run the P1 pipeline end-to-end in production — this is the highest-risk untested feature
2. Write tests for the pipeline services (topic_discovery, batch_generator, content_refresh)
3. Verify email deliverability (SPF/DKIM) — OTP emails hitting spam will kill onboarding
4. Add Cerebras as a third fallback provider (30 minutes, high resilience gain)

**Short-term (next 2 weeks):**
5. Use SambaNova 405B for code evaluations (significantly better quality, free)
6. Add Mistral to the discovery pipeline (1B free tokens/month)
7. Refactor `provider.py` into a configurable provider chain supporting N providers
8. Share the httpx client across AI calls (connection pooling)
9. Add a CI/CD pipeline (GitHub Actions)

**Medium-term (next month):**
10. Generate specialist templates (NLP, CV, MLOps, GenAI) via the pipeline
11. Complete the "new topics since last visit" banner (PRD F12)
12. Mobile responsiveness testing and fixes
13. WCAG AA accessibility pass
14. Plan the SQLite → PostgreSQL migration path

**Long-term (v2):**
15. Email/push notifications for weekly reminders
16. Gamification (streaks, badges)
17. PWA with offline curriculum access
18. Multi-provider intelligent routing (cost/quality/speed optimization)
