"""
Shared per-task token / timeout limits for all AI providers.

Rule #3 of the AI efficiency checklist: never leave max_tokens open-ended.
Every provider client imports these instead of hardcoding their own ceiling.
"""

from __future__ import annotations

TOKEN_LIMITS: dict[str, int] = {
    "chat": 1024,
    "triage": 512,
    "discovery": 4096,
    "generation": 8192,
    "quality_review": 4096,
    "quality_refine": 4096,
    "eval": 2048,
    "refresh": 2048,
    "embedding": 0,   # N/A — embeddings don't generate tokens
    "default": 4096,
}

TIMEOUTS: dict[str, float] = {
    "generation": 90.0,
    "quality_review": 60.0,
    "quality_refine": 60.0,
    "discovery": 60.0,
    "default": 30.0,
}


def get_max_tokens(task: str) -> int:
    return TOKEN_LIMITS.get(task, TOKEN_LIMITS["default"])


def get_timeout(task: str) -> float:
    return TIMEOUTS.get(task, TIMEOUTS["default"])
