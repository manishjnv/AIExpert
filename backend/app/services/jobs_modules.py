"""Map between job skills and curriculum weeks.

Published templates → indexed by lowercased skill tokens (title, focus items,
deliverables) → returns week references (template_key, week_num) for each token.

Used by:
- jobs_match.compute_match(): modules_overlap component.
- "Close the gap" CTA on job pages: missing skill → enroll link.

Cache is process-local; rebuilt on first call after publish_template() /
unpublish_template() invalidates it via `invalidate_skill_index()`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from threading import Lock

from app.curriculum.loader import list_published, load_template

logger = logging.getLogger("roadmap.jobs.modules")


@dataclass(frozen=True)
class WeekRef:
    template_key: str
    week_num: int
    week_title: str
    month: int


_SKILL_INDEX: dict[str, list[WeekRef]] | None = None
_LOCK = Lock()

# Tokens that match literally everywhere; skipping them keeps the index useful.
_STOPWORDS = {
    "and", "or", "the", "a", "an", "of", "for", "with", "to", "in", "on", "by",
    "your", "you", "build", "create", "repo", "using", "use", "setup", "set-up",
}


def _tokens(text: str) -> set[str]:
    """Extract skill-ish tokens from arbitrary curriculum text.

    Strategy: whole-word tokens (3+ chars) + common multi-word tech terms.
    Conservative — better to miss a match than produce a false one.
    """
    text = text.lower()
    # Multi-word terms we want to preserve as a single token.
    phrases = {
        "distributed training", "deep learning", "machine learning",
        "reinforcement learning", "neural networks", "large language models",
        "computer vision", "natural language processing", "prompt engineering",
        "fine-tuning", "fine tuning", "vector databases", "data engineering",
        "version control", "design patterns", "software engineering",
    }
    found: set[str] = set()
    for p in phrases:
        if p in text:
            found.add(p)
    for w in re.findall(r"[a-z][a-z0-9+#\-\.]{2,}", text):
        if w not in _STOPWORDS:
            found.add(w)
    return found


def _build_index() -> dict[str, list[WeekRef]]:
    """Scan every published template and index tokens → weeks.

    A single week contributes many tokens (title + focus items). One token may
    map to many weeks across templates; we keep them ordered by how early the
    week appears so the UI's first link is the easiest starting point.
    """
    index: dict[str, list[WeekRef]] = {}
    for key in list_published():
        try:
            tpl = load_template(key)
        except Exception as exc:
            logger.warning("skill index: skipping %s (load failed: %s)", key, exc)
            continue
        for month in tpl.months:
            for week in month.weeks:
                ref = WeekRef(
                    template_key=tpl.key,
                    week_num=week.n,
                    week_title=week.t,
                    month=month.month,
                )
                # Only mine title + focus — deliv/checks are too specific to
                # the plan's own phrasing ("Repo ai-journey created with README")
                # and pollute the index.
                text = week.t + " " + " ".join(week.focus)
                for tok in _tokens(text):
                    index.setdefault(tok, []).append(ref)
    # Sort each bucket by (month, week) so the shallowest match comes first.
    for tok in index:
        index[tok].sort(key=lambda r: (r.month, r.week_num))
    logger.info("skill index built: %d tokens across %d templates",
                len(index), len(list_published()))
    return index


def _get_index() -> dict[str, list[WeekRef]]:
    global _SKILL_INDEX
    if _SKILL_INDEX is None:
        with _LOCK:
            if _SKILL_INDEX is None:
                _SKILL_INDEX = _build_index()
    return _SKILL_INDEX


def invalidate_skill_index() -> None:
    """Call after publishing / unpublishing a template. Cheap — next access rebuilds."""
    global _SKILL_INDEX
    with _LOCK:
        _SKILL_INDEX = None


def find_weeks_for_skill(skill: str, *, limit: int = 3) -> list[WeekRef]:
    """Return up to `limit` week refs that teach `skill`, shallowest first.
    Empty list if no match — signals 'no curriculum teaches this yet'."""
    idx = _get_index()
    norm = skill.strip().lower()
    if not norm:
        return []
    # Prefer exact token hit; fall back to any token that contains the query.
    if norm in idx:
        return idx[norm][:limit]
    for tok, refs in idx.items():
        if norm in tok:
            return refs[:limit]
    return []


def skill_index_stats() -> dict:
    """For observability — exposed on admin stats strip later."""
    idx = _get_index()
    return {"tokens": len(idx), "templates": len(list_published())}
