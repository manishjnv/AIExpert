# Tasks

Phased backlog for building the platform. Each task has a clear acceptance criterion (AC). Work top to bottom. Never start a new phase before the previous one is done and its tests are passing.

When a task is completed, mark it with ✅ and add the commit SHA that shipped it. When blocked, note the blocker inline.

---

## Phase 1 — Skeleton and local stack (target: 1 session)

**Goal:** A Docker Compose stack comes up on a laptop. The existing frontend HTML loads via nginx. `GET /api/health` returns 200.

### 1.1 FastAPI app factory
- [ ] Create `backend/app/main.py` with a FastAPI app, CORS middleware (permissive for dev), JSON error handler for all HTTPExceptions
- [ ] `/api/health` returns `{"status":"ok","version":"dev"}`
- **AC:** `curl localhost:8000/api/health` returns 200 with the expected body when running `uvicorn app.main:app` directly

### 1.2 Config loading
- [ ] Create `backend/app/config.py` with a Pydantic `Settings` class loading from env
- [ ] Required fields: `database_url`, `jwt_secret`, `cors_origins`, `env` (dev/prod)
- [ ] Optional fields: `google_client_id`, `google_client_secret`, `gemini_api_key`, `groq_api_key`, `smtp_*`, etc.
- [ ] App startup validates required fields; fails loudly if `jwt_secret` is the default "changeme"
- **AC:** App refuses to start in prod mode without a real JWT secret; works in dev with defaults

### 1.3 Dockerfile + compose
- [ ] `backend/Dockerfile` — python:3.12-slim base, uv or pip install, uvicorn entrypoint
- [ ] `docker-compose.yml` already exists — update it to reference the new backend service (replace `tracker-db` pocketbase with `backend` fastapi)
- [ ] Compose brings up both services; nginx proxies `/api/*` to backend on port 8000
- **AC:** `docker compose up -d` → `curl localhost:8080/api/health` returns 200

### 1.4 Learner count endpoint (stub)
- [ ] `GET /api/learner-count` returns `{"count":0}` initially; count will become real once the users table exists
- **AC:** Endpoint returns 200 with the expected shape

### 1.5 Frontend loads through nginx
- [ ] Copy the existing tracker HTML to `frontend/index.html`
- [ ] Confirm nginx serves it at `/`
- [ ] Confirm the tracker runs in pure-local mode (no backend calls beyond `/api/learner-count`)
- **AC:** Visiting `http://localhost:8080` shows the tracker; checkboxes work via localStorage; no console errors

---

## Phase 2 — Database and models (target: 1 session)

**Goal:** SQLAlchemy async setup, Alembic migrations, all tables from DATA_MODEL.md created.

### 2.1 Async DB engine
- [ ] Create `backend/app/db.py` with async engine, session factory, `get_db()` dependency
- [ ] Enable WAL and foreign_keys pragmas on connection
- **AC:** An integration test inserts and reads back a trivial row

### 2.2 ORM models
- [ ] Create all model files listed in ARCHITECTURE.md under `backend/app/models/`
- [ ] Match schema from DATA_MODEL.md exactly
- [ ] Add `created_at` / `updated_at` mixin
- **AC:** `Base.metadata.create_all` creates all tables without errors on an empty SQLite file

### 2.3 Alembic setup
- [ ] Initialize Alembic in `backend/alembic/`
- [ ] Write the initial migration matching DATA_MODEL.md
- [ ] Backend container entrypoint runs `alembic upgrade head` before starting uvicorn
- **AC:** Starting a fresh stack creates all tables; re-running is a no-op

### 2.4 Learner count wired to DB
- [ ] `/api/learner-count` counts `users` rows; cached 60s in-memory
- **AC:** Manually inserting a user row bumps the counter after cache expiry

---

## Phase 3 — Auth: Google SSO + OTP (target: 2–3 sessions)

**Goal:** Users can sign in via Google or email OTP. JWT session cookies. `GET /api/auth/me` works.

