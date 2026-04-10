# Data Model

SQLite database via async SQLAlchemy 2.0. Every table has `id`, `created_at`, `updated_at`. Timestamps are UTC `DATETIME`. All foreign keys cascade delete unless otherwise noted.

## Tables

### `users`

The central entity. One row per signed-in human.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | autoincrement |
| `email` | TEXT UNIQUE NOT NULL | normalized to lowercase on insert |
| `name` | TEXT | display name |
| `avatar_url` | TEXT NULL | from Google, or gravatar for OTP users |
| `provider` | TEXT NOT NULL | `"google"` or `"otp"` |
| `provider_id` | TEXT NULL | Google's `sub` claim; NULL for OTP users |
| `github_username` | TEXT NULL | set by user in profile |
| `learning_goal` | TEXT NULL | from profile; max 200 chars |
| `experience_level` | TEXT NULL | `beginner` / `intermediate` / `advanced` |
| `is_admin` | BOOLEAN NOT NULL DEFAULT 0 | set manually in DB for the maintainer |
| `last_seen_version` | TEXT NULL | last plan version the user saw; used for "what's new" banner |
| `created_at` | DATETIME NOT NULL | |
| `updated_at` | DATETIME NOT NULL | |

**Indexes:** unique on `email`, index on `provider_id`.

### `otp_codes`

Short-lived codes for email sign-in. Rows are cleaned up by a background task every hour.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `email` | TEXT NOT NULL | normalized lowercase; does not require an existing user row |
| `code_hash` | TEXT NOT NULL | SHA-256 of the 6-digit code + a per-row salt |
| `salt` | TEXT NOT NULL | random 16-byte hex |
| `attempts` | INTEGER NOT NULL DEFAULT 0 | invalidated at 5 |
| `expires_at` | DATETIME NOT NULL | now + 10 minutes |
| `consumed_at` | DATETIME NULL | set on successful verify; code then unusable |
| `created_at` | DATETIME NOT NULL | |

**Indexes:** index on `email`, index on `expires_at` (for cleanup).

### `sessions`

Server-side session records keyed by JWT `jti`. Lets us revoke individual sessions (sign out everywhere).

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `jti` | TEXT UNIQUE NOT NULL | JWT ID claim |
| `user_id` | INTEGER NOT NULL FK users.id | cascade |
| `issued_at` | DATETIME NOT NULL | |
| `expires_at` | DATETIME NOT NULL | |
| `revoked_at` | DATETIME NULL | set on logout |
| `user_agent` | TEXT NULL | captured at sign-in |
| `ip` | TEXT NULL | captured at sign-in (ipv4/ipv6 as text) |

**Indexes:** unique on `jti`, index on `user_id`.

### `user_plans`

Each user has an active plan. We keep archived plans when the user switches goal/duration so progress isn't destroyed.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `user_id` | INTEGER NOT NULL FK users.id | cascade |
| `template_key` | TEXT NOT NULL | e.g. `generalist_6mo_intermediate` |
| `plan_version` | TEXT NOT NULL | the curriculum version at time of enrollment, e.g. `"1.1"` |
| `status` | TEXT NOT NULL | `active` / `archived` / `completed` |
| `enrolled_at` | DATETIME NOT NULL | |
| `archived_at` | DATETIME NULL | |

**Indexes:** index on `user_id`, unique on `(user_id, status)` where status=`active` (enforced in app logic; SQLite partial indexes supported).

### `progress`

One row per (user, plan, week, checkbox).

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `user_plan_id` | INTEGER NOT NULL FK user_plans.id | cascade |
| `week_num` | INTEGER NOT NULL | 1-indexed within the plan |
| `check_idx` | INTEGER NOT NULL | 0-indexed within the week's checklist |
| `done` | BOOLEAN NOT NULL DEFAULT 0 | |
| `completed_at` | DATETIME NULL | set when done flips to true |
| `updated_at` | DATETIME NOT NULL | |

**Indexes:** unique on `(user_plan_id, week_num, check_idx)`, index on `user_plan_id`.

### `repo_links`

