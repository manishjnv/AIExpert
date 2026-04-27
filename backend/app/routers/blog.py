"""
Blog router — simple static-HTML pages, one per post.

We don't ship a markdown library as a runtime dep (rule #9 in CLAUDE.md).
The canonical source of each post lives in docs/blog/*.md; the HTML here
is a hand-polished render of that source. When a second post ships, lift
this out to a generic renderer.

SEO-27 additions:
  - _load_pillar_config() — lru_cache'd pillar-topic config from pillar_topics.json
  - _post_matches_pillar() / _posts_for_pillar() — post-to-pillar matching
  - blog_index() — three-zone redesign with ?page=N + ?q= support
  - blog_topic_hub() — /blog/topic/{slug} pillar hub pages
  - blog_search_api() — /api/blog/search JSON endpoint
"""

from __future__ import annotations

import email.utils as _email_utils
import json as _json
import logging
import re as _re
from datetime import date as _date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape as _xml_escape

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from jinja2 import Environment, FileSystemLoader, select_autoescape
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings

logger = logging.getLogger("roadmap.blog")

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

BLOG_PAGE_SIZE = 20

# Slug regex for pillar topic pages — must match for the route to proceed.
_TOPIC_SLUG_RE = _re.compile(r'^[a-z][a-z0-9-]{1,40}$')

# Inline search script for /blog — module-level constant to prevent the
# f-string {{ }} doubling trap (RCA-024 prevention). Every { } here is
# literal JS — this string is concatenated into the HTML, not interpolated
# via f-string, so braces need no doubling.
_INLINE_SEARCH_JS = """
(function() {
  var form = document.querySelector('.search-form');
  var feedZone = document.getElementById('feed-zone');
  if (!form || !feedZone) return;

  form.addEventListener('submit', function(e) {
    var input = form.querySelector('input[name="q"]');
    var q = input ? input.value.trim() : '';
    if (!q) {
      window.location = '/blog';
      e.preventDefault();
      return;
    }
    // Let the form submit naturally for full SSR fallback (no JS required).
    // If JS is available, intercept to show API results without page reload.
    e.preventDefault();
    fetchResults(q);
  });

  function escapeHtml(str) {
    var d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
  }

  function fetchResults(q) {
    var url = '/api/blog/search?q=' + encodeURIComponent(q) + '&limit=50';
    fetch(url)
      .then(function(r) { return r.json(); })
      .then(function(data) {
        renderResults(data.results || [], q, data.total || 0);
      })
      .catch(function() {
        // On error, fall back to SSR search page
        window.location = '/blog?q=' + encodeURIComponent(q);
      });
  }

  function renderResults(results, q, total) {
    var html = '<p class="search-count">Found ' + total + ' post(s) for "';
    html += escapeHtml(q);
    html += '"</p>';
    if (!results.length) {
      html += '<div class="empty-state"><h2>No results</h2><p>No posts match that term. Try a broader search.</p></div>';
    } else {
      html += '<div class="post-grid">';
      results.forEach(function(p) {
        var card = document.createElement('a');
        card.className = 'post-card';
        card.href = '/blog/' + p.slug;
        var meta = document.createElement('div');
        meta.className = 'post-meta';
        meta.textContent = p.published;
        var title = document.createElement('h2');
        title.textContent = p.title;
        var summary = document.createElement('p');
        summary.className = 'post-summary';
        summary.textContent = p.summary;
        var rm = document.createElement('span');
        rm.className = 'read-more';
        rm.textContent = 'Read the post →';
        card.appendChild(meta);
        card.appendChild(title);
        card.appendChild(summary);
        card.appendChild(rm);
        html += card.outerHTML;
      });
      html += '</div>';
    }
    feedZone.outerHTML = '<div id="feed-zone">' + html + '</div>';
  }
})();
"""


# ---- Pillar config (SEO-27) ---------------------------------------------------
#
# Loaded once at startup via lru_cache. Admin changes to pillar_topics.json
# take effect on container redeploy (acceptable v1 maintenance model).

_PILLAR_CONFIG_PATH = Path(__file__).parent.parent / "data" / "blog" / "pillar_topics.json"

_EMPTY_PILLAR_CONFIG: dict = {"version": 1, "active_pills": [], "start_here": []}


