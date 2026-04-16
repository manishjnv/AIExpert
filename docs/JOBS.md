# AI Jobs Module — Design & Architecture

End-to-end spec for the AI Jobs board. Mirrors the blog module's file-backed + admin-gated shape. No auto-publish. SEO-first. Match-aware UX is the differentiator.

> **Before writing code:** read §1 (scope), §3 (schema), §7 (SEO), §10 (admin guide). Implementation tasks live in §12.

---

## 1. Scope & non-goals

**In scope**
- Daily scrape of allowlisted sources → AI enrich → admin review → publish.
- Public jobs board with filters, per-job SEO pages, sitemap, JobPosting JSON-LD.
- Match-% per logged-in user tied to curriculum modules + linked GitHub repos.
- Weekly email digest (opt-in).

**Out of scope (do not build)**
- In-platform apply flow (always outbound to company ATS).
- User-submitted company reviews.
- ML-based salary estimator.
- Resume upload / parsing.
- LinkedIn scraping (ToS-prohibited).

---

## 2. Module layout

```
backend/app/
├── models/job.py                    # Job, JobSource ORM
├── routers/
│   ├── jobs.py                      # public: /api/jobs, /jobs/*
│   └── admin_jobs.py                # admin: /admin/jobs/*
├── services/
│   ├── jobs_ingest.py               # orchestrator: fetch → extract → enrich → stage
│   ├── jobs_sources/
│   │   ├── greenhouse.py            # one module per source type
│   │   ├── lever.py
│   │   ├── yc.py
│   │   └── rss.py
│   ├── jobs_enrich.py               # Gemini Flash enrichment
│   ├── jobs_match.py                # match % per user
│   ├── jobs_seo.py                  # slugs, JSON-LD, sitemap
│   └── jobs_digest.py               # weekly email
├── ai/prompts/jobs_extract.txt      # enrichment prompt (enum-locked)
└── templates/jobs/                  # Jinja SSR pages for SEO

scripts/
└── daily-jobs-sync.py               # cron entrypoint (04:30 IST)

docs/
└── JOBS.md                          # this file
```

---

## 3. Data model

### 3.1 `jobs` table

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `external_id` | str | Source-scoped unique ID (e.g. `greenhouse:anthropic:4567890`) |
| `source` | str | `greenhouse` / `lever` / `yc` / `rss:<slug>` |
| `source_url` | str | Canonical ATS URL (where apply button points) |
| `hash` | str | SHA256 of `title + company + location + JD`; drives change detection |
| `status` | enum | `draft` / `published` / `rejected` / `expired` |
| `posted_on` | date | **Original** publish date from source (never scrape date) |
| `valid_through` | date | `posted_on + 45d` default; admin-editable |
| `scraped_on` | datetime | `_meta` only |
| `last_reviewed_on` | date | Stamped on publish |
| `last_reviewed_by` | str | Admin name |
| `reject_reason` | enum? | `fake` / `expired` / `off_topic` / `duplicate` / `low_quality` |
| `data` | JSON | Full enriched payload (see §3.2) |
| `created_at`, `updated_at` | datetime | |

Indexes: `(status, posted_on DESC)`, `(source, external_id)` unique, `hash`.

### 3.2 `data` JSON payload

