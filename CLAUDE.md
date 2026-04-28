# CLAUDE.md — Project Memory for Claude Code

> **Claude Code: read this file at the start of every session.** It is the single source of truth for what this project is, how it is structured, and how to work on it. Update the "Session state" section at the end of every session before you hand off.

## 1. Project identity

**Name:** AI Roadmap Platform
**Purpose:** A web platform that gives anyone a personalized, AI-curated 3-to-12-month study plan to learn AI from scratch. Users track their progress, link their practice work via GitHub, get AI-powered evaluations of their repositories, and share milestones on LinkedIn. The curriculum auto-refreshes every 3 months by pulling trending topics from top universities and practitioner sources.

**Why it exists:** Existing roadmaps (roadmap.sh, coursera, etc.) are static, one-size-fits-all, and get stale within months in the AI field. This platform stays current and gives personal feedback.

**Audience:** Working developers, CS students, and career changers who want a serious, accountable study plan.

## 2. Current status

**Phase:** 0 — planning complete, scaffolding ready, no application code written yet.
**What exists:** This repo with documentation and config scaffolding. A working static tracker HTML (`frontend/index.html` from earlier iteration) is the visual starting point for the frontend.
**What does not exist yet:** Everything in `backend/app/` beyond `main.py` and `config.py`. All API endpoints. All frontend integration with the backend. All AI integrations. All GitHub integration.

**Next thing to build:** See `docs/TASKS.md` → Phase 1.

## 3. Tech stack (chosen, do not change without discussion)

- **Backend:** Python 3.12 + FastAPI + SQLAlchemy 2.0 + SQLite (async via aiosqlite)
- **Auth:** Authlib for Google OAuth2; custom email OTP via SMTP; JWT sessions (httpOnly cookies)
- **Frontend:** Vanilla JS + ES modules, incrementally built on top of the existing single-file tracker. No SPA framework unless explicitly decided.
- **AI integration:** Google Gemini API (free tier) primary, Groq free tier fallback. No paid APIs.
- **GitHub integration:** GitHub OAuth App + direct REST calls via httpx
- **Database:** SQLite file at `/data/app.db` (mounted volume), migrations via Alembic
- **Deployment:** Docker Compose on a VPS, behind the user's existing reverse proxy
- **Email:** Brevo free tier (300 emails/day) or Resend free tier (3,000/month) via SMTP

**Rationale for each choice lives in `docs/ARCHITECTURE.md`.** Don't re-debate these unless something is genuinely blocking.

## 4. Repository layout

```
.
├── CLAUDE.md                  ← you are here, read first every session
├── README.md                  ← human overview
├── .env.example               ← template; real .env is git-ignored
├── .gitignore
├── docker-compose.yml         ← full stack: backend + nginx + cron
├── docs/
│   ├── PRD.md                 ← product requirements (what to build)
│   ├── ARCHITECTURE.md        ← technical architecture (how it fits together)
│   ├── DATA_MODEL.md          ← database schema
│   ├── API_SPEC.md            ← REST endpoints
│   ├── TASKS.md               ← phased backlog with acceptance criteria
│   ├── HANDOFF.md             ← living session state (update each session)
│   ├── SECURITY.md            ← security rules, threat model, checklist
│   ├── AI_INTEGRATION.md      ← free AI provider setup + prompts
│   └── DEPLOYMENT.md          ← VPS deployment workflow
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py            ← FastAPI entrypoint (skeleton exists)
│       ├── config.py          ← env-driven settings (skeleton exists)
│       ├── db.py              ← async SQLAlchemy session (not yet)
│       ├── models/            ← ORM models (not yet)
│       ├── routers/           ← API routers per resource (not yet)
│       ├── services/          ← business logic (not yet)
│       ├── auth/              ← OAuth + OTP + JWT (not yet)
│       └── ai/                ← Gemini/Groq wrappers (not yet)
├── frontend/
│   └── index.html             ← starting point; progressively enhanced
├── scripts/
│   └── quarterly-sync.py      ← curriculum refresh cron (stub exists)
└── pb_hooks/                  ← reserved; currently unused
```

