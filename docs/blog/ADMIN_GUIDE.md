# Blog admin operational guide

How to ship a post from empty-page to live. For editorial rules
(voice, image style, banned terms, frontmatter) read
[STYLE.md](./STYLE.md). For system internals read
[SYSTEM.md](./SYSTEM.md). This doc is the how-to once you know what
you want to say.

---

## The six-step flow

```
1. Pick a title + one-sentence angle
2. /admin/blog → paste title → Generate → Copy the prompt
3. Paste into Claude.ai (Opus 4.6, fresh chat) → wait 45-90s
4. Upload Claude's JSON artifact (or paste) → Validate → Save as draft
5. Edit the draft in-place → tune copy → upload hero image → Preview
6. Publish from the drafts list
```

Expect 30-60 minutes end to end. Most of it lives in step 5.

---

## Step 1 — Title + angle

A good title names the reader's question. A good angle answers it.

| Weak | Strong |
|---|---|
| "Update on the platform" | "Why AutomateEdge stopped auto-publishing curricula" |
| "Our values" | "Why every AI pipeline on the site has a human button" |
| "Lessons learned" | "Three things I shipped too early — and one I shipped too late" |

Angle (optional) is one sentence on what you want the post to *say*.
Example: *"Policy beats tools. Every AI pipeline needs a human
button, even if the button does nothing but exist."*

The stronger the angle, the more directly Claude writes toward it.

---

## Step 2 — Generate the prompt

Go to `/admin/blog` (admin subnav → Blog).

- Fill in **Title** (required) and **Angle** (optional)
- Click **Generate prompt**
- Click **Copy prompt** — clipboard is loaded

The system auto-numbers the slug (next `NN-` across drafts + published
+ the hardcoded post 01) and bakes title, angle, slug, today's date,
and your name into the prompt before returning it.

No backend AI spend. This is purely a string-substitution endpoint.

---

## Step 3 — Paste into Claude.ai

Click **Open Claude.ai ↗**. In a **new chat** (fresh context matters):

1. Pick **Claude Opus 4.6** from the model picker (top-right).
2. Paste the prompt. Send.
3. Wait 45-90 seconds.

