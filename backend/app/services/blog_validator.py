"""Pillar blog validator (SEO-21) + VideoObject emitter (SEO-22).

Layered on top of blog_publisher.validate_payload(). The base validator
enforces build-in-public voice + schema shape on every post. This module
adds the stricter SEO-21 quality bar that pillar SEO posts must clear:

  1.  Word count tier (3000 pillar / 4500 flagship)
  2.  First paragraph 40-60 word definitional snippet
  3.  H2 section count 8-12
  4.  >= 40 internal links
  5.  >= 5 external citations to trusted_sources.json (SEO-25)
  6.  Schemas include Article + FAQPage + one of
      {HowTo, DefinedTerm, VideoObject, ItemList}
  7.  8-15 FAQ Q&A pairs
  8.  >= 1 comparison <table> when post is comparative
  9.  dateModified freshness (warn-only; quarterly cron bumps it)
  10. OG image declared (SEO-11 route)

Activation: validate_pillar() only runs when payload["pillar_tier"] is
set. Standard build-in-public posts pass through blog_publisher
unchanged.

Also exports build_video_object() — the SEO-22 VideoObject JSON-LD
emitter used by the blog post template when payload["videos"] is set.
"""

from __future__ import annotations

import json
import re
from html import unescape
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlparse

# Repo canonical host — anchors "internal link" detection. Kept in sync
# with the SSR canonical base; an absolute link whose host matches is
# treated as internal, same as a relative '/...' link.
SITE_HOST = "automateedge.cloud"

_TRUSTED_SOURCES_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "trusted_sources.json"

_WORD_RE = re.compile(r"\b\w+\b")
_TAG_RE = re.compile(r"<[^>]+>")
_HREF_RE = re.compile(r'<a[^>]+href=["\']([^"\']+)["\']', re.IGNORECASE)
_H2_RE = re.compile(r"<h2[^>]*>(.*?)</h2>", re.IGNORECASE | re.DOTALL)
_FIRST_P_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
_TABLE_RE = re.compile(r"<table[\s>]", re.IGNORECASE)


# ---------------- trusted-sources allowlist (SEO-25) ----------------


def load_trusted_sources(path: Optional[Path] = None) -> dict:
    """Load the E-E-A-T allowlist. Returns {"domains": set[str],
    "by_category": {category: set[str]}}. Missing file → empty sets
    (validator will flag the missing allowlist as an error when a
    pillar post is being checked)."""
    path = path or _TRUSTED_SOURCES_PATH
    if not path.exists():
        return {"domains": set(), "by_category": {}, "loaded_from": str(path), "missing": True}
    raw = json.loads(path.read_text(encoding="utf-8"))
    domains: set[str] = set()
    by_cat: dict[str, set[str]] = {}
    for entry in raw.get("allowlist", []):
        d = str(entry.get("domain", "")).strip().lower()
        if not d:
            continue
        domains.add(d)
        cat = str(entry.get("category", "uncategorized"))
        by_cat.setdefault(cat, set()).add(d)
    return {
        "domains": domains,
        "by_category": by_cat,
        "loaded_from": str(path),
        "version": raw.get("version"),
        "updated": raw.get("updated"),
        "missing": False,
    }


def is_trusted_domain(url: str, domains: Iterable[str]) -> bool:
    """True iff the URL's hostname is in `domains` (exact) or is a
    subdomain of one (suffix match after a '.' boundary). Scheme-less
    or malformed URLs → False."""
    try:
        host = (urlparse(url).hostname or "").lower().strip()
    except Exception:
        return False
    if not host:
        return False
    for d in domains:
        if host == d or host.endswith("." + d):
            return True
    return False


# ---------------- pillar validator (SEO-21) ----------------


_PILLAR_TIERS = {"pillar": 3000, "flagship": 4500}

# Schema.org types allowed to satisfy the "at least one of" requirement
# alongside mandatory Article + FAQPage.
_SATISFY_SCHEMAS = {"HowTo", "DefinedTerm", "VideoObject", "ItemList"}


