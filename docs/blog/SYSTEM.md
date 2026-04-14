# Blog system — architecture reference

How the `/blog` end-to-end pipeline is wired: files, endpoints,
validators, storage, public rendering. For the admin workflow read
[ADMIN_GUIDE.md](./ADMIN_GUIDE.md). For editorial rules read
[STYLE.md](./STYLE.md). This doc is for future contributors and the
next me who comes back in six months having forgotten how it works.

---

## High-level pipeline

```
┌──────────┐   1   ┌──────────────┐   2   ┌───────────────┐
│  Admin   │──────▶│ /admin/blog  │──────▶│ Claude.ai Max │
│  (title) │       │  (generator) │       │   (Opus 4.6)  │
└──────────┘       └──────┬───────┘       └───────┬───────┘
                          │                       │ 3 (JSON artifact)
                          ▼                       ▼
                   ┌──────────────────────────────────┐
                   │ /admin/blog  (upload + validate) │
                   └──────┬───────────────────────────┘
                          │ 4 (Save as draft)
                          ▼
              ┌──────────────────────────────┐
              │ /data/blog/drafts/<slug>.json │
              └──────┬───────────────────────┘
                     │ 5 (Edit in-place, preview,
                     │    upload hero image)
                     ▼
              ┌──────────────────────────────┐
              │ /data/blog/published/<slug>  │◀─── 6 (Publish,
              └──────┬───────────────────────┘     stamps reviewer)
                     │
                     ▼                     7 (Public GET)
              ┌──────────────────────────────┐
              │     /blog/<slug>  (live)     │
              └──────────────────────────────┘
```

No backend AI spend anywhere in this flow — Claude Max chat does the
heavy lifting. The platform's only jobs are substituting placeholders
into the prompt, validating uploads, and rendering HTML from JSON.

---

## File layout

```
backend/app/
├── prompts/
│   └── claude_blog_manual.txt   ← the single source of truth for
│                                   what Claude generates. Embeds
│                                   STYLE.md rules + 25-item
│                                   self-check.
├── services/
│   └── blog_publisher.py        ← validate + save + publish + list
│                                   + image storage + legacy toggle
└── routers/
    ├── admin.py                 ← admin UI + admin-only endpoints
    │                              (/admin/blog, /admin/api/blog/*)
    └── blog.py                  ← public routes
                                   (/blog, /blog/<slug>, /blog/assets)

docs/blog/
├── ADMIN_GUIDE.md               ← operational how-to
├── STYLE.md                     ← editorial rules
├── SYSTEM.md                    ← (this file)
├── 01-building-automateedge-solo.md  ← legacy post 01 source (sunset
│                                       when 01 migrates to JSON)
└── assets/                       ← (screenshot space; real blog
                                     images live in /data/blog/assets)

VPS (persistent, mounted as /data in container):
/srv/roadmap/data/blog/
├── drafts/<slug>.json            ← in-progress posts
├── published/<slug>.json         ← live posts
├── assets/<slug>-hero.<ext>      ← uploaded hero images
└── _legacy.json                  ← {hidden: [slug, ...], audit: [...]}
```

---

## JSON schema (the wire format)

Every upload and every saved file follows this shape. Additions
require updating the validator in lockstep.

```json
{
  "title": "string, ≤150 chars",
  "slug": "NN-kebab-case, matches ^\\d{2,3}-[a-z0-9-]+$",
  "author": "string",
  "published": "YYYY-MM-DD",
  "tags": ["build-in-public", "topic", "topic"],   // 3-5 items, [0] pinned
  "og_description": "1-2 sentences, target ≤200 chars",
  "lede": "plain text, one sentence, ≤30 words, no HTML",
  "body_html": "HTML fragment, no <html>/<head>/<body> wrappers",
  "word_count": 1200,
  "image_brief": {
    "hero_prompt": "image-gen prompt, 40-90 words",
    "hero_alt": "one-sentence literal description",
    "hero_filename": "<slug>-hero.png"
  },
  "quotable_lines": ["line 1", "optional line 2"],
  "angle_note": "optional — editorial note, not published",

  // Set automatically by save_draft():
  "_saved_by": "admin name/email",
  "_saved_at": "ISO 8601 UTC",

  // Set automatically by publish_draft():
  "last_reviewed_by": "admin name/email",
  "last_reviewed_on": "YYYY-MM-DD",
  "_published_at": "ISO 8601 UTC"
}
```

