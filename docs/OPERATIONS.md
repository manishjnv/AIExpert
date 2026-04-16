# Operations Guide

Complete setup and operations reference for the AI Roadmap Platform. Covers every integration, credential, container, and configuration needed to run the platform from scratch.

## 1. VPS Setup

| Item | Value |
|------|-------|
| IP | `72.61.227.64` |
| SSH alias | `a11yos-vps` |
| OS | Ubuntu (Docker pre-installed) |
| Project path | `/srv/roadmap` |
| Data path | `/data/app.db` (SQLite, inside container volume `./data:/data`) |

### Initial setup
```bash
ssh a11yos-vps
mkdir -p /srv/roadmap
cd /srv/roadmap
git clone https://github.com/manishjnv/AIExpert.git .
chmod 777 data/   # container runs as non-root 'app' user
cp .env.example .env
# Edit .env with production values (see section 3)
docker compose up -d
```

## 2. Docker Containers

Three services defined in `docker-compose.yml`:

| Container | Image | Purpose | Port | Health |
|-----------|-------|---------|------|--------|
| `roadmap-backend` | `roadmap-backend` (built from `backend/Dockerfile`) | FastAPI API server | 8000 (internal) | `/api/health` |
| `roadmap-web` | `nginx:1.27-alpine` | Serves frontend HTML, proxies `/api/*` to backend | 8090 → 80 | — |
| `roadmap-cron` | `roadmap-backend` (same image) | Runs quarterly curriculum sync scheduler | — | — |

### Common commands
```bash
# Start all services
docker compose up -d

# Rebuild and restart backend
docker compose up -d --build --force-recreate backend

# View logs
docker compose logs -f backend
docker compose logs backend --tail 50

# Run tests
docker compose exec backend pytest tests/ -v

# Run migrations
docker compose exec backend alembic upgrade head

# Access SQLite
docker compose exec backend sqlite3 /data/app.db

# Restart a single service
docker compose restart backend
```

### Volumes
- `./data:/data` — SQLite database (`app.db`), sync snapshots
- `./frontend:/usr/share/nginx/html:ro` — Frontend HTML (nginx)
- `./scripts:/app/scripts:ro` — Quarterly sync script (both backend + cron)
- `./proposals:/proposals` — Generated curriculum proposals (cron)

## 3. Environment Variables (.env)

The `.env` file lives at `/srv/roadmap/.env` on the VPS. **Never commit this file.**

```bash
# ----- Core -----
ENV=prod                           # dev | prod
APP_VERSION=0.1.0
PUBLIC_BASE_URL=https://automateedge.cloud
CORS_ORIGINS=https://automateedge.cloud
LOG_LEVEL=INFO

# ----- Database -----
DATABASE_URL=sqlite+aiosqlite:////data/app.db

# ----- Auth / Sessions -----
JWT_SECRET=<64-char-hex>           # Generate: openssl rand -hex 32
JWT_EXPIRY_DAYS=30

# ----- Google OAuth2 -----
GOOGLE_CLIENT_ID=<from Google Cloud Console>
GOOGLE_CLIENT_SECRET=<from Google Cloud Console>
GOOGLE_REDIRECT_URI=https://automateedge.cloud/api/auth/google/callback

# ----- SMTP (OTP email) -----
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=manishjnvk@gmail.com
SMTP_PASSWORD=<16-char Google App Password, no spaces>
SMTP_FROM=contact@automateedge.cloud
SMTP_FROM_NAME=AI Roadmap

# ----- AI Providers -----
GEMINI_API_KEY=<from Google AI Studio>
GEMINI_MODEL=gemini-1.5-flash
GROQ_API_KEY=                      # Optional fallback
GROQ_MODEL=llama-3.3-70b-versatile

# ----- GitHub (optional) -----
GITHUB_TOKEN=                      # For higher rate limits

# ----- Maintainer -----
MAINTAINER_EMAIL=manishjnvk@gmail.com
```

### How to update .env on VPS
```bash
ssh a11yos-vps
nano /srv/roadmap/.env             # Edit values
cd /srv/roadmap
docker compose up -d --force-recreate backend   # Restart required to pick up changes
```

**Important:** `docker compose restart` does NOT re-read `.env`. You must use `--force-recreate`.

## 4. Google OAuth Setup

