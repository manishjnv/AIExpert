# API Specification

REST endpoints served by the FastAPI backend. All endpoints are prefixed with `/api`. JSON in and out unless noted. Authenticated endpoints require a valid JWT in the `session` httpOnly cookie.

Legend: 🔓 public · 🔒 authenticated · 👑 admin only

## Public

### `GET /api/health` 🔓
Health check. Returns `{"status":"ok","version":"<git sha>"}`.

### `GET /api/learner-count` 🔓
Returns `{"count": 1234}`. Counts rows in `users`. Cached in-process for 60 seconds.

### `GET /api/plan/default` 🔓
Returns the default plan template for anonymous browsing (`generalist_6mo_intermediate.json`). Used by the frontend on first paint before sign-in.

### `GET /api/plan-versions` 🔓
Returns the full changelog from the `plan_versions` table. Used to render the changelog section at the bottom of the page.

## Auth

### `GET /api/auth/google/login` 🔓
Starts the Google OAuth2 flow. Redirects to Google's consent screen. Stores a state token in a short-lived signed cookie.

### `GET /api/auth/google/callback` 🔓
Google redirects here with the authorization code. Backend exchanges for tokens, validates ID token, upserts a User row, issues a JWT session cookie, redirects to `/`.

### `POST /api/auth/otp/request` 🔓
Body: `{"email":"user@example.com"}`.
Rate limited: 5 requests per IP per 15 min; 3 per email per hour.
Generates a 6-digit code, sends via SMTP, stores a hash. Returns `204 No Content` regardless of whether the email exists (avoids user enumeration).

### `POST /api/auth/otp/verify` 🔓
Body: `{"email":"user@example.com","code":"123456"}`.
Rate limited: 10 per IP per 15 min.
Verifies the code against the hash. On success, upserts a User row (provider=`otp`), issues JWT cookie, returns `{"ok":true}`. On failure, returns `401 {"error":"invalid_or_expired"}`.

### `POST /api/auth/logout` 🔒
Revokes the current session in the `sessions` table, clears the cookie. Returns `204`.

### `GET /api/auth/me` 🔒
Returns the current user: `{"id","email","name","avatar_url","github_username","learning_goal","experience_level","is_admin"}`.

## Profile

### `GET /api/profile` 🔒
Returns the full profile including computed fields: total_weeks, completed_weeks, active_plan, account_created.

### `PATCH /api/profile` 🔒
Body: partial update — any of `name`, `github_username`, `learning_goal`, `experience_level`. Returns the updated profile.

### `DELETE /api/profile` 🔒
Confirms via body `{"confirm":"DELETE"}`. Cascades to all user data. Returns `204`. Clears session cookie.

### `GET /api/profile/export` 🔒
Returns a JSON dump of everything tied to this user — profile, plans, progress, repo_links, evaluations. `Content-Disposition: attachment; filename=my-roadmap-data.json`.

## Plans

### `POST /api/plans` 🔒
Body: `{"goal":"generalist","duration":"6mo","level":"intermediate"}`.
Creates a new `user_plans` row, archives the previous active plan if any, returns the new plan with embedded week data.

### `GET /api/plans/active` 🔒
Returns the user's currently active plan with all weeks and the user's progress merged in.

### `GET /api/plans/{plan_id}` 🔒
Returns a specific plan (must belong to the user). Useful for reviewing archived plans.

## Progress

### `PATCH /api/progress` 🔒
Body: `{"week_num":5,"check_idx":2,"done":true}`.
Upserts a row in `progress`. Returns `204`. Debounced 800ms on the client side.

### `POST /api/progress/migrate` 🔒
Body: `{"progress":{"w1_0":true,"w1_1":true,...}}` — the full localStorage blob from anonymous session.
Merges into the user's active plan with the merge rule from ARCHITECTURE.md. Returns the merged state.

## GitHub

### `POST /api/repos/link` 🔒
Body: `{"week_num":8,"repo_url":"https://github.com/owner/name"}` or `{"week_num":8,"repo":"owner/name"}`.
Validates via GitHub REST `GET /repos/{owner}/{name}`. On 200, upserts `repo_links`. Returns `{"owner","name","default_branch","last_commit_sha","last_commit_date"}`.

### `DELETE /api/repos/link?week_num=8` 🔒
Removes the link for the given week. Does not remove past evaluations.

## AI evaluation

### `POST /api/evaluate` 🔒
Body: `{"week_num":8}`.
Requires a linked repo for that week. Rate limited to 1 per repo per 24h per user. Runs the full evaluation pipeline. Returns the `Evaluation` row as JSON. Long operation (3–8s) — frontend shows a loading spinner.

### `GET /api/evaluations?week_num=8` 🔒
Returns the evaluation history for that week for the current user, newest first.

## AI chat

### `POST /api/chat` 🔒
Body: `{"week_num":5,"message":"..."}`.
Server-Sent Events response. Streams tokens from Gemini.
Rate limited: 20 messages per user per hour.
Each request is stateless — client maintains conversation history and sends recent turns in the `messages` array:
Body (full): `{"week_num":5,"messages":[{"role":"user","content":"..."},{"role":"assistant","content":"..."},{"role":"user","content":"..."}]}`.

## Sharing

### `GET /share/{user_id}/{milestone_id}` 🔓
Public HTML page for LinkedIn share cards. Renders a minimal branded page with OpenGraph meta tags and a link back to the site. No private data.

### `GET /share/{user_id}/{milestone_id}/og.svg` 🔓
Dynamic SVG at 1200×630 with the user's first name, milestone title, platform name. Cached 1 hour.

## Admin 👑

### `GET /admin/api/dashboard` 👑
Returns `{"total_users","dau","wau","mau","completion_per_week","dead_links","recent_signups"}`.

### `GET /admin/api/users?q=&page=&per_page=` 👑
Paginated user listing.

### `GET /admin/api/proposals` 👑
Returns pending curriculum proposals from the quarterly sync.

### `POST /admin/api/proposals/{id}/apply` 👑
Marks a proposal as applied (doesn't actually mutate the curriculum — maintainer still edits the JSON files manually).

### `POST /admin/api/proposals/{id}/reject` 👑
Marks a proposal as rejected.

## Error format

All non-2xx responses return:
```json
{
  "error": "slug_like_this",
  "message": "Human readable message",
  "details": {...optional...}
}
```

Slugs Claude Code should use: `unauthorized`, `forbidden`, `not_found`, `rate_limited`, `invalid_input`, `conflict`, `internal_error`, `upstream_error`, `invalid_or_expired`.

## Conventions

- All timestamps in responses are ISO 8601 UTC: `"2026-07-15T14:30:00Z"`
- All IDs are integers unless noted
- PATCH is partial update; PUT is not used
- DELETE bodies are allowed but avoided; prefer query params or path params
- Pagination: `?page=1&per_page=20`; max per_page is 100
- Cursor-based pagination for high-volume endpoints (evaluations history) — use `?cursor=<opaque>`
