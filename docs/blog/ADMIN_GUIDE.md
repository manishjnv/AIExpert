# Admin guide — shipping a blog post

Operational runbook for publishing a new post on `automateedge.cloud/blog/*`.
For editorial rules (voice, image style, banned terms, frontmatter) read
[STYLE.md](./STYLE.md) first. This doc is the how-to once you know what
you want to say.

## The 9-step flow

```
1. Think of a title + one-sentence angle
2. /admin/blog → paste title → Generate → Copy
3. Paste into Claude.ai (Opus 4.6, fresh chat) → wait 45-90s
4. Review Claude's markdown against the pre-publish checklist
5. Save markdown to docs/blog/<slug>.md
6. Hand-convert the body to HTML in backend/app/routers/blog.py
7. Generate the hero image using the brief at the end of the post
8. Drop image in docs/blog/assets/<slug>-hero.png
9. Commit all three files, push, deploy
```

Expect 45–75 minutes total. Most of it is steps 4 and 6.

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

Titles and angles tell Claude the thesis; it writes toward it.

## Step 2 — Generate the prompt

Go to `/admin/blog` (admin subnav → Blog). Fill in **Title** (required)
and **Angle** (optional). Click **Generate prompt**.

The system:
- Auto-numbers the slug (next `NN-` in `docs/blog/`).
- Renders the Claude Opus prompt with title + angle + slug + today's
  date + your name baked in.
- Shows the result in a copyable textarea.

Click **Copy prompt**. Your clipboard is loaded.

No backend AI cost. No draft saved anywhere yet. This is just a
prompt generator.

## Step 3 — Paste into Claude.ai

Click **Open Claude.ai ↗**. In a **new chat** (fresh context matters):
1. Pick **Claude Opus 4.6** from the model picker (top-right).
2. Paste the prompt.
3. Send.

Wait 45–90 seconds. Claude returns raw Markdown that starts with
`---` (frontmatter) and ends with an HTML-comment image brief.

If Claude wraps the output in a ` ```markdown ` code fence, strip it
before saving. The contract says no fences; if it slipped through, it
is a prompt drift you can fix next time by re-emphasising the output
contract in the chat.

## Step 4 — Review against the pre-publish checklist

Before saving anything, read Claude's output end-to-end once. Then
grep / skim for:

**Content gates**
- [ ] No stack names (`FastAPI`, `SQLite`, `WeasyPrint`, `pydyf`, `HMAC`, `SHA256`, `JWT`, `nginx`, `Docker`, `alembic`, `pytest`).
- [ ] No AI provider or model names (`Gemini`, `Claude`, `GPT`, `OpenAI`, `Anthropic`, `Google`, `Groq`, `Cerebras`, `Mistral`, `DeepSeek`, `Sambanova`, `LangChain`, `MCP`).
- [ ] No repo URLs, GitHub links, `source code` phrasing, or session numbers.
- [ ] No exact credit balances, per-call costs, or env-var names.

**Voice gates**
- [ ] Hook works in the first 15 words — would *you* read the second sentence?
- [ ] At least one concrete story / specific moment / real number.
- [ ] At least one quotable line you could screenshot for LinkedIn.
- [ ] No paragraph longer than 4 sentences.
- [ ] No sentence longer than 30 words (unless unavoidable).
- [ ] 800–1500 words in the body (rough count — `wc -w`).
- [ ] Closing CTA matches the template verbatim.

**Structure gates**
- [ ] Frontmatter has all six fields in order (`title`, `slug`, `author`, `published`, `tags`, `og_description`).
- [ ] Tags are learner-facing (no tech names).
- [ ] Image brief is present inside the closing HTML comment.

If any line fails, **either** ask Claude for a targeted rewrite in the
same chat (`"Rewrite the X section without mentioning FastAPI"`),
**or** edit manually. Do not publish with a gate failure.

## Step 5 — Save the markdown

```bash
# From the repo root
cat > docs/blog/02-some-slug.md  # paste, then Ctrl-D
```

Or save via your editor — same result. The filename must match the
slug in the frontmatter exactly.

## Step 6 — Hand-convert to HTML (the dual-source rule)

Every post lives in two places:
- `docs/blog/<slug>.md` — markdown source of truth.
- `backend/app/routers/blog.py` — hand-converted HTML, actually served.

When shipping post N:
1. Copy post `01`'s structure inside `blog.py` as a template:
   `POST_02_TITLE`, `POST_02_DESCRIPTION`, `POST_02_PUBLISHED`,
   `POST_02_BODY`.
2. Convert the markdown body to HTML by hand. Mapping:
   - `# Heading` → `<h1>Heading</h1>`
   - `## Section` → `<h2>Section</h2>`
   - Paragraphs → `<p>...</p>`
   - `**bold**` → `<strong>bold</strong>`
   - `_italic_` → `<em>italic</em>`
   - Lede paragraph → `<p class="lede">...</p>`
   - Bullet list → `<ul><li>...</li></ul>`
   - `---` horizontal rule → `<hr>`
   - `[text](url)` → `<a href="url">text</a>`