### 3.1 JWT helpers
- [ ] Create `backend/app/auth/jwt.py` with `issue_token(user)` and `verify_token(token)`
- [ ] JTI is a UUID; token lifetime 30 days
- [ ] Sessions table row created on issue, marked revoked on logout
- **AC:** Unit tests cover issue/verify/revoke

### 3.2 `get_current_user` dependency
- [ ] `backend/app/auth/deps.py` with `get_current_user` that reads the `session` cookie, verifies the JWT, loads the user
- [ ] Separate `get_current_admin` that additionally checks `is_admin`
- **AC:** Protected endpoints return 401 without cookie, 200 with valid cookie, 403 for non-admin hitting admin routes

### 3.3 Google OAuth via Authlib
- [ ] `backend/app/auth/google.py` — OAuth2 client config
- [ ] `GET /api/auth/google/login` → redirect to Google
- [ ] `GET /api/auth/google/callback` → exchange code → upsert user → issue cookie → redirect to `/`
- **AC:** End-to-end sign-in works from a browser with real Google creds

### 3.4 Email OTP
- [ ] `backend/app/auth/otp.py` with `generate_code`, `hash_code`, `verify_code`
- [ ] `POST /api/auth/otp/request` rate limited via slowapi
- [ ] `POST /api/auth/otp/verify` with attempt counter
- [ ] Email sender in `backend/app/services/email_sender.py` using aiosmtplib + Brevo SMTP
- [ ] OTP email template (plaintext + minimal HTML)
- **AC:** End-to-end OTP sign-in works with a real email account (use a testing account, not a maintainer account)

### 3.5 Cleanup task
- [ ] Background task that deletes expired OTP codes every hour
- [ ] Background task that deletes revoked/expired sessions daily
- **AC:** Expired rows disappear on schedule

### 3.6 `GET /api/auth/me` + `POST /api/auth/logout`
- [ ] Both endpoints as per API_SPEC.md
- **AC:** Sign-in → `/api/auth/me` returns the user → `/api/auth/logout` → `/api/auth/me` returns 401

---

## Phase 4 — Plans and progress (target: 2 sessions)

**Goal:** Users can enroll in a plan. Progress ticks persist. Anonymous → signed-in migration works.

### 4.1 Plan templates on disk
- [ ] Create `backend/app/curriculum/templates/generalist_6mo_intermediate.json` matching the existing tracker content
- [ ] Add a loader that reads the JSON and validates it against a Pydantic schema
- [ ] Start with ONE template; others are copy-paste variants
- **AC:** Loading the template produces a typed object with 24 weeks

### 4.2 `POST /api/plans` (enroll) + `GET /api/plan/default`
- [ ] Creates a `user_plans` row, archives any previous active plan
- [ ] `GET /api/plan/default` returns the default plan template (`generalist_6mo_intermediate.json`) for anonymous browsing
- **AC:** Re-enrolling archives the old plan; user_plans table has exactly one `status='active'` per user at all times; `/api/plan/default` returns the default plan without auth

### 4.3 `GET /api/plans/active` + `GET /api/plan-versions`
- [ ] Returns the plan template merged with the user's progress
- [ ] `GET /api/plan-versions` returns the full changelog from the `plan_versions` table
- **AC:** Freshly enrolled plan returns all weeks with `done=false` for every checkbox; `/api/plan-versions` returns the version history

### 4.4 `PATCH /api/progress`
- [ ] Upserts the progress row
- [ ] Sets `completed_at` when done flips true
- **AC:** Frontend tick persists; unchecking clears `completed_at`

### 4.5 `POST /api/progress/migrate`
- [ ] Accepts the localStorage blob, merges by the rule in ARCHITECTURE.md
- [ ] Returns the full merged state
- **AC:** Anonymous user with ticks signs in → ticks appear in their cloud state; signing in on a second device doesn't clobber cross-device state

