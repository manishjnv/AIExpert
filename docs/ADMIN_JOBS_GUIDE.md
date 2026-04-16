# Admin Guide — AI Jobs Module

> Quick-reference for daily job administration. Full technical details live in [JOBS.md §10](JOBS.md).

---

## Access

- **URL:** `/admin/jobs` (requires admin login)
- **Cron runs at:** 04:30 IST daily — new drafts appear after this
- **Best time to review:** 09:00–10:00 IST (after cron + summary generation)

---

## 1. Publishing a Job

### Prerequisites

Every job **must** have an Opus summary card before publishing. Flash extraction no longer generates summaries (Phase 14.5).

### Step-by-step

1. **Generate summaries** (run in Claude Code terminal before opening the queue):
   ```bash
   /summarize-jobs --status draft --limit 50
   ```
   Wait ~2 min for 50 jobs. This is **mandatory** — jobs without summaries show a degraded public page.

2. **Open `/admin/jobs`** and work through tabs in order:

#### A. Auto-skipped jobs (non-AI titles)
- Filter: `admin_notes` = "auto-skipped: non-AI title"
- These skipped AI enrichment entirely (Sales, HR, Legal titles)
- **Action:** Reject with `off_topic` (99% of cases)
- **False positive** (rare, e.g. "AI Sales Engineer"): click job → trigger enrichment → run `/summarize-jobs --id <ID>` → review → publish

#### B. Tier-2 lightweight jobs
- Filter: `admin_notes` = "tier2-lite"
- Sources: PhonePe, Groww, CRED, Mindtickle, Notion, Replit
- These have cheaper extraction — missing: nice_to_have, modules, summary
- **Action:** Review title/designation/location/skills → run `/summarize-jobs --id <ID>` if needed → publish or reject

#### C. Tier-1 full-enriched jobs (Anthropic, Scale, xAI, Cohere, etc.)
- These have complete enrichment from verified AI-native companies
- **Bulk Approve:** Use the "Bulk Publish Tier-1" button (max 100 per batch)
- **Spot-check:** Open 2–3 random jobs — verify summary card looks good, `tldr` is rewritten (not copy-pasted from JD)
- Any job missing summary → run `/summarize-jobs --id <ID>` first

#### D. Changed + Flagged jobs
- **Changed:** review the diff view (green=added, red=removed, amber=modified). Approve the diff, not the whole job.
- **Flagged:** enum violation or low-confidence extraction. Fix manually or reject.

