"""
Gemini API client — free-tier Gemini 1.5 Flash.

Uses the REST API directly via httpx (no SDK dependency).
"""

from __future__ import annotations

import json
import logging

import httpx

from app.config import get_settings

logger = logging.getLogger("roadmap.ai.gemini")

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiError(Exception):
    pass


class GeminiRateLimited(Exception):
    pass


async def complete(prompt: str, *, json_response: bool = True) -> dict | str:
    """Call Gemini and return the response.

    Args:
        prompt: The prompt text.
        json_response: If True, parse the response as JSON.

    Returns:
        Parsed JSON dict or raw text string.

    Raises:
        GeminiRateLimited: on 429
        GeminiError: on other failures
    """
    settings = get_settings()
    if not settings.gemini_api_key:
        raise GeminiError("GEMINI_API_KEY not configured")

    url = GEMINI_URL.format(model=settings.gemini_model)
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 2048,
        },
    }

    if json_response:
        body["generationConfig"]["responseMimeType"] = "application/json"

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            url,
            params={"key": settings.gemini_api_key},
            json=body,
        )

    if resp.status_code == 429:
        raise GeminiRateLimited("Gemini rate limited")
    if resp.status_code != 200:
        logger.error("Gemini error %d: %s", resp.status_code, resp.text[:500])
        raise GeminiError(f"Gemini API error: {resp.status_code}")

    data = resp.json()
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise GeminiError(f"Unexpected Gemini response structure: {e}") from e

    if json_response:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code blocks
            if "```json" in text:
                text = text.split("```json", 1)[1].split("```", 1)[0].strip()
                return json.loads(text)
            raise GeminiError(f"Gemini returned non-JSON: {text[:200]}")

    return text
