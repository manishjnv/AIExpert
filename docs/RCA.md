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

---

## Patterns to watch for

| Pattern | Risk | Prevention |
|---------|------|------------|
| Cookie name conflicts | High | Check all middleware before naming cookies |
| `.env` changes not applied | High | Always `--force-recreate`, never just `restart` |
| f-strings with HTML | Medium | Use HTML entities, not backslash escapes |
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
