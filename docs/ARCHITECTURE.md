# Architecture

High-level view of how the platform is put together, why each piece exists, and the boundaries between components. Read this before making any major structural decision.

## System diagram

```
                    ┌─────────────────────────────────────┐
                    │   User's browser                    │
                    │   - vanilla JS frontend             │
                    │   - localStorage for anon progress  │
                    └──────────────┬──────────────────────┘
                                   │ HTTPS
                                   ▼
                    ┌─────────────────────────────────────┐
                    │   Existing reverse proxy            │
                    │   (Caddy / nginx / Traefik)         │
                    │   Handles TLS for all your sites    │
                    └──────────────┬──────────────────────┘
                                   │ HTTP on 127.0.0.1:8080
                                   ▼
    ┌──────────────────────────────────────────────────────┐
    │   Docker network: roadmap-net                         │
    │                                                       │
    │   ┌────────────────┐         ┌──────────────────┐    │
    │   │  nginx-web     │ ───────▶│  backend        │    │
    │   │  serves HTML   │ /api/*  │  FastAPI        │    │
    │   │  proxies /api  │◀────────│  async SQLA     │    │
    │   └────────────────┘         │  aiosqlite      │    │
    │                              └────────┬─────────┘    │
    │                                       │               │
    │                              ┌────────▼─────────┐    │
    │                              │  /data volume    │    │
    │                              │  app.db (SQLite) │    │
    │                              └──────────────────┘    │
    │                                                       │
    │   ┌────────────────┐                                  │
    │   │  cron          │ runs quarterly-sync.py           │
    │   │  (separate     │                                  │
    │   │   container)   │                                  │
    │   └────────────────┘                                  │
    └──────────────────────────────────────────────────────┘
                                   │
                                   ▼
         ┌────────────────────────────────────────┐
         │   External services (free tiers)       │
         │   • Google OAuth2     (auth)           │
         │   • Google Gemini API (AI chat + eval) │
         │   • GitHub REST API   (repo checks)    │
         │   • Brevo SMTP        (OTP email)      │
         │   • arXiv / uni sites (quarterly sync) │
         └────────────────────────────────────────┘
```

## Stack rationale

### Why FastAPI + Python

- Claude Code is especially effective with Python. Fewer round-trips, fewer subtle bugs.
- FastAPI gives us automatic OpenAPI docs, type hints everywhere, and async-first design without ceremony.
- Rich ecosystem: Authlib, httpx, SQLAlchemy, Alembic, slowapi, python-jose — everything we need is mature.
- Easy to dockerize, tiny image.

### Why SQLite and not Postgres

- Single-file database, no separate container, no backup complexity.
- For this workload (thousands of users, small per-user state), SQLite in WAL mode handles it easily.
- Migration to Postgres later is a 2-hour job if we ever need it (SQLAlchemy abstracts the dialect).
- Backups are trivial: `cp app.db backup.db`.
- Lower VPS footprint.

### Why Authlib for OAuth and not a heavier auth library

- Authlib is battle-tested, focused, and plays well with FastAPI.
- We don't need FastAPI-Users or similar — too many features we don't use, too much magic.
- Keeps our auth flow readable and debuggable.

### Why JWT in httpOnly cookies and not localStorage

- localStorage is readable by any JS on the page — an XSS bug becomes an account takeover.
- httpOnly cookies are invisible to JS; even if we have an XSS bug, the session survives.
- SameSite=Lax prevents CSRF on state-changing requests from other origins.
- For state-changing requests, we add a CSRF token pattern (double-submit cookie or custom header).

### Why Gemini and not OpenAI

- Free tier is generous: Gemini 1.5 Flash offers 15 RPM and 1M tokens/day with no credit card.
- Long context window (1M tokens) handles repo evaluation without chunking tricks.
- No billing surprises.
- Fallback to Groq (also free) if Gemini is down.
- No paid APIs anywhere in the stack — hard constraint.

### Why vanilla JS on the frontend

- The existing single-file tracker already works and is nice. We extend it, we don't replace it.
- No build step = faster iteration, easier deployment, smaller attack surface.
- If the UI gets complex enough to justify a framework later (Vue or Alpine), we can port incrementally.
- Zero npm dependency rot.

### Why Docker Compose and not Kubernetes / systemd units / bare processes

