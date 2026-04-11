"""
AI provider router — tries providers in priority order with fallback.

Chain: Gemini → Groq → Cerebras → Mistral → DeepSeek → Sambanova.
Uses circuit breaker to skip unavailable providers (402, 404, cooldown).
Logs every call to ai_usage_log for admin dashboard.
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.ai.health import is_available, record_error, record_rate_limit, record_success
from app.config import get_settings

logger = logging.getLogger("roadmap.ai.provider")

MAX_RETRIES = 2
BACKOFF_BASE = 1.0  # seconds


class AIProviderError(Exception):
    """All providers failed."""
    pass


# Each entry: (name, complete_fn_getter, error_class, rate_limit_class, model_field)
_PROVIDERS = [
    (
        "gemini",
        lambda: __import__("app.ai.gemini", fromlist=["complete"]).complete,
        lambda: __import__("app.ai.gemini", fromlist=["GeminiError"]).GeminiError,
        lambda: __import__("app.ai.gemini", fromlist=["GeminiRateLimited"]).GeminiRateLimited,
        "gemini_model",
    ),
    (
        "groq",
        lambda: __import__("app.ai.groq", fromlist=["complete"]).complete,
        lambda: __import__("app.ai.groq", fromlist=["GroqError"]).GroqError,
        lambda: __import__("app.ai.groq", fromlist=["GroqRateLimited"]).GroqRateLimited,
        "groq_model",
    ),
    (
        "cerebras",
        lambda: __import__("app.ai.cerebras", fromlist=["complete"]).complete,
        lambda: __import__("app.ai.cerebras", fromlist=["CerebrasError"]).CerebrasError,
        lambda: __import__("app.ai.cerebras", fromlist=["CerebrasRateLimited"]).CerebrasRateLimited,
        "cerebras_model",
    ),
    (
        "mistral",
        lambda: __import__("app.ai.mistral", fromlist=["complete"]).complete,
        lambda: __import__("app.ai.mistral", fromlist=["MistralError"]).MistralError,
        lambda: __import__("app.ai.mistral", fromlist=["MistralRateLimited"]).MistralRateLimited,
        "mistral_model",
    ),
    (
        "deepseek",
        lambda: __import__("app.ai.deepseek", fromlist=["complete"]).complete,
        lambda: __import__("app.ai.deepseek", fromlist=["DeepSeekError"]).DeepSeekError,
        lambda: __import__("app.ai.deepseek", fromlist=["DeepSeekRateLimited"]).DeepSeekRateLimited,
        "deepseek_model",
    ),
    (
        "sambanova",
        lambda: __import__("app.ai.sambanova", fromlist=["complete"]).complete,
        lambda: __import__("app.ai.sambanova", fromlist=["SambanovaError"]).SambanovaError,
        lambda: __import__("app.ai.sambanova", fromlist=["SambanovaRateLimited"]).SambanovaRateLimited,
        "sambanova_model",
    ),
]


def _extract_http_status(error_msg: str) -> int | None:
    """Try to extract HTTP status code from error message."""
    import re
    match = re.search(r"API error: (\d+)", str(error_msg))
    if match:
        return int(match.group(1))
    return None


async def complete(
    prompt: str,
    *,
    json_response: bool = True,
    task: str = "unknown",
    subtask: str | None = None,
    db=None,
) -> tuple[dict | str, str]:
    """Call the best available AI provider.

    Returns: (response, model_name)

    Tries providers in priority order, skipping unavailable ones (circuit breaker).
    Logs each attempt to ai_usage_log if db session provided.
    """
    settings = get_settings()
    errors = []

    for name, fn_getter, err_getter, rl_getter, model_field in _PROVIDERS:
        # Skip providers without API keys
        api_key = getattr(settings, f"{name}_api_key", "")
        if not api_key:
            continue

        # Circuit breaker: skip unavailable providers
        if not is_available(name):
            logger.debug("Skipping %s (circuit breaker: unavailable)", name)
            errors.append(f"{name}: unavailable (circuit breaker)")
            continue

        complete_fn = fn_getter()
        RateLimitedError = rl_getter()
        ProviderError = err_getter()
        model = getattr(settings, model_field, name)

        for attempt in range(MAX_RETRIES + 1):
            start = time.time()
            try:
                # Pass task to Gemini for right-sized tokens/timeout
                kwargs = {"json_response": json_response}
                if name == "gemini":
                    kwargs["task"] = task
                    # Structured output schemas — guarantee valid JSON shape
                    if task == "generation":
                        from app.ai.schemas import PLAN_TEMPLATE_SCHEMA
                        kwargs["json_schema"] = PLAN_TEMPLATE_SCHEMA
                result = await complete_fn(prompt, **kwargs)
                latency = int((time.time() - start) * 1000)

                record_success(name)

                # Log success
                if db is not None:
                    from app.ai.health import log_usage
                    await log_usage(
                        db, name, model, task, "ok",
                        subtask=subtask, latency_ms=latency,
                    )

                return result, model

            except RateLimitedError:
                latency = int((time.time() - start) * 1000)
                logger.warning("%s rate limited (attempt %d)", name, attempt + 1)
                record_rate_limit(name)

                if db is not None:
                    from app.ai.health import log_usage
                    await log_usage(
                        db, name, model, task, "rate_limited",
                        subtask=subtask, latency_ms=latency,
                    )

                if attempt < MAX_RETRIES:
                    await asyncio.sleep(BACKOFF_BASE * (2 ** attempt))
                    continue
                errors.append(f"{name}: rate limited")
                break

            except ProviderError as e:
                latency = int((time.time() - start) * 1000)
                error_str = str(e)
                logger.warning("%s error: %s", name, error_str)

                http_status = _extract_http_status(error_str)
                record_error(name, error_str, http_status)

                if db is not None:
                    from app.ai.health import log_usage
                    await log_usage(
                        db, name, model, task, "error",
                        subtask=subtask, error_message=error_str,
                        latency_ms=latency,
                    )

                errors.append(f"{name}: {error_str}")
                break

        logger.info("Falling back from %s to next provider", name)

    raise AIProviderError(
        f"All AI providers failed. Errors: {'; '.join(errors) if errors else 'no providers configured'}"
    )
