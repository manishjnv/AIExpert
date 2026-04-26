# COURSES.md — AutomateEdge AI Courses Strategic Plan

> Living document. Rewrite the **Change log** at the bottom after every course-related commit (catalog edits, prompt tunes, format additions, deprecations).
> Read this file before any change to the course catalog, curriculum templates, generation/review/refine prompts, course-format infrastructure, or admin generation workflow.

## 0. Session kickoff — read this first every session

**Read this file at the start of every session** as part of the Phase 0 warm-start burst (listed in [CLAUDE.md §8](../CLAUDE.md)). You do not need to re-read the whole plan — scan this §0 + the Task status board in §0.2 + the most recent Change-log entry at the bottom. That gives you current state in ~60 seconds.

**When course work is in scope for the session**, also load §5 (architecture) + §8 (admin workflow) + §9 (tech-shift response). If you're authoring or reviewing a flagship/sprint/micro, also load §6 (competitor crib) and §7 (viral mechanics).

### 0.1 Trigger conditions — when this plan governs the work

Any of these conditions means the session must follow this plan before landing changes:

- Generating, editing, or deleting any curriculum template under `backend/app/curriculum/templates/`
- Editing `backend/app/prompts/generate_curriculum.txt` / `review_curriculum.txt` / `refine_curriculum.txt` / `discover_topics.txt` / `triage_topic.txt` / `quarterly_sync.txt`
- Editing `backend/app/services/curriculum_generator.py`, `topic_discovery.py`, `batch_generator.py`, `quality_pipeline.py`, `quality_scorer.py`, `content_refresh.py`, `pipeline_scheduler.py`
- Adding or modifying any course-format type (today: 3mo/6mo/12mo flagship; this plan adds: 1-2hr micro, 5-7 day sprint, 8-week flagship)
- Editing the admin Pipeline / Topics / Templates / Proposals UI in `backend/app/routers/admin.py` / `pipeline.py`
- Adding any course-discovery / quiz / showcase / cohort-mode / streak / certificate-bundling route
- Any task from the `COURSE-00` … `COURSE-28` set in §10 below
- A "tech-shift" event (paradigm-shift model release, framework deprecation, hiring-language drift) per §9.2

### 0.2 Task status board

Update the Status column as tasks move. `⬜ pending` → `🟡 in progress` → `✅ done`. Add a `🔒 blocked (reason)` state if waiting on something external.

