"""Social post curation prompt loader for Track 1 (Opus via Claude CLI).

§3.11 in AI_PIPELINE_PLAN.md. The {{TAG_MAP}} placeholder in
`backend/app/prompts/social_curate.txt` is substituted ONCE at module
load with the formatted _TAG_DISPLAY map from share_copy.py — keeps the
cached prompt prefix byte-identical per call (invariant #1).

Per-call substitution is only {{SOURCE_JSON}}.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.services.share_copy import _TAG_DISPLAY

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "social_curate.txt"


def _format_tag_map() -> str:
    """Render _TAG_DISPLAY as a stable, sorted, human-readable list."""
    width = max(len(slug) for slug in _TAG_DISPLAY) + 2
    lines = [
        f"  {slug:<{width}}-> {tag}"
        for slug, tag in sorted(_TAG_DISPLAY.items())
    ]
    return "\n".join(lines)


@lru_cache(maxsize=1)
def get_template() -> str:
    """Read prompt file and substitute {{TAG_MAP}} once. Cached for module lifetime."""
    raw = _PROMPT_PATH.read_text(encoding="utf-8")
    return raw.replace("{{TAG_MAP}}", _format_tag_map())


def build_prompt(source: dict) -> str:
    """Render the per-call prompt by substituting {{SOURCE_JSON}}.

    `source` is the dict shape emitted by scripts/export_social_sources.py:
      {kind: 'blog'|'course', slug, title, body_text|description, tags, url, ...}
    """
    template = get_template()
    payload = json.dumps(source, ensure_ascii=False, indent=2)
    return template.replace("{{SOURCE_JSON}}", payload)