Claude returns a **downloadable JSON artifact** titled `<slug>.json`
(per the prompt's output contract). Click the download button on the
artifact to save it to disk. If for any reason Claude returns raw JSON
in the chat body instead of an artifact, you can copy-paste — the
upload form accepts both.

---

## Step 4 — Upload the JSON

Back on `/admin/blog`, scroll to **section 2 — Upload Claude's JSON**:

- Click **📂 Upload JSON file** and pick the downloaded artifact, **OR**
- Paste Claude's raw JSON into the textarea.

Then click **Validate**. The auto-validator runs ~25 checks:

- **Schema**: every required field present, correct types, date
  format, tag count, image brief fields.
- **Banned terms** (blocking): scans title + lede + body + og + tags
  for stack names, AI provider names, repo URLs, session numbers,
  internal identifiers, credits, etc. — ~45 patterns.
- **Length**: 800-1500 words in body, ≤30 words in lede, ≤200 chars
  in og_description.
- **Structure**: ≥3 `<h2>` sections, `<p class="lede">` opener, `<hr>`
  before closing, no `<script>` / `<style>` / `<h1>` in body.
- **Voice heuristics** (warnings only): flag paragraphs >4 sentences,
  sentences >30 words.
- **Image brief sanity**: prompt length, filename extension.

**Red errors block publication. Amber warnings are editorial
judgement calls** — review them, fix if they bite, ship if they don't.

When clean, click **Save as draft**. The file lands on the VPS at
`/data/blog/drafts/<slug>.json`.

---

## Step 5 — Edit the draft (the real work)

The drafts table gains a new row. Click the **title** or the
**Edit** button to open `/admin/blog/<slug>/edit` — a full-width
form with every field editable:

### Identity card
- **Title** (max 150 chars)
- **Slug** — changing breaks existing links, renames the file on disk
- **Author**, **Published** (ISO date)
- **Tags** — comma-separated, 3-5, first must be `build-in-public`
- **OG description** — ≤200 chars

### Body card
- **Lede** — plain text, one sentence, under 30 words
- **Body HTML** — tall textarea. Opens with `<p class="lede">`, ≥3
  `<h2>` sections, ≤4 sentences per paragraph
- **Word count** — re-measured on save

### Hero image card (two-column)
- **Left**: 16:9 preview + **📤 Upload image** button (PNG/JPG/WEBP
  ≤5 MB). Shows the current image if one exists.
- **Right**: prompt, alt text, filename. Upload auto-fills filename
  and swaps the preview.

The image file lands at `/data/blog/assets/<slug>-hero.<ext>` on the
VPS and is served at `/blog/assets/<filename>` with immutable cache
headers — so your body HTML can reference it as `<img src="/blog/assets/..." alt="...">`.

### Quotables + notes card
- **Quotable lines** — one per line; 1-2 shareable sentences
- **Angle note** — not published, editorial commentary for yourself

### Sticky action bar
- **Discard changes** (back to list without saving)
- **Validate** (re-runs the checks)
- **Save changes** (re-validates, writes back, redirects to list)

The editor preserves non-edited metadata (`_saved_at`, `_saved_by`,
etc.) by overlaying your edits on the original JSON. Slug renames
are handled by deleting the stale file on disk automatically.

### Preview anytime
Every draft row + the editor toolbar has a **Preview ↗** button.
Opens `/admin/blog/<slug>/preview` in a new tab — the post rendered
through the exact same template as the public `/blog/<slug>` route,
plus a sticky amber **DRAFT PREVIEW** banner so you can never confuse
it with live. Sidebar TOC + between-post nav also render so you can
eyeball what the full page will look like.

---

## Step 6 — Publish

From the drafts list, click the draft's **Publish** button.

- The draft re-runs through the validator (rules may have drifted
  since save). Errors block; warnings pass.
- JSON moves from `/data/blog/drafts/` → `/data/blog/published/`.
- Your name + today's ISO date stamp as `last_reviewed_by` and
  `last_reviewed_on` on the JSON.
- Post goes live at `https://automateedge.cloud/blog/<slug>`.

The public blog index at `/blog` picks it up automatically, sorted
newest-first.

---

## Unpublishing — both kinds

Two types of posts, two kinds of unpublish:

### JSON-pipeline posts (everything from 02 onward)
Drafts table → Published section → **Unpublish** button.
Moves the JSON back to `/data/blog/drafts/`. Content preserved. You
can edit and republish with a new review stamp.

### Legacy hardcoded post 01
Baked into `backend/app/routers/blog.py` as Python strings (pre-JSON
pipeline). Still unpublishable from the UI via the **Unpublish**
button on the "Legacy" row — but it's a visibility flag, not a file
move:

- Click → toggles `/data/blog/_legacy.json` to `{"hidden": ["01"]}`
- `/blog/01` immediately starts returning 404
- Row re-renders with strike-through title + slate "Hidden" pill +
  green **Republish** button

Flip it back any time. Source code stays untouched; it's pure
visibility. When post-01 migrates to JSON, this branch goes away.

---

## The drafts + published list

Section 3 on `/admin/blog` is a single status-aware table:

| Status | Row shows | Actions |
|---|---|---|
| Draft | title (amber link to editor), slug, saved-by + date | Edit · Preview ↗ · Re-check · Publish · Delete |
| Published | title (amber link to live post), slug, reviewed-by + date | View ↗ · Re-check · Unpublish |
| Legacy (visible) | linked title + slate "Legacy" pill | View ↗ · Unpublish |
| Legacy (hidden) | struck-through title + slate "Hidden" pill | Republish |

Counts line above the table shows `📝 N drafts · ✅ M published` at a
glance.

---

## Common pitfalls

- **Claude returns markdown instead of JSON artifact.** Start a new
  chat with Opus 4.6 specifically — older models don't always respect
  the artifact contract. Paste the prompt verbatim.
- **Claude adds "Here's your post!" prefix.** Strip it. The JSON must
  start with `{`.
- **Paragraphs over 4 sentences warning.** This was the single most
  common warning on early drafts; the prompt now enforces it in four
  separate places. If it still fires, split the flagged paragraphs in
  the editor and re-validate.
- **Hero image has baked-in text ("THE BLOG" watermark).** Re-render
  in your image tool. AI-generated text in images always reads as
  amateur.
- **Committed without the image file.** Images upload directly to
  `/data/blog/assets/` on the VPS via the admin UI — no git commit
  needed. If the hero preview on `/admin/blog/<slug>/edit` is empty,
  the file isn't there; upload it.
- **Stale og_description after editing.** The validator doesn't
  enforce alignment between og_description and lede — but social
  previews will drift. Update OG when you rewrite the opening.
- **Validation passed on save, fails on publish.** Rules drift over
  time. Re-open the editor, re-validate, fix, save, then publish.

---

## Post-publish

- Open `/blog/<slug>` in an incognito window to verify nav + sidebar +
  TOC render.
- Paste the URL into [opengraph.xyz](https://www.opengraph.xyz/) to
  check the LinkedIn card preview.
- Share on LinkedIn with one of the `quotable_lines` as the post
  body. Generic *"new blog post!"* announcements underperform by a
  mile.
- Log the post in `docs/HANDOFF.md` for session continuity.

---

## Where everything lives on the VPS

All blog state is under the `/data` volume mount (survives container
rebuilds, backed up with the rest of `/data`):

```
/data/blog/
├── drafts/<slug>.json        ← unpublished posts
├── published/<slug>.json     ← live posts (served at /blog/<slug>)
├── assets/<slug>-hero.<ext>  ← uploaded hero images
└── _legacy.json              ← visibility toggle for hardcoded posts
```

Backup snapshot: `tar czf /srv/roadmap/data/blog-backup-$(date +%F).tgz /srv/roadmap/data/blog`
