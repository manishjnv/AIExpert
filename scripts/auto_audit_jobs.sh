#!/bin/bash
# auto_audit_jobs.sh — VPS-native WEEKLY cron for the Opus classification audit.
#
# Clones the auto_summarize_drafts.sh / auto_curate_social.sh pattern. The
# unified scheduler stamps ~1% of Tier-1 published jobs `audit.status=pending`
# each week (scripts/select_audit_sample.py). This wrapper then runs ONE Opus
# pass to verdict them via `claude -p` on the Max plan (no API spend) and writes
# the verdicts back.
#
# SAFE: mismatches (agreed=false) are only FLAGGED into admin_notes for human
# review — nothing is auto-reclassified or auto-unpublished. See Layer 10 in
# docs/JOBS_CLASSIFICATION.md.
#
# Schedule: 30 4 * * 1 (Mon 04:30 UTC = 10:00 IST) — see cron.d/auto_audit_jobs
# Lock:      /tmp/auto_audit_jobs.lock (flock -n, prevents overlapping runs)
# Log:       /var/log/auto_audit_jobs.log
# Token:     /root/.claude/oauth_token  (Max plan)

set -euo pipefail

OAUTH_TOKEN_FILE=/root/.claude/oauth_token
OAUTH_EXPIRES_FILE=/root/.claude/oauth_token.expires
ROADMAP_DIR=/srv/roadmap
TMPDIR=/tmp/auto-audit-jobs
MODEL=claude-opus-4-7
mkdir -p "$TMPDIR"

# ---- Token expiry check -------------------------------------------------------
if [ -f "$OAUTH_EXPIRES_FILE" ]; then
    EXPIRES_DATE=$(cat "$OAUTH_EXPIRES_FILE")
    EXPIRES_EPOCH=$(date -d "$EXPIRES_DATE" +%s 2>/dev/null || echo 0)
    NOW_EPOCH=$(date +%s)
    DAYS_LEFT=$(( (EXPIRES_EPOCH - NOW_EPOCH) / 86400 ))
    if [ "$DAYS_LEFT" -le 0 ]; then
        echo "FATAL: OAuth token expired on $EXPIRES_DATE — renew at /root/.claude/oauth_token" >&2
        exit 4
    elif [ "$DAYS_LEFT" -le 7 ]; then
        echo "WARNING: OAuth token expires in ${DAYS_LEFT} day(s) ($EXPIRES_DATE) — renew soon" >&2
    elif [ "$DAYS_LEFT" -le 30 ]; then
        echo "NOTICE: OAuth token expires in ${DAYS_LEFT} day(s) ($EXPIRES_DATE)" >&2
    fi
fi

# ---- Pre-flight checks --------------------------------------------------------
[ -f "$OAUTH_TOKEN_FILE" ] || { echo "FATAL: $OAUTH_TOKEN_FILE missing" >&2; exit 2; }
[ -d "$ROADMAP_DIR" ]      || { echo "FATAL: $ROADMAP_DIR missing" >&2; exit 2; }
command -v docker >/dev/null || { echo "FATAL: docker not found" >&2; exit 2; }
command -v claude >/dev/null || { echo "FATAL: claude CLI not found" >&2; exit 2; }

cd "$ROADMAP_DIR"

EXPORT_FILE="$TMPDIR/export.json"
PROMPT_FILE="$TMPDIR/prompt.txt"
OUTPUT_FILE="$TMPDIR/verdicts.json"

echo "$(date -Iseconds) INFO: starting Opus audit run"

# ---- Export pending-audit jobs as a ready-to-run prompt -----------------------
docker compose exec -T backend python -m scripts.export_audit_jobs > "$EXPORT_FILE" || {
    echo "$(date -Iseconds) ERROR: export_audit_jobs failed" >&2
    rm -f "$EXPORT_FILE"
    exit 3
}

COUNT=$(python3 -c "import json,sys
try: print(json.load(open('$EXPORT_FILE')).get('count',0))
except Exception: print(0)" 2>/dev/null)

if [ "${COUNT:-0}" -eq 0 ]; then
    echo "$(date -Iseconds) INFO: no jobs pending audit — nothing to do"
    rm -f "$EXPORT_FILE"
    exit 0
fi

echo "$(date -Iseconds) INFO: $COUNT job(s) pending audit"

# ---- Extract the ready-to-run prompt ------------------------------------------
python3 -c "import json; open('$PROMPT_FILE','w').write(json.load(open('$EXPORT_FILE'))['prompt'])"

# ---- Run ONE Opus pass over the whole sample ----------------------------------
CLAUDE_CODE_OAUTH_TOKEN="$(cat "$OAUTH_TOKEN_FILE")" \
    claude -p --model "$MODEL" < "$PROMPT_FILE" > "$OUTPUT_FILE" || {
    echo "$(date -Iseconds) ERROR: claude CLI failed — next week's cron will retry" >&2
    rm -f "$EXPORT_FILE" "$PROMPT_FILE" "$OUTPUT_FILE"
    exit 3
}

[ -s "$OUTPUT_FILE" ] || {
    echo "$(date -Iseconds) ERROR: empty Opus output — next week's cron will retry" >&2
    rm -f "$EXPORT_FILE" "$PROMPT_FILE" "$OUTPUT_FILE"
    exit 3
}

# ---- Apply verdicts (import is the tolerant parser + per-row committer) --------
docker compose exec -T backend python -m scripts.import_audit_results < "$OUTPUT_FILE" || {
    echo "$(date -Iseconds) WARNING: import_audit_results parsed/updated nothing — check Opus output" >&2
}

echo "$(date -Iseconds) INFO: auto_audit_jobs.sh finished"
rm -f "$EXPORT_FILE" "$PROMPT_FILE" "$OUTPUT_FILE"
