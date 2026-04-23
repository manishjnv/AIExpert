"""
Blog router — simple static-HTML pages, one per post.

We don't ship a markdown library as a runtime dep (rule #9 in CLAUDE.md).
The canonical source of each post lives in docs/blog/*.md; the HTML here
is a hand-polished render of that source. When a second post ships, lift
this out to a generic renderer.
"""

from __future__ import annotations

import email.utils as _email_utils
from datetime import date as _date, datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape as _xml_escape

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import get_settings


router = APIRouter()


# ---- Jinja2 template env (RCA-027 prevention) ---------------------------------
#
# Migrated _render_post from a triple-quoted f-string to a Jinja2 template after
# RCA-027 (literal { } in JSON / code samples crashed module import in admin.py
# the same way). Jinja2 inverts brace semantics: { is literal by default, only
# {{ var }} interpolates — so future schema/code/JSON additions can no longer
# crash the import. See backend/app/templates/blog/post.html.

_BLOG_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
_blog_template_env = Environment(
    loader=FileSystemLoader(str(_BLOG_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


POST_01_TITLE = "Building AutomateEdge Solo — A Free, AI-Curated Learning Platform"
POST_01_DESCRIPTION = (
    "Why AutomateEdge exists, what it does for learners, and what I'd do "
    "differently. An honest take from a solo builder on curating AI learning "
    "that stays current, stays free, and treats the learner's time like it matters."
)
POST_01_PUBLISHED = "2026-04-13"


POST_01_BODY = """
<h1>Building AutomateEdge Solo</h1>
<p class="lede">A free, self-paced platform that gives anyone a personalised,
AI-curated study plan to learn modern AI from scratch — then tracks their
progress, grades their practice work, and hands them a verifiable certificate
when they finish.</p>

<p>This is the honest story. Why I built it, what it actually does today,
what I got wrong along the way, and where it's going next.</p>

<h2>Why this exists</h2>
<p>The AI learning content that already exists falls into two buckets.</p>
<p>Static roadmaps are one-size-fits-all and drift within a quarter. The
thing at the top of "you should learn this first" is rarely the right
starting point six months later. Nobody maintains them.</p>
<p>Paid cohort programs solve the currency problem but gate on price and
schedule. If you work a full-time job and live in a timezone where the live
sessions fall at 2 AM, you're not the target.</p>
<p>AutomateEdge sits between them. The curriculum is curated from trending
signals — university course catalogues, practitioner writing, current
research themes — and re-evaluated every quarter. It's free. Learners
enrol, get a plan tailored to their duration, level, and career goal,
link their practice work as they build, and graduate with a signed
credential they can show a recruiter.</p>

<h2>What it does for a learner</h2>
<p>You pick a duration (3, 6, or 12 months) and a level (beginner,
intermediate, advanced). You get a week-by-week plan with focus areas,
deliverables, curated resources split into video courses and docs/practice,
and a checklist per week.</p>
<p>You can link your GitHub repos to the weeks they match. An AI mentor can
answer questions scoped to what you're working on right now — it sees the
current week's focus areas, not the whole internet. If you've told the
platform you're targeting a security engineer role, the mentor anchors its
examples there instead of a generic data-science framing.</p>
<p>When you cross 90% completion with the capstone month at 100%, you earn
a Completion certificate. Finish everything and link enough repos and it
upgrades to Distinction. Ship something an automated evaluator scores 8/10
or higher and it upgrades again to Honors. Each upgrade preserves your
original credential ID and issue date — it's a progression, not a reissue.</p>

<h2>The curriculum stays current by policy, not magic</h2>
<p>Quarterly refresh runs an AI discovery pass that proposes additions and
retirements against the previous cycle. The output feeds a quality pipeline
— <strong>generate → review → refine → validate → score</strong> — that
grades every candidate template across fifteen dimensions: cognitive
progression, theory/practice ratio, project density, assessment quality,
freshness, prerequisites, real-world readiness, and others.</p>
<p>A template that scores well becomes <em>publishable</em>, not
<em>published</em>. An admin still has to click Publish. That click stamps
who reviewed it and when, and that stamp is visible to learners. It's a
small thing that makes the difference between "some algorithm decided this
was good" and "a human vouched for this on this date". The score is a
filter, not a judge.</p>
<p>I shipped auto-publish at first. Within two days, a confidently-wrong
template had gone live. I pulled it, added the human gate, wrote a rule in
my notebook: <em>every generation pipeline gets a human button, even if the
button does nothing but exist</em>.</p>

<h2>The certificate actually means something (a little)</h2>
<p>Most platform certificates are lipstick on a spreadsheet. A recruiter
can't tell the difference between one you earned and one you forged in
Canva.</p>
<p>AutomateEdge certificates are signed and verifiable. Every credential ID
has a cryptographic signature baked into it. Anyone with the ID can visit
a public verification page and see a green "Credential verified" badge —
or a red one, if the signature doesn't match. If someone writes a fake ID
on their resume, the verify page will say so.</p>
<p>The page also shows the learner's display name (snapshotted at the moment
of issue, so editing your profile name later doesn't retroactively change
an issued certificate), the course title, the module breakdown, completion
stats, and the issue date. It's designed to be the thing a recruiter sees
in 20 seconds and either believes or doesn't.</p>
<p>Am I calling this a real industry credential? No. It's a portfolio proof
with tamper detection, and I'm honest about that distinction. The long-term
play is to position AutomateEdge courses as <em>preparation for</em>
recognised certs and let the existing trust do the heavy lifting.</p>

<h2>The leaderboard is the most motivating page on the site</h2>
<p>It started as a "maybe some people want to see a ranking" idea and
turned out to be the highest-engagement page I have.</p>
<p>Learners are ranked by XP, which is earned from real activity: checklist
tasks, GitHub repos shipped, certificates earned (weighted by tier), and
active weekly streaks. There are seven tiers — Apprentice, Learner,
Practitioner, Builder, Engineer, Architect, AI Guru — each with its own
coloured chip and a mini progress bar showing how close you are to the next
one. Achievement pills decorate the page for milestones like First Task,
Triple Crown (three certs), 10-week Hot Streak.</p>
<p>Two rules keep it honest. <strong>Distinct repos, not repo-links</strong>
— linking the same repo to five weeks doesn't earn you 5× the XP, so you
can't farm. <strong>Every number is a live query</strong> — there's no
placeholder data, no fake users, no editorial curation. If the page says
you're Top 5%, the arithmetic agrees.</p>
<p>There's also a help panel on the leaderboard that spells out exactly how
every signal maps to XP, what each tier requires, and what triggers each
badge. No mystery meat — if you want to climb, the rules are published.</p>

<h2>What I got wrong</h2>
<p><strong>The auto-publish decision, covered above.</strong> If a
generation pipeline ever lands work that ships to users without a human
button, I have failed the learner.</p>
<p><strong>Feature breadth before traction.</strong> I built an internal
cost dashboard, batch refinement, a provider fallback chain, and
embedding-based topic dedup before I had more than a handful of users. The
right order was the opposite: get people on the site, learn what they
actually need, build for that.</p>
<p><strong>Gut-based picks that cost time.</strong> I spent weeks
convinced one specific AI model was the right tool for a specific task
because it had the strongest reputation. The measurement eventually said a
different model was better for that workload. I had the evidence well before
I acted on it. Lesson: trust the benchmark you ran, not the benchmark you
read.</p>
<p><strong>Not writing a post-mortem every session.</strong> This is it.
I'm fixing it now.</p>

<h2>What's next</h2>
<ul>
  <li>An admin UI for revoking a credential if a genuine issue surfaces.</li>
  <li>Timeframe tabs on the leaderboard (all-time, this month, this week) —
  new learners can climb the monthly ranking fast and stay engaged through
  their first 30 days, which is the riskiest window.</li>
  <li>An AI news feed and an AI jobs board. "I finished my course, now
  what?" is the most common question from early learners; answering it
  on-platform is the obvious move.</li>
  <li>More courses beyond the three generalist tracks. The quality pipeline
  is mature enough now that the bottleneck is human review capacity, not
  generation.</li>
</ul>

<h2>If you're thinking of building something similar</h2>
<p>Ship the boring version first. Every layer you don't add is one you
don't have to keep alive.</p>
<p>Build for the user you have, not the user you wish you had. A free
product with ten real learners beats a brilliant product with zero.</p>
<p>Measure everything that isn't free, and set a hard budget cap. It's the
difference between catching a mistake at a dollar and discovering it at
fifty.</p>
<p>And write the post-mortem at the end of every session, even if the only
reader is tomorrow-you.</p>

<hr>
<p class="meta">
  <strong>Live site:</strong>
  <a href="https://automateedge.cloud">automateedge.cloud</a><br>
  <strong>Contact:</strong> Open the footer → Contact. I read everything.
</p>
"""


_BLOG_CSS = """
<style>
  :root { color-scheme: dark; }
  body {
    margin: 0; background: #0f1419; color: #e8e4d8;
    font-family: Georgia, 'Times New Roman', serif;
    line-height: 1.7; font-size: 17px;
  }
  /* Two-column layout on wide screens: 720px article + 260px sidebar.
     Below 1100px the sidebar drops off and the bottom post-nav covers
     discovery. Article stays at an editorial-optimal reading width
     regardless of viewport — widening body copy hurts comprehension. */
  main {
    max-width: 1080px; margin: 0 auto;
    padding: 48px 24px 96px;
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 48px;
  }
  @media (min-width: 1100px) {
    main {
      max-width: 1120px;
      grid-template-columns: minmax(0, 720px) 300px;
      align-items: start;
    }
  }
  .post-article { min-width: 0; }
  .post-sidebar {
    position: sticky; top: 80px;
    font-family: 'IBM Plex Sans', system-ui, sans-serif;
    font-size: 14px; color: #c0c4cc;
    max-height: calc(100vh - 100px);
    overflow-y: auto;
    padding-right: 4px;
  }
  @media (max-width: 1099px) { .post-sidebar { display: none; } }
  .sb-block { margin-bottom: 32px; }
  .sb-block h4 {
    font-family: 'IBM Plex Mono', ui-monospace, monospace;
    font-size: 10px; letter-spacing: 0.16em; text-transform: uppercase;
    color: #94a3b8; margin: 0 0 14px; font-weight: 500;
  }
  .sb-post {
    display: block; text-decoration: none; color: inherit;
    padding: 10px 12px; margin-bottom: 8px; border-radius: 6px;
    border: 1px solid transparent; transition: all 0.15s;
  }
  .sb-post:hover {
    background: #1a2029; border-color: #2a323d;
  }
  .sb-post .sb-date {
    font-family: 'IBM Plex Mono', ui-monospace, monospace;
    font-size: 10px; letter-spacing: 0.08em; color: #64748b;
    margin-bottom: 3px;
  }
  .sb-post .sb-title {
    font-family: 'Fraunces', Georgia, serif;
    font-size: 14px; color: #e8e4d8; line-height: 1.35; font-weight: 500;
  }
  .sb-post:hover .sb-title { color: #e8a849; }
  .sb-post.current {
    background: rgba(232,168,73,0.08);
    border-color: rgba(232,168,73,0.25);
  }
  .sb-post.current .sb-title { color: #e8a849; font-style: italic; }
  .sb-toc { list-style: none; padding: 0; margin: 0; font-size: 13px; }
  .sb-toc li { margin-bottom: 6px; line-height: 1.4; }
  .sb-toc a {
    color: #94a3b8; text-decoration: none;
    padding-left: 10px; border-left: 2px solid #2a323d;
    display: block; padding-top: 3px; padding-bottom: 3px;
    transition: all 0.15s;
  }
  .sb-toc a:hover { color: #e8a849; border-left-color: #e8a849; }
  .sb-toc a.active {
    color: #e8a849; border-left-color: #e8a849;
    background: rgba(232,168,73,0.05);
  }
  .sb-share {
    display: flex; gap: 8px; flex-wrap: wrap;
  }
  .sb-share a {
    flex: 1 1 auto; text-align: center;
    padding: 8px 10px; border: 1px solid #2a323d; border-radius: 4px;
    color: #c0c4cc; text-decoration: none; font-size: 11px;
    font-family: 'IBM Plex Mono', ui-monospace, monospace;
    letter-spacing: 0.08em; text-transform: uppercase;
    transition: all 0.15s;
  }
  .sb-share a:hover {
    color: #e8a849; border-color: #e8a849; background: rgba(232,168,73,0.05);
  }
  .meta-line {
    color: #94a3b8; font-family: ui-monospace, SFMono-Regular, monospace;
    font-size: 12px; text-transform: uppercase; letter-spacing: 0.1em;
    margin-bottom: 32px;
  }
  h1 {
    font-family: 'Fraunces', Georgia, serif;
    font-size: clamp(28px, 5vw, 42px); line-height: 1.15;
    color: #f5f1e8; margin: 0 0 24px; font-weight: 700;
  }
  h2 {
    font-family: 'Fraunces', Georgia, serif;
    font-size: 24px; color: #e8a849; margin: 48px 0 12px;
  }
  p { margin: 0 0 16px; }
  .lede { font-size: 19px; color: #d0cbc2; font-style: italic; }
  code {
    background: #1d242e; padding: 1px 6px; border-radius: 3px;
    font-size: 0.9em; color: #e8a849;
    font-family: ui-monospace, SFMono-Regular, 'Cascadia Mono', monospace;
    word-break: break-word;
  }
  pre {
    overflow-x: auto; overflow-y: hidden; max-width: 100%;
  }
  img { max-width: 100%; height: auto; display: block; }
  a { color: #e8a849; text-decoration: underline; text-underline-offset: 3px; }
  a:hover { color: #f5c06a; }
  ul { padding-left: 22px; margin: 0 0 16px; }
  li { margin-bottom: 6px; }
  hr { border: 0; border-top: 1px solid #2a323d; margin: 48px 0 24px; }
  .meta { color: #94a3b8; font-size: 15px; }
  strong { color: #f5f1e8; }
  /* Navbar compat */
  body > nav { font-family: system-ui, -apple-system, sans-serif; }

  /* ----- Post-level navigation ----- */
  .post-breadcrumb {
    font-family: 'IBM Plex Mono', ui-monospace, monospace;
    font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase;
    color: #94a3b8; margin-bottom: 24px;
    display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  }
  .post-breadcrumb a {
    color: #e8a849; text-decoration: none;
    padding: 4px 10px; border: 1px solid rgba(232,168,73,0.3);
    border-radius: 999px; transition: all 0.2s;
  }
  .post-breadcrumb a:hover {
    background: rgba(232,168,73,0.1); border-color: #e8a849;
  }
  .post-breadcrumb .sep { opacity: 0.4; }
  .post-breadcrumb .current {
    color: #c0c4cc;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    max-width: 60ch;
  }
  .post-nav-hr {
    border-top-color: #2a323d; margin: 64px 0 36px;
  }
  .post-nav {
    font-family: 'IBM Plex Sans', system-ui, sans-serif;
    line-height: 1.5;
  }
  .nav-pair {
    display: grid; grid-template-columns: 1fr 1fr; gap: 14px;
    margin-bottom: 32px;
  }
  @media (max-width: 640px) {
    .nav-pair { grid-template-columns: 1fr; }
    .post-breadcrumb .current { max-width: 30ch; }
  }
  .nav-card {
    display: block; text-decoration: none;
    background: #1a2029; border: 1px solid #2a323d; border-radius: 8px;
    padding: 18px 20px; color: inherit;
    transition: all 0.2s ease;
  }
  .nav-card:hover {
    border-color: #e8a849; transform: translateY(-2px);
    background: #1d242e;
  }
  .nav-label {
    font-family: 'IBM Plex Mono', ui-monospace, monospace;
    font-size: 10px; letter-spacing: 0.15em; text-transform: uppercase;
    color: #e8a849; margin-bottom: 6px;
  }
  .nav-date {
    font-family: 'IBM Plex Mono', ui-monospace, monospace;
    font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase;
    color: #94a3b8; margin-bottom: 6px;
  }
  .nav-title {
    font-family: 'Fraunces', Georgia, serif;
    font-size: 17px; color: #f5f1e8; font-weight: 500;
    line-height: 1.3; margin-bottom: 8px;
  }
  .nav-summary {
    font-size: 13px; color: #c0c4cc; line-height: 1.5;
    overflow: hidden; text-overflow: ellipsis;
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
    max-height: 3em;
  }
  .nav-card-edge {
    border-style: dashed; background: transparent; cursor: default;
  }
  .nav-card-edge:hover {
    border-color: #2a323d; transform: none; background: transparent;
  }
  .nav-edge-msg {
    font-size: 13px; color: #94a3b8; font-style: italic; margin-top: 4px;
  }
  .nav-more {
    margin-top: 8px;
  }
  .nav-more-header {
    display: flex; align-items: baseline; justify-content: space-between;
    margin-bottom: 14px; flex-wrap: wrap; gap: 10px;
  }
  .nav-more-header h3 {
    font-family: 'Fraunces', Georgia, serif;
    font-size: 18px; color: #e8a849; margin: 0; font-weight: 500;
  }
  .nav-all-link {
    font-family: 'IBM Plex Mono', ui-monospace, monospace;
    font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase;
    color: #e8a849; text-decoration: none;
  }
  .nav-all-link:hover { color: #f5c06a; }
  .nav-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 14px;
  }
  .post-nav-empty {
    text-align: center; padding: 24px 0; color: #94a3b8;
  }
  .post-nav-empty p {
    font-style: italic; margin: 0 0 14px; font-size: 14px;
  }
  @media (max-width: 480px) {
    main { padding: 32px 16px 72px; }
    h1 { margin: 0 0 16px; }
    h2 { margin: 32px 0 8px; font-size: 22px; }
    body { font-size: 16px; }
    .lede { font-size: 17px; }
    .post-breadcrumb { font-size: 10px; gap: 6px; margin-bottom: 16px; }
  }
</style>
"""


def _render_post(
    slug: str,
    title: str,
    description: str,
    body_html: str,
    published: str,
    author: str = "Manish Kumar",
) -> str:
    settings = get_settings()
    base = settings.public_base_url.rstrip("/")
    url = f"{base}/blog/{slug}"
    og_image = f"{base}/og/blog/{slug}.png"
    post_nav_html = _render_post_nav(slug, base)
    sidebar_html = _render_post_sidebar(slug, title, url, base)
    return _blog_template_env.get_template("blog/post.html").render(
        title=title,
        description=description,
        url=url,
        og_image=og_image,
        published=published,
        author=author,
        blog_css=_BLOG_CSS,
        body_html=body_html,
        sidebar_html=sidebar_html,
        post_nav_html=post_nav_html,
    )


def _render_post_sidebar(current_slug: str, current_title: str, current_url: str, base: str) -> str:
    """Right-rail sidebar on wide screens — uses the blank space beside
    the 720px article. Three blocks:
      - More posts: up to 5 posts (excluding current) with date + title.
        Current post is highlighted when present in the public list.
      - Contents: auto-built client-side from the article's <h2> headings
        (the <ul> is populated by the inline script).
      - Share: LinkedIn + Twitter/X prefilled links.

    Mobile (<1100px): hidden via CSS; the bottom post-nav covers
    discovery.
    """
    import html as _html
    from urllib.parse import quote as _q

    posts = _list_visible_posts()

    # More posts list
    list_items: list[str] = []
    if posts:
        for p in posts[:8]:  # show up to 8 in total, including current
            slug = p.get("slug", "")
            is_current = slug == current_slug
            cls = "sb-post current" if is_current else "sb-post"
            date = _html.escape(p.get("published", ""))
            title = _html.escape(p.get("title", ""))
            href = f"{base}/blog/{_html.escape(slug)}"
            list_items.append(
                f'<a class="{cls}" href="{href}">'
                f'<div class="sb-date">{date}</div>'
                f'<div class="sb-title">{title}</div>'
                f'</a>'
            )
    essays_block = ""
    if list_items:
        essays_block = (
            '<div class="sb-block">'
            '<h4>More posts</h4>'
            + "".join(list_items)
            + '</div>'
        )

    # TOC block — actual list items populated by the inline script once
    # the DOM is ready. Empty <ul> here.
    toc_block = (
        '<div class="sb-block">'
        '<h4>Contents</h4>'
        '<ul class="sb-toc" id="sbToc"></ul>'
        '</div>'
    )

    # Share block — LinkedIn + X prefilled
    share_text = f"Reading: {current_title}"
    li_url = f"https://www.linkedin.com/sharing/share-offsite/?url={_q(current_url)}"
    tw_url = f"https://twitter.com/intent/tweet?text={_q(share_text)}&url={_q(current_url)}"
    share_block = (
        '<div class="sb-block">'
        '<h4>Share</h4>'
        '<div class="sb-share">'
        f'<a href="{_html.escape(li_url)}" target="_blank" rel="noopener">LinkedIn</a>'
        f'<a href="{_html.escape(tw_url)}" target="_blank" rel="noopener">X / Twitter</a>'
        '</div>'
        '</div>'
    )

    return essays_block + toc_block + share_block


def _render_post_nav(current_slug: str, base: str) -> str:
    """Between-post navigation appended at the end of every blog post.

    Design:
      - <hr> separator
      - Prev / Next cards side-by-side (chronological neighbours). Missing
        sides show a muted 'You're at the edge' placeholder.
      - 'More posts' grid showing up to 3 other posts, sorted newest-
        first (excluding current + already-shown neighbours).
      - 'All posts →' link to /blog when there's more than 4 other posts.

    Single-post case: just a button to /blog so the reader has somewhere
    to go. Empty-state handling.
    """
    import html as _html

    posts = _list_visible_posts()  # newest-first
    if not posts:
        return ""

    # Locate current post within the newest-first list.
    cur_idx = next(
        (i for i, p in enumerate(posts) if p.get("slug") == current_slug),
        None,
    )

    # If the current post isn't in the list (e.g. preview of a draft),
    # show a 'More posts' grid without prev/next framing.
    if cur_idx is None:
        newer = None
        older = None
        others = posts[:3]
    else:
        # Newer post in reading order = earlier index (list is newest-first).
        newer = posts[cur_idx - 1] if cur_idx > 0 else None
        older = posts[cur_idx + 1] if cur_idx + 1 < len(posts) else None
        # Remaining posts for the 'More posts' strip.
        others = [p for i, p in enumerate(posts) if i != cur_idx
                  and (not newer or p.get("slug") != newer.get("slug"))
                  and (not older or p.get("slug") != older.get("slug"))][:3]

    def _card(post: dict, label: str | None = None) -> str:
        slug = _html.escape(post.get("slug", ""))
        title = _html.escape(post.get("title", ""))
        summary = _html.escape(post.get("summary", ""))
        pub = _html.escape(post.get("published", ""))
        label_html = (
            f'<div class="nav-label">{_html.escape(label)}</div>' if label else ""
        )
        return (
            f'<a class="nav-card" href="{base}/blog/{slug}">'
            f'{label_html}'
            f'<div class="nav-date">{pub}</div>'
            f'<div class="nav-title">{title}</div>'
            f'<div class="nav-summary">{summary}</div>'
            f'</a>'
        )

    def _edge(label: str, message: str) -> str:
        return (
            '<div class="nav-card nav-card-edge" aria-disabled="true">'
            f'<div class="nav-label">{_html.escape(label)}</div>'
            f'<div class="nav-edge-msg">{_html.escape(message)}</div>'
            '</div>'
        )

    # --- Prev / Next row ---
    pair_html = ""
    if newer or older:
        prev_html = _card(newer, "← Newer") if newer else _edge(
            "← Newer", "You're reading the freshest post."
        )
        next_html = _card(older, "Older →") if older else _edge(
            "Older →", "You've reached the first post."
        )
        pair_html = f'<div class="nav-pair">{prev_html}{next_html}</div>'

    # --- More posts grid ---
    grid_html = ""
    if others:
        others_html = "".join(_card(p) for p in others)
        all_link = (
            '<a class="nav-all-link" href="/blog">See all posts →</a>'
            if len(posts) > 4 else ""
        )
        grid_html = (
            '<div class="nav-more">'
            '<div class="nav-more-header">'
            '<h3>More posts</h3>'
            f'{all_link}'
            '</div>'
            f'<div class="nav-grid">{others_html}</div>'
            '</div>'
        )

    # --- Nothing else? Single post — show CTA back to index ---
    if not pair_html and not grid_html:
        return (
            '<hr class="post-nav-hr">'
            '<div class="post-nav-empty">'
            '<p>This is the only post so far — more on the way.</p>'
            '<a href="/blog" class="nav-all-link">Back to blog →</a>'
            '</div>'
        )

    return f'<hr class="post-nav-hr"><section class="post-nav" aria-label="More from the blog">{pair_html}{grid_html}</section>'


def _list_visible_posts() -> list[dict]:
    """All posts a visitor can see — JSON-pipeline published + legacy
    posts that aren't hidden. Sorted newest-first by published date."""
    from app.services.blog_publisher import list_published as _list_pub, is_legacy_hidden

    posts: list[dict] = []

    for p in _list_pub():
        posts.append({
            "slug": p.get("slug", ""),
            "title": p.get("title", ""),
            "published": p.get("published", ""),
            "summary": p.get("og_description") or p.get("title", ""),
        })

    if not is_legacy_hidden("01"):
        posts.append({
            "slug": "01",
            "title": POST_01_TITLE,
            "published": POST_01_PUBLISHED,
            "summary": POST_01_DESCRIPTION,
        })

    posts.sort(key=lambda p: p.get("published", ""), reverse=True)
    return posts


@router.get("/blog/assets/{filename}")
async def blog_asset(filename: str):
    """Serve an uploaded blog image from /data/blog/assets/.
    Strict whitelist via blog_publisher.get_asset_path."""
    from app.services.blog_publisher import get_asset_path
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    path = get_asset_path(filename)
    if not path:
        raise HTTPException(status_code=404, detail="Asset not found")
    # Let FileResponse set the mime based on extension
    return FileResponse(str(path), headers={"Cache-Control": "public, max-age=31536000, immutable"})


@router.get("/blog", response_class=HTMLResponse)
@router.get("/blog/", response_class=HTMLResponse)
async def blog_index() -> HTMLResponse:
    """Public blog index — lists every visible post. Empty-state card
    if nothing is live yet."""
    settings = get_settings()
    base = settings.public_base_url.rstrip("/")
    posts = _list_visible_posts()

    if posts:
        cards_html = "".join(_render_index_card(p, base) for p in posts)
        inner = f'<div class="post-grid">{cards_html}</div>'
    else:
        inner = (
            '<div class="empty-state">'
            '<div class="empty-icon">📝</div>'
            '<h2>No posts yet</h2>'
            '<p>The AutomateEdge blog is still warming up. Check back soon — '
            'the first post is on its way.</p>'
            f'<a class="back-home" href="{base}/">← Back to AutomateEdge</a>'
            '</div>'
        )

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Blog — AutomateEdge</title>
  <meta name="description" content="Essays from AutomateEdge on building a free AI learning platform — lessons, principles, and post-mortems.">
  <meta property="og:title" content="Blog — AutomateEdge">
  <meta property="og:description" content="Posts on building a free AI learning platform.">
  <meta property="og:url" content="{base}/blog">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="AutomateEdge">
  <meta property="og:image" content="{base}/og/course/generalist.png">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:image" content="{base}/og/course/generalist.png">
  <link rel="canonical" href="{base}/blog">
  <link rel="alternate" type="application/rss+xml" title="AutomateEdge Blog" href="{base}/blog/feed.xml">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:wght@400;500;700&family=IBM+Plex+Sans:wght@400;500&family=IBM+Plex+Mono:wght@400&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/nav.css">
  <style>
    :root {{ color-scheme: dark; }}
    html, body {{ margin: 0; background: #0f1419; color: #e8e4d8;
      font-family: 'IBM Plex Sans', system-ui, sans-serif; line-height: 1.6; }}
    main {{ max-width: 980px; margin: 0 auto; padding: 56px 24px 96px; }}
    .page-eyebrow {{ font-family: 'IBM Plex Mono', monospace;
      font-size: 11px; letter-spacing: 0.18em; text-transform: uppercase;
      color: #e8a849; margin-bottom: 10px; }}
    h1.page-title {{ font-family: 'Fraunces', Georgia, serif;
      font-size: clamp(32px, 5vw, 48px); line-height: 1.1;
      color: #f5f1e8; margin: 0 0 12px; font-weight: 500; }}
    .page-lede {{ font-size: 17px; color: #c0c4cc; max-width: 640px;
      margin: 0 0 44px; }}
    .post-grid {{ display: flex; flex-direction: column; gap: 18px; }}
    .post-card {{ display: block; text-decoration: none;
      background: #1a2029; border: 1px solid #2a323d; border-radius: 8px;
      padding: 24px 28px; transition: all 0.2s ease; color: inherit; }}
    .post-card:hover {{ border-color: #e8a849; transform: translateY(-2px);
      background: #1d242e; }}
    .post-meta {{ font-family: 'IBM Plex Mono', monospace;
      font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase;
      color: #94a3b8; margin-bottom: 10px; }}
    .post-card h2 {{ font-family: 'Fraunces', Georgia, serif;
      font-size: 22px; line-height: 1.25; color: #f5f1e8;
      margin: 0 0 10px; font-weight: 500; }}
    .post-summary {{ font-size: 15px; color: #c0c4cc; margin: 0 0 14px; }}
    .read-more {{ font-family: 'IBM Plex Mono', monospace;
      font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase;
      color: #e8a849; }}
    .empty-state {{ text-align: center; padding: 80px 28px;
      background: #1a2029; border: 1px dashed #2a323d; border-radius: 10px; }}
    .empty-state .empty-icon {{ font-size: 44px; margin-bottom: 16px; }}
    .empty-state h2 {{ font-family: 'Fraunces', Georgia, serif;
      color: #e8a849; font-size: 26px; font-weight: 400; margin: 0 0 10px; }}
    .empty-state p {{ color: #94a3b8; max-width: 440px; margin: 0 auto 28px; font-size: 15px; }}
    .back-home {{ display: inline-block; font-family: 'IBM Plex Mono', monospace;
      font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase;
      color: #e8a849; text-decoration: none; padding: 10px 20px;
      border: 1px solid rgba(232,168,73,0.4); border-radius: 4px;
      transition: all 0.2s; }}
    .back-home:hover {{ background: rgba(232,168,73,0.1); border-color: #e8a849; }}
    @media (max-width: 480px) {{
      .post-card {{ padding: 16px 20px; }}
    }}
  </style>
</head>
<body>
  <main>
    <div class="page-eyebrow">AutomateEdge · Blog</div>
    <h1 class="page-title">Posts on building a free AI learning platform</h1>
    <p class="page-lede">Lessons, design principles, and honest
      post-mortems from the solo-builder side of AutomateEdge.</p>
    {inner}
  </main>
  <script src="/nav.js" defer></script>
</body>
</html>""")


def _render_index_card(post: dict, base: str) -> str:
    slug = post.get("slug", "")
    title = post.get("title", "")
    published = post.get("published", "")
    summary = post.get("summary", "")
    # Escape text content — HTML chars in titles/summaries shouldn't break the page
    import html as _html
    return (
        f'<a class="post-card" href="{base}/blog/{_html.escape(slug)}">'
        f'<div class="post-meta">{_html.escape(published)}</div>'
        f'<h2>{_html.escape(title)}</h2>'
        f'<p class="post-summary">{_html.escape(summary)}</p>'
        f'<span class="read-more">Read the post →</span>'
        f'</a>'
    )


def _rfc822(published: str) -> str:
    """Convert ISO date 'YYYY-MM-DD' to an RFC 2822 string at UTC midnight.
    Falls back to today's date if the input is malformed — the feed would
    rather misdate a single item than 500 on a bad payload."""
    try:
        d = _date.fromisoformat(published)
    except Exception:
        d = _date.today()
    dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return _email_utils.format_datetime(dt)


@router.api_route("/blog/feed.xml", methods=["GET", "HEAD"])
async def blog_rss_feed() -> Response:
    """RSS 2.0 feed of every visible blog post (SEO-09). Newest-first.
    Declared as `/blog/feed.xml` before the dynamic `/blog/{slug}` route
    so FastAPI resolves it directly — the dynamic route would otherwise
    treat 'feed.xml' as a slug and 404."""
    settings = get_settings()
    base = settings.public_base_url.rstrip("/")
    posts = _list_visible_posts()

    feed_url = f"{base}/blog/feed.xml"
    channel_link = f"{base}/blog"
    channel_title = "AutomateEdge Blog"
    channel_desc = (
        "Essays from AutomateEdge on building a free AI learning platform — "
        "lessons, principles, and post-mortems."
    )
    build_date = _email_utils.format_datetime(datetime.now(timezone.utc))

    item_blocks: list[str] = []
    for p in posts:
        slug = p.get("slug", "")
        title = p.get("title", "")
        summary = p.get("summary", "")
        pub = p.get("published", "")
        url = f"{base}/blog/{slug}"
        item_blocks.append(
            "    <item>\n"
            f"      <title>{_xml_escape(title)}</title>\n"
            f"      <link>{_xml_escape(url)}</link>\n"
            f'      <guid isPermaLink="true">{_xml_escape(url)}</guid>\n'
            f"      <pubDate>{_rfc822(pub)}</pubDate>\n"
            f"      <description>{_xml_escape(summary)}</description>\n"
            "    </item>"
        )

    items_xml = "\n".join(item_blocks)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "  <channel>\n"
        f"    <title>{_xml_escape(channel_title)}</title>\n"
        f"    <link>{_xml_escape(channel_link)}</link>\n"
        f"    <description>{_xml_escape(channel_desc)}</description>\n"
        "    <language>en</language>\n"
        f'    <atom:link href="{_xml_escape(feed_url)}" rel="self" type="application/rss+xml" />\n'
        f"    <lastBuildDate>{build_date}</lastBuildDate>\n"
        f"{items_xml}\n"
        "  </channel>\n"
        "</rss>\n"
    )
    return Response(
        content=xml,
        media_type="application/rss+xml; charset=utf-8",
        headers={"Cache-Control": "public, max-age=600"},
    )


@router.get("/blog/01", response_class=HTMLResponse)
@router.get("/blog/01/", response_class=HTMLResponse)
async def post_01() -> HTMLResponse:
    # Honour the legacy-hidden flag — admin can toggle from /admin/blog
    # without touching the code below.
    from app.services.blog_publisher import is_legacy_hidden
    if is_legacy_hidden("01"):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Blog post not found")
    html = _render_post(
        slug="01",
        title=POST_01_TITLE,
        description=POST_01_DESCRIPTION,
        body_html=POST_01_BODY,
        published=POST_01_PUBLISHED,
    )
    return HTMLResponse(html)


# Dynamic route — serves any post published via the admin UI (02+).
# Reads the JSON from /data/blog/published/<slug>.json and renders
# through the same _render_post template used by the hardcoded /blog/01.
@router.get("/blog/{slug}", response_class=HTMLResponse)
@router.get("/blog/{slug}/", response_class=HTMLResponse)
async def post_dynamic(slug: str) -> HTMLResponse:
    # Hardcoded routes win — /blog/01 is handled above.
    if slug == "01":
        return await post_01()
    from app.services.blog_publisher import load_published
    payload = load_published(slug)
    if not payload:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Blog post not found")
    html = _render_post(
        slug=payload.get("slug", slug),
        title=payload.get("title", ""),
        description=payload.get("og_description", ""),
        body_html=payload.get("body_html", ""),
        published=payload.get("published", ""),
        author=payload.get("author", "Manish Kumar"),
    )
    return HTMLResponse(html)