## 5. Critical rules for Claude Code

These are non-negotiable. If a rule conflicts with a user request, surface the conflict and ask — do not silently violate.

1. **Never commit secrets.** Anything that looks like a key, token, password, client secret, webhook URL with embedded auth, or personal identifier goes in `.env`, never in code. Before every `git commit`, grep the staged diff for the strings `sk-`, `gh[pousr]_`, `AIza`, `GOCSPX`, `smtp`, `password`, `secret`, `key=`. If you find any, stop and ask the user.

2. **No placeholder secrets that look real.** Use obvious placeholders like `YOUR_KEY_HERE` or `changeme` — never realistic-looking random strings that someone might assume are real leaked credentials.

3. **SQLAlchemy ORM only.** Never construct SQL via string concatenation. Never use `text()` with user input. Always parameterize.

4. **Every endpoint that mutates state requires authentication.** The only unauthenticated endpoints are: `GET /` (frontend), `GET /api/health`, `GET /api/learner-count`, `POST /api/auth/google/callback`, `POST /api/auth/otp/request`, `POST /api/auth/otp/verify`, and static assets. Everything else checks `current_user` via the JWT dependency.

5. **Rate limit every auth endpoint.** OTP request, OTP verify, Google callback — all rate limited per IP via slowapi. Defaults: 5 requests / 15 minutes for OTP request.

6. **Use async throughout.** FastAPI + async SQLAlchemy + httpx (not requests). Never block the event loop. No sync DB calls inside endpoint handlers.

7. **AI evaluation never reveals secrets.** When sending a GitHub repo summary to an LLM, strip any file that looks like an env file, a config with keys, or a secrets file before sending. There is a helper for this in `backend/app/ai/sanitize.py` (to be built in Phase 4) — use it.

8. **Keep the frontend runnable standalone.** The single `frontend/index.html` must still work when opened directly from the filesystem in "local-only" mode, exactly like the original tracker. Progressive enhancement only — never break the fallback.

9. **Do not invent new dependencies without checking.** The approved dependency list lives in `backend/requirements.txt`. If you think you need a new package, ask first. Keep the footprint tight — this runs on a small VPS.

