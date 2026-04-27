"""share_copy.py — Deterministic share-copy generator.

Pure templates, no AI calls, no I/O, stdlib only.
"""

from __future__ import annotations

import html
import json
import re
from typing import Literal

# ---------------------------------------------------------------------------
# Tag / skill lookup tables
# ---------------------------------------------------------------------------

_TAG_DISPLAY: dict[str, str] = {
    "build-in-public": "#BuildInPublic",
    "ai-engineer": "#AIEngineering",
    "ml-engineer": "#MLEngineering",
    "career-guide": "#AICareer",
    "foundation-model": "#FoundationModels",
    "rag": "#RAG",
    "prompt-engineering": "#PromptEngineering",
    "agents": "#AIAgents",
    "mlops": "#MLOps",
    "evaluation": "#LLMEvaluation",
    "transformers": "#Transformers",
    "deep-learning": "#DeepLearning",
    "computer-vision": "#ComputerVision",
    "nlp": "#NLP",
    "reinforcement-learning": "#RL",
    "fine-tuning": "#FineTuning",
    "vector-database": "#VectorDB",
    "embeddings": "#Embeddings",
    "open-source": "#OpenSource",
    "python": "#Python",
}

_BRAND_TAG = "#AutomateEdge"
_AIJOBS_TAG = "#AIJobs"

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _skill_to_tag(skill: str) -> str | None:
    """Convert a skill name to a hashtag.

    Strips non-alphanumeric characters, prefixes '#'.
    Returns None if the result is empty or longer than 25 chars.
    """
    cleaned = re.sub(r"[^A-Za-z0-9]", "", skill)
    if not cleaned:
        return None
    tag = f"#{cleaned}"
    if len(tag) > 25:
        return None
    return tag


def _map_tags(slugs: list[str]) -> list[str]:
    """Map a list of tag slugs to display hashtags, dropping unmapped."""
    result = []
    for slug in slugs:
        mapped = _TAG_DISPLAY.get(slug)
        if mapped:
            result.append(mapped)
    return result


def _map_skills(skills: list[str]) -> list[str]:
    """Convert skill names to hashtags using _skill_to_tag, dropping failures."""
    result = []
    for skill in skills:
        tag = _skill_to_tag(skill)
        if tag:
            result.append(tag)
    return result


def _truncate_to_budget(prose: str, budget: int) -> str:
    """Truncate prose to fit within budget characters (character count).

    Prefers to break at a word boundary; falls back to hard cut.
    """
    if len(prose) <= budget:
        return prose
    # Try word boundary
    truncated = prose[:budget].rsplit(" ", 1)[0]
    if not truncated:
        truncated = prose[:budget]
    return truncated + "…"


def _first_sentence(text: str) -> str:
    """Return the first sentence of text (up to the first '.', '!', or '?')."""
    if not text:
        return ""
    m = re.search(r"[.!?]", text)
    if m:
        return text[: m.end()].strip()
    return text.strip()


# ---------------------------------------------------------------------------
# Template families (private)
# ---------------------------------------------------------------------------

_TWITTER_MAX = 280
_LINKEDIN_MAX = 3000
_URL_RESERVE_BUFFER = 5  # extra safety beyond URL length


