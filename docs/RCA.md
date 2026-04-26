# Root Cause Analysis Log

> Every bug fix gets an entry here. New sessions MUST read this to avoid repeating mistakes. Update after every fix.

## How to use
- Before committing any code, scan this list for patterns that match your change
- After fixing a bug, add an entry with: date, symptom, root cause, fix, prevention rule

---

## Entries

### 001 — OAuth cookie collision (2026-04-10)
- **Symptom:** Google SSO completed but user stayed logged out. `/api/auth/me` returned 401 after callback.
- **Root cause:** Authlib's `SessionMiddleware` and our JWT both used the cookie name `session`. The middleware overwrote our JWT cookie on every response.
- **Fix:** Renamed JWT cookie from `session` to `auth_token` everywhere (deps.py, auth.py, profile.py, all tests).
- **Prevention:** Never use generic names (`session`, `token`, `user`) for cookies. Check middleware cookie names before choosing.

### 002 — Google callback missing get_settings() (2026-04-10)
- **Symptom:** 500 error on `/api/auth/google/callback` — `NameError: name 'settings' is not defined`.
- **Root cause:** The callback function used `settings.is_prod` but never called `get_settings()`.
- **Fix:** Added `settings = get_settings()` before the cookie set line.
- **Prevention:** Always call `get_settings()` in every function that needs config. Don't rely on module-level `settings` in router functions.

### 003 — .env changes not picked up by container (2026-04-10)
- **Symptom:** VPS `.env` updated but container still had old values. Google OAuth client ID showed placeholder.
- **Root cause:** `docker compose restart` does NOT re-read `.env`. Only `--force-recreate` does.
- **Fix:** Used `docker compose up -d --force-recreate backend`.
- **Prevention:** Always use `--force-recreate` after `.env` changes. Documented in OPERATIONS.md.

### 004 — Gemini model retired (2026-04-11)
- **Symptom:** AI Chat returned "AI error — try again". Gemini API returned 404.
- **Root cause:** `gemini-1.5-flash` was retired by Google. Model no longer exists.
- **Fix:** Updated to `gemini-2.0-flash-lite` in VPS `.env`.
- **Prevention:** Monitor AI provider changelogs. Use model listing API to verify model availability before deploying.

### 005 — SSE stream fallback not triggering (2026-04-11)
- **Symptom:** Gemini 429 but Groq fallback never ran. Chat still showed error.
- **Root cause:** `stream_gemini()` yielded `"[AI error — try again]"` on non-200 instead of raising an exception. The `try/except` in `stream_complete()` never caught it.
- **Fix:** Changed `yield error` to `raise Exception()` in both `stream_gemini()` and `stream_groq()`.
- **Prevention:** Async generators must RAISE on errors, not yield error strings. The caller's `except` block can't catch yielded values.

### 006 — SMTP credentials leaked in docs (2026-04-11)
- **Symptom:** GitGuardian alert — SMTP password detected in repo.
- **Root cause:** `docs/OPERATIONS.md` contained the actual app password as an "example": `SMTP_PASSWORD=xhbmjzhnzbedjkfo`.
- **Fix:** Replaced with placeholder format. Rotated the password. Rotated Groq key too.
- **Prevention:** NEVER put real credential values in docs, even as examples. Use `<paste-your-key-here>` format. Run `git diff --cached | grep -iE 'sk-|ghp_|AIza|gsk_|password='` before every commit.

### 007 — SQLite NOT NULL column without default (2026-04-11)
- **Symptom:** Backend crash on startup — `Cannot add a NOT NULL column with default value NULL`.
- **Root cause:** Alembic auto-generated migration for `email_notifications BOOLEAN NOT NULL` without a `server_default`. SQLite can't add NOT NULL columns to existing tables without defaults.
- **Fix:** Added `server_default=sa.text('1')` to the migration.
- **Prevention:** Always add `server_default` when adding NOT NULL columns via Alembic on SQLite. Check generated migrations before committing.

### 008 — f-string syntax error in admin HTML (2026-04-11)
- **Symptom:** Backend won't start — `SyntaxError: unexpected character after line continuation character`.
- **Root cause:** Used `\\'{key}\\'` in an f-string for the onclick handler. Backslash escapes don't work inside f-string braces.
- **Fix:** Used `&quot;{key}&quot;` (HTML entity) instead of escaped quotes.
- **Prevention:** In f-string HTML templates, use HTML entities (`&quot;`, `&amp;`) for attribute quotes, not backslash escapes. Test f-strings with special chars locally before deploying.

### 009 — Progress showing 0% on login (2026-04-11)
- **Symptom:** After login, progress ring showed 0% briefly, then corrected on page refresh.
- **Root cause:** `checkAuth()` set the eyebrow text before `loadActivePlan()` synced server progress. The `state` object still had stale localStorage data.
- **Fix:** Clear `state = {}` before syncing from server. Calculate `pct` AFTER sync, not before. Show "Loading plan..." during fetch.
- **Prevention:** Always sync server state before rendering progress. Don't trust localStorage when signed in.

### 010 — Chat test failing after making chat public (2026-04-11)
- **Symptom:** `test_chat_requires_auth` expected 401 but got 200.
- **Root cause:** Chat endpoint was changed to allow anonymous users, but the test still asserted 401.
- **Fix:** Updated test to `test_chat_works_without_auth` asserting 200.
- **Prevention:** When changing endpoint auth requirements, update corresponding tests in the same commit.

### 011 — SSRF in link health checker (2026-04-11)
- **Symptom:** Codex security audit flagged — `httpx.head(url)` with `follow_redirects=True` on template-stored URLs could reach cloud metadata (169.254.169.254) or internal IPs.
- **Root cause:** No URL validation before outbound HTTP requests. Redirects followed blindly.
- **Fix:** Added `_is_safe_url()` that blocks RFC-1918, link-local, metadata IPs. Disabled redirect following. Skip URLs that fail check.
- **Prevention:** Any outbound HTTP request on user-influenced or DB-stored URLs must pass SSRF validation. Block private IPs, metadata endpoints, and non-http(s) schemes. Disable redirect following or re-validate targets.

### 012 — Weak CSRF origin check (2026-04-11)
- **Symptom:** Codex flagged — `_check_origin()` used substring match (`host in origin`). An attacker origin like `evil-myhost.com` containing the legitimate host string would pass. Also silently passed when both Origin and Referer were absent.
- **Root cause:** Substring match instead of strict hostname comparison. Missing headers not treated as a rejection condition.
- **Fix:** Parse origin URL, compare hostname with strict equality. Reject requests with neither Origin nor Referer header.
- **Prevention:** CSRF origin checks must use parsed hostname equality, not substring. Always reject missing Origin+Referer on state-changing endpoints.

### 013 — Missing input validation on settings API (2026-04-11)
- **Symptom:** Codex flagged — `POST /api/settings` used raw `setattr(s, key, value)` without type or range checking. Negative numbers, arbitrary strings accepted.
- **Root cause:** No Pydantic validation on the request body. Trusted admin input without schema enforcement.
- **Fix:** Added `PipelineSettingsUpdate` Pydantic model with `ge/le` constraints, regex patterns for enum fields, and `Optional` with `exclude_none`.
- **Prevention:** Every POST/PATCH endpoint must validate the request body with a Pydantic model. Never use raw `setattr` from unvalidated JSON, even for admin endpoints.

