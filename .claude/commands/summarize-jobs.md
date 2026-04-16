---
description: Generate Opus-quality data.summary for jobs over SSH using the Max plan
argument-hint: [--status draft|published|all] [--batch 10] [--limit N] [--id JOB_ID] [--dry-run]
---

# /summarize-jobs

Generate editorial-quality `data.summary` cards for jobs, running on the user's Claude Max quota (no API spend). Pipes JD batches over SSH from the VPS, you (Opus 4.6) produce the summaries, pipes back.

## How to run

Parse `$ARGUMENTS` for these flags (all optional):

- `--status draft|published|all` (default: `draft`)
- `--batch N` per-round size (default: `10`; do not exceed 12 — output-token cap)
- `--limit N` total cap across rounds (default: unlimited; loops until exporter returns 0)
- `--id JOB_ID` single-job mode (overrides all filters)
- `--dry-run` process one batch and stop — for tone preview before bulk run

## Procedure (do this in order — do not deviate)

1. Read the prompt template once:
   Bash: `ssh a11yos-vps "docker compose -f /srv/roadmap/docker-compose.yml exec -T backend cat /app/app/prompts/jobs_summary_claude.txt"`
   Keep the template text as `$PROMPT_TEMPLATE` for the session.

2. Main loop. For each round:

   a. **Export** a batch:
      ```
      ssh a11yos-vps "cd /srv/roadmap && docker compose exec -T backend python -m scripts.export_jobs_for_summary --batch 10 --status draft"
      ```
      Output is one JSON object: `{prompt_version, count, jobs: [{id, title, company, location, jd_text}, ...]}`.
      If `count == 0`: loop is done — report final totals and stop.

   b. **Generate summaries** yourself. Build the final prompt by substituting the `jobs` array as `{{JOBS_JSON}}` in `$PROMPT_TEMPLATE`. Produce the JSON array `[{id, summary}, ...]` as your internal reasoning (no tool call) — you are the Opus worker here, that's the whole point.
      - Enforce every length cap in SCHEMA. Better to drop a bullet than ship a too-long one.
      - Preserve every `id` from the export exactly. Caller matches by id.

   c. **Import** the summaries. Write your JSON array to a heredoc and pipe:
      ```
      ssh a11yos-vps "cd /srv/roadmap && docker compose exec -T backend python -m scripts.import_jobs_summary --model opus-4.6" <<'EOF'
      <paste-the-json-array-here>
      EOF
      ```
      Import prints stats on stderr + exits 0/1. Log `updated / rejected_empty / malformed / error` counts from the final stdout JSON.

   d. If `--dry-run`, stop after one round and report the 10 summaries' IDs + titles so the user can spot-check by opening `/admin/jobs` (preview link) or `/jobs/<slug>` for published.

   e. If `--limit` set and total `updated >= limit`, stop.

3. **Final report** (≤100 words):
   - batches run, total updated, total rejected/errors
   - any job IDs where validator rejected the summary (so the user knows which to investigate)
   - suggest next action: another round / inspect a specific row / commit checkpoint

## Safety + cost

- Each round costs ~(3K tokens input + 6K output) × Opus, against your Max quota. 460 jobs ≈ 46 rounds ≈ ~400K tokens. Comfortable on a 5x Max sub.
- If SSH export returns `count: 0` but `--id` was passed → the job already matches the current `prompt_version`. Not an error.
- If import returns high `malformed` rate → your output drifted; stop and report.
- Never `git push` or rebuild containers from this command. Data-plane only.

## Single-job usage

`/summarize-jobs --id 4711` — re-summarizes one specific row regardless of existing summary, stamps the current prompt_version.