def _tpl_blog(
    payload: dict,
    url: str,
    twitter_tags: list[str],
    linkedin_tags: list[str],
) -> dict[str, str]:
    """Build blog share copy."""
    title: str = payload.get("title") or ""
    description: str = payload.get("description") or ""
    lede: str = payload.get("lede") or ""
    tags_raw: list[str] = payload.get("tags") or []

    # ---- Twitter ----
    # Structure:
    #   {lede or title}
    #
    #   {first sentence of description, truncated if needed}
    #
    #   {url}
    #
    #   {tags joined by space, ≤2}
    t_header = lede if lede else title
    t_first_sent = _first_sentence(description)
    t_tag_str = " ".join(twitter_tags[:2])

    # Fixed parts that always appear
    # "\n\n{first_sent}\n\n{url}\n\n{tag_str}"  — build suffix first to know budget
    suffix_parts = []
    if t_first_sent:
        suffix_parts.append(f"\n\n{t_first_sent}")
    suffix_parts.append(f"\n\n{url}")
    if t_tag_str:
        suffix_parts.append(f"\n\n{t_tag_str}")
    suffix = "".join(suffix_parts)

    header_budget = _TWITTER_MAX - len(suffix) - _URL_RESERVE_BUFFER
    if header_budget < 0:
        header_budget = 0
    t_header_clipped = _truncate_to_budget(t_header, header_budget)
    twitter = t_header_clipped + suffix

    # Final safety truncation: never exceed 280; trim prose not url/tags
    if len(twitter) > _TWITTER_MAX:
        # Recompute with no first sentence
        suffix2_parts = [f"\n\n{url}"]
        if t_tag_str:
            suffix2_parts.append(f"\n\n{t_tag_str}")
        suffix2 = "".join(suffix2_parts)
        header_budget2 = _TWITTER_MAX - len(suffix2) - _URL_RESERVE_BUFFER
        if header_budget2 < 0:
            header_budget2 = 0
        twitter = _truncate_to_budget(t_header, header_budget2) + suffix2

    # ---- LinkedIn ----
    # Structure:
    #   {lede if present, else title}
    #
    #   {description}
    #
    #   Read more: {url}
    #
    #   {tags joined by space, 3-5 incl #AutomateEdge last}
    li_header = lede if lede else title
    li_tag_str = " ".join(linkedin_tags[:5]) if linkedin_tags else ""

    li_parts = [li_header]
    if description:
        li_parts.append(description)
    li_parts.append(f"Read more: {url}")
    if li_tag_str:
        li_parts.append(li_tag_str)
    linkedin = "\n\n".join(li_parts)

    return {"twitter": twitter, "linkedin": linkedin}


def _tpl_job(
    payload: dict,
    url: str,
    twitter_tags: list[str],
    linkedin_tags: list[str],
) -> dict[str, str]:
    """Build job share copy."""
    title: str = payload.get("title") or ""
    company: str = payload.get("company") or title or "A company"
    designation: str = payload.get("designation") or title or "an AI role"
    tldr: str = payload.get("tldr") or ""
    must_have_skills: list[str] = payload.get("must_have_skills") or []
    remote_policy: str = payload.get("remote_policy") or ""
    salary_label: str = payload.get("salary_label") or ""

    # ---- Twitter ----
    # Structure:
    #   {company} is hiring: {designation}.
    #
    #   {top 2 skills, comma-separated}{ · salary_label if present}
    #
    #   {url}
    #
    #   {1-2 tags: top skill (mapped) + #AIJobs}
    top2_skills = must_have_skills[:2]
    skills_str = ", ".join(top2_skills) if top2_skills else ""
    salary_part = f" · {salary_label}" if salary_label else ""
    detail_line = f"{skills_str}{salary_part}" if skills_str or salary_part else ""

    t_tag_str = " ".join(twitter_tags[:2])

    suffix_parts = []
    if detail_line:
        suffix_parts.append(f"\n\n{detail_line}")
    suffix_parts.append(f"\n\n{url}")
    if t_tag_str:
        suffix_parts.append(f"\n\n{t_tag_str}")
    suffix = "".join(suffix_parts)

    header = f"{company} is hiring: {designation}."
    header_budget = _TWITTER_MAX - len(suffix) - _URL_RESERVE_BUFFER
    if header_budget < 0:
        header_budget = 0
    t_header_clipped = _truncate_to_budget(header, header_budget)
    twitter = t_header_clipped + suffix

    # Safety: if still over, drop detail line
    if len(twitter) > _TWITTER_MAX:
        suffix2 = f"\n\n{url}"
        if t_tag_str:
            suffix2 += f"\n\n{t_tag_str}"
        header_budget2 = _TWITTER_MAX - len(suffix2) - _URL_RESERVE_BUFFER
        twitter = _truncate_to_budget(header, max(0, header_budget2)) + suffix2

    # ---- LinkedIn ----
    # Structure:
    #   {company} is hiring a {designation}{ (remote_policy) if Remote/Hybrid}.
    #
    #   {tldr}
    #
    #   See the role: {url}
    #
    #   {3-5 tags: top skills + #AIJobs + #AutomateEdge}
    remote_suffix = ""
    if remote_policy in ("Remote", "Hybrid"):
        remote_suffix = f" ({remote_policy})"
    li_header = f"{company} is hiring a {designation}{remote_suffix}."
    li_tag_str = " ".join(linkedin_tags[:5]) if linkedin_tags else ""

    li_parts = [li_header]
    if tldr:
        li_parts.append(tldr)
    li_parts.append(f"See the role: {url}")
    if li_tag_str:
        li_parts.append(li_tag_str)
    linkedin = "\n\n".join(li_parts)

    return {"twitter": twitter, "linkedin": linkedin}