### 4.6 Frontend wires to backend
- [ ] When signed in, checkboxes call `PATCH /api/progress` (debounced 800ms)
- [ ] On sign-in, frontend calls `POST /api/progress/migrate` with localStorage contents, then clears the keys it migrated
- [ ] Sync badge in the toolbar shows Synced / Saving / Local only / Sync failed states
- **AC:** End-to-end sign-in + tick flow works; refreshing the page preserves state from the server

---

## Phase 5 — Profile and plan customization (target: 1 session)

**Goal:** Users can set their goal/duration/experience and get a new plan.

### 5.1 Profile endpoints
- [ ] `GET /api/profile`, `PATCH /api/profile`, `DELETE /api/profile`, `GET /api/profile/export` per API_SPEC.md
- **AC:** All four work; delete cascades correctly; export returns all the user's data as JSON

### 5.2 Profile page UI
- [ ] Modal or route that shows editable profile fields
- [ ] Save button calls PATCH
- **AC:** User can change their display name and github_username; changes persist across reload

### 5.3 Plan customization UI
- [ ] First-sign-in modal: pick goal, duration, experience
- [ ] Calls `POST /api/plans` with the selection
- [ ] The modal can be reopened from the profile page to change the plan
- **AC:** Picking different options produces visibly different plans

### 5.4 At least 3 plan templates
- [ ] `generalist_6mo_intermediate.json`
- [ ] `generalist_3mo_intermediate.json` (abbreviated — condensed weeks, same structure)
- [ ] `generalist_12mo_beginner.json` (stretched out, more foundation weeks)
- **AC:** Each loads and renders correctly

---

## Phase 6 — GitHub linking (target: 1 session)

**Goal:** Users can paste a repo URL, validated against the GitHub API, and link it to a week.

### 6.1 GitHub client
- [ ] `backend/app/services/github_client.py` with `fetch_repo(owner, name)` via httpx
- [ ] Handles 404, 403 (rate limit), 200
- [ ] Returns `{owner, name, default_branch, last_commit_sha, last_commit_date}`
- **AC:** Unit test against a known public repo (mocked httpx); integration test hits a real public repo

### 6.2 `POST /api/repos/link` + `DELETE /api/repos/link`
- [ ] Endpoints per API_SPEC.md
- **AC:** Linking a public repo succeeds; linking a non-existent repo returns 404 with a friendly error

### 6.3 Frontend repo link UI
- [ ] Each week card gets a "Link repo" input with a validate+save button
- [ ] On save, shows a chip with the repo name and last commit date
- [ ] "Unlink" button to remove
- **AC:** End-to-end linking works; the chip appears immediately after save

---

## Phase 7 — AI evaluation (target: 2 sessions)

**Goal:** Click "Evaluate" on a week with a linked repo → AI score + summary shows up.

### 7.1 Secret sanitizer
- [ ] `backend/app/ai/sanitize.py` — scrub filenames and contents that look like secrets
- [ ] Excluded filename patterns: `.env*`, `*secret*`, `*credentials*`, `*.pem`, `*.key`, `id_rsa*`, `*.p12`, `*.pfx`
- [ ] Content patterns: regex-detect high-entropy strings, common API key formats
- **AC:** Unit tests cover common secret patterns

### 7.2 Gemini client
- [ ] `backend/app/ai/gemini.py` with `complete(prompt, json_response=True)` using the free-tier Gemini 1.5 Flash model
- [ ] Handles 429 (rate limit), 500, timeouts with exponential backoff
- **AC:** Successfully calls Gemini and returns a parsed response

### 7.3 Groq fallback
- [ ] `backend/app/ai/groq.py` mirroring the same interface
- **AC:** `provider.complete()` falls back to Groq if Gemini returns a retryable error

### 7.4 Provider router
- [ ] `backend/app/ai/provider.py` wraps both with retry and provider selection
- **AC:** Unit tests with mocked clients cover success + fallback paths

