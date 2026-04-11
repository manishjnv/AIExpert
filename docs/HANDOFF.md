# Handoff

> This file is rewritten at the end of every session. Read after CLAUDE.md.

## Current state as of 2026-04-11

**Last worked on:** Post-launch features + AI curriculum pipeline foundation
**Branch:** master
**Live site:** https://automateedge.cloud

## What got done this session (2026-04-11)

- Fixed Gemini model (1.5-flash retired → 2.0-flash-lite)
- Set up Groq API as fallback (key rotated)
- Fixed SSE stream fallback (Gemini 429 → Groq)
- AI Chat tested and working (structured responses, markdown rendering)
- AI Evaluation tested and working
- Repo linking tested and working
- OTP sign-in modal (Google SSO + email OTP two-step flow)
- Top nav redesigned (brand icon, grouped buttons, gold Sign In CTA)
- Dynamic hero title based on plan
- Personalized eyebrow text
- Connection badges (Google/GitHub/LinkedIn with verification)
- Account Settings modal (simplified, inline plan switch)
- Contact form with email delivery + About modal
- Footer redesigned (About, Leaderboard, Contact Us, Source Code)
- Scroll-to-top button
- Mobile responsiveness
- Weekly email reminders (with unsubscribe, throttling, 400/run cap)
- Public profiles + leaderboard (opt-in, medals, streaks, progress bars, lifetime stats)
- Dynamic plan picker (loads from /api/templates)
- Admin template generation page (AI-powered)
- Credential rotation (SMTP password + Groq key)
- SPF record updated for Gmail
- Chat prompt expanded with full platform context
- Architecture blueprints committed (AI Enrichment + Normalization)

## Credentials status

| Credential | Status |
|-----------|--------|
| SMTP App Password | Rotated (prrw...) |
| Groq API Key | Rotated (gsk_PWf...) |
| Google OAuth | Safe (never in git) |
| Gemini API | Spend-capped (PersonalAI project) |
| JWT Secret | Safe |

## Tests

**Passing:** 90 automated
**Failing:** none

---

## Session history

| Date       | Summary |
|------------|---------|
| 2026-04-10 | Phases 1-12 built, tested, deployed. OAuth, OTP, PDF, admin. |
| 2026-04-10 | Launch: OAuth fix, email config, docs, credential setup. |
| 2026-04-11 | AI features live, nav/UX redesign, email reminders, leaderboard, dynamic templates, blueprints. |