3. **Verify before clicking Publish:**
   - [ ] Company is a real AI/ML employer (not staffing firm or course-seller)
   - [ ] Role is genuinely AI/ML (not "data analyst who uses Excel")
   - [ ] `posted_on` is within last 45 days
   - [ ] `designation` enum matches actual role
   - [ ] `location` is populated (country at minimum)
   - [ ] `tldr` reads naturally and is NOT copied from JD (duplicate content = SEO penalty)
   - [ ] `apply_url` resolves (use the "Test link" button)
   - [ ] `roadmap_modules_matched` has >= 1 module (else match-% won't work)
   - [ ] No PII / email / phone leaked in `description_html`

4. **Click Publish.** The system automatically:
   - Sets status to `published`
   - Stamps `last_reviewed_on` + `last_reviewed_by`
   - Increments source publish count
   - Pings IndexNow for SEO indexing

---

## 2. Reviewing / Rejecting a Job

### When to reject

| Reason | Use when |
|---|---|
| `fake` | Obvious scam, ghost job, unverifiable company |
| `expired` | JD says "closed" or `posted_on` > 45d and not refreshed |
| `off_topic` | Not AI/ML — devops, generic backend, sales, HR |
| `duplicate` | Already published via another source (same company + title) |
| `low_quality` | JD too vague, no skills listed, enum violations |

### How to reject

1. Open the job in the admin queue
2. Click **Reject**
3. Select the correct reason from the dropdown — **never skip the reason**

**Why reasons matter:** Every daily enrichment run feeds the last 45 days of rejection reasons back into the AI prompt. The extractor self-corrects based on your feedback. Bulk-rejecting without reasons breaks this feedback loop.

### Reviewing published jobs

- Published jobs can be found under the "Published" tab
- To **unpublish** a job that shouldn't be live: reject it with the appropriate reason — rejection removes it from public view
- There is no separate "unpublish" button; rejection is the mechanism

---

## 3. Removing / Expiring Jobs

### Automatic expiry (no admin action needed)

The system handles expiry automatically via three mechanisms:

| Trigger | How it works | Detection latency |
|---|---|---|
| **Role filled** (source removes listing) | Job missing from source feed for 2+ consecutive daily runs → status flipped to `expired`, reason = `source_removed` | <= 48 hours |
| **Date-based** (45-day limit) | `valid_through` date passes (set to `posted_on + 45 days`) → auto-expired in daily ingest | < 24 hours |
| **Source board down** | Liveness probe fails 3 consecutive times → entire source disabled (no per-job flip) | ~3 days |
| **Old expired posts** | Return HTTP 410 (Gone) after 90 days post-expiry | Immediate on request |

### Admin visibility for expired jobs

- **Expired tab** in `/admin/jobs` — shows all expired jobs
- **Sub-filter:** "Auto-expired (source removed)" vs "Date-based (45d)"
- **Banner chip:** `auto-expired 24h: N` shows how many flipped in the last run

### Manual removal scenarios

There is **no delete button** — jobs are never deleted from the database. Instead:

| Scenario | What to do |
|---|---|
| Published job should no longer be live | Reject it (reason: `expired` or appropriate reason) |
| Expired job re-appears on source | It will auto-draft on next ingest (new hash) — review normally |
| Company requests takedown | Reject the job + blocklist the company (see §4) |
| Source is permanently dead | Check probe status → if auto-disabled after 3 failures, leave it. If not, manually disable via source management |

### What NOT to do with expired jobs

- Don't manually edit `posted_on` to extend a job's life — it's the source's truth
- Don't re-publish an expired job without verifying it's still live on the source
- Don't worry about cleaning up the expired tab — old entries are harmless and provide historical data

---

## 4. Company Management

**URL:** `/admin/jobs/companies`

| Action | How |
|---|---|
| **Blocklist a company** | Click company → Blocklist → provide reason. All future jobs from this company are auto-rejected. |
| **Unblocklist** | Click company → Remove blocklist. New jobs will flow in on next ingest. |
| **Edit company details** | Update `slug`, `size`, `logo_url`, `verified` flag |
| **Upload logo** | Stored at `/static/companies/<slug>.png` (128x128 PNG) |

---

## 5. Source Management

**URL:** `/admin/jobs/sources` (also accessible from the Stats panel in `/admin/jobs`)

| Action | How |
|---|---|
| **Enable/Disable a source** | Toggle in the source list. Disabled sources skip during ingest. |
| **Check source health** | "Run Probe" button → HEAD-checks every board. Results show OK/failing/disabled counts. |
| **Review source quality** | Check the **Publish-rate 45d** column: Green >= 50%, Amber 20–50%, Red < 20%. Hover for top reject reasons. |
| **Toggle bulk-approve** | Tier-1 only. Allows the "Bulk Publish" button to include this source's jobs. |
| **On-demand ingest** | "Run Ingest" button triggers a full `run_daily_ingest()` outside the cron schedule. |

### Probe auto-disable

After 3 consecutive probe failures, a source is **automatically disabled**. It **re-enables automatically** on the first successful probe. Don't manually re-enable a probe-disabled source without first verifying the board URL is back up.

---

## 6. Batch Operations

### Batch publish session (backlog of 50+ drafts)

```bash
# 1. Generate all summaries
/summarize-jobs --status draft --limit 100

# 2. (Optional) dry-run preview
/summarize-jobs --dry-run --limit 5

# 3. Open /admin/jobs
#    → Bulk-approve Tier-1 verified
#    → Review Tier-2 individually
```

### On-demand ingest

If you need fresh jobs outside the 04:30 cron:
- Click "Run Ingest" in the admin UI, or
- SSH to VPS and run: `docker compose exec backend python scripts/daily_jobs_sync.py`

---

## 7. Monitoring & Cost

| What | Where |
|---|---|
| Per-source stats (24h + 45d) | `/admin/jobs` → Stats panel |
| AI usage & token costs | `/admin/ai-usage` |
| Monthly enrichment target | ~$0.22/month |
| Jobs ingested per source/run | Max 30 new per source |

---

## 8. Things You Must Never Do

1. **Publish without reading the JD** — even Tier-1 verified jobs can have extraction errors
2. **Approve Tier-2 without checking the company's own website** — aggregated sources are noisier
3. **Edit `posted_on`** — it's the source's truth, not ours
4. **Bulk-reject without picking reasons** — breaks the extractor feedback loop
5. **Manually re-enable a probe-disabled board** without verifying the URL is actually back
6. **Publish without a summary card** — run `/summarize-jobs` first
7. **Approve > 20 jobs in one click without spot-checking** — the UI asks for re-confirmation for a reason

---

## Quick Reference: admin_notes Cheat Sheet

| Value | What happened | What to do |
|---|---|---|
| `auto-skipped: non-AI title` | Title matched Sales/HR/Legal. No AI call made. | Reject `off_topic` (or trigger enrichment if false positive) |
| `tier2-lite: full enrichment on publish` | Cheaper extraction. Missing: nice_to_have, modules, summary. | Run `/summarize-jobs --id N` → review → publish |
| `enrichment failed: ...` | AI provider error. Minimal data only. | Check error → retry enrichment or fix manually |
| _(empty / null)_ | Full Tier-1 enrichment succeeded. | Verify summary exists → publish |