```json
{
  "slug": "senior-ml-engineer-at-anthropic-a7f3",
  "title_raw": "Senior ML Engineer, Alignment",
  "designation": "ML Engineer",
  "seniority": "Senior",
  "topic": ["LLM", "Safety"],
  "company": {
    "name": "Anthropic",
    "slug": "anthropic",
    "size": "Lab",
    "logo_url": "/static/companies/anthropic.png",
    "verified": true
  },
  "location": {
    "country": "US",
    "country_name": "United States",
    "city": "San Francisco",
    "remote_policy": "Hybrid",
    "regions_allowed": ["US", "CA"]
  },
  "employment": {
    "job_type": "Full-time",
    "shift": "Day",
    "experience_years": { "min": 5, "max": 8 },
    "salary": { "min": 250000, "max": 380000, "currency": "USD", "disclosed": true }
  },
  "description_html": "<p>…</p>",
  "tldr": "Research-adjacent ML role focused on RLHF pipelines; requires prod-grade PyTorch + distributed training.",
  "must_have_skills": ["PyTorch", "Distributed training", "RLHF"],
  "nice_to_have_skills": ["JAX", "Interpretability"],
  "roadmap_modules_matched": ["llm-fundamentals", "mlops-production", "rl-basics"],
  "apply_url": "https://boards.greenhouse.io/anthropic/jobs/4567890",
  "seo": {
    "title": "Senior ML Engineer at Anthropic — San Francisco (Hybrid) | AutomateEdge Jobs",
    "description": "Research-adjacent ML role focused on RLHF pipelines…",
    "canonical": "/jobs/senior-ml-engineer-at-anthropic-a7f3"
  }
}
```

**Enum-locked fields** (extractor MUST return one of these; off-list → flagged for admin):

- `designation`: `ML Engineer | Research Scientist | Applied Scientist | Data Scientist | Data Engineer | MLOps Engineer | AI Product Manager | AI Engineer | Prompt Engineer | Research Engineer | Computer Vision Engineer | NLP Engineer | AI Solutions Architect | AI Developer Advocate | Other`
- `seniority`: `Intern | Junior | Mid | Senior | Staff | Principal | Lead | Manager | Director`
- `topic` (multi): `LLM | CV | NLP | RL | MLOps | Data Eng | Research | Applied ML | GenAI | Robotics | Safety | Agents | RAG | Fine-tuning | Evals`
- `remote_policy`: `Remote | Hybrid | Onsite`
- `job_type`: `Full-time | Part-time | Contract | Internship`
- `shift`: `Day | Night | Flexible | Unknown` (expect ~80% `Unknown`)
- `company.size`: `Startup | Scale-up | BigTech | Lab | Enterprise | Unknown`

---

## 4. Ingestion pipeline

```
  ┌─────────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
  │ Source fetch│ →  │ Normalize│ →  │ Dedupe   │ →  │ AI enrich│ →  │ Stage as │
  │ (per source)│    │ to schema│    │ by hash  │    │ (Gemini) │    │ draft    │
  └─────────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
```

**Cron:** `scripts/daily-jobs-sync.py` runs 04:30 IST daily via the same Docker cron container that runs quarterly-sync.

**Dedup logic:** compute `hash`. If exists → skip (no enrichment call, saves cost). If exists but `source` differs → add to `also_on[]` on existing job (cross-posting detection).

**Change detection:** same `external_id` but different `hash` → mark `status=draft` again, admin sees a diff view (§10).

**Cost control:** enrichment = 1 Gemini Flash call per *new* job. Target ≤ 200 new jobs/day = ~$0.01/day.

**Failure isolation:** one source failing never blocks others. Log + continue. Daily stats email to admin.

---

## 5. Sources (allowlist)

| Tier | Source | Method | Companies |
|---|---|---|---|
| 1 — Verified | Greenhouse boards | `boards-api.greenhouse.io/v1/boards/<slug>/jobs` | Anthropic, Scale, Hugging Face, Cohere, Databricks, Perplexity, Runway, Character, Anyscale, Weights & Biases |
| 1 — Verified | Lever boards | `api.lever.co/v0/postings/<slug>` | Mistral, Pika, Eleven Labs, Luma |
| 1 — Verified | Direct RSS | per company | OpenAI (ATS JSON), Google DeepMind, Meta AI |
| 2 — Aggregated | YC Work at a Startup | RSS | YC AI/ML-tagged roles |
| 2 — Aggregated | AI Jobs List (opensource) | daily CSV | long tail |