@lru_cache(maxsize=1)
def _load_pillar_config() -> dict:
    """Load and minimally validate pillar_topics.json.

    On any failure (FileNotFoundError, JSONDecodeError, malformed shape)
    logs a warning and returns an empty config so /blog still renders.
    Invalid individual pill entries are dropped; valid ones are kept.
    """
    try:
        raw = _PILLAR_CONFIG_PATH.read_text(encoding="utf-8")
        data = _json.loads(raw)
    except FileNotFoundError:
        logger.warning("pillar_topics.json not found at %s — using empty config", _PILLAR_CONFIG_PATH)
        return _EMPTY_PILLAR_CONFIG.copy()
    except Exception as exc:
        logger.warning("Failed to load pillar_topics.json: %s — using empty config", exc)
        return _EMPTY_PILLAR_CONFIG.copy()

    if not isinstance(data, dict):
        logger.warning("pillar_topics.json root is not a dict — using empty config")
        return _EMPTY_PILLAR_CONFIG.copy()

    # Validate and filter active_pills — drop any entry that is missing
    # required keys (slug, label, intro, matches) or has wrong types.
    raw_pills = data.get("active_pills", [])
    if not isinstance(raw_pills, list):
        logger.warning("active_pills is not a list — using empty config")
        return _EMPTY_PILLAR_CONFIG.copy()

    valid_pills = []
    for pill in raw_pills:
        if not isinstance(pill, dict):
            continue
        if not all(k in pill for k in ("slug", "label", "intro", "matches")):
            logger.warning("Skipping malformed pillar entry (missing keys): %s", pill)
            continue
        if not isinstance(pill.get("matches"), dict):
            logger.warning("Skipping pillar entry with non-dict matches: %s", pill.get("slug"))
            continue
        valid_pills.append(pill)

    start_here = data.get("start_here", [])
    if not isinstance(start_here, list):
        start_here = []

    return {
        "version": data.get("version", 1),
        "active_pills": valid_pills,
        "start_here": [s for s in start_here if isinstance(s, str)],
    }


def _post_matches_pillar(post: dict, pill: dict) -> bool:
    """True if post.tags shares ≥1 element with pill.matches.tags_any.

    Case-insensitive comparison. Handles empty tags, missing keys, and
    type mismatches defensively — never raises.
    """
    try:
        required_tags = pill.get("matches", {}).get("tags_any") or []
        if not required_tags:
            return False
        post_tags = [t.lower() for t in (post.get("tags") or []) if isinstance(t, str)]
        required_lower = {t.lower() for t in required_tags if isinstance(t, str)}
        return bool(set(post_tags) & required_lower)
    except Exception:
        return False


