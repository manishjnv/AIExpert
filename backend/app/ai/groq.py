"""
Groq API client — free-tier LLaMA 3.3 70B.

Same interface as gemini.py for provider interchangeability.
"""

from __future__ import annotations

import json
import logging

import httpx

from app.config import get_settings

logger = logging.getLogger("roadmap.ai.groq")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqError(Exception):
    pass


class GroqRateLimited(Exception):
    pass


async def complete(prompt: str, *, json_response: bool = True) -> dict | str:
    """Call Groq and return the response.

    Same interface as gemini.complete().
    """
    settings = get_settings()
    if not settings.groq_api_key:
        raise GroqError("GROQ_API_KEY not configured")

    body = {
        "model": settings.groq_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 4096,
    }

    if json_response:
        body["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {settings.groq_api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        )

    if resp.status_code == 429:
        raise GroqRateLimited("Groq rate limited")
    if resp.status_code != 200:
        logger.error("Groq error %d: %s", resp.status_code, resp.text[:500])
        raise GroqError(f"Groq API error: {resp.status_code}")

    data = resp.json()
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise GroqError(f"Unexpected Groq response structure: {e}") from e

    if json_response:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise GroqError(f"Groq returned non-JSON: {text[:200]}")

    return text