### Prerequisites
- Google Cloud Console account
- A project (e.g., "automateedge")

### Steps
1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. **APIs & Services → OAuth consent screen**
   - User type: External
   - App name: "AI Roadmap"
   - Support email: `manishjnvk@gmail.com`
   - Authorized domains: `automateedge.cloud`
   - Save
3. **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
   - Application type: Web application
   - Authorized redirect URI: `https://automateedge.cloud/api/auth/google/callback`
   - Click Create
4. Copy **Client ID** and **Client Secret** to `.env`
5. Recreate backend container

### Testing
- Visit `https://automateedge.cloud` → click "Sign In" → redirects to Google → returns with session cookie
- In testing mode, add test users in OAuth consent screen

### Cookie details
- Name: `auth_token` (NOT `session` — Authlib's SessionMiddleware uses `session`)
- Flags: `httpOnly; Secure; SameSite=Lax; Path=/; Max-Age=2592000`
- JWT claims: `sub` (user ID), `jti` (UUID, stored in `sessions` table), `iat`, `exp`

## 5. OTP Email Setup

### Prerequisites
- Gmail account with 2FA enabled
- Google App Password generated
- Domain with DNS control (Cloudflare)

### Step 1: Google App Password
1. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
2. Select "Mail" → Generate
3. Copy the 16-character password (format: `xxxx xxxx xxxx xxxx`)
4. Set in `.env` as `SMTP_PASSWORD=<paste without spaces>`

### Step 2: Cloudflare Email Routing
1. Cloudflare Dashboard → `automateedge.cloud` → **Email Routing**
2. Enable Email Routing
3. Create rule: `contact` → forward to `manishjnvk@gmail.com`
4. Add DNS records automatically (MX records for Cloudflare)
5. Verify destination email (`manishjnvk@gmail.com`)

### Step 3: Gmail "Send mail as" Alias
1. Gmail → Settings → **Accounts and Import** → "Send mail as" → **Add another email address**
2. Name: `AI Roadmap`, Email: `contact@automateedge.cloud`
3. SMTP server: `smtp.gmail.com`, Port: `587`, Username: `manishjnvk@gmail.com`, Password: app password
4. Gmail sends verification code to `contact@automateedge.cloud`
5. Cloudflare forwards it to `manishjnvk@gmail.com`
6. Paste code → Verified

### OTP flow
1. User enters email → `POST /api/auth/otp/request` → returns 204 always (no user enumeration)
2. Backend generates 6-digit code, hashes with SHA-256 + salt, stores in `otp_codes` table
3. Sends email via `aiosmtplib` → Gmail SMTP → delivers from `contact@automateedge.cloud`
4. User enters code → `POST /api/auth/otp/verify` → checks hash, attempts < 5, not expired (10 min)
5. On success: upserts User row, issues JWT cookie, returns `{"ok":true}`

### Rate limits
- OTP request: 5 per IP per 15 minutes (slowapi)
- OTP verify: 10 per IP per 15 minutes (slowapi)

## 6. Gemini AI Setup

### Get API key
1. Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Create API key → select project
3. Set in `.env` as `GEMINI_API_KEY=<value>`. Google issues keys in two formats today: classic `AIzaSy...` (39 chars) and the newer `AQ.Ab...` (variable length). Both authenticate against `generativelanguage.googleapis.com`; the backend treats them identically.

### 6.1 Rotating a leaked or expired AI provider key

Follow this exact sequence when you have a replacement token in hand. Applies to Gemini, Groq, Anthropic, OpenAI, and any other provider key stored in the VPS `.env`. See [RCA-023](RCA.md) for the incident that prompted this procedure.

1. **Never paste the new key into the chat.** If you must share it with a teammate, use a password manager or encrypted channel. Secrets pasted into chat transcripts persist in context snapshots — a leak you can't undo.
2. **Back up `.env` on the VPS** before mutating it:
   ```bash
   ssh a11yos-vps "cp /srv/roadmap/.env /srv/roadmap/.env.bak-$(date +%s)"
   ```
   Keeps a dated rollback target in case the new key is malformed.
3. **Replace the value in place** with `sed -i` so you don't accidentally overwrite unrelated lines:
   ```bash
   ssh a11yos-vps "sed -i 's|^GEMINI_API_KEY=.*|GEMINI_API_KEY=<new-value>|' /srv/roadmap/.env"
   ```
4. **Confirm the write** by echoing just the prefix (never the full value):
   ```bash
   ssh a11yos-vps "grep '^GEMINI_API_KEY=' /srv/roadmap/.env | cut -c1-30"
   ```
5. **Force-recreate the backend container** — `docker compose restart` does NOT reload env vars (see RCA-002):
   ```bash
   ssh a11yos-vps "cd /srv/roadmap && docker compose up -d --force-recreate backend"
   ```
6. **Smoke-test the provider** with a trivial call:
   ```bash
   ssh a11yos-vps "docker compose -f /srv/roadmap/docker-compose.yml exec -T backend python -c '
   import asyncio
   from app.ai.provider import complete
   async def main():
       r, m = await complete(prompt=\"Return JSON {\\\"ok\\\":true}\", json_response=True, task=\"smoke_test\")
       print(f\"SUCCESS model={m} result={r}\")
   asyncio.run(main())
   '"
   ```
   Expected: `SUCCESS model=gemini-2.5-flash result={'ok': True}`. Any exception means the key is wrong — revert to the backup and investigate before proceeding.
7. **Scan logs for auth errors** that may have fired from concurrent traffic while the new key was settling:
   ```bash
   ssh a11yos-vps "docker compose -f /srv/roadmap/docker-compose.yml logs --tail 100 backend | grep -iE '401|403|unauthorized|invalid.*key'"
   ```
   Zero matches = success.
8. **Revoke the old key** in the provider dashboard (for Gemini: https://aistudio.google.com/app/apikey → delete). Only the human operator can do this — the backend has no way to invalidate a key upstream. Skipping this step leaves the leaked key usable.

Cleanup: once the new key has been stable for a day, delete the `.env.bak-*` backup: `ssh a11yos-vps "rm /srv/roadmap/.env.bak-<timestamp>"`.

### Free tier limits
- Model: `gemini-1.5-flash`
- 15 requests per minute
- 1 million tokens per day
- No credit card required

### How it's used
| Feature | Endpoint | Prompt file | Mode |
|---------|----------|-------------|------|
| AI Evaluation | `POST /api/evaluate` | `prompts/evaluate.txt` | JSON response (score, summary, strengths, improvements) |
| AI Chat | `POST /api/chat` | `prompts/chat.txt` | SSE streaming |
| Quarterly Sync | Cron script | `prompts/quarterly_sync.txt` | Text response |

### Fallback
If Gemini fails (429/500), falls back to Groq (`GROQ_API_KEY` required). Provider logic in `ai/provider.py` with exponential backoff.

## 7. Database

### SQLite with WAL mode
- File: `/data/app.db` (inside container volume)
- WAL mode + foreign keys enabled via SQLAlchemy event listener
- Async driver: `aiosqlite`

### Tables (10)
`users`, `otp_codes`, `sessions`, `user_plans`, `progress`, `repo_links`, `evaluations`, `plan_versions`, `curriculum_proposals`, `link_health`

### Migrations
```bash
# Run pending migrations
docker compose exec backend alembic upgrade head

# Create new migration after model changes
docker compose exec backend alembic revision --autogenerate -m "description"

# Migrations run automatically on container startup (Dockerfile CMD)
```

### Backup
```bash
# Manual backup
docker compose exec backend cp /data/app.db /data/backup-$(date +%s).db

# Recommended: add daily cron on VPS
0 3 * * * docker compose -f /srv/roadmap/docker-compose.yml exec -T backend cp /data/app.db /data/backup-$(date +\%Y\%m\%d).db
```

### Admin operations
```bash
# Set a user as admin
docker compose exec backend sqlite3 /data/app.db "UPDATE users SET is_admin=1 WHERE email='manishjnvk@gmail.com';"

# Check user count
docker compose exec backend sqlite3 /data/app.db "SELECT count(*) FROM users;"

# List active plans
docker compose exec backend sqlite3 /data/app.db "SELECT u.email, up.template_key, up.status FROM user_plans up JOIN users u ON u.id=up.user_id WHERE up.status='active';"
```

## 8. Domain & Caddy (Reverse Proxy)

### DNS (Cloudflare)
| Type | Name | Content | Proxy |
|------|------|---------|-------|
| A | `@` | `72.61.227.64` | Proxied (orange cloud) |
| CNAME | `www` | `automateedge.cloud` | Proxied |

### SSL/TLS
- Cloudflare SSL mode: **Full** (not Full Strict)
- Caddy uses `tls internal` (self-signed cert)
- Cloudflare handles public HTTPS

### Caddy config
File: `/opt/ti-platform/caddy/Caddyfile`
```
automateedge.cloud, www.automateedge.cloud {
    tls internal
    @www host www.automateedge.cloud
    redir @www https://automateedge.cloud{uri} permanent
    import security-headers
    reverse_proxy 172.17.0.1:8090
}
```

### Reload Caddy after changes
```bash
docker exec ti-platform-caddy-1 caddy reload --config /etc/caddy/Caddyfile
```

### Traffic flow
```
User → Cloudflare CDN (HTTPS) → Caddy (port 443, self-signed) → nginx (port 8090) → FastAPI (port 8000)
```

## 9. Cron (Quarterly Sync)

### What it does
- Runs as a separate Docker container (`roadmap-cron`)
- Executes `scripts/quarterly_sync_scheduler.py`
- On 1st of Jan/Apr/Jul/Oct at 02:00 UTC:
  1. Fetches university syllabi and practitioner sources
  2. Sends content to Gemini for curriculum update proposals
  3. Writes proposal to `/proposals/YYYY-MM-DD-proposal.md`
  4. Inserts `curriculum_proposals` row (visible in admin panel)

### Test mode
```bash
# Run manually
docker compose exec cron python -m scripts.quarterly_sync

# Run on short interval (every 5 min)
# Set env: QUARTERLY_SYNC_INTERVAL_SECONDS=300
```

## 10. Deployment Workflow

### Standard deploy
```bash
# On local machine
git push origin master

# On VPS
ssh a11yos-vps
cd /srv/roadmap
git pull
docker compose up -d --build backend    # Backend changes
# OR just git pull for frontend-only changes (nginx serves from volume)
```

### Frontend-only changes
```bash
# Just pull — nginx serves directly from ./frontend/ volume
ssh a11yos-vps "cd /srv/roadmap && git pull"
# Hard-refresh browser (Ctrl+Shift+R)
```

### Full rebuild
```bash
ssh a11yos-vps "cd /srv/roadmap && git pull && docker compose up -d --build --force-recreate"
```

## 11. Monitoring & Troubleshooting

### Health check
```bash
curl https://automateedge.cloud/api/health
# Returns: {"status":"ok","version":"0.1.0","env":"prod"}
```

### Logs
```bash
# All services
docker compose -f /srv/roadmap/docker-compose.yml logs -f

# Backend only, last 50 lines
docker compose -f /srv/roadmap/docker-compose.yml logs backend --tail 50

# Filter errors
docker compose -f /srv/roadmap/docker-compose.yml logs backend 2>&1 | grep -i error
```

### Common issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| OAuth cookie not sticking | `.env` not reloaded | `docker compose up -d --force-recreate backend` |
| 500 on callback | Missing `get_settings()` call | Check backend logs for traceback |
| OTP email not arriving | Gmail alias unverified | Gmail Settings → verify alias |
| Plan not loading | `loadActivePlan()` JS error | Check browser console (F12) |
| Admin 401 | Not set as admin | `sqlite3 /data/app.db "UPDATE users SET is_admin=1 WHERE email='...';"` |
| Container can't write DB | `/data` permissions | `chmod 777 /srv/roadmap/data/` |
| `.env` changes not applied | Used `restart` instead of `--force-recreate` | `docker compose up -d --force-recreate backend` |

## 12. Security Checklist (run before every deploy)

- [ ] `.env` not in repo: `git ls-files | grep -i env`
- [ ] No placeholder values in prod `.env`: `grep -E "changeme|YOUR_|example" .env`
- [ ] `JWT_SECRET` is 32+ random bytes
- [ ] `ENV=prod` on VPS
- [ ] Rate limits tested on OTP endpoint
- [ ] `/api/auth/me` without cookie returns 401
- [ ] `/admin/` as non-admin returns 403
- [ ] All security headers present (check via browser DevTools → Network → Response Headers)