def _strip_tags(html: str) -> str:
    return unescape(re.sub(r"\s+", " ", _TAG_RE.sub(" ", html))).strip()


def _count_words(text: str) -> int:
    return len(_WORD_RE.findall(text))


def _first_paragraph(body_html: str) -> str:
    """Return the definitional paragraph — the 40-60 word featured-snippet
    target. Modern pillar posts (v2 prompt) inject a 25-40 word HOOK between
    the lede and the definitional, so we scan the first 3 non-lede paragraphs
    and prefer whichever lands in the 40-60 word target range. Falls back to
    the first non-lede paragraph if none qualify, so the validator's
    word-count error message still fires for actually-broken posts."""
    matches = _FIRST_P_RE.findall(body_html)
    if not matches:
        return ""
    has_lede = re.search(r"<p[^>]*class=[\"'][^\"']*\blede\b[^\"']*[\"'][^>]*>",
                         body_html, re.IGNORECASE)
    start = 1 if has_lede else 0
    candidates = matches[start:start + 3]
    for cand in candidates:
        wc = _count_words(_strip_tags(cand))
        if 40 <= wc <= 60:
            return _strip_tags(cand)
    if candidates:
        return _strip_tags(candidates[0])
    return ""


def validate_pillar(payload: dict, trusted: Optional[dict] = None) -> dict:
    """Pillar-tier quality bar. Returns the same shape as
    blog_publisher.validate_payload():

      {ok: bool, errors: [str, ...], warnings: [str, ...], stats: {...}}

    Only runs when payload["pillar_tier"] in {"pillar", "flagship"}.
    If the field is missing or falsy, returns ok=True with an empty
    stats dict — caller's base validator remains the sole gate.
    """
    tier = str(payload.get("pillar_tier") or "").strip().lower()
    if not tier:
        return {"ok": True, "errors": [], "warnings": [],
                "stats": {"pillar_tier": None}}

    errors: list[str] = []
    warnings: list[str] = []
    trusted = trusted if trusted is not None else load_trusted_sources()

    if trusted.get("missing"):
        errors.append(
            f"trusted_sources.json not found at {trusted.get('loaded_from')} — "
            "pillar posts cannot be validated without the SEO-25 allowlist."
        )

    if tier not in _PILLAR_TIERS:
        errors.append(
            f"pillar_tier '{tier}' not recognised — use 'pillar' (>=3000 words) "
            "or 'flagship' (>=4500 words)."
        )

    body_html = str(payload.get("body_html", ""))
    slug = str(payload.get("slug", "")).strip()
    stripped = _strip_tags(body_html)
    word_count = _count_words(stripped)

    # --- Check 1: word count tier ---
    min_words = _PILLAR_TIERS.get(tier, 3000)
    if word_count < min_words:
        errors.append(
            f"pillar tier '{tier}' requires >= {min_words} words; post has {word_count}."
        )

    # --- Check 2: first paragraph 40-60 word definitional snippet ---
    first_para = _first_paragraph(body_html)
    first_para_words = _count_words(first_para)
    if first_para_words < 40 or first_para_words > 60:
        errors.append(
            f"first non-lede paragraph is {first_para_words} words "
            "(SEO-21 target: 40-60 words for a featured-snippet definitional lead)."
        )

    # --- Check 3: H2 count 8-12 ---
    h2_count = len(_H2_RE.findall(body_html))
    if h2_count < 8 or h2_count > 12:
        errors.append(
            f"pillar post has {h2_count} <h2> sections; target is 8-12 for TOC depth + Google section parsing."
        )

    # --- Check 4/5: internal + external links ---
    internal_count = 0
    external_count = 0
    trusted_count = 0
    external_untrusted: list[str] = []
    domains = trusted.get("domains", set())
    for href in _HREF_RE.findall(body_html):
        href_l = href.strip()
        if not href_l:
            continue
        if href_l.startswith("#") or href_l.startswith("mailto:") or href_l.startswith("tel:"):
            continue
        parsed_host = (urlparse(href_l).hostname or "").lower()
        if href_l.startswith("/") and not href_l.startswith("//"):
            internal_count += 1
        elif parsed_host == SITE_HOST or (parsed_host and parsed_host.endswith("." + SITE_HOST)):
            internal_count += 1
        elif parsed_host:
            external_count += 1
            if is_trusted_domain(href_l, domains):
                trusted_count += 1
            else:
                external_untrusted.append(href_l)

    if internal_count < 40:
        errors.append(
            f"pillar post has {internal_count} internal links; SEO-21 requires >= 40 "
            "(interlink roadmap weeks, jobs, tracks, other blog posts)."
        )
    if trusted_count < 5:
        errors.append(
            f"pillar post has {trusted_count} citations to trusted sources; "
            "SEO-21 + SEO-25 require >= 5 from the E-E-A-T allowlist "
            "(arXiv, Papers with Code, OpenAI/Anthropic/DeepMind docs, framework docs, BLS, Stanford AI Index, etc.)."
        )
    if external_untrusted and len(external_untrusted) > external_count - trusted_count + 5:
        # Harmless — guard against accidental infinite growth (shouldn't fire)
        pass

    # --- Check 6: mandatory schemas ---
    declared_schemas = payload.get("schemas")
    if not isinstance(declared_schemas, list) or not declared_schemas:
        errors.append(
            'payload["schemas"] must list schema.org types declared on the page '
            '(e.g. ["Article", "FAQPage", "HowTo"]).'
        )
    else:
        schema_set = {str(s) for s in declared_schemas}
        if "Article" not in schema_set:
            errors.append('schemas must include "Article".')
        if "FAQPage" not in schema_set:
            errors.append('schemas must include "FAQPage".')
        if not (schema_set & _SATISFY_SCHEMAS):
            errors.append(
                f'schemas must include at least one of {sorted(_SATISFY_SCHEMAS)} '
                "(picked to match the post's content shape)."
            )

    # --- Check 7: FAQ 8-15 pairs ---
    faqs = payload.get("faqs")
    faq_count = len(faqs) if isinstance(faqs, list) else 0
    if faq_count < 8 or faq_count > 15:
        errors.append(
            f"pillar post has {faq_count} FAQ pairs; SEO-21 requires 8-15 "
            "(drawn from People Also Ask for the target query)."
        )

    # --- Check 8: comparison table when post is comparative ---
    is_comparative = bool(payload.get("comparative"))
    table_count = len(_TABLE_RE.findall(body_html))
    if is_comparative and table_count < 1:
        errors.append(
            "payload.comparative=true but body_html contains no <table> — "
            "comparative posts must render at least one comparison table "
            "to win table-shaped SERP features."
        )

    # --- Check 9: dateModified freshness (warn-only) ---
    from datetime import date as _date
    try:
        last_reviewed = payload.get("last_reviewed_on")
        if last_reviewed:
            delta = (_date.today() - _date.fromisoformat(str(last_reviewed))).days
            if delta > 90:
                warnings.append(
                    f"last_reviewed_on is {delta} days old — pillar posts should be "
                    "bumped quarterly (the curriculum-refresh cron can do this)."
                )
    except Exception:
        # Malformed date is caught by the base validator.
        pass

    # --- Check 10: OG image declared ---
    og_image = str(payload.get("og_image") or "").strip()
    expected_og = f"/og/blog/{slug}.png" if slug else ""
    if not og_image:
        # Allow implicit default — but flag so the author sees it.
        warnings.append(
            f"og_image not set explicitly; SEO-11 default '{expected_og}' will be used."
        )
    elif expected_og and og_image != expected_og:
        warnings.append(
            f"og_image '{og_image}' does not match the SEO-11 pattern '{expected_og}'."
        )

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "stats": {
            "pillar_tier": tier,
            "word_count": word_count,
            "min_words": min_words,
            "first_para_words": first_para_words,
            "h2_count": h2_count,
            "internal_links": internal_count,
            "external_links": external_count,
            "trusted_citations": trusted_count,
            "faq_count": faq_count,
            "tables": table_count,
            "schemas": list(payload.get("schemas") or []),
        },
    }


