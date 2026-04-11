"""
Sambanova API client — fast inference on Llama models, OpenAI-compatible.

Same interface as gemini.py/groq.py for provider interchangeability.
"""

from __future__ import annotations

import json
import logging

import httpx

from app.config import get_settings

logger = logging.getLogger("roadmap.ai.sambanova")

SAMBANOVA_URL = "https://api.sambanova.ai/v1/chat/completions"


class SambanovaError(Exception):
    pass


class SambanovaRateLimited(Exception):
    pass


async def complete(prompt: str, *, json_response: bool = True) -> dict | str:
    """Call Sambanova and return the response.

    Same interface as gemini.complete() / groq.complete().
    """
    settings = get_settings()
    if not settings.sambanova_api_key:
        raise SambanovaError("SAMBANOVA_API_KEY not configured")

    body = {
        "model": settings.sambanova_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 2048,
    }

    if json_response:
        body["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            SAMBANOVA_URL,
            headers={
                "Authorization": f"Bearer {settings.sambanova_api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        )

    if resp.status_code == 429:
        raise SambanovaRateLimited("Sambanova rate limited")
    if resp.status_code != 200:
        logger.error("Sambanova error %d: %s", resp.status_code, resp.text[:500])
        raise SambanovaError(f"Sambanova API error: {resp.status_code}")

    data = resp.json()
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise SambanovaError(f"Unexpected Sambanova response structure: {e}") from e

    if json_response:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise SambanovaError(f"Sambanova returned non-JSON: {text[:200]}")

    return text
