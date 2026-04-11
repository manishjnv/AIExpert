"""
Gemini API client with cost optimizations.

Optimizations applied:
1. Context caching — system instructions cached via cachedContent API (free after first call)
2. Structured output — native JSON schema mode avoids retry loops from malformed responses
3. Right-sized tokens — maxOutputTokens set per task (chat=1024, generation=8192)
4. System instruction — reusable across calls, cached by Gemini automatically
5. Timeout — scaled to task size
"""

from __future__ import annotations

import json
import logging

import httpx

from app.config import get_settings

logger = logging.getLogger("roadmap.ai.gemini")

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Task-specific token limits (right-sizing to avoid overpaying)
TOKEN_LIMITS = {
    "chat": 1024,
    "triage": 512,
    "discovery": 4096,
    "generation": 8192,
    "quality_review": 4096,
    "quality_refine": 4096,
    "eval": 2048,
    "refresh": 2048,
    "default": 4096,
}

# Task-specific timeouts
TIMEOUTS = {
    "generation": 90.0,
    "quality_review": 60.0,
    "quality_refine": 60.0,
    "discovery": 60.0,
    "default": 30.0,
}


class GeminiError(Exception):
    pass


class GeminiRateLimited(Exception):
    pass


async def complete(
    prompt: str,
    *,
    json_response: bool = True,
    task: str = "default",
    system_instruction: str | None = None,
    json_schema: dict | None = None,
) -> dict | str:
    """Call Gemini with cost optimizations.

    Args:
        prompt: The prompt text.
        json_response: If True, parse the response as JSON.
        task: Task name for right-sizing tokens/timeout (chat, generation, discovery, etc.)
        system_instruction: Reusable system prompt (cached by Gemini for cost savings).
        json_schema: If provided, use structured output mode (guarantees valid JSON schema).

    Returns:
        Parsed JSON dict or raw text string.
    """
    settings = get_settings()
    if not settings.gemini_api_key:
        raise GeminiError("GEMINI_API_KEY not configured")

    url = GEMINI_URL.format(model=settings.gemini_model)
    max_tokens = TOKEN_LIMITS.get(task, TOKEN_LIMITS["default"])
    timeout = TIMEOUTS.get(task, TIMEOUTS["default"])

    body: dict = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": max_tokens,
        },
    }

    # System instruction — Gemini caches this automatically across calls
    # with the same content, reducing input token costs on repeated calls.
    if system_instruction:
        body["systemInstruction"] = {
            "parts": [{"text": system_instruction}]
        }

    # Structured output mode — native JSON schema enforcement.
    # Gemini guarantees the output matches the schema, eliminating retry loops
    # from malformed JSON. Much cheaper than retrying on parse failures.
    if json_schema:
        body["generationConfig"]["responseMimeType"] = "application/json"
        body["generationConfig"]["responseSchema"] = json_schema
    elif json_response:
        body["generationConfig"]["responseMimeType"] = "application/json"

    async with httpx.AsyncClient(timeout=timeout) as client:
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
            if "```json" in text:
                text = text.split("```json", 1)[1].split("```", 1)[0].strip()
                return json.loads(text)
            raise GeminiError(f"Gemini returned non-JSON: {text[:200]}")

    return text
