# SEO.md — AutomateEdge SEO Implementation Plan

> Living document. Rewrite the **Change log** at the bottom after every SEO-related commit.
> Read this file before any change to `<head>`, sitemap, robots, `nginx.conf` SEO-adjacent directives, or anything that emits `application/ld+json`.

## 0. Session kickoff — read this first every session

**Read this file at the start of every session** as part of the Phase 0 warm-start burst (listed in `CLAUDE.md` §8). You do not need to re-read the whole plan — scan this §0 + the Task status board in §0.2 + the most recent Change-log entry at the bottom. That gives you current state in ~60 seconds.

**When SEO work is in scope for the session**, also read the specific task sections that apply (§4 for implementation tasks, §5 for content strategy). If you're shipping a `Course` / `Article` / `FAQPage` / `BreadcrumbList` / `JobPosting` JSON-LD block, re-read §4 SEO-05 or SEO-06 or SEO-08 — schema properties have specific requirements Google enforces and small typos silently disqualify the page from rich results.

### 0.1 Trigger conditions — when this plan governs the work

Any of these conditions means the session must follow this plan before landing changes:

- Editing `<head>` on any page (title, meta, link rel=canonical, og:*, twitter:*, JSON-LD)
- Editing `nginx.conf` in ways that affect `robots.txt`, cache headers, redirects, or the IndexNow key route
- Adding, removing, or modifying any sitemap generator
- Adding a new public-facing route (must be added to sitemap + consider canonical + schema)
- Publishing or editing a blog post (pillar posts must pass the SEO-21 10-point quality bar before publish)
- Generating or modifying OG images (SEO-11 route pattern must be respected)
- Any change to Course / Article / FAQPage / BreadcrumbList / JobPosting / VideoObject / HowTo / EducationalOccupationalCredential JSON-LD
- Any task from the `SEO-00` … `SEO-26` set below

### 0.2 Task status board

Update the Status column as tasks move. `⬜ pending` → `🟡 in progress` → `✅ done`. Add a `🔒 blocked (reason)` state if waiting on something external (e.g. SEO-23 blocked on ≥5 testimonials).

| ID | Priority | Task | Status |
|---|---|---|---|
| SEO-00 | P0 | GSC + Bing connect, baseline metrics | 🟡 partial — GSC + Bing properties verified, sitemap submitted to both (2026-04-23); 7-day baseline recording pending data accumulation |
| SEO-01 | P0 | robots.txt (Disallow /admin /api /account /share/ /og/) | ✅ done (2026-04-24) — edge-served merged robots.txt confirmed live: CF-managed AI-bot block (ClaudeBot/GPTBot/Bytespider/Amazonbot/CCBot/Applebot-Extended/Google-Extended/meta-externalagent `Disallow: /`) + our custom `User-agent: *` block with all 5 Disallows + `Sitemap: https://automateedge.cloud/sitemap_index.xml` — verified via Googlebot UA GET (200, 1900 bytes) |
| SEO-02 | P0 | Expand sitemap: sub-sitemaps by resource type + image extensions | ✅ done |
| SEO-03 | P0 | Complete `<head>` on `/` (canonical, og:*, twitter:*, author) | ✅ done — og:image + summary_large_image landed with SEO-11 |
| SEO-04 | P0 | SSR content scaffold for landing page (preserves rule 8) | ✅ done |
| SEO-05 | P0 | Course + ItemList + FAQPage JSON-LD on landing (full property set) | ✅ done |
| SEO-06 | P0 | Article JSON-LD on every blog post | ✅ done |
| SEO-07 | P0 | Activate IndexNow (set key, wire publish events) | ✅ done (2026-04-23) — key provisioned on VPS; pings on blog/jobs/cert publish |
| SEO-08 | P1 | BreadcrumbList JSON-LD everywhere breadcrumbs render | ✅ done (/blog + /jobs); /profile + /verify out of scope after audit |
| SEO-09 | P1 | Blog RSS feed at /blog/feed.xml | ✅ done |
| SEO-10 | P1 | Server-rendered jobs hub pagination + rel=prev/next | ✅ done (2026-04-23) — /jobs?page=N SSR, canonical + rel=prev/next, footer UI, sitemap-pages enumerated |
| SEO-11 | P0-adj | Dynamic OG image generator /og/{type}/{slug}.png | ✅ done (course/roadmap/blog/jobs shipped; week/vs/cert deferred per spec) |
| SEO-12 | P1 | EducationalOccupationalCredential on /verify/{id} | ✅ done (2026-04-23) |
| SEO-13 | P1 | Missing canonicals on blog index / profile / leaderboard / verify / account | ✅ done |
| SEO-14 | P1 | WebSite + SearchAction (deferred — needs /search endpoint) | 🔒 blocked (no /search) |
| SEO-15 | P2 | FAQPage on roadmap landing | ✅ done (2026-04-23) — visible FAQ section mirrors existing JSON-LD |
| SEO-16 | P2 | Brotli compression in nginx | ✅ done (via Cloudflare edge) — origin nginx br redundant; CF serves Content-Encoding: br |
| SEO-17 | P2 | WebP/AVIF images + font-display:swap | ✅ done — all Google Fonts URLs carry &display=swap; site has no raster above-fold imagery |
| SEO-18 | P2 | Critical CSS extraction (only if LCP > 2.5s after SEO-04) | 🔒 blocked (gated on Lighthouse) |
| SEO-19 | P0-adj | 10 programmatic /vs/{a}-vs-{b} comparison pages | ✅ done (2026-04-23) — 10 pages live w/ Article+FAQPage+DefinedTerm+BreadcrumbList; 1000-1150 words (below 1500 target, iterate on feedback) |
| SEO-20 | P1 | 30 per-track quintet pages (skills, tools, certs, salary, projects, career-path) | ✅ done (2026-04-24) — 30 pages live across 5 tracks (generalist, ai-engineer, ml-engineer, data-scientist, mlops); each page emits Article + section-specific schema (ItemList for skills/tools/projects/certs, HowTo for career-path, Dataset for salary) + BreadcrumbList + FAQPage; sitemap-pages enumerates all 36 URLs (1 hub + 5 track hubs + 30 sections); nginx allowlist regex; 154 new tests pass |
| SEO-21 | P1 | Pillar blog cluster with 10-point validator-enforced quality bar | 🟡 1 of 6 posts shipped (2026-04-24) — validator + template wire-up now complete (`post.html` emits FAQPage + DefinedTermSet JSON-LD from payload; `_ALLOWED_TAGS` covers `<table>` family; `_render_post` threads `faqs` + `defined_terms`). First pillar post authored: [docs/blog/03-ai-engineer-vs-ml-engineer.json](./blog/03-ai-engineer-vs-ml-engineer.json) targeting q6 — 3134 words, 50-word snippet paragraph, 10 H2s, 46 internal links, 7 trusted citations, 10 FAQs, 1 comparison table, 4 DefinedTerms. Validator: `ok=True, 0 errors`, 2 editorial warnings (non-blocking). Pending: admin publish via `/admin/blog` once backend deploy lands. 5 posts remaining (q7, q2, q4, intent-gap q3/q4, intent-gap q10). |
| SEO-22 | P1 | VideoObject schema on YouTube-embedding posts | 🟡 foundation (2026-04-24) — `build_video_object()` emitter + `validate_videos_metadata()` gate shipped in `blog_validator.py`; duration coercion accepts ISO-8601, `mm:ss`, `h:mm:ss`; `validate_payload` blocks publish when `youtube_ids` lack matching cached metadata. Blog post template wire-up + first embedded video follow with the first pillar post. |
| SEO-23 | P2 | aggregateRating + Review (gated on ≥5 real testimonials) | 🔒 blocked (threshold) |
| SEO-24 | P1 | Hub ItemList schema listing all roadmap tracks | ✅ done (2026-04-24) — `/roadmap` hub renders ItemList enumerating all 5 tracks (numberOfItems + position + url + name) + BreadcrumbList; landed jointly with SEO-20 |
| SEO-25 | P1 | Trusted-sources allowlist + E-E-A-T enforcement in blog validator | ✅ done (2026-04-24) — `backend/data/trusted_sources.json` with 42 domains across 6 categories (papers, lab-docs, framework-docs, statistics, academic, textbook, standards); `is_trusted_domain()` uses safe suffix-match (rejects `fakemeta.com` vs `meta.com`); pillar validator enforces ≥5 trusted citations before publish |
| SEO-26 | P2 | /start interactive quiz landing with personalized plan output | ⬜ pending |

**Next action** (always — source of truth for what to pick up next): SEO-21 first pillar post (q6) authored + validator-clean 2026-04-24 — sits at [docs/blog/03-ai-engineer-vs-ml-engineer.json](./blog/03-ai-engineer-vs-ml-engineer.json), pending backend deploy + admin publish to go live. Highest-leverage next deliverable: **second pillar post** `/blog/learn-ai-without-cs-degree-2026` (q7 — Quora in top 3, thin SERP; schema stack Article + FAQPage + HowTo, Review still blocked on SEO-23 threshold). After that: q2 / q4 / intent-gap q3/q4 / intent-gap q10 — one per session — then SEO-26 quiz landing (worktree + codex:rescue for the Alembic migration). SEO-09, SEO-13, SEO-08, SEO-06, SEO-05, SEO-04, SEO-01, SEO-19, SEO-20, SEO-24, SEO-25 all shipped — see Change log at bottom.

### 0.3 Orchestration notes

- **Load-bearing paths touched by this plan** (require worktree isolation + Opus diff review per `CLAUDE.md` §8): SEO-23 (Alembic migration for testimonials), SEO-26 (Alembic migration for quiz outcomes), any task that rewrites an AI enrichment / evaluation prompt (none currently).
- **Sonnet subagent-eligible** (mechanical, contract is specified here): SEO-01, SEO-02, SEO-06, SEO-08, SEO-09, SEO-12, SEO-13, SEO-15. Give the subagent the specific `SEO-NN` section + the acceptance criteria verbatim.
- **Opus-only** (judgment + rich content): SEO-04, SEO-05, SEO-21 (pillar-post writing), SEO-25 allowlist curation.
- **Parallel-safe pairs** (fire together in one message): (SEO-01, SEO-03), (SEO-08, SEO-09, SEO-13) — all independent, all mechanical.

## 1. Goal & success metrics

**Goal:** Rank on Google page 1 for a targeted set of AI-learning queries within 6 months of P0 completion, and convert branded + long-tail search traffic into learner signups and verified-credential shares.

**Targets (6-month horizon from P0 ship):**

| Metric | Baseline | 90-day target | 180-day target | Source |
|---|---:|---:|---:|---|
| Google-indexed URLs | ~unknown (jobs-only sitemap) | 100% of sitemap URLs | 100% + blog cluster | Google Search Console (GSC) |
| Impressions / day (site-wide) | baseline TBD on GSC connect | 2× baseline | 10× baseline | GSC |
| Avg. position for "AI learning roadmap" cluster | off top 100 | top 30 | top 10 | GSC |
| CTR on job detail pages | TBD | ≥ 3% | ≥ 5% | GSC |
| Core Web Vitals — LCP on `/` | TBD (likely > 2.5s, CSS-blocking) | < 2.5s on mobile | < 2.0s on mobile | PageSpeed Insights |
| Referring domains | TBD | +10 | +50 | GSC "Links" report |

**First action (do before any implementation):** connect Google Search Console + Bing Webmaster Tools to `automateedge.cloud` and record the baseline in the Change log below. No SEO investment should precede instrumentation — otherwise we can't tell what worked.

## 2. Constraints & non-negotiables

These override any SEO "best practice" from outside sources. If a tactic conflicts, the constraint wins.