- Compose is the right size for a small VPS with a few services.
- The user already runs Docker on their VPS (stated requirement).
- Portable: the same compose file works on the dev laptop and the VPS.
- Isolated networks keep the roadmap stack from interfering with other sites on the same host.

## Module boundaries (backend)

```
backend/app/
├── main.py              FastAPI app factory, middleware, startup
├── config.py            Pydantic Settings, env loading, validation
├── db.py                Async engine + session factory
├── models/
│   ├── __init__.py
│   ├── user.py          User, OtpCode, Session
│   ├── progress.py      Progress, RepoLink
│   ├── evaluation.py    Evaluation
│   └── curriculum.py    PlanTemplate, PlanVersion, Changelog
├── routers/
│   ├── auth.py          /api/auth/*
│   ├── profile.py       /api/profile
│   ├── progress.py      /api/progress
│   ├── evaluate.py      /api/evaluate
│   ├── chat.py          /api/chat (SSE)
│   ├── public.py        /api/health, /api/learner-count
│   ├── admin.py         /admin/api/*
│   └── share.py         /share/*
├── services/
│   ├── plan_generator.py   takes goal×duration×level, returns plan
│   ├── github_client.py    wraps GitHub REST calls
│   ├── email_sender.py     SMTP OTP sender
│   └── merge_progress.py   anon→signed-in progress migration
├── auth/
│   ├── google.py        OAuth2 flow
│   ├── otp.py           OTP generate + verify
│   ├── jwt.py           issue + verify JWT
│   ├── deps.py          get_current_user dependency
│   └── ratelimit.py     slowapi wrappers
├── ai/
│   ├── gemini.py        Gemini API client
│   ├── groq.py          Groq fallback client
│   ├── provider.py      routing + retry between providers
│   ├── sanitize.py      scrub secrets before sending to LLM
│   └── prompts/
│       ├── evaluate.txt
│       ├── chat.txt
│       └── quarterly_sync.txt
└── curriculum/
    └── templates/
        ├── generalist_6mo_intermediate.json
        └── ...
```

**Boundary rules:**

