"""
AI provider router — tries Gemini first, falls back to Groq.

Handles retries with exponential backoff for transient errors.
"""

from __future__ import annotations

import asyncio
import logging

from app.ai.gemini import GeminiError, GeminiRateLimited
from app.ai.gemini import complete as gemini_complete
from app.ai.groq import GroqError, GroqRateLimited
from app.ai.groq import complete as groq_complete

logger = logging.getLogger("roadmap.ai.provider")

MAX_RETRIES = 2
BACKOFF_BASE = 1.0  # seconds


class AIProviderError(Exception):
    """All providers failed."""
    pass


async def complete(prompt: str, *, json_response: bool = True) -> tuple[dict | str, str]:
    """Call the best available AI provider.

    Returns: (response, model_name)

    Tries Gemini first. If Gemini fails with a retryable error,
    falls back to Groq. If both fail, raises AIProviderError.
    """
    # Try Gemini
    for attempt in range(MAX_RETRIES + 1):
        try:
            result = await gemini_complete(prompt, json_response=json_response)
            from app.config import get_settings
            return result, get_settings().gemini_model
        except GeminiRateLimited:
            logger.warning("Gemini rate limited (attempt %d)", attempt + 1)
            if attempt < MAX_RETRIES:
                await asyncio.sleep(BACKOFF_BASE * (2 ** attempt))
                continue
            break
        except GeminiError as e:
            logger.warning("Gemini error: %s", e)
            break

    # Fallback to Groq
    logger.info("Falling back to Groq")
    for attempt in range(MAX_RETRIES + 1):
        try:
            result = await groq_complete(prompt, json_response=json_response)
            from app.config import get_settings
            return result, get_settings().groq_model
        except GroqRateLimited:
            logger.warning("Groq rate limited (attempt %d)", attempt + 1)
            if attempt < MAX_RETRIES:
                await asyncio.sleep(BACKOFF_BASE * (2 ** attempt))
                continue
        except GroqError as e:
            logger.warning("Groq error: %s", e)
            break

    raise AIProviderError("All AI providers failed. Try again later.")
