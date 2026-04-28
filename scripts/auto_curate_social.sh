#!/bin/bash
# auto_curate_social.sh — VPS-native daily cron for social draft curation.
#
# Clones the auto_summarize_drafts.sh pattern. Each round picks ONE blog/course
# source that lacks an active social_posts row, inserts 2 pending rows
# (twitter + linkedin), runs an Opus 4.7 pass, and writes back the result.
#
# Schedule: 0 1 * * * (01:00 UTC = 06:30 IST) — see cron.d/auto_curate_social
# Lock:      /tmp/auto_curate_social.lock (flock -n, prevents overlapping runs)
# Log:       /var/log/auto_curate_social.log
# Token:     /root/.claude/oauth_token  (Max plan, expires 2027-04-26)

set -euo pipefail

OAUTH_TOKEN_FILE=/root/.claude/oauth_token
OAUTH_EXPIRES_FILE=/root/.claude/oauth_token.expires
ROADMAP_DIR=/srv/roadmap
TMPDIR=/tmp/auto-curate-social
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

# ---- Fetch rendered prompt template ({{TAG_MAP}} already substituted) --------
PROMPT_TEMPLATE_FILE="$TMPDIR/prompt_template.txt"
docker compose exec -T backend python -c \
    "from app.ai.social_curate import get_template; print(get_template())" \
    > "$PROMPT_TEMPLATE_FILE"

echo "$(date -Iseconds) INFO: starting social curation loop"

ROUND=0

# ---- Main loop — one source per Opus call -------------------------------------
while true; do
    ROUND=$(( ROUND + 1 ))
    EXPORT_FILE="$TMPDIR/export_${ROUND}.json"
    PROMPT_FILE="$TMPDIR/prompt_${ROUND}.txt"
    OUTPUT_FILE="$TMPDIR/output_${ROUND}.json"

    # Export ONE pending source, insert 2 pending social_posts rows atomically
    docker compose exec -T backend python -m scripts.export_social_sources \
        > "$EXPORT_FILE" 2>&1 || {
        echo "$(date -Iseconds) ERROR: export_social_sources failed in round $ROUND" >&2
        break
    }

    COUNT=$(python3 -c "
import json, sys
try:
    d = json.load(open('$EXPORT_FILE'))
    print(d.get('count', 0))
except Exception as e:
    print(0, file=sys.stderr)
    print(0)
" 2>/dev/null)

    if [ "${COUNT:-0}" -eq 0 ]; then
        echo "$(date -Iseconds) INFO: queue empty after $((ROUND - 1)) source(s), done"
        break
    fi

    # Capture pending row IDs from the export so the importer can target
    # the exact pair (avoids the "most recent pending pair" fallback,
    # which would race if a prior round stranded any rows).
    TWITTER_ID=$(python3 -c "
import json, sys
try:
    print(json.load(open('$EXPORT_FILE'))['source'].get('twitter_post_id', ''))
except Exception:
    print('')
")
    LINKEDIN_ID=$(python3 -c "
import json, sys
try:
    print(json.load(open('$EXPORT_FILE'))['source'].get('linkedin_post_id', ''))
except Exception:
    print('')
")

    # Build prompt: substitute {{SOURCE_JSON}} with the source dict.
    # python3 -c "..." (NOT a quoted heredoc) so bash expands $VARs.
    python3 -c "
import json
template = open('$PROMPT_TEMPLATE_FILE').read()
data = json.load(open('$EXPORT_FILE'))
source_json = json.dumps(data.get('source', {}), indent=2, ensure_ascii=False)
open('$PROMPT_FILE', 'w').write(template.replace('{{SOURCE_JSON}}', source_json))
"

    # Call Claude Opus 4.7
    CLAUDE_CODE_OAUTH_TOKEN="$(cat "$OAUTH_TOKEN_FILE")" \
        claude -p --model "$MODEL" < "$PROMPT_FILE" > "$OUTPUT_FILE" 2>&1 || {
        echo "$(date -Iseconds) WARNING: claude CLI failed in round $ROUND — incrementing retry_count" >&2
        docker compose exec -T backend python -m scripts.import_social_drafts \
            --invalid < "$EXPORT_FILE" || true
        rm -f "$EXPORT_FILE" "$PROMPT_FILE" "$OUTPUT_FILE"
        continue
    }

    # Validate JSON shape: must parse, must have keys twitter + linkedin
    python3 -c "
import json, sys
raw = open('$OUTPUT_FILE').read()
# Strip markdown code fences if present
import re
s = raw.strip()
s = re.sub(r'^[\x60]{1,3}(?:json)?\s*', '', s)
s = re.sub(r'\s*[\x60]{1,3}\s*$', '', s)
# Find first { to strip any prose preamble
idx = s.find('{')
if idx > 0:
    s = s[idx:]
try:
    d = json.loads(s)
except Exception as e:
    print(f'PARSE_FAIL: {e}', file=sys.stderr)
    sys.exit(1)
if 'twitter' not in d or 'linkedin' not in d:
    print('SHAPE_FAIL: missing twitter or linkedin key', file=sys.stderr)
    sys.exit(2)
# Write cleaned JSON back for importer
open('$OUTPUT_FILE', 'w').write(json.dumps(d))
" 2>/dev/null || {
        echo "$(date -Iseconds) WARNING: invalid JSON shape from Opus in round $ROUND — incrementing retry_count" >&2
        docker compose exec -T backend python -m scripts.import_social_drafts \
            --invalid < "$EXPORT_FILE" || true
        rm -f "$EXPORT_FILE" "$PROMPT_FILE" "$OUTPUT_FILE"
        continue
    }

    # Import: validate via Pydantic, update pending rows to draft (or archive on 3rd fail).
    # Pass the row IDs via CLI flags so the importer hits the exact pair we just
    # inserted, not "the most recent pending pair" (which would race).
    IMPORT_ARGS=""
    [ -n "$TWITTER_ID" ] && IMPORT_ARGS="--twitter-id $TWITTER_ID"
    [ -n "$LINKEDIN_ID" ] && IMPORT_ARGS="$IMPORT_ARGS --linkedin-id $LINKEDIN_ID"
    docker compose exec -T backend python -m scripts.import_social_drafts \
        $IMPORT_ARGS < "$OUTPUT_FILE" || {
        echo "$(date -Iseconds) WARNING: import_social_drafts failed in round $ROUND" >&2
    }

    echo "$(date -Iseconds) INFO: round $ROUND complete"
    rm -f "$EXPORT_FILE" "$PROMPT_FILE" "$OUTPUT_FILE"
done

echo "$(date -Iseconds) INFO: auto_curate_social.sh finished (${ROUND} round(s))"