# ---------------- VideoObject emitter (SEO-22) ----------------


_ISO_DURATION_RE = re.compile(r"^PT(?:\d+H)?(?:\d+M)?(?:\d+S)?$")


def _coerce_iso_duration(value: str) -> Optional[str]:
    """Accept either an ISO-8601 duration ('PT14M23S') or mm:ss / h:mm:ss
    and return ISO-8601. Bad input → None."""
    if not value:
        return None
    value = str(value).strip()
    if _ISO_DURATION_RE.match(value):
        return value
    parts = value.split(":")
    try:
        parts_int = [int(p) for p in parts]
    except ValueError:
        return None
    if len(parts_int) == 2:
        m, s = parts_int
        return f"PT{m}M{s}S"
    if len(parts_int) == 3:
        h, m, s = parts_int
        return f"PT{h}H{m}M{s}S"
    return None


def build_video_object(video: dict) -> Optional[dict]:
    """Emit a single VideoObject JSON-LD dict from cached YouTube metadata.

    Required keys on `video`: id, title, description, published_at,
    duration (ISO-8601 or h:mm:ss). Returns None if any required key
    is missing — caller skips the entry rather than emitting invalid
    schema (Google disqualifies the whole script on one bad object).
    """
    if not isinstance(video, dict):
        return None
    vid = str(video.get("id") or "").strip()
    title = str(video.get("title") or "").strip()
    desc = str(video.get("description") or "").strip()
    published = str(video.get("published_at") or "").strip()
    duration = _coerce_iso_duration(str(video.get("duration") or ""))
    if not (vid and title and desc and published and duration):
        return None

    thumb = str(video.get("thumbnail_url") or "").strip() or \
        f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg"

    return {
        "@context": "https://schema.org",
        "@type": "VideoObject",
        "name": title,
        "description": desc,
        "thumbnailUrl": thumb,
        "uploadDate": published,
        "duration": duration,
        "contentUrl": f"https://www.youtube.com/watch?v={vid}",
        "embedUrl": f"https://www.youtube.com/embed/{vid}",
    }


