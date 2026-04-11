"""
Mistral API client — good for classification tasks, OpenAI-compatible.

Same interface as gemini.py/groq.py for provider interchangeability.
"""

from __future__ import annotations

import json
import logging

import httpx

from app.config import get_settings

logger = logging.getLogger("roadmap.ai.mistral")

MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"


class MistralError(Exception):
    pass


class MistralRateLimited(Exception):
    pass


async def complete(prompt: str, *, json_response: bool = True) -> dict | str:
    """Call Mistral and return the response.

    Same interface as gemini.complete() / groq.complete().
    """
    settings = get_settings()
    if not settings.mistral_api_key:
        raise MistralError("MISTRAL_API_KEY not configured")

    body = {
        "model": settings.mistral_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 8192,
    }

    if json_response:
        body["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            MISTRAL_URL,
            headers={
                "Authorization": f"Bearer {settings.mistral_api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        )

    if resp.status_code == 429:
        raise MistralRateLimited("Mistral rate limited")
    if resp.status_code != 200:
        logger.error("Mistral error %d: %s", resp.status_code, resp.text[:500])
        raise MistralError(f"Mistral API error: {resp.status_code}")

    data = resp.json()
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise MistralError(f"Unexpected Mistral response structure: {e}") from e

    if json_response:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Mistral sometimes wraps JSON in markdown code blocks
            if "```json" in text:
                text = text.split("```json", 1)[1].split("```", 1)[0].strip()
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    pass
            elif "```" in text:
                text = text.split("```", 1)[1].split("```", 1)[0].strip()
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    pass
            raise MistralError(f"Mistral returned non-JSON: {text[:200]}")

    return text