Linked GitHub repos per week.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `user_plan_id` | INTEGER NOT NULL FK user_plans.id | cascade |
| `week_num` | INTEGER NOT NULL | |
| `repo_owner` | TEXT NOT NULL | |
| `repo_name` | TEXT NOT NULL | |
| `default_branch` | TEXT NULL | fetched from GitHub at link time |
| `last_commit_sha` | TEXT NULL | fetched at link time; updated on re-evaluation |
| `linked_at` | DATETIME NOT NULL | |

**Indexes:** unique on `(user_plan_id, week_num)`.

### `evaluations`

AI-generated repo evaluations.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `repo_link_id` | INTEGER NOT NULL FK repo_links.id | cascade |
| `score` | INTEGER NOT NULL | 0–100 |
| `summary` | TEXT NOT NULL | short paragraph |
| `strengths_json` | TEXT NOT NULL | JSON array of strings |
| `improvements_json` | TEXT NOT NULL | JSON array of strings |
| `commit_sha` | TEXT NOT NULL | the commit this evaluation was run against |
| `model` | TEXT NOT NULL | e.g. `"gemini-1.5-flash"` or `"llama-3.3-70b-versatile"` |
| `created_at` | DATETIME NOT NULL | |

**Indexes:** index on `repo_link_id`, index on `created_at`.

### `plan_versions`

Versioned curriculum changelog (server-side). The frontend also has its own `PLAN_VERSIONS` constant, but the source of truth lives here and the frontend constant is regenerated from this table on every deploy (or loaded dynamically via an endpoint in a future version).

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `version` | TEXT UNIQUE NOT NULL | e.g. `"1.2"` |
| `published_at` | DATETIME NOT NULL | |
| `label` | TEXT NOT NULL | e.g. `"October 2026 refresh"` |
| `changes_json` | TEXT NOT NULL | JSON array of strings shown in the UI |
| `is_current` | BOOLEAN NOT NULL DEFAULT 0 | exactly one row is current |

**Indexes:** unique on `version`.

### `curriculum_proposals`

Output of the quarterly sync script, awaiting maintainer review.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `source_run` | TEXT NOT NULL | cron run identifier, e.g. `"2026-07-01"` |
| `proposal_md` | TEXT NOT NULL | the full markdown from the sync script |
| `status` | TEXT NOT NULL | `pending` / `applied` / `rejected` |
| `reviewer_id` | INTEGER NULL FK users.id | maintainer who reviewed |
| `reviewed_at` | DATETIME NULL | |
| `notes` | TEXT NULL | maintainer's notes |
| `created_at` | DATETIME NOT NULL | |

**Indexes:** index on `status`, index on `created_at`.

### `rate_limits` (optional — slowapi in-memory works for v1)

Only if we need cross-process rate limiting. Skip for v1.

### `link_health`

Weekly dead-link checker results.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `template_key` | TEXT NOT NULL | plan template where the link lives |
| `week_num` | INTEGER NOT NULL | |
| `resource_idx` | INTEGER NOT NULL | 0-indexed within the week's resources |
| `url` | TEXT NOT NULL | |
| `last_status` | INTEGER NULL | last HTTP status code |
| `last_checked_at` | DATETIME NULL | |
| `consecutive_failures` | INTEGER NOT NULL DEFAULT 0 | |

**Indexes:** index on `(template_key, week_num)`.

## Relationships summary

```
users ────1:N──── user_plans ────1:N──── progress
  │                     │
  │                     └────1:N──── repo_links ────1:N──── evaluations
  │
  ├────1:N──── sessions
  │
  └────1:N──── otp_codes (via email, not FK)
```

## Migration strategy

- Initial migration creates all tables defined above.
- Every schema change lives in a new Alembic migration in `backend/alembic/versions/`.
- Never edit a past migration; always add a new one.
- Migrations run automatically on backend container startup via `alembic upgrade head` in the entrypoint.
- Before any destructive migration (column drop, table rename), back up the SQLite file: `cp /data/app.db /data/backup-$(date +%s).db`.

## SQLite-specific notes

- Run in **WAL mode** (`PRAGMA journal_mode=WAL`) for concurrent reads during writes. Set this on engine startup.
- Set `PRAGMA foreign_keys=ON` on every connection (SQLAlchemy `event.listens_for` hook).
- Use `DATETIME` not `TIMESTAMP` — SQLAlchemy handles the conversion and timezone-naive storage.
- VACUUM once a week in a low-traffic window to reclaim space from deleted rows.
