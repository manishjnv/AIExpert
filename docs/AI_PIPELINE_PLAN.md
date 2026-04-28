# AI Pipeline & Enrichment — Centralized Plan

**Drafted:** 2026-04-27
**Status:** Awaiting session execution. Supersedes `docs/PLAN_TIERED_CLAUDE_ROUTING.md`.
**Authority:** Single source of truth for every AI surface in the platform. When this doc conflicts with `AI_INTEGRATION.md` or `AI_QUALITY_PIPELINE.md`, this doc wins on routing/strategy; the source docs win on operational detail (prompt text, schema fields, exact error semantics).

**Reference docs (do not duplicate, link to):**
- `docs/AI_INTEGRATION.md` — provider abstraction, prompt files, sanitization rules
- `docs/AI_QUALITY_PIPELINE.md` — curriculum pipeline stage-by-stage contract
- `docs/AI_Enrichment_Architecture_Blueprint.html` — domain-agnostic ideal pattern

---

## §0 Status board

| Phase | What | Status | Target session |
|---|---|---|---|
| **A** | Surface inventory + maturity audit | ✅ done (this doc, §3) | — |
| **B** | VPS Claude Code crons — clone the proven pattern × 4 surfaces | not started | next session (low risk) |
| **C** | Quality pipeline collapse (4-stage → single Opus pass) | not started | session +1 (load-bearing, §8) |
| **D** | Reasoning trail (schema field) + quarantine table | not started | session +2 |
| **E** | Repo evaluation MVP (after §7 decision) | not started | session +3 |
| **F** | Observability: cache hit-rate dashboard + per-user token budget | partial | piecemeal across B–E |
| **G** | Social post curation (admin-only) — Opus 4.7 cron + `/admin/social` UI | not started · v1 scope locked 2026-04-28 | 2 sessions; backend slice load-bearing per §8 (Alembic + AI prompt) |

