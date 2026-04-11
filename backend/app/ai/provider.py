"""
AI provider router — tries providers in priority order with fallback.

Chain: Gemini → Groq → Cerebras → Mistral → DeepSeek → Sambanova.
Handles retries with exponential backoff for transient errors.
"""

from __future__ import annotations

import asyncio
import logging

from app.config import get_settings

logger = logging.getLogger("roadmap.ai.provider")

MAX_RETRIES = 2
BACKOFF_BASE = 1.0  # seconds


class AIProviderError(Exception):
    """All providers failed."""
    pass


# Each entry: (module_path, complete_fn_getter, error_class, rate_limit_class, model_field)
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


async def complete(prompt: str, *, json_response: bool = True) -> tuple[dict | str, str]:
    """Call the best available AI provider.

    Returns: (response, model_name)

    Tries providers in priority order: Gemini → Groq → Cerebras → Mistral → DeepSeek → Sambanova.
    For each provider, retries on rate limits with exponential backoff.
    If all fail, raises AIProviderError.
    """
    settings = get_settings()
    errors = []

    for name, fn_getter, err_getter, rl_getter, model_field in _PROVIDERS:
        # Skip providers without API keys
        api_key = getattr(settings, f"{name}_api_key", "")
        if not api_key:
            continue

        complete_fn = fn_getter()
        RateLimitedError = rl_getter()
        ProviderError = err_getter()

        for attempt in range(MAX_RETRIES + 1):
            try:
                result = await complete_fn(prompt, json_response=json_response)
                model = getattr(settings, model_field, name)
                return result, model
            except RateLimitedError:
                logger.warning("%s rate limited (attempt %d)", name, attempt + 1)
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(BACKOFF_BASE * (2 ** attempt))
                    continue
                errors.append(f"{name}: rate limited")
                break
            except ProviderError as e:
                logger.warning("%s error: %s", name, e)
                errors.append(f"{name}: {e}")
                break

        logger.info("Falling back from %s to next provider", name)

    raise AIProviderError(
        f"All AI providers failed. Errors: {'; '.join(errors) if errors else 'no providers configured'}"
    )