| ID | Phase | Priority | Task | Status |
|---|---|---|---|---|
| COURSE-00 | A | P0 | Author this doc + capstone rubrics + admin SOP | 🟡 in progress (this commit) |
| COURSE-00.5 | A | P0 | Add "Roadmap" to top nav + footer (links to existing /roadmap hub) | ✅ done (2026-04-25) — [nav.js:79](../frontend/nav.js#L79) topnav + [nav.js:170](../frontend/nav.js#L170) footer; position: Home → Roadmap → Leaderboard → Blog → Jobs |
| COURSE-01 | A | P0 | Add `discovery_focus` param + role-shaped + viral-shaped seed prompts to topic_discovery | ⬜ pending |
| COURSE-02 | A | P0 | Format-specific generate prompts (micro / sprint / 8wk variant) + resource `type` + per-column primary | ⬜ pending |
| COURSE-03 | A | P0 | Capstone-rubric review checklist (admin UI + scorer dimension) | ⬜ pending |
| COURSE-04 | B | P0 | Build flagship "AI Foundations" — 6-week beginner | ⬜ pending |
| COURSE-05 | B | P0 | Build flagship "LLM Engineer" — 12-week (default flagship) | ⬜ pending |
| COURSE-06 | B | P0 | Capstone showcase: route + page + index | ⬜ pending |
| COURSE-07 | B | P0 | "What AI track is right for you?" quiz funnel (extends SEO-26) | ⬜ pending |
| COURSE-08 | B | P0 | Specialization-bundle certificate (flagship + 4 shorts → LinkedIn share) | ⬜ pending |
| COURSE-09 | C | P1 | Sprint format infra + first sprint "LLM Engineer Quickstart 7d" | ⬜ pending |
| COURSE-10 | C | P1 | Micro format infra + first 5 micros (1-2hr each) | ⬜ pending |
| COURSE-11 | C | P1 | Streak counter on profile + week cards | ⬜ pending |
| COURSE-12 | C | P1 | 30-day LLM app challenge (sprint variant) | ⬜ pending |
| COURSE-13 | C | P1 | Spaced-retention email loop (post-micro / post-sprint nudge) | ⬜ pending |
| COURSE-14 | C | P1 | Public capstone gallery index `/showcase` | ⬜ pending |
| COURSE-15 | D | P1 | Build flagship "AI Product Builder" — 8-week | ⬜ pending |
| COURSE-16 | D | P1 | Build flagship "ML Engineer" — 12-week | ⬜ pending |
| COURSE-17 | D | P1 | Build flagship "GenAI Engineer" — 12-week (depth track) | ⬜ pending |
| COURSE-18 | D | P1 | Build flagship "MLOps" — 8-week | ⬜ pending |
| COURSE-19 | E | P2 | Build advanced flagships: LLM Internals/Training + AI Research (12-week each, Karpathy-style) | ⬜ pending |
| COURSE-20 | E | P1 | Generate 22 short modules in parallel Sonnet batches | ⬜ pending |
| COURSE-21 | E | P2 | Course-discovery page redesign (filter + role-recommend on 40-course catalog) | ⬜ pending |
| COURSE-22 | F | P1 | Tech-shift triage admin page (signal monitor + tier classifier) | ⬜ pending |
| COURSE-23 | F | P1 | Course versioning UI in admin (v1.0 → v1.1 → v1.2 history per template) | ⬜ pending |
| COURSE-24 | F | P1 | Course deprecation flow (mark deprecated, keep enrolled, archive) | ⬜ pending |
| COURSE-25 | F | P1 | Course quality dashboard (per-course completion, dropout points, capstone-ship rate) | ⬜ pending |
| COURSE-26 | F | P2 | Weekly "what's new in AI" digest tied to active courses | ⬜ pending |
| COURSE-27 | F | P2 | Cohort mode opt-in (deadlines + peer accountability) | ⬜ pending |
| COURSE-28 | F | P2 | Format-aware completion analytics + funnel-conversion tracking | ⬜ pending |
| COURSE-29 | A | P0 | 2-column resource rendering (video left / non-video right) on week cards | ⬜ pending |

**Next action** (always — single source of truth): COURSE-00 (this doc) → COURSE-00.5 (Roadmap nav, ~15-line drive-by) → COURSE-01 (`discovery_focus` param, ~30-line change in [topic_discovery.py](../backend/app/services/topic_discovery.py)) → COURSE-02 (format-specific prompts + resource `type` field + column-primary marker) → COURSE-03 (capstone rubric scorer dimension) → COURSE-29 (2-column rendering, frontend-only). COURSE-00.5 + COURSE-01 + COURSE-02 + COURSE-03 + COURSE-29 are foundation work that unblocks Phase B. Phases B and C ship the *visible* viral surface area; Phases D-E fill the catalog; Phase F operationalizes ongoing maintenance.

### 0.3 Orchestration notes

- **Load-bearing paths touched by this plan** (require worktree isolation + Opus diff review per [CLAUDE.md §8](../CLAUDE.md#L168)): `backend/app/prompts/generate_curriculum.txt` and the other prompt assets (tuned content, never regenerated without user approval); `backend/alembic/versions/` (any course-versioning / deprecation schema migrations); `backend/app/services/quality_pipeline.py` and `quality_scorer.py` (regression risks affect every published course).
- **Sonnet subagent-eligible** (mechanical, contract specified here): COURSE-00.5, COURSE-01, COURSE-06, COURSE-09 infra (not the sprint authoring), COURSE-11, COURSE-14, COURSE-20 (parallel batch — fan out one Sonnet per short, in one message), COURSE-21, COURSE-22, COURSE-23, COURSE-24, COURSE-25, COURSE-28, COURSE-29.
- **Opus-only** (judgment + tuned editorial): COURSE-02 prompt design, COURSE-03 rubric authoring, COURSE-04 / COURSE-05 / COURSE-15..COURSE-19 flagship authoring (all 8 flagships), COURSE-09 sprint authoring (first sprint sets the template), COURSE-10 first micro authoring.
- **Codex:rescue gating**: any Alembic migration in COURSE-23 / COURSE-24 (course versioning + deprecation schema). Per [CLAUDE.md global playbook](../../.claude/CLAUDE.md), security/auth-adjacent or load-bearing migrations require adversarial sign-off before push.
- **Parallel-safe pairs** (fire together in one message): (COURSE-01, COURSE-02, COURSE-03), (COURSE-22, COURSE-23, COURSE-25), all of COURSE-20's 22 sub-tasks (one Sonnet per short).

## 1. Goal & success metrics

**Goal:** Ship 30-40 AI courses across 4 format tiers — 8 flagships (4-12wk), 22 short modules (1-2wk), 5-10 micro-courses (1-2hr), 3-4 sprints (5-7d) — that map to 2026 hiring roles, gate progress on shipped artifacts, and compound socially through public capstones, certificates, and viral sprint formats. Maintain currency through admin-operated tech-shift response (§9).

**Targets (12-month horizon from Phase B ship):**

| Metric | Baseline | 90-day target | 180-day target | 365-day target | Source |
|---|---:|---:|---:|---:|---|
| Published courses | 3 (3mo/6mo/12mo generic) | 10 (2 flagships + 5 micros + 1 sprint + 2 shorts) | 25 | 40 | `/api/templates` |
| Flagship completion rate (12wk capstone shipped) | n/a | n/a | ≥ 25% (vs MOOC ~5-15% baseline) | ≥ 40% | progress + capstone showcase ship-rate |
| Sprint completion rate (day 7 ship) | n/a | ≥ 50% | ≥ 60% | ≥ 70% (vs cohort literature 60-80%) | sprint cohort data |
| Micro-course completion rate | n/a | ≥ 60% | ≥ 70% (vs DLAI shorts 60-80%) | ≥ 75% | per-template progress |
| Capstones shared on LinkedIn / X | 0 | ≥ 20 | ≥ 100 | ≥ 500 | share button telemetry |
| Quiz-funnel completion → flagship enrollment | n/a | ≥ 30% | ≥ 40% | ≥ 50% | funnel analytics |
| Certificates issued | 0 | ≥ 50 | ≥ 250 | ≥ 1500 | certificates table |
| 7-day-streak active learners | n/a | ≥ 100 | ≥ 500 | ≥ 2000 | streak counter |

**First action (do before any catalog work):** ship COURSE-00 (this doc), then COURSE-01 + COURSE-02 + COURSE-03 in parallel. Without `discovery_focus` and format-specific prompts, the auto-discovery → triage → generate pipeline cannot produce role-shaped or short-format catalog at quality. Without capstone rubrics, "completion" remains checkbox-shaped, not artifact-shaped — and the entire viral thesis depends on shipped artifacts.

## 2. Constraints & non-negotiables

These override any course-design "best practice" from outside sources. If a tactic conflicts, the constraint wins.

1. **Frontend stays a single file that runs standalone from disk** ([CLAUDE.md §5 rule 8](../CLAUDE.md#L82-L83)). Course catalog UI must preserve `file://` execution. No build step, no SPA framework.
2. **AI prompt assets are tuned; never regenerated without user approval** ([CLAUDE.md §8](../CLAUDE.md#L189)). `generate_curriculum.txt`, `review_curriculum.txt`, `refine_curriculum.txt` — propose edits in this doc, get approval, then patch.
3. **Flagship templates are tuned editorial assets**, not auto-generated boilerplate. Per [feedback_opus_for_editorial.md](../../.claude/projects/e--code-AIExpert/memory/feedback_opus_for_editorial.md) — Flash/Groq cannot match Opus editorial quality. Flagships generate via the manual paste-upload flow (Topics → Claude prompt generator → paste into admin, per [feedback_manual_template_workflow.md](../../.claude/projects/e--code-AIExpert/memory/feedback_manual_template_workflow.md)). Auto-pipeline is for shorts only.
4. **Enrolled users keep their pinned template version** when course is updated ([project_auto_curriculum.md Phase 5](../../.claude/projects/e--code-AIExpert/memory/project_auto_curriculum.md)). Never silently mutate a published template — always create a new version row, prompt opt-in upgrade.
5. **Capstone rubrics enforce concrete artifacts**, not "demonstrate understanding." Acceptance criteria must be a deployed thing, a public repo, or a published artifact — verifiable by the existing AI evaluation pipeline ([evaluate.py](../backend/app/routers/evaluate.py)).
6. **Choice paralysis at week 1 is the silent killer**. Each week emits *two* primary resources — one video ("if you only watch one, watch this") and one non-video ("if you only read/build one, do this") — plus 4 secondary resources. Resources carry an explicit `type: "video" | "non-video"` field. The generation prompt currently emits 6 equal-weight, untyped resources — **COURSE-02** fixes the data layer (typing + per-column primary), **COURSE-29** renders the result in a 2-column layout (Watch / Read-&-Build).
7. **No paid course platforms, no paid LMS tools, no agencies.** Build inside the existing FastAPI/SQLAlchemy/SQLite/Vanilla-JS stack. Reuse existing primitives (templates, progress, evaluations, certificates, AI mentor) before adding new ones.
8. **Course-data privacy.** Public showcase pages only when learner opts in (`user.public_profile = True` per [reference_platform_config.md](../../.claude/projects/e--code-AIExpert/memory/reference_platform_config.md)). Streaks, progress, in-progress capstones — all private by default.
9. **Reversibility.** Every catalog change (publish, deprecate, version bump) must be reversible without learner data loss.
10. **The auto-curriculum stays as a "Custom / Explore" path**, not the marketing default. After Phase B, the visible default for new visitors is a flagship — auto-generated 3mo/6mo/12mo plans demote to "build a custom plan" mode.
11. **Resources are the *top 3 best* for the subtopic, not arbitrary 3.** Each week ships exactly 3 video + 3 non-video resources, and each set of 3 is selected against a quality bar: authority of source (allowlist in §14), currency (≤24 months for AI topics; older only if foundational/canonical like Goodfellow et al.), practical applicability (has code/lab/exercise — not pure theory), and pedagogical fit (matches the week's level). The 1 primary per type is the *best of the 3* — the "if you only watch/read one." Generation prompt enforces this; AI review and the COURSE-03 capstone rubric gate on it; quality scorer adds a "Resource Quality" dimension.

## 3. Diagnosis — why current courses underperform

Three structural problems, none about content quality:

1. **Topic-shaped, not role-shaped.** Existing tracks are "AI in 3/6/12 months" by subject. 2026 hiring is by role: GenAI/LLM Engineer (largest active surge), ML Engineer (steady undersupply), AI Product Builder (fastest-growing new role), MLOps. A learner finishing the 6-month plan still can't answer *what job am I qualified for now?*
2. **Checklists, not capstones.** Checkbox completion ≠ skill demonstration. Best-in-class courses gate progress on a *shipped artifact* judged against a public rubric. The existing AI evaluation pipeline ([evaluate.py](../backend/app/routers/evaluate.py)) is the engine for this — but it's decorative today, not gating.
3. **No format ladder.** Single 4-week-month structure means all courses look the same. The viral lever — micro-courses (1-2hr) for top of funnel, sprints (5-7d) for activation, 12-week flagships for portfolio — doesn't exist.

Subordinate issues:

- Auto-generation optimizes coverage over voice. Andrew Ng / fast.ai / HF win on opinionated single-path narrative — auto-generated content cannot replicate this without manual Opus editorial polish for flagships.
- Six equal-weight resources per week creates choice paralysis (Iyengar 2000 — choice-load reduces completion).
- No external accountability loop. Solo MOOCs lose 85-95% of starters; cohort/deadline-driven courses retain 60-80% (Maven, On Deck, Reforge data).
- 12-month plan is a credibility/SEO asset, not a learning product. Currently positioned as default — should be visible-but-de-emphasized.

## 4. Research foundation

Citations or attributable sources where possible. All numbers used to set the targets in §1 and the format choices in §5.

### 4.1 Completion data by format

| Duration | Completion (started) | Source |
|---|---:|---|
| 1-2hr micro | **60-80%** | DeepLearning.AI Short Courses portfolio (2023-25 launch data); LinkedIn Learning aggregate |
| 5-7 day sprint (daily 30-60min) | **60-80%** | Maven 1-week sprints; Karpathy nanoGPT 6-day cohort; Andrew Ng "Build Agent in a Week" |
| 4-8 weeks (multi-week with cohort) | 30-50% | Coursera/edX 2019-2023 longitudinal; Maven 4wk; HF NLP course |
| 4-8 weeks (self-paced solo) | 15-25% | Coursera self-paced data |
| 12 weeks with monthly capstone gates | 25-40% | DeepLearning.AI Specializations (gated); Berkeley LLM Bootcamp |
| 12 weeks self-paced no gates | 5-10% | classic MOOC Coursera/edX |
| 6 months any format | 5-10% | classic MOOC |
| 12 months any format | **<3%** | classic MOOC; "year-long roadmap" social-share pattern |

Mechanism: Bjork & Bjork "desirable difficulties," Cepeda 2006 spacing meta-analysis, Tom Stafford streak research (day-2-3 dropout cliff, day-5+ completion bias).

### 4.2 Pedagogy patterns that work for AI specifically

- **Top-down (fast.ai)**: ship working artifact in lesson 1, theory after → ~4× completion vs bottom-up theory-first (fast.ai cohort vs Coursera ML aggregate).
- **Build-from-scratch once before library** (Karpathy zero-to-hero thesis): highest skill-transfer pattern; produces learners who can *debug* not just *use*.
- **Daily ship beats daily lecture**: each session ends with a commit / screenshot / deployed thing — drives both retention and viral content.
- **30-60 min/day, 5 days/week**: highest-completion daily load. 2-3hr/day = aspirational, kills completion at 30% by week 2.
- **Spaced retrieval > re-reading** (Cepeda 2006): post-completion email nudges with 1 retrieval question at +3d, +7d, +21d → 2× retention vs none.
- **Cohort accountability**: Maven internal data shows opt-in deadline + peer roll-call = 60-80% completion vs ~25% solo. Don't *force* cohort — opt-in only, default solo.
- **Decision moment, not graduation**: beginner courses end with "you now know enough to pick X / Y / Z," not a generic congrats. Funnel intent must be explicit.

### 4.3 Format ladder — what each is for

| Format | Role in funnel | Skill-transfer | Virality | Daily load | Retention design |
|---|---|---|---|---|---|
| **1-2hr micro** | Top of funnel; SEO; lead magnet; tasting-menu | Low — exposure only | High — single-sitting share | n/a (one sitting) | **Mandatory** post-completion email loop at +3d, +7d, +21d |
| **5-7 day sprint** | Activation; cohort hook; viral content | Moderate — repeated practice → functional ability | **Highest** — "Day N of 7" public-build threads | 30-60 min/day | Daily roll call; Day 0 prep email; end-of-week capstone share |
| **4-8 wk short** | Skill specialization; flagship-week swap-in | Moderate-high | Moderate | 4-8 hr/wk | Quality scorer ≥ 80; weekly capstone optional |
| **12 wk flagship** | Portfolio-worthy; hiring-aligned | High — capstone-gated | Moderate (compounded via showcase) | 10-22 hr/wk by level | Capstone gate every 4 weeks; cert + LinkedIn share |

### 4.4 The forgetting curve and the post-completion nudge

Without follow-up, 1-2hr micro retention drops to ~30% at 24h, ~20% at 7 days (Ebbinghaus / Cepeda). The fix is cheap and the platform's existing email infra (Brevo/Resend, [reference_platform_config.md](../../.claude/projects/e--code-AIExpert/memory/reference_platform_config.md)) makes it trivial: 3-touch retrieval-question email loop after every micro completion. Same loop after sprint completion at +7d / +30d. **Without this loop the high micro completion rate is a vanity metric.** COURSE-13 wires this.

## 5. Course architecture

### 5.1 Format ladder (the four tiers)

| Format | Duration | Weekly structure | Resources/wk | Resource layout | Capstone | Generated by |
|---|---|---|---|---|---|---|
| Micro | 1-2 hr (single sitting) | n/a (3-5 segments) | 3 (one primary, 2 secondary) | Linear (single column — single sitting context) | None — single artifact at end | Auto-pipeline (new prompt — COURSE-02) |
| Sprint | 5-7 days, 30-60 min/day | day-keyed, not week-keyed | 2/day primary (1 video + 1 non-video) + 1 stretch | 2-column per day (COURSE-29) | Required — public ship by day 7 | Manual Opus authoring (first one); auto for variants |
| Short | 1-2 wk (8-15 hr total) | 1-2 weeks, current 4-week structure | 6 = (3 video + 3 non-video) with 1 primary per type | **2-column** per week — Watch / Read-&-Build (COURSE-29) | Optional | Auto-pipeline (existing flow) |
| Flagship | 4 / 8 / 12 weeks | 4-week monthly modules with capstone gates | 6 = (3 video + 3 non-video) with 1 primary per type | **2-column** per week — Watch / Read-&-Build (COURSE-29) | Required, gated, AI-evaluated | Manual Opus authoring (Topics → paste-upload) |

### 5.2 Course count by level (the 40-course catalog)

| Level | Flagships | Shorts (1-2wk) | Micros (1-2hr) | Sprints (5-7d) | Total |
|---|---:|---:|---:|---:|---:|
| Absolute Beginner (no coding) | 1 ("AI Foundations" 6wk) | 4 (Python-for-AI, Math-for-AI, Read-AI-papers-101, Prompt-engineering-for-non-coders) | 3 (What is AI · Build your first chatbot in 60min · AI for your day job in 90min) | 1 ("Beginner Quickstart 7d") | **9** |
| Beginner-with-coding | 2 (LLM Engineer 12wk · AI Product Builder 8wk) | 5 (RAG basics · Agents 101 · Vector DBs · LLM evals 101 · Build with OpenAI API) | 3 (Build a RAG app in 90min · Ship an LLM agent in 2hr · Deploy your first model in 60min) | 1 ("LLM Engineer Quickstart 7d") | **11** |
| Intermediate | 3 (ML Engineer 12wk · GenAI Engineer 12wk · MLOps 8wk) | 6 (Fine-tuning · LoRA/PEFT · LangGraph · LLM observability · Multimodal apps · Edge AI) | 2 (LLM evaluation in 2hr · Production traces in 90min) | 1 ("30-day LLM app challenge — week 1") | **12** |
| Advanced | 2 (LLM Internals/Training 12wk · AI Research 12wk) | 4 (RLHF/DPO · Distributed training · Mech-interp · Inference optimization) | — | — | **6** |
| Specialty (cross-level) | — | 3 (AI Safety + Red-teaming · AI for non-tech roles · Career-prep / portfolio review) | — | — | **3** |
| **Catalog total** | **8** | **22** | **8** | **3** | **41** |

**Why these numbers:** 8 flagships gives 1-3 per level — opinionated paths for everyone, few enough to handcraft each. 22 shorts feed both flagship weeks (as embeddable modules) and stand alone as SEO/lead-magnet products. 8 micros are top-of-funnel and shareable; 3 sprints are the viral-engine format that compounds via public day-7 ships. Beginner level intentionally has *no flagship choice* (one path) to eliminate week-1 paralysis; advanced has no micro/sprint because that audience self-selects into longer formats.

### 5.3 Canonical course list (priority-ordered for Phase sequencing)

**Tier 1 — ship in Phase B (highest leverage, most search volume, biggest audience):**
- AI Foundations (6wk beginner flagship)
- LLM Engineer (12wk default flagship)

**Tier 2 — ship in Phase C-D:**
- AI Product Builder (8wk) · ML Engineer (12wk) · GenAI Engineer (12wk) · MLOps (8wk)
- LLM Engineer Quickstart 7d sprint · 30-day LLM app challenge sprint
- 5 Tier 1 micros (one per high-search-volume topic)

**Tier 3 — ship in Phase E:**
- LLM Internals/Training (12wk advanced) · AI Research (12wk advanced)
- 22 short modules (parallel Sonnet generation) · remaining micros · Beginner Quickstart sprint

## 6. Competitor crib sheet

What each top platform does best, mapped to a concrete feature on automateedge.cloud.

| Competitor | Their best feature | Map to our platform | Plan reference |
|---|---|---|---|
| **DeepLearning.AI Specializations** | Bundle 4-5 short courses → LinkedIn-shareable certificate | Our flagship + 4 paired shorts = a Specialization. Cert system in progress per [project_certificate_system.md](../../.claude/projects/e--code-AIExpert/memory/project_certificate_system.md) | COURSE-08 |
| **DeepLearning.AI Short Courses** | 1-2hr, 1 instructor, 1 SDK — highest completion in their portfolio | Our 8 micros. One tool/concept each. | COURSE-10 |
| **fast.ai** | Top-down: working artifact in lesson 1, theory later | Enforce in flagship review: week 1 must ship a working thing | COURSE-03 + COURSE-05 |
| **Karpathy zero-to-hero** | Build-from-scratch series (micrograd, makemore, nanoGPT) | The advanced "LLM Internals/Training" flagship IS this. Highest viral coefficient on YouTube/X. | COURSE-19 |
| **Hugging Face NLP course** | Free, current (within weeks of new releases), Colab-hosted | Quarterly refresh + auto-discovery solves currency. Prefer Colab-hosted notebooks as canonical resources. | COURSE-26 + existing pipeline |
| **Maven cohort courses** | Deadlines + peer review = 60-80% completion | Opt-in cohort mode. Don't force; it's the high-conversion path. | COURSE-27 |
| **Kaggle Learn** | Micro-course → contest pipeline | Wire shorts → AI Jobs module + Kaggle competition links. "Finish this short, here are 3 jobs/contests where you can apply it." | COURSE-21 |
| **Andrew Ng "AI for Everyone"** | Concept-first, code-light, business-grounded | This *is* AI Product Builder + the non-coder shorts. | COURSE-15 |
| **Berkeley LLM Bootcamp** | Production-focused; ships deployed apps | Flagship capstone rubric mirrors this. | COURSE-03 |
| **#100DaysOfCode / 30 Days of ML** | Public daily-ship threads; high social signal | 30-day LLM app challenge as sprint variant. | COURSE-12 |
| **Brilliant.org** | Visual interactive learning; tiny daily session | Future micro-course UX direction (deferred, not in scope). | — |
| **Coursera flagship** | Industry signoffs (Google/IBM/Meta certificates) | We're free; differentiate on *gated capstones + AI evaluation*, not brand-stamped certs. Don't compete on partnerships. | n/a |

## 7. Viral mechanics

The "viral" lever isn't course content — content goes viral *once*. What compounds:

1. **Public capstone showcase** (COURSE-06 + COURSE-14): every learner who ships a capstone gets `/showcase/{username}/{slug}` — a permanent SEO/social asset. Index page lists all capstones. Each is a hub-and-spoke link back to the course that produced it. Compounds linearly with course completions.
2. **"Build GPT from scratch" track with public leaderboard** (COURSE-19): learners *want* to share when they ship a GPT they trained. Karpathy demonstrated this is the highest-virality format in AI education.
3. **"What AI track is right for you?" quiz** (COURSE-07; extends [SEO-26](SEO.md)): personalized output → LinkedIn-shareable result card → embedded course recommendation. Quiz outcome card image generated via existing OG image route.
4. **30-day LLM app challenge** (COURSE-12): daily-ship cadence creates daily social shares. Highest content-to-engagement ratio of any format. TikTok / X / LinkedIn-friendly.
5. **Cert + LinkedIn share** (COURSE-08; extends [project_certificate_system.md](../../.claude/projects/e--code-AIExpert/memory/project_certificate_system.md)): biggest single retention-and-social driver in MOOC research. Specialization bundle = flagship + 4 shorts → unified badge.
6. **Streak counter** (COURSE-11): Duolingo-style. Public number on profile (opt-in). Drives daily return visits.
7. **Weekly "what's new in AI + how it changes your course" digest** (COURSE-26): email re-engagement loop. Existing Brevo/Resend infra. Content is auto-generated from auto-discovery + content-refresh proposals.
8. **Sprint format day-1 roll call** (COURSE-09): public list of who started, public list of who shipped day 7. Pre-commitment + survivorship social proof.

**The compounding asset is the artifacts learners produce in sprints and capstones**, because those are the things that get shared on LinkedIn / X and bring new learners in. Content production scales linearly; learner-produced artifacts scale with the user base.

## 8. Admin workflow — the operating manual

The platform already has the levers needed (Pipeline → Discovery → Topics → Generation → Templates → Proposals → Refresh — see [admin.py](../backend/app/routers/admin.py) and [pipeline.py](../backend/app/routers/pipeline.py)). This section is the SOP for using them to produce and maintain the catalog.

### 8.1 Initial build (one-time, ~6-9 weeks)

Phase B (MVP funnel — 2-3 weeks):
1. **Pipeline → Settings** — set `max_topics_per_discovery=15`, `auto_approve_topics=false`, generation models = current free chain (Gemini → Groq → Cerebras → Mistral → Sambanova). Set `discovery_focus="role_shaped"` (after COURSE-01 ships).
2. **Pipeline → Run Discovery** — twice. Once with "2026 AI hiring roles" focus, once with "viral AI capstone projects" focus. Each run yields ~10-15 topics; you'll approve a small fraction.
3. **Pipeline → Topics → Triage queue** — approve only topics matching the canonical 8 flagships / 22 shorts / 8 micros / 3 sprints in §5.3. Reject everything else (do not let auto-discovery dictate the catalog — *you* dictate, discovery surfaces options).
4. **For each Tier 1 flagship** (AI Foundations, LLM Engineer):
   - **Topics → Claude Prompt Generator** ([pipeline.py:410](../backend/app/routers/pipeline.py#L410)) → copy generated prompt → paste into Claude Max chat (Opus 4.7) per [feedback_manual_template_workflow.md](../../.claude/projects/e--code-AIExpert/memory/feedback_manual_template_workflow.md).
   - Receive JSON template back → **Topics → Upload Manual Template** ([pipeline.py:621](../backend/app/routers/pipeline.py#L621)).
   - **Admin → Templates → /admin/templates/{key}** — review against the COURSE-03 capstone rubric (not just heuristic score). Reject if capstone is generic / un-shippable / not AI-evaluatable.
   - **Pipeline → Refine-one** ([pipeline.py:209](../backend/app/routers/pipeline.py#L209)) for surgical fixes.
   - **Publish** only when: heuristic score ≥ 90 AND capstone passes COURSE-03 rubric AND week 1 ships a working artifact AND first resource-per-week is the "if-only-one-thing" pick.
5. **COURSE-06 capstone showcase** + **COURSE-07 quiz funnel** + **COURSE-08 cert bundle** — these wire the *visible* viral surface area.

Phase C (viral hooks — 2 weeks): COURSE-09 sprint infra + first sprint, COURSE-10 micro infra + first 5 micros, COURSE-11 streak, COURSE-13 spaced-retention email, COURSE-14 showcase index.

Phase D-E (catalog fill — 4 weeks): remaining flagships (manual Opus per #4 above), 22 shorts via parallel Sonnet generation (COURSE-20 — fan out one Sonnet per short, all in one message, ~22 minutes).

### 8.2 Weekly cadence (recurring, ~30 min/week)

| Day | Admin action | Surface | Expected result |
|---|---|---|---|
| Monday | Scan **Pipeline → AI Usage** ([pipeline.py:1959](../backend/app/routers/pipeline.py#L1959)) for spend/cost alerts | Dashboard | No alerts → continue. Alert → investigate provider |
| Monday | Scan **Pipeline → Topics** for new pending discoveries (auto-discovery runs weekly) | Topics queue | 0-5 new pending. Triage: approve, reject, or "hold for tech-shift review" |
| Tuesday | Review **Admin → Templates → Quality** ([pipeline.py:792](../backend/app/routers/pipeline.py#L792)) for any newly-generated short | Quality scores | All ≥ 80 published; <80 sent back to refine-one |
| Wednesday | Skim **Course quality dashboard** (COURSE-25 once shipped) — completion / dropout points / capstone-ship rate per course | Dashboard | Flag any course with <50% week-1 completion → likely week-1 needs polish |
| Friday | Scan **Admin → Proposals** for content-refresh suggestions | Proposals | Auto-apply to shorts if score regression < 5pts; queue for manual review on flagships |

If nothing in queue → 5 min done. If proposals queue is large → schedule 1hr session.

### 8.3 Quarterly refresh (recurring, ~1 day/quarter)

Triggered by **Pipeline → Run Refresh** ([pipeline.py:250](../backend/app/routers/pipeline.py#L250)) — checks link health, currency, generates **proposals**.

1. **Admin → Proposals** — queue of "topic X has new SOTA / framework Y deprecated / link Z dead."
2. **For each proposal**:
   - **Short / micro / sprint** → if score regression < 5pts after auto-applying the proposal, auto-apply (admin still reviews diff).
   - **Flagship** → manual review always. Affected flagship may need a v1.X bump (see §9.4 versioning).
3. **Run Refresh again on flagships** to catch second-order link rot.
4. **Update the canonical 41-course list in §5.3** if any course is added / merged / deprecated this quarter.
5. **Append entry to Change log** at the bottom.

### 8.4 Tech-shift response (event-driven, ad-hoc)

When a paradigm-shift event occurs (per §9.2 trigger taxonomy), step out of the weekly cadence and follow §9.3 update playbook directly. Most months have zero such events; some quarters have one.

### 8.5 Decision tree — discovery → approve → generate → publish

```
    [ Auto-discovery surfaces topic ]
                |
                v
    Pipeline → Topics (triage queue, status=pending)
                |
                v
    [ Admin reviews ]
       |          |
       v          v
   reject     approve
       |          |
       v          v
   archived   [ Is it a flagship? ]
                  |          |
                  v          v
                yes          no (short/micro/sprint)
                  |          |
                  v          v
        Manual Opus     Pipeline → Run Generation
        paste-upload     (auto-pipeline: Gen → Score
                          → Review → Refine → Validate)
                  |          |
                  +----+-----+
                       |
                       v
              Admin → Templates
              (quality score + capstone-rubric review)
                       |
                       v
                [ Score ≥ 80 AND
                  rubric pass AND
                  week-1 ships? ]
                  |          |
                  v          v
                 no         yes
                  |          |
                  v          v
            Pipeline      Publish (status=published)
            → Refine-one      |
                  |          v
                  +-->  Templates → quarterly refresh
                              loop forever
```

### 8.6 Quality gates per format

| Format | Heuristic score floor | AI review dimensions floor | Capstone rubric | Week-1-ships check | Approver |
|---|---:|---|---|---|---|
| Micro 1-2hr | ≥ 75 | n/a (review skipped) | Single artifact at end | n/a | Auto-publish if floor met |
| Sprint 5-7d | ≥ 85 | All ≥ 7 | Day-7 public ship required | Day 1 ships ≥ "hello world" artifact | Admin manual review |
| Short 1-2wk | ≥ 80 | All ≥ 7 | Optional | Week 1 has 1 deliverable | Auto-publish if all met |
| Flagship 4-12wk | ≥ 90 | All ≥ 8 | **Required, AI-evaluatable** | Week 1 ships a working artifact | Admin manual review + COURSE-03 rubric pass |

### 8.7 When to use Opus manual vs auto-pipeline

| Course type | Use auto-pipeline (free chain) | Use manual Opus (paste-upload) |
|---|---|---|
| Micro 1-2hr | ✅ default | only on regen after rubric fail |
| Sprint 5-7d | ❌ first sprint of each flagship lineage | ✅ first sprint authored manually; auto-pipeline used for variant sprints |
| Short 1-2wk | ✅ default; parallel Sonnet for batch | only on rubric fail or refine-one regression |
| **Flagship** | ❌ never as primary | ✅ **always** — Opus editorial is non-negotiable per [feedback_opus_for_editorial.md](../../.claude/projects/e--code-AIExpert/memory/feedback_opus_for_editorial.md) |

## 9. Adapting to changing AI tech

The hardest sustainability problem: AI moves fast, courses go stale. This section is the operating manual for staying current without burning admin time on every minor release.

### 9.1 Signal sources to monitor

The auto-discovery service ([topic_discovery.py](../backend/app/services/topic_discovery.py)) already pulls from web research. Augment with these explicit watchlists (added to discovery prompt as `evidence_sources` priors):

| Source | What to extract | Cadence |
|---|---|---|
| arXiv (cs.LG, cs.CL, cs.CV) — top papers by Twitter/X velocity | New techniques crossing 1000-like threshold | Weekly |
| HuggingFace trending models | New base models / fine-tuning techniques | Weekly |
| GitHub trending Python with `ai`/`ml`/`llm` topics | New OSS frameworks | Weekly |
| Job postings via your own [jobs_ingest](../backend/app/services/jobs_ingest.py) data | Skill-language drift in 2026 hiring | Monthly |
| Andrew Ng's "The Batch" / TLDR AI / AI News | Synthesized signal of what matters | Weekly |
| OpenAI / Anthropic / Google / Meta release notes | Model capabilities + API changes | Per-release |
| LangChain / LlamaIndex / DSPy changelogs | Framework breaking changes | Per-release |
| Stanford CS229 / CS224N / CS336 / Berkeley CS294 syllabi | Academic curriculum drift | Per-quarter (matches existing quarterly_sync) |

These watchlists feed into the existing **Pipeline → Run Discovery** ([pipeline.py:170](../backend/app/routers/pipeline.py#L170)) — no new infrastructure needed beyond `discovery_focus="tech_shift"` (COURSE-01) and lightweight watchlist priors in [discover_topics.txt](../backend/app/prompts/discover_topics.txt).

### 9.2 Trigger taxonomy — classifying tech shifts

Every signal from §9.1 gets classified into one of four tiers. The triage decision lives in **Tech-shift triage admin page** (COURSE-22).

| Tier | What | Frequency | Examples (historical) | Action |
|---|---|---|---|---|
| **T1 — Paradigm shift** | Reshapes what "doing AI" means | 1-2 / year | Transformers (2017); GPT-3 (2020); ChatGPT (2022); o1/o3 reasoning (2024) | Rewrite affected flagships from scratch (manual Opus). Major version bump (v2.0). |
| **T2 — Major release** | New SOTA model, new framework, new technique with adoption velocity | ~quarterly | Claude 3.5 Sonnet release; LangGraph 0.1; DSPy adoption; Llama 3.1 | Update affected weeks; new short module if technique is standalone. Minor version bump (v1.X). |
| **T3 — Minor update** | API version bump, prompting trick, library update | Monthly | Tokenizer change; new feature flag; minor SDK release | Auto-applied to shorts via proposals; manual review on flagships. Patch version (v1.0.X). |
| **T4 — Noise** | Big on Twitter for a week, then dies | Constant | Most "this changes everything" claims | Ignore. Let proposals queue archive them. |

**Classifier:** the auto-discovery already produces a `confidence_score` per topic ([topic_discovery.py:54](../backend/app/services/topic_discovery.py#L54)). COURSE-22 adds a `tier_classification` (T1-T4) via a one-shot prompt to the same Gemini/Groq chain — costs ~$0/run, runs as part of weekly discovery.

### 9.3 Update playbook by tier

**T1 — Paradigm shift (rare, high-stakes):**
1. Stop weekly cadence. Schedule 1-2 sessions in the week of the event.
2. Identify affected flagships (usually 2-4 of the 8).
3. For each: open a *new* template version (v2.0), do not edit the live one. Manual Opus authoring per §8.7.
4. Ship in parallel — all affected v2.0 flagships in one cohort week.
5. Notify enrolled users via email (existing Brevo infra) — opt-in to upgrade. Per [project_auto_curriculum.md Phase 5](../../.claude/projects/e--code-AIExpert/memory/project_auto_curriculum.md), version pinning means current learners keep the old plan unless they opt in.
6. Append RCA-style entry to Change log: trigger event → affected flagships → new version → opt-in window.
7. **Codex:rescue gate** if the new version touches AI-classifier prompts (per [global CLAUDE.md hard rules](../../.claude/CLAUDE.md)).

**T2 — Major release (~quarterly):**
1. Auto-discovery surfaces it within 1 week. Triage in normal weekly cadence.
2. If affected flagship: minor version bump (v1.X) — generate diff via **Pipeline → Refine-one** scoped to affected weeks. Review in admin. Publish.
3. If standalone-worthy: spawn new short module. Use auto-pipeline.
4. Update §5.3 canonical course list if catalog count changes.
5. Single Change-log entry.

**T3 — Minor update (monthly):**
1. Surfaces via quarterly **Pipeline → Run Refresh**, captured in **Admin → Proposals**.
2. **Auto-apply** if: (a) target is a short / micro / sprint AND (b) score regression < 5pts. Admin reviews the diff post-hoc.
3. Manual review otherwise.
4. No Change-log entry unless multiple T3s bundled.

**T4 — Noise:**
1. Auto-discovery may surface it as `pending`. Admin rejects in weekly triage.
2. After 30 days, archive automatically (existing lifecycle).

### 9.4 Versioning strategy

| Version delta | Semantics | Triggered by | Enrolled-user behavior |
|---|---|---|---|
| Major (v1.0 → v2.0) | Course rewritten; new month structure | T1 paradigm shift | Pinned to v1.0; opt-in upgrade prompt sent via email |
| Minor (v1.0 → v1.1) | Content updates within same structure | T2 major release | Pinned to v1.0; in-app banner "v1.1 available, upgrade?" |
| Patch (v1.0 → v1.0.1) | Link health, typos, single-resource swap | T3 / quarterly refresh | Auto-applied; no notice |

Implementation: existing template-version pinning per [project_auto_curriculum.md Phase 5](../../.claude/projects/e--code-AIExpert/memory/project_auto_curriculum.md). COURSE-23 adds the admin UI to view version history per template.

### 9.5 Deprecation criteria

Mark a course `deprecated` when *any* of:

- Underlying tech is dead (e.g. "Build with GPT-3" when GPT-3 is sunset).
- Better course exists in catalog (e.g. shipping new "GenAI Engineer 2026" deprecates "GenAI Engineer 2025").
- Completion rate < 5% for 6 consecutive months (signal of misfit; visible via COURSE-25 quality dashboard).
- Capstone-ship rate < 15% for 3 consecutive months (signal of broken pedagogy, not just niche topic).

Deprecated semantics:
- Hidden from course catalog for new enrollees.
- Current enrollees retain access; banner suggests successor course.
- After 12 months with zero active enrollees → archive (move JSON out of `templates/`, keep DB row for cert verification).

COURSE-24 wires this flow.

### 9.6 New-topic spawn criteria

A new course is spawned (vs. updating an existing one) when:

- Topic has no overlap with any existing course's stated learning outcomes.
- Topic appears in ≥ 2 of: hiring-language drift, top-arxiv velocity, framework adoption.
- Auto-discovery confidence_score ≥ 80 AND tier ∈ {T1, T2}.

Default: short module (1-2wk). Promote to flagship only if topic has ≥ 6 weeks of standalone material AND ≥ 1 hiring role aligned.

## 10. Phased implementation — COURSE-00..COURSE-28

The full sequenced backlog. Each task has acceptance criteria. Status tracked in §0.2 board above.

### Phase A — Foundation (1 week)

#### COURSE-00 — Author this strategy doc + capstone rubrics + admin SOP
- [ ] This file at `docs/COURSES.md` (~700 lines)
- [ ] Memory pointer at `~/.claude/projects/e--code-AIExpert/memory/reference_course_plan.md`
- [ ] Single-line index entry in `MEMORY.md`
- [ ] Capstone rubrics for the 8 flagships drafted in §13 of this doc (placeholder section — flesh out in COURSE-04 / COURSE-05 / COURSE-15..COURSE-19)
- **AC:** Doc exists, status board renders correctly, memory loads on next session's Phase 0.

#### COURSE-00.5 — Add "Roadmap" to top nav + footer
- [ ] Edit [frontend/nav.js](../frontend/nav.js) topnav-links — insert `<a href="/roadmap">Roadmap</a>` between Home and Blog (Roadmap is the primary product; reads as Product → Catalog → Marketing → Adjacent-product)
- [ ] Active-class logic mirrors `/blog` and `/jobs` patterns: `path === '/roadmap' || path.startsWith('/roadmap/')`
- [ ] Footer (line ~170 of nav.js): add `<a href="/roadmap" class="ftr-link">Roadmap</a>` alongside Blog and Jobs
- [ ] No backend change — `/roadmap` hub already exists from [SEO-24](SEO.md) (shipped 2026-04-24)
- [ ] **Tradeoff:** name is "Roadmap" not "Courses" — preserves existing URL/SEO equity (~36 internal links from SEO-20, ItemList JSON-LD, sitemap entries) and "AI roadmap" has higher search volume than "AI courses" per the duration-research conversation. Page H1 may become "AI Learning Roadmap — Browse Courses" to surface both terms.
- **AC:** Roadmap appears in top nav and footer on all pages; clicking navigates to `/roadmap`; active state highlights when on `/roadmap` or any `/roadmap/{track}` sub-page; no regression on existing nav. Verify on Home, Blog, Jobs, /admin, and /roadmap pages.

#### COURSE-01 — Add `discovery_focus` param + role-shaped + viral-shaped seed prompts
- [ ] Add `discovery_focus: Optional[Literal["role_shaped", "viral_shaped", "tech_shift", "general"]]` param to `discover_trending_topics()` in [topic_discovery.py](../backend/app/services/topic_discovery.py)
- [ ] Three prompt variants in [discover_topics.txt](../backend/app/prompts/discover_topics.txt) — base prompt + 3 focus appendices
- [ ] **Pipeline → Run Discovery** UI gets a `focus` dropdown
- **AC:** Running with `focus=role_shaped` produces topics tagged with hiring role mappings; `focus=viral_shaped` produces capstone-project topics; `focus=tech_shift` includes paradigm-shift signals from §9.1 watchlist.

#### COURSE-02 — Format-specific generate prompts + resource `type` + per-column primary
- [ ] `backend/app/prompts/generate_curriculum_micro.txt` — single-sitting structure, 3 segments, 1 artifact at end
- [ ] `backend/app/prompts/generate_curriculum_sprint.txt` — day-keyed (not week-keyed), 5-7 days, 30-60 min/day load, day-7 capstone, day-1-ships requirement
- [ ] [generate_curriculum.txt](../backend/app/prompts/generate_curriculum.txt) resource schema updated: each resource gains `type: "video" | "non-video"` and `primary: bool`. Mix per week stays at 6 (3 video + 3 non-video, already enforced) but now **explicitly typed** in JSON, not heuristically inferred at render time.
- [ ] **Per-column primary**: each week has exactly 2 resources marked `primary: true` — one video (the "if-only-one-video-watch-this") and one non-video (the "if-only-one-thing-read-this"). Other 4 are `primary: false`. Eliminates choice paralysis at *both* media types, not just one global pick.
- [ ] [PlanTemplate Pydantic schema](../backend/app/curriculum/loader.py) updated; [PLAN_TEMPLATE_SCHEMA](../backend/app/ai/schemas.py) Gemini structured-output schema updated. Validator rejects weeks without exactly (3 video + 3 non-video) and exactly (1 primary video + 1 primary non-video).
- [ ] `curriculum_generator.generate_curriculum()` accepts `format: Literal["flagship","short","sprint","micro"]` and selects the right prompt.
- [ ] Backfill script: existing published templates need `type` field added. Heuristic: URL contains `youtube.com|youtu.be|vimeo.com|youtube-nocookie.com` → video; else non-video. First resource per type → `primary: true`. Idempotent.
- [ ] **Top-3-best selection criteria baked into the prompt**: each week's 3 video and 3 non-video resources must be selected against the quality bar from §2 constraint #11 — authority (prefer §14 allowlist sources), currency (≤24 months for AI topics; older only if canonical), practical applicability (code/lab/exercise required for at least 2 of 3 in each type), pedagogical fit (level-appropriate). Prompt explicitly references the §14 allowlists as preferred sources and instructs the model to reject Medium/dev.to/random-blog picks unless no allowlist alternative exists.
- [ ] **"Resource Quality" dimension added to AI review** ([review_curriculum.txt](../backend/app/prompts/review_curriculum.txt)) — scored 1-10. Penalizes: stale URLs, non-allowlist sources where allowlist alternative exists, resources without code/exercise where applicable, choice paralysis (more than one resource doing essentially the same thing). Floor 7/10 to publish.
- [ ] **Heuristic Resource Quality scorer** added to [quality_scorer.py](../backend/app/services/quality_scorer.py) — checks: (a) ≥ 60% of resources from §14 allowlist domains, (b) all URLs return HTTP 200 (existing link-health check), (c) no duplicates within a week, (d) primary-of-type is the highest-authority pick within its column.
- **AC:** Generating a micro produces a 3-segment 1-2hr template. Generating a sprint produces a day-keyed 5-7d template. Existing flagship/short generation produces (3 video + 3 non-video) per week with (1 primary video + 1 primary non-video) marked AND ≥60% of resources from the §14 allowlists. Backfill ran successfully on all existing templates. Schema rejects malformed mixes. AI review's Resource Quality dimension scores ≥ 7/10 on a sample-published flagship.

#### COURSE-03 — Capstone-rubric review checklist
- [ ] New rubric section in admin Templates UI for flagship/sprint courses: "Capstone rubric pass/fail" checklist before publish
- [ ] Rubric criteria (per format):
  - **Flagship**: capstone is a deployed thing OR public repo OR published artifact; AI-evaluatable via existing [evaluate.py](../backend/app/routers/evaluate.py); week 1 ships a working artifact; one primary resource per week marked.
  - **Sprint**: day-7 public ship is required; day 1 ships ≥ "hello world" artifact; daily load ≤ 60 min.
  - **Short / micro**: single artifact at end; not "demonstrate understanding of X."
- [ ] Add rubric-pass dimension to [quality_scorer.py](../backend/app/services/quality_scorer.py) (heuristic, no AI cost)
- **AC:** Generating a course without a concrete capstone fails the rubric and cannot be published; admin sees clear pass/fail per criterion.

### Phase B — MVP funnel (2-3 weeks)

#### COURSE-04 — Build "AI Foundations" 6-week beginner flagship
- [ ] Manual Opus authoring via Topics → Claude Prompt Generator → paste-upload
- [ ] 6 weeks, ~10-12 hr/wk per [generate_curriculum.txt](../backend/app/prompts/generate_curriculum.txt) beginner load
- [ ] Capstone: ship one working AI thing (e.g. a sentiment-classifier deployed on HuggingFace Spaces) by week 6
- [ ] Ends with a *decision moment*: "you now know enough to pick LLM Engineer / AI Product Builder / ML Engineer"
- [ ] Week 1 ships a working notebook (not just "explore Python")
- **AC:** Published. Rubric passes. Quality score ≥ 90.

#### COURSE-05 — Build "LLM Engineer" 12-week default flagship
- [ ] Manual Opus authoring
- [ ] 12 weeks, monthly capstone gates (each month-end produces a shippable artifact)
- [ ] Final capstone: deployed RAG+agents app with evals, traced in production
- [ ] Marketed as the platform's default flagship; quiz-funnel default recommendation for "I want to build with LLMs"
- **AC:** Published. Rubric passes. Quality score ≥ 90.

#### COURSE-06 — Capstone showcase route + page
- [ ] Route: `/showcase/{username}/{slug}` — server-rendered (Jinja), public, BreadcrumbList + Article JSON-LD per [SEO.md](SEO.md)
- [ ] Surfaces: AI evaluation score, learner's GitHub repo link, course they finished, learner's first name + LinkedIn (if linked)
- [ ] Privacy: opt-in via `user.public_profile` + per-capstone `is_showcased` flag
- [ ] Sitemap addition (`sitemap-showcase.xml`)
- [ ] [nginx.conf](../nginx.conf) allowlist update per [feedback_nginx_allowlist_on_new_routes.md](../../.claude/projects/e--code-AIExpert/memory/feedback_nginx_allowlist_on_new_routes.md)
- **AC:** Published capstone renders at the URL; appears in sitemap; privacy default opt-out.

#### COURSE-07 — "What AI track is right for you?" quiz funnel
- [ ] Extends [SEO-26](SEO.md) (already on SEO backlog as `/start` interactive quiz)
- [ ] Quiz: 8-10 questions on goals / time available / coding background / target outcome
- [ ] Outputs: recommended flagship + 2 paired shorts + LinkedIn-shareable result card (OG image via existing route)
- [ ] Persists outcome to `quiz_outcomes` table (Alembic migration — load-bearing per [CLAUDE.md §8](../CLAUDE.md), worktree + codex:rescue review)
- **AC:** End-to-end quiz works; recommended track converts ≥ 30% to enrollment within 7 days.

#### COURSE-08 — Specialization-bundle certificate
- [ ] Extends [project_certificate_system.md](../../.claude/projects/e--code-AIExpert/memory/project_certificate_system.md) Steps 2-8
- [ ] Bundle: flagship + 4 paired shorts → unified certificate
- [ ] LinkedIn share intent integrates Google's `EducationalOccupationalCredential` schema (per [SEO-12](SEO.md))
- [ ] Certificate page (`/verify/{id}`) shows the bundle, not just the flagship
- **AC:** Completing flagship + 4 shorts auto-issues bundle cert; LinkedIn share renders correctly.

### Phase C — Viral hooks (2 weeks)

#### COURSE-09 — Sprint format infra + first sprint "LLM Engineer Quickstart 7d"
- [ ] Sprint template schema (sibling of `PlanTemplate`) — day-keyed, 5-7 days, daily load 30-60min, day-7 capstone
- [ ] Generation prompt per COURSE-02
- [ ] First sprint: "LLM Engineer Quickstart 7d" — ship a deployed RAG agent in 7 days
- [ ] Day-1 roll call public list + day-7 ships public list (uses showcase infra from COURSE-06)
- [ ] Day-0 prep email (existing Brevo)
- **AC:** Sprint runs end-to-end with one test cohort; day-1 roll call + day-7 showcase work; daily reminder emails trigger.

#### COURSE-10 — Micro format infra + first 5 micros
- [ ] Micro template schema — single-sitting, 3-5 segments, 1 artifact, no week structure
- [ ] Generation prompt per COURSE-02 — auto-pipeline produces these (no manual Opus needed for micros)
- [ ] First 5: Build a RAG app in 90min · Ship an LLM agent in 2hr · Deploy your first model in 60min · Build your first chatbot in 60min · Prompt engineering in 90min
- [ ] Mobile-first UI: micros render in single-scroll page, not week cards
- **AC:** All 5 micros published, ≥ 60% completion among test users.

#### COURSE-11 — Streak counter
- [ ] User table: `streak_days`, `last_active_date`
- [ ] Updated on any progress tick
- [ ] Displayed: profile page (always), week cards (signed-in), public showcase (opt-in)
- **AC:** Tick on day N, day N+1 → streak = 2; skip a day → streak resets to 1.

#### COURSE-12 — 30-day LLM app challenge
- [ ] Sprint variant: 30 days, daily ship, weekend rest days (Mon-Fri × 6 weeks)
- [ ] Each day: build a different LLM app (templates pre-seeded; learners can customize)
- [ ] Public day-N ships gallery (uses showcase infra)
- [ ] Email digest weekly: "Day 1-5 ships from cohort"
- **AC:** First cohort runs; ≥ 25% reach day 30; ≥ 50% reach day 7.

#### COURSE-13 — Spaced-retention email loop
- [ ] Trigger: micro completion (T+0)
- [ ] Email at T+3d, T+7d, T+21d — each with one retrieval question + a "next micro" recommendation
- [ ] Trigger: sprint completion → emails at T+7d, T+30d
- [ ] Existing Brevo/Resend infra; one new template per loop step
- **AC:** Click-through on +3d email ≥ 25%; conversion to "next micro" enrollment ≥ 15%.

#### COURSE-14 — Public capstone gallery `/showcase` index
- [ ] Index page listing all opt-in capstones, filterable by course / skill / level
- [ ] Pagination, ItemList JSON-LD per [SEO-24](SEO.md) pattern
- [ ] Sitemap entry
- **AC:** Index renders; filtering works; sitemap updated.

### Phase D — Tier 2 flagships (2 weeks)

#### COURSE-15 — Build "AI Product Builder" 8-week flagship
- [ ] Manual Opus authoring
- [ ] Audience: PMs / non-ML engineers / designers — code-light, concept-heavy, ship 5 LLM apps
- [ ] Capstone: deploy 5 distinct LLM apps with shared eval framework
- **AC:** Published; rubric pass; ≥ 85 quality.

#### COURSE-16 — Build "ML Engineer" 12-week flagship
- [ ] Manual Opus authoring
- [ ] Classical ML → DL → MLOps progression
- [ ] Capstone: productionize a model end-to-end (data → training → serving → monitoring)
- **AC:** Published; rubric pass; ≥ 90 quality.

#### COURSE-17 — Build "GenAI Engineer" 12-week flagship (depth track)
- [ ] Manual Opus authoring
- [ ] Deeper than LLM Engineer — fine-tuning, evals, multi-modal, agent frameworks
- [ ] Capstone: multi-modal agent ecosystem with evals
- **AC:** Published; rubric pass; ≥ 90 quality.

#### COURSE-18 — Build "MLOps" 8-week flagship
- [ ] Manual Opus authoring
- [ ] Capstone: deploy a model with monitoring + retraining pipeline + cost tracking
- **AC:** Published; rubric pass; ≥ 85 quality.

### Phase E — Full catalog (2 weeks)

#### COURSE-19 — Advanced flagships: LLM Internals/Training + AI Research
- [ ] Both manual Opus authoring
- [ ] LLM Internals: Karpathy zero-to-hero style — build micrograd, makemore, nanoGPT from scratch
- [ ] AI Research: read papers, reproduce results, write a paper-style writeup
- **AC:** Both published; rubrics pass; ≥ 90 quality.

#### COURSE-20 — Generate 22 short modules in parallel Sonnet batches
- [ ] Fan out one Sonnet subagent per short, all in one message (per [orchestration playbook](../../.claude/CLAUDE.md))
- [ ] Each subagent receives: topic name + level + COURSE-03 rubric + generate_curriculum.txt
- [ ] Heuristic-only quality gate (≥ 80) — admin reviews quality table, not each course
- [ ] Auto-publish if all gates pass
- **AC:** All 22 shorts published within one session.

#### COURSE-21 — Course-discovery page redesign
- [ ] 40-course catalog cannot fit existing plan-picker UI
- [ ] New: `/courses` page with filters (level / format / hiring role / time available)
- [ ] Recommend top 3 based on quiz outcome (COURSE-07) if available
- [ ] Replaces 3mo/6mo/12mo plan picker as default; existing picker becomes "Custom plan" mode
- **AC:** Catalog renders, filters work, recommend logic works.

### Phase F — Tech-shift operationalization (1 week)

#### COURSE-22 — Tech-shift triage admin page
- [ ] Surface: pending discoveries with tier classification (T1-T4 per §9.2)
- [ ] One-click reclassify
- [ ] Watchlist signal viewer (top 10 from each source in §9.1)
- [ ] Triggers `/admin/tech-shift/triage` route
- **AC:** Admin can triage a week's signals in ≤ 15 min.

#### COURSE-23 — Course versioning UI
- [ ] Per template, show v1.0 → v1.X version history with diffs
- [ ] Trigger v-bump from admin (manual or auto from refresh)
- [ ] Alembic migration — load-bearing, worktree + codex:rescue
- **AC:** Version history shows for any template; diffs render.

#### COURSE-24 — Course deprecation flow
- [ ] Admin can mark course `deprecated`
- [ ] Hide from new enrollees; banner for current
- [ ] After 12 months no active enrollees → archive
- [ ] Alembic migration if `status` enum needs `deprecated` / `archived` values
- **AC:** Deprecation hides from picker; current learners see banner; archived courses removed from catalog APIs.

#### COURSE-25 — Course quality dashboard
- [ ] Per course: % learners who started, % who completed week 1, % who completed mid-point capstone, % who shipped final capstone, average time-to-complete
- [ ] Dropout-point heatmap: which week loses the most learners?
- [ ] Auto-flag any course with < 50% week-1 completion
- **AC:** Dashboard renders; heatmap shows real data; flag fires correctly.

#### COURSE-26 — Weekly "what's new in AI" digest
- [ ] Auto-generated weekly email per active learner
- [ ] Content: top 3 signals from §9.1 watchlist + how they affect learner's enrolled course
- [ ] Generated via existing AI prompt chain
- **AC:** Email sends; click-through ≥ 20%.

#### COURSE-27 — Cohort mode opt-in
- [ ] Per flagship, admin can spawn a cohort with start/end dates
- [ ] Learners opt-in to a cohort; deadlines enforced (Slack-style — late warning, not blocking)
- [ ] Public day-7 / week-4 / week-12 roll calls
- **AC:** Cohort runs; opt-in completion ≥ 1.5× solo baseline.

#### COURSE-28 — Format-aware completion analytics
- [ ] Funnel: micro completion → sprint enrollment → flagship enrollment → capstone ship → cert issued
- [ ] Per-format completion-rate tracking
- [ ] Visible on COURSE-25 dashboard
- **AC:** Funnel populates with real data; conversion rates visible.

#### COURSE-29 — 2-column resource rendering on week cards
- [ ] Each week-card resources section renders as **two columns**: left = video resources (3), right = non-video resources (3). Driven by the `type` field landed in COURSE-02.
- [ ] Within each column, the `primary: true` resource renders at the top with a visual emphasis (e.g. larger title, "Recommended" badge, gold accent matching brand). Other 2 secondary resources render below.
- [ ] Column headers: "🎥 Watch" and "📖 Read & Build" (use icons via Unicode or inline SVG to keep [CLAUDE.md §5 rule 8](../CLAUDE.md#L82-L83) standalone-from-disk constraint).
- [ ] Mobile: columns stack (video on top, non-video below) at ≤720px breakpoint. Per [feedback memory on jobs mobile-first](../../.claude/projects/e--code-AIExpert/memory/MEMORY.md), mobile is the primary surface for course discovery.
- [ ] Resource hours total per column visible (e.g. "🎥 Watch — 8 hrs total" / "📖 Read & Build — 8 hrs total") so learners see the time split.
- [ ] Apply across: existing tracker week cards in [frontend/index.html](../frontend/index.html), public roadmap track pages ([backend/app/routers/track_pages.py](../backend/app/routers/track_pages.py)), any future flagship/sprint/short course pages.
- [ ] Sprint variant: per-day instead of per-week — same 2-column structure, daily 1 video + 1 non-video primary.
- [ ] Micro variant: NOT applicable (single sitting, 3-5 segments — render linearly).
- [ ] CSS lives in shared [frontend/nav.css](../frontend/nav.css) (or new `course-card.css` if it grows large). No build step.
- [ ] Backwards-compatible: weeks without `type` field (pre-COURSE-02-backfill) render in legacy single-column layout. After backfill (COURSE-02 AC), all weeks render 2-column.
- **AC:** Open any week card → see two labeled columns with primary resource emphasized at top of each. Mobile: columns stack cleanly, no horizontal scroll. Test on Home (tracker), `/roadmap/{track}`, and a flagship course page. Verify with at least one course where `type` is missing (legacy fallback) and one fully backfilled.

## 11. Metrics & KPIs

Per-format completion targets and funnel conversion targets summarized in §1. Tracked weekly in COURSE-25 dashboard once shipped. Annual review against §1 targets at quarterly refresh (§8.3).

## 12. Open questions

1. **Cohort mode (COURSE-27) — required for Phase B or deferrable?** Cohort accountability is the highest-completion lever in research, but adds operational load (running cohorts, moderating roll calls). Defer to Phase F unless Phase B retention metrics fall below targets.
2. **Pricing inflection** — platform is currently 100% free. If certificates + bundles drive demand, is there a paid tier? (Out of scope for this plan; flag for separate strategic discussion.)
3. **Live instructor ingestion** — should we wire course shells that point to YouTube live-stream office hours, or stay fully self-paced? (Defer; not part of viral mechanics core.)
4. **Multi-language support** — substantial market in Hindi / Spanish / Mandarin, but doubles authoring cost. Defer until English catalog is at 25+ courses.

## 13. Capstone rubric appendix (placeholder — fill in COURSE-04..COURSE-19)

For each flagship, the rubric is a 6-point checklist that gates publication and is enforced by COURSE-03 admin UI. Filled in as each flagship ships:

- **COURSE-04 AI Foundations capstone**: TBD (placeholder — to author with Opus during COURSE-04)
- **COURSE-05 LLM Engineer capstone**: TBD
- **COURSE-15 AI Product Builder capstone**: TBD
- **COURSE-16 ML Engineer capstone**: TBD
- **COURSE-17 GenAI Engineer capstone**: TBD
- **COURSE-18 MLOps capstone**: TBD
- **COURSE-19 LLM Internals / AI Research capstones**: TBD

Each rubric must specify: (1) artifact type (deployed app / public repo / published writeup), (2) AI-evaluatable criteria via existing [evaluate.py](../backend/app/routers/evaluate.py) prompt, (3) minimum complexity / scope, (4) exclusions ("not just a tutorial fork"), (5) public-share requirement, (6) cert-eligibility threshold.

**COURSE-03 capstone rubric — week-level resource quality gate (applies to all flagship / short / sprint courses):**

Beyond the per-flagship capstone criteria above, every week of every course must pass these resource-quality gates before publish (per §2 constraint #11):

- ✅ Exactly 3 video resources tagged `type: "video"` AND exactly 3 non-video tagged `type: "non-video"` (sprint courses: per-day 1-of-each instead of per-week 3-of-each).
- ✅ Exactly 1 `primary: true` per type. Primary must be the highest-authority pick from that column (prefer §14 allowlist).
- ✅ ≥ 60% of all resources sourced from the §14 allowlists. Free pass for canonical foundational picks (Goodfellow Deep Learning book, Bishop PRML, Russell-Norvig AIMA) even if not strictly on the allowlist.
- ✅ All URLs return HTTP 200 at time of publish (existing link-health check).
- ✅ No two resources in the same week teach essentially the same thing (heuristic: title overlap > 60% triggers manual review).
- ✅ For AI/ML topics: published / updated within 24 months unless explicitly canonical. Stale resources auto-flagged in admin Templates UI.

Failing any gate blocks publish; admin sees the specific failed gate in the Templates UI.

## 14. Trusted-source allowlist for course resources

This is the curated allowlist of domains/channels considered high-authority sources for course resources. Mirrors the [SEO-25 trusted_sources.json](../backend/data/trusted_sources.json) pattern — same suffix-matching logic (`endswith` not `contains`, to reject `fakemeta.com` while accepting `meta.com`).

The generation prompt ([generate_curriculum.txt](../backend/app/prompts/generate_curriculum.txt) after COURSE-02) instructs the model to **prefer these sources** and **reject Medium/dev.to/random blog posts** unless no allowlist alternative covers the subtopic. The heuristic scorer in [quality_scorer.py](../backend/app/services/quality_scorer.py) gates on ≥ 60% of resources matching the allowlist.

Implementation: a new `backend/data/course_resource_sources.json` file with same shape as `trusted_sources.json` — categories + domains/channels + canonical names. Backfilled from this list as part of COURSE-02.

### 14.1 Video resources — trusted channels / instructors

| Category | Channel / Instructor | URL pattern |
|---|---|---|
| Foundational explainers | 3Blue1Brown | `youtube.com/@3blue1brown` |
| Foundational explainers | StatQuest with Josh Starmer | `youtube.com/@statquest` |
| Build-from-scratch (highest authority) | Andrej Karpathy | `youtube.com/@AndrejKarpathy` |
| Paper walkthroughs | Yannic Kilcher | `youtube.com/@YannicKilcher` |
| Research summaries | Two Minute Papers | `youtube.com/@TwoMinutePapers` |
| University courses | Stanford Online | `youtube.com/@stanfordonline` (CS229, CS224N, CS231N, CS336) |
| University courses | MIT OpenCourseWare | `youtube.com/@mitocw` (6.S191, 6.034) |
| University courses | UC Berkeley CS294 | university channels |
| Research labs | DeepMind | `youtube.com/@Google_DeepMind` |
| Research labs | OpenAI | `youtube.com/@OpenAI` |
| Research labs | Anthropic | `youtube.com/@anthropic-ai` |
| Industry pedagogy | DeepLearning.AI / Andrew Ng | `youtube.com/@Deeplearningai` |
| Industry pedagogy | Hugging Face | `youtube.com/@HuggingFace` |
| Industry pedagogy | fast.ai | `youtube.com/@howardjeremyp` |
| Long-form depth | Lex Fridman (selective — interviews/depth, not introductions) | `youtube.com/@lexfridman` |
| Long-form depth | Computerphile (selective) | `youtube.com/@Computerphile` |
| Live coding (selective) | Sentdex / Two Minute Papers / Outlier (case-by-case) | various |

**Excluded by default** (require explicit override + justification): general-tech YouTubers without AI credentials; bootcamp marketing channels; "10x your AI skills in 10 minutes" content-farm channels; courses behind paywalls when free equivalent exists on allowlist.

### 14.2 Non-video resources — trusted domains / publishers

| Category | Source | URL pattern |
|---|---|---|
| Papers | arXiv | `arxiv.org` |
| Papers | Papers with Code | `paperswithcode.com` |
| Lab / org docs | OpenAI | `openai.com/research`, `platform.openai.com/docs` |
| Lab / org docs | Anthropic | `anthropic.com/research`, `docs.anthropic.com` |
| Lab / org docs | Google DeepMind | `deepmind.google`, `deepmind.com` |
| Lab / org docs | Meta AI | `ai.meta.com` |
| Framework docs | Hugging Face | `huggingface.co/docs`, `huggingface.co/learn` |
| Framework docs | PyTorch | `pytorch.org/docs`, `pytorch.org/tutorials` |
| Framework docs | TensorFlow / JAX | `tensorflow.org`, `jax.readthedocs.io` |
| Framework docs | LangChain | `python.langchain.com` |
| Framework docs | LlamaIndex | `docs.llamaindex.ai` |
| Framework docs | DSPy | `dspy.ai` |
| Editorial / explainers | Distill.pub | `distill.pub` |
| Editorial / explainers | The Gradient | `thegradient.pub` |
| Editorial / explainers | DeepLearning.AI blog | `deeplearning.ai/the-batch` |
| Practitioner blogs | Lilian Weng | `lilianweng.github.io` |
| Practitioner blogs | Sebastian Raschka | `magazine.sebastianraschka.com` |
| Practitioner blogs | Andrej Karpathy | `karpathy.github.io`, `karpathy.medium.com` (Karpathy-authored exception) |
| Practitioner blogs | fast.ai | `fast.ai`, `course.fast.ai` |
| Books (canonical, free PDFs preferred) | Deep Learning (Goodfellow et al.) | `deeplearningbook.org` |
| Books | Pattern Recognition and Machine Learning (Bishop) | when free PDF available |
| Books | AIMA (Russell-Norvig) | when free chapters available |
| Books | fast.ai book | `course.fast.ai` |
| University courses | Stanford CS229/CS224N/CS231N/CS336 | `cs229.stanford.edu`, `web.stanford.edu/class/cs224n`, etc. |
| University courses | MIT OCW | `ocw.mit.edu` |
| University courses | UC Berkeley CS294 / CS285 | university course pages |
| Hands-on platforms | Kaggle Learn | `kaggle.com/learn` |
| Hands-on platforms | Hugging Face Course / Spaces | `huggingface.co/learn`, `huggingface.co/spaces` |
| Hands-on platforms | freeCodeCamp | `freecodecamp.org` (selective — AI/ML curriculum only) |
| Code repositories | High-star GitHub repos | `github.com/{org}` where stars ≥ 5k AND last commit ≤ 12 months |
| Code repositories | nanoGPT, micrograd, makemore (Karpathy) | `github.com/karpathy/*` |

**Excluded by default**: Medium (except Karpathy-authored), dev.to, random WordPress sites, content-farm tutorial sites, paywalled tutorials when free equivalent exists, Stack Overflow answers (use as references only, not primary resources).

### 14.3 Allowlist maintenance

- Added to / removed from in same PR as a course generation that hits an edge case
- Reviewed quarterly during the §8.3 quarterly refresh — sources that have gone stale or paywalled get removed
- New entries require: ≥ 6 months of consistent quality output, ≥ 1 senior practitioner endorsement (admin judgment), no commercial / paywall / SEO-spam pattern
- Tracked changes appended to the change log at the bottom of this doc

## Change log

> Append a single entry per course-related commit. Include date, what changed, and link to commit / PR if applicable.

- **2026-04-25** — COURSE-00 initial authoring of this strategy doc. Status board seeded with all 28 tasks across 6 phases. Capstone rubrics §13 left as placeholders to be filled by COURSE-04..COURSE-19. Memory pointer + MEMORY.md index entry committed alongside this file. Next action: COURSE-01 + COURSE-02 + COURSE-03 (foundation phase) — all three are parallel-safe and unblock Phase B.
- **2026-04-25** — Plan additions in same session: (1) **COURSE-00.5** added — "Roadmap" top-nav + footer link to existing `/roadmap` hub (preserves SEO-24 equity; `/roadmap` URL stays stable). (2) **COURSE-02 expanded** — resources gain explicit `type: "video"|"non-video"` field and per-column `primary: true` marker (1 primary video + 1 primary non-video per week, replacing single global primary). PlanTemplate Pydantic + Gemini structured-output schemas updated; backfill script for existing templates. (3) **COURSE-29 added** — 2-column resource rendering on week cards (left = "🎥 Watch", right = "📖 Read & Build") with primary resource emphasized at top of each column; mobile stacks at ≤720px; sprints render per-day, micros stay linear. Format ladder table in §5.1 updated to reflect 2-column layout per format. Updated Next-action sequence: COURSE-00 → COURSE-00.5 → COURSE-01 → COURSE-02 → COURSE-03 → COURSE-29.
- **2026-04-26** — **Top-3-best resource-quality bar** baked into the plan as a hard requirement. Each week's 3 video + 3 non-video resources must be the top 3 best for the subtopic, not arbitrary 3. Specifically: (1) **§2 constraint #11** added — quality bar (authority / currency / practical applicability / pedagogical fit) with the primary-of-type being the best of the 3. (2) **COURSE-02 AC expanded** — generation prompt enforces top-3 selection criteria + references §14 allowlists; new "Resource Quality" dimension in `review_curriculum.txt` AI rubric (floor 7/10); heuristic scorer in `quality_scorer.py` gates on ≥ 60% allowlist + no within-week duplicates + primary-of-type is highest-authority pick. (3) **COURSE-03 capstone rubric** — adds week-level resource-quality gates that block publish (3+3 count, 1+1 primary, ≥60% allowlist, all URLs 200, no duplicate teaching, ≤24-month currency unless canonical). (4) **§14 trusted-source allowlist** appended — 16 video channels (3Blue1Brown / Karpathy / Stanford / MIT / DeepMind / OpenAI / Anthropic / DeepLearning.AI / HF / fast.ai etc.) and ~25 non-video sources (arXiv / lab docs / framework docs / Distill / Lilian Weng / Sebastian Raschka / canonical books / university courses / Kaggle Learn / high-star GitHub). Implementation as `backend/data/course_resource_sources.json` (mirrors SEO-25 `trusted_sources.json` pattern + suffix-match logic). Allowlist maintained in same PR as course generation hitting edge cases; reviewed quarterly during §8.3 refresh.