def _tpl_course(
    payload: dict,
    url: str,
    twitter_tags: list[str],
    linkedin_tags: list[str],
) -> dict[str, str]:
    """Build course milestone share copy."""
    milestone_title: str = payload.get("milestone_title") or "a milestone"
    milestone_subtitle: str = payload.get("milestone_subtitle") or ""
    first_name: str = payload.get("first_name") or "A learner"

    # ---- Twitter ----
    # Structure:
    #   Just shipped: {milestone_title}.
    #
    #   {milestone_subtitle}
    #
    #   Building in public:
    #   {url}
    #
    #   #LearnInPublic
    suffix_parts = []
    if milestone_subtitle:
        suffix_parts.append(f"\n\n{milestone_subtitle}")
    suffix_parts.append(f"\n\nBuilding in public:\n{url}")
    suffix_parts.append("\n\n#LearnInPublic")
    suffix = "".join(suffix_parts)

    header = f"Just shipped: {milestone_title}."
    header_budget = _TWITTER_MAX - len(suffix) - _URL_RESERVE_BUFFER
    if header_budget < 0:
        header_budget = 0
    t_header_clipped = _truncate_to_budget(header, header_budget)
    twitter = t_header_clipped + suffix

    if len(twitter) > _TWITTER_MAX:
        # drop subtitle
        suffix2 = f"\n\nBuilding in public:\n{url}\n\n#LearnInPublic"
        header_budget2 = _TWITTER_MAX - len(suffix2) - _URL_RESERVE_BUFFER
        twitter = _truncate_to_budget(header, max(0, header_budget2)) + suffix2

    # ---- LinkedIn ----
    # Structure:
    #   Just shipped: {milestone_title}.
    #
    #   {milestone_subtitle}
    #
    #   {first_name}'s personal AI roadmap — building it in public:
    #   {url}
    #
    #   #LearnInPublic #AIRoadmap #AutomateEdge
    li_parts = [f"Just shipped: {milestone_title}."]
    if milestone_subtitle:
        li_parts.append(milestone_subtitle)
    li_parts.append(f"{first_name}'s personal AI roadmap — building it in public:\n{url}")
    li_parts.append("#LearnInPublic #AIRoadmap #AutomateEdge")
    linkedin = "\n\n".join(li_parts)

    return {"twitter": twitter, "linkedin": linkedin}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_share_copy(
    *,
    surface: Literal["blog", "job", "course_milestone"],
    url: str,
    payload: dict,
) -> dict[str, str]:
    """Return {'twitter': str, 'linkedin': str}.

    Twitter ≤ 280 chars TOTAL (URL counted at literal length).
    LinkedIn ≤ 3000 chars; aim for ≤ 1200 to stay above 'see more' fold.
    Both drafts include the URL.
    Brand tag '#AutomateEdge' is appended LAST on every LinkedIn draft, NEVER on Twitter.
    Twitter ≤ 2 hashtags total. LinkedIn 3-5 hashtags including brand.
    """
    tags_raw: list[str] = payload.get("tags") or []
    skills_raw: list[str] = payload.get("must_have_skills") or []
    topics_raw: list[str] = payload.get("topics") or []

    if surface == "blog":
        mapped = _map_tags(tags_raw)
        # Twitter: up to 2, no brand
        twitter_tags = mapped[:2]
        # LinkedIn: up to 4 mapped + brand last (to keep total ≤5)
        linkedin_tags = mapped[:4] + [_BRAND_TAG]
        result = _tpl_blog(payload, url, twitter_tags, linkedin_tags)

    elif surface == "job":
        # Map skills + topics to tags; build twitter and linkedin pools
        skill_tags = _map_skills(skills_raw)
        topic_tags = _map_tags(topics_raw)
        combined = skill_tags + topic_tags

        # Twitter: top skill tag + #AIJobs, ≤2 total
        twitter_tags = (combined[:1] + [_AIJOBS_TAG])[:2]

        # LinkedIn: top skills + #AIJobs + #AutomateEdge, 3-5 total
        li_skill_pool = combined[:3]  # up to 3 skill/topic tags
        linkedin_tags = (li_skill_pool + [_AIJOBS_TAG, _BRAND_TAG])[:5]

        result = _tpl_job(payload, url, twitter_tags, linkedin_tags)

    elif surface == "course_milestone":
        # Tags are fixed in the template strings; pass empty lists
        result = _tpl_course(payload, url, [], [])

    else:
        raise ValueError(f"Unknown surface: {surface!r}")

    return result


