# Handoff

> This file is rewritten at the end of every session. Read after CLAUDE.md.
>
> **Every session MUST start by reading [RCA.md](./RCA.md) end-to-end.** New entries get added after every bug fix or security change. Scan the most recent 5 entries and the "Patterns to watch for" table before writing any new code — they encode the real mistakes this codebase has made, and repeating them is the #1 way to introduce regressions.

## Current state as of 2026-04-16 (session 14e — Jobs Admin Guide)

**Last worked on:** Added Jobs Admin Guide page at `/admin/jobs-guide` and updated JOBS.md §10.
**Branch:** master
**Commit:** `2e09f45`
**Live site:** https://automateedge.cloud
**Tests:** No test changes (static HTML page only).

### What shipped

**1. Jobs Admin Guide page** — `/admin/jobs-guide`

A standalone admin reference page covering the complete daily jobs workflow:

| Section | Content |
|---------|---------|
| 1. Publishing a Job | Step-by-step: generate summaries → triage auto-skipped/Tier-2/Tier-1 → publish checklist |
| 2. Reviewing & Rejecting | Reject reasons table, feedback loop explanation, how to unpublish |
| 3. Removing & Expiring | 4 auto-expiry mechanisms, manual removal scenarios, "never delete" rule |
| 4. Company Management | Blocklist/unblocklist, edit details, logo upload |
| 5. Source Management | Enable/disable, probes, quality signals, bulk-approve |
| 6. Batch Operations | Batch publish workflow, on-demand ingest |
| 7. Monitoring & Cost | Stats locations, admin_notes cheat sheet |
| 8. Never-Do list | 7 hard rules with styled danger callout |

- Styled with existing admin dark theme (ADMIN_CSS + guide-specific styles)
- Protected by `get_current_admin` (returns 401 for non-admins)
- Added to admin sub-nav in `nav.js`
- Added as quick action on admin dashboard

**2. JOBS.md §10 updates**

- Added new §10.9 "Unpublishing / removing a published job" — documents that rejection is the mechanism (no delete/unpublish button)
- Cross-reference to new standalone guide
- Fixed subsection numbering (10.10→10.14)

**3. Standalone markdown guide** — `docs/ADMIN_JOBS_GUIDE.md`

Same content as the web page in markdown format for offline/repo reference.

### Files changed

- `backend/app/routers/admin.py` — +242 lines (new route + HTML template)
- `frontend/nav.js` — +1 line (nav link)
- `docs/JOBS.md` — +20 lines (§10.9, numbering fix, cross-ref)
- `docs/ADMIN_JOBS_GUIDE.md` — new file (standalone markdown guide)

### Next priorities

1. Rotate Gemini API key (leaked in prior session transcript)
2. Run one daily ingest to verify token counts appear in dashboard
3. Admin to review + publish drafts at `/admin/jobs`
4. Submit `sitemap_index.xml` to Google Search Console
5. Set `INDEXNOW_KEY` in `.env`

---

## Prior state as of 2026-04-16 (session 14d — AI Usage dashboard + token tracking)

**Last worked on:** AI Usage admin dashboard overhaul — trimmed 15→8 widgets, fixed all-zero cost data, ensured every AI call logs tokens.
**Commits:** `e1790c7`, `e3bfbaa`, `d060b88`
**Tests:** 276 passed, 3 pre-existing failures, 0 new failures.

---

## Prior state as of 2026-04-16 (session 14c — Phase 14.6 + 14.7)

**Last worked on:** Completed all 7 Phase 14 cost optimizations.
**Tests:** 273 passed, 1 skipped, 0 failures.

---

## Prior state as of 2026-04-16 (session 14 — Jobs cost optimization)

**Last worked on:** Phase 14 cost optimizations for the jobs enrichment pipeline. Monthly cost: ~$2.80 → ~$0.22 (92% reduction).