### 7.5 Evaluation service
- [ ] `backend/app/services/evaluate.py`:
  - Load week's repo link
  - Fetch GitHub content (README + top 10 small files + tree)
  - Sanitize
  - Build prompt from `prompts/evaluate.txt`
  - Call provider
  - Parse JSON result
  - Insert Evaluation row
- **AC:** Running the service against a known public repo returns a score 0–100

### 7.6 `POST /api/evaluate` + `GET /api/evaluations`
- [ ] Endpoints per API_SPEC.md
- [ ] 24h cooldown per repo per user
- **AC:** First call succeeds; second call within 24h returns 429; call after cooldown succeeds

### 7.7 Frontend evaluation UI
- [ ] "Evaluate" button on each week that has a linked repo
- [ ] Loading state during the 3–8s call
- [ ] Score shown with a visual gauge, strengths and improvements as two-column lists, summary as a paragraph
- **AC:** End-to-end click → result render works smoothly

---

## Phase 8 — AI chat (target: 1 session)

**Goal:** Floating chat button opens a panel. Messages stream from Gemini.

### 8.1 SSE endpoint
- [ ] `POST /api/chat` with SSE response streaming tokens from Gemini
- [ ] Rate limit: 20 per user per hour
- [ ] System prompt from `prompts/chat.txt` with the current week's context
- **AC:** curl with `-N` shows tokens streaming in real time

### 8.2 Frontend chat panel
- [ ] Floating button bottom-right
- [ ] Opens a panel with message list + input
- [ ] Messages stream in as tokens arrive
- [ ] History kept in JS memory, scoped to the current week
- **AC:** End-to-end chat works; answers cite resources when relevant

---

## Phase 9 — LinkedIn sharing (target: 1 session)

**Goal:** Milestone completion shows a share button. Click opens LinkedIn's share intent. The shared URL is a nice branded page.

### 9.1 Share page route
- [ ] `GET /share/{user_id}/{milestone_id}` — public HTML page with OG tags
- [ ] Shows user's first name, milestone title, platform name
- **AC:** Page loads; OG tags present; no private data exposed

### 9.2 Dynamic OG image
- [ ] `GET /share/{user_id}/{milestone_id}/og.svg` — 1200×630 SVG with styled content
- [ ] Cached 1 hour via HTTP Cache-Control
- **AC:** Image loads and validates as SVG; LinkedIn's post inspector renders it

### 9.3 Share button in frontend
- [ ] Appears on month completion and capstone completion
- [ ] Click opens `https://www.linkedin.com/sharing/share-offsite/?url=...` in a new tab
- **AC:** Button appears at the right moments; click opens LinkedIn

---

## Phase 10 — Admin panel (target: 1 session)

**Goal:** Maintainer can view stats, users, and curriculum proposals.

### 10.1 Admin routes
- [ ] All admin endpoints per API_SPEC.md
- [ ] Protected by `get_current_admin`
- **AC:** Non-admin gets 403; admin gets the data

### 10.2 Minimal admin UI
- [ ] Simple HTML pages under `/admin/`, server-rendered by Jinja2 (no SPA)
- [ ] Dashboard, users list, proposals list
- **AC:** Admin can sign in, see stats, approve/reject proposals

---

## Phase 11 — Quarterly curriculum sync (target: 1 session)

**Goal:** A cron job runs a script that fetches syllabi and generates a proposal markdown for the maintainer.

### 11.1 Sync script
- [ ] `scripts/quarterly-sync.py` as a standalone Python file runnable via `python -m scripts.quarterly-sync`
- [ ] Fetches curated sources, diffs against last snapshot, sends to Gemini with the quarterly_sync prompt
- [ ] Writes `proposals/YYYY-MM-DD-proposal.md` in the repo
- [ ] Inserts a `curriculum_proposals` row
- **AC:** Running manually produces a file in `proposals/` and a DB row

### 11.2 Cron container
- [ ] Add a separate `cron` service to `docker-compose.yml` that runs the script on the 1st of the quarter
- **AC:** Running with a test schedule (every 5 min) triggers the script and produces output

