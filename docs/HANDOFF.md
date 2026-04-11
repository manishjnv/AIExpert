# Handoff

> This file is rewritten at the end of every session. Read after CLAUDE.md.

## Current state as of 2026-04-11 (session 2)

**Last worked on:** P1 pipeline live testing, 4 new AI providers, Resend email, provider fixes
**Branch:** master
**Live site:** https://automateedge.cloud

## What got done this session (2026-04-11, session 2)

### P1 Pipeline — Tested Live

- **Discovery**: Triggered from admin API, 10 topics discovered via Groq (Gemini was 429'd)
- Topics: Vision-Language Models, Efficient Transformers, Adversarial Robustness in CV, Multimodal Few-Shot Learning, Explainable RL, Graph Neural Networks, Transfer Learning for Edge AI, Causal Inference, Autonomous Exploration in RL, Explainable Time Series Forecasting
- All 10 approved, batch generation triggered
- **28 templates generated** across 8 topics (2 topics still have failed variants from rate limits)
- Budget tracking works (tokens_used_this_month increments correctly)
- Triage, dedup, schema validation all working

### 4 New AI Providers Added

- **Cerebras** (`cerebras.py`): llama3.1-8b (was llama-3.3-70b, retired)
- **Mistral** (`mistral.py`): mistral-small-latest, added markdown code block JSON parsing
- **DeepSeek** (`deepseek.py`): deepseek-chat (402 insufficient balance — needs top-up)
- **Sambanova** (`sambanova.py`): Meta-Llama-3.3-70B-Instruct, 4096 max_tokens
- **Fallback chain**: Gemini → Groq → Cerebras → Mistral → DeepSeek → Sambanova
- **Streaming**: all 6 providers available for chat via shared `_stream_openai_compat()` helper
- **Pipeline settings UI**: all 6 providers selectable for research/formatting models
- **Anthropic/Claude**: config fields added, key on VPS, NOT in fallback chain (reserved, needs user permission)

### P3 Email — Resend SMTP

- Switched from Gmail SMTP (587/STARTTLS) to Resend (465/SSL)
- Domain verified: automateedge.cloud in Resend (auto-configured via Cloudflare)
- DKIM: `resend._domainkey.automateedge.cloud` (RSA key, verified)
- SPF: `send.automateedge.cloud` includes amazonses.com
- **"via gmail.com" fixed** on platform-sent emails (OTP, reminders, contact form)
- Manual Gmail replies still show "via gmail.com" (Gmail limitation, not fixable without Google Workspace)
- Added `SMTP_USE_TLS` config option for port 465/SSL vs 587/STARTTLS

### Bug Fixes

- **Cerebras model retired**: llama-3.3-70b → llama3.1-8b
- **Mistral non-JSON**: Added markdown code block extraction for JSON responses
- **Sambanova truncation**: Increased max_tokens from 2048 to 4096 (all new providers)
- **Week schema too strict**: Added default values for optional fields (checks, focus, deliv, resources)
- **nginx timeout**: Admin routes now allow 600s for pipeline operations
- **Container rebuild**: Must use `--build` not just `--force-recreate` for code changes (RCA pattern)

## Credentials status

| Credential | Status |
|-----------|--------|
| SMTP (Resend) | re_... key on VPS .env, verified domain |
| Groq API Key | On VPS, working but rate-limited |
| Gemini API | On VPS, rate-limited (free tier) |
| Cerebras API | On VPS, working (llama3.1-8b) |
| Mistral API | On VPS, working |
| DeepSeek API | On VPS, 402 insufficient balance |
| Sambanova API | On VPS, working (rate-limited under load) |
| Anthropic API | On VPS, NOT wired up (reserved) |
| Google OAuth | Safe (never in git) |
| JWT Secret | Safe |

## Tests

**Passing:** 90 automated
**Failing:** none

## Key files changed this session

| File | Change |
|------|--------|
| `backend/app/ai/cerebras.py` | NEW — Cerebras provider wrapper |
| `backend/app/ai/mistral.py` | NEW — Mistral provider wrapper |
| `backend/app/ai/deepseek.py` | NEW — DeepSeek provider wrapper |
| `backend/app/ai/sambanova.py` | NEW — Sambanova provider wrapper |
| `backend/app/ai/provider.py` | REWRITTEN — 6-provider fallback chain |
| `backend/app/ai/stream.py` | REWRITTEN — 6-provider streaming with shared helper |
| `backend/app/config.py` | Added 4 new provider configs + anthropic + smtp_use_tls |
| `backend/app/curriculum/loader.py` | Week schema: default values for optional fields |
| `backend/app/routers/pipeline.py` | Settings validation + UI for 6 providers |
| `backend/app/services/email_sender.py` | Configurable TLS mode (SSL vs STARTTLS) |
| `backend/app/services/weekly_reminder.py` | Configurable TLS mode |
| `backend/app/routers/contact.py` | Configurable TLS mode |
| `nginx.conf` | Admin route 600s timeout |
| `.env.example` | All new provider docs + Resend SMTP |

## Next session priorities

1. **Re-run generation** for remaining 2 topics (wait for rate limits to reset)
2. **Review generated templates** — 28 templates on VPS, check quality
3. **Wire up Anthropic/Claude** for curriculum gen if user approves
4. **Top up DeepSeek** or remove from chain (402 insufficient balance)
5. **P4: Content** — Generate specialist templates (NLP, CV, MLOps) via pipeline
6. **Future:** AI News Feed, AI Job Board

---

## Session history

| Date | Summary |
|------|---------|
| 2026-04-10 | Phases 1-12 built, tested, deployed. OAuth, OTP, PDF, admin. |
| 2026-04-10 | Launch: OAuth fix, email config, docs, credential setup. |
| 2026-04-11 | AI features live, nav/UX redesign, email reminders, leaderboard, dynamic templates, blueprints. |
| 2026-04-11 | P1 pipeline + P2 UX + security hardening + unified nav + account page + admin UI. 20+ commits. |
| 2026-04-11 | P1 live test, 4 new AI providers, Resend email, provider fixes. 28 templates generated. |
