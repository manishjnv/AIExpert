# Handoff

> This file is rewritten at the end of every session. Read after CLAUDE.md.
>
> **Every session MUST start by reading [RCA.md](./RCA.md) end-to-end.** New entries get added after every bug fix or security change. Scan the most recent 5 entries and the "Patterns to watch for" table before writing any new code — they encode the real mistakes this codebase has made, and repeating them is the #1 way to introduce regressions.

## Current state as of 2026-04-16 (session 14f — Admin jobs queue + summary pipeline)

**Last worked on:** Admin jobs queue visibility + guardrails + summary-pipeline hardening.
**Branch:** master
**Commits:** `2dcff77` (queue row chips + quick-filters), `6115e60` (summary pipeline improvements)
**Live site:** https://automateedge.cloud
**Tests:** 218 passed, 0 new failures (61 pre-existing deselected).

### What shipped

**1. Queue row signals** ([admin_jobs.py](backend/app/routers/admin_jobs.py))

Every job row in `/admin/jobs` now shows at-a-glance signals that were previously buried inside the Details dropdown or invisible:

| Chip | When | Color |
|---|---|---|
| `T1` / `T2` | Always — derived from `Job.verified` | green / grey |
| `⚠ non-AI` | `admin_notes` starts with "auto-skipped" | red |
| `tier2-lite` | `admin_notes` starts with "tier2-lite" | amber |
| `enrich-failed` | AI provider errored during enrichment | red |
| `⚠ dup` | Another Job row has the same content hash | red |
| `⚠ no-summary` | `data.summary` is missing entirely | red |
| `vX.Y.Z` | Summary present — shows the prompt version stamp | grey |

New quick-filter toggles in the filter bar: **Tier-1 only**, **Non-AI (auto-skipped)**, **Tier-2 lite**, **Enrichment failed**, **Missing summary**.

**2. Publish guardrails**

- Single-row publish: confirm dialog if the draft has no Opus summary ("Public page will render degraded").
- Bulk-publish: warn banner counts how many of the selected rows are missing a summary before proceeding.

**3. Duplicate hash detection** (API)

`GET /admin/jobs/api/queue` now returns a `duplicate_hashes` array of content hashes that appear in 2+ Job rows. Frontend uses this to stamp the `⚠ dup` chip.

**4. Summary pipeline hardening** ([scripts/](scripts/))

- **Prompt versioning** — `CURRENT_PROMPT_VERSION` is no longer hardcoded in two places. Both `export_jobs_for_summary.py` and `import_jobs_summary.py` now parse the `PROMPT_VERSION:` line from the shared `jobs_summary_claude.txt` template. Bumping the version = one edit.
- **Duplicate propagation** — after a successful summary write, `import_jobs_summary.py` fans the same summary out to every Job sharing the same content hash. Verified end-to-end: 1 update → 4 propagations for a known dup-group.
- **Schema-violation tracking** — import now counts pre-clamp field-length violations (chip_label/resp_title/resp_detail/must_have/benefit/watch_out) and surfaces them in the stats line. Was previously silently clamped — now prompt drift is visible.
- **Export dedup** — within a single batch, only one job per unique content hash is emitted for Opus. Propagation fills in the siblings on import.

**5. Summary observability** — `/admin/jobs/api/summary-stats`

New panel in `/admin/jobs`:
- Coverage by status: total / with-summary / missing / % (color-coded green ≥95%, amber ≥70%, red <70%)
- Prompt-version distribution across every summarized row (catch stragglers on old versions)
- 7-day generation rate

**Current state from stats:** 175 drafts still missing summaries, 734 rows on pre-version Flash-era summaries (bumping the prompt will auto-surface them), 57 on the current version (from this session's `/summarize-jobs` runs).

### Files changed

- `backend/app/routers/admin_jobs.py` — +131 lines (chips, filters, summary-stats endpoint, JS)
- `scripts/import_jobs_summary.py` — +116 lines (dynamic version, violations, propagation)
- `scripts/export_jobs_for_summary.py` — +28 lines (dynamic version, batch dedup)

### Verified end-to-end

- Prompt version syncs across both scripts ✓
- Schema-violation detector fires on synthetic over-length content ✓
- Duplicate propagation: 1 update fanned out to 4 hash-siblings ✓
- Summary-stats query returns valid shape with coverage/versions/7d count ✓
- `no_summary` filter count matches stats-reported 175 ✓
- All admin endpoints return 401 (auth gated) ✓
- Backend logs clean after deploy ✓
- Test suite: 218 passed, 0 new failures ✓

### Next priorities

1. Rotate Gemini API key (leaked in prior session transcript)
2. Run another `/summarize-jobs --status draft --limit 100` to clear the remaining 175 drafts
3. Consider bumping `PROMPT_VERSION` in `jobs_summary_claude.txt` to force-regen the 734 stale Flash-era summaries
4. Admin to review + bulk-reject the ~1000 draft backlog using the new quick-filters
5. Submit `sitemap_index.xml` to Google Search Console
6. Set `INDEXNOW_KEY` in `.env`

---

## Prior state as of 2026-04-16 (session 14e — Jobs Admin Guide)

**Last worked on:** Added `/admin/jobs-guide` standalone admin reference page. Simplified with AUTO/YOU badges. Updated JOBS.md §10.9 for unpublish workflow.
**Commits:** `2e09f45`, `66c37a8`

---

## Prior state as of 2026-04-16 (session 14d — AI Usage dashboard + token tracking)

**Last worked on:** AI Usage admin dashboard overhaul — trimmed 15→8 widgets, fixed all-zero cost data, ensured every AI call logs tokens.
**Commits:** `e1790c7`, `e3bfbaa`, `d060b88`

---

## Prior state as of 2026-04-16 (session 14 — Jobs cost optimization)

**Last worked on:** Phase 14 cost optimizations for the jobs enrichment pipeline. Monthly cost: ~$2.80 → ~$0.22 (92% reduction).