Tier 1 jobs get `verified: true` badge. Tier 2 requires admin review before publish (no bulk-approve).

**Do not scrape:** LinkedIn, Indeed, Glassdoor, Wellfound. ToS risk outweighs value.

---

## 6. AI enrichment

### 6.1 Model strategy (Phase 14 cost-optimized)

Three-tier model pipeline minimizes cost while maximizing quality on published jobs:

| Tier | Model | When | Cost/job |
|------|-------|------|----------|
| **Pre-filter** | Rule-based (no model) | Non-AI titles (Sales, Legal, HR, etc.) | $0 |
| **Tier-2 lite** | Gemini 2.5 Flash | Non-AI-native boards (PhonePe, Notion, etc.) | ~$0.00008 |
| **Tier-1 full** | Gemini 2.5 Flash | AI-native boards (Anthropic, Scale, xAI, etc.) | ~$0.00012 |
| **Summary (publish)** | Claude Opus via Max | Admin publishes → `/summarize-jobs` | $0 (subscription) |

### 6.2 Prompt architecture

Prompts split into **static system instruction** (cached by Gemini across calls) and **dynamic user prompt** (job-specific data):

| File | Purpose | Tokens |
|------|---------|--------|
| `prompts/jobs_extract_system.txt` | Schema + rules (Tier-1 full) | ~800 |
| `prompts/jobs_extract.txt` | Job data template (Tier-1 full) | ~200 + JD |
| `prompts/jobs_extract_lite_system.txt` | Reduced schema (Tier-2 lite) | ~500 |
| `prompts/jobs_extract_lite.txt` | Job data template (Tier-2 lite) | ~100 + JD |

**JD caps:** Full enrichment = 4000 chars. Lite enrichment = 2000 chars. Median JD after HTML strip is ~3500 chars.

### 6.3 Pre-filter (Phase 14.2)

`is_non_ai_title()` in `jobs_ingest.py` matches against 40+ non-AI title patterns. Matched titles are staged with `admin_notes = "auto-skipped: non-AI title"` and no AI call. Admin can override from the queue.

### 6.4 Tier-2 sources (Phase 14.3)

`TIER2_SOURCES` in `jobs_ingest.py`: `phonepe`, `groww`, `cred`, `mindtickle`, `notion`, `replit`. These use `enrich_job_lite()` — produces only designation, seniority, topic, location, employment, tldr, must_have_skills. No nice_to_have, no roadmap_modules, no description_html rewrite, no summary. Full enrichment deferred to publish.

### 6.5 Enrichment flow

```
title pre-filter? ──yes──→ stage with minimal payload, admin_notes="auto-skipped"
        │no
        ▼
tier-2 source? ──yes──→ enrich_job_lite() → stage with admin_notes="tier2-lite"
        │no
        ▼
enrich_job() (full) → stage as draft
```

**Caching:** keyed on `hash`. Never re-enriched unless hash changes.
**Sanitization:** strip email/phone/tracking pixels from `description_html` before storage.

**Prompt rules enforced:**
- `tldr` is 2 lines max, **rewritten** not paraphrased (duplicate content SEO).
- All enum fields return one of the allowed values or `Unknown`.
- `roadmap_modules_matched` returns only slugs that exist in current `PlanTemplate` module inventory (pass inventory in prompt).
- No hallucinated salaries — `disclosed: false` if not in JD.
- `summary` removed from Flash prompt — comes exclusively from Opus via Max on publish.

### 6.6 Cost summary

| Metric | Before (Phase 13) | After (Phase 14) |
|--------|-------------------|-------------------|
| Model | Flash for everything | Flash (extraction) + Opus (summary on publish) |
| JD cap | 6000 chars | 4000 (full) / 2000 (lite) |
| Prompt caching | None | systemInstruction cached (~40% input savings) |
| Pre-filter | None | ~40% fewer calls on mixed boards |
| Tier-2 deferral | None | ~60% fewer tokens for Tier-2 |
| Summary | Flash (every job) | Opus on publish only ($0 via Max) |
| **Monthly cost** | **~$2.80** | **~$0.22** |

