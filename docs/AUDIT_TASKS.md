# Audit Remediation — Master Backlog

> **Source:** Merged from `docs/AUDIT_2026-04.md` (v2, 2026-04-26 self-audit) + the prior `docs/AUDIT_TASKS.md` sequenced backlog.
> **Last merged:** 2026-04-28 (after S49 + S50).
> **Use:** This is THE backlog. Pick one P-tier item (or a tightly-related cluster from the same tier) per session. Do not bundle across tiers.
> **Status legend:** ⬜ not started · 🟡 in progress · ✅ done · ⏭️ deferred (with reason) · 🟢 partial (started; remaining noted)
> **Sizing:** **D** = decision-only (no code) · **XS** ≤ 30 min · **S** ≤ 1 session (~2-3h) · **M** = 1 session · **L** = 2-3 sessions · **XL** = a sprint

---

## §0 What's been done since the 2026-04-26 audit

- **S49 (2026-04-27)** — Shipped anonymous-funnel subscribe ribbons on `/jobs`, `/roadmap`, `/blog`, `/blog/{slug}`. Increases visibility of the existing notify-channel signup, but **does not retire B5** (engagement is still email-only behind those buttons). Channel diversification (Web Push / Telegram) still pending.
- **S50 (2026-04-27)** — Shipped `docs/AI_PIPELINE_PLAN.md` (centralized AI strategy doc, supersedes the dormant `PLAN_TIERED_CLAUDE_ROUTING.md`) + Claude Code harness Day-1: 2 PreToolUse hooks (pre_commit_secrets, pre_push_noreply) + 2 skills (`/aiexpert-phase0`, `/deploy-vps`) under `.claude/`. **Partially addresses P1-08 / F5** at the *local* level — pre-commit hook now blocks AKIA-style patterns and warns on TODO/FIXME. CI-side gates (pip-audit, gitleaks, JS smoke) still pending.
- **2026-04-26 (pre-audit)** — `auto_summarize_drafts.sh` Opus cron shipped for jobs editorial summaries (Track 1, $0 marginal via Max OAuth). Independent of audit; underwrites Phase B of `AI_PIPELINE_PLAN.md`.

---

## §1 P0 — Founder decisions (no code, but block downstream work)

These are **founder-only** decisions. Engineering work in P1+ assumes these have answers. Make them in one sitting; record answers in `CLAUDE.md` §9 or a new `docs/DECISIONS.md`.

| # | Audit ID | Decision | Sizing | Why now | Acceptance |
|---|----------|----------|--------|---------|------------|
| D1 | I5 / J2 | **Brand rename: yes or no?** If yes, pick replacement domain. | D | Compounds against every GTM motion. Irreversible after PH/HN launch. | Decision recorded; if rename, domain registered. |
| D2 | J1 | **Monetization sequence:** affiliate (a) → premium (b) → B2B tenant (c)? Or different order? | D | Affiliate already plumbed; (b)/(c) need it as proof. Sequencing affects Q2 calendar. | Three-line written plan with "first revenue by date." |
| D3 | H9 / H11 | **Cert credibility approach:** reframe-only (10 min) vs reframe + add quiz (sprint) vs add quiz keep "graduation" wording (sprint). | D | Determines whether P1-02 is one PR or rolls into P2-02. | Pick one; written in DECISIONS.md. |
| D4 | H5 | **Cohort delivery:** native widget vs Discord vs both. | D | Affects whether P2-03 is webhook or table+UI. | Pick one or pick the order. |
| D5 | A3 | **Backup destination:** Cloudflare R2 / Backblaze B2 / second VPS. | D | Determines compose service shape in P2-07. | Account created at chosen provider; bucket name written down. |
| D6 | D5 | **CSRF approach:** global `_check_origin` middleware vs documented X-CSRF-Token. | D | Frontend touches differ. P1-06 implementation depends on this. | Pick one; SECURITY.md updated to match. |
| D7 | J5 | **`codex:rescue`: fix or drop.** | D | 0/N over recent sessions (now 10 in a row across S45–S50). Doc-vs-practice mismatch growing. | Either 1-2h debug ticket scheduled OR removed from CLAUDE.md §8. |
| D8 | (new) §7 of AI_PIPELINE_PLAN.md | **Repo evaluation: Option A (admin-only) / B (sync Flash) / D (sync Flash + Sonnet opt-in) / E (async cron, Opus, $0 marginal — recommended).** Plus per-user submission cap if E. | D | Phase E of `AI_PIPELINE_PLAN.md` cannot start without this. | Pick one; if E, set the per-user-per-day cap (default suggestion: 5/day free, 20/day paid). |

