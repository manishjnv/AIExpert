# Deployment

How to deploy this platform to a VPS alongside your other sites.

## Prerequisites

On the VPS:
- Docker Engine 20.10+
- Docker Compose v2
- An existing reverse proxy (Caddy / nginx / Traefik) handling TLS for your other sites
- A subdomain like `roadmap.yourdomain.com` with DNS A/AAAA records pointing to the VPS
- SSH access as a non-root sudo user

From your local machine:
- `ssh` access to the VPS
- A clone of this repo

## File layout on the VPS

```
/srv/roadmap/                      (or wherever you keep sites)
├── .env                           ← real secrets, never committed
├── docker-compose.yml             ← from the repo
├── nginx.conf                     ← from the repo
├── backend/                       ← from the repo
├── frontend/                      ← from the repo
├── scripts/                       ← from the repo
├── data/                          ← created at runtime
│   ├── app.db                     ← SQLite database
│   └── backups/                   ← daily backups
└── logs/                          ← created at runtime
```

## First-time deployment

### 1. Create the directory and clone the repo

```bash
sudo mkdir -p /srv/roadmap
sudo chown $USER:$USER /srv/roadmap
cd /srv/roadmap
git clone <your-repo-url> .
```

### 2. Create the `.env` file

```bash
cp .env.example .env
chmod 600 .env
```

Edit `.env` and fill in every required value. The file has comments explaining each one.

Critical values:
- `JWT_SECRET` — generate with `openssl rand -hex 32`
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` — from Google Cloud Console OAuth2 credentials
- `GEMINI_API_KEY` — from https://aistudio.google.com
- `GROQ_API_KEY` — from https://console.groq.com
- `SMTP_*` — from your email provider (Brevo, Resend, SendGrid)
- `PUBLIC_BASE_URL` — `https://roadmap.yourdomain.com` (no trailing slash)
- `ENV=prod`

### 3. Configure Google OAuth

