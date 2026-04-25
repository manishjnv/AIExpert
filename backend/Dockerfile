# ============================================================
# AI Roadmap Platform — backend Dockerfile
# Python 3.12 slim, non-root user, minimal layers
# ============================================================

FROM python:3.12-slim

# System dependencies (sqlite3 CLI for backups, curl for debugging, ca-certs for TLS)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        sqlite3 \
        curl \
        ca-certificates \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user
RUN useradd --create-home --shell /bin/bash app

WORKDIR /app

# Install dependencies first (leverages Docker layer cache)
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy the rest of the backend
COPY app ./app
COPY data ./data
COPY alembic.ini ./
COPY alembic ./alembic
COPY tests ./tests
COPY pytest.ini ./

# Seed templates — kept separate so volume mount can overlay /app/app/curriculum/templates/
COPY app/curriculum/templates /app/seed_templates

# Data volume mount point
RUN mkdir -p /data && chown -R app:app /data /app

USER app

EXPOSE 8000

# Run migrations (if any exist) then start the server
CMD ["sh", "-c", "if [ -z \"$(ls /app/app/curriculum/templates/*.json 2>/dev/null)\" ]; then cp /app/seed_templates/*.json /app/app/curriculum/templates/; fi && if ls alembic/versions/*.py 1>/dev/null 2>&1; then alembic upgrade head; fi && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
