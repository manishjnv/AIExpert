"""Simplify scraped JD HTML into scannable bullets.

Job descriptions on ATSes are written as marketing prose. Readers want to
know three things: what the role does, what they need to have, what they'll
get. Everything else (about us / come work with us / how we're different /
our values / EEO statement / application process) is filler from the
candidate's point of view.

This module parses the HTML, classifies each section by its heading, keeps
the signal, drops the filler, and converts wall-of-text paragraphs into
bullet points where it's safe to do so. No external deps — uses stdlib
html.parser so it's cheap to run at render time.

The output is small HTML that renders inline above the collapsible raw JD.
If classification yields nothing (very short JDs, unusual structure), the
caller falls back to showing only the raw JD.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from html import escape as _esc

# Section heading text (case-insensitive substring) that we DROP entirely.
# Every entry here is filler from a candidate's scanning perspective.
DROP_PATTERNS = [
    "about us", "about the company", "about anthropic", "about the team",
    "who we are", "our team", "our company", "our mission", "our values",
    "our culture", "why us", "why join", "why work", "come work",
    "how we're different", "how we are different", "what we do",
    "application process", "interview process", "next steps",
    "equal opportunity", "eeo", "diversity", "inclusion statement",
    "compensation philosophy", "logistics",
    "deadline to apply", "the fine print",
]

# Section headings we explicitly KEEP. Anything not matching either list is
# kept by default (safer than dropping unknown sections).
KEEP_PATTERNS = [
    "responsibilit", "what you'll do", "what you will do", "what you do",
    "the role", "the opportunity", "key responsibilities",
    "requirement", "qualifications", "what we're looking for",
    "what we are looking for", "you have", "you bring", "you should have",
    "must have", "must-have",
    "nice to have", "nice-to-have", "preferred qualifications", "bonus",
    "benefits", "what we offer", "what you'll get", "perks",
]

# Headings to rewrite for consistency in the simplified view.
HEADING_REWRITE = [
    (re.compile(r"responsibilit|what you.?ll do|what you do|the role|the opportunity",
                re.I), "What you'll do"),
    (re.compile(r"requirement|qualifications|what we.?re looking for|you have|"
                r"you bring|you should have|must.?have", re.I), "Requirements"),
    (re.compile(r"nice.?to.?have|preferred qualifications|bonus", re.I), "Nice to have"),
    (re.compile(r"benefit|what we offer|what you.?ll get|perks", re.I), "Benefits"),
]


class _Flattener(HTMLParser):
    """Flatten HTML into an ordered stream of ('h', text) / ('p', text) / ('li', text).

    Nested structures (divs, spans, formatting) are transparent — only block
    semantics and list items are preserved. Scripts/styles are dropped.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stream: list[tuple[str, str]] = []
        self._buf: list[str] = []
        self._kind: str | None = None
        self._skip_depth = 0
        self._strong_only = False
        self._strong_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("script", "style"):
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in ("h1", "h2", "h3", "h4"):
            self._flush()
            self._kind = "h"
        elif tag == "li":
            self._flush()
            self._kind = "li"
        elif tag == "p":
            self._flush()
            self._kind = "p"
            self._strong_depth = 0
            self._strong_only = True
        elif tag in ("strong", "b") and self._kind == "p":
            self._strong_depth += 1
        elif tag == "br" and self._kind in ("p", "li"):
            self._buf.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag in ("h1", "h2", "h3", "h4", "p", "li"):
            # Promote <p> that contains only a <strong> run to a heading.
            if self._kind == "p" and self._strong_only and self._strong_depth:
                self._kind = "h"
            self._flush()
        elif tag in ("strong", "b") and self._kind == "p":
            self._strong_depth = max(0, self._strong_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._skip_depth or self._kind is None:
            return
        if self._kind == "p":
            # Any non-whitespace outside a <strong> disqualifies the
            # strong-only-paragraph heading promotion.
            if self._strong_depth == 0 and data.strip():
                self._strong_only = False
        self._buf.append(data)

    def _flush(self) -> None:
        if self._kind is None:
            return
        text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
        if text:
            self.stream.append((self._kind, text))
        self._buf = []
        self._kind = None
        self._strong_only = False
        self._strong_depth = 0


def _classify(heading: str) -> str | None:
    h = heading.lower().strip(" :·-–—")
    for pat in DROP_PATTERNS:
        if pat in h:
            return "drop"
    for pat in KEEP_PATTERNS:
        if pat in h:
            return "keep"
    # Unknown heading — keep by default so we don't silently lose content.
    return "keep"


def _canonical_heading(heading: str) -> str:
    for pattern, replacement in HEADING_REWRITE:
        if pattern.search(heading):
            return replacement
    return heading.strip(" :·-–—").strip()


def _sentence_bullets(paragraph: str, max_items: int = 6) -> list[str]:
    """Turn a prose paragraph into bullets at sentence boundaries.

    Only applied when a kept section has no <li> items — otherwise native
    bullets win. Paragraphs under ~160 chars are left as a single item.
    """
    if len(paragraph) < 160:
        return [paragraph]
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", paragraph)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) < 2:
        return [paragraph]
    return parts[:max_items]


def simplify_jd(html: str) -> dict[str, list[str]]:
    """Return {section_name: [bullet, ...]} of kept, de-fluffed content.

    Empty dict when the input is empty, too short, or has no usable structure.
    Caller decides whether to render the simplified view or fall back to the
    raw JD inside a collapsible details block.
    """
    if not html or len(html) < 80:
        return {}

    f = _Flattener()
    try:
        f.feed(html)
        f._flush()
    except Exception:
        return {}

    sections: dict[str, list[str]] = {}
    current_name: str | None = None
    current_kind: str = "keep"
    pending_para: list[str] = []

    def _commit_pending() -> None:
        nonlocal pending_para
        if current_kind == "drop" or current_name is None or not pending_para:
            pending_para = []
            return
        for para in pending_para:
            for item in _sentence_bullets(para):
                item = item.strip(" •*-–—")
                if item and len(item) > 3:
                    sections.setdefault(current_name, []).append(item)
        pending_para = []

    for kind, text in f.stream:
        if kind == "h":
            _commit_pending()
            current_kind = _classify(text) or "keep"
            current_name = _canonical_heading(text) if current_kind == "keep" else None
        elif kind == "li":
            _commit_pending()
            if current_kind == "drop":
                continue
            name = current_name or "Highlights"
            clean = text.strip(" •*-–—")
            if clean and len(clean) > 3:
                sections.setdefault(name, []).append(clean)
        elif kind == "p":
            if current_kind == "drop":
                continue
            pending_para.append(text)

    _commit_pending()

    # Trim each section to a sensible cap + drop empties.
    out: dict[str, list[str]] = {}
    for name, items in sections.items():
        # Dedup while preserving order.
        seen: set[str] = set()
        deduped: list[str] = []
        for it in items:
            key = it.lower()
            if key not in seen:
                seen.add(key)
                deduped.append(it)
        if deduped:
            out[name] = deduped[:10]

    # Order sections for display: responsibilities → requirements → nice-to-have → benefits → rest.
    preferred = ["What you'll do", "Requirements", "Nice to have", "Benefits"]
    ordered: dict[str, list[str]] = {}
    for name in preferred:
        if name in out:
            ordered[name] = out.pop(name)
    # Drop leftover unnamed/filler-looking sections unless they're substantial.
    for name, items in out.items():
        if name in ("Highlights",) or len(items) >= 3:
            ordered[name] = items

    # If everything got dropped, signal fallback to raw.
    if sum(len(v) for v in ordered.values()) < 2:
        return {}
    return ordered


def render_simplified(sections: dict[str, list[str]]) -> str:
    """Render the output of simplify_jd into HTML. Returns '' for empty input."""
    if not sections:
        return ""
    parts: list[str] = ['<div class="jd-simple">']
    for name, items in sections.items():
        parts.append(f'<h3 class="jd-sec">{_esc(name)}</h3>')
        parts.append('<ul class="jd-bullets">')
        for it in items:
            parts.append(f"<li>{_esc(it)}</li>")
        parts.append("</ul>")
    parts.append("</div>")
    return "".join(parts)
