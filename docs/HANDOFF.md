# Handoff

> This file is rewritten at the end of every session. Read after CLAUDE.md.
>
> **Every session MUST start by reading [RCA.md](./RCA.md) end-to-end.** New entries get added after every bug fix or security change. Scan the most recent 5 entries and the "Patterns to watch for" table before writing any new code — they encode the real mistakes this codebase has made, and repeating them is the #1 way to introduce regressions.

## Current state as of 2026-04-24 (session 39 — SEO-21 first pillar post + template wire-up)

**Branch:** `master` · One commit sitting local on top of session 38's `5c81c21` (which is live on VPS).
**Live site:** [automateedge.cloud](https://automateedge.cloud) — at commit `5c81c21`; session 39 not yet deployed.
**Tests:** 65 blog tests pass (blog-adjacent slice only; full suite not re-run, changes are additive).

### Session 39 — first pillar post + SEO-21 template closure

**Deliverable:** the first pillar blog post in the SEO-21 cluster — `/blog/ai-engineer-vs-ml-engineer`, targeting q6 ("AI engineer vs ML engineer"), the most beatable SERP per [docs/SEO.md §5.1](./SEO.md#51). Authored as `docs/blog/03-ai-engineer-vs-ml-engineer.json`; still an authoring archive — publish is a manual admin action via `/admin/blog` once deployed.

**Post stats (validator: `ok=True, 0 errors`):**

| Gate | Required | Actual |
|---|---|---|
| Word count | ≥3000 | **3134** |
| First non-lede paragraph | 40–60 words | **50** |
| H2 sections | 8–12 | **10** |
| Internal links | ≥40 | **46** (all 12 AI/ML track-section pages + /jobs + /blog/01-02 + /vs/ai-engineer-vs-ml-engineer + /roadmap + /) |
| Trusted citations | ≥5 | **7** (Stanford AI Index, BLS, arXiv, Hugging Face, OpenAI platform docs, PyTorch, Papers with Code) |
| FAQs | 8–15 | **10** (drawn from PAA) |
| Comparison table | ≥1 | **1** — seven-dimension side-by-side |
| Schemas | Article + FAQPage + one of {HowTo, DefinedTerm, VideoObject, ItemList} | **Article + FAQPage + DefinedTerm** (4 defined terms) |

Two remaining validator warnings (non-blocking): 8 paragraphs >4 sentences, 10 sentences >30 words. Both are editorial judgment calls in an information-dense pillar; optional split pass can land with session 40 if zero-warning compliance becomes a priority.

**Template infrastructure that shipped in the same commit (plugs SEO-21 foundation gaps):**

- [backend/app/templates/blog/post.html](../backend/app/templates/blog/post.html) — adds `FAQPage` + `DefinedTermSet` JSON-LD `<script>` blocks, emitted conditionally when `payload.faqs` / `payload.defined_terms` are present. Without this, the pillar validator's schema *declaration* was a claim with no actual emission — Google would see Article + BreadcrumbList only, and the rich-result assertion would fail.
- [backend/app/routers/blog.py:443](../backend/app/routers/blog.py#L443) — `_render_post` signature extended with `faqs` and `defined_terms` kwargs, threaded from the published-post payload.
- [backend/app/services/blog_publisher.py:87](../backend/app/services/blog_publisher.py#L87) — `_ALLOWED_TAGS` gains `table/thead/tbody/tr/th/td`. Pillar posts with `comparative: true` require a `<table>`; pre-fix every such post threw a non-standard-tag warning. Browser-native tags, zero XSS risk under admin-controlled `body_html`.

**Render verification:** rendered the template with the session-39 payload and confirmed all four JSON-LD blocks parse as valid JSON: `Article` + `BreadcrumbList` + `FAQPage` (10 Question entities) + `DefinedTermSet` (4 DefinedTerm entities).

**Session 38 deploy status (correction landed in CLAUDE.md §9):** both session-38 commits (`b491ca7` + `5c81c21`) are live on VPS and have been since shortly after they were pushed. Routes `/roadmap` (ItemList), `/roadmap/ai-engineer/skills`, `/roadmap/generalist/career-path` all return 200 with expected schema. The earlier §9 note claiming "NOT yet deployed" was stale and was corrected in this session.

**Deploy + publish (pending user decision):**

```bash
# VPS (after pushing the session-39 commit)
ssh a11yos-vps "cd /srv/roadmap && git pull && docker compose up -d --build --force-recreate backend"
```

Template + router + validator changes all need the rebuild. Frontend files are volume-mounted and would not normally require `--build`, but backend changes do — use the full command.

Once deployed, the pillar post goes live via the admin publish flow:

1. Open `/admin/blog`.
2. Paste the contents of `docs/blog/03-ai-engineer-vs-ml-engineer.json` into the draft editor.
3. Save draft → review → publish. IndexNow ping fires automatically on publish (SEO-07 wiring).

Until the admin publish step runs, `/blog/03-ai-engineer-vs-ml-engineer` will 404 even after the backend deploy — this is intentional: no auto-publish from repo files.

**Next session (40):** second pillar post `/blog/learn-ai-without-cs-degree-2026` (q7). Schema stack: Article + FAQPage + HowTo (Review still blocked on ≥5 real testimonials per SEO-23).

---

## Current state as of 2026-04-17 (session 23 — roadmap week-row collapse UX)

**Branch:** `master` (frontend commit this session on top of session 21's `2dece31`; session 22 was data-plane only)
**Live site:** [automateedge.cloud](https://automateedge.cloud)
**VPS:** SSH alias `a11yos-vps` (72.61.227.64). Deploy root: `/srv/roadmap/`. Backend healthy.
**Tests:** **432 passed** (no backend test changes this session — frontend UX only).

### Session 23 — Roadmap week-row collapse UX (frontend)

**Scope:** UX tweak on the public roadmap page. User reported that every week row rendered open by default (noisy wall of text) and the per-row toggle was a bare grey glyph users didn't recognize as a control.

**Changes — all in [frontend/index.html](../frontend/index.html):**

1. **Collapse all weeks by default** — [line 904](../frontend/index.html#L904) simplified from `const collapsedByDefault = isComplete && wTotal > 0;` to `const collapsedByDefault = true;`. Rendered DOM now omits the `open` attribute on `<details>` for every week, so a whole month is scannable at a glance; users click to expand the row they want.
2. **Toggle redesigned as an obvious control** — [lines 191-220](../frontend/index.html#L191-L220). Old: bare `▾` glyph, `color: var(--ink-soft)`, 14px, no border, no hover. New: bordered pill, mono-caps `EXPAND` / `COLLAPSE` label, chevron on `::after`, hover/focus flip border + text to `var(--accent)`.
3. **Chevron-only rotation** — [line 191](../frontend/index.html#L191). The old rule `.wk-toggle { transform: rotate(180deg); }` would flip the whole pill (including the new text) upside-down when the row opens. Rotated only the `::after` pseudo-element instead.
4. **Mobile affordance** — `@media (max-width: 480px)` hides the text labels and keeps the chevron+border pill, so the toggle still reads as a button on phones without stealing the title's horizontal space.
5. **Markup** — [line 950](../frontend/index.html#L950) wraps `.label-closed` / `.label-open` spans inside `.wk-toggle`. CSS swaps which is visible based on `[open]` state.

**Rule-8 guarantee preserved:** frontend still runs standalone when opened from disk (pure CSS + inline JS edits, no new deps, no new files).

**Deploy:** frontend is volume-mounted in `docker-compose.yml` (`./frontend:/usr/share/nginx/html:ro`), so `ssh a11yos-vps "cd /srv/roadmap && git pull"` is sufficient — no `--build`, no `--force-recreate`. Nginx serves the updated file immediately.

**Verification plan post-deploy:** load `https://automateedge.cloud/`, scroll to Month 1, confirm every week row is collapsed; hover the EXPAND pill (border + text turn orange); click to open; the chevron rotates and the label flips to COLLAPSE. Repeat at viewport ≤480px and confirm only the chevron remains. Completed weeks (if any exist in saved state) still render the green ✓ badge and still default collapsed.

### Session 21 — admin Bulk-Reject in Jobs Review queue

**Scope:** feature add. User-reported gap: the queue had "Bulk publish selected (Tier-1 only)" but no bulk-reject. Added a mirrored action so admins can clear low-quality drafts in one click with a shared reason.

**Design decisions:**

- **No tier gate on reject** (unlike bulk-publish). Publish gates to Tier-1 + `bulk_approve=1` sources because a bad approval creates a public URL. Rejection is safe to allow everywhere — the whole point is to clear noise fast.
- **Shared reason per batch**, not per row. The UI prompts once, applies the same reason to every selected id. Matches how reviewers actually triage noisy sources ("all of these are `off_topic`"); a per-row flow would defeat the purpose.
- **Same cap as bulk-publish** (100 ids per call). Consistency with the existing limit and the `docs/JOBS.md §10.7` note.
- **No IndexNow ping.** Publish pings IndexNow because a new public URL appeared. Reject changes no public URLs.
- **Two-step confirm** (reason prompt → count confirm) — mis-click protection on an irreversible-feeling action. The count echo (`Reject N jobs as "off_topic"?`) is specifically to catch "wrong tab selected" errors.

**Files changed (1 feature file + 1 test):**

- [backend/app/routers/admin_jobs.py](../backend/app/routers/admin_jobs.py)
  - Line 8 — docstring updated (bulk-reject added to action list)
  - Lines 365-395 — new `POST /api/bulk-reject` endpoint (mirrors `bulk_publish` structure)
  - Line 1252 — "Bulk reject selected" button next to existing bulk-publish button
  - Lines 1308-1322 — `bulkRej()` JS function (reason prompt + count confirm + fetch)
- [backend/tests/test_jobs_admin.py](../backend/tests/test_jobs_admin.py)
  - Line 1 — module docstring updated
  - Lines 137-166 — new `test_bulk_reject_accepts_any_tier_and_records_reason` covering the three primary paths (invalid reason 400, empty ids 400, mixed-tier success 200 + DB state verification)

**Not touched:** no prompt changes, no migration, no nginx config change (route is under the already-allowlisted `/admin/jobs/api/` prefix).

**Deploy:** pending. Per memory `feedback_deploy_rebuild.md`:

```bash
ssh a11yos-vps "cd /srv/roadmap && git pull && docker compose up -d --build --force-recreate backend"
```

Plain `restart` won't pick up the code change.

**Verification plan post-deploy:** load `/admin/jobs`, select a handful of tier-2 drafts, hit "Bulk reject selected", pick `off_topic` in the prompt, confirm. Confirm rows disappear from the draft tab and appear under the Rejected tab with the right reason. Also verify the existing single-row reject still works.

### Session 22 — editorial summary refresh chunk 4 (Claude Max)

**Scope:** data-plane only (parallel to session 21's admin bulk-reject code work). No repo files modified except this HANDOFF + CLAUDE.md §9. No git-level deploy required.

**What ran:** 7 rounds of `/summarize-jobs --status draft --batch 10 --model sonnet-4.6` against `prompt_version 2026-04-16.2`. Same operator flow as session 20. **70 rows imported, 0 malformed, 0 rejected, 0 retries.**

**Target & outcome:** +70 net draft-pool `sonnet-4.6` stamps. Result: **+70 net exactly** (151 → 221). Draft pool now:

| model / prompt_version | count | Δ vs session 20 start | Δ vs session 22 start |
|---|---:|---:|---:|
| null (no summary) | 298 | — | −57 |
| sonnet-4.6 @ 2026-04-16.2 (current) | 221 | +140 cumulative | **+70** |
| opus-4.6 @ 2026-04-16.2 (current) | 79 | — | −1 (sibling propagation) |
| opus-4.6 @ 2026-04-16.1 (stale) | 55 | — | −13 |
| test-propagation | 5 | — | 0 |

**Generator-side validator caught 1 chip-label cap pre-flight:** "dbt + Airflow + Snowflake" (R3, 25 chars) — trimmed to "dbt + Snowflake". **0 post-import schema violations** reported by the `_validate_summary` clamp.

**IDs stamped this session:**

- R1 (692, 646, 516, 505, 322, 118, 57, 47, 45, 693) — PhonePe HR + SRE, Together AI Commerce Eng, 3× Scale AI (DevOps Pub Sec, Head Finance Systems, Dir Enterprise ML), Cerebras Compute Platform Architect, 3× Anthropic (CSM Tokyo, Community Mktg, Inst Comms)
- R2 (663, 661, 653, 651, 491, 480, 429, 428, 427, 417) — 4× Together AI ($160-275K band: Partnerships Mgr, Dir DC Ops, CSE GPU, Staff DW), 2× Anthropic (MM AE Industries, Intl Readiness), 4× Figure NASDAQ:FIGR (Head BD Figure Open, 2× CSA Reno+Charlotte, Staff PM Stablecoin)
- R3 (381, 374, 371, 364, 358, 356, 172, 167, 61, 35) — 6× Together AI (Sr Network Eng Amsterdam, EA, Dir Tax, Sr TPM, Sr BE Commerce, Staff Analytics Eng), 4× Anthropic (Network Eng Capacity, Mgr Sales Dev, CSM Higher Ed, Capital Markets & IR)
- R4 (10, 697, 465, 776, 451, 945, 779, 778, 766, 754) — Anthropic AE Pub Sec Sydney (**clearance required**), PhonePe PM Growth + Mgr PR, 3× Anthropic (Staff Infra Pre-training, IT Sys Eng, Cyber Harms PM), Mistral AI DevRel Singapore (**50% APAC travel**), 3× Anthropic (Research Lead Training Insights, Cyber Threat Investigator $230-290K, ML Eng Safeguards $350-500K)
- R5 (489, 472, 160, 155, 106, 101, 99, 97, 96, 89) — all Anthropic: RE Agents + RE Virtual Collab ($500-850K each), CBRN-E Threat Investigator (**explicit content exposure**), SWE Account Abuse $320-405K, S&O Biz Partner, RE Societal Impacts (**SF-only + residency option**), Security Architect Applied AI NYC, RE Performance RL $350-850K, RS Frontier Red Team Emerging Risks $320-850K (**SF-only**), Safeguards Analyst Human Exploitation (**disturbing content + on-call**)
- R6 (82, 77, 74, 71, 62, 51, 36, 29, 966, 821) — 7× Anthropic (RE Post-Training $350-500K, Dir Tech Acctg M&A, Dev Education Lead, Design Eng Education Labs, CSM Industries NYC, Contracts Mgr Pub Sec, Cert Dev Lead), Anthropic Bio Safety RS $300-320K, **Mindtickle Sr Graphic Designer (location blank — flagged)**, Scale AI Lead TPM Trust & Safety
- R7 (786, 493, 94, 93, 42, 13, 790, 789, 788, 783) — all Anthropic: Strategic Deals Lead Compute, Partner Sales Mgr SI, IT Support Eng, Head Programmatic Outcomes Partners, Commercial Counsel EMEA Dublin €165-210K (**3 days in-office**), AE Startups, **Industry Principal Insurance (20+ yrs required)**, TPM Infra, Prompt Eng Claude Code $300-405K, TPM Marketing Technology

**Anomalies flagged in watch_outs:** Sydney AE security-clearance required; Mistral Singapore 50% APAC travel + multilingual (KR/JP/CN) preferred; 3 Anthropic roles with explicit/disturbing content exposure (CBRN-E Inv, Cyber Threat Inv, Safeguards HE&A); 2 SF-exclusive Anthropic roles with relocation required (RE Societal Impacts, RS Frontier Red Team); Python-only interview format for RE Post-Training; Dublin Commercial Counsel 3-days-in-office (above 25% baseline); Insurance Industry Principal 20+ yrs + 8 yrs exec (unusually senior bar); Mindtickle location field blank.

**No new operator gotchas** beyond session 20's four. Artifact prefix `s21_*` used on disk (session 21 by operator naming; this doc entry is session 22).

### Session 20 — editorial summary refresh chunk 3 (Claude Max)

**Scope:** data-plane only. No repo files modified (this HANDOFF + CLAUDE.md §9 the sole exceptions). No git-level deploy required.

**What ran:** 7 rounds of `/summarize-jobs --status draft --batch 10` using the VPS export/import scripts, generated JSON stamped `--model sonnet-4.6` against `prompt_version 2026-04-16.2`. Summaries authored by this Opus session (Max plan, $0 API spend) via the standard skill flow: `export_jobs_for_summary → generate → import_jobs_summary`.

**Target & outcome:** User target was **+69 net** draft-pool `sonnet-4.6` stamps. Result: **+70 net** (81→151). 70 rows processed, 0 retries, 0 malformed outputs, 0 post-import schema violations.

**Export-filter premise verified.** The session-kickoff hypothesis — that `scripts.export_jobs_for_summary` was re-serving already-sonnet-4.6 rows — was **not** the actual cause of session 19's apparent overlap. `_needs_regen()` correctly skips rows already at `prompt_version 2026-04-16.2`. The overlap was `import_jobs_summary._propagate_to_siblings` copying summaries to cross-source-duplicate rows in **published** status (each Opus draft was only requested once, but summaries fanned out to all rows sharing the same `jobs.hash`). No export-side fix needed; the client-side `already_sonnet.txt` safety filter was built but unused.

**IDs stamped this session:**

- R1 (847, 845, 838, 833, 831, 830, 829, 827, 824, 802) — Databricks (RSA Atlanta, Counsel, GTM Dir, SE Aarhus, Backend Aarhus, SE Retail-CPG, FINS SEA, Dir R&CPG DE, Dir Emerging Ent) + Scale AI GenAI SWE
- R2 (771, 712, 698, 553, 552, 549, 548, 547, 546, 544) — Anthropic PM Monetization, PhonePe HR Coord + AI Creative Head, 7 Databricks (CS Enablement, Hunter AE, APM Berlin, SWE Delta, Org Dev Arch, AI FDE Mgr, Core AE Zurich)
- R3 (542, 541, 539, 538, 537, 536, 535, 533, 531, 530) — 2× UC Runtime Enforcement (Zurich/Berlin), EM Streaming Bellevue, CEA Bellevue, MFG AE Arizona, AI FDE, Sr Mgr FE FSI, PM Repos Seattle, AE FSI NYC, Named Core AE Retail
- R4 (529, 527, 526, 525, 524, 425, 421, 420, 419, 416) — Databricks SA Japan (JP JD), SA FSI EC, SWE Delta Aarhus, Sr Resident SA SG, Fed Sec Assurance + 5 Figure roles (Transfer Agent, Partner Support, Controller, CCO, Principal PD)
- R5 (414, 238, 237, 235, 234, 230, 229, 228, 227, 226) — Figure Sr Mgr Strategic Finance + 9 Databricks (DSA Nordics, EBC Mgr SF, Dir FE SG, EntAE FSI, Mgr FE MEL, EM Notebook DP, Hunter AE SG, Finance Mgr, CEC Amsterdam)
- R6 (225, 223, 219, 218, 216, 215, 213, 212, 211, 205) — Databricks SSA AI Tooling, CEC Belgrade, Partner Enablement, Learning PM, DSA H&LS, AI FDE Federal (citizenship+clearance), Partner Sales Dir, MBA Intern SF, SA Public Sector LEAPS, Scale Staff Applied AI
- R7 (171, 149, 147, 146, 144, 142, 141, 139, 103, 80) — Anthropic SLG AE $360-435K + 7 Databricks + Anthropic Incident Mgr D&R + Anthropic Privacy RE $320-485K

**Generator-side validator caught 3 chip-label caps pre-flight:** "Spark Structured Streaming" (R3, 26 chars), "Principal Product Designer" (R4, 26), "C-level customer audience" (R5, 25). All trimmed before import. **0 post-import schema violations** reported by the `_validate_summary` clamp.

**Carry-forward operator gotchas (confirmed still live on Windows):**

1. **Heredoc + apostrophes:** single-quoted bash heredocs break when the JSON payload contains `'`. Workaround: always write summaries to a local file and pipe via `cat local.json | ssh VPS "docker compose exec -T backend python -m scripts.import_jobs_summary ..."`. Never heredoc JSON inline.
2. **Container `/tmp` ≠ host `/tmp`:** `docker compose exec -T backend cat /tmp/x.json` reads the **container's** `/tmp`, not the host. A prior attempt to stage JSON via `cat local | ssh VPS "cat > /tmp/x"` then separately `docker compose exec ... cat /tmp/x` failed (file on host, container couldn't see it). Fix: pipe stdin all the way through in one chain: `cat local.json | ssh VPS "docker compose exec -T backend python -m scripts.import_jobs_summary --model sonnet-4.6"`.
3. **Windows stdout codec (cp1252):** Python prints crash on Japanese JDs / Cyrillic titles. Workarounds: `sys.stdout.reconfigure(encoding='utf-8')` at script top, or read export JSON via a Read tool / file open with `encoding="utf-8"` instead of piping through stdout.
4. **Session-artifact naming:** `C:/tmp/gen_r{N}.py` and `C:/tmp/r{N}_summaries.json` from prior sessions are still on disk. Use a session prefix (e.g., `s20_r{N}`) to avoid collision; sweep old ones periodically.

### Session 19 — editorial summary refresh chunk 2 (Claude Max, 30 rows)

Previous chunk stamped 30 rows (Rounds 8-10) continuing from chunk 1. Data-plane only; see git commit `ddf6688` doc-level note and session 20's baseline (sonnet-4.6 draft = 81 at start). Rounds 8-10 IDs: 50, 15, 892, 819, 792, 784, 716, 509, 470, 424, 418, 415, 331, 312, 239, 231, 210, 181, 168, 163, 152, 143, 120, 70, 64, 63, 851, 850, 849, 848.

### Session 18 — editorial summary refresh chunk 1 (Claude Max, 70 rows)

First chunk of the `2026-04-16.2` refresh campaign. Stamped 70 rows via Rounds 1-7 (Scale HFC fellows, xAI roles, Anthropic Fellows 16/17/18, Databricks APAC, Figure trio, etc.). Introduced helper-function pattern for repeated role templates (`XAI_BENEFITS`, `hfc_ml()`, `figure_team_manager()`) — carry-forward recommendation for subsequent chunks.

### Sessions 15–17 — single-thread arc on AI Jobs classification

The whole arc started with one motivating example: PhonePe **"Manager, Legal"** got ingested with `Topic = ["Applied ML"]` because the JD said *"LLB / LLM from a recognized university"* and Gemini Flash conflated **M**aster of **L**aws with **L**arge **L**anguage **M**odel. Investigation revealed 268+ historical false positives across Tier-1 sources (Anthropic, Databricks, xAI, Cerebras, etc.).

**Result:** 10-layer classification defense system across RCA-026 + Waves 1–5 #18. **268 historical false positives backfilled**, **115 new tests** in `test_jobs_cost_opt.py`, full developer reference in [docs/JOBS_CLASSIFICATION.md](./JOBS_CLASSIFICATION.md), admin-facing sections #7+#8 added to `/admin/jobs-guide`.

### Commit history (sessions 15–17)

| Commit | Scope | One-liner |
|---|---|---|
| `065e93e` | `backend/app/services/jobs_ingest.py`, `jobs_enrich.py`, both prompts | RCA-026 4-layer fix (title patterns, JD scanner, removed Applied-ML fallback, LLM disambiguation) |
| `3257350` | `scripts/backfill_rca026_non_ai.py` | Backfill script — fix `Job.title` not `title_raw` |
| `4792d8f` | `jobs_ingest.py`, `jobs_enrich.py`, both prompts, tests | Wave 1 — 50+ title patterns, designation↔topic, topic anchors, self-rejection prompt block |
| `a4dee0a` | `jobs_ingest.py`, tests | Wave 2 — 3-tier weighted intensity scoring, word-boundary regex, dedup, boilerplate strip |
| `2255064` | `jobs_ingest.py`, tests | Wave 3 — non-AI cluster expansion, requirement-phrase neutralizer, bare-verb gate |
| `e36078e` | `scripts/backfill_rca026_non_ai.py` | Backfill — add Wave 3 bare-verb gate |
| `fc9ed5c` | `jobs_ingest.py`, `admin_jobs.py`, tests | Wave 4 #14+#15 — rejection-rate alarm + AI-intensity histogram |
| `fc670bc` | `scripts/select_audit_sample.py`, `admin_jobs.py`, `scheduler.py`, tests | Wave 4 #16 — Opus audit via Claude Code (no API spend) |
| `d6f62db`, `ee95af7` | `scripts/select_audit_sample.py`, tests | Audit test fixes (db session reuse, datetime import) |
| `1610cee` | `jobs_enrich.py`, both prompts, tests | Wave 5 #18 — evidence-span topic validation |
| `7585db0` | `docs/JOBS_CLASSIFICATION.md`, `admin.py`, `CLAUDE.md` | 10-layer documentation + admin guideline sections #7+#8 |
| `784f8d8` | `admin.py` | Hotfix — escape JSON braces in f-string admin guide (RCA-027 outage) |
| `4b78608` | `docs/RCA.md` | RCA-027 entry + updated "f-strings with HTML/JS/JSON" pattern row |
| `3233850` | `docs/HANDOFF.md` | Session 17 close handoff |
| `4a79082` | `admin.py`, `templates/admin/jobs_guide.html` (new), `prompts/jobs_summary_claude.txt`, tests, `HANDOFF.md` | Jinja2 migration of `_JOBS_GUIDE_HTML` (RCA-027 prevention) + bumped PROMPT_VERSION to `2026-04-16.2` + cleaned stale handoff items |
| `7e10ca9` | `admin_jobs.py`, `templates/admin/jobs_guide.html` | Session 18 — Jobs Review UX polish + missing signals (KPI tiles, intensity histogram, noisy-source table, auto-disabled guard, last-audit chip, 7d-published chip) + admin guide Section 10 |

---

## What's live (10 defense layers, in pipeline order)

1. `is_non_ai_title()` — ~120 substring patterns across 21 categories
2. `has_non_ai_jd_signals()` — ≥2 cluster hits AND intensity < 5
3. `is_bare_verb_title()` — Manager/Director/Lead w/o AI anchor + low intensity
4. `compute_ai_intensity()` — 3-tier weighted score, threshold 5, dedup, boilerplate stripped, requirement-phrases neutralized
5. SELF-REJECTION rules in both system prompts (21-category list)
6. `_validate_topic_with_evidence()` — Wave 5 #18: anti-hallucination + per-topic forbidden patterns
7. `_enforce_topic_anchors()` — each topic must have JD anchor
8. `_enforce_designation_topic_consistency()` — Other ⇒ []; AI-adjacent capped at 1
9. `check_source_rejection_rates()` — auto-disable >40% reject sources at end of daily ingest
10. Weekly Opus audit — Mon 04:30 UTC cron picks 1% Tier-1 published; admin reviews via COPY PROMPT button → VS Code Claude Max → POST `/api/audit-submit`

Wave 5 #19 (two-stage classifier) **deliberately not shipped** — cost-benefit unfavorable post-Waves 1–5; revisit only if observability (Layers 9, 10) reveals new failure patterns.

---

## Documentation map

- **Developer reference:** [docs/JOBS_CLASSIFICATION.md](./JOBS_CLASSIFICATION.md) — all 10 layers with code locations, calibration data, configuration constants, and "Adding a new defense layer" guidance
- **Admin user guide:** [/admin/jobs-guide](../backend/app/routers/admin.py) sections #7, #8, #10 — classification layers, Opus audit workflow, and new "Reading the Dashboard Signals" reference covering KPI tiles / histogram / noisy sources / audit staleness
- **Bug records:** [docs/RCA.md](./RCA.md) RCA-026 (LLM-as-law-degree fix) + RCA-027 (f-string outage from this session)
- **Backfill script:** `python scripts/backfill_rca026_non_ai.py --apply` — idempotent, runs Layers 1+2+3 against historical rows

---

## RCA-027 (this session) — production hotfix + structural fix

After deploying the admin guideline (commit `7585db0`), the backend crashed with `NameError: name 'job_id' is not defined` because `_JOBS_GUIDE_HTML` is an f-string and my new section had literal `{job_id, agreed, ...}` and `{"results":[...]}` JSON in `<code>` blocks. Same root cause as RCA-024 (JS strings in f-strings). Hotfix `784f8d8` doubled all literal braces. Down ~5 minutes.

**Structural fix shipped same session (commit `4a79082`):** migrated the entire 313-line `_JOBS_GUIDE_HTML` to a proper Jinja2 template at `backend/app/templates/admin/jobs_guide.html`. Jinja2 inverts the brace semantics (`{` is literal by default; `{{ var }}` is interpolation) so adding HTML/JSON/code samples can no longer crash module import. Per CLAUDE.md "no compat shims" — the legacy f-string was removed entirely (315 lines deleted from admin.py), not kept as fallback. 4 new tests guard against regression. Pattern documented in [docs/JOBS_CLASSIFICATION.md](./JOBS_CLASSIFICATION.md) "Jinja2 migration" section.

Other admin f-strings (templates page 141 lines, users page 76 lines, dashboard 37 lines) left as-is — below the high-risk threshold (no code samples, lower edit frequency).

---

## Next session

**Primary action: measure for 1–2 weeks.** The Wave 4 observability stack (rejection-rate alarm, intensity histogram, weekly Opus audit) surfaces drift automatically. The Jobs Review page now has full signal coverage — KPI tiles, intensity histogram, noisy-source table, auto-disabled guardrail count, last-audit staleness, and 7d-published throughput chip. No new code work needed unless:

- Admin reports a false positive that slipped through all 10 layers → identify which layer should have caught it, add patterns/anchors per [docs/JOBS_CLASSIFICATION.md](./JOBS_CLASSIFICATION.md) "Adding a new defense layer" section
- Drift detection (Layer 9 auto-disable or Layer 10 audit mismatch) reveals a systematic gap → may revisit Wave 5 #19 (two-stage classifier)

**Outstanding (verified live state 2026-04-17 session 22 close):**

1. Submit `sitemap_index.xml` to Google Search Console (manual one-time admin task)
2. Set `INDEXNOW_KEY` in `.env` (currently empty — IndexNow notifications fail silently; minor SEO loss, not a bug)
3. **Editorial uplift — burn-down continues.** Sessions 18+19+20+22 have stamped **239 rows** at `prompt_version 2026-04-16.2 / sonnet-4.6` (221 draft + ~18 propagated to published). Remaining work at session 22 close:
   - **464 rows with no summary** (298 draft + 166 published) — pure-null, untouched by Flash or Opus
   - **92 rows with stale prompt_version summaries** (55 opus-4.6@old in draft + 32 in published + 5 test-propagation)
   - **Total refreshable: 556 rows** → plan 5-8 more chunks of 70-100 each

   $0 API spend (Claude Max in VS Code), only paste-cycle operator time. Goal: burn down to zero, then optionally sweep published-side prior-Opus rows for consistency.

**Recently dropped (verified done):** Gemini API key (rotated prior session); `/summarize-jobs --status draft` full seed coverage (drafts all have *a* summary — now in prompt-version-refresh mode, not seed mode).

### Next-session resume prompt (session 22 handoff)

Paste the following prompt verbatim into a fresh session to pick up a new chunk:

```text
Continue the legacy-summary refresh on the AI Roadmap Platform VPS using the
/summarize-jobs skill. Session 22 stamped 70 rows (all clean, +70 net
sonnet-4.6 stamps in draft pool). This session: run another 70-100 row chunk.

CURRENT STATE AT SESSION START
Draft-pool model distribution:
  null (no summary)      : 298
  opus-4.6 @ 2026-04-16.2: 79    (current version — SKIPPED by export filter)
  opus-4.6 @ 2026-04-16.1: 55    (stale — WILL be re-exported)
  sonnet-4.6 @ current   : 221   (SKIPPED by export filter)
  test-propagation       : 5

EXPORT-FILTER BEHAVIOR (verified sessions 20 + 22)
scripts/export_jobs_for_summary.py uses _needs_regen() which SKIPS rows whose
summary._meta.prompt_version == current (2026-04-16.2). So rows already at
current prompt_version + sonnet-4.6 will NOT be re-served. Each export of
--batch 10 should give 10 fresh rows from the null-summary pool and the
stale-opus-4.6@2026-04-16.1 pool. No client-side filter needed.

TARGET THIS SESSION
Pick a row target (e.g. +70 net draft sonnet-4.6 stamps, or +100). Report
totals every 30 rows. Stop when target hit or at 100-row ceiling.

CRITICAL FLAGS (unchanged across chunks)
- Import with --model sonnet-4.6 (NOT opus-4.6 — overrides skill default)
- Prompt template version is 2026-04-16.2
- Data-plane only: no git commits, no container rebuilds, no code edits

WORKFLOW PER ROUND
1. Export batch of 10 from VPS:
     ssh a11yos-vps "cd /srv/roadmap && docker compose exec -T backend python -m scripts.export_jobs_for_summary --batch 10 --status draft"
   Save to C:/tmp/s{N}_r{R}_export.json (use a session prefix to avoid
   collision with prior sessions' artifacts still on disk).
2. Read the JDs via the Read tool (NOT via python -c printing — Windows cp1252
   chokes on Japanese/CJK titles). Or add sys.stdout.reconfigure(encoding='utf-8').
3. Draft summaries in a Python generator at C:/tmp/s{N}_r{R}.py:
   - Enforce caps: chip ≤24, resp title ≤48, detail ≤90, must_have ≤100,
     benefit ≤110, watch_out ≤110
   - Write JSON to C:/tmp/s{N}_r{R}.json with open(..., encoding="utf-8")
   - Validator in the generator should print violations and exit 1 if any
4. Import via stdin piped all the way through in one chain:
     cat C:/tmp/s{N}_r{R}.json | ssh a11yos-vps "cd /srv/roadmap && docker compose exec -T backend python -m scripts.import_jobs_summary --model sonnet-4.6"
   DO NOT stage JSON to /tmp on VPS between ssh and docker exec — the
   container's /tmp is separate from host /tmp.

PROGRESS CHECK ONE-LINER (run after every round)
  ssh a11yos-vps 'docker compose -f /srv/roadmap/docker-compose.yml exec -T backend sqlite3 /data/app.db "SELECT json_extract(data,'\''$.summary._meta.model'\'') AS m, COUNT(*) FROM jobs WHERE status='\''draft'\'' GROUP BY m ORDER BY 2 DESC;"'

QUALITY RULES
- Enforce every schema cap (pre-flight validator in the generator)
- Preserve every id exactly as exported (the import script matches by id)
- Flag anomalies in watch_outs: JD/posting contradictions, sparse JDs,
  language requirements (non-English JDs like Japanese), unusual comp
  structures, visa constraints, security-clearance requirements, fixed-term
  contracts, onsite-with-no-city-named
- Use Python helper functions for repeating role templates (e.g., Figure
  benefits, Scale HFC fellows, xAI AI tutors, Databricks UC Runtime
  Enforcement) — the /summarize-jobs skill template lives in the repo:
    ssh a11yos-vps "docker compose -f /srv/roadmap/docker-compose.yml exec -T backend cat /app/app/prompts/jobs_summary_claude.txt"

KNOWN WORKAROUNDS (confirmed sessions 20 + 22)
- Heredocs break on apostrophes in JSON (e.g. "Bachelor's") — always use the
  `cat local | ssh VPS "docker compose exec -T backend ..."` one-chain pattern
- Windows stdout codec is cp1252 — always write JSON to a file with
  encoding="utf-8" or reconfigure sys.stdout
- Container `/tmp` ≠ host `/tmp` — DO NOT stage files between them, pipe stdin
- Use session-prefixed artifact names (e.g. s22_r1.py) to avoid collision
  with C:/tmp files left over from sessions 18/19/20/21

SETUP CONTEXT
- Repo root: e:\code\AIExpert (Windows)
- VPS SSH alias: a11yos-vps
- Skill reference: /summarize-jobs (projectSettings:summarize-jobs)

Start by reading the prompt template + snapshotting the current model
distribution, then run rounds until target hit or 100-row ceiling, then stop
and report.
```

**Future migration (deferred, not urgent):** other admin f-string blobs (templates page 141 lines, users page 76 lines) could be migrated to Jinja2 too — but they're below the high-risk threshold. Only do this if one of them gets a code-sample edit that requires brace-doubling.

**Open questions for the user:** None.

---

## Key constants (see [docs/JOBS_CLASSIFICATION.md](./JOBS_CLASSIFICATION.md) "Configuration" for full list)

```python
# backend/app/services/jobs_ingest.py
PER_SOURCE_NEW_CAP = 30
ENRICH_CONCURRENCY = 4
AI_INTENSITY_THRESHOLD = 5
REJECTION_RATE_WINDOW_DAYS = 30
REJECTION_RATE_MIN_SAMPLE = 20
REJECTION_RATE_THRESHOLD = 0.40

# scripts/select_audit_sample.py
DEFAULT_SAMPLE_PCT = 0.01
MIN_SAMPLE = 1
MAX_SAMPLE = 20
DEFAULT_COOLDOWN_DAYS = 90
```