def render_share_modal(
    *,
    share_copy: dict[str, str],
    og_image_url: str,
    title: str,
    description: str,
    surface: str,
    source_id: str,
    url: str,
    modal_id: str = "shareOverlay",
) -> str:
    """Return the modal <div>...</div> HTML + JSON island + JS as a string.

    Embeds share_copy as a JSON island.
    surface / source_id / url emitted as data-* attrs on the overlay div so
    the inline JS can read them for the /api/share/log analytics POST.
    All interpolated text is html.escape()'d (RCA-008).
    JSON island escapes '</' as '<\\/' to prevent </script> close-tag injection.
    """
    esc_og = html.escape(og_image_url, quote=True)
    esc_title = html.escape(title, quote=True)
    esc_desc = html.escape(description, quote=True)
    esc_modal_id = html.escape(modal_id, quote=True)
    esc_surface = html.escape(surface, quote=True)
    esc_source_id = html.escape(source_id, quote=True)
    esc_url = html.escape(url, quote=True)

    # JSON island — prevent </script> injection
    json_str = json.dumps(share_copy, ensure_ascii=False).replace("</", "<\\/")

    modal_html = (
        f'<div class="share-overlay" id="{esc_modal_id}" role="dialog"'
        f' aria-modal="true" aria-labelledby="shareModalTitle" data-open="0"'
        f' data-surface="{esc_surface}" data-source-id="{esc_source_id}"'
        f' data-source-url="{esc_url}">\n'
        f'  <div class="share-modal">\n'
        f'    <div class="share-modal-head">\n'
        f'      <h3 id="shareModalTitle">Share this post</h3>\n'
        f'      <button type="button" class="share-close" data-share-close'
        f' aria-label="Close">\xd7</button>\n'
        f'    </div>\n'
        f'    <div class="share-tabs" role="tablist">\n'
        f'      <button type="button" class="share-tab" role="tab"'
        f' data-share-tab="linkedin" aria-selected="true">LinkedIn</button>\n'
        f'      <button type="button" class="share-tab" role="tab"'
        f' data-share-tab="twitter" aria-selected="false">X (Twitter)</button>\n'
        f'    </div>\n'
        f'\n'
        f'    <div class="share-panel" data-share-panel="linkedin"'
        f' data-active="1" role="tabpanel">\n'
        f'      <div class="share-preview">\n'
        f'        <img src="{esc_og}" alt="" loading="lazy">\n'
        f'        <div class="share-preview-meta">\n'
        f'          <p class="ttl">{esc_title}</p>\n'
        f'          <p class="desc">{esc_desc}</p>\n'
        f'        </div>\n'
        f'      </div>\n'
        f'      <textarea class="share-textarea" id="shareTextLinkedin"'
        f' rows="7" maxlength="3000"></textarea>\n'
        f'      <div class="share-meta-row">\n'
        f'        <span>LinkedIn pulls the link card from this page</span>\n'
        f'        <span class="share-count" id="shareCountLinkedin">0</span>\n'
        f'      </div>\n'
        f'      <p class="share-note">\n'
        f"        LinkedIn&#x27;s share dialog doesn&#x27;t accept pre-filled text."
        f" Copy the draft below, then\n"
        f"        click <strong>Open LinkedIn</strong> and paste it into the compose box.\n"
        f'      </p>\n'
        f'      <div class="share-actions">\n'
        f'        <button type="button" class="share-action secondary"'
        f' data-share-copy="linkedin">Copy text</button>\n'
        f'        <button type="button" class="share-action"'
        f' data-share-go="linkedin">Open LinkedIn &#x2197;</button>\n'
        f'      </div>\n'
        f'    </div>\n'
        f'\n'
        f'    <div class="share-panel" data-share-panel="twitter"'
        f' data-active="0" role="tabpanel">\n'
        f'      <div class="share-preview">\n'
        f'        <img src="{esc_og}" alt="" loading="lazy">\n'
        f'        <div class="share-preview-meta">\n'
        f'          <p class="ttl">{esc_title}</p>\n'
        f'          <p class="desc">{esc_desc}</p>\n'
        f'        </div>\n'
        f'      </div>\n'
        f'      <textarea class="share-textarea" id="shareTextTwitter"'
        f' rows="5" maxlength="280"></textarea>\n'
        f'      <div class="share-meta-row">\n'
        f'        <span>X limits posts to 280 characters</span>\n'
        f'        <span class="share-count" id="shareCountTwitter">0</span>\n'
        f'      </div>\n'
        f'      <div class="share-actions">\n'
        f'        <button type="button" class="share-action secondary"'
        f' data-share-copy="twitter">Copy text</button>\n'
        f'        <button type="button" class="share-action"'
        f' data-share-go="twitter">Post on X &#x2197;</button>\n'
        f'      </div>\n'
        f'    </div>\n'
        f'  </div>\n'
        f'</div>\n'
        f'<script id="shareCopyData" type="application/json">{json_str}</script>\n'
        f'<script>{_SHARE_MODAL_JS}</script>'
    )
    return modal_html