3. Add the route: `@router.get("/blog/02")` and `/blog/02/`.
4. `POST_02_DESCRIPTION` goes into OG tags — keep it short (≤ 200 chars)
   and free of banned terms.

> **Why the duplication?** The blog ships no markdown renderer at
> runtime (keeps the backend lean). When there are 4+ posts we'll
> lift this out to a tiny renderer. Until then, one commit, two files.

## Step 7 — Hero image

At the bottom of Claude's output you'll find an HTML comment with an
`IMAGE-BRIEF` block. It contains a prompt and an alt-text line.

Paste the prompt into your preferred image tool:
- **Midjourney** (best results for photoreal-digital).
- **Gemini Imagen** (free with a Google account).
- **DALL·E 3** (via ChatGPT or the API).
- **Adobe Firefly** (royalty-free commercial output).

Render at **16:9** for the hero. Re-roll until you get one without
obvious AI tells (six-fingered hands, warped text, glass doing
impossible things).

Save as `docs/blog/assets/<slug>-hero.png`.

If Claude's prompt is too generic, edit before rendering. You're
the editor here.

## Step 8 — Wire the image into the published page

Inside the `POST_02_BODY` HTML, insert after the lede:

```html
<figure class="hero">
  <img src="/blog/assets/02-hero.png"
       alt="<literal description from the image brief>"
       loading="lazy" width="1600" height="900">
</figure>
```

The `/blog/assets/` path will need a small static-file route if it
isn't already wired — check `backend/app/routers/blog.py` and the
nginx config. If not yet wired, add the image route while you're
there (this is a one-time setup; post 03 onward inherits).

## Step 9 — Commit, push, deploy

```bash
git add docs/blog/<slug>.md \
        backend/app/routers/blog.py \
        docs/blog/assets/<slug>-hero.png

git commit -m "blog: ship post <NN> — <title>"
git push origin master

ssh a11yos-vps "cd /srv/roadmap && git pull && \
  docker compose build backend && \
  docker compose up -d --force-recreate backend"
```

Then visit `https://automateedge.cloud/blog/<slug>` and verify:
- Page renders with the hero image.
- Lede is italicised and readable in isolation.
- No broken internal links.
- OG preview works — paste the URL into
  [opengraph.xyz](https://www.opengraph.xyz/) and check the card.

## Common pitfalls

- **Claude adds "Here's your post!" prefix.** Strip it. The output
  must start with `---`. If this keeps happening, re-emphasise the
  output contract in the chat.
- **Frontmatter fields reordered.** Fix manually. Order matters for
  any future static-site generator we add.
- **Bullet lists become paragraphs of `-`.** Happens when you forget
  to preserve newlines during paste. Redo the paste.
- **Hero image has baked-in text ("THE BLOG" watermark).** Re-render.
  AI-generated text in images always reads as amateur.
- **Forgot to update the `og_description`** after editing the post.
  Social previews will drift from the content. Fix before commit.
- **Committed without the image.** GitHub will show a broken-image
  icon. Double-check the `git status` before pushing.

## Post-publish

- Screenshot the live page (desktop + mobile) and drop into
  `docs/screenshots/blog-<slug>.png` for future use.
- Share on LinkedIn with one of the quotable lines from the post as
  the post body (not a generic "new blog post!" announcement — that
  performs poorly).
- Log the post in `docs/HANDOFF.md` for session continuity.

---

That's the whole loop. Steps 1-3 are 5 minutes. Step 4 is where
judgement lives. Everything after is mechanical.