---

## 7. SEO architecture

### 7.1 URL structure

| Pattern | Example | Purpose |
|---|---|---|
| `/jobs` | `/jobs` | Hub, latest 50 |
| `/jobs/<designation-slug>` | `/jobs/ml-engineer` | Designation hub |
| `/jobs/<designation-slug>/remote` | `/jobs/ml-engineer/remote` | Designation + remote |
| `/jobs/<designation-slug>/<country>/<city>` | `/jobs/ml-engineer/in/bengaluru` | Geo hub |
| `/jobs/company/<slug>` | `/jobs/company/anthropic` | Company page |
| `/jobs/topic/<slug>` | `/jobs/topic/llm` | Topic page |
| `/jobs/<job-slug>` | `/jobs/senior-ml-engineer-at-anthropic-a7f3` | Individual job |

All other combos served via `/jobs?filter=…` with `<meta name="robots" content="noindex">`.

### 7.2 Per-job page requirements

- Server-rendered HTML (Jinja), not JS hydration.
- `<title>`, `<meta description>`, canonical, OG, Twitter — same pattern as blog.
- **JobPosting JSON-LD** (non-negotiable — this is what lands you in Google Jobs):

```json
{
  "@context": "https://schema.org/",
  "@type": "JobPosting",
  "title": "…",
  "description": "<HTML>",
  "datePosted": "2026-04-10",
  "validThrough": "2026-05-25",
  "employmentType": "FULL_TIME",
  "hiringOrganization": { "@type": "Organization", "name": "Anthropic", "sameAs": "https://anthropic.com" },
  "jobLocation": { "@type": "Place", "address": { "@type": "PostalAddress", "addressLocality": "San Francisco", "addressCountry": "US" } },
  "applicantLocationRequirements": { "@type": "Country", "name": "United States" },
  "baseSalary": { "@type": "MonetaryAmount", "currency": "USD", "value": { "@type": "QuantitativeValue", "minValue": 250000, "maxValue": 380000, "unitText": "YEAR" } },
  "directApply": false
}
```

- Breadcrumb JSON-LD on every page.
- Apply button: `rel="nofollow sponsored"`.

### 7.3 Hub page content

- Unique H1 per hub.
- 80–120 word AI-generated intro, cached as static HTML, regenerated weekly.
- FAQ JSON-LD ("How much does an ML Engineer earn in Bengaluru?" — aggregated from own data).
- Salary/skills stats block (original content).

### 7.4 Sitemaps

`sitemap_index.xml` at root includes:
- `sitemap-jobs.xml` — every `published` job, `<lastmod>` = `updated_at`, `<priority>` = 0.8.
- `sitemap-job-hubs.xml` — designation/geo/topic/company hubs, priority 0.6.
- Regenerated on every publish + nightly.

### 7.5 Ping & robots

- `robots.txt`: `Allow: /jobs/`, `Disallow: /jobs/*?*`.
- On publish: POST to IndexNow (Bing + Yandex).
- Google Search Console: submit `sitemap-jobs.xml` manually once.

### 7.6 Expiry handling

- **Date-based:** `posted_on + 45d` (or admin-set `valid_through`) → `status=expired`.
- **Early disappearance:** during daily ingest, any `published` job whose `external_id` is absent from the source feed increments `data._meta.missing_streak`. At `missing_streak >= 2` the job auto-flips to `status=expired` with `data._meta.expired_reason = "source_removed"`. Guard: a source that returned 0 rows is treated as an outage and skipped, preventing mass-expire on API blips. Lives in `backend/app/services/jobs_ingest.py::_auto_expire_missing`.
- Expired jobs: `noindex` header + page renders "This job has closed" + related-jobs block. Kept resolvable 90d (preserves backlinks).
- After 90d: return 410 Gone; removed from sitemap.

