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
