# Handoff

> This file is rewritten at the end of every session. Read after CLAUDE.md.
>
> **Every session MUST start by reading [RCA.md](./RCA.md) end-to-end.** New entries get added after every bug fix or security change. Scan the most recent 5 entries and the "Patterns to watch for" table before writing any new code — they encode the real mistakes this codebase has made, and repeating them is the #1 way to introduce regressions.

## Current state as of 2026-04-16 (session 14f — Admin jobs queue + summary pipeline + key rotation)

**Branch:** `master` (HEAD: `e76a662`)
**Live site:** [automateedge.cloud](https://automateedge.cloud)
**VPS:** SSH alias `a11yos-vps` (72.61.227.64). Deploy root: `/srv/roadmap/`.
**Tests:** 218 passed, 0 new failures (61 pre-existing deselected with `-k 'not test_jobs_match and not test_jobs_cost_opt'`).

### Session 14f commits (in order)

| Commit | Scope | One-liner |
|---|---|---|
| `2dcff77` | `backend/app/routers/admin_jobs.py` | Row chips for T1/T2, non-AI, tier2-lite, enrich-failed, dup; quick-filter toggles |
| `6115e60` | `admin_jobs.py`, `scripts/import_jobs_summary.py`, `scripts/export_jobs_for_summary.py` | Summary pipeline hardening: visibility, guardrails, dedup, version-sync, observability |
| `798a27f` | `CLAUDE.md`, `docs/HANDOFF.md` | Session-close docs |
| `e76a662` | `docs/RCA.md`, `docs/OPERATIONS.md`, `docs/HANDOFF.md` | RCA-023 + §6.1 key rotation procedure |

---

## What shipped

### 1. Admin queue row signals

Previously buried inside the Details dropdown, now surfaced as colored chips on every row in `/admin/jobs`.

| Chip | Source of truth | Color | Meaning |
|---|---|---|---|
| `T1` | `Job.verified == 1` | green | Tier-1 verified AI-native company |
| `T2` | `Job.verified == 0` | grey | Tier-2 aggregated source |
| `⚠ non-AI` | `admin_notes LIKE "auto-skipped%"` | red | Title matched non-AI allowlist. Typically reject `off_topic`. |
| `tier2-lite` | `admin_notes LIKE "tier2-lite%"` | amber | Lightweight extraction. Run `/summarize-jobs --id N` before publish. |
| `enrich-failed` | `admin_notes LIKE "enrichment failed%"` | red | AI errored. Retry or reject `low_quality`. |
| `⚠ dup` | Content hash appears in 2+ Job rows | red | Candidate for reject `duplicate`. |
| `⚠ no-summary` | `data.summary` is missing | red | Public page will render degraded. Run `/summarize-jobs --id N`. |
| `vX.Y.Z` | `summary._meta.prompt_version` | grey | Stamp so version-bump regen is visible. |

New quick-filter toggles under the filter bar. Click to apply, click again to clear:
`Tier-1 only`, `⚠ Non-AI (auto-skipped)`, `Tier-2 lite`, `Enrichment failed`, `⚠ Missing summary`.

### 2. Publish guardrails

- **Single publish** ([admin_jobs.py `pub()`](backend/app/routers/admin_jobs.py)): confirm dialog if draft has no summary. Suggests `/summarize-jobs --id N`.
- **Bulk publish** ([admin_jobs.py `bulkPub()`](backend/app/routers/admin_jobs.py)): counts how many of the selected rows are missing summaries; warning included in confirm prompt.
- **API-level Tier-1 enforcement** already existed — bulk-publish rejects non-Tier-1 jobs server-side.

### 3. Duplicate detection

- `GET /admin/jobs/api/queue` now returns `duplicate_hashes: [...]` — any content hash appearing in 2+ rows.
- Query is cheap (`hash` is indexed); uses the already-loaded batch to scope the IN clause.
- Known dup group: `6b7496b2...` → jobs `666, 671, 672, 682, 689` (all "Solution Sales Executive" @ moveworks, non-AI, should all be rejected).

### 4. Summary pipeline improvements ([`scripts/`](scripts/))

#### Prompt version is now a single source of truth

Both `export_jobs_for_summary.py` and `import_jobs_summary.py` parse the `PROMPT_VERSION: <value>` line from the shared template at `backend/app/prompts/jobs_summary_claude.txt`. Bumping the version = **one edit**, no code change.

Candidate paths (covers both Docker and local dev):
```python
_PROMPT_CANDIDATES = [
    Path(__file__).resolve().parent.parent / "app" / "prompts" / "jobs_summary_claude.txt",          # Docker
    Path(__file__).resolve().parent.parent / "backend" / "app" / "prompts" / "jobs_summary_claude.txt",  # local
]
```

Verified: `CURRENT_PROMPT_VERSION` in both scripts returns `2026-04-16.1`.

#### Duplicate propagation on import

After a successful summary write, `_propagate_to_siblings(job_id, content_hash, clamped)` finds every Job row sharing the hash and copies the same summary. Skips siblings already on the current prompt version.

Verified end-to-end: test import targeted job `666` → stats reported `"updated": 1, "propagated_to_duplicates": 4` → direct DB inspection confirmed all 5 siblings `(666, 671, 672, 682, 689)` had identical summaries and matching `v2026-04-16.1` stamp.

#### Export batch-level dedup

If multiple jobs in the same batch share a content hash, only the first is emitted for Opus. Propagation on import fills in the siblings.

#### Schema-violation tracking

`import_jobs_summary.py._schema_violations()` pre-clamp counter reports how often Opus exceeds documented caps:

| Field | Cap |
|---|---|
| chip_label | 24 |
| resp_title | 48 |
| resp_detail | 90 |
| must_have | 100 |
| benefit | 110 |
| watch_out | 110 |

Clipping was already happening silently in `_validate_summary()`; now the counter surfaces drift. Stats line example: `{"updated": 10, "schema_violations": {"chip_label": 3}, "prompt_version": "2026-04-16.1"}`.

### 5. Summary observability — `/admin/jobs/api/summary-stats`

New panel in `/admin/jobs`: **"Summary-card pipeline (coverage · versions · 7d rate)"**. Returns:

```json
{
  "coverage": [
    {"status": "draft", "total": 962, "with_summary": 787, "missing": 175, "coverage_pct": 82},
    {"status": "published", "total": 5, "with_summary": 4, "missing": 1, "coverage_pct": 80},
    ...
  ],
  "versions": [
    {"version": "unknown", "count": 734},
    {"version": "2026-04-16.1", "count": 57}
  ],
  "generated_last_7d": 57
}
```

Color coding: green ≥ 95%, amber ≥ 70%, red < 70%.

### 6. Gemini key rotation (post-session op)

Old key leaked in a prior chat transcript. Rotated in-session:

1. User created replacement key in AI Studio (new format `AQ.Ab...`, not classic `AIzaSy...`)
2. `ssh a11yos-vps "cp /srv/roadmap/.env /srv/roadmap/.env.bak-$(date +%s)"`
3. `sed -i 's|^GEMINI_API_KEY=.*|GEMINI_API_KEY=<new>|' /srv/roadmap/.env`
4. `docker compose up -d --force-recreate backend` (plain `restart` does NOT reload env — see RCA-002)
5. Smoke test via `app.ai.provider.complete(prompt=..., json_response=True)` → `gemini-2.5-flash` returned valid JSON ✓
6. Log scan for 401/403: clean ✓
7. User revoked old key in AI Studio ✓ (operator action only — backend can't do this)

Incident + procedure codified:
- [RCA-023](RCA.md) — full incident write-up with 3 prevention rules
- [OPERATIONS.md §6.1](OPERATIONS.md) — 8-step rotation checklist, applies to any provider key

Google Gemini keys can now start with either `AIzaSy...` (classic, 39 chars) OR `AQ.Ab...` (newer format, variable length). Both formats accepted by the backend.

---

## Verification commands (run these first in next session)

```bash
# 1. Confirm HEAD matches
ssh a11yos-vps "cd /srv/roadmap && git log -1 --oneline"
# Expected: e76a662 docs(ops): document Gemini key rotation procedure (RCA-023)

# 2. Confirm backend up + Gemini auth works
ssh a11yos-vps "docker compose -f /srv/roadmap/docker-compose.yml exec -T backend python -c '
import asyncio
from app.ai.provider import complete
async def main():
    r, m = await complete(prompt=\"Return JSON {\\\"ok\\\":true}\", json_response=True, task=\"handoff_check\")
    print(f\"SUCCESS {m}: {r}\")
asyncio.run(main())'"
# Expected: SUCCESS gemini-2.5-flash: {'ok': True}

# 3. Confirm summary-stats endpoint
ssh a11yos-vps "docker compose -f /srv/roadmap/docker-compose.yml exec -T backend python -c '
import asyncio, json
from app.db import init_db, close_db
import app.db as _db
from sqlalchemy import select, func
from app.models import Job
async def m():
    await init_db()
    async with _db.async_session_factory() as s:
        summary_expr = func.json_extract(Job.data, \"\$.summary.headline_chips\")
        total = (await s.execute(select(func.count(Job.id)).where(Job.status==\"draft\"))).scalar()
        missing = (await s.execute(select(func.count(Job.id)).where(Job.status==\"draft\", summary_expr.is_(None)))).scalar()
        print(f\"drafts={total} missing_summary={missing}\")
    await close_db()
asyncio.run(m())'"
# Expected: drafts=962 missing_summary=175 (or slightly shifted if cron ran overnight)
```

---

## Known production state (snapshot end of 14f)

| Metric | Value | Notes |
|---|---|---|
| Total draft jobs | 962 | Grown over last 14 sessions of ingest |
| Drafts with summary | 787 | 82% coverage |
| Drafts missing summary | **175** | Primary backlog for next `/summarize-jobs` run |
| Published jobs | 5 | 4 with summary, 1 missing |
| Rejected jobs | 1 | Orphan — ok to ignore |
| Summaries on current version `2026-04-16.1` | 57 | From this session's manual runs + propagation |
| Summaries on `unknown` (pre-version) | 734 | Flash-era, no `_meta.prompt_version`. Bumping PROMPT_VERSION will auto-surface them on next run. |
| Known hash-dup group | 5 jobs | `666, 671, 672, 682, 689` — all fake dupes, safe to bulk reject |

---

## Next priorities (in rough order)

### Immediate

1. **Run `/summarize-jobs --status draft --limit 100`** — clears the 175 missing-summary drafts in ~5 rounds. After this, coverage for drafts reaches ~100%.
2. **Admin bulk-rejects the non-AI drafts** using the new `⚠ Non-AI (auto-skipped)` quick-filter. The filter narrows the queue and the rows are already chip-tagged; reject each with `off_topic`. One click per reject, maybe 5–10 min for the ~100 auto-skipped rows.
3. **Reject the known dup group** `666, 671, 672, 682, 689` with reason `duplicate` — they're all hash-identical copies of the Moveworks Solution Sales Executive role, all non-AI anyway.

### Near-term

4. **Consider bumping `PROMPT_VERSION`** in [jobs_summary_claude.txt](backend/app/prompts/jobs_summary_claude.txt). This will auto-surface the 734 Flash-era summaries for regeneration. Only do this if you want them re-worked with the current prompt style. Cost: ~74 Opus batches over your Max quota, roughly 15 min of runtime.
5. **Delete the `.env.bak-*` backup** on VPS once the new Gemini key has been stable for a day: `ssh a11yos-vps "ls /srv/roadmap/.env.bak-* && rm /srv/roadmap/.env.bak-<timestamp>"`
6. **Submit `sitemap_index.xml` to Google Search Console** — admin action only, I can't do this.
7. **Set `INDEXNOW_KEY` in `.env`** — we have IndexNow pinging logic wired in [admin_jobs.py](backend/app/routers/admin_jobs.py) and [jobs.py](backend/app/routers/jobs.py) but the key is still unset, so pings are no-ops. Get one at https://www.indexnow.org/documentation.

### Future (no deadline)

8. Add schema-violation telemetry to `/admin/ai-usage` so prompt drift shows up in the dashboard, not just script stdout.
9. Revisit `_validate_summary()` in `jobs_enrich.py` — its caps (32, 64, 120, 130, 140) are more generous than the documented prompt caps (24, 48, 90, 100, 110). Reconcile.
10. Add per-provider key redaction for the new `AQ.Ab...` format in `logging_redact.py` — current patterns likely only catch `AIzaSy`.

---

## Gotchas discovered this session

1. **Gemini key format expanded.** Google now issues both `AIzaSy...` (classic) and `AQ.Ab...` (newer). My initial pushback was wrong — don't repeat. See RCA-023.
2. **`docker compose restart` does NOT reload `.env`.** Must use `docker compose up -d --force-recreate backend`. See RCA-002 (cookie incident) — same underlying Docker quirk.
3. **Provider `complete()` signature** is `(prompt, *, json_response, task, subtask, db, system_instruction)` — no `max_tokens`, no `providers` list. Returns `(response, model_name)` tuple. See [provider.py:85](backend/app/ai/provider.py#L85).
4. **Standalone scripts need `init_db()` + `close_db()`** explicitly — `async_session_factory` is None until init runs. See the smoke-test command pattern above.
5. **SSH heredocs with single quotes in JSON fail.** The shell misinterprets `'` inside the heredoc. Workaround: write JSON to a local temp file, then `ssh ... < temp.json` via stdin.
6. **915/919 are NOT hash-siblings** despite identical titles. Slight JD differences produce different hashes. The `⚠ dup` chip won't fire. Admin will need to manually notice.
7. **Prompt cache file location differs local vs Docker:** use candidate-list pattern to find it robustly.

---

## Prior sessions (abbreviated)

- **14e (2026-04-16):** `/admin/jobs-guide` page with AUTO/YOU badges. JOBS.md §10.9 unpublish workflow. Commits `2e09f45`, `66c37a8`.
- **14d (2026-04-16):** AI Usage dashboard overhaul (15→8 widgets). Token tracking fix across all AI call sites (RCA-022). Commits `e1790c7`, `e3bfbaa`, `d060b88`.
- **14c (2026-04-16):** Phase 14.6 + 14.7 cost optimizations (module-match backfill, JD-hash dedup cache).
- **14 (2026-04-16):** Phase 14 jobs enrichment cost cuts: ~$2.80 → ~$0.22/month (92% reduction).