---

## §2 P1 — Now (target: Sessions 51–54, 4 sessions max)

**Theme: Make the cert truthful, the chat personalized, the brand decided, and the obvious paid-tier overruns gated.** Each task fits in one session unless noted.

### P1-01 ⬜ Coursera affiliate rewriter activation 🔥
- **Audit ID:** J1a (CRITICAL — first revenue path)
- **Severity:** CRITICAL business / **Effort:** S
- **Why P0:** Plumbing already exists (`config.py:114` `coursera_affiliate_id` empty default; `services/affiliate.py` exists). Just needs activation + Coursera Partner Network application + transparent disclosure.
- **Steps:** (1) Apply to Coursera Partner Network (Impact.com); (2) Once approved, populate `COURSERA_AFFILIATE_ID` on VPS `.env`; (3) Wire `services/affiliate.py.rewrite()` into the resource-render path (likely `routers/plans.py` or `curriculum/loader.py`); (4) Add a footer disclosure on every plan page; (5) Add the same for DeepLearning.AI and Udemy partner programs.
- **Acceptance:** Click on a Coursera resource link from a signed-in user's plan page produces a URL with the affiliate query string. Logged-out users see clean URLs (recruiters/share contexts). Test: `test_affiliate_rewrite_only_for_authed`.
- **Depends on:** D2 (monetization sequence pick must include affiliate as first move).

### P1-02 ⬜ Cert copy reframe ⏱️
- **Audit ID:** H9 (HIGH — credibility)
- **Severity:** HIGH / **Effort:** XS
- **Why P0:** Closes credibility gap in 10 minutes. Pair with D3; if D3 picks "add quiz first," skip this and do P2-02.
- **Steps:** Find every public-facing string that says "graduated" / "completion" / "graduation" tied to the cert. Replace with "verified learning record." Likely surfaces: `routers/verify.py`, `routers/certificates.py`, `services/certificate_pdf.py`, `frontend/index.html` cert section, `README.md:39-43`, weekly digest cert-issued email. Update OG card text generator if applicable.
- **Acceptance:** `grep -ri "graduation\|graduated" frontend/ backend/app/ docs/` returns only audit references. Live `/verify/<id>` page shows new wording.
- **Depends on:** D3.

### P1-03 ⬜ Inject user state into AI chat prompt 🎯
- **Audit ID:** H8 (HIGH — product value)
- **Severity:** HIGH / **Effort:** S
- **Why P0:** Single biggest user-perceived value lift available. Personalization wedge is in the data model already; just wire it into the system prompt.
- **Steps:** Extend `routers/chat.py:_learner_profile_block` to also inject (a) `completed_weeks: [1,2,3]`, (b) `recent_eval_scores: [{week, score, top_improvements: [str, ...]}]` (last 3), (c) `linked_repo_titles: [str, ...]`, (d) `current_week_progress_pct`. Bound combined block at 4 KB to protect context for chatty users. Update `prompts/chat.txt` to instruct the model to leverage this state without restating it. Add `test_chat_prompt_includes_user_progress`.
- **Acceptance:** Manual test: ask "what should I focus on next?" — response should reference at least one specific completed/in-progress week or eval score, not be generic.
- **Depends on:** none.

### P1-04 ⬜ Brevo daily-cap enforcement
- **Audit ID:** B4 (HIGH)
- **Severity:** HIGH / **Effort:** XS
- **Why P0:** Free-tier deliverability outage one digest run from happening. `MAX_EMAILS_PER_RUN=400` already over the 300/day cap.
- **Steps:** (1) Lower `weekly_digest.py:44` `MAX_EMAILS_PER_RUN` to 250 (leaves 50/day for OTPs). (2) Add `/data/email_quota.json` daily counter, atomic write (same pattern as RCA-019 chat-rate). (3) Short-circuit `email_sender.py.send_otp_email` + `weekly_digest.run_*` when quota exhausted; log a CRITICAL alert. (4) Reset at UTC midnight.
- **Acceptance:** Test: `test_brevo_quota_short_circuits_at_250`. Manual: simulate 250 sends, assert 251st raises with logged warning.
- **Depends on:** none.

