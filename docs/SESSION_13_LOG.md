# Session 13 — Jobs module quality, reliability, India expansion

**Date range:** 2026-04-15 → 2026-04-16
**Branch:** master (no feature branches)
**Outcome:** 8 commits on master, all live on VPS. Tests 189 → **210 passing** (+21). Zero regressions.
**Theme:** "Finish what session 12 started." Session 12 shipped the Jobs module end-to-end. Session 13 fixed the rough edges that only surfaced once real jobs started flowing — silent extraction noise, decaying slugs, mediocre summary quality, bad expiry logic, and an API-key leak in the logs.

---

## 1. What's new (by commit)

| # | Commit | Area | Summary |
|---|---|---|---|
| 1 | `cd82152` | Jobs / ingest | **Early auto-expiry** when an ATS listing disappears. `_auto_expire_missing()` tracks `data._meta.missing_streak` per published job; flips to `expired` at streak ≥ 2. One-day grace absorbs transient API blips. Source returning 0 rows treated as outage and skipped. |
| 2 | `bc3deb7` | Admin UI | **Expired sub-filter + auto-expired 24h banner chip.** `/admin/jobs` expired tab now filterable by `source_removed` vs `date_based`. Amber chip surfaces the last 24h flip count. |
| 3 | `252563c` | Jobs / filters | **City filter + `/api/jobs/locations` aggregation.** `city=` query param on both `/api/jobs` and `/admin/jobs/api/queue`. New locations endpoint returns `{countries, cities}` with counts from published jobs — powers the country dropdown + city datalist. |
| 4 | `5cd32f8` | Jobs / UX | **Admin job-preview link + scannable detail page.** Every admin row title is now a clickable `?preview=1` URL with amber banner + `noindex`. Public job pages got a highlights grid (role/seniority/experience/location/type/shift/salary), structured skills block, collapsible raw JD with improved CSS. |
| 5 | `7550c19` | Jobs / UX | **Rule-based JD de-fluffer.** New `app/services/jobs_readable.py` classifies sections by heading, drops `About us`/`EEO`/`Culture`, keeps `Responsibilities`/`Requirements`/`Nice-to-have`/`Benefits`, canonicalises variants, converts prose to sentence bullets. Falls through to raw JD when nothing usable. |
| 6 | `983da2b` → `cc32dcc` | Jobs / UX | **Headingless-JD path + bullet tightening.** For JDs with no section structure, sentence-level filler filter (25 patterns: `we are a`, `our mission`, `equal opportunity`, ...) + signal-match keep (action verbs, `N+ years`, `PhD`, tech names). Leading clauses stripped (`As part of our commitment`, `The successful candidate will`). Hard-cap 140 chars/bullet, 8 bullets max. |
| 7 | `5b3f310` | Jobs / enrichment | **LLM-generated `data.summary` card.** Extended the Gemini Flash schema: `headline_chips[]` with tone enum, `comp_snapshot` (or null), `responsibilities[]` as `{title, detail}`, `must_haves[]`, `benefits[]`, `watch_outs[]`. Render layer prefers `data.summary` (4-block color-coded card), falls back to rule-based de-fluffer, then raw JD. `scripts/backfill_jobs_summary.py` re-enriches existing rows. |
| 8 | `792d4df` | Jobs / sources | **India sources + Ashby ATS + slug probe + date-based auto-expire.** Greenhouse: PhonePe (126 jobs), Groww (30). Lever: CRED (6), Mindtickle (40). New Ashby module with 9 seed boards including **Sarvam AI** (India AI lab). New `jobs_sources/probe.py` runs pre-ingest, HEAD-checks every board in parallel, tracks `[fail_streak=N]` in `JobSource.last_run_error`, auto-disables after 3 consecutive fails. Bonus: `_auto_expire_past_valid_through()` flips published rows whose `valid_through` has elapsed. |
| 9 | `5abda91` | Jobs / summary quality | **Opus-via-Max worker pattern (improvement #1).** `backend/app/prompts/jobs_summary_claude.txt` (version-tagged, editorial rules), `scripts/export_jobs_for_summary.py` (selects jobs with missing or stale `prompt_version`), `scripts/import_jobs_summary.py` (stdin JSON, tolerant of code fences + leading prose, stamps `_meta{model, prompt_version, generated_at}`). Slash command `.claude/commands/summarize-jobs.md`. Provenance stamp preserved through `_validate_summary`. |
| 10 | `32c7511` | Jobs / bugfixes | **Module grounding (improvement #2) + API-key redaction (improvement #4).** `_get_module_slugs()` switched from the phantom `PlanVersion.status` column to `list_published()` template keys — restores `roadmap_modules_matched` population on every new enrichment. New `app/logging_redact.RedactingFilter` scrubs `?key=…`, `?api_key=…`, `Authorization: Bearer …` from every log record before formatting. Installed at backend startup + every script entrypoint. |
| 11 | `5d7ed0f` | Jobs / quality | **Rejection feedback loop (#5) + per-source publish-rate (#6).** Enrichment prompt now injects last-45-days reject reasons for the same source as a hint ("Past reviewers rejected N; top: off_topic(8)…"). `/admin/jobs/api/stats` returns `publish_rate_45d`, `published_45d`, `rejected_45d`, `top_reject_reasons_45d` per source; admin table shows color-coded chip (green ≥50% / amber 20-50% / red <20%). Side fix: `/api/stats` was shadowed by `/api/{job_id}` — constrained to `:int`. |

---

## 2. Tests delta

| File | Before | After | Tests added |
|---|---|---|---|
| `test_jobs_ingest.py` | 8 | 12 | +4 (auto-expire missing, streak reset, empty-source skip, other-status untouched) |
| `test_jobs_admin.py` | 8 | 10 | +2 (expired-reason sub-filter, publish-rate stats) |
| `test_jobs_public.py` | 8 | 11 | +3 (draft preview auth, highlights grid, city filter) |
| `test_jobs_readable.py` | 0 | 12 | new — section classification, heading canonicalisation, sentence bullets, headingless path, bullet caps, leading-strip |
| `test_jobs_sources.py` | 0 | 9 | new — India slug presence, Ashby normalization, isListed filter, probe streak/recovery/auto-disable, date-expiry flip, feedback loop, module grounding |
| `test_jobs_summary.py` | 0 | 11 | new — tone clamp, comp-snapshot null, all-sections render, HTML escape, meta stamp, bogus-meta drop, parser code-fences, parser leading-prose, parser items-envelope |
| `test_logging_redact.py` | 0 | 5 | new — query-param redaction, auth-header redaction, record-message scrub, %-args scrub |

**Totals:** 189 → 210 passing (+21), 1 skipped (aiosmtplib on Windows host), 0 failing.

---

## 3. Live VPS verification (final run)

| Check | Result |
|---|---|
| Source probe (25 boards) | **25/25 OK, 0 failures** |
| Module grounding returns templates | 4 published templates returned, zero warnings |
| Redaction filter on live `httpx.info` | `?key=AIzaSyLEAK-TEST-999` → `?key=[REDACTED]` |
| `/api/health` | 200 |
| `/jobs` | 200, 4 published jobs render |
| `/api/jobs?country=SG` / `?city=Bengaluru` | 1 each |
| `/api/jobs/locations` | 2 countries, 2 cities |
| `/api/jobs/<slug>/match` anon | 401 |
| `/admin/jobs` anon | 401 |
| `/jobs/<slug>?preview=1` anon | 404 (correct) |
| Sitemap index + jobs sitemap | 200 |
| `/admin/jobs/api/stats` | returns all 4 new fields on all 36 source rows |
| Total jobs in DB | 752 (748 draft + 4 published) |
| Any-summary coverage | 751/752 = 99.9% |
| Opus-stamped summaries | 2 (ids 95 + 148) as round-trip proof |
| Opus worker end-to-end | export → generate → import → verify render → stale-version detection ✅ |

---

## 4. Schema additions

### `data.summary` (nested in `Job.data`)

```jsonc
{
  "headline_chips": [{"label": "Senior leadership", "tone": "primary"}],
  "comp_snapshot": {"base": "$144-216K", "bonus": "25%", "equity": "RSUs", "total_est": "$180-270K+"} | null,
  "responsibilities": [{"title": "Salary band design", "detail": "frontline + corporate"}],
  "must_haves":   ["10+ years global comp experience", ...],
  "benefits":     ["100% employer-paid health", ...],
  "watch_outs":   ["No visa sponsorship", ...],          // 0-3
  "_meta": {                                              // present when Opus-imported
    "model": "opus-4.6",
    "prompt_version": "2026-04-16.1",
    "generated_at": "2026-04-16T00:47:05+00:00"
  }
}
```

### `data._meta` (top-level on `Job.data`)

```jsonc
{
  "missing_streak": 0,                 // inc'd when external_id absent from feed; reset on reappearance
  "expired_reason": "source_removed",  // or "date_based"
  "expired_on": "2026-04-16"
}
```

No schema migration needed — all lives inside existing `Job.data` JSON column.

---

## 5. Docs updated alongside

- `docs/JOBS.md` §7.6 — expiry handling now documents early-disappearance + date-based flip
- `docs/JOBS.md` §10 (admin guide) — see below (separate commit in this session wrap)
- `docs/TASKS.md` — Phase 13 entry (early-expiry detection, already closed in this session)
- This log

---

## 6. Handoff caveats

1. **Gemini API key leaked** earlier in the session transcript via an httpx INFO log (before the redaction filter was shipped). Filter now prevents future slips but the already-exposed key must be rotated.
2. **Only 4 published jobs of 752 drafts.** The admin review queue hasn't been worked through. Low priority unless you want traffic from the new sources.
3. **Summary quality:** 751 of 752 rows have a summary, but only 2 are Opus-grade; the rest are Flash. Use `/summarize-jobs` to upgrade the ones you want to publish.
4. **`PlanVersion.status` phantom** was a two-session bug (silently zero'd `roadmap_modules_matched`). Now fixed but historical data still has empty arrays.
