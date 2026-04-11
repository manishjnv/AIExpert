"""
Cerebras API client — ultra-fast inference, OpenAI-compatible.

Same interface as gemini.py/groq.py for provider interchangeability.
"""

from __future__ import annotations

import json
import logging

import httpx

from app.config import get_settings

logger = logging.getLogger("roadmap.ai.cerebras")

CEREBRAS_URL = "https://api.cerebras.ai/v1/chat/completions"


class CerebrasError(Exception):
    pass


class CerebrasRateLimited(Exception):
    pass


async def complete(prompt: str, *, json_response: bool = True) -> dict | str:
    """Call Cerebras and return the response.

    Same interface as gemini.complete() / groq.complete().
    """
    settings = get_settings()
    if not settings.cerebras_api_key:
        raise CerebrasError("CEREBRAS_API_KEY not configured")

    body = {
        "model": settings.cerebras_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 8192,
    }

    if json_response:
        body["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            CEREBRAS_URL,
            headers={
                "Authorization": f"Bearer {settings.cerebras_api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        )

    if resp.status_code == 429:
        raise CerebrasRateLimited("Cerebras rate limited")
    if resp.status_code != 200:
        logger.error("Cerebras error %d: %s", resp.status_code, resp.text[:500])
        raise CerebrasError(f"Cerebras API error: {resp.status_code}")

    data = resp.json()
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise CerebrasError(f"Unexpected Cerebras response structure: {e}") from e

    if json_response:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise CerebrasError(f"Cerebras returned non-JSON: {text[:200]}")

    return text