---

## 8. Filter UX

**Groups (collapsible sidebar):**

1. **Time** — posted in last 24h / 7d / 30d · custom date range.
2. **Role** — designation (multi) · topic (multi) · seniority (multi) · experience years (slider).
3. **Location** — remote policy · country · city · regions allowed (for remote).
4. **Company** — company (typeahead) · company size.
5. **Employment** — job type · shift · salary disclosed toggle.

**Above results:**
- Search box (full-text over `title + company + skills`).
- Sort: Newest · Best match · Salary (high→low) · Posted date.
- Active filter chips with one-click removal.

**Zero-results state:** suggests the single filter to remove with "This filter excludes 94% of jobs".

**Save search:** logged-in users only → stores filter JSON → feeds weekly digest.

**URL reflects state** (canonical paths where possible, else querystring with `noindex`).

---

## 9. Match-% feature

The platform's real differentiator vs. a generic job board.

**Inputs:**
- Completed modules (from `UserPlan` progress).
- Linked GitHub repos + their evaluation scores (reuse `app/services/evaluate.py`).
- User's `experience_level` (from onboarding).

**Algorithm (v1, deterministic — no ML):**

```
match_score = 0.5 * modules_overlap  +  0.3 * skills_overlap  +  0.2 * level_fit

modules_overlap = |user_completed_modules ∩ job.roadmap_modules_matched| / |job.roadmap_modules_matched|
skills_overlap  = |user_skills_from_repos ∩ job.must_have_skills|       / |job.must_have_skills|
level_fit       = 1 if user_level in job.experience_years range else 0.3
```

Computed on-demand (cached 1h per `(user_id, job_id)`).

**UI:**
- Colored ring on card: green ≥ 70, amber 40–69, grey < 40.
- Expandable "Why this match" line + missing-skills list.
- **"Close the gap" CTA** — links to specific modules that would raise the score. Jobs → learning loop.

**Anonymous users:** no ring shown. CTA on jobs hub: "Sign in to see your match %".

---

## 10. Admin guide

> This section is the operational manual for whoever reviews jobs daily. Keep it bookmarked.

### 10.1 Daily workflow — step by step (10–15 min/day)

#### Step 1: Generate summaries for the queue (before reviewing)

Open Claude Code terminal and run:

```bash
/summarize-jobs --status draft --limit 50
```

This generates Opus-quality summary cards for up to 50 draft jobs. Flash no longer produces summaries (Phase 14.5), so **every job needs this step before publishing**. Wait for it to finish (~2 min for 50 jobs).

#### Step 2: Open the admin queue

Go to `/admin/jobs` around 09:00 IST (after the 04:30 cron).
Top banner shows: `X new drafts · Y changed · Z flagged`.

#### Step 3: Handle pre-filtered jobs first

Filter by `admin_notes` containing **"auto-skipped"**. These are non-AI titles (Sales, HR, Legal, etc.) that skipped enrichment to save cost.

- **If genuinely non-AI** → Reject with reason `off_topic`. Done.
- **If actually AI** (rare false positive, e.g. "AI Sales Engineer") → click the job → trigger full enrichment from the queue → then run `/summarize-jobs --id <JOB_ID>` → review and publish.

#### Step 4: Handle Tier-2 lightweight jobs

Filter by `admin_notes` containing **"tier2-lite"**. These are from PhonePe, Groww, CRED, Mindtickle, Notion, Replit — they got cheaper extraction (no nice_to_have, no modules, no summary).

For each job worth publishing:
1. Click → review title, designation, location, tldr, skills.
2. If it looks good, run: `/summarize-jobs --id <JOB_ID>` (if not already done in Step 1).
3. Verify the summary card rendered on Preview.
4. Publish.

For junk → Reject with reason (`off_topic`, `low_quality`, etc.).

#### Step 5: Review Tier-1 full-enriched jobs