**Next action:** Founder confirms the repo evaluation decision in §7, then start Phase B (which can absorb Phase G's cron as a 5th cron clone).

---

## §1 Why this doc exists

Three docs each describe one slice of AI usage. The blueprint describes the ideal pattern. The routing plan describes which model goes where. The quality pipeline describes the curriculum surface end-to-end. **None describe how it all fits together.** Different surfaces use different conventions for cache keys, validation, fallback chains, and instrumentation. This doc is the unifying layer.

The pivot driving this consolidation: as of 2026-04-26 the VPS Max plan auto-summarize cron is live and proven. That single experiment unlocks Claude as the primary editorial model across most surfaces at $0 marginal cost. Until now, every cost-vs-quality decision started from "but Claude is expensive" — that premise is now false for all background work.

---

## §2 Two-track architecture

The product runs every AI workload through one of two tracks. The track determines invocation path, cost shape, and SLA.

### Track 1 — Background work via Claude Code on VPS

The VPS runs the `claude -p --output-format json` CLI binary, authenticated by a Max-plan OAuth token at `/root/.claude/oauth_token`. Cron drives it. Inputs are batched DB rows; outputs are validated structured JSON written back to the DB.

**Use Track 1 when:**
- Work runs on a schedule (daily / weekly / hourly) — no human waiting
- Output is single-account-bound (admin / system) — never directly attributed to a learner request
- Per-call latency is irrelevant; throughput per cron window is what matters
- Quality matters (Opus 4.7 reasoning beats Gemini Pro on editorial)

**Cost shape:** $0 marginal per call. Capped only by Max plan rate limits (700 messages / 5 hours, far above expected daily volume).

**Pattern reference:** `/srv/roadmap/scripts/auto_summarize_drafts.sh` deployed 2026-04-26. New crons clone this script and swap the prompt + DB query.

### Track 2 — Interactive work via Anthropic API

Per-token paid API calls via the official `anthropic` SDK. Authenticated by `ANTHROPIC_API_KEY` env. Streams tokens to the user in real time.

**Use Track 2 when:**
- A learner clicks a button and is staring at the screen waiting
- Multi-user concurrency matters (chat, learner-self-triggered eval)
- Streaming UX is required
- Per-user token budget enforcement is needed

**Cost shape:** $3/M input, $15/M output for Sonnet 4.6 (paid tier). Driven down 60-90% by ephemeral prompt caching on system prompt + context blocks.

### Why the split is structural, not preference

| Constraint | VPS Claude Code | Anthropic API |
|---|---|---|
| Anthropic Max plan ToS | single-user (OK for cron, illegal for multi-user serving) | multi-user OK |
| OAuth token scope | bound to one account (founder's) | per-org API key, multi-user safe |
| Rate limit model | 5-hour bucket per account | per-key rate limits, scalable |
| Streaming | no native streaming over `--output-format json` | yes, `stream=true` |
| Per-call cost | $0 marginal | metered per token |
| Cache mechanism | implicit (CLI manages it) | explicit `cache: 'ephemeral'` blocks |

**Net of the split:** ~85% of Claude work runs Track 1 (free). Only chat (always) and learner-triggered repo eval (if §7 chooses that path) run Track 2 (paid).

---

## §3 Surface inventory — current vs target

Every AI surface in the platform, with the current state and the target state. Maturity rated against the blueprint's 4 invariants (cache / budget / schema / reasoning trail) plus 8 supporting practices.

### 3.1 Curriculum generation, review, refinement

| Aspect | Current | Target |
|---|---|---|
| Discovery model | Gemini 2.5 Flash | unchanged (structured output works well) |
| Generation model | Gemini 2.5 Flash + JSON schema | unchanged for v1; Opus opt-in for flagship templates |
| Review model | Gemini 2.5 Flash (cross-model) | **Opus 4.7 via Track 1 (cron)** |
| Refine — pattern fixes | Gemini 2.5 Flash | unchanged (mechanical, Flash handles fine) |
| Refine — reasoning-heavy | Gemini 2.5 Pro | **Opus 4.7 via Track 1 (cron)** |
| Validate — semantic guardrail | OpenAI embeddings (best-effort skip) | unchanged + made mandatory + log |
| Pipeline shape | 4 stages (Generate → Review → Refine → Validate), 4 separate model calls | **Single Opus pass for non-flagship** (one call returns plan + self-review + diagnostics); legacy flag for 1-week A/B |
| Trigger | admin "Refine all below 90" / per-template button | unchanged + nightly cron auto-refines stale templates |
| Reasoning trail | partial (`dimensions_below_threshold`, `critical_fixes`) | full (`reasoning.{score_justification, evidence_sources, uncertainty_factors}`) |

Maturity now: **Defined (3/5)**. Target: **Managed (4/5)**.

### 3.2 Jobs editorial summaries

| Aspect | Current (shipped 2026-04-26) | Target |
|---|---|---|
| Model | Opus 4.7 via Track 1 (`auto_summarize_drafts.sh`) | unchanged |
| Trigger | daily cron 00:30 UTC | unchanged |
| Schema | output-shape validated | + reasoning trail + quarantine on invalid |

Maturity: **Defined (3/5)** → **Managed (4/5)** after schema + quarantine.

### 3.3 Jobs 10-layer classifier (jobs_ingest / jobs_enrich)

| Aspect | Current | Target |
|---|---|---|
| Pattern | 10-layer defense-in-depth (`docs/JOBS_CLASSIFICATION.md`) | **unchanged — do not touch** |
| Bias | aggressive false-positive rejection | unchanged (per `feedback_classification_bias.md`) |
| Models | mixed (Gemini Flash for extraction, free-tier classifiers for triage) | unchanged |

Maturity: **Managed (4/5)**. No improvements proposed — this is the most mature surface and changes are high-risk.

### 3.4 Topic discovery + triage + dedup

| Aspect | Current | Target |
|---|---|---|
| Discovery | Gemini 2.5 Flash quarterly | **Sonnet 4.6 via Track 1, weekly cron** |
| Triage | Groq Llama → Cerebras → Mistral cascade | **Haiku 4.5 via API for paid surface, Groq cascade as fallback** |
| Dedup | OpenAI `text-embedding-3-small` (cosine > 0.88 reject) | unchanged |
| Trigger | manual / quarterly | weekly cron |
| Schema | partial JSON validation | full + reasoning trail |

Maturity: **Repeatable (2/5)** → **Defined (3/5)**.

### 3.5 Chat assistant

**Decision (founder, 2026-04-27): keep unchanged.** Out of scope for this plan.

Current: Gemini 2.5 Flash + Groq fallback, sanitization, capped at 1024 output tokens. No tiering, no prompt caching, no per-user token budget.

Re-open this surface only when (a) chat costs become measurable on the Gemini paid-tier dashboard, or (b) learner feedback signals quality issues on Flash.

### 3.6 Repo evaluation

**Status: not built.** See §7 for design decision.

### 3.7 Email digest composition

| Aspect | Current | Target |
|---|---|---|
| Model | Gemini Flash (current) | **Opus 4.7 via Track 1, weekly cron** |
| Trigger | weekly Monday | unchanged |
| Output | editorial email body | + reasoning trail (per-section evidence) |

Maturity: **Initial (1/5)** → **Defined (3/5)**.

### 3.8 Blog draft summaries

| Aspect | Current | Target |
|---|---|---|
| Model | manual / not automated | **Opus 4.7 via Track 1, daily cron** |
| Trigger | n/a | daily 06:15 IST |
| Pattern | n/a | clone of `auto_summarize_drafts.sh` |

Maturity: **Manual (0/5)** → **Defined (3/5)**.

### 3.9 Course showcase metadata (non-flagship)

| Aspect | Current | Target |
|---|---|---|
| Model | manual paste-upload (flagship) / auto Gemini (non-flagship) | flagship unchanged + **Opus 4.7 via Track 1 for non-flagship** |
| Trigger | admin click | non-flagship: nightly cron |

Maturity: **Manual (0/5) for non-flagship** → **Defined (3/5)**. Flagship intentionally manual per memory `feedback_manual_template_workflow.md`.

### 3.10 Embedding usage (OpenAI)

| Aspect | Current | Target |
|---|---|---|
| Model | `text-embedding-3-small` | unchanged |
| Volume | 1 lifetime call (3 tokens, $0) | unchanged-by-design; volume rises to ~thousands/year as discovery and quality-pipeline guardrail crons activate |
| Cap | $0.50/day | unchanged (massively over-provisioned, no action) |
| Use | dedup + post-refine guardrail | unchanged |

Maturity: **Defined (3/5)**. The path is wired but dormant. Volume rises naturally as Track 1 crons activate.

### 3.11 Social post curation (admin-only)

**Status:** designed 2026-04-28 · v1 scope locked by founder · awaiting build session.

| Aspect | Current | Target |
|---|---|---|
| Surface | n/a — only `tweet_curator.py` exists (deterministic templates, daily auto-tweet from blog backlog, Twitter only) | New admin surface at `/admin/social` for AI-curated drafts |
| Sources for v1 | n/a | **blog + course only** (jobs / weekly digest / cohort milestones deferred to v2) |
| Platforms | Twitter only via daily cron | Twitter + LinkedIn drafts per source |
| Generation model | deterministic templates | **Opus 4.7 via Track 1 (`claude -p` Max OAuth)** — $0 marginal |
| Trigger | 8am IST daily cron picks freshest unused blog | **Daily 06:30 IST cron** scans for blogs/courses without active `social_posts` row → generates draft for both platforms in one Opus call. No on-publish event coupling — cron handles backfill. |
| Admin UX | n/a (admin posts manually) | `/admin/social` page: Drafts (default) / Published / Archived tabs. Per row: source, platform, draft body editable, hashtags, reasoning trail collapsible. Actions: Edit · Publish · Re-publish · Discard. |
| Twitter publish | n/a | Reuses existing `twitter_client.py.post_tweet()`. Direct API post on admin click. |
| LinkedIn publish (v1) | n/a | **Manual:** `📋 Copy + Open LinkedIn` button copies body to clipboard + opens LinkedIn share intent in new tab. Admin posts manually, returns, clicks `Mark as posted` with the LinkedIn URL. **No LinkedIn API integration in v1.** Defer to v2 when founder applies for LinkedIn Marketing Developer Platform. |
| Auto-archive | n/a | **Drafts older than 30 days that admin never published auto-archive.** UI shows a banner "N stale drafts ready to archive" with one-click cleanup. Archived rows preserved in DB for analytics; hidden from default UI. |
| State machine | n/a | `pending → draft → published` (terminal) · `draft → archived` (admin discard) · `pending → archived` (validation failed 3×) · `published → pending` (Re-publish spawns new row, old `published` row preserved as history). UNIQUE index on `(source_kind, source_slug, platform) WHERE status IN ('pending', 'draft')` prevents double-queueing. |
| Schema | n/a | New `social_posts` table (Alembic migration, **load-bearing**). Pydantic output schema enforces Twitter ≤ 280, LinkedIn ≤ 3000, hashtags well-formed, **mandatory reasoning trail** (per invariant #4). |
| Re-publish prompt | n/a | Opus prompt for re-publish includes prior draft text with instruction "find a different angle, different hook, different framing — do not duplicate phrasing." Different angle, not regeneration. |
| Hashtag canonicality | n/a | Reuses `_TAG_DISPLAY` lookup from `share_copy.py`. Opus prompt includes the brand-canonical hashtag map; never invents `#prompt-engineering`, always emits `#PromptEngineering`. |
| User-facing share modal | unchanged ([per S50 commit `0d4a45f`](../docs/HANDOFF.md#current-state-as-of-2026-04-28-session-50-continued--audit-merge--day-2-agent-team-skills)) | unchanged. The `build_share_copy()` deterministic templates that drive `/blog/{slug}` Share button stay untouched. This admin surface is purely additive. |

**Cost shape:** ~5-20 sources/month at typical solo cadence × 2 platforms = 10-40 Opus drafts/month. One Opus call generates both Twitter + LinkedIn in a single structured response. Track 1 = $0 marginal. Trivial volume, no Max plan rate-limit concern (700 messages/5h cap is far above this).

**v1 scope explicitly out:** jobs as a source, weekly digest as a source, cohort milestone as a source, LinkedIn API integration, recommendation engine ("which post to publish first"), engagement-rate tracking back into the system, A/B testing of angles. All deferred to v2 once v1 proves the loop.

**Pre-build blockers (must resolve before ship):**

- **X API write auth currently 403s.** Diagnosed 2026-04-28: `.env` has Twitter OAuth 1.0a credentials that pass `GET /2/users/me` (200 OK as `@manishjnvk`) but fail `POST /2/tweets` with `403 Forbidden — "Your client app is not configured with the appropriate oauth1 app permissions for this endpoint"`. The X Developer Portal's User authentication settings show "Read and write and Direct message" as the App permissions selection, but the issued token has read scope only. Likely cause: permission change in portal wasn't actually saved before token regeneration, OR the X portal silently failed to persist the change. The pre-existing `tweet_curator` daily 13:30 UTC cron loop is **disabled in `scripts/scheduler.py`** (commented out of `asyncio.gather`) so failed-row noise doesn't accumulate on `/admin/social`. **Phase G smoke test will hit the same 403 on the first POST attempt — resolve before going live.** Two paths: (a) re-do the User authentication settings save flow being deliberate about clicking the Save button at the bottom of the page, then regenerate Access Token + Secret + update `.env`. (b) Create a fresh app in the same Project with Read+Write set at creation time (more reliable than retrofitting the existing app). Either way takes ~5 min once the X portal cooperates.
- **Recommended Phase G hedge:** Build with `settings.x_publish_enabled` env flag gating `twitter_client.post_tweet()` calls. If the flag is off, drafts ship as "awaiting manual post" — same fallback path as LinkedIn v1's copy-to-clipboard flow. Lets Phase G ship cleanly even while X portal is still being weird, and the LinkedIn-only manual flow remains useful by itself.

**Model choice:** **Opus 4.7** — confirmed founder pick 2026-04-28. Editorial work (per `feedback_opus_for_editorial.md`); Sonnet/Haiku not considered because Track 1 is $0 marginal anyway, so quality dominates. Same model already proven on the 2026-04-26 jobs editorial cron.

**Voice & tone (v1, locked 2026-04-28):**

Three rules baked into the `prompts/social_curate.txt` prompt — these will be the prompt's tightest constraints, with concrete do/don't examples drawn from the founder's existing blog voice:

1. **Humane.** Sounds like a person who learned this the hard way, not an enterprise marketing channel. First-person plural ("we", "let's") and second-person ("you") OK; third-person corporate ("our platform offers") never. No buzzwords (synergy, leverage, empower, unlock). No emoji-overload — one purposeful emoji max per post, often zero. No exclamation marks unless genuinely warranted (max one per post).
2. **Simple.** Plain English. If a 12-year-old who's interested in coding wouldn't follow the sentence, rewrite it. Sentences ≤ 18 words median. Active voice. Avoid "leverage" / "utilize" / "facilitate" / "robust" / "comprehensive" / "robust solution" entirely. Concrete numbers > vague claims ("50 questions mined from 25 live job loops" beats "extensive interview prep").
3. **Slightly humorous.** One light beat per post — a wry observation, a self-deprecating aside, a pattern-name that pokes at the obvious. Not stand-up jokes, not memes. Aim for the tone of a senior engineer's Slack message to a friend, not a LinkedIn motivation poster. Twitter posts can be 10-20% funnier than LinkedIn (LinkedIn audience expects more measured tone, but flat is the failure mode there).

**Voice samples (drawn from existing blog voice — fed into Opus prompt as few-shot anchors):**

- ✅ "Stop your LLM from hallucinating." (lede from RAG post — humane, simple, no fluff)
- ✅ "Pattern matching to a 2022 interview list is the fastest way to fail a 2026 AI engineer loop." (lede from interview-prep post — slight humor in "fastest way to fail," precise verb)
- ❌ "Unlock your AI engineering potential with our comprehensive guide!" (corporate, vague, exclamation, "unlock")
- ❌ "We're excited to announce…" (anti-pattern: every word adds zero signal)
- ❌ "Discover the secrets of…" (clickbait register; not the audience)

These samples become the few-shot anchors in `prompts/social_curate.txt`. Voice will be spec-checked in admin reviews — if drafts drift toward LinkedIn-corporate over time, founder updates the prompt rather than editing each draft.

**Hashtag voice rule:** hashtags exist for discovery, not punctuation. Twitter ≤ 2 mapped tags. LinkedIn 3-5 including `#AutomateEdge` last. Never inline mid-sentence (`#AI is changing #everything` — banned). Always end-of-post block.

Maturity now: **Manual (0/5)** (admin writes posts by hand or uses the daily auto-tweet cron). Target after build: **Defined (3/5)**.

---

## §4 The 4 invariants (apply uniformly)

Every AI call across every surface must satisfy these four. Reference: blueprint §02.

1. **Cache before you call.** Stable system prompts + reference corpora marked cacheable. Track 1: implicit via Claude CLI. Track 2: explicit `cache_control: {'type': 'ephemeral'}` blocks. Target: 80%+ cache hit rate per surface (instrumented in §F).
2. **Budget before you spend.** Track 2 only (Track 1 is $0). Per-user daily token budget with three-tier degradation: warn at 80% / fallback to Haiku at 90% / hard-stop at 100%.
3. **Schema before you trust.** Every LLM output validated against a strict Pydantic schema. Failed validation → quarantine row, not silent skip.
4. **Reasoning trail mandatory.** Every output includes `reasoning.{score_justification, evidence_sources[], uncertainty_factors[]}`. `evidence_sources` non-empty is enforced; empty array → reject as hallucination.

---

## §5 The 7 high-leverage improvements (sequenced by priority + dependencies)

Each improvement: what it is, why it matters, where it lands, what it depends on, acceptance criteria.

### 5.1 Reasoning trail as mandatory schema field

**What.** Every Pydantic output schema gains `reasoning: ReasoningTrail` with three required fields.

**Why.** Today scores have no audit trail. Learners and admins cannot defend any AI output. This blocks meaningful UX ("why did you score this 87?") and meaningful drift detection.

**Where.** `backend/app/ai/schemas.py` (new shared `ReasoningTrail` Pydantic model); referenced by `PLAN_TEMPLATE_SCHEMA`, `QUALITY_REVIEW_SCHEMA`, future `REPO_EVAL_SCHEMA`, future `JOB_EDITORIAL_SCHEMA`.

**Dependencies.** None (pure schema work).

**Acceptance.** All Pydantic outputs validate `len(reasoning.evidence_sources) >= 1`. One unit test per surface confirms the refinement rejects empty evidence. Admin view renders the trail.

### 5.2 Centralized `claude_client.py` + cache hit-rate dashboard

**What.** One module, owns all Anthropic API calls and shells out to Track 1 CLI for background. Validates cached prefixes are byte-identical (no templating into cache blocks). Logs `cache_read_input_tokens / total_input_tokens` per call to `ai_usage_log`. Admin dashboard at `/admin/ai-usage/cache` aggregates.

**Why.** Blueprint calls cache hit rate the single most important cost metric. We don't track it. The first time we look at production data we'll discover hit rate is 12% and has been for months.

**Where.** New `backend/app/ai/claude_client.py`; new admin route; `ai_usage_log` schema gets `cache_read_tokens` + `cache_creation_tokens` columns via Alembic migration.

**Dependencies.** None.

**Acceptance.** Dashboard shows ≥7 days of data; alert fires when surface drops below 60%. Test confirms templating dynamic content into cache block raises a runtime error, not just a missed cache.

### 5.3 Curriculum quality pipeline collapse

**What.** Replace 4-stage chain (Generate → Review → Refine → Validate) with single Opus pass for non-flagship. Stage 0 (deterministic auto-fix) and Stage 4 (semantic guardrail) stay; Stages 1+2+3 collapse into one structured Opus call returning plan + self-review + diagnostics.

**Why.** Opus single-pass reasoning > Flash chained four times on editorial work. Currently 4 calls per template. After collapse: 1 call per template. Quality up, cost flat (Opus on Track 1 = $0 marginal).

**Where.** `backend/app/services/quality_pipeline.py`. Load-bearing path — requires §8 ceremony (worktree + Opus diff review + `codex:rescue` sign-off).

**Dependencies.** 5.1 (reasoning trail), 5.2 (centralized client). Behind `USE_LEGACY_QUALITY_PIPELINE=true` flag for 1-week A/B before legacy delete.

**Acceptance.** 5 representative templates produce ≥ legacy quality on Opus spot-check. Cost-per-template metric ≤ legacy. Rollback flag flip works.

### 5.4 Per-user token budget (Track 2 surfaces)

**What.** Three-tier daily budget enforcement keyed by `user_id`: warn 80% → fallback Haiku 90% → hard-stop 100%. Surface to user as "tokens remaining today" pill — feature, not punishment.

**Why.** No enforcement exists today. One runaway user or misconfigured loop can spike Anthropic API spend with nothing to stop it. Required before any new Track 2 surface ships (chat exists but is unchanged; repo eval if §7 picks Track 2).

**Where.** `backend/app/ai/budget.py` (new); `ai_user_budget` table via Alembic; UI pill in dashboard nav.

**Dependencies.** 5.2 (centralized client logs tokens to `ai_usage_log`).

**Acceptance.** Test with `daily_limit_tokens=100`: first call passes, second triggers Haiku fallback, third hard-stops with friendly error. Admin override per user works.

### 5.5 Quarantine table + admin reprocess UI

**What.** New `ai_quarantine` table stores raw responses that failed schema validation: surface, raw_response, validation_errors, called_at, status (open/reprocessed/discarded). Admin view at `/admin/ai-usage/quarantine` lists, inspects, re-triggers, or discards.

**Why.** Today invalid LLM outputs trigger silent skip + fallback to original. Drift is invisible. RCA-033 pattern: editorial regression went undetected because nothing surfaced the failure.

**Where.** `backend/app/models/ai.py` (new model); admin route + template; `claude_client.py` writes quarantine rows on `pydantic.ValidationError`.

**Dependencies.** 5.1 (schemas), 5.2 (client).

**Acceptance.** Inject malformed response → row appears in admin UI within 5s. Click "reprocess" → retries with same prompt; result either validates and clears the row or appends a new quarantine.

### 5.6 External-signal-first composite scoring (for repo eval, §7)

**What.** Free signals run in parallel before LLM is invoked: GitHub API (stars, forks, last commit, README presence, languages), local static checks (test directory? CI configured? deps file?). LLM receives consolidated structured context, doesn't waste tokens looking up facts. Final score: `(free_signals × 0.30) + (deliverable_match × 0.30) + (LLM_reasoning × 0.40)`.

**Why.** Most variation in repo quality is structural (does it compile? does it have tests? does it match the deliverable?). Free signals catch this. LLM reasons about the rest. Result: cheaper, more defensible, harder to game.

**Where.** `backend/app/services/repo_eval.py` (new). Depends on §7 decision.

**Dependencies.** §7 decision. 5.1 (reasoning trail). 5.4 (per-user budget if learner-triggered).

**Acceptance.** Composite score on 10 reference repos differs from pure-LLM score by <10 points but exposes 2-3 issues LLM missed.

### 5.7 Batch API path for jobs enrichment (when scale demands)

**What.** Anthropic Message Batches API offers 50% discount on inputs + 24h SLA. Optional alternative to Track 1 cron when (a) volume exceeds Max plan rate limits, or (b) multi-tenant safe processing is required.

**Why.** Future-proofing. Current jobs editorial cron handles volume fine on Track 1. If scale grows or Max plan ToS becomes ambiguous, Batch API is the multi-tenant-safe upgrade path with similar economics.

**Where.** Add as a third track in `claude_client.py` once 5.1–5.5 are stable.

**Dependencies.** 5.2 (client). Not blocking — defer until Track 1 actually hits a constraint.

**Acceptance.** Switch jobs editorial from Track 1 → Batch API in one config flip; output quality + completion time within 5% of Track 1.

---

## §6 VPS Claude Code playbook

The proven pattern. Every new Track 1 surface clones it verbatim.

### Reference implementation

`/srv/roadmap/scripts/auto_summarize_drafts.sh` (deployed 2026-04-26, 4957 bytes). Cron entry at `/etc/cron.d/auto_summarize_drafts`.

### What every Track 1 wrapper has

1. **Pre-flight token check.** Reads `/root/.claude/oauth_token` mtime, prints warning at 30 / 7 days to expiry, hard-fails on expired. Memory entry `reference_vps_auto_summarize_cron.md` tracks the expiry date (currently 2027-04-26).
2. **`flock -n` concurrency guard.** Prevents two cron firings overlapping. Cron line: `flock -n /var/lock/<name>.lock <script>`.
3. **Idempotency.** Re-running picks up where prior left off (queries DB for "rows still without summary"). Safe to re-trigger manually.
4. **`claude -p --output-format json`.** Headless invocation. Parses JSON metadata for token usage. Writes one `ai_usage_log` row per call.
5. **Logrotate config.** 8-week retention at `/var/log/auto_<name>.log`.
6. **Output-shape validation.** Before writing to DB, validates response shape; quarantines on failure (per 5.5).

### Crons to add (Phase B)

| Script | Schedule (UTC / IST) | Surface | Model |
|---|---|---|---|
| `auto_summarize_blog_drafts.sh` | `45 0 * * *` / 06:15 IST daily | Blog summaries (3.8) | Opus 4.7 |
| `auto_generate_course_metadata.sh` | `0 1 * * *` / 06:30 IST daily | Course metadata non-flagship (3.9) | Opus 4.7 |
| `auto_discover_topics.sh` | `15 1 * * 1` / 06:45 IST Mon | Topic discovery weekly (3.4) | Sonnet 4.6 |
| `auto_compose_email_digest.sh` | TBD (verify cadence) | Email digest (3.7) | Opus 4.7 |

After 5.3 ships, add a fifth: `auto_refine_curriculum_stale.sh` (nightly stale-template refinement via the new collapsed pipeline).

### Token rotation cadence

OAuth token expires 2027-04-26. At 30-day warning (2027-03-27), schedule a session to run `renew_oauth_token.sh`. Memory entry tracks both dates.

---

## §7 Repo evaluation — design decision

Surface not yet built. Founder asked for a recommendation. Three options compared.

### Option A — Admin-only

Admin clicks "AI evaluate" on a learner's repo from `/admin/users/<id>`. Single-user invocation. Track 1 (VPS Claude Code) feasible.

**Pros.** Simple. Free (Track 1). High quality (Opus 4.7).
**Cons.** Bottlenecks on admin time. Doesn't give learners self-service feedback. Defeats the product hypothesis ("AI evaluates your work").

### Option B — Use Gemini Flash (current default everywhere else)

Build the `evaluate.txt`-driven endpoint, Gemini Flash on free tier, learner-triggered from dashboard.

**Pros.** Free. Already wired (provider abstraction supports it). Consistent with current chat (Flash).
**Cons.** Flash quality is "OK" but not great on multi-criterion code review. No reasoning trail. No composite scoring. Easy to game (a polished README scores well even if the code is broken).

### Option C — Existing process (don't build)

Skip the surface entirely. Acceptable if repo eval isn't a priority.

**Pros.** Zero work.
**Cons.** Loses a marketed product feature. Phase 4 of `docs/TASKS.md` still has it queued.

### Option D — Recommended: Hybrid composite, Gemini Flash default + Sonnet 4.6 opt-in

Mirrors the Gemini-default + Claude-premium shape that chat already runs (and that the founder asked to preserve for chat).

**Architecture.**
1. **Free signals first** (no LLM, parallel): GitHub API for stars/forks/last-commit/README/license/languages; local static checks (test directory exists? CI configured? deps file present?). Costs zero, runs in <2s.
2. **Heuristic deliverable match**: keyword + structural match against the week's stated deliverable. Costs zero.
3. **LLM reasoning tier**:
   - Default: **Gemini 2.5 Flash via existing provider abstraction**. Free tier. Per-user daily quota (e.g. 5 evaluations/day for free users).
   - Premium opt-in: **Claude Sonnet 4.6 via Anthropic API (Track 2)**. Triggered by user clicking "Get a deeper evaluation" button. Higher per-user budget for paid tiers; free tier gets 1 premium eval per week.
4. **Composite final score**: `(free_signals × 0.30) + (deliverable_match × 0.30) + (LLM_reasoning × 0.40)`.
5. **Reasoning trail mandatory** (per 5.1). Surface to learner: "Score 87 because [evidence]. Uncertain about [factor]. Suggested next step: [action]."
6. **Sanitize before send** (per existing `backend/app/ai/sanitize.py` rules — no `.env`, redact tokens, 20KB cap).

**Pros.** Cheap baseline (Flash free tier handles >95% of traffic). Premium upgrade lever for power users / paid tiers. Composite scoring is harder to game than pure-LLM. Reasoning trail makes the score defensible.
**Cons.** More moving parts than B. Requires per-user budget (5.4). Requires composite scoring scaffolding (5.6).

**Recommendation: Option D.** It's the most blueprint-aligned, most cost-disciplined, most consistent with chat, and gives a clean "premium" upgrade lever without forcing every learner through paid-API economics. Build only after 5.1 (reasoning trail), 5.4 (per-user budget), and 5.6 (composite scoring) land.

**Decision needed from founder:** confirm Option D, or pick A/B/C. Doc updates after decision.

---

## §8 Surface-by-surface migration plan

| Surface | Action | Track | Phase | Depends on |
|---|---|---|---|---|
| Curriculum gen | unchanged for now (Gemini Flash + JSON schema) | Gemini | — | — |
| Curriculum review | move to Opus via cron | Track 1 | C | 5.1, 5.2, 5.3 |
| Curriculum refine (reasoning) | move to Opus via cron | Track 1 | C | 5.1, 5.2, 5.3 |
| Jobs editorial | already shipped 2026-04-26 | Track 1 | done | + 5.1 reasoning trail upgrade |
| Jobs classifier | unchanged — do not touch | mixed | — | — |
| Topic discovery weekly | move to Sonnet via cron | Track 1 | B | OAuth token only |
| Topic triage | unchanged (Groq cascade) | free-tier | — | — |
| Embedding dedup | unchanged | OpenAI | — | — |
| Chat | unchanged (founder decision 2026-04-27) | Gemini | — | — |
| Repo eval (after §7) | Option D: Flash default + Sonnet opt-in | Track 2 + Gemini | E | 5.1, 5.4, 5.6 |
| Email digest | move to Opus via cron | Track 1 | B | OAuth token only |
| Blog summaries | new — Opus via cron | Track 1 | B | OAuth token only |
| Course metadata (non-flagship) | new — Opus via cron | Track 1 | B | OAuth token only |
| Course metadata (flagship) | unchanged manual paste | manual | — | per memory |
| Social post curation (admin /admin/social) | new — Opus drafts both Twitter + LinkedIn from blog/course publishes; daily cron backfill; admin reviews + publishes when convenient | Track 1 | G | OAuth token; 5.1 reasoning trail (recommended); existing `twitter_client.py` for X publish; LinkedIn manual copy-paste in v1 |
| User-facing share modal (/blog Share button) | unchanged ([shipped 2026-04-28 in commit `0d4a45f`](../docs/HANDOFF.md)) — `build_share_copy()` deterministic templates | Track 0 (no AI) | done | — |

---

## §9 Out of scope (do not touch)

These are intentional non-goals. Surface arguments to founder before any of them moves.

- **Chat assistant** — keep unchanged (founder decision 2026-04-27).
- **Flagship course Opus paste-upload** — manual gate intentional per `feedback_manual_template_workflow.md`.
- **Jobs 10-layer classifier** — false-positives never acceptable per `feedback_classification_bias.md`. Bias toward rejection is a feature.
- **OpenAI embeddings** — rule already documented. No competitive alternative. Volume stays trivial.
- **Quarterly sync (legacy)** — already replaced by auto-pipeline. Don't resurrect.
- **The 2026-04-26 jobs editorial cron** — working, don't refactor. Only addition allowed: schema upgrade in 5.1, quarantine wiring in 5.5.

---

## §10 Risk register

| Risk | Mitigation |
|---|---|
| Max plan rate limit hit during a backfill burst | Track 1 wrappers process 10/batch, cron once daily. Worst case = 700 messages/5h cap, far above expected daily volume. |
| OAuth token expires mid-session | Pre-flight check in every wrapper (already shipped). 30-day warning gives runway. |
| 5.3 quality pipeline collapse degrades non-flagship templates | `USE_LEGACY_QUALITY_PIPELINE=true` flag for 1-week A/B before legacy delete. |
| Repo eval Option D Sonnet path leaks paid spend | 5.4 per-user token budget hard-stops at 100%. |
| RCA-033-style editorial regression in cron output | 5.5 quarantine table surfaces invalid output instead of silent skip. |
| Anthropic API monthly cost exceeds budget | 5.4 budgets cap blast radius; Brevo alert at threshold. |
| Cache hit rate silently regresses | 5.2 dashboard + alert at <60%. |
| Single-account OAuth becomes Anthropic ToS issue | 5.7 Batch API path is the multi-tenant-safe migration. |

---

## §11 Success criteria (definition of done)

- [ ] All 4 Phase B background crons running daily/weekly with no manual prompt generation
- [ ] Single Opus pass replaces 4-step quality pipeline for non-flagship paths (5.3)
- [ ] Every AI output schema includes `reasoning.{score_justification, evidence_sources, uncertainty_factors}` (5.1)
- [ ] `/admin/ai-usage/cache` dashboard live with ≥7 days of data; cache hit rate ≥80% on instrumented surfaces (5.2)
- [ ] `/admin/ai-usage/quarantine` admin reprocess UI live (5.5)
- [ ] Per-user token budget enforced on Track 2 surfaces with three-tier degradation (5.4)
- [ ] Repo eval shipped per §7 decision (default Flash, Sonnet opt-in if Option D)
- [ ] Lifetime Anthropic API spend bounded by per-user budget × user count (no surprise invoices)
- [ ] Memory entries updated:
  - `project_claude_api_usage.md` → "expanded 2026-04-27"
  - `reference_vps_auto_summarize_cron.md` → list all Track 1 wrappers
  - new: `reference_ai_pipeline_plan.md` → pointer to this doc
  - new: `reference_ai_usage_dashboard.md` → where to find usage data
- [ ] Zero regressions in untouched surfaces (jobs editorial, classifier, chat)
- [ ] One RCA entry per bug caught + fixed during implementation

---

## §12 Recommended session split

| Session | Phases | Approx hrs | Risk | Why this order |
|---|---|---|---|---|
| **Session N** | Phase B (4 cron clones) + 5.1 (reasoning trail schemas) | 5–6 | Low | Clones proven pattern; schema work touches no live behavior |
| **Session N+1** | Phase C (5.3 quality pipeline collapse) + 5.2 (centralized client) | 6–8 | Medium — load-bearing | Needs `codex:rescue` gate; benefits from N's reasoning trail being in place |
| **Session N+2** | 5.4 (per-user budget) + 5.5 (quarantine) + Phase D close-out | 5–7 | Medium | Surfaces failures from N+1 in production; budget infra ready for Phase E |
| **Session N+3** | Phase E (repo eval per §7) + 5.6 (composite scoring) + 5.7 batch path optional | 6–8 | Medium — new user-facing surface | All dependencies from N, N+1, N+2 in place |

Four sessions total. Each leaves the codebase in a working, shippable state.

---

## §13 Phase 0 reads (when starting any session in this plan)

In one parallel-tool-call burst:

- This doc (§0 status board + §3 surface entry being touched)
- `CLAUDE.md` (project rules + load-bearing paths)
- `docs/HANDOFF.md` (last session state)
- `docs/RCA.md` first ~150 lines (recent + patterns)
- `~/.claude/projects/e--code-AIExpert/memory/MEMORY.md`
- For 5.3 / Phase C only: `docs/AI_QUALITY_PIPELINE.md` (current pipeline contract before collapse)
- For Phase E only: `docs/TASKS.md` Phase 4 spec + `backend/app/ai/prompts/evaluate.txt`

State the goal in one sentence, the relevant memory entries to honor, the plan, and what will be delegated. Wait for founder approval before touching code.