### body_html allowlist

`<p>`, `<h2>`, `<h3>`, `<strong>`, `<em>`, `<a>`, `<ul>`, `<ol>`,
`<li>`, `<hr>`, `<br>`, `<blockquote>`, `<code>`, `<figure>`,
`<img>`, `<span>`, `<div>`, `<pre>`.

Disallowed (blocking): `<script>`, `<style>`, `<h1>` (template owns
the page title).

Non-allowlisted tags render fine in the browser but produce a
validator warning so the admin notices inconsistency.

---

## Validator — what blocks vs warns

Implemented in `backend/app/services/blog_publisher.py::validate_payload`.
Returns `{ok, errors, warnings, stats}`. `ok` is False iff `errors` is
non-empty; warnings never block.

### Blocking (must fix to save / publish)

1. Missing required field.
2. Title empty or >150 chars.
3. Slug doesn't match `^\d{2,3}-[a-z0-9-]+$`.
4. `published` not a valid ISO date.
5. `tags` not a 3–5 list, or `tags[0] != "build-in-public"`.
6. `og_description` empty.
7. `lede` empty, >30 words, or contains `<` / `>`.
8. Body word count below 800.
9. Fewer than 3 `<h2>` sections.
10. `<script>` or `<style>` in body_html.
11. **Banned terms** in title / lede / body / og / tags. ~45 regex
    patterns covering:
    - Stack names (FastAPI, SQLite, nginx, Docker, pydantic, etc.)
    - AI providers + models (Gemini, Claude, GPT, OpenAI, Groq,
      Cerebras, Mistral, DeepSeek, Sambanova, LangChain, MCP, etc.)
    - Implementation details (HMAC, SHA256, JWT, bcrypt, WeasyPrint)
    - Repo URLs, "source code" phrase, `manishjnv/AIExpert`
    - Session numbers, commit hashes

### Warnings (editorial judgement)

- `og_description` > 220 chars (may truncate in previews).
- Body > 1500 words.
- `claimed word_count` differs from measured by > 50.
- < 5 `<p>` elements (post feels thin).
- Any paragraph with > 4 sentences.
- Any sentence with > 30 words.
- `<p class="lede">` missing as body opener.
- No `<hr>` before closing CTA.
- Non-allowlisted tags present.
- Zero `quotable_lines` provided.
- `hero_prompt` < 40 chars (likely too generic).
- `hero_filename` missing image extension or doesn't match slug prefix.

### Stats returned alongside

`word_count`, `paragraphs`, `h2_count`, `long_paragraphs`,
`long_sentences`, `quotable_lines`, `tags_count`, `og_length`.

---

## Admin endpoints (all require `get_current_admin` + CSRF origin check)

All under `/admin/`:

| Method | Path | Purpose |
|---|---|---|
| GET | `/admin/blog` | Admin UI — prompt generator + upload + drafts + published list |
| GET | `/admin/blog/<slug>/edit` | Full-field editor for a draft |
| GET | `/admin/blog/<slug>/preview` | Render any draft or published post with an amber/green preview banner |
| POST | `/admin/api/render-blog-prompt` | `{title, angle}` → rendered Claude prompt |
| POST | `/admin/api/blog/validate` | `{json payload}` → validator report, no persistence |
| POST | `/admin/api/blog/draft` | `{json payload}` → validate + save |
| POST | `/admin/api/blog/draft/update` | `{json payload, _original_slug}` → validate + overwrite, handles slug rename |
| GET | `/admin/api/blog/validate-draft?slug=` | Re-validate a saved draft without re-pasting |
| POST | `/admin/api/blog/publish` | `{slug}` → draft → published + stamps reviewer |
| POST | `/admin/api/blog/unpublish` | `{slug}` → published → draft (non-destructive) |
| POST | `/admin/api/blog/legacy-toggle` | `{slug, hidden}` → toggle hidden flag for hardcoded posts |
| POST | `/admin/api/blog/image` | multipart `image` + `slug` → `/data/blog/assets/<slug>-hero.<ext>` |
| DELETE | `/admin/api/blog/draft` | `{slug}` → hard delete draft |