These are from AI-native companies (Anthropic, Scale, xAI, Cohere, etc.) with complete enrichment.

- **Bulk Approve** Tier-1 Verified batch if nothing looks off.
- Spot-check 2–3 random jobs: does the summary card look good? Is `tldr` rewritten (not copied)?
- Any job missing summary → run `/summarize-jobs --id <JOB_ID>` before publishing.

#### Step 6: Handle changed + flagged jobs

- **Changed** → diff view, approve the diff (not the whole job).
- **Flagged** (enum violation or low-confidence extraction) → manual fix or reject.

#### Step 7: Clear queue

All jobs processed. Done.

#### Quick-reference: admin_notes cheat sheet

| `admin_notes` value | What happened | What to do |
|---|---|---|
| `auto-skipped: non-AI title` | Title matched Sales/HR/Legal/etc. No AI call made. | Reject `off_topic` (most cases) or trigger enrichment if false positive |
| `tier2-lite: full enrichment on publish` | Cheaper extraction from Tier-2 board. Missing: nice_to_have, modules, summary. | Run `/summarize-jobs --id N` → review → publish |
| `enrichment failed: ...` | AI provider returned an error. Minimal data only. | Check error message. Retry enrichment or fix manually. |
| _(empty / null)_ | Full Tier-1 enrichment succeeded. | Verify summary exists; run `/summarize-jobs --id N` if missing → publish |

#### One-liner: batch publish session

If you have a backlog of 50+ drafts to clear:

```bash
# Step 1: Generate all summaries
/summarize-jobs --status draft --limit 100

# Step 2: Dry-run preview (optional)
/summarize-jobs --dry-run --limit 5

# Step 3: Open /admin/jobs, bulk-approve Tier-1, review Tier-2 individually
```

### 10.2 Review checklist — approve only if ALL true

