# Blog authoring guide

Every post on `/blog/*` follows this playbook. Read before writing the next one.

## 1. Voice — simple English, slight humour

**Simple English.** Write for a smart learner who does not have a computer-science degree. The reader might be a product manager, a career-changer, a college student, or a curious recruiter. If a sentence would lose a bright high-schooler, it is too complex.

Rules of thumb:

- Short sentences beat long sentences. Split when in doubt.
- Common words beat impressive ones. "Use" beats "utilise". "Build" beats "architect".
- One idea per paragraph. If a paragraph turns into a list, make it a list.
- Prefer active voice. "I picked SQLite" not "SQLite was chosen".
- Cut filler. "In order to" → "to". "At this point in time" → "now". "Due to the fact that" → "because".
- Avoid jargon. If a term is unavoidable, explain it in the same sentence: *"A webhook (a small URL the other app calls when something happens) …"*.

**Slight humour.** One well-placed dry line per 4–6 paragraphs. Not a comedy routine. Think *The Economist* on a good day, not stand-up.

Good humour on this blog sounds like:

- *"The thing at the top of the 'you should learn this first' list is rarely the thing you should learn first six months later. Nobody maintains them."*
- *"If a generation pipeline ever lands work that ships to users without a human button, I have failed the learner."*
- *"A free product with ten real learners beats a brilliant product with zero."*

Dry, observational, self-deprecating. Never:

- Punching down at users, competitors, or recruiters.
- Memes, emoji punchlines, or "lol".
- Jokes that depend on insider tech culture (Stack Overflow-ese, Reddit-ese).

If removing the joke would not break the point, keep the joke short or drop it.

## 2. Images — realistic + digital

Every blog post ships **at least one hero image** and should ideally include one or two inline images that break up long text stretches.

**Style:**

- Realistic, digital — photographic-looking, not cartoon, not stock-illustration, not emoji, not hand-drawn.
- Dark-palette friendly (the blog background is `#0f1419`).
- Amber, slate, or muted warm accents preferred — they harmonise with the brand.
- Subtle grain / depth-of-field is fine. Flat vector ClipArt is not.

**Sourcing, in priority order:**

1. **Real product screenshots** — `docs/screenshots/` already has hero, certificate, leaderboard, week-card, resources-split, footer-brand, certificate-modules, leaderboard-help. Use these first when the post discusses a feature.
2. **AI-generated images** from a model capable of photorealism (Midjourney, Imagen, DALL·E 3, Gemini Imagen). Prompt template:
   > *"A photorealistic close-up of <subject>, warm amber and slate lighting, shallow depth of field, cinematic, 16:9, high detail, editorial photography style. No text, no logos, no watermarks."*
   Always render 16:9 landscape for heroes, 4:3 or 1:1 for inline.
3. **Stock** only if 1 and 2 fail. Use Unsplash (free, credit in alt text) and avoid anything that screams "corporate banner".

**Do not use:**