# ---------------------------------------------------------------------------
# Inline JS for the share modal
# ---------------------------------------------------------------------------
#
# Triple-quoted RAW string (r"""...""") — not an f-string. Python does NOT
# interpret braces or backslashes here, so RCA-024 / RCA-027 brace-escape
# traps do not apply. The JS body must NEVER contain a literal '</script>'
# substring (would close the wrapping <script> tag in the rendered HTML);
# verified clean as of authoring.
#
# Behaviour:
#   - reads share_copy from <script id="shareCopyData">
#   - reads surface / source_id / source_url from data-* attrs on overlay
#   - POSTs {surface, source_id, channel, action} to /api/share/log on
#     modal-open ('opened') and on share-button click ('shared').
#     Uses navigator.sendBeacon when available; fetch keepalive fallback.
#     Analytics never blocks UX — failures are silently swallowed.
#
_SHARE_MODAL_JS = r"""
(function() {
  var dataNode = document.getElementById('shareCopyData');
  if (!dataNode) return;
  var copy;
  try { copy = JSON.parse(dataNode.textContent); }
  catch (e) { return; }

  var overlay = document.getElementById('shareOverlay');
  if (!overlay) return;
  var taLinkedin = document.getElementById('shareTextLinkedin');
  var taTwitter = document.getElementById('shareTextTwitter');
  var countLinkedin = document.getElementById('shareCountLinkedin');
  var countTwitter = document.getElementById('shareCountTwitter');
  if (!taLinkedin || !taTwitter) return;

  var surface = overlay.dataset.surface || '';
  var sourceId = overlay.dataset.sourceId || '';
  var sourceUrl = overlay.dataset.sourceUrl || '';
  var activeTab = 'linkedin';

  function logShareEvent(action, channel) {
    if (!surface || !sourceId) return;
    var body = JSON.stringify({
      surface: surface,
      source_id: sourceId,
      channel: channel,
      action: action
    });
    try {
      if (navigator.sendBeacon) {
        var blob = new Blob([body], { type: 'application/json' });
        navigator.sendBeacon('/api/share/log', blob);
      } else {
        fetch('/api/share/log', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: body,
          credentials: 'same-origin',
          keepalive: true
        }).catch(function() {});
      }
    } catch (e) { /* analytics never blocks UX */ }
  }

  function seed() {
    if (!taLinkedin.value) taLinkedin.value = copy.linkedin || '';
    if (!taTwitter.value) taTwitter.value = copy.twitter || '';
    updateCount('linkedin');
    updateCount('twitter');
  }

  function updateCount(which) {
    if (which === 'linkedin') {
      countLinkedin.textContent = taLinkedin.value.length + ' / 3000';
      countLinkedin.classList.toggle('over', taLinkedin.value.length > 3000);
    } else {
      countTwitter.textContent = taTwitter.value.length + ' / 280';
      countTwitter.classList.toggle('over', taTwitter.value.length > 280);
    }
  }

  taLinkedin.addEventListener('input', function() { updateCount('linkedin'); });
  taTwitter.addEventListener('input', function() { updateCount('twitter'); });

  function openModal() {
    seed();
    overlay.dataset.open = '1';
    document.body.style.overflow = 'hidden';
    logShareEvent('opened', activeTab);
  }
  function closeModal() {
    overlay.dataset.open = '0';
    document.body.style.overflow = '';
  }

  document.querySelectorAll('[data-share-open]').forEach(function(btn) {
    btn.addEventListener('click', openModal);
  });
  document.querySelectorAll('[data-share-close]').forEach(function(btn) {
    btn.addEventListener('click', closeModal);
  });
  overlay.addEventListener('click', function(e) {
    if (e.target === overlay) closeModal();
  });
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && overlay.dataset.open === '1') closeModal();
  });

  document.querySelectorAll('[data-share-tab]').forEach(function(tab) {
    tab.addEventListener('click', function() {
      var which = tab.dataset.shareTab;
      activeTab = which;
      document.querySelectorAll('[data-share-tab]').forEach(function(t) {
        t.setAttribute('aria-selected', t === tab ? 'true' : 'false');
      });
      document.querySelectorAll('[data-share-panel]').forEach(function(p) {
        p.dataset.active = (p.dataset.sharePanel === which) ? '1' : '0';
      });
    });
  });

  document.querySelectorAll('[data-share-copy]').forEach(function(btn) {
    btn.addEventListener('click', async function() {
      var which = btn.dataset.shareCopy;
      var text = (which === 'linkedin') ? taLinkedin.value : taTwitter.value;
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(text);
        } else {
          var ta = (which === 'linkedin') ? taLinkedin : taTwitter;
          ta.select();
          document.execCommand('copy');
        }
        var orig = btn.textContent;
        btn.textContent = 'Copied ✓';
        btn.classList.add('copied');
        setTimeout(function() {
          btn.textContent = orig;
          btn.classList.remove('copied');
        }, 1800);
      } catch (e) { /* clipboard failed silently */ }
    });
  });

  document.querySelectorAll('[data-share-go]').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var which = btn.dataset.shareGo;
      var shareUrl;
      if (which === 'twitter') {
        shareUrl = 'https://twitter.com/intent/tweet?text='
          + encodeURIComponent(taTwitter.value);
      } else {
        shareUrl = 'https://www.linkedin.com/sharing/share-offsite/?url='
          + encodeURIComponent(sourceUrl);
      }
      logShareEvent('shared', which);
      window.open(shareUrl, '_blank', 'noopener,width=640,height=720');
    });
  });
})();
"""