---

## Public endpoints

All under root:

| Method | Path | Purpose |
|---|---|---|
| GET | `/blog` | Index page — list every visible post |
| GET | `/blog/<slug>` | Render a single post via `_render_post` |
| GET | `/blog/<slug>/` | Trailing-slash alias |
| GET | `/blog/01` | Legacy hardcoded post (respects hidden flag) |
| GET | `/blog/assets/<filename>` | Serve uploaded hero images with `Cache-Control: public, max-age=31536000, immutable` |

`nginx.conf` proxies `/blog` (exact) and `/blog/` (prefix) to the
backend — both required so the index without trailing slash works.

---

## Public rendering — layout

The `_render_post` template (in `backend/app/routers/blog.py`)
outputs an HTML page with:

```
┌──────────────────────────────────────────────────────┐
│ shared topnav (injected by nav.js in body)           │
├──────────────────────────────────────────────────────┤
│                                                      │
│    ┌──────────────────────────┐  ┌──────────────┐   │
│    │    post-article (720px)  │  │ post-sidebar │   │
│    │                          │  │   (300px,    │   │
│    │  breadcrumb              │  │   sticky,    │   │
│    │  published meta line     │  │   ≥1100px)   │   │
│    │                          │  │              │   │
│    │  <body_html>             │  │ · More posts │   │
│    │    - lede                │  │ · Contents   │   │
│    │    - h2 / h2 / h2 / ...  │  │   (JS-built) │   │
│    │    - closing CTA         │  │ · Share      │   │
│    │                          │  │              │   │
│    │  <hr> post-nav           │  │              │   │
│    │    - Prev / Next cards   │  │              │   │
│    │    - More posts grid     │  │              │   │
│    │                          │  │              │   │
│    └──────────────────────────┘  └──────────────┘   │
│                                                      │
├──────────────────────────────────────────────────────┤
│ shared footer (injected by nav.js on DOMContentLoaded)│
└──────────────────────────────────────────────────────┘
```

Below 1100px the sidebar hides; the bottom post-nav covers
discovery. Reading width stays at 720px regardless of viewport
(editorial-optimal; widening body copy hurts comprehension).

The **Contents** block is populated client-side by a small inline
script that scans `.post-article h2` at DOMContentLoaded, generates
anchor IDs, builds the `<ul>`, and wires a scroll-spy handler to
highlight the currently-visible section.

---

## Legacy post-01 branch

Post 01 was shipped before the JSON pipeline existed. Its content
still lives as Python string constants in `routers/blog.py`
(`POST_01_TITLE`, `POST_01_BODY`, `POST_01_DESCRIPTION`,
`POST_01_PUBLISHED`). The route is hand-coded (`@router.get("/blog/01")`).

To give the admin a non-destructive unpublish path without requiring
a code deploy, `is_legacy_hidden(slug)` reads `/data/blog/_legacy.json`
at request time. The post-01 route checks the flag and raises 404 if
hidden. `set_legacy_hidden(slug, hidden, admin_name)` flips the flag
and stamps an audit entry (capped at last 100 events).

Everywhere the admin UI enumerates posts, the legacy post is synthesised
into the list with a `"type": "legacy"` row so it can be shown with the
same affordances — with a dedicated `"Legacy"` badge and a toggle
button instead of the file-based unpublish used for JSON posts.