---

## Phase 12 — Polish and ship (target: 1 session)

### 12.1 End-to-end smoke test
- [ ] Sign in, enroll, tick boxes, link a repo, evaluate, chat, share — all in one session, all working
### 12.2 Security pass
- [ ] Run through `docs/SECURITY.md` checklist; fix anything flagged
### 12.3 Deploy to VPS
- [ ] Follow `docs/DEPLOYMENT.md`
- [ ] Confirm live site works end-to-end
### 12.4 Public soft launch
- [ ] Share with 3–5 friends for feedback
- [ ] Fix anything broken
- [ ] Share publicly

---

## Phase 13 — Jobs early-expiry detection (target: <1 session)

**Goal:** A job filled before `valid_through` stops being served as `published` without waiting for admin action. Closes the "ATS removes listing on day 10, we keep showing it till day 45" gap.

**Context:** [docs/JOBS.md §7.6](JOBS.md#L252-L255) covers date-based expiry only. Greenhouse/Lever give no signal when a role is filled — the listing just disappears from the feed. We must infer closure from absence.

### 13.1 Disappearance detection in ingest

- [ ] In `backend/app/services/jobs_ingest.py`, after per-source fetch, compute `expected_ids = {published jobs from this source}` and `seen_ids = {external_ids in today's feed}`.
- [ ] For each `id in expected_ids - seen_ids`: increment `_meta.missing_streak` (default 0) on the job row.
- [ ] For each `id in expected_ids ∩ seen_ids`: reset `_meta.missing_streak = 0`.
- [ ] When `missing_streak >= 2`: flip `status=expired`, stamp `_meta.expired_reason = "source_removed"`, stamp `_meta.expired_on = today`.
- [ ] Skip if the source itself returned 0 jobs (treat as source outage, not mass-fill). Log warning instead.
- **AC:** Unit test — seed 3 published jobs, feed returns 2 of them for 2 runs → the missing one flips to `expired` on the second run, not the first.

### 13.2 Sitemap + SEO wiring

- [ ] On flip to `expired`, drop from `sitemap-jobs.xml` on next regeneration (confirm via test).
- [ ] Expired page already renders "This job has closed" + `X-Robots-Tag: noindex` per JOBS.md §7.6 — no change, just a test.
- **AC:** Integration test — `GET /jobs/<slug>` on an expired job returns 200 + `X-Robots-Tag: noindex` + "closed" copy.

### 13.3 Admin visibility

- [ ] `/admin/jobs?tab=expired` already exists; add a sub-filter "Auto-expired (source removed)" driven by `_meta.expired_reason`.
- [ ] 24h stats strip: add `auto-expired: N` counter alongside scraped/published/rejected.
- **AC:** Admin sees at a glance how many jobs auto-expired yesterday per source; high rate from one source = investigate.

### 13.4 Optional weekly apply-URL health check

- [ ] Deferred unless §13.1 proves insufficient. Weekly HEAD-request on every `published` `apply_url`; 404/410 → flag in admin.
- **AC:** N/A until built.

**Rollout:** one PR, ~30–50 lines + tests. No migration (uses existing `_meta` JSON). Safe — only triggers on `published` jobs demonstrably missing for 2 consecutive days.

**Update JOBS.md §7.6** when merged to document the new auto-expiry mechanism alongside the date-based one.

---

## Task status log

Claude Code: update this section as tasks complete.

| Phase | Task | Status | Commit | Notes |
|---|---|---|---|---|
| 1 | 1.1 | done | cb40943 | HTTPException handler added for API_SPEC error format |
| 1 | 1.2 | done | cb40943 | Skeleton existed; prod validation verified |
| 1 | 1.3 | done | cb40943 | docker compose up works; all 3 containers healthy |
| 1 | 1.4 | done | cb40943 | Stub returns {"count":0}; wired to DB in Phase 2 |
| 1 | 1.5 | done | cb40943 | Frontend loads at /; checkboxes work via localStorage |
