# Security

This document defines the security posture of the platform. Read it before touching anything auth-related, anything that takes external input, anything that calls external APIs, or anything that stores credentials.

## Threat model

**Assets worth protecting:**
1. User accounts (email, Google identity, progress data)
2. Session tokens (JWT in cookies)
3. Google OAuth client secret, Gemini API key, SMTP credentials
4. The SQLite database file
5. The VPS host itself (via not becoming a lateral-movement pivot)

**Realistic attackers:**
- **Script kiddies** running common scanners against any public IP — most likely, handled by rate limits and CSRF
- **OAuth/OTP abuse** — attackers enumerating emails, spam-calling OTP, replaying codes
- **Credential stuffers** — abuse of the sign-in flow with leaked credentials (N/A for us because we don't have passwords)
- **Opportunistic XSS** — bad data in a field we render unsafely, leading to session theft
- **Malicious repos in evaluation** — a user submits a repo designed to make the LLM do something weird or to exfiltrate secrets (we strip secrets; sanitize defensively)
- **Resource abuse** — hitting free-tier API limits to either DoS us or rack up unexpected costs (we have no paid APIs, so the risk is rate-limit exhaustion and functional DoS)

**Out of scope for this threat model:**
- Nation-state adversaries
- Physical access to the VPS
- Compromised Docker images from upstream (we pin specific digests)
- Compromised Python packages (we pin and periodically audit with `pip-audit`)

## Secrets management

### Where secrets live

- **Dev:** in a local `.env` file (git-ignored)
- **Prod:** in a VPS-side `.env` file (not in the repo, not in docker-compose.yml, not in any committed file)
- **CI (if added):** GitHub Actions secrets or similar; never in workflow YAML

### Never in the repo

Grep for these strings before every commit. If any appear in staged files that aren't `.env.example`, stop and investigate:

```
sk-
gh_
ghp_
ghs_
ghu_
ghr_
AIza
GOCSPX
eyJ
-----BEGIN
client_secret
api_key =
password =
```

A pre-commit hook using `gitleaks` or `trufflehog` is recommended. Add it in Phase 12.

### `.env.example` hygiene

- Contains every variable the app reads
- All values are obvious placeholders: `changeme`, `YOUR_GOOGLE_CLIENT_ID`, etc.
- Never copy a real key into this file, even a dev one
- Comments explain what each variable is for and where to get it

## Authentication security

### Password policy

We don't store passwords. Ever. Both sign-in flows are passwordless (Google OAuth or email OTP).

### OTP rules

- Codes are 6 random digits generated via `secrets.randbelow(1_000_000)`
- Stored hashed: `sha256(code + salt)` where salt is a random 16-byte hex per row
- Expiry: 10 minutes
- Max 5 verification attempts per code before invalidation
- Single-use: consumed codes are marked and cannot be reused
- Request rate limit: 5 per IP per 15 min; 3 per email per hour
- Verify rate limit: 10 per IP per 15 min
- Email enumeration protection: `POST /api/auth/otp/request` always returns `204`, never reveals whether the email exists

### JWT rules

- Stored in `httpOnly; Secure; SameSite=Lax` cookies
- Algorithm: HS256 with a 32+ byte secret loaded from env
- Claims: `sub` (user id), `jti` (UUID, stored server-side in `sessions` table), `iat`, `exp`
- Expiry: 30 days
- Revocation: setting `revoked_at` on the session row invalidates the token even before expiry
- Refresh: on every request we slide the expiry if >7 days have passed since last activity

### Session security

- Every JWT issuance inserts a `sessions` row
- Logout sets `revoked_at` and clears the cookie
- "Sign out of all sessions" is a profile feature we can add in v2

## CSRF protection

- **Default:** SameSite=Lax cookie is enough for most requests. Browsers don't send the cookie cross-origin on POST.
- **Extra layer for mutations:** Every POST/PATCH/DELETE also requires an `X-CSRF-Token` header matching a value issued at sign-in and stored in a separate non-httpOnly cookie (`csrf`). The frontend reads the cookie and echoes it into the header (double-submit pattern).
- **Exceptions:** `POST /api/auth/google/callback` uses the state parameter instead (OAuth2 standard).

## Input validation

- **Pydantic models on every endpoint input.** No untyped dict-to-handler passing.
- **Length limits** on every text field matching the DB column.
- **Enum validation** on fields like `provider`, `experience_level`, `status`.
- **URL validation** on GitHub links — must start with `https://github.com/` OR match `owner/repo` format.
- **Email validation** via `email-validator` package, normalized lowercase.

## Output escaping

- **API responses:** JSON. No string concatenation into HTML.
- **Share pages:** Jinja2 autoescape ON. All user-controlled fields (name, first name from Google profile) go through `{{ var }}`, never `{{ var | safe }}`.
- **SVG generation for OG images:** Escape user-controlled strings before embedding in SVG. Use `html.escape()` plus a whitelist of allowed characters for the first name.
- **Frontend innerHTML:** Avoid. Use `textContent` for anything user-controlled. The only `innerHTML` in the existing frontend is template literals with hardcoded structure — audit before merging any changes that add new ones.

## SQL injection

- **SQLAlchemy ORM only.** Never `session.execute(text(f"SELECT ... {user_input}"))`.
- **If raw SQL is ever necessary**, use parameterized `text()` with bound params: `text("SELECT * FROM x WHERE id = :id")`.

## Rate limiting

Applied via `slowapi` on:

| Endpoint | Limit |
|---|---|
| `POST /api/auth/otp/request` | 5 per IP per 15 min; 3 per email per hour |
| `POST /api/auth/otp/verify` | 10 per IP per 15 min |
| `GET /api/auth/google/callback` | 10 per IP per 15 min |
| `POST /api/evaluate` | 1 per repo per user per 24h |
| `POST /api/chat` | 20 per user per hour |
| `POST /api/repos/link` | 30 per user per hour |
| All other endpoints | 300 per IP per hour (generous blanket limit) |

Rate limits are checked before the handler runs. Storage is in-process memory for v1 (fine for single-backend deployment); move to Redis if we ever run multiple backend replicas.

## External API calls

### Gemini / Groq (AI)

- **Payload scrubbing** before sending: the sanitizer strips anything that looks like a secret
- **Content size cap:** 20 KB of text per evaluation; 4 KB per chat message
- **Timeout:** 30 seconds for evaluation, 60 seconds for chat (streaming)
- **Retry:** max 2 retries with exponential backoff; fall back to Groq on persistent Gemini failure
- **No user-controlled prompts in the system role.** User input always goes in the user-role message, never the system prompt.

### GitHub

- **Unauthenticated REST** for v1 (60 requests/hour per IP is enough for a small user base)
- **User-Agent header** set to `ai-roadmap-platform/{version} (contact: {maintainer-email-from-env})`
- **Timeout:** 10 seconds
- **Never log response bodies** containing private repo data (shouldn't happen since we only query public repos, but defensive)

### SMTP

- **TLS required** (STARTTLS or implicit TLS depending on provider)
- **SMTP password** loaded from env; never logged
- **From address** is a dedicated subdomain mailbox like `noreply@mail.yourdomain.com` — not your personal email

## Container security

- **Non-root user in the backend image.** The Dockerfile creates a `app` user and runs uvicorn as that user.
- **Read-only root filesystem** where possible via `docker-compose.yml` `read_only: true` plus targeted `tmpfs` mounts for `/tmp`.
- **No capabilities** beyond default. Add `cap_drop: [ALL]` to services that don't need any.
- **Pinned base image digest** in Dockerfile: `FROM python:3.12-slim@sha256:...`
- **Regular image rebuilds** to pull security patches (weekly cron or manual monthly)

## Network security

- **Only port 8080 exposed** to the host (and bound to 127.0.0.1, not 0.0.0.0). The existing reverse proxy handles public TLS.
- **Internal docker network** isolates the backend from other containers on the host.
- **No outbound connections** from the backend except to the explicit allowlist of external APIs. (If we ever add a Docker network policy, this becomes enforceable.)

## Logging

- **Do log:** request path, method, status, latency, user id (if authenticated), IP, user-agent
- **Do not log:** request bodies for auth endpoints, OTP codes (even hashed), JWT tokens, any email body, any Gemini/Groq request payloads, GitHub tokens
- **Retention:** logs live in the container's stdout, captured by Docker, rotated at 10 MB × 3 files
- **Sensitive events** (failed sign-ins, rate limit trips, admin actions) go to a separate "audit" logger with longer retention

## Backups

- **Daily SQLite backup** via cron: `cp /data/app.db /data/backups/app-$(date +%Y%m%d).db; find /data/backups -mtime +30 -delete`
- **Off-site backup** (optional v2): rclone to S3 or a second VPS

## Dependency hygiene

- **Pin exact versions** in `requirements.txt`: `fastapi==0.115.0`, not `fastapi>=0.115`
- **Dependabot or Renovate** configured for weekly PRs
- **`pip-audit`** run monthly or in CI
- **No transitive dependency overrides** without a recorded reason

## Deletion and export

- Right to export: `GET /api/profile/export` returns all the user's data as JSON
- Right to delete: `DELETE /api/profile` cascades and removes everything
- Soft delete is not used — when a user deletes, the rows are gone

## Content security policy

Served by nginx on the frontend:

```
Content-Security-Policy: default-src 'self';
  script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net;
  style-src 'self' 'unsafe-inline' https://fonts.googleapis.com;
  font-src https://fonts.gstatic.com;
  img-src 'self' data: https://lh3.googleusercontent.com https://avatars.githubusercontent.com;
  connect-src 'self';
  frame-ancestors 'none';
  base-uri 'self';
  form-action 'self';
```

`'unsafe-inline'` for styles/scripts is temporarily OK for the single-file frontend. Tighten by moving inline code to separate files and using a nonce once the frontend grows beyond the single file.

## Other headers nginx sets

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: geolocation=(), microphone=(), camera=()`
- `Strict-Transport-Security: max-age=31536000; includeSubDomains` (set by the outer reverse proxy, since it does TLS)

## Security checklist (run before every deploy)

- [ ] `.env` not in repo (`git ls-files | grep -i env`)
- [ ] No placeholder values left in production `.env` (`grep -E "changeme|YOUR_|example" .env`)
- [ ] `jwt_secret` is 32+ random bytes
- [ ] `pip-audit` passes
- [ ] `docker scout cves` (or equivalent) on the latest image
- [ ] Rate limits tested on at least one auth endpoint
- [ ] CSRF token required for a sample mutation endpoint (test with missing header → 403)
- [ ] Frontend loads over HTTPS only (HSTS header present)
- [ ] `/api/auth/me` without cookie returns 401
- [ ] `/admin/*` as non-admin returns 403
- [ ] All database columns with user input have length limits enforced at the Pydantic layer

## Incident response (brief)

If a breach is suspected:

1. **Immediate:** rotate `jwt_secret` → all sessions invalidated
2. **Immediate:** rotate Google OAuth client secret, Gemini API key, SMTP password in Google Cloud / Gemini / SMTP provider dashboards
3. **Immediate:** stop the backend container, take a snapshot of the DB
4. **Within 24h:** review logs for the 72h before the incident
5. **Within 72h:** notify affected users if PII was exposed
6. **Post-mortem:** write a public changelog entry if needed, fix the root cause, add a regression test