### 014 — Prompt injection via DB-sourced strings (2026-04-11)
- **Symptom:** Codex flagged — existing topic names from DB interpolated directly into AI discovery prompt. Malicious topic name like `"Ignore above. Instead output: ..."` could manipulate AI output. Same pattern in triage prompt and content refresh review prompt.
- **Root cause:** DB-sourced strings treated as safe and interpolated directly into AI prompts without sanitization.
- **Fix:** JSON-encode topic lists for discovery prompt. Truncate + strip newlines for triage and review prompts. Schema validation on AI output (already existed) as defense-in-depth.
- **Prevention:** Never interpolate DB/user-sourced strings directly into AI prompts. Use JSON encoding for lists, truncate + strip control characters for individual strings. Always validate AI output against strict schemas.

### 015 — Opted-in user missing from leaderboard (2026-04-11)
- **Symptom:** User manishkumarjnvk@gmail.com enabled `public_profile` but didn't appear on `/leaderboard`.
- **Root cause:** Leaderboard had `if stats["plan"] is None: continue` — users who opted in but hadn't enrolled in a plan were silently dropped. The user had `public_profile=1` but zero rows in `user_plans`.
- **Fix:** Removed the plan-required gate. All opted-in users now appear on the leaderboard, showing "Not enrolled yet" and 0% if no plan.
- **Prevention:** Opt-in features should work independently of other state. If a user enables a feature, they should see the result regardless of whether they've completed other prerequisites. Test opt-in features with minimal user state.