10. **Update `docs/HANDOFF.md` at the end of every session.** This is how the next session (yours or another developer's) knows where to resume.

11. **Read `docs/RCA.md` at the START of every session** before writing any code. Scan the most recent 5 entries and the "Patterns to watch for" table at the bottom — they encode real mistakes this codebase has already paid for. After fixing any bug or security defect, add a new numbered entry with symptom / root cause / fix (with file+line link) / prevention rule, and update the pattern table if the failure mode is new.

12. **Follow the orchestration playbook in §8** for any change touching 2+ files or any path flagged load-bearing (`backend/app/ai/`, `backend/app/auth/`, `jobs_ingest/`, `jobs_enrich/`, `backend/alembic/versions/`). Generic phases + routing live in the global `~/.claude/CLAUDE.md`; this repo's overlay is §8 below. Use `/orchestrate` to trigger Phase 0 explicitly.

## 6. Quick commands

```bash
# Local dev
docker compose up -d                              # bring the stack up
docker compose logs -f backend                    # tail backend logs
docker compose exec backend alembic upgrade head  # run migrations
docker compose exec backend pytest                # run tests

# Deploy (when ready)
git push origin main                              # triggers webhook / manual pull on VPS
ssh vps "cd /srv/roadmap && git pull && docker compose up -d --build backend"
```

## 7. Working style

- **Small, reviewable changes.** One feature slice per session, not sprawling rewrites.
- **Write the test first when the logic is non-trivial.** Skip tests for throwaway UI polish.
- **Ask before deleting files.** Never delete a file you did not create in the same session without explicit approval.
- **Prefer editing over rewriting.** If a file exists and works, extend it; don't replace it wholesale.
- **When a spec doc is ambiguous, propose an interpretation, then update the doc.** Don't silently choose.

## 8. Orchestration playbook (project overlay)

The generic playbook — routing table, Phase 0–6 flow, hard rules — lives in `~/.claude/CLAUDE.md` (global). This section is the repo-specific overlay. When a rule here conflicts with the global playbook, **this one wins**. Trigger the full flow explicitly with `/orchestrate`.

### Phase 0 reads (exact paths for this repo)

In the Phase 0 parallel-tool-call burst, read all six in one message:

- `CLAUDE.md` (this file)
- `docs/HANDOFF.md`
- `docs/RCA.md` — first ~150 lines (recent entries + the "Patterns to watch for" table at the bottom)
- `docs/SEO.md` — §0 only, first ~100 lines (trigger conditions + task status board + next action). Load deeper sections on-demand when §0.1 trigger conditions apply to the current session's work.
- `docs/COURSES.md` — §0 only, first ~120 lines (trigger conditions + task status board + next action). Load deeper sections on-demand when §0.1 trigger conditions apply.
- `C:\Users\manis\.claude\projects\e--code-AIExpert\memory\MEMORY.md`

### Load-bearing paths (require Opus diff review + worktree isolation)

Any Sonnet/Haiku subagent editing these paths MUST be spawned with `isolation: "worktree"`, and you MUST review the diff line-by-line in Phase 3:

- `backend/app/ai/` — provider clients, prompt construction, sanitizer (secrets-stripping before LLM send)
- `backend/app/auth/` — Google OAuth, email OTP, JWT, session cookies, rate limiting
- `jobs_ingest/` and `jobs_enrich/` — the 10-layer classifier defense (see [docs/JOBS_CLASSIFICATION.md](docs/JOBS_CLASSIFICATION.md))
- `backend/alembic/versions/` — schema migrations (irreversible in prod)
- Anything that constructs or edits an **AI enrichment / evaluation prompt** — never regenerate these from scratch without explicit user approval (prompts are tuned assets, not boilerplate)

### Memory entries to actively consult (do not re-derive)

Before proposing changes in the relevant area, pull the matching memory entry from `MEMORY.md`:

- **Classifier work** → `feedback_classification_bias.md` (false-positives never acceptable; don't propose Wave 5 #19 without drift evidence)
- **Long-running DB writes** → `feedback_sqlite_writer_sessions.md` (commit per row; WAL clash with live backend)
- **New HTTP route** → `feedback_nginx_allowlist_on_new_routes.md` (update `nginx.conf` in same PR)
- **Editorial AI output** → `feedback_opus_for_editorial.md` (Flash can't match Opus editorial quality; tiered strategy)
- **Any new logger/httpx caller** → `feedback_redact_api_keys.md` (install `_redacting_filter` at entrypoints)
- **Deployments** → `feedback_deploy_rebuild.md` (`restart` doesn't pick up code; build + force-recreate)
- **Standalone scripts** → `feedback_scripts_need_init_db.md` (call `init_db()` / `close_db()` explicitly)
- **SEO work** (any `<head>` / sitemap / robots / JSON-LD / nginx SEO directive / new public route / blog publish / OG image) → `reference_seo_plan.md` → full plan at `docs/SEO.md`. Any task in the `SEO-00..SEO-26` set governed by that doc. Do not free-style schema or ship ad-hoc SEO changes — follow the sequenced tasks.
- **Course / curriculum work** (any change to curriculum templates / generation pipeline / prompts in `generate_curriculum.txt|review_curriculum.txt|refine_curriculum.txt|discover_topics.txt` / admin Pipeline / Topics / Templates UI / new course-format type / quiz / showcase / cohort / streak / cert-bundling routes / tech-shift response) → `reference_course_plan.md` → full plan at `docs/COURSES.md`. Any task in the `COURSE-00..COURSE-28` set governed by that doc. Flagships are manual Opus authoring (paste-upload), never auto-generated.

### Phase 6 exit — this repo specifically

- Rewrite the `## 9. Session state` section below (≤30 lines)
- If a bug was fixed, append a numbered entry to `docs/RCA.md` and update its pattern table if the failure mode is new
- Do **not** `git commit` without explicit user approval (per §5 rule on risky actions)
- If AI enrichment prompts were touched, confirm with the user before overwriting — tuned prompts are never regenerated without approval

### Harness artifacts (Day-1, shipped 2026-04-27)

The orchestration playbook is partly enforced by Claude Code hooks and skills checked into `.claude/`. They are loaded automatically every session.

**Hooks** (in `.claude/settings.json`, scripts under `.claude/hooks/`):

- `pre_commit_secrets.py` — PreToolUse on Bash. Self-filters on `git commit`. Greps the staged diff for 11 secret patterns (AWS, GitHub, Google, OpenAI, Slack, hardcoded literals). Blocks the commit (exit 2) on any hit. Warns (exit 0 + stderr) on TODO/FIXME/XXX in added lines.
- `pre_push_noreply.py` — PreToolUse on Bash. Self-filters on `git push`. Blocks (exit 2) when HEAD's author or committer email is `manishjnvk@live.com` (GitHub email privacy will reject the push anyway). Warns (exit 0) when commits ahead of `@{u}` do not include `docs/HANDOFF.md` — Phase 6 reminder.

**Skills** (in `.claude/skills/`):

- `/aiexpert-phase0 [area]` — replaces the manual Phase 0 read burst. Areas: `ai`, `auth`, `jobs`, `seo`, `courses`, `general`. After reads, prompts the standard 6-item plan (goal / memory / RCA / plan / parallel / diversification) and waits for founder approval.
- `/deploy-vps` — replaces the seven-step manual deploy sequence (verify identity → push → ssh pull → rebuild force-recreate → migration check → smoke test → log tail). Encodes the `feedback_deploy_rebuild.md` rule (never `restart`, always `build + force-recreate`).

**When to use them.** Always invoke `/aiexpert-phase0` at session start instead of recalling the §8 read list manually. Always invoke `/deploy-vps` when deploying to `a11yos-vps` instead of running the seven steps by hand. Hooks fire automatically on every `git commit` and `git push` — no opt-in.

### Agent teams (Day-2, shipped 2026-04-28)

Three named orchestration patterns checked into `.claude/skills/`. Each is a markdown skill that main session invokes when the work matches the trigger; the skill body tells main session which subagents to spawn in parallel, with what contracts, and how to synthesize results.

- **`/research-team <question>`** — 3 parallel Explore agents + main-session synthesis. Use for cross-cutting investigations spanning >2 files (audit-style sweeps, convention checks, drift discovery). Returns a single synthesized answer; raw file content stays in subagents. Main-context savings ~4-5× vs reading directly.
- **`/build-team <contract>`** — N parallel Sonnet implementers + 1 Sonnet test-writer + Opus review (main session). Use for implementation contracts that split cleanly across N files (template rollouts, decorator sweeps, cron clones for Phase B of `AI_PIPELINE_PLAN.md`). Mandatory: every prompt must include exact paths + contract + acceptance test + output format. Refuses to spawn if contract is incomplete.
- **`/adversarial-team <ref>`** — 3 uncorrelated reviewers in parallel: Opus structural + `codex:rescue` adversarial + Sonnet bug-hunt. Mandatory before merge on diffs touching load-bearing paths (see list below). Synthesizes into a numbered concern list with severity rules; logs accept/revise/reject outcome per `CLAUDE.md` §8 Phase 3.

### Trigger map (when each artifact fires)

| Signal | Lever |
|---|---|
| Session start | `/aiexpert-phase0 <area>` |
| Read-only research touching >2 files | `/research-team` |
| Implementation contract splits across ≥2 independent files | `/build-team` |
| Diff touches `backend/app/ai/`, `backend/app/auth/`, `jobs_ingest/`, `jobs_enrich/`, `backend/alembic/versions/`, or any AI prompt | `/adversarial-team` (mandatory before merge) |
| About to push code that needs to land on VPS runtime | `/deploy-vps` |
| Pre-`git commit` (every commit) | hook auto-fires |
| Pre-`git push` (every push) | hook auto-fires |
| Tool-call count >60 OR approach pivoted mid-session | `/clear` and restart from `docs/HANDOFF.md` |

### Cost discipline

The cheap levers (Phase 0 reads, hooks, deploy skill, research-team) fire **always** when the trigger matches — they pay for themselves in seconds. The expensive levers (`build-team` for small work, `adversarial-team` for non-load-bearing diffs) fire only on the strict triggers above; firing them outside trigger conditions is a tuning bug. Main session may invoke any team directly via `Skill(skill: "<name>", args: "...")` — no need to wait for user typing the slash command.

## 9. Session state (update at end of each session)

> Claude Code: rewrite everything below this line at the end of every session. Keep it under 30 lines. This is what the next session reads to know where you left off.

**Last session date:** 2026-04-28 (session 51 — Phase G(a) social draft pipeline)
**Last session summary (S51):** First of two Phase G sessions. Shipped the read-only build slice of `/admin/social`: Alembic `social_posts` table (CHECK constraints + partial UNIQUE index `WHERE status IN ('pending','draft')`) + Pydantic `ReasoningTrail`/`SocialDraftSchema`/`SocialCurateOutput` enforcing §4 invariant #4 + §3.11 hashtag rules + Opus prompt with §3.11 voice rules + ✅/❌ samples + lru_cached `{{TAG_MAP}}` substitution from `share_copy._TAG_DISPLAY` (cache-clean per invariant #1) + `auto_curate_social.sh` daily 06:30 IST cron cloning the proven `auto_summarize_drafts.sh` pattern + read-only `GET /admin/social/drafts` admin page with `html.escape()` defense + 17 schema unit tests (all green).

- **One commit `8c41a0e`** — 13 files / 1707 insertions / 1 deletion. Plus `chmod +x` follow-up for the cron script.
- **Phase 2 gates green:** secrets clean · TODO clean · ast.parse clean · bash -n clean · 17/17 pytest · static integration check across new modules clean.
- **Phase 3 Opus diff review** caught + fixed 2 blocking bugs in main session: (a) shell quoted-heredoc broke `$VAR` expansion → converted to inline `python3 -c "..."`; (b) import script read row IDs from Opus output but prompt doesn't emit them → added `--twitter-id`/`--linkedin-id` CLI flags + most-recent-pending-pair fallback.
- **Phase 4 codex:rescue:** founder real-time override during invocation ("continue, takeover opus"). Now 11/11 empty across S45-S51 — saved memory `feedback_codex_rescue_skip.md`. Escalates urgency on D7 fix-or-drop decision.
- **Sonnet:** 2 parallel worktree-isolated subagents (slice 1 schema + slice 2 cron/router); both reported clean; merged + Phase 3 review caught the 2 bugs above.
- **No RCA** — no bug fixed in committed code; the 2 Phase-3 finds were caught pre-commit so don't qualify per HANDOFF "after fixing a bug" rule.

**Deploy status (verified LIVE):** `8c41a0e` pushed + deployed. Backend rebuilt + force-recreated. Migration applied. Cron + logrotate installed. Smoke clean. **Cron dry-run completed end-to-end on VPS: 14 rounds, 13 productive, queue empty, ~14 min runtime; 22 draft rows persisted (11 sources × 2 platforms), 4 pending (2 hit retry_count=1 from invalid JSON in round 10 — retry mechanism working correctly per spec; 2 mid-flight when log emitted).** Editorial spot-check: drafts hit §3.11 voice rules cleanly. Soft Opus drift on 1 of 22: `/blog` rendered instead of full slug URL — surface for admin review, not blocking.

**Open questions:** (1) **All 8 P0 decisions still pending** including D7 (codex:rescue fix-or-drop, now 11/11 empty) and D8 (repo-eval option pick). (2) **S49 browser smoke** still pending. (3) **Three orphan modifications** (`backend/app/services/jobs_ingest.py` + `backend/tests/test_jobs_cost_opt.py` + `docs/AI_PIPELINE_PLAN.md`) sit unstaged — not from this session.

**Next action — Session 52 (Phase G session b):** review the ~20 drafts now live at `/admin/social/drafts`; ship publish flow (Twitter direct via `twitter_client.post_tweet` once X 403 cleared) + LinkedIn copy-to-clipboard + Mark-as-posted + Discard + Re-publish + 30-day auto-archive sweep + Published + Archived tabs.

**Queued:** S49 browser smoke · 8 P0 decisions · P1-01..08 · P2-01..13 · P3-01..20 · `AI_PIPELINE_PLAN.md` Phase B–F sequenced sessions.

**Agent-utilization footer (S51):**

- Opus: full session — Phase 0 reads parallel; read 8 supporting files for design (share_copy, schemas, prompts dir, admin routers, nginx, jobs_summary_claude.txt, claude_blog_manual.txt, etc); SSH-fetched canonical `auto_summarize_drafts.sh` pattern from VPS; authored `prompts/social_curate.txt` (164 lines, founder-approved before Sonnet fired); wrote 2 detailed Sonnet contracts (one per worktree); Phase 3 line-by-line diff review on 13-file changeset; identified + fixed 2 blocking bugs in main session (don't-delegate-when-self-executing-faster rule); Phase 2 gates; commit with noreply identity; deploy 7-step sequence + cron/logrotate install; this HANDOFF + §9; saved `feedback_codex_rescue_skip.md` memory.
- Sonnet: 2 parallel worktree-isolated subagents (~88K + ~101K tokens, ~200s + ~373s) — slice 1 (Alembic + ORM + Pydantic + tests, all 17 green) + slice 2 (cron + router + scripts + cron entry + logrotate); both reported clean; both required Opus-level fixes in Phase 3.
- Haiku: n/a — no bulk sweeps; targeted Opus reads + SSH execs cheaper.
- codex:rescue: founder real-time override during invocation. **11/11 empty across S45-S51.** Memory entry saved; D7 decision urgency escalated.

---

**Last session date (S49):** 2026-04-27 (session 49 — funnel ribbons land on /jobs /roadmap /blog /blog/{slug})
**Last session summary (session 49):** Closed the S47 carry-over (and fulfilled S48-audit's option-2 recommendation): shipped the 4 anonymous-discovery subscribe ribbons. Anonymous = 4 channel buttons → 302 to login → /account pre-checked. Logged-in = 4 inline checkboxes reflecting `notify_*` state, toggle fires PATCH /api/profile with optimistic UI + toast. Dismiss persists 30 days per surface via localStorage. Pre-Phase-1 recon caught a meaningful design improvement: rather than 4× duplicated SSR ribbons (4 different brace/escape conventions across f-string + plain-string + 2 Jinja files, RCA-024/027 risk × 4), shipped one shared `frontend/subscribe-ribbon.{css,js}` asset pair + a 3-line insertion per surface. Routing flipped from "parallel Sonnet × 4" to "all Opus, no subagents" per playbook's "don't delegate when self-executing is faster" rule.

- **1 commit, +503 lines:** `f405b25` (feat(funnel) subscribe ribbons) · 6 files · 2 new (subscribe-ribbon.css 247, subscribe-ribbon.js 242) · 4 modified (jobs.py +4, blog.py +3, blog/post.html +3, tracks/hub.html +4). All inserts pure HTML literals, zero `{` `}` chars in new lines.
- **Phase 2 gates green:** secrets scan clean · node --check on subscribe-ribbon.js parses · Python ast.parse on routers OK · TestClient end-to-end render of all 4 surfaces returns 200 with asset link + ribbon div + JS tag · git stash round-trip confirmed 3 pagination test failures pre-existing (S45 baseline, NOT introduced by S49).
- **Sonnet:** n/a — design-pivot collapsed work to ≤30 lines across hot-cached files; subagent cold-start would have outweighed direct typing.
- **codex:rescue:** n/a — none of the 3 touched paths in §8's strictly-mandatory list (no auth/AI/Alembic/jobs-classifier).
- **No RCA** — clean feature ship, no bug fixed.

**Deploy status:** Live at `f405b25`. VPS HEAD `f405b25e82c795fd338d273f9d531dac08fff504` matches local. Backend container healthy. `/subscribe-ribbon.css` + `/subscribe-ribbon.js` serve 200 over the wire (nginx `\.(js|css)$` regex auto-served — no nginx update needed). All 4 surfaces curl-smoked: 200 + correct `data-surface` value + asset references. `/api/profile/subscribe-intent?channel=jobs` returns 302 anonymously.

**Open questions:** (1) **Browser-side interactivity validation pending** — server-side render verified end-to-end; remaining checks (button-click → 302, checkbox flip → PATCH → toast, dismiss → reload, 375px viewport) need a real browser. (2) **S48-audit deliverables sit as orphan untracked files** — `docs/AUDIT_2026-04.md`, `docs/AUDIT_TASKS.md`, `docs/PLAN_TIERED_CLAUDE_ROUTING.md` from a parallel session; founder decides whether to commit. (3) **Brevo 300/day cap** still latent (audit B4). (4) **`/blog/topic/{slug}`** doesn't have the ribbon (kept scope tight to the 4-surface list).

**Next action — Session 50:** browser smoke + iteration if anything looks off; otherwise pick from S48-audit P0 decisions (~30 min, unblocks P1/P2 sequence) OR feature-roadmap items (SEO-21 q2 post · SEO-26 quiz landing · COURSE-01..03 Phase A).

**Queued:** browser smoke (S50) · audit P0 decisions × 7 + P1 tasks × 8 (in `docs/AUDIT_TASKS.md`) · S47's Phase B engagement upgrades (cron time, image attach, quotable hook) · pagination test fix · SEO-21 q2 / 5+6 · **SEO-26 quiz landing** (worktree + codex:rescue for `quiz_outcomes` migration) · COURSE-01..03 Phase A · COURSE-04+05 Phase B MVP · separate commit for `docs/COURSES.md` from S43.

**Agent-utilization footer:**

- Opus: full session — Phase 0 reads (CLAUDE.md + HANDOFF + RCA + memory parallel); pre-Phase-1 recon across 7 files (jobs.py, blog.py, post.html, hub.html, profile.py, account.html, nginx.conf) to map insertion seams + login-state idiom + brace conventions; design-pivot decision (Sonnet × 4 → all Opus shared-asset shape) with rationale; ~500-line subscribe-ribbon.{css,js} authoring with brand tokens + a11y + mobile + dismiss localStorage + optimistic-UI PATCH + toast; 4 surface inserts (12 lines across 4 files); Phase 2 gates (secrets + ast.parse + node --check + TestClient render); git-stash round-trip; Phase 3 line-by-line review against 15 audit criteria; 1 bundled commit with noreply identity; VPS deploy + HEAD verification + 4-surface curl smoke + asset 200 + 302 funnel; this HANDOFF + §9.
- Sonnet: n/a — consciously skipped per "don't delegate when self-executing is faster" rule (≤30 lines across hot-cached files).
- Haiku: n/a — no bulk sweeps; targeted Opus reads on 7 specific files cheaper than Haiku round-trip.
- codex:rescue: n/a — touched paths not in §8's strictly-mandatory list. Helper-runtime continues empty (now 9 attempts in a row across S45/46/47). Will retry on SEO-26 + COURSE-23/24.
