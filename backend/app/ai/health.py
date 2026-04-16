"""
AI provider health tracker + circuit breaker.

Tracks per-provider health state in memory. Providers that return
permanent errors (402 insufficient balance, 404 model not found) are
marked unavailable. Providers that are rate-limited get a cooldown.

Also logs every AI call to the ai_usage_log table for the admin dashboard.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("roadmap.ai.health")

# ---- In-memory circuit breaker state ----

# Per-provider health: {provider_name: {...}}
_provider_state: dict[str, dict] = {}

# How long to wait after a rate limit before retrying (seconds)
RATE_LIMIT_COOLDOWN = 60
# Permanent errors — don't retry until restart or manual reset
PERMANENT_ERROR_CODES = {402, 404}


def _get_state(provider: str) -> dict:
    if provider not in _provider_state:
        _provider_state[provider] = {
            "available": True,
            "last_success": None,
            "last_error": None,
            "last_error_msg": None,
            "last_rate_limit": None,
            "rate_limit_count": 0,
            "error_count": 0,
            "success_count": 0,
            "permanent_error": False,
        }
    return _provider_state[provider]


def is_available(provider: str) -> bool:
    """Check if a provider is available (not permanently failed or in cooldown)."""
    state = _get_state(provider)

    if state["permanent_error"]:
        return False

    if state["last_rate_limit"] is not None:
        elapsed = time.time() - state["last_rate_limit"]
        if elapsed < RATE_LIMIT_COOLDOWN:
            return False

    return state["available"]


def record_success(provider: str) -> None:
    """Record a successful call."""
    state = _get_state(provider)
    state["available"] = True
    state["last_success"] = time.time()
    state["success_count"] += 1
    state["rate_limit_count"] = 0  # reset consecutive rate limits


def record_rate_limit(provider: str) -> None:
    """Record a rate limit hit."""
    state = _get_state(provider)
    state["last_rate_limit"] = time.time()
    state["rate_limit_count"] += 1
    state["last_error"] = time.time()
    state["last_error_msg"] = "rate_limited"


def record_error(provider: str, error_msg: str, http_status: int | None = None) -> None:
    """Record an error. Marks provider as permanently unavailable for 402/404."""
    state = _get_state(provider)
    state["error_count"] += 1
    state["last_error"] = time.time()
    state["last_error_msg"] = error_msg

    if http_status in PERMANENT_ERROR_CODES:
        state["permanent_error"] = True
        state["available"] = False
        logger.warning(
            "Provider %s marked permanently unavailable (HTTP %d): %s",
            provider, http_status, error_msg
        )


def reset_provider(provider: str) -> None:
    """Manually reset a provider's health state (e.g. after adding balance)."""
    if provider in _provider_state:
        del _provider_state[provider]
    logger.info("Provider %s health state reset", provider)


def get_all_health() -> dict[str, dict]:
    """Get health state for all known providers. For admin dashboard."""
    return {k: {**v} for k, v in _provider_state.items()}


# ---- Usage logging to DB ----


def get_last_tokens(provider_name: str) -> int:
    """Read total_tokens from a provider module's _last_usage dict.

    Every provider module (gemini, groq, cerebras, etc.) sets a module-level
    `_last_usage` dict after each successful API call. This helper reads it
    so callers don't need to repeat the __import__ + getattr dance.

    Returns 0 if the provider doesn't expose _last_usage or if the value
    is missing/empty.
    """
    try:
        mod = __import__(f"app.ai.{provider_name}", fromlist=["_last_usage"])
        last = getattr(mod, "_last_usage", None)
        if last and isinstance(last, dict):
            return int(last.get("total_tokens") or 0)
    except Exception:
        pass
    return 0


async def log_usage(
    db: AsyncSession,
    provider: str,
    model: str,
    task: str,
    status: str,
    *,
    subtask: Optional[str] = None,
    error_message: Optional[str] = None,
    tokens_estimated: int = 0,
    latency_ms: int = 0,
) -> None:
    """Log an AI call to the ai_usage_log table."""
    from app.models.curriculum import AIUsageLog

    log_entry = AIUsageLog(
        called_at=datetime.now(timezone.utc).replace(tzinfo=None),
        provider=provider,
        model=model,
        task=task,
        subtask=subtask,
        status=status,
        error_message=error_message[:500] if error_message else None,
        tokens_estimated=tokens_estimated,
        latency_ms=latency_ms,
    )
    db.add(log_entry)
    # Don't flush here — let the caller's transaction handle it
