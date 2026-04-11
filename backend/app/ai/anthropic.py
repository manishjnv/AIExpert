"""
Anthropic Claude API client — for curriculum refinement only.

NOT in the general fallback chain. Called explicitly by the quality pipeline
for surgical fixes on broken curriculum weeks.

Uses the Messages API directly via httpx (no SDK dependency).
"""

from __future__ import annotations

import json
import logging

import httpx

from app.config import get_settings

logger = logging.getLogger("roadmap.ai.anthropic")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


class AnthropicError(Exception):
    pass


class AnthropicRateLimited(Exception):
    pass


async def complete(
    prompt: str,
    *,
    json_response: bool = True,
    max_tokens: int = 4096,
    system_prompt: str | None = None,
) -> dict | str:
    """Call Claude and return the response.

    Args:
        prompt: User message content
        json_response: Parse response as JSON
        max_tokens: Max output tokens
        system_prompt: Optional system prompt (cached via prompt caching for ~90% input discount)
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise AnthropicError("ANTHROPIC_API_KEY not configured")

    body = {
        "model": settings.anthropic_model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }

    # Prompt caching: system prompt marked with cache_control for 90% discount on repeated calls.
    # The system prompt (review/refine instructions) stays the same across templates,
    # only the user message (specific curriculum) changes.
    if system_prompt:
        body["system"] = [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            ANTHROPIC_URL,
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json=body,
        )

    if resp.status_code == 429:
        raise AnthropicRateLimited("Claude rate limited")
    if resp.status_code != 200:
        logger.error("Claude error %d: %s", resp.status_code, resp.text[:500])
        raise AnthropicError(f"Claude API error: {resp.status_code}")

    data = resp.json()
    try:
        text = data["content"][0]["text"]
    except (KeyError, IndexError) as e:
        raise AnthropicError(f"Unexpected Claude response structure: {e}") from e

    if json_response:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try extracting from markdown code blocks
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
            raise AnthropicError(f"Claude returned non-JSON: {text[:200]}")

    return text