def _posts_for_pillar(slug: str) -> list[dict]:
    """All visible posts matching the named pillar slug, newest-first."""
    try:
        config = _load_pillar_config()
    except Exception:
        return []
    pill = next((p for p in config.get("active_pills", []) if p["slug"] == slug), None)
    if pill is None:
        return []
    return [p for p in _list_visible_posts() if _post_matches_pillar(p, pill)]


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

  /* ----- Pillar visual elements (SEO-21 attention layer) ----- */
  /* stat-card: zero-asset highlight for one big numerical claim. */
  .stat-card {
    background: linear-gradient(135deg, rgba(232,168,73,0.08), rgba(232,168,73,0.02));
    border: 1px solid rgba(232,168,73,0.35);
    border-left: 4px solid #e8a849;
    border-radius: 6px;
    padding: 16px 20px; margin: 24px 0;
    font-size: 16px; line-height: 1.55; color: #d0cbc2;
  }
  .stat-card strong {
    display: block;
    font-family: 'Fraunces', Georgia, serif;
    font-size: 32px; font-weight: 600;
    color: #f5c06a; letter-spacing: -0.01em;
    margin-bottom: 4px;
  }
  /* stat-card-row: 2-4 cards side-by-side, auto-wrap on narrow viewports. */
  .stat-card-row {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 14px; margin: 24px 0;
  }
  .stat-card-row .stat-card { margin: 0; }

  /* trend marker: inline pill + arrow, color-coded for direction. */
  .trend {
    display: inline-block;
    font-family: 'IBM Plex Mono', ui-monospace, monospace;
    font-size: 0.85em; font-weight: 600;
    padding: 2px 7px; border-radius: 3px;
    letter-spacing: 0.02em; white-space: nowrap;
  }
  .trend-up    { background: rgba(143,208,165,0.15); color: #8fd0a5; }
  .trend-up::before    { content: "▲ "; }
  .trend-down  { background: rgba(252,165,165,0.15); color: #fca5a5; }
  .trend-down::before  { content: "▼ "; }
  .trend-flat  { background: rgba(148,163,184,0.15); color: #94a3b8; }
  .trend-flat::before  { content: "● "; }

  /* callout: short framed paragraph for "what most guides miss" asides. */
  .callout {
    background: #1a2029;
    border: 1px solid #2a323d; border-left: 3px solid #94a3b8;
    border-radius: 0 4px 4px 0;
    padding: 14px 18px; margin: 24px 0;
    color: #c0c4cc; font-size: 15px; line-height: 1.6;
  }
  .callout strong { color: #f5f1e8; }

  @media (max-width: 480px) {
    .stat-card { padding: 14px 16px; font-size: 15px; }
    .stat-card strong { font-size: 26px; }
    .stat-card-row { grid-template-columns: 1fr; gap: 10px; }
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
    faqs: list | None = None,
    defined_terms: list | None = None,
    how_to: dict | None = None,
    quotable_lines: list | None = None,
    tags: list | None = None,
) -> str:
    from app.services.share_copy import build_share_copy

    settings = get_settings()
    base = settings.public_base_url.rstrip("/")
    url = f"{base}/blog/{slug}"
    og_image = f"{base}/og/blog/{slug}.png"
    post_nav_html = _render_post_nav(slug, base)
    sidebar_html = _render_post_sidebar(slug, title, url, base)

    lede = ""
    if quotable_lines and isinstance(quotable_lines, list):
        first = next((q for q in quotable_lines if isinstance(q, str) and q.strip()), "")
        lede = first.strip()
    share_copy = build_share_copy(
        surface="blog",
        url=url,
        payload={
            "title": title,
            "description": description,
            "lede": lede,
            "tags": tags or [],
        },
    )
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
        faqs=faqs or [],
        defined_terms=defined_terms or [],
        how_to=how_to or {},
        share_copy=share_copy,
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

    return toc_block + essays_block + share_block


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
    posts that aren't hidden. Sorted newest-first by published date.

    SEO-27: includes `tags`, `lede`, `target_query`, `body_html` fields
    from the published JSON so post-to-pillar matching and search work.
    POST_01 (hardcoded) has no tags — it won't match any pillar.
    """
    from app.services.blog_publisher import list_published as _list_pub, is_legacy_hidden, load_published

    posts: list[dict] = []

    for p in _list_pub():
        slug = p.get("slug", "")
        # Load the full payload for tags + lede + body_html (needed for search)
        full = load_published(slug) if slug else None
        posts.append({
            "slug": slug,
            "title": p.get("title", ""),
            "published": p.get("published", ""),
            "summary": p.get("og_description") or p.get("title", ""),
            "tags": full.get("tags", []) if full else [],
            "lede": full.get("lede", "") if full else "",
            "target_query": full.get("target_query", "") if full else "",
            "body_html": full.get("body_html", "") if full else "",
        })

    if not is_legacy_hidden("01"):
        posts.append({
            "slug": "01",
            "title": POST_01_TITLE,
            "published": POST_01_PUBLISHED,
            "summary": POST_01_DESCRIPTION,
            # POST_01 is a hardcoded post — no tags, no pillar match
            "tags": [],
            "lede": "",
            "target_query": "",
            "body_html": POST_01_BODY,
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
async def blog_index(
    page: int = Query(default=1, ge=1),
    q: str = Query(default=""),
) -> HTMLResponse:
    """Public blog index — three-zone design (SEO-27).

    Zone 1: search input + pillar pill bar.
    Zone 2: curated 'Start here' row (page=1 only, hidden on search).
    Zone 3: paginated chronological feed (?page=N) or search results (?q=).

    Canonical: {base}/blog (page=1), {base}/blog?page=N (page>1).
    404 when page > total_pages.
    WebSite + SearchAction JSON-LD on page=1 (closes SEO-14).
    """
    import html as _html

    settings = get_settings()
    base = settings.public_base_url.rstrip("/")
    all_posts = _list_visible_posts()
    try:
        config = _load_pillar_config()
    except Exception as _exc:
        logger.warning("_load_pillar_config raised unexpectedly: %s", _exc)
        config = {"version": 1, "active_pills": [], "start_here": []}

    # --- Clamp page to valid range ---
    total_posts = len(all_posts)
    total_pages = max(1, (total_posts + BLOG_PAGE_SIZE - 1) // BLOG_PAGE_SIZE)
    page = max(1, page)

    # Normalise q
    q_clean = q.strip()
    is_search = bool(q_clean)

    # 404 on invalid page (only for non-search, paginated view)
    if not is_search and page > total_pages:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Page not found")

    # --- Canonical + rel prev/next ---
    canonical = f"{base}/blog" if page == 1 else f"{base}/blog?page={page}"
    rel_prev = ""
    rel_next = ""
    if not is_search:
        if page > 1:
            prev_url = f"{base}/blog" if page == 2 else f"{base}/blog?page={page - 1}"
            rel_prev = f'<link rel="prev" href="{_html.escape(prev_url)}">'
        if page < total_pages:
            rel_next = f'<link rel="next" href="{_html.escape(base)}/blog?page={page + 1}">'

    # --- Zone 1: Pillar pills HTML ---
    pills = config.get("active_pills", [])
    pills_html = ""
    if pills:
        pill_items = []
        for pill in pills:
            pill_slug = _html.escape(pill.get("slug", ""))
            pill_label = _html.escape(pill.get("label", ""))
            pill_items.append(
                f'<a class="pill" href="{base}/blog/topic/{pill_slug}">{pill_label}</a>'
            )
        pills_html = '<div class="pill-bar">' + "".join(pill_items) + "</div>"

    # --- Zone 1: Search box (value pre-populated for ?q= SSR fallback) ---
    q_escaped = _html.escape(q_clean)
    search_html = (
        '<form class="search-form" action="/blog" method="get" role="search">'
        '<input type="search" name="q" placeholder="Search posts…" '
        f'value="{q_escaped}" autocomplete="off" aria-label="Search posts">'
        '<button type="submit">Search</button>'
        '</form>'
    )

    # --- Zone 2: Start here (page=1, non-search only) ---
    zone2_html = ""
    if page == 1 and not is_search:
        start_slugs = config.get("start_here", [])
        published_slugs = {p["slug"] for p in all_posts}
        start_posts = [
            p for slug in start_slugs
            for p in [next((x for x in all_posts if x["slug"] == slug), None)]
            if p is not None and slug in published_slugs
        ]
        if start_posts:
            cards = "".join(_render_index_card(p, base) for p in start_posts)
            zone2_html = (
                '<section class="start-here">'
                '<h2 class="section-label">Start here</h2>'
                f'<div class="start-here-grid">{cards}</div>'
                '</section>'
            )

    # --- Zone 3: Feed or search results ---
    if is_search:
        # SSR search fallback — match against title/summary/tags (no body scan
        # server-side for SSR; JS client will use /api/blog/search for full match)
        q_lower = q_clean.lower()
        matched = [
            p for p in all_posts
            if q_lower in p.get("title", "").lower()
            or q_lower in p.get("summary", "").lower()
            or any(q_lower in t.lower() for t in p.get("tags", []))
            or q_lower in p.get("lede", "").lower()
        ][:50]
        if matched:
            cards_html = "".join(_render_index_card(p, base) for p in matched)
            zone3_html = f'<div class="post-grid" id="feed-zone">{cards_html}</div>'
        else:
            zone3_html = (
                '<div class="empty-state" id="feed-zone">'
                '<h2>No results</h2>'
                f'<p>No posts match <em>{q_escaped}</em>. Try a broader term.</p>'
                '</div>'
            )
        search_count_html = f'<p class="search-count">Found {len(matched)} post(s) for &ldquo;{q_escaped}&rdquo;</p>'
        zone3_html = search_count_html + zone3_html
    else:
        # Paginated feed
        page_posts = all_posts[(page - 1) * BLOG_PAGE_SIZE: page * BLOG_PAGE_SIZE]
        if page_posts:
            cards_html = "".join(_render_index_card(p, base) for p in page_posts)
            zone3_html = f'<div class="post-grid" id="feed-zone">{cards_html}</div>'
        else:
            zone3_html = (
                '<div class="empty-state" id="feed-zone">'
                '<h2>No posts yet</h2>'
                '<p>The AutomateEdge blog is still warming up. Check back soon.</p>'
                f'<a class="back-home" href="{base}/">Back to AutomateEdge</a>'
                '</div>'
            )
        # Pagination footer
        if total_pages > 1:
            prev_link = ""
            next_link = ""
            if page > 1:
                prev_url = "/blog" if page == 2 else f"/blog?page={page - 1}"
                prev_link = f'<a class="page-link" href="{_html.escape(prev_url)}">&laquo; Prev</a>'
            if page < total_pages:
                next_link = f'<a class="page-link" href="/blog?page={page + 1}">Next &raquo;</a>'
            zone3_html += (
                f'<div class="pagination">'
                f'{prev_link}'
                f'<span class="page-info">Page {page} of {total_pages}</span>'
                f'{next_link}'
                f'</div>'
            )

    # --- WebSite + SearchAction JSON-LD (page=1 only — SEO-14) ---
    website_jsonld = ""
    if page == 1 and not is_search:
        import json as _json_mod
        website_payload = {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "url": f"{base}/",
            "potentialAction": {
                "@type": "SearchAction",
                "target": {
                    "@type": "EntryPoint",
                    "urlTemplate": f"{base}/blog?q={{search_term_string}}",
                },
                "query-input": "required name=search_term_string",
            },
        }
        website_jsonld = (
            '<script type="application/ld+json">\n'
            + _json_mod.dumps(website_payload, ensure_ascii=False, indent=2)
            + '\n</script>'
        )

    # --- Full page HTML ---
    # CSS inline styles use {{ }} in f-strings (doubled braces = literal { })
    return HTMLResponse("<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="UTF-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Blog — AutomateEdge</title>\n"
        '  <meta name="description" content="Essays and guides on AI engineering, career paths, salaries, and learning roadmaps from AutomateEdge.">\n'
        f'  <meta property="og:title" content="Blog — AutomateEdge">\n'
        f'  <meta property="og:description" content="AI engineering guides, career paths, salary data, and learning roadmaps.">\n'
        f'  <meta property="og:url" content="{base}/blog">\n'
        '  <meta property="og:type" content="website">\n'
        '  <meta property="og:site_name" content="AutomateEdge">\n'
        f'  <meta property="og:image" content="{base}/og/course/generalist.png">\n'
        '  <meta property="og:image:width" content="1200">\n'
        '  <meta property="og:image:height" content="630">\n'
        '  <meta name="twitter:card" content="summary_large_image">\n'
        f'  <meta name="twitter:image" content="{base}/og/course/generalist.png">\n'
        f'  <link rel="canonical" href="{_html.escape(canonical)}">\n'
        + (f"  {rel_prev}\n" if rel_prev else "")
        + (f"  {rel_next}\n" if rel_next else "")
        + f'  <link rel="alternate" type="application/rss+xml" title="AutomateEdge Blog" href="{base}/blog/feed.xml">\n'
        + website_jsonld + "\n"
        + '  <link rel="preconnect" href="https://fonts.googleapis.com">\n'
        '  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
        '  <link href="https://fonts.googleapis.com/css2?family=Fraunces:wght@400;500;700&family=IBM+Plex+Sans:wght@400;500&family=IBM+Plex+Mono:wght@400&display=swap" rel="stylesheet">\n'
        '  <link rel="stylesheet" href="/nav.css">\n'
        '  <link rel="stylesheet" href="/subscribe-ribbon.css">\n'
        "  <style>\n"
        "    :root { color-scheme: dark; }\n"
        "    html, body { margin: 0; background: #0f1419; color: #e8e4d8;\n"
        "      font-family: 'IBM Plex Sans', system-ui, sans-serif; line-height: 1.6; }\n"
        "    main { max-width: 980px; margin: 0 auto; padding: 56px 24px 96px; }\n"
        "    .page-eyebrow { font-family: 'IBM Plex Mono', monospace;\n"
        "      font-size: 11px; letter-spacing: 0.18em; text-transform: uppercase;\n"
        "      color: #e8a849; margin-bottom: 10px; }\n"
        "    h1.page-title { font-family: 'Fraunces', Georgia, serif;\n"
        "      font-size: clamp(32px, 5vw, 48px); line-height: 1.1;\n"
        "      color: #f5f1e8; margin: 0 0 12px; font-weight: 500; }\n"
        "    .page-lede { font-size: 17px; color: #c0c4cc; max-width: 640px;\n"
        "      margin: 0 0 24px; }\n"
        "    /* Zone 1: search + pills */\n"
        "    .search-form { display: flex; gap: 8px; margin-bottom: 16px;\n"
        "      max-width: 600px; }\n"
        "    .search-form input { flex: 1; background: #1a2029; border: 1px solid #2a323d;\n"
        "      border-radius: 6px; padding: 10px 14px; color: #e8e4d8; font-size: 15px;\n"
        "      font-family: 'IBM Plex Sans', system-ui, sans-serif;\n"
        "      outline: none; transition: border-color 0.15s; }\n"
        "    .search-form input:focus { border-color: #e8a849; }\n"
        "    .search-form button { background: #e8a849; color: #0f1419; border: none;\n"
        "      border-radius: 6px; padding: 10px 18px; font-family: 'IBM Plex Mono', monospace;\n"
        "      font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase;\n"
        "      cursor: pointer; transition: background 0.15s; white-space: nowrap; }\n"
        "    .search-form button:hover { background: #f5c06a; }\n"
        "    .pill-bar { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 40px; }\n"
        "    .pill { display: inline-block; font-family: 'IBM Plex Mono', monospace;\n"
        "      font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase;\n"
        "      color: #94a3b8; text-decoration: none;\n"
        "      padding: 5px 12px; border: 1px solid #2a323d; border-radius: 999px;\n"
        "      transition: all 0.15s; }\n"
        "    .pill:hover { color: #e8a849; border-color: #e8a849;\n"
        "      background: rgba(232,168,73,0.06); }\n"
        "    /* Zone 2: start here */\n"
        "    .section-label { font-family: 'IBM Plex Mono', monospace;\n"
        "      font-size: 11px; letter-spacing: 0.18em; text-transform: uppercase;\n"
        "      color: #e8a849; margin: 0 0 14px; font-weight: 500; }\n"
        "    .start-here { margin-bottom: 48px; }\n"
        "    .start-here-grid { display: grid;\n"
        "      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));\n"
        "      gap: 14px; }\n"
        "    /* Zone 3 + shared cards */\n"
        "    .post-grid { display: flex; flex-direction: column; gap: 18px; }\n"
        "    .post-card { display: block; text-decoration: none;\n"
        "      background: #1a2029; border: 1px solid #2a323d; border-radius: 8px;\n"
        "      padding: 24px 28px; transition: all 0.2s ease; color: inherit; }\n"
        "    .post-card:hover { border-color: #e8a849; transform: translateY(-2px);\n"
        "      background: #1d242e; }\n"
        "    .post-meta { font-family: 'IBM Plex Mono', monospace;\n"
        "      font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase;\n"
        "      color: #94a3b8; margin-bottom: 10px; }\n"
        "    .post-card h2 { font-family: 'Fraunces', Georgia, serif;\n"
        "      font-size: 22px; line-height: 1.25; color: #f5f1e8;\n"
        "      margin: 0 0 10px; font-weight: 500; }\n"
        "    .post-summary { font-size: 15px; color: #c0c4cc; margin: 0 0 14px; }\n"
        "    .read-more { font-family: 'IBM Plex Mono', monospace;\n"
        "      font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase;\n"
        "      color: #e8a849; }\n"
        "    .search-count { font-family: 'IBM Plex Mono', monospace;\n"
        "      font-size: 12px; color: #94a3b8; margin-bottom: 20px; }\n"
        "    .empty-state { text-align: center; padding: 80px 28px;\n"
        "      background: #1a2029; border: 1px dashed #2a323d; border-radius: 10px; }\n"
        "    .empty-state h2 { font-family: 'Fraunces', Georgia, serif;\n"
        "      color: #e8a849; font-size: 26px; font-weight: 400; margin: 0 0 10px; }\n"
        "    .empty-state p { color: #94a3b8; max-width: 440px; margin: 0 auto 28px; font-size: 15px; }\n"
        "    .back-home { display: inline-block; font-family: 'IBM Plex Mono', monospace;\n"
        "      font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase;\n"
        "      color: #e8a849; text-decoration: none; padding: 10px 20px;\n"
        "      border: 1px solid rgba(232,168,73,0.4); border-radius: 4px;\n"
        "      transition: all 0.2s; }\n"
        "    .back-home:hover { background: rgba(232,168,73,0.1); border-color: #e8a849; }\n"
        "    .pagination { display: flex; align-items: center; justify-content: center;\n"
        "      gap: 16px; margin-top: 32px; font-family: 'IBM Plex Mono', monospace;\n"
        "      font-size: 12px; }\n"
        "    .page-link { color: #e8a849; text-decoration: none; letter-spacing: 0.08em;\n"
        "      text-transform: uppercase; padding: 6px 14px; border: 1px solid rgba(232,168,73,0.4);\n"
        "      border-radius: 4px; transition: all 0.15s; }\n"
        "    .page-link:hover { background: rgba(232,168,73,0.1); border-color: #e8a849; }\n"
        "    .page-info { color: #94a3b8; letter-spacing: 0.08em; }\n"
        "    @media (max-width: 480px) {\n"
        "      .post-card { padding: 16px 20px; }\n"
        "      .search-form { flex-direction: column; }\n"
        "    }\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        "  <main>\n"
        '    <div class="page-eyebrow">AutomateEdge · Blog</div>\n'
        '    <h1 class="page-title">AI engineering guides, career paths &amp; roadmaps</h1>\n'
        '    <p class="page-lede">Honest takes on learning AI, landing roles, and staying current in a field that ships a new paradigm every 18 months.</p>\n'
        '    <div id="subscribe-ribbon" data-surface="blog"></div>\n'
        f"    {search_html}\n"
        f"    {pills_html}\n"
        f"    {zone2_html}\n"
        f"    {zone3_html}\n"
        "  </main>\n"
        '  <script src="/nav.js" defer></script>\n'
        '  <script src="/subscribe-ribbon.js" defer></script>\n'
        "  <script>" + _INLINE_SEARCH_JS + "</script>\n"
        "</body>\n"
        "</html>"
    )


@router.get("/blog/topic/{slug}", response_class=HTMLResponse)
@router.get("/blog/topic/{slug}/", response_class=HTMLResponse)
async def blog_topic_hub(slug: str) -> HTMLResponse:
    """Pillar topic hub — /blog/topic/{slug} (SEO-27).

    Shows intro + ItemList of matching posts + CollectionPage + ItemList + BreadcrumbList JSON-LD.
    404 on invalid slug format or unknown pillar slug.
    """
    import html as _html

    # Defensive: validate slug pattern before any lookup
    if not _TOPIC_SLUG_RE.match(slug):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Topic not found")

    config = _load_pillar_config()
    pill = next((p for p in config.get("active_pills", []) if p["slug"] == slug), None)
    if pill is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Topic not found")

    settings = get_settings()
    base = settings.public_base_url.rstrip("/")

    matched_posts = _posts_for_pillar(slug)
    label = pill.get("label", slug.replace("-", " ").title())
    intro = pill.get("intro", "")

    # Build cards HTML
    if matched_posts:
        cards_html = "".join(_render_index_card(p, base) for p in matched_posts)
        feed_html = f'<div class="post-grid">{cards_html}</div>'
    else:
        feed_html = (
            '<div class="empty-state">'
            f'<h2>No posts yet</h2>'
            f'<p>No posts in this topic yet — check back soon.</p>'
            '</div>'
        )

    # Build ItemList JSON-LD items
    import json as _json_mod
    item_list_elements = []
    for i, p in enumerate(matched_posts, 1):
        item_list_elements.append({
            "@type": "ListItem",
            "position": i,
            "url": f"{base}/blog/{p['slug']}",
            "name": p["title"],
        })

    collection_page_jsonld = _json_mod.dumps({
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": f"{label} — AutomateEdge Blog",
        "description": intro,
        "url": f"{base}/blog/topic/{slug}",
        "hasPart": [
            {"@type": "Article", "url": f"{base}/blog/{p['slug']}", "name": p["title"]}
            for p in matched_posts
        ],
    }, ensure_ascii=False, indent=2)

    item_list_jsonld = _json_mod.dumps({
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": f"{label} posts",
        "numberOfItems": len(matched_posts),
        "itemListElement": item_list_elements,
    }, ensure_ascii=False, indent=2)

    breadcrumb_jsonld = _json_mod.dumps({
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home",
             "item": f"{base}/"},
            {"@type": "ListItem", "position": 2, "name": "Blog",
             "item": f"{base}/blog"},
            {"@type": "ListItem", "position": 3, "name": label},
        ],
    }, ensure_ascii=False, indent=2)

    canonical_url = f"{base}/blog/topic/{slug}"
    label_esc = _html.escape(label)
    intro_esc = _html.escape(intro)
    canonical_esc = _html.escape(canonical_url)

    return HTMLResponse(
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="UTF-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"  <title>{label_esc} — AutomateEdge Blog</title>\n"
        f'  <meta name="description" content="{intro_esc}">\n'
        f'  <meta property="og:title" content="{label_esc} — AutomateEdge Blog">\n'
        f'  <meta property="og:description" content="{intro_esc}">\n'
        f'  <meta property="og:url" content="{canonical_esc}">\n'
        '  <meta property="og:type" content="website">\n'
        '  <meta property="og:site_name" content="AutomateEdge">\n'
        f'  <link rel="canonical" href="{canonical_esc}">\n'
        f'  <link rel="alternate" type="application/rss+xml" title="AutomateEdge Blog" href="{base}/blog/feed.xml">\n'
        f'  <script type="application/ld+json">\n{collection_page_jsonld}\n  </script>\n'
        f'  <script type="application/ld+json">\n{item_list_jsonld}\n  </script>\n'
        f'  <script type="application/ld+json">\n{breadcrumb_jsonld}\n  </script>\n'
        '  <link rel="preconnect" href="https://fonts.googleapis.com">\n'
        '  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
        '  <link href="https://fonts.googleapis.com/css2?family=Fraunces:wght@400;500;700&family=IBM+Plex+Sans:wght@400;500&family=IBM+Plex+Mono:wght@400&display=swap" rel="stylesheet">\n'
        '  <link rel="stylesheet" href="/nav.css">\n'
        "  <style>\n"
        "    :root { color-scheme: dark; }\n"
        "    html, body { margin: 0; background: #0f1419; color: #e8e4d8;\n"
        "      font-family: 'IBM Plex Sans', system-ui, sans-serif; line-height: 1.6; }\n"
        "    main { max-width: 980px; margin: 0 auto; padding: 56px 24px 96px; }\n"
        "    .breadcrumb { font-family: 'IBM Plex Mono', monospace; font-size: 11px;\n"
        "      letter-spacing: 0.1em; text-transform: uppercase; color: #94a3b8;\n"
        "      margin-bottom: 24px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }\n"
        "    .breadcrumb a { color: #e8a849; text-decoration: none; }\n"
        "    .breadcrumb a:hover { color: #f5c06a; }\n"
        "    .breadcrumb .sep { opacity: 0.4; }\n"
        "    h1.page-title { font-family: 'Fraunces', Georgia, serif;\n"
        "      font-size: clamp(28px, 4vw, 42px); line-height: 1.1;\n"
        "      color: #f5f1e8; margin: 0 0 16px; font-weight: 500; }\n"
        "    .topic-intro { font-size: 17px; color: #c0c4cc; max-width: 640px;\n"
        "      margin: 0 0 40px; line-height: 1.7; }\n"
        "    .post-count { font-family: 'IBM Plex Mono', monospace; font-size: 11px;\n"
        "      color: #64748b; letter-spacing: 0.1em; text-transform: uppercase;\n"
        "      margin-bottom: 20px; }\n"
        "    .post-grid { display: flex; flex-direction: column; gap: 18px; }\n"
        "    .post-card { display: block; text-decoration: none;\n"
        "      background: #1a2029; border: 1px solid #2a323d; border-radius: 8px;\n"
        "      padding: 24px 28px; transition: all 0.2s ease; color: inherit; }\n"
        "    .post-card:hover { border-color: #e8a849; transform: translateY(-2px);\n"
        "      background: #1d242e; }\n"
        "    .post-meta { font-family: 'IBM Plex Mono', monospace;\n"
        "      font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase;\n"
        "      color: #94a3b8; margin-bottom: 10px; }\n"
        "    .post-card h2 { font-family: 'Fraunces', Georgia, serif;\n"
        "      font-size: 22px; line-height: 1.25; color: #f5f1e8;\n"
        "      margin: 0 0 10px; font-weight: 500; }\n"
        "    .post-summary { font-size: 15px; color: #c0c4cc; margin: 0 0 14px; }\n"
        "    .read-more { font-family: 'IBM Plex Mono', monospace;\n"
        "      font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase;\n"
        "      color: #e8a849; }\n"
        "    .empty-state { text-align: center; padding: 60px 28px;\n"
        "      background: #1a2029; border: 1px dashed #2a323d; border-radius: 10px; }\n"
        "    .empty-state h2 { font-family: 'Fraunces', Georgia, serif;\n"
        "      color: #e8a849; font-size: 24px; font-weight: 400; margin: 0 0 10px; }\n"
        "    .empty-state p { color: #94a3b8; margin: 0; font-size: 15px; }\n"
        "    .back-blog { display: inline-block; font-family: 'IBM Plex Mono', monospace;\n"
        "      font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase;\n"
        "      color: #e8a849; text-decoration: none; margin-top: 40px; }\n"
        "    .back-blog:hover { color: #f5c06a; }\n"
        "    @media (max-width: 480px) { .post-card { padding: 16px 20px; } }\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        "  <main>\n"
        '    <nav class="breadcrumb" aria-label="Breadcrumb">\n'
        f'      <a href="{base}/">Home</a><span class="sep">/</span>\n'
        f'      <a href="{base}/blog">Blog</a><span class="sep">/</span>\n'
        f"      <span>{label_esc}</span>\n"
        "    </nav>\n"
        f'    <h1 class="page-title">{label_esc}</h1>\n'
        f'    <p class="topic-intro">{intro_esc}</p>\n'
        f'    <p class="post-count">{len(matched_posts)} post{"s" if len(matched_posts) != 1 else ""}</p>\n'
        f"    {feed_html}\n"
        f'    <a class="back-blog" href="{base}/blog">← All posts</a>\n'
        "  </main>\n"
        '  <script src="/nav.js" defer></script>\n'
        "</body>\n"
        "</html>"
    )


@router.get("/api/blog/search")
@limiter.limit("10/minute")
async def blog_search_api(
    request: Request,
    q: str = Query(..., min_length=2, max_length=80),
    limit: int = Query(default=20, ge=1, le=50),
) -> JSONResponse:
    """Blog search API — /api/blog/search?q={query}&limit=N (SEO-27).

    Case-insensitive substring search across title, og_description/summary,
    lede, tags (joined), target_query, and first 500 chars of body_html.
    Results ranked: title match > tag match > body match.
    Rate-limited to 10/minute via slowapi (same pattern as auth + contact routers).
    """
    q_lower = q.strip().lower()

    all_posts = _list_visible_posts()

    def _strip_tags_local(html: str) -> str:
        return _re.sub(r'<[^>]+>', ' ', html)

    results_title: list[dict] = []
    results_tag: list[dict] = []
    results_body: list[dict] = []

    for p in all_posts:
        title = p.get("title", "")
        summary = p.get("summary", "")
        lede = p.get("lede", "")
        tags = p.get("tags", [])
        target_query = p.get("target_query", "")
        body_html = p.get("body_html", "")
        body_text = _strip_tags_local(body_html[:500] if len(body_html) > 500 else body_html)

        tags_str = " ".join(t for t in tags if isinstance(t, str))

        matched_in: list[str] = []
        in_title = q_lower in title.lower()
        in_summary = q_lower in summary.lower()
        in_lede = q_lower in lede.lower()
        in_tags = q_lower in tags_str.lower()
        in_target = q_lower in target_query.lower()
        in_body = q_lower in body_text.lower()

        if in_title:
            matched_in.append("title")
        if in_summary or in_lede:
            matched_in.append("summary")
        if in_tags or in_target:
            matched_in.append("tags")
        if in_body and not matched_in:
            matched_in.append("body")
        elif in_body:
            matched_in.append("body")

        if not matched_in:
            continue

        record = {
            "slug": p.get("slug", ""),
            "title": title,
            "summary": summary,
            "published": p.get("published", ""),
            "matched_in": matched_in,
        }

        if in_title:
            results_title.append(record)
        elif in_tags or in_target:
            results_tag.append(record)
        else:
            results_body.append(record)

    combined = (results_title + results_tag + results_body)[:limit]

    return JSONResponse({
        "query": q.strip(),
        "total": len(combined),
        "results": combined,
    })


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
        faqs=payload.get("faqs") or None,
        defined_terms=payload.get("defined_terms") or None,
        how_to=payload.get("how_to") or None,
        quotable_lines=payload.get("quotable_lines") or None,
        tags=payload.get("tags") or None,
    )
    return HTMLResponse(html)