- **routers/** contain zero business logic. They parse input, call a service, return the response.
- **services/** contain business logic. They call models and external clients.
- **models/** contain ORM definitions and table-specific methods only (classmethod factories, `to_dict()`, etc.).
- **auth/** is used by routers via FastAPI dependency injection. Never import auth from services.
- **ai/** is called only from services, never directly from routers. That lets us swap providers or add caching without touching the API surface.

## Request lifecycle examples

### Example A: User ticks a checkbox

```
1. Browser: checkbox click → JS updates UI optimistically → PATCH /api/progress
   body: { week: 5, idx: 2, done: true }
2. nginx-web: proxies /api/progress to backend:8000
3. backend: routers/progress.py receives request
4. auth/deps.py: extracts JWT from cookie, verifies, loads user
5. services/progress.py: upserts Progress row for (user_id, week, idx)
6. SQLAlchemy: async INSERT ... ON CONFLICT DO UPDATE
7. routers/progress.py: returns 204 No Content
8. Browser: optimistic UI already updated; no rerender needed
```

Total typical latency: 20–50ms.

### Example B: User requests AI evaluation of a repo

```
1. Browser: click "Evaluate" on week 8 → POST /api/evaluate
   body: { week_id: 8 }
2. backend: routers/evaluate.py receives request
3. auth/deps.py: loads user
4. ratelimit: check cooldown (max 1 eval per repo per 24h per user)
5. services/evaluate.py:
   a. Load week's RepoLink for this user
   b. Call github_client.fetch_repo_summary(repo_url)
      → hits GitHub REST API: /repos, /contents, /readme
      → returns { readme, file_tree, top_files: [...] }
   c. Call ai/sanitize.scrub_secrets(top_files)
   d. Build prompt from ai/prompts/evaluate.txt + week objectives + sanitized content
   e. Call ai/provider.complete(prompt, json_response=True)
      → tries gemini first, falls back to groq if 429/500
      → parses JSON response
   f. Insert Evaluation row
6. routers/evaluate.py: returns the Evaluation as JSON
7. Browser: renders score + summary inline
```

Typical latency: 3–8 seconds (dominated by the LLM call).

### Example C: Quarterly curriculum sync

```
1. Cron: 1st of quarter at 02:00 UTC triggers scripts/quarterly-sync.py
2. Script fetches syllabi and newsletters from curated sources via httpx
3. Script diffs against the previous sync snapshot stored at /data/last-sync.json
4. Script sends aggregated text to Gemini with quarterly_sync.txt prompt
5. Gemini returns structured proposal: new topics, revisions, retirements
6. Script writes proposals/YYYY-MM-DD-proposal.md to the repo (via git commit on the host)
7. Maintainer reviews, edits, merges, bumps PLAN_VERSIONS in the frontend, deploys
```

Cron doesn't auto-publish. Human-in-the-loop by design.

## Data flow: anonymous → signed-in migration

This is subtle and worth writing down so we get it right:

1. Anonymous user ticks boxes → stored in `localStorage` keyed by `progress:w{week}_{idx}` and a local `plan_id`
2. User signs in (Google or OTP)
3. After JWT cookie is set, the frontend reads localStorage and calls `POST /api/progress/migrate` with the full local state
4. Backend:
   - If the user has no existing cloud progress → bulk insert everything from the payload
   - If the user has existing cloud progress → merge with this rule: cloud wins where both sides have state (user already chose from another device); local wins for keys cloud doesn't have
5. Backend returns the merged state; frontend clears localStorage for progress keys (keeps settings)
6. Show toast: "Progress synced."

Do not delete localStorage data until the merge returns success.

## External Integrations

Complete list of every external service the platform integrates with, how it's configured, and what it's used for.

### 1. Google OAuth 2.0 (Authentication)

| Field | Value |
|-------|-------|
| Purpose | "Sign in with Google" — primary sign-in method |
| Provider | Google Cloud Console → APIs & Services → Credentials |
| Type | OAuth 2.0 Web Application |
| Scopes | `openid email profile` |
| Redirect URI | `https://automateedge.cloud/api/auth/google/callback` |
| Env vars | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` |
| Backend files | `auth/google.py` (Authlib client), `routers/auth.py` (login/callback endpoints) |
| Cookie | `auth_token` (httpOnly, Secure, SameSite=Lax, 30-day expiry) |
| Notes | Authlib's `SessionMiddleware` uses a separate `session` cookie for OAuth state. Our JWT uses `auth_token` to avoid collision. |

### 2. Google Gemini API (AI Evaluation + Chat)

| Field | Value |
|-------|-------|
| Purpose | AI-powered repo evaluation scoring and conversational chat mentor |
| Provider | Google AI Studio → API Keys |
| Model | `gemini-1.5-flash` (free tier: 15 RPM, 1M tokens/day) |
| Endpoints used | `generateContent` (evaluation), `streamGenerateContent` (chat SSE) |
| Env vars | `GEMINI_API_KEY`, `GEMINI_MODEL` |
| Backend files | `ai/gemini.py` (REST client), `ai/stream.py` (SSE streaming), `ai/provider.py` (fallback routing) |
| Prompts | `prompts/evaluate.txt`, `prompts/chat.txt`, `prompts/quarterly_sync.txt` |
| Rate limits | 24h cooldown per repo per user (evaluation), 20 msg/hr per user (chat) |
| Security | Repo content is sanitized via `ai/sanitize.py` before sending — strips secrets, redacts API keys, excludes `.env`/`.pem`/`id_rsa` files |

### 3. Groq API (AI Fallback)

| Field | Value |
|-------|-------|
| Purpose | Fallback when Gemini is rate-limited or down |
| Provider | Groq Console → API Keys |
| Model | `llama-3.3-70b-versatile` (free tier) |
| Interface | OpenAI-compatible `/v1/chat/completions` |
| Env vars | `GROQ_API_KEY`, `GROQ_MODEL` |
| Backend files | `ai/groq.py` (client), `ai/provider.py` (tries Gemini → Groq with exponential backoff) |

### 4. GitHub REST API (Repo Validation + Content Fetch)

| Field | Value |
|-------|-------|
| Purpose | Validate linked repos exist, fetch file tree and content for AI evaluation |
| Auth | Optional `GITHUB_TOKEN` for higher rate limits (60/hr unauthenticated, 5000/hr with token) |
| Endpoints used | `GET /repos/{owner}/{name}`, `GET /repos/.../commits/{branch}`, `GET /repos/.../git/trees/{branch}`, raw content via `raw.githubusercontent.com` |
| Env vars | `GITHUB_TOKEN` (optional) |
| Backend files | `services/github_client.py` (fetch_repo, parse_repo_input), `services/evaluate.py` (content fetch for AI eval) |
| Security | Only public repos supported. File tree filtered through `sanitize.is_excluded_file()`. Content redacted via `sanitize.redact_secrets()`. |

### 5. Gmail SMTP (OTP Email)

| Field | Value |
|-------|-------|
| Purpose | Send 6-digit OTP codes for email sign-in |
| Provider | Gmail SMTP via Google App Password (2FA required) |
| SMTP server | `smtp.gmail.com:587` (STARTTLS) |
| From address | `contact@automateedge.cloud` (Gmail "Send mail as" alias) |
| Env vars | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_FROM_NAME` |
| Backend files | `services/email_sender.py` (aiosmtplib), `auth/otp.py` (code generation + verification) |
| Dev mode | When `SMTP_HOST` is empty, logs the OTP code instead of sending |
| Rate limits | 5 OTP requests per IP per 15 min (slowapi) |
| Security | OTP codes hashed with SHA-256 + per-row salt. Max 5 attempts. 10-minute expiry. Single-use. |

### 6. Cloudflare (DNS + CDN + Email Routing)

| Field | Value |
|-------|-------|
| Purpose | DNS management, HTTPS termination (proxy mode), email forwarding |
| Domain | `automateedge.cloud` |
| DNS records | A record `@` → `72.61.227.64` (proxied), CNAME `www` → `automateedge.cloud` (proxied) |
| SSL mode | Full (Cloudflare → Caddy with internal/self-signed cert) |
| Email routing | `contact@automateedge.cloud` → forwards to `manishjnvk@gmail.com` |
| Configuration | Cloudflare Dashboard → automateedge.cloud → DNS / SSL/TLS / Email Routing |

### 7. Caddy (Reverse Proxy on VPS)

| Field | Value |
|-------|-------|
| Purpose | Reverse proxy from port 443 to the Docker stack on port 8090 |
| Runs as | Docker container in the `ti-platform` stack |
| Config file | `/opt/ti-platform/caddy/Caddyfile` |
| TLS | `tls internal` (self-signed, Cloudflare handles public TLS) |
| Proxy target | `172.17.0.1:8090` (Docker bridge to roadmap-web nginx) |
| Security headers | HSTS, X-Frame-Options DENY, CSP, Referrer-Policy, Permissions-Policy |

### Integration dependency chain

```
User → Cloudflare CDN → Caddy (VPS) → nginx (Docker) → FastAPI backend
                                                              │
                                    ┌───────────────┬─────────┼──────────┐
                                    ▼               ▼         ▼          ▼
                              Google OAuth    Gemini API   GitHub API   Gmail SMTP
                                              (+ Groq)
```

## Deployment topology

- **Dev:** `docker compose up` on the developer's laptop, SQLite file in `./data/`, hot reload via `uvicorn --reload`
- **Prod:** same compose file on the VPS, reverse proxy in front, SQLite in a named volume, no reload, logs shipped to the host's syslog

No staging environment in v1. If we need one, we add a `docker-compose.staging.yml` override.

## Scalability notes

This stack scales to about 10K–50K registered users on a modest VPS (2 vCPU, 2 GB RAM) before SQLite write contention becomes a concern. If we ever hit that:

- **First upgrade:** move to PostgreSQL (SQLAlchemy makes this a config change + re-migration)
- **Second upgrade:** add Redis for rate-limit storage and session caching
- **Third upgrade:** split the backend into a web tier + worker tier for AI evaluations (Celery or ARQ)

We are nowhere near any of these. Do not preemptively add infrastructure.

## What we deliberately don't have

- **No message queue.** AI evaluations run inline in the request. If they become a bottleneck, we add a queue.
- **No Redis.** slowapi supports in-process memory storage, which is fine for a single-container deployment. Add Redis when we go multi-container.
- **No separate CDN.** The existing reverse proxy serves the static HTML directly.
- **No separate static asset bundle.** Everything is in one HTML file.
- **No microservices.** One backend service, one frontend, done.
- **No feature flags.** If something is half-built, it's behind a route that returns 404 until it's done.

## The north star

**If a new piece of infrastructure isn't required by a feature in PRD.md, we don't add it.** The instinct to over-engineer a small project has killed many side projects. Stay small.
