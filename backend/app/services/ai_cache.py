"""
Simple file-based AI response cache.

Per AI Enrichment Blueprint: every LLM call must be preceded by a cache check.
Uses JSON files in a cache directory. No Redis needed for our scale.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger("roadmap.ai_cache")

CACHE_DIR = Path(__file__).parent.parent.parent / "data" / "ai_cache"
DEFAULT_TTL = 86400 * 7  # 7 days


def _cache_key(prompt_type: str, params: str) -> str:
    """Deterministic cache key from prompt type and params."""
    raw = f"{prompt_type}:{params}"
    return hashlib.sha256(raw.encode()).hexdigest()


def cache_get(prompt_type: str, params: str) -> dict | None:
    """Check cache before an AI call. Returns cached response or None."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = _cache_key(prompt_type, params)
    path = CACHE_DIR / f"{key}.json"

    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if time.time() > data.get("expires_at", 0):
            path.unlink(missing_ok=True)
            logger.debug("Cache expired: %s/%s", prompt_type, key[:12])
            return None
        logger.debug("Cache hit: %s/%s", prompt_type, key[:12])
        return data["response"]
    except (json.JSONDecodeError, KeyError):
        path.unlink(missing_ok=True)
        return None


def cache_set(prompt_type: str, params: str, response: dict, ttl: int = DEFAULT_TTL) -> None:
    """Store an AI response in cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = _cache_key(prompt_type, params)
    path = CACHE_DIR / f"{key}.json"

    data = {
        "prompt_type": prompt_type,
        "cached_at": time.time(),
        "expires_at": time.time() + ttl,
        "response": response,
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.debug("Cache set: %s/%s (ttl=%ds)", prompt_type, key[:12], ttl)


def cache_clear(prompt_type: str | None = None) -> int:
    """Clear cache entries. If prompt_type given, only clear that type."""
    if not CACHE_DIR.exists():
        return 0
    count = 0
    for path in CACHE_DIR.glob("*.json"):
        if prompt_type:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("prompt_type") != prompt_type:
                    continue
            except (json.JSONDecodeError, KeyError):
                pass
        path.unlink(missing_ok=True)
        count += 1
    return count