### P1-05 ⬜ Gemini cost-cap gate
- **Audit ID:** C3 (HIGH)
- **Severity:** HIGH / **Effort:** XS
- **Why P0:** Largest paid-AI consumer is currently un-gated against admin-set caps.
- **Steps:** Move `from app.ai.pricing import check_cost_limit` import + call into `ai/provider.py:complete()` at the top of each provider attempt. Skip via `is_free()` for free-tier providers. Catch `CostLimitExceeded` and continue to the next provider in the chain (so a Gemini cap doesn't 503 the user — it gracefully falls back to free tier).
- **Acceptance:** Test: `test_provider_cost_cap_skips_provider_at_limit`. Manual: set Gemini admin cap to $0.01, fire 5 calls, observe fallback to Groq.
- **Depends on:** none.

### P1-06 ⬜ CSRF unification
- **Audit ID:** D5 (HIGH)
- **Severity:** HIGH / **Effort:** S
- **Why P0:** Doc-vs-code mismatch is a security finding by itself, and SameSite=Lax-only is below the bar SECURITY.md sets.
- **Steps:** **If D6 picks `_check_origin` middleware:** lift the function to `auth/csrf.py`, register as a global FastAPI middleware that runs before any state-changing handler, exempt `/api/auth/google/callback` (OAuth state param covers it). **If D6 picks X-CSRF-Token:** issue a separate non-httpOnly `csrf` cookie at sign-in (random 32 bytes), require frontend to echo into `X-CSRF-Token` header on POST/PATCH/DELETE, validate match server-side. Update `SECURITY.md` §CSRF to match.
- **Acceptance:** Test: `test_post_without_csrf_returns_403` covering 4 representative endpoints (`/api/profile`, `/api/repos/link`, `/api/evaluate`, `/api/progress`). SECURITY.md grep matches code.
- **Depends on:** D6.

### P1-07 ⬜ Doc-vs-code reconciliation pass
- **Audit ID:** Cross-cutting (HIGH)
- **Severity:** HIGH / **Effort:** S
- **Why P0:** Future Claude Code sessions act on stale docs. One-shot rewrite while every drift is fresh in mind.
- **Steps:** Rewrite (1) `CLAUDE.md` §2 to current state, (2) `docs/PRD.md:213-225` "Not in scope" section, (3) `docs/AI_INTEGRATION.md` prompt list (3 docs vs 17 actual), (4) `docs/DEPLOYMENT.md:74-115` Caddy/nginx topology, (5) `README.md:40` "truncated HMAC" → "HMAC-SHA256-signed", (6) `README.md:100` "127 passing" → "extensive test suite — see backend/tests/" or actual count, (7) `docs/SECURITY.md:90` JWT sliding-refresh claim or implement P3-08. (8) Delete `CLAUDE.md` §4 `pb_hooks/` line and fix `quarterly-sync.py` → `quarterly_sync.py`. (9) Sync `SMTP_FROM_NAME` between `.env` and `.env.example`.
- **Acceptance:** Diff-only review by founder; no behavior change.
- **Depends on:** none, but pair with D6 if it changes SECURITY.md anyway.

### P1-08 🟢 CI security gates (PARTIAL)
- **Audit ID:** F5 (HIGH)
- **Severity:** HIGH / **Effort:** S (remaining)
- **Status:** Local pre-commit secrets hook shipped in S50 (`.claude/hooks/pre_commit_secrets.py` covers AKIA / sk- / GitHub PAT / Google AIza / GOCSPX / Slack / hardcoded literal patterns + TODO/FIXME warn). **Remaining: GitHub Actions side.**
- **Why P0:** RCA-024 prevention rule has been logged for 12+ days without being wired in CI. Local hook covers the developer side; CI covers the "different developer / different machine / cloud build" side.
- **Steps remaining:** Add a second `security` job to `.github/workflows/ci.yml`: (1) `pip-audit` (already in requirements); (2) `gitleaks detect --no-git -v` against working tree; (3) Python-side `extract_inline_js.py` script that pulls `<script>...</script>` bodies out of every `routers/*.py` f-string and pipes through `node --check`. Fail the job on any non-zero exit.
- **Acceptance:** A PR that introduces a fake `AKIA[16-char]` literal fails the `security` job. A PR that introduces a JS syntax error in an admin HTML f-string fails too.
- **Depends on:** none.

---

## §3 P2 — Next (target: Sessions 55–60, this month)

**Theme: GTM launch + structural product gaps.**

### P2-01 ⬜ GTM week-1 launch 🚀
- **Audit ID:** J2 (HIGH — GTM motion)
- **Severity:** HIGH / **Effort:** L (a calendar week, not a code sprint)
- **Steps:** Pick a Tue/Wed US morning. Same day: Product Hunt + HN Show post. Same week: LinkedIn long-form ("488 commits later — what worked, what broke") + a Twitter thread. Following week: r/learnmachinelearning weekly progress + r/india for Bengaluru variant. Pre-write all four artifacts before launch day.
- **Acceptance:** All four channels posted within the same week. Track UTM-tagged signups per channel.
- **Depends on:** D1 (brand rename or stay), D2 (monetization sequence), P1-01 (so launch traffic monetizes).

### P2-02 ⬜ Quiz / MCQ assessment
- **Audit ID:** H11 (HIGH — credibility)
- **Severity:** HIGH / **Effort:** L
- **Steps:** Bring `quiz_outcomes` migration forward from queue (already on the SEO-26 list). 5-question monthly checkpoint per goal/level: 4 MCQ + 1 free-form. AI-graded via existing `provider.complete`. Cert tier gated on quiz pass + ≥1 graded repo. Admin UI to author/edit quiz banks per template.
- **Acceptance:** A user who skips all quizzes cannot reach `distinction` tier even at 100% checks done.
- **Depends on:** D3 if it picks "reframe-only" then this becomes P3.

### P2-03 ⬜ Cohort widget v1
- **Audit ID:** H5 (HIGH — retention)
- **Severity:** HIGH / **Effort:** M
- **Steps:** Build `/cohort/{week_num}` listing the last 20 users to start that week, anonymized to first name + tier. Opt-in via `User.cohort_visible` (re-use `public_profile` flag if scope-equivalent). Add a "Learners on Week N right now" widget to each weekly card for signed-in users.
- **Acceptance:** Test: `test_cohort_only_shows_optin_users`. Manual: tick the opt-in, refresh another browser, see yourself.
- **Depends on:** D4.

### P2-04 ⬜ Practice surfaces beyond GitHub
- **Audit ID:** H3 (HIGH — audience fit for AI/ML learners)
- **Severity:** HIGH / **Effort:** M
- **Steps:** Generalize `RepoLink` → `PracticeLink` with `kind` ∈ {github, kaggle, hf_space, colab}. Migration adds `kind` column, defaults existing rows to `github`. Update `services/evaluate.py` to dispatch per kind: GitHub keeps current path; Colab fetches notebook JSON; Kaggle fetches the notebook + metadata; HF Space fetches the README.md from the repo. Eval rubric extends naturally.
- **Acceptance:** Test: `test_link_colab_notebook_url_validates`. Manual: link a Colab notebook to a week, run eval, get a non-empty score.
- **Depends on:** none. **Note:** if D8 picks Option E (recommended), this is naturally bundled with the cron-based eval shape.

### P2-05 ⬜ Move `/api/evaluate` to background-task pattern
- **Audit ID:** B2 / B3 (MEDIUM)
- **Severity:** MEDIUM / **Effort:** M
- **Note:** **Largely subsumed by D8 / Option E** in `AI_PIPELINE_PLAN.md` §7. If D8 picks E, this task collapses into the cron-based repo-eval implementation. If D8 picks A/B, this remains a separate task.
- **Steps:** New `evaluation_jobs` table (id, repo_link_id, status, error, created_at, completed_at). `POST /api/evaluate` returns 202 + `evaluation_job_id`. New `/api/evaluations/job/{id}` for polling. Background coroutine processes the queue with retry-once on transient errors. UI: replace the inline spinner with a poll-every-2s + success-state.
- **Acceptance:** Test: `test_evaluate_returns_202_immediately`. p95 of `POST /api/evaluate` < 200ms.
- **Depends on:** D8.

### P2-06 ⬜ Health endpoint deepening
- **Audit ID:** G3 (MEDIUM)
- **Severity:** MEDIUM / **Effort:** S
- **Steps:** Public `/api/health` stays minimal (per RCA-021). Add `/api/admin/health` (admin-only) that pings: DB (`SELECT 1`), latest AI provider success in `AIUsageLog` within last 1h, SMTP DNS resolution, optional `/data` disk-free check. Return JSON with per-component status. Wire docker-compose healthcheck to a more meaningful predicate (still public but checks DB liveness via a count query).
- **Acceptance:** Stop the DB connection pool, hit `/api/admin/health`, see `db: down`. Public `/api/health` still 200.
- **Depends on:** none.

### P2-07 ⬜ Automated DB backups
- **Audit ID:** A3 (HIGH — reliability)
- **Severity:** HIGH / **Effort:** S
- **Steps:** Add a `backup` service to `docker-compose.yml` that runs `sqlite3 /data/app.db ".backup '/data/backups/app-${date}.db'"` daily at low-traffic hour. Retain 30 days. `rclone sync` to chosen off-site target (D5).
- **Acceptance:** Day after deploy, find dated backup file in `/data/backups/`. Restore-test once on the test VPS.
- **Depends on:** D5.

### P2-08 ⬜ PWA shell
- **Audit ID:** E2 (HIGH — mobile/offline)
- **Severity:** HIGH / **Effort:** S
- **Steps:** Add `frontend/manifest.webmanifest` (icons, name, start_url=/, display=standalone, theme_color matches index.html). Add `frontend/sw.js` service worker that caches `/`, `/nav.css`, `/nav.js`, `/account.html`, the current default plan JSON. `<link rel="manifest">` in index.html. `navigator.serviceWorker.register` on page load.
- **Acceptance:** Chrome install prompt fires. Disconnect network, refresh, see cached shell + last-week's plan.
- **Depends on:** P3-01 (frontend split makes this cleaner) — but can ship without it.

### P2-09 ⬜ Trim AI providers to 3
- **Audit ID:** C8 (MEDIUM)
- **Severity:** MEDIUM / **Effort:** XS
- **Steps:** Keep `gemini`, `anthropic`, `groq`. Remove (or feature-flag-guard) `cerebras`, `mistral`, `deepseek`, `sambanova` from `_PROVIDERS` in `ai/provider.py`. Don't delete the modules; archive under `ai/_archived/` so re-adding is a one-line move. Update `docs/AI_INTEGRATION.md`.
- **Acceptance:** All tests still pass. `_PROVIDERS` length is 3.
- **Depends on:** none.

### P2-10 ⬜ Engagement channel diversification
- **Audit ID:** B5 (MEDIUM)
- **Severity:** MEDIUM / **Effort:** S
- **Note:** S49 made the email signup *visible* via 4 ribbons but the channel itself is still email-only. This task is about adding a second channel (Web Push / Telegram) so retention has a fallback path when the email channel is full.
- **Steps:** Pick one (D-style decision; default to Web Push for cheapest path). Web Push: VAPID keys + service worker subscription + `/api/push/subscribe` + a small admin UI to send a test. Telegram: `@BotFather` setup + `/api/telegram/webhook` + invite flow on enrollment.
- **Acceptance:** Send a test from admin panel; receive on second device.
- **Depends on:** P2-08 (service worker exists for Web Push variant).

### P2-11 ⬜ Coverage in CI
- **Audit ID:** F2 (MEDIUM)
- **Severity:** MEDIUM / **Effort:** XS
- **Steps:** Add `--cov=app --cov-report=term-missing --cov-fail-under=70` to `ci.yml:58`. Then iterate to fill gaps in the lowest-covered modules (likely `pipeline.py`, `admin.py`, `blog.py` per their LoC).
- **Acceptance:** CI fails if any module drops below 70% line coverage.
- **Depends on:** none.

### P2-12 ⬜ 5 good-first-issue tickets + CONTRIBUTING.md + Discord
- **Audit ID:** J4 (MEDIUM — bus factor)
- **Severity:** MEDIUM / **Effort:** S
- **Steps:** Open 5 issues with `good-first-issue` label, each ≤ 1 weekend of work for a junior dev. Examples: "Wire Razorpay receipt webhook," "Add Hindi locale stub for cert PDF," "Activate Coursera affiliate rewriter (P1-01 follow-up if not done)." Write `CONTRIBUTING.md` derived from CLAUDE.md §8 load-bearing paths, public-friendly. Set up Discord with #general / #showcase / #help.
- **Acceptance:** All 5 issues posted, CONTRIBUTING.md committed, Discord invite link in README.
- **Depends on:** none.

### P2-13 ⬜ Mobile pass review (new — from audit E1)
- **Audit ID:** E1 (MEDIUM — mobile UX)
- **Severity:** MEDIUM / **Effort:** S
- **Why surface now:** RCA-030 fixed mobile only on leaderboard + profile. Onboarding flow, weekly card collapse, certificate verify page, and `/account` have not been reviewed at 320–430 px.
- **Steps:** Walk through each of these surfaces at 320 / 375 / 430 px in Chrome devtools mobile mode. Capture screenshots of any layout breaks. Log each finding as a new RCA (or as a clustered fix-PR if multiple share a root cause). Test the onboarding modal especially — narrow viewports often break form fields.
- **Acceptance:** No horizontal scrollbar at 320 px on any of the 4 surfaces. Tap targets ≥ 28px on all interactive elements. Onboarding completable on a 375px-wide simulated device.
- **Depends on:** none.

---

## §4 P3 — Later (target: this quarter, sequenced opportunistically)

| # | Audit ID | Task | Severity | Effort | Notes |
|---|----------|------|----------|--------|-------|
| P3-01 | E5 | Split `frontend/index.html` (3,015 LoC) into `index.html` + `css/main.css` + `js/{state,render,api,onboarding}.js` | HIGH | M | Pure mechanical move; no logic change. Cleans the way for P2-08 + future framework adoption. |
| P3-02 | J1b + J3 | Premium tier + Razorpay (INR-first) | CRITICAL business | L | Priority eval, deeper rubric, ad-free leaderboard, higher chat rate-limit. |
| P3-03 | J1c | B2B L&D tenant model | CRITICAL business | XL | `users.tenant_id` + cohort dashboards + completion analytics + branded certs API. 100× revenue ceiling. |
| P3-04 | H2 | Publish eval rubric page | MEDIUM | XS | `docs/EVALUATION_RUBRIC.md` linked from README + each eval response. |
| P3-05 | H10 | Leaderboard XP anti-gaming + opt-in | MEDIUM | S | Per-week cap, commits-per-repo floor, decay function for inactive repos. |
| P3-06 | D8 | MFA / TOTP | MEDIUM | S | `pyotp` + 1 migration; opt-in for users, required for `is_admin`. |
| P3-07 | D2 | Per-email OTP rate limit | MEDIUM | XS | File-backed counter like RCA-019 chat-rate. |
| P3-08 | D3 | JWT sliding refresh OR drop the doc claim | MEDIUM | XS or S | Drop is XS; implement is S. Pick one. |
| P3-09 | C1 | Provider success-rate alerting | MEDIUM | S | Daily summary in `cost_alerts.py`; CRITICAL log on <80% over 7 days. |
| P3-10 | F6 | Frontend Playwright smoke | MEDIUM | S | One end-to-end: sign-in → tick → progress updates. |
| P3-11 | A4 | Migration `downgrade()` audit | MEDIUM | XS | Document forward-only on SQLite; add CI check that fails empty `downgrade()` on destructive ops. |
| P3-12 | D7 | CORS startup validation | MEDIUM | XS | Reject `*` / `localhost` in `cors_origins_list` when `is_prod`. |
| P3-13 | C5 | AQ.Ab Gemini key pattern in sanitize.py | LOW | XS | One regex addition. |
| P3-14 | C7 | Provider error-class refactor | LOW | S | Replace `_extract_http_status` string parsing with structured `.status_code` attribute. |
| P3-15 | J6 | HANDOFF format split | LOW | XS | Carve into `docs/ROADMAP.md` (queued) + `docs/HANDOFF.md` (last 1-2 sessions) + `docs/HANDOFF_archive_*.md`. |
| P3-16 | I7 | Live-site UX validation pass | MEDIUM | S | PowerShell on host; grep rendered HTML for OG, JSON-LD, robots, canonical. |
| P3-17 | J7 | CLAUDE.md ceremony cost-vs-benefit data | LOW | XS | Trend RCAs over Q2; trim Phase 0 reads if cadence flat. |
| P3-18 | A5 | GitHub OAuth token encryption (only if per-user OAuth gets added) | MEDIUM | S | `cryptography.fernet` keyed off `cert_hmac_secret`. Currently moot — defer until feature triggers. |
| P3-19 | E3 | Chat SSE reconnect wrapper (new — from audit) | MEDIUM | S | Small wrapper around `fetch + getReader()` that handles reconnect on disconnect — useful when mobile flips cellular ↔ wifi mid-stream. ~30 LoC. |
| P3-20 | C6 | Prompt versioning headers (new — from audit) | LOW | XS | Add `# version: 1.0` line to each of the 17 prompts in `backend/app/prompts/`. Future blame-history searches faster. |

---

## §5 Cross-cutting parking lot (no sizing — depends on which P-tier item triggers them)

These are items where the audit recommended waiting for a trigger. Surface them when the trigger fires; do not promote to a P-tier without one.

- **Brand rename mechanical execution** (post-D1 if yes): `grep -rl AutomateEdge | xargs sed -i 's/AutomateEdge/<NewName>/g'`, domain swap, OG card regen, Cloudflare DNS, all 100+ touch-points across HTML/email/cert/blog. ~2-3h **after** the decision lands. Does not block P1; can ship as a single PR after P1-01 monetizes the existing brand traffic.
- **Sentry / observability upgrade** (audit G1, MEDIUM, deferred from P3 because the audit recommended Cloudflare Logpush as a free alternative — pick at the time the first painful debugging session demands it).
- **Postgres migration** (architectural, not in audit because SQLite + WAL + busy_timeout is fine at current scale; surface as a finding when DAU > 1k OR write-contention in the wild).
- **Multi-instance breaker state** (audit C2): `_provider_state` is in-process — fine for single-instance. If you ever go multi-instance, persist to DB or Redis. Trigger: second backend container.
- **Per-user GitHub OAuth** (audit A5 / D6): currently only server-side `GITHUB_TOKEN` is used. If you add per-user OAuth (PRD §F8), use `public_repo` scope only and encrypt at-rest with `cryptography.fernet` keyed off `cert_hmac_secret`. Trigger: feature work to add per-user GitHub linking.
- **WeasyPrint CI cache** (audit F4): `actions/cache@v4` for the apt-installed `.deb`s. Trigger: CI runtime climbs above 5 min.
- **Plan rigidity → user-configurable resource mix** (audit H6): `Settings.preferred_resource_mix` on `User`. Trigger: enough learners ask for non-3+3 splits.
- **Bind-mount volume documentation** (audit A6): document that `docker-compose down -v` semantics differ from named volumes for `./data:/data`. Trigger: a contributor (other than founder) onboards.

---

## §6 Audit metadata

- **Audit performed:** 2026-04-26 by Claude Opus 4.7 (read-only; full file at `docs/AUDIT_2026-04.md` until consolidation).
- **Audit revision:** v2 — folded in external review, added Area J (Sustainability/GTM/ops/contributor), added H8–H11 + B5 + C8 + D8 + I7, escalated H3/H5/I5 from LOW to HIGH.
- **Findings count by severity (audit v2):** CRITICAL 1 · HIGH 16 · MEDIUM 21 · LOW 17.
- **This merged file:** 2026-04-28 — consolidates audit findings + sequenced backlog into one source of truth, drops findings already addressed by S49+S50, surfaces 3 new tasks (P2-13, P3-19, P3-20) from audit narrative not previously sequenced.

---

## §7 How to use this file in a session

1. **At Phase 0** (or via `/aiexpert-phase0`), read this file alongside `docs/HANDOFF.md` (last session) and `docs/RCA.md`. Pick **one P-tier item** (or a tightly-related cluster from the same tier) for the session.
2. **Mark the item 🟡** (in this file) at session start, **✅** at session end, **⏭️** with reason if deferred, **🟢** with remaining notes if partial.
3. **Do not skip P-tiers.** P1 items block P2; P0 decisions block P1. If a P2 item looks more attractive than the remaining P1 work, surface that to the founder rather than silently re-ordering.
4. **One bundled commit per item** is the norm. If an item splits across sessions, commit the in-progress slice with a `[WIP P1-03]` prefix and resume next session.
5. **Update this file at session end** as part of the Phase 6 hand-off, alongside `docs/HANDOFF.md` and `docs/RCA.md`.

---

*Merged 2026-04-28 from `docs/AUDIT_2026-04.md` v2 + prior `docs/AUDIT_TASKS.md` + S49+S50 deltas. Will be revised after every batch of P-tier closures or as new audit findings emerge.*