When post 01 migrates to the JSON pipeline, drop the legacy branch
from both `routers/blog.py` and the admin UI rendering.

---

## Between-post navigation

`_render_post_nav(current_slug, base)` is appended at the end of
every post. It reads `_list_visible_posts()` — which merges
`list_published()` + non-hidden legacy — and produces:

1. **Prev / Next pair**: two side-by-side cards. At the edges of
   the list the missing side renders as a dashed placeholder
   ("You're reading the freshest post" / "You've reached the first
   post") so readers understand they're at a boundary, not bugged.

2. **More posts grid**: up to 3 other posts (excluding current and
   already-shown neighbours), responsive auto-fit columns. If there
   are more than 4 others, a `See all posts →` shortcut sits next
   to the header.

3. **Empty-single-post CTA**: when the current post is the only one,
   everything above collapses to a centred "This is the only post so
   far — more on the way. Back to blog →".

4. **Draft-preview edge case**: if the current slug isn't in the
   public list (admin previewing a draft), prev/next is hidden and
   the grid shows up to 3 live posts — the preview still gives the
   admin a sense of how nav will render when the post goes live.

---

## Hero image pipeline

Upload flow:

1. Admin picks a file in the editor (PNG/JPG/WEBP, ≤5 MB).
2. Multipart POST to `/admin/api/blog/image` with `image` file and
   `slug` form field.
3. `save_image()` validates size + extension, writes to
   `/data/blog/assets/<safe-slug>-hero.<ext>`. Returns
   `{filename, path, url, size}`.
4. Admin UI auto-fills the `hero_filename` field with the returned
   filename and swaps the preview (cache-busted with `?t=<now>`).

Serving flow:

1. Browser requests `/blog/assets/<filename>`.
2. `GET /blog/assets/<filename>` → `blog_publisher.get_asset_path()`
   runs a strict whitelist (no path separators, no null bytes,
   extension in `{.png, .jpg, .jpeg, .webp}`, resolves to within
   `ASSETS_DIR`).
3. Valid → `FileResponse` with `Cache-Control: public, max-age=31536000,
   immutable`. Invalid → 404.

Images are served by the backend, not by nginx static — no extra
nginx config needed, and the cache headers mean the browser + CDN
still only fetch each image once.

---

## Testing

Current coverage:

- **Validator unit tests**: planned, not yet written. Validator is
  exercised end-to-end through the admin UI.
- **End-to-end flow tests**: planned. A full upload → save → publish
  → fetch would belong in `backend/tests/test_blog_flow.py`.

Manual smoke test after any blog-system change:

```bash
# Local
docker compose build backend
pytest -q

# Prod
ssh a11yos-vps "cd /srv/roadmap && git pull && \
  docker compose build backend && \
  docker compose up -d --force-recreate backend"

# Verify
curl -s https://automateedge.cloud/blog | grep -oE '<title>|No posts'
curl -s https://automateedge.cloud/blog/01 | grep -oE 'post-article|post-sidebar'
```

---

## Failure modes seen and fixed

- **nginx /blog 404** — `location /blog/ {}` only matches with
  trailing slash; added `location = /blog` exact-match. Fix lives in
  `nginx.conf`.
- **Footer rendering at top of page** — `nav.js` was appending via
  `document.body.appendChild()` at parse-time (when body was empty).
  Deferred to `DOMContentLoaded`.
- **Nav rendering twice on /admin/blog** — page loaded nav.js via
  both `<head>` and `{ADMIN_NAV}` body substitution. Removed the head
  link.
- **Claude outputs markdown instead of JSON** — happened before
  Opus-4.6 was explicitly named in the prompt. Fixed by adding
  `"Use Claude Opus 4.6"` + explicit artifact instructions in the
  admin UI how-to.
- **Paragraphs over 4 sentences warning on post-01** — prompt now
  repeats the hard limit in 4 separate sections and includes a
  worked before/after split example.