In [Google Cloud Console](https://console.cloud.google.com):

1. Create a new project or reuse an existing one
2. APIs & Services → OAuth consent screen → External → fill in app name, support email, developer contact
3. APIs & Services → Credentials → Create credentials → OAuth client ID → Web application
4. Authorized JavaScript origins: `https://roadmap.yourdomain.com`
5. Authorized redirect URIs: `https://roadmap.yourdomain.com/api/auth/google/callback`
6. Copy the client ID and secret into `.env`

### 4. Point your reverse proxy at the tracker

**Caddy:**
```caddyfile
roadmap.yourdomain.com {
    reverse_proxy 127.0.0.1:8080
}
```
```bash
sudo systemctl reload caddy
```

**nginx (host-level, in front of Docker):**
```nginx
server {
    listen 443 ssl http2;
    server_name roadmap.yourdomain.com;
    ssl_certificate     /etc/letsencrypt/live/roadmap.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/roadmap.yourdomain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 120s;
    }
}
server {
    listen 80;
    server_name roadmap.yourdomain.com;
    return 301 https://$host$request_uri;
}
```
```bash
sudo certbot --nginx -d roadmap.yourdomain.com
sudo nginx -t && sudo systemctl reload nginx
```

### 5. Bring up the stack

```bash
docker compose pull
docker compose up -d --build
docker compose logs -f backend
```

On first startup, Alembic creates all tables. Tail the logs until you see `Application startup complete`.

### 6. Verify

```bash
curl -s https://roadmap.yourdomain.com/api/health
# → {"status":"ok","version":"..."}

curl -s https://roadmap.yourdomain.com/api/learner-count
# → {"count":0}
```

Visit `https://roadmap.yourdomain.com` in a browser. You should see the tracker. Try signing in via Google.

### 7. Make yourself admin

```bash
docker compose exec backend python -c "
import asyncio
from app.db import get_session
from app.models.user import User
from sqlalchemy import update
async def main():
    async with get_session() as s:
        await s.execute(update(User).where(User.email == 'your@email.com').values(is_admin=True))
        await s.commit()
        print('done')
asyncio.run(main())
"
```

## Updating the deployment

```bash
cd /srv/roadmap
git pull
docker compose up -d --build backend
docker compose logs -f backend
```

If there's a new migration, it runs automatically on startup.

Zero-downtime is not a goal for v1. A few seconds of 502 during restart is acceptable.

## Backups

### SQLite daily snapshot (cron)

Create `/etc/cron.daily/roadmap-backup`:

```bash
#!/bin/bash
set -e
BACKUP_DIR=/srv/roadmap/data/backups
mkdir -p "$BACKUP_DIR"
DATE=$(date +%Y%m%d)
# Use the SQLite .backup command for a consistent snapshot (safe while the DB is in use)
docker compose -f /srv/roadmap/docker-compose.yml exec -T backend \
  sqlite3 /data/app.db ".backup '/data/backups/app-${DATE}.db'"
# Keep last 30 days
find "$BACKUP_DIR" -name "app-*.db" -mtime +30 -delete
```

```bash
sudo chmod +x /etc/cron.daily/roadmap-backup
```

### Off-site backup (recommended)

Sync the backups directory to an S3 bucket or a second VPS nightly. Example with `rclone`:

```bash
# After configuring an rclone remote named "b2" pointing to Backblaze B2:
rclone sync /srv/roadmap/data/backups b2:my-roadmap-backups --max-age 31d
```

Add to the same cron.daily script if desired.

## Monitoring

Start simple:

- `docker compose ps` — are containers running?
- `docker compose logs --tail=100 backend` — recent logs
- `docker stats` — RAM and CPU usage

If you want a proper dashboard, wire Prometheus + Grafana from your existing monitoring stack (if you have one). Don't add a new monitoring stack just for this service.

## Troubleshooting

**Container won't start, logs say "JWT secret is too short"**
- Your `.env` has the default `changeme`. Generate a real one: `openssl rand -hex 32`.

**Google sign-in redirects to a blank page or "redirect_uri_mismatch"**
- The redirect URI in `.env` (`GOOGLE_REDIRECT_URI`) must match what you configured in Google Cloud Console exactly, including protocol and trailing behavior.

**OTP email never arrives**
- Check `docker compose logs backend | grep -i smtp`
- Verify SMTP credentials in `.env`
- Try sending a test email manually: `docker compose exec backend python -c "from app.services.email_sender import send_test; import asyncio; asyncio.run(send_test('you@example.com'))"` (create this helper if it doesn't exist)
- Check spam folder

**`/api/evaluate` returns "AI service unavailable"**
- Check `GEMINI_API_KEY` is set and valid
- Check Gemini quota in https://aistudio.google.com
- Check Groq fallback is configured
- Check `docker compose logs backend | grep -i "ai"` for the actual error

**Progress not syncing after sign-in**
- Open browser DevTools → Application → Cookies → confirm `session` cookie is set after sign-in
- Open Network tab and verify `PATCH /api/progress` returns 204 on a checkbox click
- If 401: JWT not being sent; check cookie Secure flag and that you're on HTTPS
- If 403: CSRF header missing; check the `X-CSRF-Token` header is being sent

**Container OOM killed**
- `docker stats` during load to see which container is using RAM
- Backend should sit under 200 MB. If higher, something is leaking — check recent changes.

## Rollback

```bash
cd /srv/roadmap
git log --oneline -20           # find the commit to roll back to
git reset --hard <commit-sha>
docker compose up -d --build backend
```

For DB rollbacks, restore from a backup:
```bash
docker compose stop backend
cp /srv/roadmap/data/backups/app-YYYYMMDD.db /srv/roadmap/data/app.db
docker compose start backend
```

## Decommissioning

If you ever shut the platform down:

1. Post a public notice 30 days in advance
2. Enable data export for all users
3. Email all users with an export link
4. After the 30-day window, shut down and delete the DB
