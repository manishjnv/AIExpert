"""Blog publishing pipeline — JSON-in, file-backed, human-gated.

Flow:
  admin pastes Claude's JSON into /admin/blog
    → validate_payload() runs 20+ checks (schema, banned terms,
      branding, length, structure, image brief)
    → save_draft() writes /data/blog/drafts/<slug>.json
    → admin reviews in /admin/blog draft list
    → publish_draft() moves to /data/blog/published/<slug>.json
      and stamps last_reviewed_on + last_reviewed_by

No AI call on our dime. No auto-publish path.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date as _date, datetime, timezone
from html import unescape
from pathlib import Path
from typing import Optional

logger = logging.getLogger("roadmap.blog_publisher")

# /data is mounted in docker-compose so drafts + published posts
# survive container rebuilds. In tests (no CHAT_RATE_DIR-like flag
# here), tests can monkeypatch BLOG_ROOT to a temp dir.
BLOG_ROOT = Path("/data/blog")
DRAFTS_DIR = BLOG_ROOT / "drafts"
PUBLISHED_DIR = BLOG_ROOT / "published"

REQUIRED_FIELDS = (
    "title", "slug", "author", "published", "tags",
    "og_description", "lede", "body_html", "word_count", "image_brief",
)
REQUIRED_IMAGE_FIELDS = ("hero_prompt", "hero_alt", "hero_filename")

# Banned terms — same list as the Claude prompt. Case-insensitive
# whole-word-ish match. Scans title / lede / body_html / og_description
# / tags. A single hit flags the post.
_BANNED_TERMS = [
    # Stack
    r"\bFastAPI\b", r"\bFlask\b", r"\bDjango\b", r"\bSQLAlchemy\b",
    r"\bSQLite\b", r"\bPostgres(?:QL)?\b", r"\bnginx\b", r"\bDocker\b",
    r"\bKubernetes\b", r"\bVue\b", r"\bReact\b", r"\bAngular\b",
    r"\bHTMX\b", r"\bvanilla\s+JS\b", r"\balembic\b", r"\bpytest\b",
    r"\bpydantic\b", r"\bpydyf\b", r"\bWeasyPrint\b", r"\bJinja\b",
    # AI providers / model families
    r"\bGemini\b", r"\bClaude\b", r"\bGPT-?\d*\b", r"\bOpenAI\b",
    r"\bAnthropic\b", r"\bGroq\b", r"\bCerebras\b", r"\bMistral\b",
    r"\bDeepSeek\b", r"\bSambanova\b", r"\bLangChain\b", r"\bLangGraph\b",
    r"\bMCP\b", r"\bImagen\b", r"\bMidjourney\b", r"\bDALL.?E\b",
    r"\bFirefly\b",
    # Impl details
    r"\bHMAC(?:-SHA\d+)?\b", r"\bSHA-?256\b", r"\bSHA-?512\b", r"\bJWT\b",
    r"\bbcrypt\b", r"\bJSON\s+Schema\b",
    # Repo / source
    r"github\.com/\S+", r"source\s+code", r"manishjnv/AIExpert",
    # Operational leaks
    r"\bsession\s+\d+\b", r"\bcommit\s+[0-9a-f]{6,}\b",
]
_BANNED_RE = re.compile("|".join(_BANNED_TERMS), re.IGNORECASE)

# Safe HTML tags allowed in body_html. Anything else triggers a warning.
_ALLOWED_TAGS = {
    "p", "h2", "h3", "strong", "em", "a", "ul", "ol", "li",
    "hr", "br", "blockquote", "code", "figure", "img", "span", "div",
}
_TAG_RE = re.compile(r"<(/?[a-zA-Z][a-zA-Z0-9]*)", re.IGNORECASE)

_WORD_RE = re.compile(r"\b\w+\b")


# ---------------- public API ----------------


def _strip_tags(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    return unescape(re.sub(r"\s+", " ", text)).strip()


def _count_words(text: str) -> int:
    return len(_WORD_RE.findall(text))


def slugify(title: str, prefix: Optional[str] = None) -> str:
    """Derive a URL slug from a title. Optionally prepend a zero-padded
    NN- prefix (for new-post auto-numbering)."""
    body = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]
    return f"{prefix}-{body}" if prefix else body


def next_slug_prefix() -> str:
    """Next zero-padded slug prefix across drafts and published posts."""
    max_n = 0
    for d in (DRAFTS_DIR, PUBLISHED_DIR):
        if d.exists():
            for f in d.glob("*.json"):
                m = re.match(r"(\d+)-", f.stem)
                if m:
                    try:
                        max_n = max(max_n, int(m.group(1)))
                    except ValueError:
                        pass
    # Also count the hardcoded /blog/01 so next slug starts at 02
    max_n = max(max_n, 1)
    return f"{max_n + 1:02d}"


def validate_payload(payload: dict) -> dict:
    """Run every automated check on a blog JSON payload.

    Returns:
      {
        "ok": bool,                 # True iff no errors (warnings allowed)
        "errors": [str, ...],       # blocking — must fix to publish
        "warnings": [str, ...],     # non-blocking — admin judgement call
        "stats": {word_count, paragraphs, h2_count, ...},
      }
    """
    errors: list[str] = []
    warnings: list[str] = []

    # --- Schema shape ---
    if not isinstance(payload, dict):
        return {"ok": False, "errors": ["Payload is not a JSON object."],
                "warnings": [], "stats": {}}

    for field in REQUIRED_FIELDS:
        if field not in payload:
            errors.append(f"Missing required field: {field}")
    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings, "stats": {}}

    if not isinstance(payload.get("image_brief"), dict):
        errors.append("image_brief must be an object.")
    else:
        for sub in REQUIRED_IMAGE_FIELDS:
            if sub not in payload["image_brief"]:
                errors.append(f"image_brief missing field: {sub}")

    # --- Field types + basic constraints ---
    title = str(payload.get("title", "")).strip()
    slug = str(payload.get("slug", "")).strip()
    author = str(payload.get("author", "")).strip()
    published = str(payload.get("published", "")).strip()
    tags = payload.get("tags")
    og = str(payload.get("og_description", "")).strip()
    lede = str(payload.get("lede", "")).strip()
    body_html = str(payload.get("body_html", ""))
    claimed_wc = payload.get("word_count")

    if not title:
        errors.append("title is empty.")
    elif len(title) > 150:
        errors.append(f"title too long ({len(title)} chars, max 150).")

    if not re.fullmatch(r"\d{2,3}-[a-z0-9-]+", slug):
        errors.append("slug must match pattern '<NN>-<kebab-case>' (e.g. '02-policy-beats-tools').")

    if not author:
        errors.append("author is empty.")

    try:
        _date.fromisoformat(published)
    except Exception:
        errors.append("published must be an ISO date (YYYY-MM-DD).")

    if not isinstance(tags, list) or len(tags) < 3 or len(tags) > 5:
        errors.append("tags must be a list of 3–5 strings.")
    elif tags[0] != "build-in-public":
        errors.append("tags[0] must be 'build-in-public'.")

    if not og:
        errors.append("og_description is empty.")
    elif len(og) > 220:
        warnings.append(f"og_description is long ({len(og)} chars) — some link previews truncate at 200.")

    if not lede:
        errors.append("lede is empty.")
    elif len(lede.split()) > 30:
        errors.append(f"lede is {len(lede.split())} words — must be ≤ 30.")
    elif "<" in lede or ">" in lede:
        errors.append("lede should be plain text, no HTML tags.")

    # --- Body checks ---
    stripped = _strip_tags(body_html)
    actual_wc = _count_words(stripped)
    if actual_wc < 800:
        errors.append(f"body is {actual_wc} words — below the 800 minimum.")
    elif actual_wc > 1500:
        warnings.append(f"body is {actual_wc} words — over the 1500 target (may lose recruiter readers).")

    if isinstance(claimed_wc, int) and abs(claimed_wc - actual_wc) > 50:
        warnings.append(f"word_count mismatch — claimed {claimed_wc}, measured {actual_wc}.")

    h2_count = len(re.findall(r"<h2[^>]*>", body_html, re.IGNORECASE))
    if h2_count < 3:
        errors.append(f"body has {h2_count} <h2> sections — need at least 3.")

    paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", body_html, re.IGNORECASE | re.DOTALL)
    if len(paragraphs) < 5:
        warnings.append(f"body has only {len(paragraphs)} paragraphs — feels thin.")

    # Long-paragraph and long-sentence heuristics (warnings only — editorial judgement)
    long_paras = 0
    long_sentences = 0
    for p in paragraphs:
        p_text = _strip_tags(p)
        sentences = re.split(r"(?<=[.!?])\s+", p_text)
        if len([s for s in sentences if s.strip()]) > 4:
            long_paras += 1
        for s in sentences:
            if _count_words(s) > 30:
                long_sentences += 1
    if long_paras:
        warnings.append(f"{long_paras} paragraph(s) exceed 4 sentences — consider splitting.")
    if long_sentences:
        warnings.append(f"{long_sentences} sentence(s) exceed 30 words — consider tightening.")

    if '<p class="lede">' not in body_html and "<p class='lede'>" not in body_html:
        warnings.append("body_html doesn't open with a `<p class=\"lede\">` — lede will render without special styling.")

    if "<hr" not in body_html:
        warnings.append("no <hr> dividing rule found before the closing CTA.")

    # Disallowed tags
    seen_tags = {m.group(1).lower().lstrip("/") for m in _TAG_RE.finditer(body_html)}
    stray = seen_tags - _ALLOWED_TAGS
    if stray:
        warnings.append(f"body uses non-standard tags: {sorted(stray)} (will still render).")

    if "<script" in body_html.lower() or "<style" in body_html.lower():
        errors.append("body_html must not contain <script> or <style> blocks.")

    # --- Banned-terms / branding scan ---
    scan_targets = {
        "title": title, "lede": lede, "og_description": og,
        "body_html": body_html,
        "tags": " ".join(tags) if isinstance(tags, list) else "",
    }
    for field, text in scan_targets.items():
        hits = _BANNED_RE.findall(text)
        if hits:
            # Dedup case-insensitively
            uniq = sorted({h if isinstance(h, str) else h[0] for h in hits}, key=str.lower)
            errors.append(f"{field} contains banned term(s): {uniq}")

    # --- Quotables ---
    quotable = payload.get("quotable_lines", [])
    if not isinstance(quotable, list) or len(quotable) < 1:
        warnings.append("no quotable_lines provided — harder to pull copy for LinkedIn.")

    # --- Image brief sanity ---
    img = payload.get("image_brief", {}) or {}
    hp = str(img.get("hero_prompt", ""))
    if len(hp) < 40:
        warnings.append("hero_prompt is very short — may produce a generic image.")
    hf = str(img.get("hero_filename", ""))
    if hf and not hf.endswith((".png", ".jpg", ".jpeg", ".webp")):
        warnings.append(f"hero_filename '{hf}' lacks an image extension.")
    if hf and not hf.startswith(slug.split("-", 1)[0] if slug else ""):
        warnings.append("hero_filename prefix doesn't match slug number.")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "stats": {
            "word_count": actual_wc,
            "paragraphs": len(paragraphs),
            "h2_count": h2_count,
            "long_paragraphs": long_paras,
            "long_sentences": long_sentences,
            "quotable_lines": len(quotable) if isinstance(quotable, list) else 0,
            "tags_count": len(tags) if isinstance(tags, list) else 0,
            "og_length": len(og),
        },
    }


# ---------------- persistence ----------------


def _ensure_dirs() -> None:
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)


def save_draft(payload: dict, admin_name: str) -> Path:
    _ensure_dirs()
    slug = payload["slug"]
    payload = {**payload, "_saved_by": admin_name,
               "_saved_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
    path = DRAFTS_DIR / f"{slug}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Blog draft saved: %s (by %s)", slug, admin_name)
    return path


def load_draft(slug: str) -> Optional[dict]:
    path = DRAFTS_DIR / f"{slug}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def delete_draft(slug: str) -> bool:
    path = DRAFTS_DIR / f"{slug}.json"
    if path.exists():
        path.unlink()
        return True
    return False


def list_drafts() -> list[dict]:
    _ensure_dirs()
    out = []
    for f in sorted(DRAFTS_DIR.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            out.append({
                "slug": d.get("slug", f.stem),
                "title": d.get("title", ""),
                "published": d.get("published", ""),
                "saved_by": d.get("_saved_by", "—"),
                "saved_at": d.get("_saved_at", ""),
            })
        except Exception:
            continue
    return out


def publish_draft(slug: str, admin_name: str) -> dict:
    """Move a validated draft to published. Stamps reviewer + date."""
    _ensure_dirs()
    src = DRAFTS_DIR / f"{slug}.json"
    if not src.exists():
        raise FileNotFoundError(f"Draft not found: {slug}")
    payload = json.loads(src.read_text(encoding="utf-8"))

    # Re-validate before publishing — drafts could be stale post-rule-changes
    report = validate_payload(payload)
    if not report["ok"]:
        raise ValueError("Draft failed validation at publish time: "
                         + "; ".join(report["errors"]))

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    payload["last_reviewed_by"] = admin_name
    payload["last_reviewed_on"] = _date.today().isoformat()
    payload["_published_at"] = now

    dst = PUBLISHED_DIR / f"{slug}.json"
    dst.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    src.unlink()
    logger.info("Blog published: %s (by %s)", slug, admin_name)
    return payload


def load_published(slug: str) -> Optional[dict]:
    path = PUBLISHED_DIR / f"{slug}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_published() -> list[dict]:
    _ensure_dirs()
    out = []
    for f in sorted(PUBLISHED_DIR.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            out.append({
                "slug": d.get("slug", f.stem),
                "title": d.get("title", ""),
                "published": d.get("published", ""),
                "last_reviewed_by": d.get("last_reviewed_by", "—"),
                "last_reviewed_on": d.get("last_reviewed_on", ""),
            })
        except Exception:
            continue
    return out


def unpublish(slug: str) -> bool:
    path = PUBLISHED_DIR / f"{slug}.json"
    if not path.exists():
        return False
    # Move back to drafts so edits are non-destructive
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("last_reviewed_by", None)
    payload.pop("last_reviewed_on", None)
    payload.pop("_published_at", None)
    (DRAFTS_DIR / f"{slug}.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    path.unlink()
    return True