def build_video_objects(videos: Iterable[dict]) -> list[dict]:
    """Emit JSON-LD for all valid videos; silently drops malformed ones."""
    out: list[dict] = []
    for v in videos or []:
        obj = build_video_object(v)
        if obj is not None:
            out.append(obj)
    return out


def validate_videos_metadata(payload: dict) -> list[str]:
    """If payload declares a youtube_ids list OR a videos array, confirm
    the cached metadata (harvested at publish time) covers every id with
    all required fields. Returns a list of violation strings; empty
    means clean. This runs regardless of pillar_tier — VideoObject is
    independent of SEO-21 (any post can embed video)."""
    violations: list[str] = []
    ids = payload.get("youtube_ids") or []
    videos = payload.get("videos") or []
    if not isinstance(ids, list):
        return ["youtube_ids must be a list of YouTube video ids."]
    if not isinstance(videos, list):
        return ["videos must be a list of cached metadata dicts."]
    if not ids and not videos:
        return []

    # Every declared id needs a cached metadata entry.
    by_id = {str(v.get("id", "")).strip(): v for v in videos if isinstance(v, dict)}
    for vid in ids:
        entry = by_id.get(str(vid).strip())
        if not entry:
            violations.append(
                f"youtube_ids contains '{vid}' but no matching entry in videos[] — "
                "run the harvest step to cache title/description/duration/published_at."
            )
            continue
        obj = build_video_object(entry)
        if obj is None:
            missing = [k for k in ("id", "title", "description", "published_at", "duration")
                       if not str(entry.get(k) or "").strip()]
            violations.append(
                f"video '{vid}' cached metadata missing field(s): {missing}."
            )
    return violations