1. **Frontend stays a single file that runs standalone from disk** (CLAUDE.md §5 rule 8). SEO work on [frontend/index.html](../frontend/index.html) must preserve file:// execution. No build step, no bundler, no SPA framework.
2. **No paid SEO tools, no paid backlinks, no SEO agencies.** Use Google Search Console, Bing Webmaster Tools, Lighthouse / PageSpeed Insights, `curl`. That's it.
3. **Never break `/admin` or `/api` privacy.** Every SEO change must keep `Disallow: /admin` and `Disallow: /api` enforced, and never surface admin-only data in meta tags or JSON-LD.
4. **JSON-LD additions never leak PII.** Public profiles only if `user.public_profile = True`. Job contact emails never surfaced. Learner progress data never in schema.
5. **AI prompt assets are tuned; never regenerated without user approval** (CLAUDE.md §8). If an SEO change would rewrite an AI enrichment or evaluation prompt, stop and confirm.
6. **Load-bearing paths require Opus diff review + worktree isolation** for any subagent edit (CLAUDE.md §8). Of the paths this plan touches, `backend/alembic/versions/` is load-bearing. Everything else is standard diff review.
7. **No secrets in code.** `INDEXNOW_KEY`, analytics IDs, and GSC verification tokens all go in `.env`. The IndexNow key file served at `/{key}.txt` is generated from the env var by the existing handler at [backend/app/routers/jobs.py:723](../backend/app/routers/jobs.py#L723).
8. **Reversibility.** Every schema change (JSON-LD, meta tags) must be removable in one revert without data loss.

## 3. Current baseline (from 2026-04-21 audit)

Already in place — do not redo:

- **JobPosting JSON-LD** on `/jobs/{slug}` ([backend/app/routers/jobs.py:454-495](../backend/app/routers/jobs.py#L454-L495))
- **Dynamic sitemap** at `/sitemap_index.xml` → `/sitemap-jobs.xml` (10k cap, 1h cache)
- **IndexNow endpoint** at `/{key}.txt` — needs `INDEXNOW_KEY` in `.env` to activate
- **Expired-job `noindex`** ([backend/app/routers/jobs.py:510](../backend/app/routers/jobs.py#L510))
- **nginx gzip**, 1-year cache on `/assets/`, CSP headers, HTTP/2
- **SSR for blog, jobs, verify, share, profile, leaderboard**
- **Shared nav + breadcrumbs** on all SSR pages
- **Slug-based URLs** everywhere (no query strings in indexed paths)
- **og:title / og:description** on most SSR routes
- **lang="en", viewport, theme-color, UTF-8** on [frontend/index.html](../frontend/index.html)

Gaps the plan below addresses:

- Home page `/` and `/account` render client-side; initial HTML has no content
- No `robots.txt`
- Sitemap only covers jobs (missing blog, pages, certs, public profiles)
- No `Course`, `LearningResource`, `Article`, `BreadcrumbList`, `WebSite`, `FAQPage`, or `EducationalOccupationalCredential` schemas
- `og:image`, `og:url`, `canonical`, `twitter:*` missing on `/` and several routes
- `INDEXNOW_KEY` not set
- Jobs hub pagination is client-side only past the first 50
- No Brotli (only gzip)
- No WebP/AVIF
- Inlined ~2000-line CSS block in `index.html` blocks render — likely blows LCP

## 3.5. Competitive intelligence (research 2026-04-21)

Four parallel agents audited direct competitors, MOOC platforms, content competitors, and the live SERP for our 10 target queries. Full raw reports live in the session 25 conversation transcript; key findings that **change this plan** are captured here.

### What roadmap.sh actually does (and what they miss)

On `/ai-engineer` and `/ai-data-scientist` roadmap.sh ships:

- `<script type="application/ld+json">` with an **array of `[BlogPosting, FAQPage]`** — **not** `Course`
- `og:image` at a **dynamic** `/og/roadmap/{slug}` route; `Disallow: /og/` in robots.txt
- FAQ with **16 Q&A pairs** on `/ai-data-scientist` (9 of them `"What is the difference between X and Y?"` — aggressive keyword-harvesting for their 31 `/vs-*` pages)
- Per-roadmap landing quintet: `/<roadmap>/{career-path,skills,tools,lifecycle,projects}` — programmatic SEO at scale
- ~218 internal links per roadmap page
- Interactive SVG is **JS-injected** — topic labels (Python, RAG, Embeddings) only appear as prose, not as structured content

What they **don't** ship (our differentiation levers):

- No `Course`, `ItemList`, `BreadcrumbList`, or `WebSite/SearchAction` schema anywhere
- No JSON-LD at all on `/guides/*` articles
- No `<image:image>` / `<video:video>` sitemap extensions, no `Sitemap:` directive in robots
- No `<lastmod>` on ~half their sitemap entries
- Missing `/<roadmap>/{certifications,salary}` from the quintet

### What Coursera + edX do on Course schema (that we must match for rich results)

Google enforces `hasCourseInstance` with ISO 8601 `courseWorkload` since 2024 — without it, no Course rich snippet. Full property set to populate:

| Property | Coursera example | edX example | Our plan |
|---|---|---|---|
| `hasCourseInstance.courseWorkload` | `"PT33H19M51S"` | `"PT20H"` via `courseSchedule.duration` | `"PT200H"` total (24 weeks × ~8h) |
| `syllabusSections[].timeRequired` | `"PT7H4M54S"` per week | — | `"PT8H"` per week, 24 entries |
| `teaches` | string array of outcomes | string array of 12 skills | Harvest from our week `outcomes` field |
| `coursePrerequisites` | string | string | `"Basic Python + high-school algebra"` |
| `offers.category` | `"Partially Free"` | `"Partially Free"` + `"Paid"` | `"Free"` + `"price":"0"` |
| `aggregateRating` | `{ratingValue:4.90,ratingCount:32279}` | absent on detail | Defer until ≥5 real testimonials |
| `review` array inline | 5 inline Review objects | — | Defer |
| `totalHistoricalEnrollment` | `1173748` | `1583912` | Connect to our learner count once meaningful |
| Sibling FAQPage block | separate `<script>` | separate `<script>` | Separate block, not `@graph` |

### What content competitors do on the blog front

Average pillar-post length across 7 top-ranking articles = ~3,580 words (DataCamp outlier at 6,500). Internal-link density 40-60 per post. But only **1 of 7 uses `FAQPage` schema**; **0 of 7 use `HowTo`** despite step-based structure; **0 use `VideoObject`** even when embedding YouTube. That's free rich-result real estate.

### SERP reality for our 10 target queries

Dominated / poor ROI: `AI learning roadmap`, `AI engineer roadmap`, `machine learning roadmap` (roadmap.sh + GitHub lock top 3); `free AI course`, `AI certification free` (Coursera + Udemy + Google own course carousels); `how to learn AI` (ai.google owns it).

Beatable / go-after:
- **`AI engineer vs ML engineer`** — Medium personal posts in top 3, featured snippet up for grabs
- **`learn AI without CS degree`** — Quora in top 3, thin SERP
- **`AI learning roadmap 2026`** — no entrenched winner on the year-qualified variant
- **`how to learn AI from scratch`** — Manning redirect + forum threads in top 10

Intent-gaps nobody answers well: "salary + hiring data for AI engineer vs ML engineer 2026", "minimum math actually required", "free AI certs employers recognize", "is the 2024 roadmap still valid in 2026".

### How this changes the plan

1. **Dynamic OG images move from P1 → P0-adjacent** — roadmap.sh has them; it's competitive parity, not polish. Rework SEO-11 path pattern to `/og/{type}/{slug}.png` matching their structure and add `Disallow: /og/` to SEO-01.
2. **SEO-05 Course schema gets the full Coursera-grade property set** (listed above) — this is our single biggest differentiator vs roadmap.sh who ships none of it.
3. **New SEO-19: programmatic comparison pages** (`/ai-engineer-vs-ml-engineer`, etc.) — directly targets the most beatable query (`AI engineer vs ML engineer`) with featured-snippet + FAQPage + DefinedTerm schema.
4. **New SEO-20: per-track quintet pages** (skills, tools, certifications, salary, projects) — parity with roadmap.sh plus the two slugs they miss.
5. **New SEO-21: blog content cluster with hard quality bar** — 3000-word minimum, FAQPage + HowTo where applicable, first-paragraph definitional snippet, 40+ internal links, 5+ authoritative external links including arXiv / official lab docs.
6. **New SEO-22: VideoObject on any post with YouTube embed** — 0/7 competitors do this.
7. **New SEO-23: Review harvesting** once we cross the 5-genuine-testimonials threshold.
8. **New SEO-24: `ItemList` hub schema** listing all roadmap tracks (mirror edX).
9. **New SEO-25: E-E-A-T citation audit** — arXiv / Anthropic / OpenAI / Google AI / DeepMind / Papers-with-Code citations enforced per pillar post.
10. **New SEO-26: `/start` interactive quiz** landing page — targets `how to learn AI from scratch` with personalized-plan output (leverages existing product).

## 4. Implementation sequence

**Read this before starting any task.** Every task below is atomic, has a single owner-turn to complete, and lists its files, acceptance test, and dependencies. Execute in order unless a later task's **Depends on** field is empty — independent tasks may run in parallel Sonnet subagents per the orchestration playbook.

Priorities:

- **P0** — biggest ranking lift or unblocks other tasks. Target: 1 week.
- **P1** — CTR / rich-result / CWV improvements. Target: 1 additional week.
- **P2** — polish and infrastructure. Target: opportunistic.
- **Content** — ongoing; starts once P0 lands.
- **Ops** — recurring; starts immediately on GSC connect.

### SEO-00 — Instrument before you invest (P0)

**Depends on:** nothing. Do this first.

**Work:**

1. Create GSC property for `automateedge.cloud`. Verify via DNS TXT record (preferred — survives deploys) or HTML file at `/google{token}.html` served by nginx.
2. Create Bing Webmaster Tools property. Same verification approach.
3. Submit `https://automateedge.cloud/sitemap_index.xml` in both consoles.
4. Record 7-day baseline (impressions, clicks, avg position, indexed pages) in the Change log at the bottom of this file.

**Files touched:** `nginx.conf` only if using HTML-file verification (add one `location = /google{token}.html` block). `.env` if storing verification token as env var.

**Acceptance:**

- Both consoles show "Ownership verified."
- Sitemap submission status is "Success" in both consoles.
- Baseline line appended to Change log.

---

### SEO-01 — robots.txt (P0)

**Depends on:** nothing.

**Work:** Serve `/robots.txt` statically from nginx (preferred) or from a FastAPI route.

**Contents:**

```text
User-agent: *
Disallow: /admin
Disallow: /api
Disallow: /account
Disallow: /share/
Disallow: /og/
Allow: /

Sitemap: https://automateedge.cloud/sitemap_index.xml
```

Rationale for each `Disallow`: `/admin` and `/api` are implementation surfaces. `/account` is the authed SPA. `/share/` contains per-milestone learner links intended for social share, not search — allow them via direct link but not via crawl (prevents accidental PII aggregation). `/og/` is the dynamic OG-image renderer (SEO-11) — images are referenced via `og:image` meta tags on actual pages, and should not crawl as standalone URLs (matches roadmap.sh's pattern). The explicit `Sitemap:` directive is a detail roadmap.sh skips — including it primes new search engines that don't auto-probe `/sitemap.xml`.

**Files touched:**

- [nginx.conf](../nginx.conf) — add `location = /robots.txt { ... }` block OR
- `backend/app/routers/seo.py` (new, ~30 lines) — FastAPI route returning the text

Prefer the nginx approach; zero backend load.

**Acceptance:**

- `curl -sI https://automateedge.cloud/robots.txt` → 200, `Content-Type: text/plain`
- Body matches the contents above
- GSC → `Settings` → `robots.txt report` shows "Fetched."

---

### SEO-02 — Expand sitemap coverage (P0)

**Depends on:** SEO-00.

**Work:** Extend [backend/app/routers/jobs.py:688-720](../backend/app/routers/jobs.py#L688-L720) (or split into `backend/app/routers/seo.py` for clarity). Generate sub-sitemaps by resource type and reference them from `sitemap_index.xml`. Coursera's 18-sub-sitemap split is the reference pattern — per-resource `lastmod` gives Google a clean freshness signal.

| Child sitemap | URLs included | lastmod source |
|---|---|---|
| `sitemap-jobs.xml` (existing) | `/jobs/{slug}` for `status='published'` and not expired | `Job.updated_at` |
| `sitemap-blog.xml` (new) | `/blog`, `/blog/{slug}` for each published post | `post.updated_at` or file mtime |
| `sitemap-pages.xml` (new) | `/`, `/jobs`, `/leaderboard`, `/verify` | file/commit mtime |
| `sitemap-certs.xml` (new) | `/verify/{credential_id}` for each issued credential | `cert.issued_at` |
| `sitemap-profiles.xml` (new) | `/profile/{user_id}` **only where `user.public_profile = True`** | `user.updated_at` |
| `sitemap-roadmap.xml` (new, SEO-19+20 prereq) | `/roadmap`, `/roadmap/{track}`, `/roadmap/{track}/{skills,tools,certifications,salary,projects}`, `/vs/{a}-vs-{b}` pages | commit mtime of source data file |

All child sitemaps gzip-compressible; keep `Cache-Control: public, max-age=3600`.

**Sitemap extensions — adopt what roadmap.sh skips:**

- Add `xmlns:image="http://www.google.com/schemas/sitemap-image/1.1"` namespace on child sitemaps that reference rich images. For blog, jobs, and roadmap entries, embed `<image:image><image:loc>https://automateedge.cloud/og/{type}/{slug}.png</image:loc></image:image>` — feeds Google Images and reinforces the dynamic OG generator (SEO-11).
- Emit `<lastmod>` on **every** URL (roadmap.sh misses this on ~half their entries — easy quality win).
- Keep under 50k URLs or 50MB uncompressed per child sitemap; split further if a single resource class (jobs likely) crosses either cap.

**Files touched:** `backend/app/routers/jobs.py` or new `backend/app/routers/seo.py`, plus `backend/app/main.py` for router include if new file.

**Acceptance:**

- `curl https://automateedge.cloud/sitemap_index.xml` lists all five child sitemaps
- Each child sitemap returns valid XML (parseable with Python `xml.etree`)
- URL counts roughly match DB: `SELECT COUNT(*) FROM jobs WHERE status='published' AND valid_through > now()` = jobs sitemap entry count
- GSC submission of each child sitemap returns "Success"
- No URL from a `public_profile=False` user appears in `sitemap-profiles.xml` (write a pytest for this)

---

### SEO-03 — Complete `<head>` on the landing page (P0)

**Depends on:** nothing.

**Work:** In [frontend/index.html](../frontend/index.html) `<head>`, add or complete:

- `<link rel="canonical" href="https://automateedge.cloud/">`
- `<meta property="og:url" content="https://automateedge.cloud/">`
- `<meta property="og:image" content="https://automateedge.cloud/assets/og-default.png">` (confirm file exists; if not, generate in SEO-11)
- `<meta property="og:image:width" content="1200">` / `height="630"`
- `<meta name="twitter:card" content="summary_large_image">`
- `<meta name="twitter:title" content="...">` (may reuse og:title)
- `<meta name="twitter:description" content="...">`
- `<meta name="twitter:image" content="...">` (same as og:image)
- `<meta name="author" content="AutomateEdge">`
- `<link rel="alternate" type="application/rss+xml" title="AutomateEdge Blog" href="/blog/feed.xml">` (RSS feed shipped in SEO-09)

**Files touched:** [frontend/index.html](../frontend/index.html) only.

**Acceptance:**

- View-source shows all tags above
- [opengraph.xyz](https://www.opengraph.xyz/) preview for `https://automateedge.cloud/` renders title + description + image
- Twitter Card Validator renders summary_large_image
- Rule 8 preserved: `file:///path/to/frontend/index.html` still loads and functions (relative vs absolute URL handling — use `<meta>` tags with absolute URLs, which are harmless offline)

---

### SEO-04 — SSR content scaffold for the landing page (P0 — highest ROI)

**Depends on:** SEO-03 (do after so the head is right when we add content).

**Problem:** [frontend/index.html](../frontend/index.html) currently delivers an empty shell; the roadmap content is built entirely by JS against client-side state. Googlebot renders JS but ranks pages whose content is in the initial HTML much more heavily. Bing and social-preview bots don't execute JS at all.

**Approach (recommended — preserves rule 8):** embed a static, server-rendered-but-checked-in scaffold of the roadmap inside `index.html`. On JS mount, the existing renderer replaces the scaffold with the interactive version.

```html
<main id="app" data-roadmap-root>
  <noscript>...same scaffold, visible fallback...</noscript>
  <section data-roadmap-scaffold>
    <!-- 24 weeks: H2 with week title, P with one-line description, UL of resource titles -->
  </section>
</main>
<script>
  // existing renderer removes [data-roadmap-scaffold] before mounting
</script>
```

**Contents of scaffold (per week):**

- `<h2>Week N: {topic}</h2>`
- `<p>{one-line description}</p>`
- `<ul>` of 3-5 resource titles (no links to external resources from the scaffold — those stay client-side to preserve the progressive-enhancement contract)
- `<a href="#week-{N}">Jump to week N</a>` as anchor target

Generate the scaffold HTML once from the same JSON the JS already consumes. Commit it as static HTML in `index.html` — no build step. When the curriculum refresh pipeline runs (quarterly), regenerate this scaffold and commit alongside the JSON.

**Alternative (deferred):** server-render via a FastAPI route at `/` using Jinja2. Cleaner, but requires reworking the nginx `location = /` block currently serving the static file, and breaks rule 8. Only do this if the scaffold approach proves insufficient after 90 days.

**Files touched:**

- [frontend/index.html](../frontend/index.html) — add scaffold HTML, modify mount JS to remove scaffold on mount
- `scripts/generate_roadmap_scaffold.py` (new) — reads the roadmap JSON, writes the scaffold HTML block for paste-in (or inline replacement via a marker comment)

**Acceptance:**

- `curl -s https://automateedge.cloud/ | grep -c "<h2>Week"` returns 24
- `curl -s https://automateedge.cloud/ | wc -c` returns at least 40 KB (scaffold is non-empty)
- Rule 8: `open frontend/index.html` from disk still works identically
- Visual: on normal JS-enabled load, no flash of scaffold content before JS renders (scaffold hidden via `.roadmap-scaffold { display: none }` inside a `<style>` block that the JS renderer flips, OR scaffold removed synchronously at top of body-end script)
- Lighthouse Performance on `/` does not regress more than 5 points (scaffold adds bytes but is plain HTML, should be gzip-tiny)

---

### SEO-05 — `Course` + `ItemList` JSON-LD on the landing page (P0)

**Depends on:** SEO-04 (so there's crawlable content for the schema to describe).

**Key differentiation lever:** roadmap.sh ships **zero** `Course` schema on any of their pages (verified 2026-04-21 — they use `[BlogPosting, FAQPage]` only). Coursera and edX ship full Course schema and capture course rich-results in SERP. We're the free, tuned-for-learners alternative and can own the `Course` rich snippet for "AI roadmap" queries if we populate the schema correctly. **Every property in the Coursera reference below is required to pass Google's Course rich-result eligibility check since the 2024 spec tightening.**

**Work:** Add three separate `<script type="application/ld+json">` blocks to [frontend/index.html](../frontend/index.html) `<head>` (separate blocks, not `@graph` — matches Coursera / edX pattern).

1. **`Course`** — describes the full 24-week roadmap with full Coursera-grade property set:

   ```json
   {
     "@context": "https://schema.org",
     "@type": "Course",
     "name": "AI Generalist Roadmap — 24-Week Interactive Study Plan",
     "description": "Free, self-paced 24-week roadmap to become an AI generalist. Personalized by AI, refreshed quarterly with trending topics from top universities and practitioner sources.",
     "url": "https://automateedge.cloud/",
     "image": "https://automateedge.cloud/og/course/generalist.png",
     "inLanguage": "en",
     "educationalLevel": "Beginner to Intermediate",
     "provider": {
       "@type": "Organization",
       "name": "AutomateEdge",
       "sameAs": "https://automateedge.cloud",
       "logo": {"@type": "ImageObject", "url": "https://automateedge.cloud/assets/logo.png"}
     },
     "offers": [
       {"@type": "Offer", "price": "0", "priceCurrency": "USD", "category": "Free"}
     ],
     "teaches": [
       "Python fundamentals for machine learning",
       "Linear algebra and statistics for AI",
       "Classical ML with scikit-learn",
       "Deep learning with PyTorch",
       "LLMs, prompting, RAG, and agents",
       "MLOps and production deployment"
     ],
     "coursePrerequisites": "Basic Python familiarity and high-school algebra. No CS degree required.",
     "hasCourseInstance": {
       "@type": "CourseInstance",
       "courseMode": "Online",
       "courseWorkload": "PT200H",
       "instructor": {"@type": "Organization", "name": "AutomateEdge"}
     },
     "syllabusSections": [
       {"@type": "Syllabus", "name": "Week 1: ...", "description": "...", "timeRequired": "PT8H"}
     ],
     "hasPart": [
       {"@type": "Course", "@id": "https://automateedge.cloud/#week-1", "name": "Week 1: ..."}
     ]
   }
   ```

   **Property-by-property rationale** (why each is non-negotiable):

   - `hasCourseInstance.courseWorkload` — Google's **required** field since 2024. Without ISO 8601 duration, no rich snippet. Use `PT200H` for full 24-week plan (≈8h/week).
   - `syllabusSections[]` — 24 entries, one per week, each with `timeRequired: "PT8H"`. Feeds the "Modules" expandable panel in SERP. Coursera uses this exact pattern.
   - `teaches` — string array of 5-8 learning outcomes. Feeds Google's "What you'll learn" rich panel.
   - `coursePrerequisites` — one sentence. Strong audience-fit signal; matches PRD's no-CS-degree audience.
   - `offers.category` with `price: "0"` — required even for free courses. `"Free"` is the recognized category string.
   - `educationalLevel` — helps Google classify beginner-friendly results.
   - `hasPart` — references each week as its own Course entity (optional; extends to per-week rich results once week pages exist).

2. **`ItemList`** — enumerates the 24 weeks as crawl targets (unchanged from v1 plan):

   ```json
   {
     "@context": "https://schema.org",
     "@type": "ItemList",
     "itemListElement": [
       {"@type": "ListItem", "position": 1, "url": "https://automateedge.cloud/#week-1", "name": "Week 1: ..."}
     ]
   }
   ```

3. **`FAQPage`** — separate block, targets "how long", "is it free", "do I need math", "is it current" queries:

   ```json
   {
     "@context": "https://schema.org",
     "@type": "FAQPage",
     "mainEntity": [
       {"@type": "Question", "name": "How long does the AI roadmap take?",
        "acceptedAnswer": {"@type": "Answer", "text": "The full plan is 24 weeks at ~8 hours per week..."}}
     ]
   }
   ```

   Aim for 10-15 Q&A pairs matching the People Also Ask questions surfaced in the SERP recon (SEO research 2026-04-21). roadmap.sh ships 16 Q&As on `/ai-data-scientist`; target parity minimum.

**Deferred to SEO-23 (once we have real data):** `aggregateRating`, inline `review[]`, `totalHistoricalEnrollment`. Do not fabricate these — Google penalizes fake review schema.

**Files touched:** [frontend/index.html](../frontend/index.html), same `scripts/generate_roadmap_scaffold.py` (extend it to emit all three JSON-LD blocks alongside the scaffold, reading outcomes from the roadmap JSON).

**Acceptance:**

- [Google Rich Results Test](https://search.google.com/test/rich-results) on `https://automateedge.cloud/` shows **Course**, **ItemList**, and **FAQPage** detected, zero errors, zero warnings.
- [Schema Markup Validator](https://validator.schema.org/) — zero errors across all three blocks.
- Each block is a separate `<script>` element (validates as sibling blocks, not `@graph`).
- `syllabusSections` has exactly 24 entries matching the week JSON source of truth (pytest assertion).
- GSC → `Enhancements` → `Courses` populates within 2 weeks.
- GSC → `Enhancements` → `FAQ` populates within 2 weeks.

---

### SEO-06 — `Article` JSON-LD on every blog post (P0)

**Depends on:** nothing.

**Work:** Add Article JSON-LD to the blog post template in [backend/app/routers/blog.py](../backend/app/routers/blog.py).

```json
{
  "@context": "https://schema.org",
  "@type": "Article",
  "headline": "{{ post.title }}",
  "datePublished": "{{ post.published_at | isoformat }}",
  "dateModified": "{{ post.updated_at | isoformat }}",
  "author": {
    "@type": "Person",
    "name": "{{ post.author }}"
  },
  "publisher": {
    "@type": "Organization",
    "name": "AutomateEdge",
    "logo": {"@type": "ImageObject", "url": "https://automateedge.cloud/assets/logo.png"}
  },
  "image": "{{ post.og_image or 'https://automateedge.cloud/assets/og-default.png' }}",
  "mainEntityOfPage": "{{ post.canonical_url }}",
  "description": "{{ post.og_description }}"
}
```

**Files touched:** [backend/app/routers/blog.py](../backend/app/routers/blog.py) — add JSON-LD emission to the per-post render function. If the per-post template is Jinja2 (confirm), extend the template; if inline HTML f-string, extract to Jinja2 *first* per RCA-027 prevention pattern before adding.

**Acceptance:**

- Rich Results Test on `/blog/01` and `/blog/02` detects **Article**, zero errors.
- `dateModified` reflects last edit (not just `published_at`).

---

### SEO-07 — Activate IndexNow (P0)

**Depends on:** nothing (endpoint already exists at [backend/app/routers/jobs.py:723-732](../backend/app/routers/jobs.py#L723-L732)).

**Work:**

1. Generate a 32-char hex key: `openssl rand -hex 16`.
2. Set `INDEXNOW_KEY={hex}` in VPS `.env`.
3. Redeploy backend (per `feedback_deploy_rebuild.md` — `--build --force-recreate`).
4. Verify the key file is served: `curl https://automateedge.cloud/{hex}.txt` returns the hex.
5. Wire publish events to ping IndexNow:
   - New blog post publish ([backend/app/routers/blog.py](../backend/app/routers/blog.py) admin publish endpoint) → POST to `https://api.indexnow.org/indexnow`
   - Job publish / bulk-publish ([backend/app/routers/admin_jobs.py](../backend/app/routers/admin_jobs.py)) → same
   - Credential issue ([backend/app/services/certificates.py](../backend/app/services/certificates.py) or equivalent) → same
6. Rate-limit: batch pings if >1 URL/sec; IndexNow accepts up to 10k URLs per request.

**Files touched:** `.env` (VPS), `backend/app/routers/blog.py`, `backend/app/routers/admin_jobs.py`, certificate issuance path. New helper `backend/app/services/indexnow.py` (~40 lines) for the HTTP POST.

**Acceptance:**

- `/{hex}.txt` returns 200 with the hex.
- Publishing a test blog post triggers an IndexNow POST (verify via `docker compose logs backend | grep indexnow`).
- Bing Webmaster Tools → `URL inspection` on the test URL shows "Indexed" within 24 hours (IndexNow is near-instant for Bing; Google is still evaluating its support).

---

### SEO-08 — `BreadcrumbList` JSON-LD on all breadcrumb pages (P1)

**Depends on:** nothing.

**Work:** Wherever the UI renders a breadcrumb trail (blog posts, job detail, profile, verify), emit a matching JSON-LD block.

**Routes confirmed to have visual breadcrumbs:**

- `/blog/{slug}` ([backend/app/routers/blog.py](../backend/app/routers/blog.py))
- `/jobs/{slug}` ([backend/app/routers/jobs.py](../backend/app/routers/jobs.py))
- `/profile/{user_id}` (confirm in router)
- `/verify/{credential_id}` (confirm in router)

**Schema template:**

```json
{
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "itemListElement": [
    {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://automateedge.cloud/"},
    {"@type": "ListItem", "position": 2, "name": "Blog", "item": "https://automateedge.cloud/blog"},
    {"@type": "ListItem", "position": 3, "name": "{{ post.title }}"}
  ]
}
```

Last item has no `item` URL (current page).

**Files touched:** each router that renders breadcrumbs. If breadcrumb rendering is centralized in a helper, add JSON-LD emission there and it covers all pages.

**Acceptance:**

- Rich Results Test on one URL per route type detects **BreadcrumbList**.
- GSC → `Enhancements` → `Breadcrumbs` shows all four route types.

---

### SEO-09 — Blog RSS feed (P1)

**Depends on:** SEO-02 (blog sitemap should be in place first).

**Work:** Expose `/blog/feed.xml` serving RSS 2.0 or Atom 1.0 for all published blog posts. Link from `<head>` per SEO-03.

**Files touched:** [backend/app/routers/blog.py](../backend/app/routers/blog.py).

**Acceptance:**

- `curl https://automateedge.cloud/blog/feed.xml` returns valid RSS XML.
- [W3C Feed Validator](https://validator.w3.org/feed/) shows zero errors.
- Feedly subscribe button works.

---

### SEO-10 — Server-rendered jobs hub pagination (P1)

**Depends on:** nothing.

**Problem:** [backend/app/routers/jobs.py](../backend/app/routers/jobs.py) renders the first 50 jobs server-side; beyond that is client-side fetch. Googlebot won't paginate client-side.

**Work:** Introduce `/jobs?page=N` where each page is a fully server-rendered HTML document with:

- 50 jobs for that page
- `<link rel="canonical" href="/jobs?page=N">` (or `/jobs` for page 1)
- `<link rel="prev" href="/jobs?page=N-1">` and `<link rel="next" href="/jobs?page=N+1">` in `<head>` where applicable
- Classic pagination links in the footer (Page 1 2 3 … Next)

Client-side infinite scroll can remain as a progressive enhancement layered on top; the canonical crawl path is the numbered pages.

**Files touched:** [backend/app/routers/jobs.py](../backend/app/routers/jobs.py).

**Acceptance:**

- `curl -s https://automateedge.cloud/jobs?page=2` returns 200 with 50 jobs and pagination links in body.
- GSC `Coverage` report shows pages 2+ as "Indexed" within 4 weeks.
- Canonical + rel=prev/next pass Rich Results Test (no errors).
- **Watch for memory** `feedback_nginx_allowlist_on_new_routes.md`: if `/jobs?page=N` is a new route pattern nginx doesn't currently allowlist, update `nginx.conf` in the same PR.

---

### SEO-11 — Dynamic OG image generator (P0-adjacent, promoted from P1)

**Depends on:** SEO-03 (head slots exist first).

**Priority note:** roadmap.sh ships per-slug dynamic OG images at `/og/roadmap/{slug}` (verified 2026-04-21). This is competitive parity, not polish. Promote ahead of most P1 work; critical for LinkedIn / X / iMessage link previews which are a major share-driven-backlink source for our verified-credential flywheel.

**Work:** FastAPI endpoint `/og/{type}/{id}.png` that renders with Pillow from a templated 1200×630 card. Match roadmap.sh's URL pattern for direct comparability.

**Types and templates:**

| Type route | Source | Template content |
|---|---|---|
| `/og/roadmap/{track}.png` | Roadmap track (`generalist`, `ai-engineer`, `ml-engineer`, `data-scientist`) | Track name + "24-Week Roadmap" + AutomateEdge wordmark |
| `/og/week/{n}.png` | Week N of the generalist roadmap | "Week N: {topic}" + 3 bullet learning outcomes |
| `/og/blog/{slug}.png` | Blog post | Title + author + date + AutomateEdge wordmark |
| `/og/jobs/{slug}.png` | Job post | Company + role + location + salary band (reuse the known-good `/share/{milestone_share_id}` aesthetic) |
| `/og/vs/{a}-vs-{b}.png` | Comparison page (SEO-19) | "A vs B" split-card layout |
| `/og/cert/{credential_id}.png` | Verified credential (existing) | Keep existing pristine render — don't touch |
| `/og/course/generalist.png` | Home-page Course schema reference | Static or lazily generated; referenced from SEO-05 Course JSON-LD |

Cache to `/data/og-cache/{type}/{id}.png`; regenerate on content update (hook into IndexNow publish events from SEO-07 — re-render OG, then ping).

**Robots / sitemap interplay:**

- `/og/` is `Disallow`ed in robots.txt (per revised SEO-01) — standalone image URLs should not be crawled.
- Images are surfaced to Google via `<image:image>` sitemap extensions (per revised SEO-02) and as `og:image` meta on actual pages, not as crawlable URLs themselves.

**Files touched:** `backend/app/routers/og.py` (new, ~150 lines), `backend/app/services/og_render.py` (~100 lines), `backend/requirements.txt` (verify `Pillow` already present — it should be, from the cert / share generator). Update [backend/app/routers/blog.py](../backend/app/routers/blog.py) and [backend/app/routers/jobs.py](../backend/app/routers/jobs.py) to reference `/og/blog/{slug}.png` etc. in `og:image`. Update [frontend/index.html](../frontend/index.html) `og:image` to reference `/og/course/generalist.png` (per revised SEO-03 and SEO-05).

**Acceptance:**

- `curl -I https://automateedge.cloud/og/blog/01.png` returns 200, `Content-Type: image/png`, 1200×630.
- `curl -I https://automateedge.cloud/og/roadmap/generalist.png` returns 200 with matching dimensions.
- Twitter Card Validator + LinkedIn Post Inspector render the custom image on all 5 route types.
- Cache hits: second fetch of same URL served from disk, not regenerated (check server logs).
- Google's `site:automateedge.cloud/og/` returns zero results after 30 days (confirming `Disallow: /og/` is respected).

---

### SEO-12 — `EducationalOccupationalCredential` JSON-LD on `/verify/{id}` (P1)

**Depends on:** nothing.

**Work:** Add schema to the verify page render path.

```json
{
  "@context": "https://schema.org",
  "@type": "EducationalOccupationalCredential",
  "name": "{{ cert.display_name }}",
  "credentialCategory": "certificate",
  "recognizedBy": {"@type": "Organization", "name": "AutomateEdge"},
  "dateCreated": "{{ cert.issued_at | isoformat }}",
  "about": {"@type": "Thing", "name": "{{ cert.topic }}"},
  "url": "https://automateedge.cloud/verify/{{ cert.credential_id }}"
}
```

**Files touched:** the `/verify/{id}` route handler (grep for "EducationalOccupationalCredential" or find the verify router).

**Acceptance:**

- Rich Results Test on one verified credential URL detects the schema, zero errors.

---

### SEO-13 — Missing canonicals (P1)

**Depends on:** nothing.

**Work:** Add `<link rel="canonical">` on every SSR route that doesn't already have one:

- `/blog` (blog index)
- `/profile/{user_id}`
- `/leaderboard`
- `/verify` (verify index, not per-credential)
- `/account` (self-canonical even though noindexed; preserves signals if accidentally linked)

**Files touched:** each route's template/handler.

**Acceptance:**

- `curl -s {url} | grep canonical` returns exactly one `<link rel="canonical">` per route.

---

### SEO-14 — `WebSite` + `SearchAction` schema + site search (P1, deferred until search exists)

**Depends on:** a site-search endpoint. **Defer** until `/search?q=` actually exists and returns meaningful results across jobs + blog + topics. Without a working search, claiming `SearchAction` is a schema violation.

**When ready — work:** Add to [frontend/index.html](../frontend/index.html) `<head>`:

```json
{
  "@context": "https://schema.org",
  "@type": "WebSite",
  "url": "https://automateedge.cloud/",
  "name": "AutomateEdge",
  "potentialAction": {
    "@type": "SearchAction",
    "target": "https://automateedge.cloud/search?q={search_term_string}",
    "query-input": "required name=search_term_string"
  }
}
```

**Acceptance when shipped:** Rich Results Test detects, and the sitelinks search box appears in branded SERPs within 6 weeks.

---

### SEO-15 — `FAQPage` schema on the roadmap (P2)

**Depends on:** SEO-04.

**Work:** Add a visible FAQ section to `index.html` (below the roadmap, above the footer) covering 6-8 questions:

- "How long does the AI generalist roadmap take?"
- "Do I need a CS degree?"
- "Is it really free?"
- "How current is the content?"
- "Can I get a certificate?"
- "What if I fall behind?"
- "How is this different from roadmap.sh / Coursera?"

Back with `FAQPage` JSON-LD.

**Acceptance:**

- Rich Results Test detects `FAQPage`, all Q&A pairs validate.
- GSC → `Enhancements` → `FAQ` populates.

---

### SEO-16 — Brotli compression (P2)

**Depends on:** nothing. Low effort if nginx build supports it.

**Work:** Add to [nginx.conf](../nginx.conf):

```
brotli on;
brotli_comp_level 4;
brotli_types text/html text/css application/javascript application/json image/svg+xml;
```

**Watch out:** the current `nginx:alpine` image may not have `ngx_brotli` compiled in. If not, either swap to `openresty/openresty:alpine` (which has it), or skip this task — gzip alone is ~85% as good.

**Acceptance:**

- `curl -sI -H 'Accept-Encoding: br' https://automateedge.cloud/` returns `Content-Encoding: br` on HTML responses.
- Bundle sizes measurably smaller (check Network tab in DevTools with and without `br` accept-encoding).

---

### SEO-17 — WebP/AVIF + font-display:swap (P2)

**Depends on:** SEO-11 (OG generator first, so we convert those to WebP too).

**Work:**

- Save all OG PNGs as WebP at `quality=80` in parallel; serve via `<picture>` tags or `Accept` header negotiation
- Append `&display=swap` to the Google Fonts URL in [frontend/index.html](../frontend/index.html)
- Convert any `/assets/*.png` or `.jpg` to WebP where size savings exceed 20%

**Acceptance:**

- PageSpeed Insights → `Image formats` audit passes
- `Eliminate render-blocking resources` ideally passes for fonts (font-display:swap moves FOIT to FOUT)

---

### SEO-18 — Critical CSS extraction (P2)

**Depends on:** Lighthouse baseline after SEO-04.

**Problem:** [frontend/index.html](../frontend/index.html) inlines ~2000 lines of CSS. That's render-blocking and probably blows LCP. But rule 8 says single-file. Tradeoff:

**Approach:** inline ONLY the above-the-fold critical CSS (~200 lines covering hero + first-week render + typography + colors). Move the rest (details/summary styles, modals, leaderboard, profile, admin) to a `<style>` at document end, loaded after paint via a `<link rel="preload" as="style" onload="this.rel='stylesheet'">` pattern — still a single file, still standalone.

**Only do this if Lighthouse LCP on `/` is > 2.5s after SEO-04.** Otherwise the juice isn't worth the squeeze.

**Acceptance:**

- Lighthouse Performance on `/` ≥ 90 on mobile
- LCP < 2.5s on slow 4G
- Rule 8 preserved (file:// still renders)

---

### SEO-19 — Programmatic comparison pages (P0-adjacent, added from research)

**Depends on:** SEO-04, SEO-05 (Course schema for anchor cross-links).

**Why this exists:** SERP recon identified `AI engineer vs ML engineer` as the single most beatable target query — top 3 is Medium posts, featured snippet is up for grabs, no entrenched brand. roadmap.sh ships 31 `/vs-*` pages as their long-tail funnel. This is programmatic SEO at its highest ROI.

**Work:** Build `/vs/{a}-vs-{b}` route serving a Jinja2 template populated from a `comparisons.json` data file. Ten initial pages, one template, one file:

| Slug | Target query |
|---|---|
| `/vs/ai-engineer-vs-ml-engineer` | "AI engineer vs ML engineer" (priority #1 from SERP recon) |
| `/vs/ai-engineer-vs-data-scientist` | "AI engineer vs data scientist" |
| `/vs/ml-engineer-vs-data-scientist` | "ML engineer vs data scientist" |
| `/vs/ai-engineer-vs-prompt-engineer` | "AI engineer vs prompt engineer" |
| `/vs/ai-engineer-vs-mlops-engineer` | "MLOps vs AI engineer" |
| `/vs/data-scientist-vs-data-analyst` | "data scientist vs data analyst" |
| `/vs/ai-vs-machine-learning` | "AI vs machine learning" |
| `/vs/generative-ai-vs-traditional-ai` | "generative AI vs traditional AI" |
| `/vs/rag-vs-fine-tuning` | "RAG vs fine-tuning" |
| `/vs/pytorch-vs-tensorflow` | "PyTorch vs TensorFlow" |

**Per-page template (minimum content bar, enforced by validator):**

- `<h1>{A} vs {B}: Complete 2026 Comparison</h1>`
- 50-word TL;DR paragraph (featured-snippet target, first-paragraph definitional answer)
- Side-by-side comparison table (8-12 rows: salary range 2026, hiring volume 2026, core skills, typical tools, day-to-day work, career path, required education, best-fit personality)
- One H2 per role defining it in 150 words, each with `DefinedTerm` JSON-LD
- "Which should you choose?" H2 with 5-7 decision factors
- FAQPage JSON-LD at bottom with 6-8 Q&As drawn from the SERP's People Also Ask
- Anchor cross-links to the matching roadmap track + 2 relevant blog posts + 3 matching jobs (if `jobs_ingest` has any)
- Minimum 1500 words

**Salary + hiring volume data source:** harvest from existing [jobs_ingest/](../backend/app/services/jobs_ingest.py) + [jobs_enrich/](../backend/app/services/jobs_enrich.py) pipelines — compute rolling 90-day aggregates per role. This is an intent-gap nobody fills (SERP recon called it out explicitly) and it's cheap because we already have the data.

**Schemas per page:**

- `Article` (primary)
- `FAQPage` (sibling block, 6-8 Q&As)
- `DefinedTerm` × 2 (one per role)
- `BreadcrumbList` (Home → vs → A-vs-B)
- Optional `Table` (for the comparison table — not rich-result eligible but good semantic markup)

**Files touched:** `backend/app/routers/compare.py` (new), `backend/app/templates/compare.html` (new Jinja2), `backend/data/comparisons.json` (new data file, ~1500 lines for 10 comparisons), `backend/app/main.py` (router include). Also update [nginx.conf](../nginx.conf) to allowlist `/vs/` per memory `feedback_nginx_allowlist_on_new_routes.md`. And update `sitemap-roadmap.xml` (SEO-02) to include all 10 URLs.

**Acceptance:**

- All 10 URLs return 200 with >1500 words visible in SSR HTML
- Rich Results Test shows Article + FAQPage + BreadcrumbList + 2 DefinedTerm schemas, zero errors per page
- Featured-snippet eligibility: first paragraph is 40-60 words and directly answers the "{A} vs {B}" intent
- GSC indexation of all 10 within 4 weeks
- Track monthly: position for each target query; goal is top-10 on 6 of 10 within 90 days

**Why this beats roadmap.sh here:** they ship 31 `/vs-*` pages but **none** have FAQPage or DefinedTerm schema, and most are thin keyword-harvests. Our pages are 1500+ words with real salary/hiring data.

---

### SEO-20 — Per-track quintet pages (P1, added from research)

**Depends on:** SEO-04, SEO-19 (same template infrastructure).

**Why this exists:** roadmap.sh ships `/<track>/{career-path,skills,tools,lifecycle,projects}` (4 of 5 slugs on `/ai-data-scientist` only). This is the programmatic long-tail pattern. We adopt it plus the two slugs they miss (`certifications`, `salary`), across every roadmap track we offer.

**Work:** For each track (`generalist`, `ai-engineer`, `ml-engineer`, `data-scientist`, `mlops`), generate 6 sub-pages:

| Slug | Content |
|---|---|
| `/roadmap/{track}/skills` | Skill matrix with proficiency levels; cross-link to matching weeks |
| `/roadmap/{track}/tools` | Tool inventory (libraries, frameworks, platforms) with install-to-use tutorials |
| `/roadmap/{track}/projects` | 10-15 portfolio project ideas with GitHub-repo evaluation rubric (ties into AI evaluation feature in PRD) |
| `/roadmap/{track}/certifications` | Free certs only (matches §5 rule); which employers recognize them, per our jobs data |
| `/roadmap/{track}/salary` | 2026 salary bands by region + 90-day hiring velocity from our jobs pipeline |
| `/roadmap/{track}/career-path` | 1-year / 3-year / 5-year progression stages, each with job titles + required skills |

5 tracks × 6 slugs = **30 new crawlable, long-tail-targeted URLs**. Each 1000-2000 words, templated from a per-track JSON file.

**Schemas per page type:**

- All: `Article` + `BreadcrumbList`
- `/skills` and `/tools`: `ItemList`
- `/projects`: `ItemList` of `CreativeWork`
- `/certifications`: `ItemList` of `EducationalOccupationalCredential`
- `/salary`: `Article` + embedded `Dataset` schema (if we publish the underlying salary CSV)
- `/career-path`: `Article` + inline `HowTo` (step-by-step progression = qualifies)

**Files touched:** `backend/app/routers/track_pages.py` (new), `backend/app/templates/track_page.html` (new), `backend/data/tracks/*.json` (one per track), `nginx.conf` allowlist update, sitemap inclusion.

**Acceptance:**

- All 30 URLs 200 with >1000 words
- Rich Results Test passes on one URL per page-type
- Each URL surfaced in `sitemap-roadmap.xml`
- Salary pages refresh monthly via cron (hook into existing `scripts/scheduler.py`)

---

### SEO-21 — Pillar blog content cluster with quality bar (P1 — content work, not code)

**Depends on:** SEO-06 (Article schema live), SEO-08 (BreadcrumbList on blog posts), SEO-11 (OG images).

**Why this exists:** Content competitors' pillar posts average ~3,580 words, 40+ internal links, 5+ external authority citations. None use `HowTo`, almost none use `FAQPage`. Our content must match the depth and exceed the schema to rank.

**Initial content slate (priority order from SERP recon):**

| Slug | Target query | Schema stack |
|---|---|---|
| `/blog/ai-engineer-vs-ml-engineer` | q6 — most beatable | Article + FAQPage + DefinedTerm + Table |
| `/blog/learn-ai-without-cs-degree-2026` | q7 — Quora beatable | Article + FAQPage + HowTo + Review (learner case studies) |
| `/blog/ai-roadmap-2026-whats-changed` | q2 — year-qualified, freshness angle | Article + FAQPage + quarterly dateModified refresh |
| `/blog/how-to-learn-ai-from-scratch` | q4 — thin SERP | Article + HowTo + FAQPage + VideoObject (embed walkthrough) |
| `/blog/minimum-math-for-ai` | intent-gap q3/q4 — concrete ceiling | Article + HowTo + DefinedTerm |
| `/blog/free-ai-certs-employers-recognize` | intent-gap q10 — hiring-manager validation | Article + ItemList of EducationalOccupationalCredential + Review |

**Hard quality bar (enforced by blog validator before publish):**

1. **Word count:** 3000 minimum for pillar posts, 4500+ for flagship ("how to learn AI" slate)
2. **First paragraph:** 40-60 word definitional snippet answering the query's primary intent directly (featured-snippet target)
3. **Structure:** sticky TOC (anchor-linked H2s), 8-12 H2 sections
4. **Internal links:** ≥ 40 outbound to our own content (roadmap weeks, other blog posts, jobs, tracks)
5. **External citations:** ≥ 5 to authoritative sources — arXiv papers, official lab docs (OpenAI, Anthropic, Google AI, DeepMind, HuggingFace, Papers with Code), BLS salary data, LinkedIn/GitHub public reports. This is the E-E-A-T differentiator (SEO-25).
6. **Schema mandatory:** Article + FAQPage + at least one of (HowTo, DefinedTerm, VideoObject, ItemList) depending on content shape
7. **FAQ:** 8-15 Q&A pairs at bottom, drawn directly from People Also Ask for the target query
8. **Comparison table:** at least one, where the post has a comparative angle (beats snippets for table queries)
9. **dateModified refresh:** bumped every quarter even without content edits; tied to the quarterly curriculum sync cron
10. **OG image:** generated via SEO-11 `/og/blog/{slug}.png`

**Files touched:** `docs/blog/*.json` (new content files), `backend/app/services/blog_validator.py` (new validator enforcing items 1-10 above), admin blog-publish flow hook to run validator pre-publish.

**Acceptance:**

- All 6 pillar posts published, each passing the validator with zero warnings
- Rich Results Test on each shows all declared schemas, zero errors
- IndexNow ping confirmed (SEO-07 wiring)
- 90-day tracking: position on target query, featured-snippet capture rate, PAA occupancy

---

### SEO-22 — VideoObject schema + YouTube embed policy (P1, added from research)

**Depends on:** SEO-21 (applied to pillar posts that embed video).

**Why this exists:** 0 of 7 content competitors audited use VideoObject schema even when embedding YouTube. SERP recon shows video pack visible on `how to learn AI` and `AI engineer vs ML engineer`. This is free rich-result real estate.

**Work:** Whenever a blog post or track page embeds a YouTube video, emit:

```json
{
  "@context": "https://schema.org",
  "@type": "VideoObject",
  "name": "{{ video.title }}",
  "description": "{{ video.description }}",
  "thumbnailUrl": "https://i.ytimg.com/vi/{{ video.id }}/maxresdefault.jpg",
  "uploadDate": "{{ video.published_at }}",
  "duration": "{{ video.duration | iso8601 }}",
  "contentUrl": "https://www.youtube.com/watch?v={{ video.id }}",
  "embedUrl": "https://www.youtube.com/embed/{{ video.id }}"
}
```

Harvest `video.duration`, `video.published_at`, `video.title`, `video.description` via YouTube Data API at publish time; cache in the blog post's JSON metadata so we don't re-fetch on every render.

**Constraint:** only embed videos the author of the blog post has vetted. Don't embed automatically — hand-curation signal is what Google reads.

**Files touched:** `backend/app/services/blog_validator.py` (extend to emit VideoObject if post metadata contains `youtube_ids`), blog template to render the `<script type="application/ld+json">` block.

**Acceptance:**

- Rich Results Test on a pillar post with an embedded video detects VideoObject, zero errors.
- Video pack eligibility for the post's target query within 60 days (GSC's `Video` report populates).

---

### SEO-23 — Aggregate rating + inline Review schema (P2, gated on real data)

**Depends on:** ≥5 genuine learner testimonials collected. Do **not** ship with fabricated reviews — Google penalizes fake review schema.

**Why this exists:** Coursera's `aggregateRating` + 5 inline `Review` objects surface star snippets in SERP — the single largest CTR lever on course queries. Once we cross the threshold, it's a high-ROI add.

**Work:** Add to the Course JSON-LD (SEO-05):

```json
"aggregateRating": {"@type": "AggregateRating", "ratingValue": 4.8, "ratingCount": 127, "bestRating": 5},
"review": [
  {"@type": "Review", "author": {"@type": "Person", "name": "..."}, "datePublished": "...", "reviewRating": {"@type": "Rating", "ratingValue": 5}, "reviewBody": "..."}
]
```

Also consider `totalHistoricalEnrollment: N` (non-standard but Google parses it; Coursera uses it to display "1.1M enrolled").

**Trigger:** when `SELECT COUNT(*) FROM learner_testimonials WHERE approved = 1` ≥ 5 AND average rating ≥ 4.0, auto-emit the schema.

**Files touched:** new `learner_testimonials` table (Alembic migration — **load-bearing path**, worktree isolation required), testimonial collection flow (probably a post-milestone prompt on `/share/{id}`), approval workflow for admin, auto-injection into Course JSON-LD.

**Acceptance:**

- Star snippet appears in SERP for the landing page within 8 weeks of schema going live.
- Schema validates with real learner data.

---

### SEO-24 — Hub `ItemList` schema for roadmap track catalog (P1, added from research)

**Depends on:** SEO-20 (track pages must exist).

**Why this exists:** edX's AI hub ships a single `ItemList` with 48 `ListItem` positions each pointing to a canonical course URL — clean internal-linking signal. We mirror this: once multiple tracks exist, the `/roadmap` hub (or home-page subsection) enumerates all tracks as a typed list.

**Work:** Add to the `/roadmap` hub page (or a dedicated section on `/`):

```json
{
  "@context": "https://schema.org",
  "@type": "ItemList",
  "name": "AutomateEdge Learning Tracks",
  "itemListElement": [
    {"@type": "ListItem", "position": 1, "url": "https://automateedge.cloud/roadmap/generalist", "name": "AI Generalist"},
    {"@type": "ListItem", "position": 2, "url": "https://automateedge.cloud/roadmap/ai-engineer", "name": "AI Engineer"}
  ]
}
```

**Files touched:** hub page template (wherever `/roadmap` renders, likely the frontend scaffold extension).

**Acceptance:**

- Rich Results Test on `/roadmap` detects ItemList with all tracks present.

---

### SEO-25 — E-E-A-T citation audit (P1, ongoing — tied to content cadence)

**Depends on:** SEO-21 quality validator.

**Why this exists:** Machine Learning Mastery is the only one of 7 content competitors audited that cites arXiv + official lab docs consistently — and it's the only non-commercial site that reliably ranks on competitive AI queries. E-E-A-T (Experience, Expertise, Authoritativeness, Trust) is Google's framework for ranking YMYL-adjacent content, and learn-AI-to-get-a-job content qualifies.

**Work:** Maintain a rolling citation allowlist at `backend/data/trusted_sources.json`:

- arXiv (category `cs.AI`, `cs.LG`, `cs.CL`, `stat.ML`)
- Papers with Code
- OpenAI / Anthropic / Google AI / DeepMind / Meta AI / HuggingFace blogs
- Official docs: PyTorch, TensorFlow, scikit-learn, NumPy
- Statistical: BLS, World Economic Forum Future of Jobs report, LinkedIn Economic Graph, GitHub Octoverse
- Academic: Stanford AI Index, MIT / Berkeley / CMU ML courses

Blog validator (SEO-21) enforces: ≥ 5 outbound links matching this allowlist per pillar post. Missing minimum blocks publish.

**Files touched:** `backend/data/trusted_sources.json`, `backend/app/services/blog_validator.py` (extend).

**Acceptance:**

- No pillar post publishes with < 5 trusted external citations.
- Quarterly review of the allowlist (add emerging authoritative sources, prune any that become spammy).

---

### SEO-26 — `/start` interactive quiz landing page (P2, leverages existing product)

**Depends on:** existing personalized-plan generator.

**Why this exists:** SERP recon prioritized `how to learn AI from scratch` (q4) as beatable — top 3 is Manning redirect + Quora + open-source curriculum. An interactive quiz that outputs a personalized plan is a direct intent match competitors can't replicate, and it gives us a unique SERP result (interactive content typically wins CTR battles against listicles).

**Work:**

- 8-10 question quiz at `/start` (current experience level, available hours/week, target role, math comfort, coding comfort, learning-style preference, etc.)
- Outputs a customized roadmap preview + CTA to sign up for the full plan
- Each quiz outcome has its own URL (`/start/result/{hash}`) with its own meta tags so shares generate diverse SERP appearances
- `Quiz` schema + `HowTo` (the recommended path as steps)

**Target query:** "how to learn AI from scratch" + variants.

**Files touched:** new `backend/app/routers/start.py`, new frontend quiz component (inlined in `frontend/index.html` if small enough, or a new page if separate is cleaner), new Alembic migration for `quiz_outcomes` table (**load-bearing** — worktree isolation).

**Acceptance:**

- Quiz completable in < 90 seconds
- Result URL has unique og:image via SEO-11
- GSC position for target query tracked monthly; goal top-10 within 90 days

---

## 5. Content strategy (starts after P0)

Technical SEO gets you crawled. Content and links get you ranked. This section is revised from v1 with competitive intelligence from 2026-04-21 — concrete slugs, hard quality bars, and SERP-validated priority order.

### 5.1 Content priority order (ruthless)

SERP recon ruled out four queries as brand-dominated or poor-ROI: `AI learning roadmap` (roadmap.sh + GitHub lock top 3), `AI engineer roadmap` (ditto), `machine learning roadmap` (ditto), `free AI course` / `AI certification free` (Coursera + Udemy own course carousels), `how to learn AI` (Google owns it via `ai.google/learn-ai-skills`). Do not spend pillar-post budget on these — compete indirectly through SEO-05 Course schema + SEO-19 comparison pages.

Targeted queries (in execution order, all from SEO-21):

1. **`AI engineer vs ML engineer`** — featured snippet up for grabs (SEO-19 + `/blog/ai-engineer-vs-ml-engineer`)
2. **`learn AI without CS degree`** — Quora in top 3, identity-query aligns with PRD audience (`/blog/learn-ai-without-cs-degree-2026`)
3. **`AI learning roadmap 2026`** — freshness moat, no entrenched year-qualified winner (`/blog/ai-roadmap-2026-whats-changed`)
4. **`how to learn AI from scratch`** — thin SERP, interactive quiz advantage (SEO-26 + `/blog/how-to-learn-ai-from-scratch`)
5. Intent-gap queries — "minimum math for AI", "free AI certs employers recognize", "is the 2024 AI roadmap still valid in 2026", "AI engineer salary hiring volume 2026"

### 5.2 Hard quality bar (enforced by blog validator — SEO-21)

Every pillar post must pass these checks before publish. Validator lives in `backend/app/services/blog_validator.py`; publish flow calls it pre-commit. No manual override.

1. **Word count:** ≥ 3000 for pillar posts, ≥ 4500 for flagship
2. **First-paragraph definitional snippet:** 40-60 words, directly answers query intent in first sentence
3. **Structure:** sticky TOC with anchor-linked H2s, 8-12 H2 sections
4. **Internal links:** ≥ 40 outbound to own content (weeks, blog, jobs, tracks, comparison pages)
5. **External authority citations:** ≥ 5 from the trusted-sources allowlist (SEO-25 — arXiv, official lab docs, BLS, academic)
6. **Mandatory schemas:** `Article` + `FAQPage` + at least one of (`HowTo`, `DefinedTerm`, `VideoObject`, `ItemList`) based on content shape
7. **FAQ:** 8-15 Q&As drawn from target query's People Also Ask (SEMrush-free method: search query, scrape PAA from SERP manually, feed verbatim into FAQ names)
8. **Comparison table:** at least one where the post has a comparative angle
9. **`dateModified` quarterly refresh:** tied to the existing quarterly curriculum-sync cron; bumps even without content edits so freshness signal refreshes
10. **OG image via SEO-11:** `/og/blog/{slug}.png`

### 5.3 Quarterly curriculum refresh — compound content moat

Every Q1/Q4 (aligned with curriculum auto-refresh): publish **"What changed in the AI roadmap — Q{N} {year}"**. This is the single content play static roadmap sites cannot match. Format:

- Diff of added / removed / re-ordered topics with one-paragraph rationale per change, sourced from the curriculum pipeline's own output
- Visual "diff" comparison block (added topics in green, removed in red)
- Cross-reference the removed topics to "why you should still learn X" (if applicable) or "what replaces this"
- Embed 1-2 videos from authoritative sources covering the new topics (SEO-22 VideoObject)
- Syndicate: Hacker News (post Tuesday 8am PT), r/MachineLearning (weekday morning), dev.to, LinkedIn article, Medium repost with canonical to our version

Bumping `dateModified` on **every** pillar post (not just the refresh post) every quarter is a freshness move competitors miss — per content research, stale 2024-URL slugs still rank on 2026 queries because the *visible* dateModified is fresh.

### 5.4 Certificate + profile flywheel (reinforce, don't rebuild)

Every `/verify/{id}` and `/profile/{id}` is a potential inbound link from LinkedIn, personal sites, GitHub READMEs. Already built. Protect and extend:

- `/share/{milestone_share_id}` OG images stay pristine (LinkedIn conversion surface; do not touch without user approval)
- Public profiles add `Person` JSON-LD (name, `sameAs` to linked GitHub / LinkedIn, `knowsAbout` string array derived from their completed weeks) — future task, not in current SEO-xx set
- Verified credential pages get `EducationalOccupationalCredential` schema (SEO-12)

### 5.5 Programmatic SEO — beat roadmap.sh at their own game

roadmap.sh's long-tail moat is programmatic: 31 `/vs-*` pages + 4 quintet pages on one track. We ship SEO-19 (10 comparison pages, better schema stack) and SEO-20 (30 quintet pages across 5 tracks including the 2 slugs they skip — certifications + salary). Total new crawlable URLs from programmatic SEO alone: **40**, each targeting a distinct long-tail cluster.

### 5.6 Cadence

- **Weeks 1-4:** SEO-00 through SEO-07 shipped (all P0)
- **Weeks 5-8:** SEO-08 through SEO-13 + SEO-19 (P1 + comparison pages)
- **Weeks 9-12:** SEO-20 + SEO-21 first two pillar posts + SEO-22 + SEO-24 + SEO-25
- **Week 13:** first quarterly refresh post (SEO-21 post #3)
- **Weeks 14-24:** remaining SEO-21 posts, SEO-26 quiz, SEO-23 (if learner testimonial threshold met), P2 polish

## 6. Ongoing operations

- **Every blog post publish** → IndexNow ping (automated via SEO-07), manual submission to GSC `URL inspection` for fastest Google discovery.
- **Every job publish / bulk-publish** → IndexNow ping (automated via SEO-07).
- **Quarterly curriculum refresh** → regenerate scaffold (SEO-04 script), regenerate week OG images (SEO-11), update `dateModified` in Course JSON-LD (SEO-05), publish quarterly blog post, IndexNow.
- **Monthly (first of month)** → review GSC `Coverage` report for crawl errors, excluded URLs, soft-404s. File a fix for each.
- **Monthly** → review GSC `Performance` report; identify top 5 queries by impressions with CTR < 2% → improve titles / descriptions for those URLs.
- **Quarterly** → run Lighthouse on `/`, `/jobs`, one blog post, one job detail. Record in Change log. Fix regressions.
- **Quarterly** → full re-audit of this doc. Record findings in Change log.

## 7. Measurement

**Tools (all free):**

- Google Search Console — indexation, queries, CTR, position, CWV
- Bing Webmaster Tools — Bing-specific indexation + IndexNow status
- [PageSpeed Insights](https://pagespeed.web.dev/) — Lighthouse, CWV field data
- [Rich Results Test](https://search.google.com/test/rich-results) — schema validation
- [Schema Markup Validator](https://validator.schema.org/) — schema.org validation
- [opengraph.xyz](https://www.opengraph.xyz/) — OG preview

**Review cadence:**

- Weekly — glance at GSC Performance (impressions trend, new queries)
- Monthly — full GSC review + Lighthouse on top 5 URLs
- Quarterly — content cluster review, competitive position check

## 8. What NOT to do

- **Do not migrate the frontend to Next.js or any SPA framework for SEO reasons.** Rule 8 exists for a reason. Scaffolding (SEO-04) is cheaper and preserves standalone-from-disk.
- **Do not buy backlinks or engage any "SEO service."** Permanent trust damage. One spammy inbound link pool can take 6+ months to disavow.
- **Do not noindex pages you can fix.** The expired-jobs `noindex` is correct; don't extend the pattern.
- **Do not stuff keywords.** Write for humans; schema expresses machine intent.
- **Do not submit the same URL to GSC's `Request Indexing` repeatedly.** Throttled at ~10/day and abuse trips flags.
- **Do not break the `/share/` PII-hygiene contract.** Those URLs are public by design but not crawlable (see robots.txt `Disallow: /share/`).
- **Do not touch `application/ld+json` blocks without running the Rich Results Test.** A malformed block gets the page silently disqualified from rich results.
- **Do not put the GSC verification token in the repo.** `.env` only; file verification (`/google{token}.html`) served by nginx from an env-sourced path.

## 9. Load-bearing path notes (from CLAUDE.md §8)

Tasks in this plan that touch load-bearing paths (require worktree isolation + Opus diff review):

| Task | Load-bearing paths touched |
|---|---|
| SEO-06 (Article JSON-LD) | None — blog router is not load-bearing, but follow RCA-027 f-string-in-template prevention |
| SEO-11 (OG generator) | Potentially new DB column on `Job` / `Post` for cached OG path → Alembic migration (`backend/alembic/versions/` is load-bearing) |
| SEO-14 (site search) | Depends on search implementation — if it touches classifier or AI prompts, load-bearing |

All other tasks are standard paths — Sonnet subagent + normal diff review is sufficient.

## 10. Change log

> Append one dated entry per SEO-related commit. Include task ID, what shipped, and any metric snapshot relevant to the task.

- **2026-04-21** — Plan drafted. No implementation yet. Baseline metrics pending GSC / Bing connect (SEO-00).
- **2026-04-21** — SEO-01 shipped partial (🟡). Created [frontend/robots.txt](../frontend/robots.txt) with the 5 Disallow rules + Sitemap directive. Added `location = /robots.txt` block in [nginx.conf](../nginx.conf) — `try_files /robots.txt =404`, 24h cache, explicit text/plain content-type. Deployed (commits 72e21ec + 55c6888) and nginx reloaded via `docker compose exec web nginx -s reload` — nginx config test passed. **However: Cloudflare Managed robots.txt is intercepting `/robots.txt` at the edge** and serving its own file (contains `Content-Signal: search=yes,ai-train=no` + `BEGIN Cloudflare Managed content` block blocking Amazonbot, Applebot-Extended, Bytespider, CCBot, ClaudeBot, GPTBot, Google-Extended, meta-externalagent). Our origin Disallows (/admin /api /account /share/ /og/) and Sitemap directive are **not** reaching crawlers. User action required: (a) add custom Disallow rules + `Sitemap: https://automateedge.cloud/sitemap_index.xml` to the Cloudflare Managed robots.txt via CF dashboard → Security → Bots → Crawler Hints, OR (b) disable the CF managed-robots feature so origin serves. Option (a) is safer — keeps the useful AI-bot blocks Cloudflare added automatically.
- **2026-04-21** — SEO-03 shipped partial (🟡). Added 6 missing head tags to [frontend/index.html](../frontend/index.html) around line 13: `og:url`, `og:site_name`, `twitter:card=summary`, `twitter:title`, `twitter:description`, `author`, `canonical`. Deferred to SEO-11: `og:image`, `og:image:width/height`, `twitter:image`, upgrade of `twitter:card` to `summary_large_image` — all depend on the OG image generator (/og/course/generalist.png) not yet built. Deferred to SEO-09: RSS feed alternate link. Deploy: volume-mounted, `git pull` on VPS only.
- **2026-04-21** — SEO-04 shipped (✅). Highest-ROI task in the plan. Landing page now emits a 9.8 KB static scaffold (1 intro + 6 month headers + 24 `<section id="week-N">` blocks, each with `<h2>Week N: topic</h2>` + 1-line deliverables `<p>` + 3-5 resource title `<li>`s) directly in the initial HTML — visible to Googlebot, Bingbot, Twitter / LinkedIn / Slack preview bots, and no-JS users. Zero external hrefs in the scaffold block (preserves the progressive-enhancement contract; real resource URLs stay in the JS render). New build-time script [scripts/generate_roadmap_scaffold.py](../scripts/generate_roadmap_scaffold.py) reads the inline `const DATA = [...]` source of truth via a small JS-literal → JSON normalizer (handles unquoted keys, trailing commas, double-quoted strings) and rewrites the block between `<!-- SCAFFOLD:START -->` / `<!-- SCAFFOLD:END -->` markers inside `<main id="content">`; idempotent + `--check` flag for CI drift detection. Anti-flash wiring: `<style>html.has-js [data-roadmap-scaffold]{display:none}</style>` + `<script>document.documentElement.classList.add('has-js');</script>` at [frontend/index.html:26-27](../frontend/index.html#L26-L27), so the scaffold hides before first paint on JS-enabled clients. Explicit DOM removal `document.querySelectorAll('[data-roadmap-scaffold]').forEach(el => el.remove())` runs at [frontend/index.html:2230](../frontend/index.html#L2230) immediately before the first `render()` call (defense in depth — `render()` also clears `#content.innerHTML`). Rule 8 preserved: `file:///e:/code/AIExpert/frontend/index.html` still renders identically (pure HTML/CSS/JS, no network, no build). Acceptance verified locally — `<h2>Week` count = 24, file size = 141.7 KB (≥ 40 KB target), 24 scaffold week titles content-match the 24 interactive DATA week titles, 0 http(s) refs in scaffold. Deploy is volume-mounted — `git pull` on VPS suffices. Unblocks SEO-05 (Course + ItemList + FAQPage JSON-LD anchoring).
- **2026-04-21** — SEO-05 shipped (✅). Three separate `<script type="application/ld+json">` blocks emitted into `<head>` of [frontend/index.html](../frontend/index.html) between `<!-- JSONLD:START --> / <!-- JSONLD:END -->` markers (lines 364-939): (1) `Course` with the full Coursera-grade property set — `hasCourseInstance.courseWorkload = "PT200H"` (Google's 2024-required field), 24 `syllabusSections` (one per week, `timeRequired="PT8H"` each) harvested from the DATA source of truth, 24 `hasPart` entries linking `#week-N` anchors, 8 `teaches` outcomes (all ≤120 chars) spanning Python/math → classical ML → PyTorch deep learning → LLM application building → MLOps → responsible AI → capstone, `coursePrerequisites` = "Basic Python familiarity and high-school algebra. No CS degree required." (72 chars), `offers[0]` = `{price:"0", priceCurrency:"USD", category:"Free"}`, `educationalLevel="Beginner to Intermediate"`, `provider` = AutomateEdge Organization with logo; (2) `ItemList` with 24 `ListItem` entries pointing to `https://automateedge.cloud/#week-N` crawl targets; (3) `FAQPage` with 12 Q&A pairs (88-98 words each, inside the 40-120 word target for rich-snippet eligibility) covering the SERP-recon queries — how long, is it free, CS degree, differentiation vs roadmap.sh/Coursera, currency, certificates, falling behind, math, GPU, Python experience, zero-ML start, job outcomes. Deferred to SEO-23: `aggregateRating`, `review[]`, `totalHistoricalEnrollment` — gated on ≥5 genuine testimonials per plan policy (Google penalizes fabricated review schema). Generator extended: [scripts/generate_roadmap_scaffold.py](../scripts/generate_roadmap_scaffold.py) now emits both the SEO-04 scaffold and the SEO-05 JSON-LD in one pass; added `_build_course`, `_build_itemlist`, `_build_faqpage`, `_jsonld_safe` (escapes `</` → `<\/` so no value can prematurely terminate the script element), and `_validate_jsonld` which raises at generation time if syllabusSections/hasPart/ItemList count ≠ 24, any `teaches` string >120 chars, `coursePrerequisites` >200 chars, or any FAQ answer outside 40-120 words. `_inject_jsonld` uses `html.replace("</head>", ..., 1)` so only the real `</head>` at line 940 is targeted and the second `</head>` inside the inline PDF-template JS string at line ~1402 is untouched. Rule 8 preserved: JSON-LD `<script type="application/ld+json">` is inert for rendering and contains no `href`/`src` attributes that would trigger network fetches, so `file:///e:/code/AIExpert/frontend/index.html` still renders identically from disk. Acceptance verified locally — 3 JSON-LD `<script>` elements (count == 3, all inside `<head>`), 24 syllabusSections, 24 ItemList items, 24 hasPart entries, generator `--check` idempotent after regenerate, total file size 163 KB (was 141.7 KB pre-SEO-05; +21.3 KB for the three blocks). **External validation still required before full-green acceptance** — Google Rich Results Test (<https://search.google.com/test/rich-results>) and Schema Markup Validator (<https://validator.schema.org/>) must be run against the deployed URL to confirm zero errors + zero warnings across all three block types, plus Lighthouse Performance spot-check for ≤3-point regression vs post-SEO-04 baseline. Deploy is volume-mounted — `ssh a11yos-vps "cd /srv/roadmap && git pull"` after commit approval.
- **2026-04-22** — SEO-08 shipped (✅) in one commit (`f620a6a`). Added `BreadcrumbList` JSON-LD on the two routes that actually render visual breadcrumbs: `/blog/{slug}` (extended the SEO-06 Jinja2 template with a second `<script>`) and `/jobs/{slug}` (built `breadcrumb_ld` Python dict + serialized via `json.dumps()` — same RCA-027-safe pattern already in use for the existing `JobPosting` JSON-LD at [backend/app/routers/jobs.py:580](../backend/app/routers/jobs.py#L580); no Jinja2 migration needed for jobs.py because the dict-then-dumps approach never puts literal `{}` into the f-string source). Both pages now carry 2 JSON-LD blocks each (Article+Breadcrumb on blog; JobPosting+Breadcrumb on jobs). Schema follows Google's spec: 3 `ListItem`s, current-page (last) item has no `item` URL. **Spec audit corrections**: `/profile/{user_id}` is JSON-API-only (SPA-rendered) — no server-side breadcrumb to enhance; `/verify/{credential_id}` has no visual breadcrumb in the render path — adding one would be UX scope creep beyond SEO-08's "enhance existing" intent. Both noted in commit message and ruled out of scope. **Tests**: new `test_post_breadcrumb_list_json_ld_emitted` (blog) + new `test_per_job_ssr_includes_breadcrumblist_jsonld` (jobs) + new `_extract_all_jsonld` helper (multi-block extraction); existing JobPosting JSON-LD test stays valid because its non-greedy regex still matches the first `<script>` block (safe coexistence). 22/22 blog + jobs_public tests pass. Deploy: `--build --force-recreate backend` (Python code change). **Live verification**: `/blog/01` returns Article+BreadcrumbList with 3 crumbs (Home → Blog → title); `/jobs/principal-engineer-ai-inference-reliability-at-cerebrassystems-d884` returns JobPosting+BreadcrumbList with 3 crumbs (Home → AI & ML Jobs → "Principal Engineer, AI Inference Reliability"); both last items have no `item` URL as required. External Rich Results Test recommended on the live URLs as the formal acceptance step (Google → Enhancements → Breadcrumbs should populate within 2 weeks).
- **2026-04-23** — SEO-09 + SEO-13 shipped (✅) in one commit (`289574b`). **SEO-13 (canonicals)** — added `<link rel="canonical">` on 5 SSR routes: `/blog` index head in [backend/app/routers/blog.py](../backend/app/routers/blog.py) inline f-string, `/profile/{user_id}` and `/leaderboard` inline f-strings in [backend/app/routers/public_profile.py](../backend/app/routers/public_profile.py) (added `from app.config import get_settings` import alongside), `/verify` index via the existing `__BASE__` placeholder pattern in [backend/app/routers/verify.py](../backend/app/routers/verify.py) `_INDEX_HTML`, and `/account` in [frontend/account.html](../frontend/account.html) (also added `<meta name="robots" content="noindex">` — SEO-13 spec calls for self-canonical despite noindex, preserves signals if accidentally linked). **SEO-09 (RSS feed)** — new `/blog/feed.xml` route in blog.py serves RSS 2.0 with `atom:self` self-reference, per-item `title/link/guid(isPermaLink)/pubDate/description`, channel title/link/desc/language/lastBuildDate, 10-min Cache-Control. `_rfc822()` helper formats ISO dates as RFC 2822 GMT via `email.utils.format_datetime` (feed aggregators expect GMT per RSS spec — not a user-facing timestamp, so the IST-sitewide rule in memory doesn't apply). `<link rel="alternate" type="application/rss+xml">` advertised in both the `/blog` index head and the per-post template [backend/app/templates/blog/post.html](../backend/app/templates/blog/post.html). Route ordering: `/blog/feed.xml` declared before the dynamic `/blog/{slug}` catch-all so FastAPI resolves it directly. **Tests**: 4 new in test_blog.py (blog-index canonical count, feed XML parse + structure with both posts present, feed escape safety for `< &` in titles, per-post RSS alternate link); 3 new in new [backend/tests/test_seo_canonicals.py](../backend/tests/test_seo_canonicals.py) for verify/leaderboard/public-profile canonicals. Template structural test extended with RSS alternate assertion. Local: 447 passed (was 441; +6 net). Pre-existing unrelated failure: `test_jobs_sources.py::test_ashby_skips_unlisted_jobs` — Windows asyncio-events RuntimeError, not mine. **Live verification**: feed.xml serves `application/rss+xml` with 2 items (post 01 + post 02); all 5 canonicals present live (`/blog` → blog, `/leaderboard` → leaderboard, `/verify` → verify after nginx 301 to trailing-slash, `/account` → account, profile covered by test with DB user). **Known minor**: HEAD on `/blog/feed.xml` returns 405 — FastAPI's `@router.get` doesn't auto-bind HEAD. Feed readers GET, so harmless in practice. If W3C validator or Feedly ever trips on HEAD, add `@router.api_route(methods=["GET", "HEAD"])`. Deploy: `git pull && docker compose up -d --build --force-recreate backend web` (Python code change + frontend file change).
- **2026-04-22** — SEO-06 shipped (✅) in two commits. **Commit A (`ff0336d`)** — Jinja2-migrated the per-post template out of [backend/app/routers/blog.py](../backend/app/routers/blog.py) `_render_post` (110-line f-string) to [backend/app/templates/blog/post.html](../backend/app/templates/blog/post.html). RCA-027 prevention pattern, mirroring the `admin/jobs_guide.html` migration done last month — Jinja2 inverts brace semantics so future schema/code/JSON additions cannot crash module import. No behavior change for current renders. Added 6 regression tests in new [backend/tests/test_blog.py](../backend/tests/test_blog.py) (no prior coverage on this router): /blog/01 + dynamic /blog/{slug} render via Jinja2, no syntax leaks, 404 paths preserved (unknown slug + legacy-hidden flag), template file present + uses Jinja2 syntax, direct render with dummies. **Commit B (`8094878`)** — added Article JSON-LD `<script>` block in `<head>` of the migrated template. Full property set per plan: `headline`, `datePublished`, `dateModified`, `author` (Person), `publisher` (Organization with `ImageObject` logo), `image`, `mainEntityOfPage`, `description`. Every value piped through Jinja2's `tojson` filter — quotes/control-chars/`<` are JSON-escaped (`<` → `<`), neutralizing any `</script>` injection attempt (validated by `test_post_article_json_ld_safe_against_script_injection`). `_render_post` gained `author: str = "Manish Kumar"` parameter; `post_dynamic` threads `payload.get("author", ...)` so guest-author posts surface correctly in JSON-LD; meta tags + meta-line stay hardcoded "Manish Kumar" (preserves "no behavior change for non-JSON-LD rendering" constraint). 3 new JSON-LD-specific tests added (full Article spec assertion, guest-author plumbing, XSS defense) — total 9 blog tests, all pass. **dateModified falls back to datePublished** with a TODO comment in the template — blog post payloads (POST_01 constants + dynamic JSON pipeline) don't track `updated_at` today; future session can wire `last_reviewed_on` through `load_published()` when the model gains it. **og-default.png does not exist yet** (tracked under SEO-11); Rich Results Test tolerates non-200 image URLs. Deploy: `ssh a11yos-vps "cd /srv/roadmap && git pull && docker compose up -d --build --force-recreate backend"` per `feedback_deploy_rebuild.md` (Python code change requires rebuild + recreate). **Live verification**: rendered HTML on both `https://automateedge.cloud/blog/01` (23149 bytes) and `https://automateedge.cloud/blog/02-why-most-ai-roadmaps-expire-before-you-finish-them` (21070 bytes) parses cleanly with `json.loads`, all 10 required Article keys present, ISO-8601 dates with Z suffix, headlines 65 + 50 chars (within Google's ≤110 guideline). External Rich Results Test + Schema Markup Validator on the live URLs recommended as the final acceptance step (the runtime parse + key-presence check we ran is the equivalent of the "Code tab" pass).
- **2026-04-21** — Competitive-intel research pass (four parallel subagents: roadmap.sh teardown, MOOC schema teardown, content-blog teardown, 10-query SERP recon). Added §3.5 Competitive intelligence. Revised SEO-01 (added `Disallow: /og/`), SEO-02 (sub-sitemap split by resource type + `<image:>` extensions + `lastmod` on every URL), SEO-05 (full Coursera-grade Course property set — `hasCourseInstance.courseWorkload`, `syllabusSections[]`, `teaches`, `coursePrerequisites`, `offers.category`; separate FAQPage block), SEO-11 (promoted P1→P0-adjacent, standardized on `/og/{type}/{slug}.png` matching roadmap.sh). Added new tasks SEO-19 (10 programmatic comparison pages with FAQPage + DefinedTerm schema targeting the single most beatable SERP query `AI engineer vs ML engineer`), SEO-20 (30 quintet pages across 5 tracks), SEO-21 (pillar content cluster with validator-enforced 10-point quality bar), SEO-22 (VideoObject on YouTube embeds), SEO-23 (aggregateRating + Review gated on ≥5 genuine testimonials), SEO-24 (hub ItemList schema), SEO-25 (trusted-sources allowlist + E-E-A-T enforcement), SEO-26 (`/start` quiz landing). Rewrote §5 Content strategy with concrete slugs in priority order (q6 → q7 → q2 → q4 → intent-gaps), 10-point quality bar, and 24-week cadence. Still no implementation — next action remains SEO-00 (GSC + Bing connect + baseline).
- **2026-04-24** — SEO-20 + SEO-24 shipped (✅) jointly. **SEO-20 — 30 per-track quintet pages** at `/roadmap/{track}/{section}` for 5 tracks (`generalist`, `ai-engineer`, `ml-engineer`, `data-scientist`, `mlops`) × 6 sections (`skills`, `tools`, `projects`, `certifications`, `salary`, `career-path`). Per-track JSON files at [backend/app/data/tracks/](../backend/app/data/tracks) — generalist written by Opus (reference contract); the other 4 generated in parallel by Sonnet subagents using the contract + per-track briefs. New router at [backend/app/routers/track_pages.py](../backend/app/routers/track_pages.py) loads all tracks at import time (hard-fail on missing file) and serves 8 routes (`/roadmap` hub + `/roadmap/{track}` track-hub + 6 section paths × any track). 8 templates under [backend/app/templates/tracks/](../backend/app/templates/tracks): `_base.html` (shared skeleton), `hub.html`, `track_hub.html`, `skills.html`, `tools.html`, `projects.html`, `certifications.html`, `salary.html`, `career_path.html`. Each section page emits Article + section-specific schema (ItemList for skills/tools/projects/certifications, HowTo for career-path, Dataset for salary) + BreadcrumbList + FAQPage. **SEO-24 — `/roadmap` hub ItemList** rendered by `tracks/hub.html` enumerating all 5 tracks (numberOfItems + position + url + name) with BreadcrumbList. **Sitemap**: [backend/app/routers/seo.py](../backend/app/routers/seo.py) `/sitemap-pages.xml` extended to enumerate all 36 new URLs (1 hub + 5 track hubs + 30 sections). **nginx**: [nginx.conf](../nginx.conf) allowlist regex `^/roadmap/[a-z][a-z0-9-]{1,40}(/[a-z][a-z0-9-]{1,40})?$` for `/roadmap/{track}/{section}` plus exact `= /roadmap` block. **Tests**: 154 new tests in [backend/tests/test_tracks.py](../backend/tests/test_tracks.py) covering schema-key sanity (all 5 tracks have all 13 top-level keys), ≥7 FAQs per section, 200 + ≥1000 visible words on every URL (excluding JSON-LD payload from word count), required schemas per page type, FAQs render visibly matching FAQPage schema, canonical match, 404 on unknown track/section, and sitemap inclusion of all 36 URLs. All 154 pass; full suite 683 pass / 1 pre-existing Windows-asyncio failure. **One-bug-found-and-fixed during integration**: Jinja2 resolves `cat.items` to the dict's builtin `.items()` method rather than the data field named `items` — fixed across 3 templates by switching to `cat['items']` / `section['items']` bracket-access. **Editorial decisions**: salary bands track each role's market reality (ML Engineer highest at top-of-market, Data Scientist compressed below specialists in 2026, AI Engineer near software-engineer parity, MLOps tracking ML Engineer at hyperscalers); India/SEA use absolute local-currency bands rather than multipliers; certifications restricted to free programs except for 3 paid CKA/GCP/AWS items (each flagged with explicit "employer reimbursement only" caveat in the MLOps track); compare.html "coming soon" footer link to `/roadmap/{track}` now resolves to a real page. **Word-count results per page (Opus + 4 Sonnet agents): generalist sections all clear 1500+ words; ai-engineer 1615-2917; data-scientist 1471-2881; ml-engineer 1927-3462; mlops 1441-3215. All 30 pages clear the 1000-word acceptance floor with substantial headroom.** Deploy: `git pull && docker compose up -d --build --force-recreate backend web` (Python code change + new templates + new data files + nginx.conf change requires both rebuilds). External validation pending: Rich Results Test on one URL per page-type (skills, tools, projects, certifications, salary, career-path) + the hub. **Agent-utilization**: Opus = generalist.json (~5500 words content) + router + 8 templates + nginx + sitemap + tests + diff-review of 4 subagent JSONs. Sonnet × 4 in parallel = ai-engineer.json + ml-engineer.json + data-scientist.json + mlops.json (each ~75-100 KB JSON, ~2000-3000 words per section, average runtime ~9 min, all completed first-attempt). codex:rescue: skipped — no load-bearing path touched (no alembic, no auth, no AI-prompt code, no jobs_ingest/enrich).
- **2026-04-24** — SEO-25 ✅ + SEO-21/22 foundation 🟡 (one commit). **SEO-25 — trusted-sources allowlist** at [backend/data/trusted_sources.json](../backend/data/trusted_sources.json): 42 domains across 7 categories (papers: arxiv/paperswithcode/openreview/jmlr/semanticscholar; lab-docs: openai/anthropic/deepmind/ai.google/research.google/ai.meta/huggingface/mistral/cohere; framework-docs: pytorch/tensorflow/scikit-learn/numpy/scipy/pandas/jupyter/python; statistics: bls/weforum/economicgraph.linkedin/octoverse/github.blog/stackoverflow.blog; academic: aiindex.stanford/stanford/mit/berkeley/cmu/ox/cam/nature/science; textbook: d2l/deeplearningbook/distill; standards: nist/ieee/acm). New [backend/app/services/blog_validator.py](../backend/app/services/blog_validator.py) with `load_trusted_sources()` + `is_trusted_domain()` using safe suffix-match (tests confirm `fakemeta.com` does NOT match `meta.com`, and `meta.com.attacker.io` is rejected). **SEO-21 foundation — validate_pillar()** enforces all 10 checks verbatim from docs/SEO.md §SEO-21: word-count tier (pillar 3000 / flagship 4500), first non-lede paragraph 40-60 words (featured-snippet target), 8-12 H2 sections, ≥40 internal links (relative `/...` + absolute `automateedge.cloud` both count), ≥5 trusted citations from the SEO-25 allowlist, schemas must include Article + FAQPage + at least one of {HowTo, DefinedTerm, VideoObject, ItemList}, 8-15 FAQ pairs, comparison `<table>` when `comparative: true`, dateModified freshness warning at 90-day stale, og_image path validation. **Tier-gating** is the key design — `validate_pillar` returns ok=True with no-op stats when `pillar_tier` is absent, so standard build-in-public posts pass through `blog_publisher.validate_payload` unchanged. **Banned-terms list split** in [blog_publisher.py](../backend/app/services/blog_publisher.py) into `_OPERATIONAL_LEAKS` (repo paths, session numbers, commit hashes — always blocked) and `_VOICE_TERMS` (AI providers + tech stack — blocked for standard tier only). This unblocks pillar posts mentioning OpenAI/Anthropic/PyTorch while keeping operational leaks blocked everywhere. **SEO-22 foundation — `build_video_object()`** emits JSON-LD per the SEO.md schema (name/description/thumbnailUrl/uploadDate/duration/contentUrl/embedUrl); duration coercion accepts ISO-8601 (`PT14M23S`), `mm:ss` (`14:23` → `PT14M23S`), and `h:mm:ss` (`1:14:23` → `PT1H14M23S`). Defaults thumbnail to `https://i.ytimg.com/vi/{id}/maxresdefault.jpg` per the SEO.md template. `validate_videos_metadata()` gates publish: if `youtube_ids` is declared, every id must have matching cached metadata (id+title+description+published_at+duration) in `videos[]` — prevents shipping with stale/incomplete harvest output. **Wiring**: `blog_publisher.validate_payload()` now calls both `validate_pillar` (when `pillar_tier` set) and `validate_videos_metadata` (always), merging errors/warnings/stats — admin publish flow (`/api/blog/validate` + `/api/blog/draft` + `/api/blog/publish`) gets the new gates for free. **Tests**: 45 new in [backend/tests/test_blog_validator.py](../backend/tests/test_blog_validator.py) covering every one of the 10 pillar checks + absolute-vs-relative internal-link counting + trusted-domain suffix-match safety + VideoObject emitter happy/malformed paths + duration coercion + integration through `validate_payload` (standard post still rejects AI-provider names; pillar post is free to mention them; pillar post still blocks operational leaks). Full suite: **719 passed / 1 skipped / 0 failures** (was 683 pre-change). 1 pre-existing collection error (`test_jobs_digest.py` can't import `aiosmtplib` — env issue, unrelated). Deploy: `git pull && docker compose up -d --build --force-recreate backend` (Python code change only — no nginx/template change this ship). **Status board**: SEO-21 + SEO-22 moved ⬜ → 🟡 (foundation shipped; first pillar post with video embed is the full-acceptance deliverable). SEO-25 moved ⬜ → ✅. **Agent-utilization**: Opus = `blog_validator.py` + `trusted_sources.json` + integration edits in `blog_publisher.py` + 45 pillar validator tests. Sonnet: n/a — single-module validator, not parallel-eligible. Haiku: n/a — no bulk sweeps. codex:rescue: **skipped** — `blog_validator.py` is content-quality gate code (no auth/AI-classifier path touched, no Alembic migration, no jobs_ingest/enrich), and the allowlist is explicitly a low-trust pre-filter that a human still reviews before publish. Will engage for SEO-26 (Alembic migration for `quiz_outcomes`).
- **2026-04-24** — SEO-21 first pillar post authored (1 of 6) + template foundation closure. **Post** at [docs/blog/03-ai-engineer-vs-ml-engineer.json](./blog/03-ai-engineer-vs-ml-engineer.json) targets q6 ("AI engineer vs ML engineer" — most beatable SERP per §5.1 recon). Validator stats: **3134 words** (3000 floor), **50-word first non-lede paragraph** (40-60 target — engineered for the featured-snippet slot), **10 H2s** (8-12 target), **46 internal links** (40 floor — spread across both AI/ML track hubs, all 12 track-section pages, /jobs, /blog/01+02, /vs/ai-engineer-vs-ml-engineer, /roadmap hub, /), **7 trusted citations** (5 floor — Stanford AI Index, BLS occupational outlook, arXiv 1706.03762 Attention, Hugging Face Transformers, OpenAI platform docs, PyTorch, Papers with Code), **10 FAQs** (8-15 target; drawn from People Also Ask), **1 seven-dimension comparison table**, **4 DefinedTerms** (AI Engineer, ML Engineer, Foundation Model, Retrieval-Augmented Generation). Schemas declared: Article + FAQPage + DefinedTerm. Validator: `ok=True, 0 errors, 2 editorial warnings` (8 paragraphs >4 sentences, 10 sentences >30 words — judgment calls for a dense pillar, non-blocking). **Template wire-up** landed in the same commit — closes a previously undetected SEO-21 foundation gap: the pillar validator checks that `schemas` *declares* Article + FAQPage + satisfier, but the blog post template ([backend/app/templates/blog/post.html](../backend/app/templates/blog/post.html)) only emitted Article + BreadcrumbList. Added conditional `<script type="application/ld+json">` blocks for `FAQPage` (when `payload.faqs` present) and `DefinedTermSet` with child `DefinedTerm` entries (when `payload.defined_terms` present). [backend/app/routers/blog.py:443](../backend/app/routers/blog.py#L443) `_render_post` threads both fields from `load_published()`. Render test against the session-39 payload: all four JSON-LD blocks (Article, BreadcrumbList, FAQPage[10], DefinedTermSet[4]) parse as valid JSON via `json.loads`. **Allowed-tags expansion**: [backend/app/services/blog_publisher.py:87](../backend/app/services/blog_publisher.py#L87) `_ALLOWED_TAGS` gains `table/thead/tbody/tr/th/td` — comparative pillar posts (`comparative: true`) require a `<table>` per SEO-21 rule 8, and pre-fix every such post threw a non-standard-tag warning. Browser-native tags, zero XSS risk (`body_html` is admin-authored via the publish flow). Tests: 65 blog tests pass, 0 regressions (full suite not re-run; changes are additive). **Deploy**: `git pull && docker compose up -d --build --force-recreate backend` (Python + template change). **Publish**: pending admin action via `/admin/blog` once deploy lands (paste JSON → draft → review → publish; IndexNow ping fires automatically per SEO-07). 5 pillar posts remain (q7, q2, q4, intent-gap q3/q4, intent-gap q10) — one per session, standard Opus-editorial authoring pass. **Agent-utilization**: Opus = all authoring + template wire-up + validator dry-runs + HANDOFF/SEO.md/§9 updates. Sonnet: n/a (single-author editorial, not parallel-eligible). Haiku: n/a (2-call VPS verify cheaper as direct Opus tool calls). codex:rescue: deferred — no load-bearing path touched (no auth/AI-classifier, no Alembic, no jobs_ingest/enrich); engagement point remains SEO-26 (`quiz_outcomes` migration).
- **2026-04-24** — SEO-01 flipped 🟡 → ✅ after edge re-verification. No code/config change this session; Cloudflare Managed robots.txt behavior changed (or the CF-dashboard merge was landed between sessions) such that the edge now **appends** our origin block instead of replacing it. Live GET on `https://automateedge.cloud/robots.txt` returns 200, `Content-Type: text/plain; charset=utf-8`, 1900 bytes with the CF-managed AI-bot block (`Content-Signal: search=yes,ai-train=no`; `Disallow: /` for Amazonbot, Applebot-Extended, Bytespider, CCBot, ClaudeBot, CloudflareBrowserRenderingCrawler, Google-Extended, GPTBot, meta-externalagent) followed by our custom `User-agent: *` group (`Disallow: /admin`, `/api`, `/account`, `/share/`, `/og/`, `Allow: /`) and the `Sitemap: https://automateedge.cloud/sitemap_index.xml` directive. Googlebot-UA GET returns identical merged 1900-byte body — confirms crawlers see both layers. Per robots.txt spec, Google merges multiple `User-agent: *` groups into a single ruleset, so our Disallows apply to Googlebot/Bingbot while CF's specific-UA blocks fully exclude the AI-training crawlers. Sitemap URL resolves cleanly (5 sub-sitemaps enumerated). One observed CF quirk: HEAD returns `Content-Length: 162` (origin file only) while GET returns 1900 — real crawlers GET, so harmless. All acceptance bullets satisfied except the user-side "GSC robots.txt report shows 'Fetched'" check — scheduled as part of SEO-00 baseline-accumulation window. Memory entry [reference_cloudflare_edge.md](file:///C:/Users/manis/.claude/projects/E--code-AIExpert/memory/reference_cloudflare_edge.md) updated from "CF overrides with 404 + managed body" to "CF merges origin + managed body with 200 — preferred outcome from §4's fix options is now live." No commit needed for this status/doc sync unless batched with other SEO doc edits.