- [ ] Company is a real AI/ML-adjacent employer (not a reseller, staffing firm, or course-seller).
- [ ] Role is genuinely AI/ML (not "data analyst who uses Excel").
- [ ] `posted_on` is within last 45 days.
- [ ] `designation` enum matches the actual role (not "ML Engineer" for a devops-only job).
- [ ] `location` block is populated (country at minimum).
- [ ] `tldr` reads like a human wrote it and is NOT copied from JD (duplicate content SEO penalty).
- [ ] `apply_url` resolves (one-click "Test link" button).
- [ ] `roadmap_modules_matched` contains ≥ 1 module (else match-% won't work).
- [ ] No PII / email / phone leaked in `description_html`.

### 10.3 Reject reasons — pick the right one (feeds the extractor)

| Reason | Use when |
|---|---|
| `fake` | Obvious scam, ghost job, unverifiable company |
| `expired` | JD says "closed" or `posted_on` > 45d and not refreshed |
| `off_topic` | Not AI/ML (devops, generic backend, sales) |
| `duplicate` | Already published via another source with same company+title |
| `low_quality` | JD too vague, no skills listed, enum violations |

### 10.4 Diff-view actions (changed jobs)

- Green = added, red = removed, amber = modified.
- Approve diff → new `hash` stored, `last_reviewed_on` bumped.
- Reject diff → keeps previous published version live.

### 10.5 Company management

`/admin/jobs/companies` — one row per company ever seen.
- Edit `slug`, `size`, `logo_url`, `verified` flag.
- Blocklist a company (auto-rejects all future jobs from it).
- Upload logo (stored in `/static/companies/<slug>.png`, 128×128 PNG).

### 10.6 Source management

`/admin/jobs/sources` — one row per source.
- Toggle enabled/disabled.
- Per-source stats: scraped today, published, rejected, rejection rate (high rate = source deteriorating).
- **Publish-rate 45d** column: `published / (published + rejected)` over the last 45 days. Green ≥50%, amber 20–50%, red <20%. Hover shows top reject reasons with counts.
- Bulk-approve toggle (Tier-1 only).
- **On-demand probe:** `POST /admin/jobs/api/sources/probe` HEAD-checks every configured board slug. Sources failing 3 consecutive probes auto-disable.

### 10.7 Preview before publish

Every row in the admin queue has a clickable title + `Preview ↗` button. Opens `/jobs/<slug>?preview=1` in a new tab. Preview is admin-only (non-admins and anon see 404), carries `noindex`, and shows an amber `"⚠ ADMIN PREVIEW · status=draft"` banner.

### 10.8 Summary cards

Published jobs render a **structured summary card** (headline chips, compensation snapshot, "What you'll own", "Must-haves", "Benefits highlights", "Watch-outs") above the collapsible raw JD.

**Summary is Opus-only (Phase 14.5).** Flash extraction no longer generates summary. All summaries come from Claude Opus via the Max subscription at $0 marginal cost.

**Before publishing any job**, run the summary generator:

```bash
/summarize-jobs --id <JOB_ID>         # single job
/summarize-jobs --status draft --limit 50  # batch before publish session
/summarize-jobs --dry-run --limit 5   # preview 5, then inspect at /admin/jobs
```

Each summary carries `_meta.prompt_version`; when the prompt is bumped, `scripts/export_jobs_for_summary.py` auto-surfaces stale rows in the next `/summarize-jobs` run.

**If summary is missing on a published job:** the page renders the tldr + skills as a fallback. No summary card appears. Run `/summarize-jobs --id N` to fix.

### 10.9 Expiry mechanisms

Three auto-expire triggers protect public UX without admin action:

| Trigger | How detected | Latency | `_meta.expired_reason` |
|---|---|---|---|
| Role filled (ATS removes listing) | `missing_streak ≥ 2` in daily ingest | ≤ 48h | `source_removed` |
| Posting past `posted_on + 45d` | `valid_through < today` in daily ingest | < 24h | `date_based` |
| Source board entirely down | `probe.py` auto-disables after 3 fails | 3 days | (source disabled, no job-level flip) |
| Old expired posts | HTTP 410 after 90 days | 90d | — |

**Admin visibility:** Expired tab has a sub-filter "Auto-expired (source removed)" vs "Date-based (45d)". Banner shows `auto-expired 24h: N` chip when any flip occurred in the last run.

### 10.10 Rejection feedback loop

Rejections aren't wasted. Every daily enrichment run injects the last 45 days of reject_reason counts from the same source into the prompt: *"Past reviewers rejected 12 of the last batch. Top reasons: off_topic(8), low_quality(4)."* The extractor adapts without manual prompt tuning.

**How to maximise this:** always pick the correct reject reason (never "other" unless truly unclassifiable). The feedback loop only fires if `reject_reason IS NOT NULL` in the last 45 days for that source.

### 10.11 Escalation

- Source returns 0 jobs 2 days running → auto-expire logic does not fire for that source (treated as outage, not mass-fill). Admin should investigate if a board was replaced.
- **Probe auto-disable** after 3 consecutive failures (see §10.6).
- Any single admin action that affects > 20 jobs requires re-confirmation.

### 10.12 Never do

- Publish a job you haven't read the JD for.
- Approve a Tier-2 job without checking the company's own website.
- Edit `posted_on` (it's the source's truth, not ours).
- Bulk-reject without picking reasons (breaks the extractor feedback loop).
- Manually disable a board the probe auto-disabled without first verifying the slug is truly dead (the probe re-enables it automatically on first OK).

### 10.13 Cost optimization — background (Phase 14)

Five automatic optimizations reduced monthly enrichment cost from ~$2.80 to ~$0.22 (92%). Admin doesn't configure anything — the pipeline applies them silently. The daily workflow in **§10.1** already incorporates all the steps you need; this section is background context only.

| Optimization | What it does | Admin-visible effect |
|---|---|---|
| **Pre-filter non-AI titles** | Sales/HR/Legal/Finance titles skip AI entirely | `admin_notes = "auto-skipped: non-AI title"` — see §10.1 Step 3 |
| **Tier-2 lightweight enrichment** | PhonePe, Groww, CRED, Mindtickle, Notion, Replit get cheaper extraction | `admin_notes = "tier2-lite"` — see §10.1 Step 4 |
| **No Flash summary** | Summary removed from Flash prompt; Opus-only on publish | Must run `/summarize-jobs` before publishing — see §10.1 Step 1 |
| **JD cap 4000 chars** | Input capped at 4000 chars (was 6000); Tier-2 at 2000 | No admin impact (95th percentile JD is under 4000) |
| **Prompt caching** | Static schema cached via Gemini `systemInstruction` | No admin impact (transparent) |

**Monthly cost target:** ~$0.22/mo. Monitor at `/admin/ai-usage`.

---

## 11. Email digest

- **Opt-in only** on `/account` ("Email me matching jobs weekly").
- **Sent Monday 09:00 IST.** Reuse Brevo SMTP.
- **Content:** top 5 jobs by match-% for that user, posted in last 7d, not already in their "dismissed" list.
- **Unsubscribe link** — single-click, no login (signed token).
- **Body is static HTML**, built from same Jinja partials as the jobs cards.

---

## 12. Implementation phases

Task-level detail lives in [TASKS.md](TASKS.md) Phase 7. Summary:

| Step | Deliverable | Acceptance |
|---|---|---|
| 1 | Model + migration + this doc | `jobs` table created, tests pass |
| 2 | Greenhouse source + ingest orchestrator | Fetches Anthropic board, stages drafts |
| 3 | AI enrichment (Gemini Flash) + prompt | 10 test JDs → valid enum output |
| 4 | Admin UI: queue, review, approve, reject, diff | Admin can clear a 50-job queue in < 10 min |
| 5 | Public list + per-job SSR + JSON-LD | Google Rich Results test passes |
| 6 | Filter UI + URL state | All filter groups work client-side |
| 7 | Match-% + "Close the gap" | Logged-in user sees ring + missing skills |
| 8 | Lever + YC sources | Sources isolated; one failing doesn't break others |
| 9 | Sitemap + IndexNow + robots | `sitemap-jobs.xml` live, pinged on publish |
| 10 | Weekly digest | Opt-in user gets Monday email with 5 matches |
| 11 | Company/source admin pages | Blocklist + logo upload working |
| 12 | Analytics + admin stats strip | Per-source scraped/published/rejected visible |

---

## 13. Security notes

- Ingest runs server-side only; never trust source HTML into the DOM without sanitization (bleach allowlist on `description_html`).
- Apply-URL must be validated as `https://` + domain allowlist (known ATS hosts) before storing.
- Admin endpoints behind existing admin-JWT dependency.
- No user input reaches the extraction prompt — only scraped JD content.
- Rate-limit `/api/jobs` at 60 req/min/IP to prevent scraping (enforce via slowapi).
- `sitemap-jobs.xml` is cached 1h; don't regenerate on every publish in prod — queue it.

---

## 14. Open decisions to confirm before coding

1. **Match algorithm v1 deterministic vs. embeddings?** → Recommend deterministic (§9). Revisit at 500+ published jobs.
2. **Company logos — host ourselves or hotlink?** → Host ourselves (`/static/companies/`). Hotlinking breaks + referrer leaks.
3. **Location geocoding API?** → Use free Natural Earth country list + city lookup from a static JSON; no live geocoder.
4. **Dedup across companies that rebrand?** → Out of scope for v1.
5. **Salary currency conversion for filtering?** → v1 filters by disclosed-salary-yes/no only; no conversion.

---

**Last updated:** 2026-04-14
**Owner:** Manish Kumar
**Next doc to read:** [TASKS.md](TASKS.md) Phase 7 (to be added).