- AI images with obvious tells (six-fingered hands, warped text, impossible glass reflections). If it looks fake at a glance, re-render.
- Screenshots with real user PII (other learners' names, emails, credential IDs that are not our public sample `AER-2026-04-YSE8SJ`).
- Images that imply guarantees we do not make — a photo of a smiling graduate in a cap with "HIRED!" text oversells.

**File naming:** `docs/blog/assets/<slug>-<role>.<ext>` — for example `docs/blog/assets/01-hero.png`, `02-certificate-inline.jpg`. Keep assets next to the markdown source.

**Alt text is mandatory.** Describe what is literally in the image in one sentence. Screen readers, broken-link fallback, SEO.

## 3. What to show, what to hide

The public blog is learner- and recruiter-facing. It is **not** a changelog.

**Show:**

- Why the product exists — the learner problem.
- What a learner actually does on the site (features described from their side).
- Design principles (human review, anti-gaming rules, honest framing of credential value).
- Lessons learned framed as product decisions.
- Roadmap bullets — from a user's perspective.

**Hide:**

- Stack names (FastAPI, SQLite, WeasyPrint, pydyf, SQLAlchemy, nginx, Docker, etc.).
- AI provider names and model IDs (Gemini 2.5, Groq, Cerebras, Claude, OpenAI, Anthropic, Mistral, DeepSeek, Sambanova).
- Internal implementation details (HMAC algorithms, field names from JSON or DB, version pinning, regex patterns, the specific XP formula weights, env-var names).
- Source code repo URL.
- Session numbers, commit hashes, internal file paths.
- Exact paid credit balances or per-call costs.

If the sentence only makes sense to someone who has seen the codebase, cut it or rewrite it for a learner.

## 4. JSON schema contract

Posts are authored as JSON (not Markdown). The full schema lives in
[SYSTEM.md](./SYSTEM.md#json-schema-the-wire-format). Fields Claude
Opus emits for every post, in this order:

- `title` (≤150 chars)
- `slug` (NN-kebab-case, auto-numbered by the prompt generator)
- `author` (string)
- `published` (ISO date)
- `tags` (3-5 strings, first must be `build-in-public`)
- `og_description` (≤200 chars target)
- `lede` (plain text, one sentence, ≤30 words)
- `body_html` (HTML fragment — allowed tags listed in SYSTEM.md)
- `word_count` (integer)
- `image_brief` (hero prompt + alt + filename)
- `quotable_lines` (array of shareable sentences)
- `angle_note` (editorial commentary, not published)

Tag picks must be learner-facing: `ai-learning`, `curriculum`,
`certificates`, `leaderboard`, `solo-founder`, `product`,
`gamification`, `career`, `education`. **NEVER** use technology names
as tags.

## 5. Structure

Default outline — deviate when the topic demands it, but start here:

1. **Hero line (`<p class="lede">`)** — one sentence that says what the post is about, readable in isolation.
2. **Why this exists / Why now** — the problem or the hook.
3. **What it does / What changed** — concrete, learner-facing.
4. **Principles / how the decision was made** — optional, if the post is a lesson.
5. **What I got wrong** — honesty wins. One or two items, no humble-brag.
6. **What's next** — 3–5 bullets.
7. **Closing note** — one line. Always include a contact CTA.

Target length **800–1500 words**. Under 800 feels like a tweet. Over 1500 loses the recruiter.

## 6. Storage — the VPS is the source of truth

Posts live as JSON under `/data/blog/` on the VPS:

- `drafts/<slug>.json` — in-progress, invisible to readers
- `published/<slug>.json` — live at `/blog/<slug>`
- `assets/<slug>-hero.<ext>` — uploaded hero images
- `_legacy.json` — visibility flag for the hardcoded post 01

No markdown source files, no git commits per post, no hand-converted
HTML twins. Every admin action (save, publish, edit, image upload,
unpublish) writes to disk directly through the admin UI. Full
architecture in [SYSTEM.md](./SYSTEM.md).

The only exception is post 01, which was written before the JSON
pipeline existed and still lives as Python constants in
`routers/blog.py`. It'll migrate to JSON when I next regenerate it.

## 7. Checklist before publishing

Run through every item. If any fail, fix before you push.

- [ ] Read out loud. If a sentence trips your tongue, rewrite it.
- [ ] Zero forbidden terms — see section 3. Grep before you commit.
- [ ] Exactly one hero image, at least one inline image.
- [ ] All images have alt text.
- [ ] Frontmatter validated — slug is new, tags are learner-facing, OG description matches.
- [ ] Markdown copy and the HTML in `blog.py` say the same thing.
- [ ] A human read the post end-to-end. Typos lose more trust than broken links.
- [ ] Live site loads `/blog/<slug>` with a 200 and the OG preview on LinkedIn is clean (test via <https://www.opengraph.xyz/>).

## 8. Cadence

One post a month is ambitious. One post a quarter is realistic. One post a year is not a blog.

Whichever cadence you pick, put the next slot on the calendar the day this one ships.
