"""
DeepSeek API client — strong reasoning, OpenAI-compatible.

Same interface as gemini.py/groq.py for provider interchangeability.
"""

from __future__ import annotations

import json
import logging

import httpx

from app.config import get_settings

logger = logging.getLogger("roadmap.ai.deepseek")

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"


class DeepSeekError(Exception):
    pass


class DeepSeekRateLimited(Exception):
    pass


async def complete(prompt: str, *, json_response: bool = True) -> dict | str:
    """Call DeepSeek and return the response.

    Same interface as gemini.complete() / groq.complete().
    """
    settings = get_settings()
    if not settings.deepseek_api_key:
        raise DeepSeekError("DEEPSEEK_API_KEY not configured")

    body = {
        "model": settings.deepseek_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 4096,
    }

    if json_response:
        body["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            DEEPSEEK_URL,
            headers={
                "Authorization": f"Bearer {settings.deepseek_api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        )

    if resp.status_code == 429:
        raise DeepSeekRateLimited("DeepSeek rate limited")
    if resp.status_code != 200:
        logger.error("DeepSeek error %d: %s", resp.status_code, resp.text[:500])
        raise DeepSeekError(f"DeepSeek API error: {resp.status_code}")

    data = resp.json()
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise DeepSeekError(f"Unexpected DeepSeek response structure: {e}") from e

    if json_response:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise DeepSeekError(f"DeepSeek returned non-JSON: {text[:200]}")

    return text