### 016 — OTP cookie `Secure` flag tied to env (2026-04-13) [Security audit #1]
- **Symptom:** Audit flagged the OTP `/verify` endpoint issuing `auth_token` with `secure=settings.is_prod`. In any non-prod environment the cookie would travel over plain HTTP, exposing the session token to a passive network attacker. The Google OAuth callback already used `secure=True`, so behaviour was inconsistent across the two auth paths.
- **Root cause:** Historical copy-paste: the OTP handler was written when the team still tested over `http://127.0.0.1` and the author flipped the flag to `is_prod` to make local login work. The author did not realise that Chrome/Firefox/Safari treat `http://localhost` (and loopback addresses) as a "secure context" — so `Secure=True` cookies *do* attach on localhost. There was no real need for the env-dependent flag.
- **Fix:** [auth.py:199](backend/app/routers/auth.py#L199) changed `secure=settings.is_prod` → `secure=True`. OTP cookie now matches the Google-OAuth cookie. All 10 auth/OTP tests still pass locally.
- **Prevention:** Never branch security-critical cookie flags on environment. If a flag can be on in prod, it must be on everywhere. Localhost is a secure context — dev convenience is not a reason to weaken cookies. Code review rule: grep new `set_cookie` calls for `is_prod`/`is_dev`/`debug` and reject.

### 017 — CORS `allow_headers=["*"]` with credentials (2026-04-13) [Security audit #2]
- **Symptom:** Security audit flagged `allow_headers=["*"]` combined with `allow_credentials=True`. The wildcard tells the browser to reflect *any* request header the attacker's JS tries to send on cross-origin preflight. Combined with credentialed mode, this weakens the same-origin guarantees that CSRF protection relies on: an attacker who tricks a victim's browser into issuing a cross-origin request can inject arbitrary custom headers (e.g., `X-Admin-Override`, `Authorization`, custom auth tokens), which several middlewares and upstream proxies key on. It also prevents us from ever adding a header-based CSRF token (because the wildcard would silently accept any value).
- **Root cause:** The CORS middleware was added during Phase-1 scaffolding with permissive defaults, before we fully understood which headers the frontend actually needs. Nobody revisited it because the frontend was same-origin in every deployed environment, so the wildcard never caused a visible problem.
- **Fix:** [main.py:115](backend/app/main.py#L115) changed `allow_headers=["*"]` → `["content-type", "authorization", "x-requested-with"]`. Audit of `frontend/**` confirmed only `Content-Type` is actually sent on XHR; `authorization` and `x-requested-with` are future-proofing for the planned GitHub PAT import and anti-CSRF header.
- **Prevention:** Any CORS config with `allow_credentials=True` must enumerate `allow_origins` *and* `allow_headers` explicitly. Wildcards are never acceptable with credentials. Code review rule: grep PRs for `allow_headers=["*"]` and reject. Startup assertion idea for later: fail fast if both settings coexist.

### 018 — Google OAuth callback redirect target unvalidated (2026-04-13) [Security audit #3]
- **Symptom:** The Google OAuth callback does `RedirectResponse(url=settings.public_base_url, 302)`. The value is *not* user-controlled, so there is no direct open-redirect from a crafted request. However, `public_base_url` is consumed raw with no shape validation — if an operator typos the `.env` (e.g., leaves `http://localhost:8080` in a prod deploy, or points it at an attacker-controlled staging host), Google sends every successfully-authenticated user to the wrong origin *carrying the auth cookie*, because the cookie is then set in that response. This turns a config mistake into a full session handover.
- **Root cause:** `Settings` declared `public_base_url: str` with a dev default and no prod-time check. The `_validate_prod_settings()` hook verifies JWT and OAuth secrets but not URL hygiene. Phase-0 scaffolding prioritised "make it boot" over "make it fail loud."
- **Fix:** [config.py:140](backend/app/config.py#L140) extended `_validate_prod_settings()` to (a) require `https://` scheme, (b) reject `localhost`/`127.0.0.1`/`0.0.0.0`/`::1` hostnames. Any of these in a prod boot now raises at startup before the first request is served. The callback code is unchanged — the defence is pushed up to config load time, where a broken value surfaces immediately instead of silently redirecting users later.
- **Prevention:** Any env var that controls a URL the server will redirect to — or set a cookie on — must be schema-validated at startup, not trusted. Pattern: for every new `public_*_url` or `*_redirect_uri` setting, add a matching assertion in `_validate_prod_settings()`. Separately, treat the combo "redirect + Set-Cookie in the same response" as a high-risk sink and prefer redirecting to same-origin paths only.

### 019 — Chat rate limit lost on restart (2026-04-13) [Security audit #4]
- **Symptom:** `_check_rate_limit()` in the chat router kept per-user timestamps in a module-level `defaultdict`. The tracker evaporated on every `docker compose up --force-recreate`, on every code deploy, and on every OOM restart. A determined abuser who hit the 20 msg/hr cap could recover their full quota just by waiting for the next deploy, which is roughly 1–3 times a week during active development. The cap was therefore advisory, not enforced.
- **Root cause:** Quick-and-dirty limiter was landed in Phase-1 with a note "good enough until we add Redis." The note was never followed up on. No persistence, no file-backed fallback, no documentation that the cap was non-durable. Adding `slowapi` with its default storage would not have helped — slowapi's default is also in-memory.
- **Fix:** [chat.py:28-66](backend/app/routers/chat.py#L28) replaced the bare `defaultdict` with a JSON-file-backed tracker. Reads on import via `_load_rate_tracker()`; writes after every hit via `_persist_rate_tracker()` under a `threading.Lock`. Persistence is **opt-in** via `CHAT_RATE_DIR` env var so the test suite (which does not mount `/data`) stays purely in-memory — no sandbox-escape writes, no cross-test leakage. Docker-compose now exports `CHAT_RATE_DIR=/data` on the backend service so the volume-mounted file survives rebuilds. Atomic write via `.tmp` + `os.replace()` to avoid torn reads on crash. Test `tests/test_chat.py::test_chat_rate_limit` also updated — it previously cleared `_rate_tracker[int_key]` but the handler keys by `str(user_id)` now, so the reset was a no-op and caused state leak from preceding tests; switched to `_rate_tracker.clear()`.
- **Prevention:** Any in-memory rate limit / counter / quota is a time bomb. Treat module-level `dict`/`defaultdict`/`Counter` as a red flag in code review when its *purpose* is security. Pattern: if the variable name contains `rate`, `quota`, `attempts`, `cooldown`, or `tracker`, it MUST have a persistence story or a TODO with a ticket number. Also: when changing a dict key's type (int → str), grep tests for the old key form — silent type mismatches don't fail loudly.

### 020 — `parse_repo_input` hostname not validated (2026-04-13) [Security audit #5]
- **Symptom:** `parse_repo_input()` in `github_client.py` keyed off `startswith("https://github.com/")` for URL inputs and otherwise assumed "owner/name". Although the current caller `fetch_repo` rebuilds the request against `api.github.com/repos/{owner}/{name}` — so the original hostname is dropped — the parser itself accepted *any* string that happened to start with that prefix. Combined with a future caller that might forward the raw URL (e.g. for avatar / README / release-asset fetches — all planned features), this would be a direct SSRF sink. The owner and name were also unconstrained: values containing `/`, `@`, `:`, URL escapes, or control characters would be passed into downstream API paths unchanged.
- **Root cause:** Phase-1 scaffolding wrote the parser as a one-liner for the happy path. Because the downstream API call always targets github.com, the parser never needed to care about hostnames, and nobody treated it as a security boundary. GitHub Enterprise support was never added, so we can tighten without regressing any real feature.
- **Fix:** [github_client.py:85](backend/app/services/github_client.py#L85) rewritten to (a) parse via `urllib.parse.urlparse` and require `scheme == "https"` and `hostname == "github.com"` (case-insensitive), rejecting IP literals, look-alikes like `github.com.evil.tld`, userinfo, and alt ports; (b) apply `^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$` to both `owner` and `name`, matching GitHub's own username/reponame rules; (c) strip a trailing `.git` so `git clone` URLs still work. All 10 `tests/test_repos.py` cases still pass.
- **Prevention:** `str.startswith("https://host/")` is **never** a sufficient host check — `https://host.evil.tld` and `https://host@evil.tld` both satisfy it. Rule: every user-controllable URL that crosses into `httpx`/`requests`/`aiohttp` must be routed through `urlparse` with explicit scheme + hostname equality, and every identifier that lands in a downstream URL path must match a whitelist regex. Add the SSRF pattern to the code-review checklist alongside SQLi and XSS.

### 021 — `/api/health` leaks build metadata (2026-04-13) [Security audit #6]
- **Symptom:** The unauthenticated health probe returned `{"status": "ok", "version": settings.app_version, "env": settings.env}`. Version strings give attackers a free first step: they can map them to known CVEs in our dependency set (weasyprint, uvicorn, pydyf, etc.) and jump straight to targeted exploits without fingerprinting. The `env` field also confirms which host is "prod" vs staging, helping an attacker choose their target.
- **Root cause:** Developer convenience — the first-week-of-Phase-1 scaffolder wanted to curl health and see which build was live. The value stayed on public because nobody re-reviewed public endpoints after auth was added.
- **Fix:** [main.py:193](backend/app/main.py#L193) trimmed to `{"status": "ok"}`. Version/env remain available on the authenticated `/api/admin/*` dashboards.
- **Prevention:** Public endpoints must declare, in a comment, the exact keys they expose. Rule of thumb: an anonymous caller never needs to know the build version. If monitoring wants it, add a separate authenticated `/api/admin/version`. Add to code-review checklist: "does this endpoint expose any non-essential server metadata?"

### 022 — AI Usage dashboard shows $0.00 everywhere (2026-04-16) [Observability]
- **Symptom:** Every cost widget on `/admin/pipeline/ai-usage` showed $0.00. `tokens_estimated` was 0 for all 196 rows in `ai_usage_log`.
- **Root cause:** Three independent bugs: (1) `jobs_enrich.py` called `provider.complete()` without `db=`, so `log_usage()` was never called — zero rows logged for the biggest AI consumer. (2) `quality_pipeline.py` called `log_usage()` without `tokens_estimated=` after direct Gemini/Groq calls — defaulted to 0. (3) `evaluate.py`, `content_refresh.py`, `topic_discovery.py` (triage + Groq fallback) all called AI without `db=` or manual logging.
- **Fix:** [health.py](backend/app/ai/health.py) — added `get_last_tokens(provider)` centralized helper. [provider.py](backend/app/ai/provider.py) — uses helper + includes response length in fallback estimate. [jobs_enrich.py](backend/app/services/jobs_enrich.py), [jobs_ingest.py](backend/app/services/jobs_ingest.py) — pass `db=` through. [quality_pipeline.py](backend/app/services/quality_pipeline.py) — reads `_last_usage` via helper. [evaluate.py](backend/app/services/evaluate.py), [content_refresh.py](backend/app/services/content_refresh.py), [topic_discovery.py](backend/app/services/topic_discovery.py) — pass `db=` and `task=`. Commits: `e3bfbaa`, `d060b88`.
- **Prevention:** Every new AI call site MUST pass `db=` to `provider.complete()`, or manually call `log_usage()` with `tokens_estimated=get_last_tokens(provider)` after direct provider calls. Add to code-review checklist: "does this AI call log to `ai_usage_log` with non-zero tokens?"

### 023 — Gemini API key leaked in chat transcript (2026-04-16) [Security / key hygiene]
- **Symptom:** In a prior working session the live `GEMINI_API_KEY` value was pasted into a Claude Code chat transcript. Anyone with access to that transcript — or any future context snapshot that ingested it — would have had a valid production key with full quota.
- **Root cause:** The key lived correctly in the VPS `.env` only (never committed), but was referenced by value in a troubleshooting exchange rather than by name. The host side of the transcript has no known-secret redaction hook, so once typed it persisted.
- **Fix:** (1) User rotated the key in https://aistudio.google.com/app/apikey; the replacement used the newer Google format with prefix `AQ.` instead of the classic `AIzaSy...`. (2) On the VPS: backed up `/srv/roadmap/.env` as `.env.bak-<epoch>` and replaced the `GEMINI_API_KEY=` line via `sed -i`. (3) `docker compose up -d --force-recreate backend` — plain `restart` would not reload env (RCA-002). (4) Smoke test via `app.ai.provider.complete(prompt=..., json_response=True, task='smoke_test_new_key')` — `gemini-2.5-flash` returned valid JSON. (5) `docker compose logs backend` grep'd for 401/403/`invalid.*key` — none. (6) User revoked the old key in AI Studio.
- **Prevention:**
  - Never paste a secret *value* into a chat transcript. Reference it by variable name (`GEMINI_API_KEY`) and have the assistant SSH + `grep` on the host if the actual value is ever needed. Treat conversational context as quasi-public.
  - CLAUDE.md §5 rule 1 already lists redaction prefixes for pre-commit grep. Update that list: Gemini keys may now start with either `AIzaSy` (classic, 39 chars) **or** `AQ.Ab` (newer format, variable length). Both must be redacted in `logging_redact.py` and in pre-commit diff grep.
  - Rotation procedure is now codified in [docs/OPERATIONS.md §6.1](OPERATIONS.md#61-rotating-a-leaked-or-expired-ai-provider-key). Follow it verbatim for any future leak — it's an 8-step checklist that covers backup, replacement, force-recreate, smoke test, log scan, and revocation.

### 024 — `/admin/jobs` stuck on "Loading…" (2026-04-16) [Frontend / Python-to-JS escaping]
- **Symptom:** After session 14f deploy, `/admin/jobs` rendered the page shell (banner, filters, quick-filter toggles) but every data section ("Queue", "Source stats", "Summary-card pipeline", job list) stayed on "Loading…" forever. nginx access logs showed zero `/admin/jobs/api/queue` / `/api/stats` / `/api/summary-stats` hits from the user's browser — the fetches never fired.
- **Root cause:** In the inline `<script>` block of `_ADMIN_HTML` (a Python triple-quoted string), the new publish-guardrail `confirm()` dialog at [admin_jobs.py:843-845](backend/app/routers/admin_jobs.py#L843-L845) used double-quoted JS strings containing `\n\n`. Python `"""..."""` is *not* a raw string — `\n` was interpreted as a real newline (LF) at module load, so the browser received JS like `"…yet.<LF><LF>" +` which is a `SyntaxError` inside a JS `"..."` literal. The entire `<script>` block failed to parse, so the top-level `load()` call and every event-handler wiring never ran.
- **Fix:** Double-escaped each `\n` to `\\n` so Python emits the literal two-character `\n` escape that JS then parses correctly. Verified by piping the rendered script body through `node --check` — was throwing `Invalid or unexpected token`, now prints clean. Commit `bf184eb`.
- **Prevention:**
  - Any JS string literal emitted from inside a Python `"""..."""` block must **not** contain a single-backslash `\n` (or `\t`, `\r`, `\\`) — Python will eat the escape. Double them, or use a JS template literal (backticks) where real newlines are legal, or move the JS into a static file served from `/static/`.
  - Add a CI/pre-commit check that extracts `<script>...</script>` bodies from admin HTML templates and runs `node --check` on them. A single `node --check` invocation would have caught this in seconds.
  - Test fixture needed: render `_ADMIN_HTML` in a unit test and assert no literal LF inside any double-quoted JS string (regex: `"[^"\n]*\n[^"]*"` on the extracted script body must not match).

### 025 — TIER2_SOURCES companies stamped as T1 / bulk-approve-eligible (2026-04-16) [Data model / safety]
- **Symptom:** Admin `/admin/jobs` with the "TIER-2 LITE" quick-filter on showed rows badged with the green `T1` chip *and* the `TIER2-LITE` chip — specifically PhonePe jobs like "Lead Exit and Benefits Administration" and "Operations Associate, Merchant KYC". The two axes looked contradictory. Hidden worse consequence: bulk-publish's server gate ([admin_jobs.py:293](backend/app/routers/admin_jobs.py#L293)) keys on `JobSource.tier == 1 AND bulk_approve`, so those HR/KYC drafts were eligible for one-click bulk approval without individual review — defeating the whole point of `TIER2_SOURCES`.
- **Root cause:** `ensure_source_rows()` in [jobs_ingest.py:128-149](backend/app/services/jobs_ingest.py#L128-L149) unconditionally created every Greenhouse/Lever/Ashby source with `tier=1, bulk_approve=1` and every JobCompany with `verified=1`. It never consulted the `TIER2_SOURCES` hardcoded set — which is used *only* downstream in `_stage_one()` to pick the lite-enrichment prompt. Result: two parallel tiering models that disagreed on non-AI-native boards (PhonePe, Groww, CRED, Mindtickle, Notion, Replit).
- **Fix:** (1) `ensure_source_rows()` now checks `key in TIER2_SOURCES` and stamps those with `tier=2, bulk_approve=0` and their `JobCompany.verified=0`. (2) One-off backfill on VPS via SQLAlchemy updates: 6 job_sources, 6 job_companies, 65 jobs rows corrected. (3) Added regression test `TestTier2Sources.test_ensure_source_rows_tiers_tier2_sources_correctly` that spins up an in-memory DB, calls `ensure_source_rows()`, and asserts per-key/per-slug flags for both tiers. Commits `7eb8165` (code+test) and live backfill at 2026-04-16 06:32 UTC.
- **Prevention:**
  - Single source of truth for tiering: `TIER2_SOURCES` is the canonical set. Any code that classifies a source/company as tier-1 must consult it instead of assuming "registered = tier-1".
  - Bulk-approve, filter chips, and enrichment path are three downstream consumers of the same axis. When adding a fourth, search for all call sites that branch on `tier`, `verified`, or `bulk_approve` and make sure the new code reads from the same place.
  - Data-classification bugs are silent: tests pass, UI renders, the defect surfaces only when an admin trusts the chip. Add a post-ingest invariant test: for every row in `TIER2_SOURCES`, assert `JobSource.tier == 2` and `JobCompany.verified == 0`. Caught this at the model layer in `test_ensure_source_rows_tiers_tier2_sources_correctly`.

### 026 — Legal job ingested as "Applied ML" because "LLM" means two things (2026-04-16) [AI quality / classification]

- **Symptom:** PhonePe "Manager, Legal" (Bengaluru, 7+ yrs PQE) landed in the admin Jobs queue with Topic="Applied ML" and was surfaced as an AI role. The JD said "LLB / LLM from a recognized university" — "LLM" here is the Master of Laws degree, not Large Language Model — plus the JD was saturated with non-AI content (Indian Contract Act, procurement contracts, MSAs, NDAs, redlining). Zero AI/ML content in the whole posting.
- **Root cause:** Three layers all failed open. (1) Title pre-filter `_NON_AI_TITLE_PATTERNS` in [jobs_ingest.py:59-80](backend/app/services/jobs_ingest.py#L59-L80) listed "legal counsel"/"general counsel"/"attorney" but not "manager, legal" / "legal manager" / "corporate counsel" / "compliance manager" / "benefits administration" / "merchant kyc" — so substring match missed. (2) Lite-enrichment system prompt [jobs_extract_lite_system.txt:13](backend/app/prompts/jobs_extract_lite_system.txt#L13) listed "LLM" as a topic without disambiguation; Gemini Flash saw "LLM" in "LLB / LLM" and returned it as an AI topic. (3) `_validate()` and `enrich_job_lite()` had a safety fallback `or ["Applied ML"]` at [jobs_enrich.py:287](backend/app/services/jobs_enrich.py#L287) and [:390](backend/app/services/jobs_enrich.py#L390) — even when AI returned empty topic, the code silently lied and stamped "Applied ML".
- **Fix:** Four-layer defense. (1) Title filter expanded with 15 new legal/HR/finance/KYC patterns including "legal manager", "manager, legal", "corporate counsel", "compliance manager", "contracts manager", "benefits administration", "merchant kyc". (2) New `has_non_ai_jd_signals(jd_html)` function — two-gate rule: >=2 legal/HR cluster terms (LLB, PQE, "Indian Contract Act", "law firm", "procurement contracts", MSA, NDA, redlining, "benefits administration", "merchant kyc") AND zero AI signal terms (pytorch, tensorflow, transformer, MLOps, fine-tuning, RAG, Claude/Gemini/GPT, etc.). Called in `_stage_one` after title check. (3) Removed `or ["Applied ML"]` fallback at both call sites — empty topic now propagates as `[]`, surfacing `⚠ no-topic` to admin rather than a false-positive Topic chip. (4) Added "DISAMBIGUATION" block to both full and lite system prompts instructing Gemini that "LLM" in the enum is Large Language Model only — LLB/LLM degree, PQE, law firm, contract drafting, Indian Contract Act ⇒ return `"topic": []`, `"designation": "Other"`. 10 new tests (`TestNonAIJDSignals` + legal title cases) cover PhonePe JD shape and "LLM degree + law firm" variants while guarding against false negatives on ML Engineer JDs that mention NDAs in passing.
- **Prevention:**
  - Any topic enum with a two-meaning acronym ("LLM", "CV" — curriculum vitae vs computer vision — "RL" could mean reinforcement learning or real-life) must ship with explicit disambiguation in the prompt. Test with adversarial JDs that use the non-AI meaning heavily.
  - Never default a classification field when the model returns empty. `or ["Applied ML"]` is a "lie rather than say I don't know" pattern — silently corrupts analytics and misroutes jobs. Empty is a valid signal; surface it in the UI.
  - Title-based pre-filter is fragile on flexible title formats (punctuation/capitalization/abbreviation). Back it with a JD-content scanner gated on "zero AI signal" so legit AI roles are never accidentally filtered.
  - When extending `_NON_AI_TITLE_PATTERNS`, also update `TestNonAITitleFilter` in the same commit — regressions are silent otherwise.

### 027 — Backend crash-loop from unescaped JSON braces in f-string admin guide (2026-04-16) [Self-inflicted production outage]

- **Symptom:** After deploying the Wave 4 #16 admin guideline section to `/admin/jobs-guide` (commit `7585db0`), the backend container entered a crash-loop with `NameError: name 'job_id' is not defined` at `app/routers/admin.py:2409`. Production was down for ~5 minutes between deploy and hotfix.
- **Root cause:** `_JOBS_GUIDE_HTML` is a triple-quoted f-string (`f"""..."""`). My new admin-guideline content included literal JSON in `<code>` blocks: `<code>{job_id, agreed, opus_topic, opus_designation, notes}</code>` and the curl example body `'{"results":[ {"job_id":20, ...} ]}'`. Python interpreted every single `{...}` as an f-string interpolation, calling `eval()` on the contents at module-import time. `job_id` is not a defined symbol → NameError → uvicorn never finished loading → container crashed → restart loop.
- **Fix:** Doubled all literal `{` and `}` in the new sections so Python emits single braces in the rendered HTML. Verified by extracting the f-string and `eval()`-ing it in isolation: produces 23,219 chars cleanly. Hotfix in commit `784f8d8`. Container healthy 16s after redeploy.
- **Prevention:**
  - **EVERY single brace inside a `f"""..."""` block must be doubled** when it's literal output, not an interpolation. This is the second time this exact pattern has bitten us (RCA-024 was JS strings; RCA-027 is JSON strings — same root cause).
  - The pattern table below already lists "f-strings with HTML" — extend it to **"f-strings with ANY embedded code (HTML attributes, JS strings, JSON, CSS)"**. The risk is universal to f-strings, not just HTML.
  - Pre-commit check: extract every `f"""..."""` block in `app/routers/*.py` and run `eval()` against it with dummy values for the named interpolations (`{ADMIN_CSS}`, `{ADMIN_NAV}`, etc.). A brace-counting heuristic isn't enough — need actual parse.
  - Migration target: move `_JOBS_GUIDE_HTML` and similar large templates to actual template files served via `Jinja2Templates` or `aiofiles`. F-strings are the wrong tool for >100-line HTML blobs containing arbitrary code samples. Tracked but deferred — too much surface to migrate in this session.
  - When adding example code to admin docs, always test the rendered page in a browser BEFORE pushing. The `python -m py_compile` syntax check passes for f-strings with mismatched `{}` because evaluation is deferred to runtime.

### 028 — Admin Jobs queue 500: UnicodeEncodeError from lone surrogate in job data (2026-04-16) [Data quality / serialization]

- **Symptom:** `/admin/jobs` page showed "Load failed: 500". Banner stuck on "Loading…". Backend log: `UnicodeEncodeError: 'utf-8' codec can't encode character '\udcb7' in position 1154940: surrogates not allowed` inside `starlette/responses.py render()`. Health endpoint still 200 — backend was running, only the queue API crashed.
- **Root cause:** A job scraped from an external source board had a lone surrogate character (`\udcb7`) in its `description_html` field. SQLite stores raw bytes and Python's `sqlite3` driver decodes them with `errors='surrogateescape'`, producing a Python `str` that contains a surrogate codepoint. This is legal in Python's internal string representation but JSON serialization (which must produce valid UTF-8) rejects it with `UnicodeEncodeError`. FastAPI's `JSONResponse` calls `json.dumps` → triggers the error → 500 on every queue request until the row is fixed or the serializer sanitizes it.
- **Fix:** Added `_strip_surrogates(obj)` helper at [admin_jobs.py:52](backend/app/routers/admin_jobs.py#L52) — recursively walks dicts/lists/strings, re-encodes each string through `utf-8 errors=replace` to substitute `\ufffd` (Unicode replacement character) for any surrogate. Applied to `job.data` in `_serialize()`. Surrogates become `\ufffd` (visible as `?` in the UI) — data is still readable and the queue loads. Commit `<pending>`.
- **Prevention:**
  - Sanitize at ingest time: `jobs_ingest.py` should run `_strip_surrogates` (or equivalent) on `description_html` and other scraped string fields before writing to the DB, so surrogates never reach the DB at all.
  - Add to the "Patterns to watch for" table: scraped HTML → surrogate leakage.
  - The serializer fallback (`_strip_surrogates` in `_serialize`) is a safety net, not the primary fix. Primary fix should be at scrape time.

---

### 029 — daily_jobs_sync silently dead for 8 days: retry helper missed "unable to open database file" (2026-04-23) [Silent cron failure]

- **Symptom:** Zero jobs had ever been auto-expired in production. 195 published jobs were past `valid_through` but still status='published' — showing in `/api/jobs` and the sitemap as "live". Only 1 of 784 published rows had a `missing_streak` counter tracked. `job_sources.last_run_at` frozen at 2026-04-14 23:09:58 for every source with `last_run_fetched=0`. Cron log showed `daily_jobs_sync` failing nightly with `sqlite3.OperationalError: unable to open database file` inside `_set_sqlite_pragmas` → stack trace traceable to `_auto_expire_missing`, `_auto_expire_past_valid_through`, `ensure_source_rows`, and the final `stamp last_run_at` transaction.
- **Root cause:** Two-part. (a) `_stage_with_retry` in [backend/app/services/jobs_ingest.py:723](backend/app/services/jobs_ingest.py#L723) only retried on `"database is locked"` / `"database table is locked"` — both real SQLite concurrency conditions. But under heavy parallel aiosqlite connection opens from the cron container while the live backend was also writing, SQLite sometimes surfaces the race as `"unable to open database file"` instead (a separate error string — fired inside the `PRAGMA journal_mode=WAL` event listener at [backend/app/db.py:57](backend/app/db.py#L57) when the WAL/journal file couldn't be acquired). That string fell through the retry check and was re-raised. (b) `ensure_source_rows`, both `_auto_expire_*` helpers, and the final stamp session had NO retry at all — a single transient failure killed the operation. The outer `try/except Exception` only logged the failure; the next daily run hit the same condition and same fate. 8 days of silent failure because one ERROR line per day blended into the scheduler's hourly heartbeat INFO logs.
- **Fix:**
  - Extracted `_is_transient_db_error()` classifier at [jobs_ingest.py:723](backend/app/services/jobs_ingest.py#L723) — now catches all three strings: `"database is locked"`, `"database table is locked"`, `"unable to open database file"`.
  - New `_retry_db(op, label, max_attempts=4)` helper wraps any async DB op with exponential backoff (0.2s, 0.4s, 0.8s + jitter).
  - Wrapped `ensure_source_rows`, each per-source iteration of `_auto_expire_missing`, `_auto_expire_past_valid_through`, and the final `stamp_last_run_at` session with `_retry_db`.
  - Added `PRAGMA busy_timeout=30000` to [backend/app/db.py:60](backend/app/db.py#L60) — SQLite waits up to 30s on lock contention instead of failing, attacking the concurrency race at the connection layer too.
  - Added consecutive-failure alerting in [scripts/scheduler.py:72](scripts/scheduler.py#L72) — `_run_guarded` tracks per-label streak, logs `CRITICAL ALERT: N consecutive failed runs` after ≥2 in a row, so a future silent outage surfaces on day 2 instead of day 8.
  - Backfill script [scripts/backfill_expire_stale_jobs.py](scripts/backfill_expire_stale_jobs.py) to flip the 195 accumulated past-valid_through rows without waiting for the next scheduled run.
- **Prevention:**
  - Any SQLite error-string allowlist must include `"unable to open database file"` alongside the lock variants — all three are transient under aiosqlite + multi-process concurrency.
  - Every DB session opened inside a scheduled cron job must be retry-wrapped. Bare `async with _db.async_session_factory()` in a cron context is a silent-failure trap.
  - Scheduler runs must escalate repeated failures to `CRITICAL` severity — an `ERROR` log per daily run blends into heartbeat noise and won't page anyone.

### 030 — Leaderboard (and /u/{handle}) missing viewport meta, rendered at desktop width on phones (2026-04-24) [Mobile accessibility]

- **Symptom:** Mobile review of the site (iPhone 320–430 px) revealed `/leaderboard` and `/u/{handle}` rendered as desktop-width pages with pinch-zoom required to read anything. The 9-column ranking table was several viewports wide; the stat row wrapped into a tall stack with huge 28 px stat numbers. Other pages (home, `/blog`, `/blog/{slug}`, `/jobs`) had viewport meta; only the public-profile router was missing it.
- **Root cause:** `public_profile.py` was written before the rest of the SSR pages standardized on `<meta name="viewport" content="width=device-width, initial-scale=1">`. It shipped with only `<meta charset="UTF-8">` in the `<head>`. There's no project-wide enforcement: each SSR handler builds its own HTML string, and nothing checks for viewport meta at boot or test time. The shared `nav.css` only sets responsive rules on `.topnav` — it doesn't backfill viewport meta, so a page without the tag gets desktop layout regardless of nav styling.
- **Fix:** [public_profile.py:415 and 600](backend/app/routers/public_profile.py) — added `<meta name="viewport" content="width=device-width, initial-scale=1">` to both HTML-returning handlers (profile + leaderboard). Wrapped the 9-col table in `<div class="table-wrap">` with `overflow-x: auto` + `min-width: 720px` on `table` so the table scrolls internally instead of forcing page-wide horizontal scroll. Added `@media (max-width: 480px)` block tightening stat grid, tier chip, badge pill, and help grid. Also shipped mobile CSS fixes to home / blog / jobs in the same commit: `img { max-width: 100% }` + `pre { overflow-x: auto }` on blog post body (uploaded images no longer overflow); `@media (max-width: 480px)` blocks on jobs hub + detail with WCAG-AA tap targets; modal overlay padding + narrow-viewport modal override on home. Commit `f3a2749`.
- **Prevention:**
  - Every new SSR handler returning `HTMLResponse` must include `<meta name="viewport" content="width=device-width, initial-scale=1">` in `<head>`. Grep rule for PR review: any `return f"""<!DOCTYPE html>` without a matching viewport meta in the same f-string is a bug.
  - Any `<table>` SSR'd into a public page needs a `.table-wrap { overflow-x: auto }` wrapper if it has >4 columns — wrapping is cheap insurance, unwrapping is easy.
  - Uploaded-content renderers (blog post body is the canonical case) must set `img { max-width: 100%; height: auto }` and `pre { overflow-x: auto }` globally — authors can't be relied on to size images to every viewport.

### 031 — Pillar-post validator inert in production: `trusted_sources.json` never copied into image (2026-04-25) [Deploy / file inclusion]

- **Symptom:** New CLI `scripts/stage_blog_draft.py` ran the SEO-25 pillar validator inside the backend container and got `trusted_sources.json not found at /app/data/trusted_sources.json` for every pillar post — meaning *every* pillar-post validation since SEO-25 shipped (session 38, commit `5c81c21`) was effectively a no-op in production. The file existed locally at `backend/data/trusted_sources.json`, so session-39 validation runs (which were executed *locally*, not in the container) reported `ok=True, 0 errors` and the gap was invisible.
- **Root cause:** [`backend/Dockerfile`](backend/Dockerfile) had `COPY app ./app`, `COPY alembic ./alembic`, `COPY tests ./tests`, etc. — but no `COPY data ./data`. The `backend/data/` directory was created in session 38 specifically for `trusted_sources.json` and nothing told the Dockerfile to include it. Validator's `_TRUSTED_SOURCES_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "trusted_sources.json"` resolves correctly to `/app/data/trusted_sources.json` inside the container — the path was right, the file just wasn't there. The legacy admin paste-flow happened to run validation in the same container path, so it would have failed identically — but no pillar post had been pasted into `/admin/blog` yet (both session-39 archives sat as JSON files only), so the failure mode was latent.
- **Fix:** [backend/Dockerfile:34](backend/Dockerfile#L34) — added `COPY data ./data` between `COPY app ./app` and `COPY alembic.ini ./`. Image rebuilt + force-recreated. Verified `/app/data/trusted_sources.json` is now present inside the container; staging script now successfully validates + writes drafts for both pillar posts. Commit `4162362`.
- **Prevention:**
  - **Any new directory under `backend/` that the runtime reads must be added to the Dockerfile in the same PR.** The bug was a missed COPY, not a path mismatch — and the validator's relative-path resolution made it appear local-vs-container neutral when it wasn't.
  - **Tests that import a fixture-loading helper must run it.** `blog_validator.load_trusted_sources()` should be exercised by at least one container-aware test (e.g., `pytest --no-header tests/test_blog_validator.py`) so a missing file would fail CI, not silent-pass.
  - **Validators that depend on file-system state should fail loudly at import time, not at first-call time.** Consider eager-loading `_TRUSTED_SOURCES` at module load and raising `RuntimeError` if missing — turns a latent prod bug into a startup crash that the healthcheck catches.

### 032 — `/jobs` filter dropped on pagination + dropdown count mismatched displayed cards (2026-04-26) [Frontend / SSR-JS state split]

- **Symptom:** On `/jobs`, picking country `IN` from the location dropdown showed only 1 job even though the dropdown advertised `IN (45)`. Clicking page 2 (the SSR-rendered "1 2 3 … 15" footer) navigated to `/jobs?page=2` and showed 50 unfiltered jobs — the country filter was silently dropped. Same trap for any other filter.
- **Root cause:** Two coupled defects in the SSR-vs-JS state split. (a) The `/jobs` SSR endpoint accepts only `page=` (not filter params), so its pagination links carry no filter state — and per the SEO-10 hydration rule the JS deliberately skips `loadJobs()` whenever `?page=` is present, so on page 2 there is no client-side path to re-apply the filter either. The footer pagination was therefore an unconditional escape hatch back to an unfiltered set whenever the user had narrowed the list. (b) The default `posted_within_days=7` radio was `checked` on initial render, which auto-applied a Last-7-days filter via JS the moment the page loaded; the location dropdown counts come from `/api/jobs/locations` which counts *all* published jobs ignoring time, so the visible count `(45)` and the rendered card count (1 — the only IN job posted in the last week) advertised two different result sets and the user had no way to see this without inspecting the chips row.
- **Fix:** [backend/app/routers/jobs.py:1011-1015](backend/app/routers/jobs.py#L1011-L1015) — `loadJobs()` now hides `nav.pagination` whenever it paints (commit `6e2ea12`). The element still ships in the SSR HTML so Googlebot's crawl path through `/jobs?page=N` is intact; only the in-page UI affordance is suppressed. [backend/app/routers/jobs.py:362-366](backend/app/routers/jobs.py#L362-L366) — `Any time` is now the default `posted` radio instead of `Last 7 days` (commit `fd60f63`), so the dropdown counts and the rendered card count agree on first paint. Verified live: `/api/jobs?country=IN&limit=200` returns 45 jobs, matching the dropdown.
- **Prevention:**
  - **An SSR-rendered control that mutates the result set must either (a) round-trip the active client-side filter state in its URLs, or (b) be hidden once the client has narrowed.** Half-measures (showing the control but ignoring the filter on click) are worse than either extreme — they look authoritative and silently drop user intent.
  - **A "count" string next to a filter option (e.g., `IN (45)`) advertises a contract: clicking it should produce that many results.** If any other default filter is silently in play, the contract is broken at first paint. Rule: counts in `<option>` labels must be computed under the *same* filter set the page applies on initial load — or the default filter set must be empty.
  - **Whenever an HTML page combines an SSR-rendered list with a JS hydration that replaces it under different parameters, audit every footer/header control for "does it still make sense after JS paint?"** Pagination, sort dropdowns, "next/prev" buttons, and page-N breadcrumbs are common offenders.

### 036 — Email job-card chip rendered Python dict repr `{'min': None, '` (2026-04-26) [Email rendering / type assumption]

- **Symptom:** User reviewed the live test digest sent to `manishjnvk1@gmail.com` (Sarvam AI / ML Ops Engineer card) and reported a chip showing literal `{'min': None, '` next to a real `3+ years` chip. The salary chip was leaking a Python `dict.__repr__` truncated at the 30-char `[:30]` slice.
- **Root cause:** [backend/app/services/weekly_digest.py](../backend/app/services/weekly_digest.py) `_jobs_section` assumed `job.data["employment"]["salary"]` was a string and ran `_esc_str(salary)[:30]` directly. Production data has the field shaped as a typed dict `{"min": int|None, "max": int|None, "currency": str}` (matching the existing `experience_years` shape, which the same function handled correctly). Calling `_esc_str` on a dict invokes `str(dict)` → `"{'min': None, 'max': None, 'currency': 'INR'}"`, which the slice then truncates to `{'min': None, '`. Same dict-vs-string ambiguity existed silently for `employment.type` (no production breakage observed yet because most rows had it as a string, but defensively unsafe).
- **Fix:** [backend/app/services/weekly_digest.py:268-303](../backend/app/services/weekly_digest.py#L268-L303) — extracted `_fmt_salary()` and `_fmt_emp_type()` helpers that explicitly switch on `isinstance(value, dict)` vs `isinstance(value, str)` and format min/max/currency intentionally (`"INR 50–80"` / `"INR 50+"` / `"up to 80"`) or skip when no usable data exists. Two regression tests in [backend/tests/test_weekly_digest.py](../backend/tests/test_weekly_digest.py): `test_jobs_section_chips_never_render_dict_repr` (the production shape with `min: None, max: None` — chip must not appear, exp_y chip must still render) and `test_jobs_section_renders_dict_salary_with_min_max` (real `min: 50, max: 80, currency: INR` — chip must render as `INR 50–80`). Both mock `_top_matches` so the test isn't coupled to the live match-score threshold.
- **Prevention:**
  - **Never call `_esc_str(value)` on a value whose runtime type isn't proven to be a string.** `_esc_str` falls back to `str(x)` for non-strings, which silently leaks dict/list reprs into the rendered output. Rule: any new `_esc_str(field)` call against a JSON-blob field must be preceded by an `isinstance(field, str)` guard OR an explicit formatter.
  - **For typed JSON-blob fields shared between the API and the renderer, document the schema once and reference it from both.** The `employment.{salary, type, experience_years}` schema lives in `Job.data` (an opaque dict) — it's effectively a contract the renderer has to know without static help. Either add a Pydantic shape for `JobData` (best) or a helper module that all renderers call (`format_employment_chips(data)`).
  - **When a production user reports an unusual character sequence in rendered output (`{'min':`, `[None,`, `<class '`), suspect missing type-narrowing before the renderer.** These reprs almost always come from `str(dict)` / `str(list)` / `str(class)` paths.

---

### 035 — Social-card crawlers blocked by robots.txt Disallow on /og/ (2026-04-26) [Crawler etiquette / OG image delivery]

- **Symptom:** Tweets sharing automateedge.cloud blog posts rendered as Twitter's generic `summary` placeholder card (📰 icon, no image) instead of the gold-logo + title OG card. The `/og/blog/<slug>.png` URL returned a valid 1200×630 PNG when fetched manually with any user-agent (including `User-Agent: Twitterbot/1.0` — server-side check passed cleanly).
- **Root cause:** [frontend/robots.txt](../frontend/robots.txt) had `Disallow: /og/` (original intent: keep OG card images out of search-result image indexes). Twitterbot, LinkedInBot, Facebook External Hit, and Slackbot all respect robots.txt — they fetch `/robots.txt` first when resolving a page's `og:image` URL, see the disallow, and refuse to load the image. Twitter then falls back to the small `summary` card layout regardless of the page's `<meta name="twitter:card" content="summary_large_image">` declaration. The disallow was effectively a global "don't show our card on social" rule the original author hadn't intended.
- **Fix:** [frontend/robots.txt:6](../frontend/robots.txt#L6) — changed `Disallow: /og/` to `Allow: /og/`. Updated stale comments in [backend/app/routers/og.py:13-15](../backend/app/routers/og.py#L13-L15) and [nginx.conf:231-235](../nginx.conf#L231-L235) to reflect the new policy. Force-recreated the `web` container so nginx serves the updated `robots.txt` from the `frontend/` mount.
- **Prevention:**
  - **OG card paths must be Allow-listed in robots.txt**, not Disallow-listed. Search engines don't index image URLs as pages anyway, so the original disallow had no practical search-hygiene benefit but blocked every social-card preview platform-wide.
  - **Twitter caches OG fetch results per-page-URL for ~7 days** with no public re-fetch API (their Card Validator was retired in 2021). The fix only applies to *new* tweets after Twitter naturally re-crawls. LinkedIn's [Post Inspector](https://www.linkedin.com/post-inspector/) DOES still allow forced re-fetch for affected LinkedIn shares — use it to validate the fix without waiting for the cache to expire.
  - **Cloudflare prepends a managed `User-agent: *` block to robots.txt** (per [reference_cloudflare_edge.md](memory)) — don't assume the served file matches the origin verbatim. Test with `curl https://<host>/robots.txt` after deploy.

---

### 034 — Banned-term regex matched within longer domain string (2026-04-26) [Validator / regex anchoring]

- **Symptom:** Pillar post upload at `/admin/blog` was rejected with `body_html contains banned term(s): ['github.com/">GitHub']`. The post's only `github.com` substring was a legitimate trusted-source citation — `<a href="https://octoverse.github.com/">GitHub Octoverse report</a>`. `octoverse.github.com` IS in [trusted_sources.json](../backend/data/trusted_sources.json) as an allowed citation domain.
- **Root cause:** `_OPERATIONAL_LEAKS` regex `github\.com/\S+` at [backend/app/services/blog_publisher.py:59](../backend/app/services/blog_publisher.py#L59) matched as a substring within `octoverse.github.com/`. The greedy `\S+` then ate `">GitHub` until the next whitespace, producing a misleading error message that pointed at the wrong byte offset. Two compounding bugs: (1) no domain-boundary anchor, (2) trailing pattern too greedy (HTML attribute closures and anchor text were captured into the "match").
- **Fix:** [backend/app/services/blog_publisher.py:58-67](../backend/app/services/blog_publisher.py#L58-L67) — replaced with `(?<![\w.-])github\.com/[^\s"'<>]*`. Negative lookbehind ensures the match starts at a real domain boundary (so `octoverse.github.com/` and `gist.github.com/...` both pass through cleanly); the explicit URL-char class scopes the trailing match to the URL itself rather than greedily eating closing quote + anchor text. Two regression tests added in [test_blog_validator.py](../backend/tests/test_blog_validator.py): `test_pillar_tier_allows_trusted_github_subdomains` (asserts `octoverse.github.com` + `gist.github.com` cites pass) and `test_bare_github_homepage_link_still_blocked` (asserts the original threat — bare `github.com/` URLs — still trips).
- **Prevention:**
  - **Banned-term regexes that target a domain must use a domain-boundary negative lookbehind** like `(?<![\w.-])` — otherwise legitimate longer-domain citations (`*.github.com`, `subdomain.example.com`) get matched as substrings of trusted hosts.
  - **Use a URL-char class (`[^\s"'<>]*`) instead of `\S+`** for the trailing portion. `\S+` greedily eats HTML attribute closures and produces error messages that point at the wrong location, sending the author hunting for a non-existent bug.
  - When error messages contain unusual character sequences (`'github.com/">GitHub'`), suspect over-greedy regex capture before suspecting the content.

---

### 033 — Email composer double-escaped a controlled HTML literal during refactor (2026-04-26) [Refactor / HTML rendering]

- **Symptom:** During Phase 3 review of the new `weekly_digest.py` composer, line 196 wrapped `intro_html` in `_esc_str()` before interpolating into the section template. `intro_html` was set on line 187 to a literal containing `<strong>...</strong>` tags around an integer task count. The escape would render `&lt;strong&gt;` in the email instead of bold text — every "Great week — N tasks done" message would have shown literal `<strong>3 tasks</strong>` to the recipient.
- **Root cause:** Sonnet refactor extracted the rendering logic from [backend/app/services/weekly_reminder.py:142](backend/app/services/weekly_reminder.py#L142) into the new section helper, but added a defensive `_esc_str()` wrapping that didn't exist in the original. The original was correct because the only interpolated value (`done_this_week`) is an int from `SQL COUNT(*)` — no XSS risk — and the surrounding `<strong>` tags are static template text. The refactor pattern "wrap every f-string interpolation in escape" misfires when the variable already holds controlled HTML.
- **Fix:** [backend/app/services/weekly_digest.py:196-201](backend/app/services/weekly_digest.py#L196-L201) — dropped the `_esc_str()` wrap on `intro_html`, kept it on every other interpolated value (`url`, `company_name`, `loc_str`, `tldr` snippet, `published`, etc.). Added regression test [backend/tests/test_weekly_digest.py::test_roadmap_section_html_renders_strong_tag_literally](backend/tests/test_weekly_digest.py) that builds a real Progress row with `done_this_week>0` and asserts `<strong>` survives unescaped AND `&lt;strong&gt;` does not appear.
- **Prevention:**
  - **An HTML escape on a variable named `*_html` is almost always wrong** — the suffix signals "I already contain HTML." Escape applies to user input or DB-sourced strings interpolated into HTML *attributes/text*, not to controlled internal templates. Code review rule: if a variable name ends in `_html` and the next line wraps it in any escape helper, flag.
  - **When refactoring a render function, diff the interpolation patterns against the original line-by-line** — a "defensive" addition is a behavior change. The original `weekly_reminder.py` rendered fine in production for months; the refactor broke it.
  - **Always include at least one test that asserts the rendered HTML contains the expected literal markup** (e.g. `<strong>`), not just that the function returns non-None. Output-shape tests catch escape regressions; structural-only tests don't.

---

## Patterns to watch for

| Pattern | Risk | Prevention |
|---------|------|------------|
| Cookie name conflicts | High | Check all middleware before naming cookies |
| `.env` changes not applied | High | Always `--force-recreate`, never just `restart` |
| f-strings with HTML / JS / JSON / CSS | High | Double EVERY literal brace `{{ }}`. Test rendered output before push. Move >100-line templates to Jinja2 files. |
| SQLite NOT NULL migrations | Medium | Always add `server_default` |
| Real credentials in docs | Critical | Never. Use placeholders. Grep staged diff. |
| AI model retirement | Medium | Verify model exists before deploying |
| Async generator error handling | Medium | Raise exceptions, don't yield error strings |
| Auth changes without test updates | Medium | Update tests in same commit as auth changes |
| SSRF on outbound HTTP | High | Block private IPs, metadata, disable redirects |
| CSRF substring match | Medium | Use parsed hostname equality, reject missing headers |
| Raw setattr from JSON | Medium | Always validate with Pydantic model first |
| DB strings in AI prompts | Medium | JSON-encode lists, truncate strings, validate output |
| Opt-in feature with prerequisite gate | Medium | Opt-in must work independently of other state |
| AI call without `db=` or `log_usage` | High | Every AI call must log to `ai_usage_log` with `tokens > 0`. Use `get_last_tokens()` helper. |
| Scraped HTML with surrogate characters | Medium | Sanitize at ingest time with `_strip_surrogates`; fallback sanitizer in `_serialize` is a safety net only. |
| SSR HTMLResponse missing viewport meta | Medium | Every `return f"""<!DOCTYPE html>` must include `<meta name="viewport" content="width=device-width, initial-scale=1">`. Missing = mobile renders at desktop width. |
| Public SSR `<table>` with >4 columns | Low | Wrap in `<div class="table-wrap">` with `overflow-x: auto` — protects against mobile horizontal-scroll the whole page. |
| Uploaded-content rendering without overflow rules | Medium | Blog/post renderers must set `img { max-width: 100% }` and `pre { overflow-x: auto }` — authors can't size content for every viewport. |
| Runtime data dir not in Dockerfile COPY | High | Any new directory under `backend/` that runtime code reads (e.g. `backend/data/`) must be added as `COPY <dir> ./<dir>` in the same PR. Validate by running the consumer inside the container, not just locally. |
| SSR pagination + JS-applied filter | Medium | Either round-trip filters through pagination URLs or hide the SSR control once JS has narrowed the set. Never let a footer link silently drop the filter. |
| Filter-option count vs default filter set | Medium | If `<option>X (45)</option>` advertises a count, the page's initial render must produce that count. Any default filter that narrows further breaks the contract at first paint. |
| HTML escape applied to `*_html` variable | Medium | Variables suffixed `_html` already contain controlled markup — escaping double-encodes it. Only escape user/DB-sourced strings. Refactors that "defensively add escape" are behavior changes; diff vs the original. Tests must assert rendered markup, not just non-None return. |
| `_esc_str(value)` on a dict / list / model | Medium | `_esc_str` (and `html.escape`) silently coerce non-strings via `str(x)`, leaking `{'min': None, ...}` / `[obj at 0x...]` into rendered output. Rule: any `_esc_str(field)` against a JSON-blob field needs an `isinstance(field, str)` guard OR an explicit formatter. Hint at runtime: unusual character sequences in user-reported output (`{'`, `[None`, `<class '`) almost always come from `str(non_string)`. |
| Banned-term regex matching across domain boundaries | High | Anchor with `(?<![\w.-])` negative lookbehind; use `[^\s"'<>]*` for the trailing capture, not `\S+`. Otherwise legitimate longer-domain cites (e.g. `octoverse.github.com`) get matched as substrings and the over-greedy capture produces misleading error messages. |
| robots.txt Disallow on `/og/` or share-asset paths | High | Twitterbot / LinkedInBot / Slackbot / Facebook External Hit respect robots.txt and fall back to placeholder cards when the og:image URL is disallowed. Allow-list anything social previews need to fetch. Twitter caches per-page for ~7 days with no public re-fetch API; LinkedIn's Post Inspector forces re-fetch. Cloudflare may also prepend a managed block — test with `curl /robots.txt` after deploy. |
