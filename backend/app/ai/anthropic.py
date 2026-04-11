"""
Anthropic Claude API client — for curriculum refinement only.

NOT in the general fallback chain. Called explicitly by the quality pipeline
for surgical fixes on broken curriculum weeks.

Uses the Messages API directly via httpx (no SDK dependency).

Batch API: For bulk operations (5+ items), use create_batch() + poll_batch()
for 50% cost discount. Batches complete within 24h (usually minutes for small jobs).
"""

from __future__ import annotations

import json
import logging

import httpx

from app.config import get_settings

logger = logging.getLogger("roadmap.ai.anthropic")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_BATCH_URL = "https://api.anthropic.com/v1/messages/batches"


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


# ---- Batch API (50% discount for bulk operations) ----


async def create_batch(
    requests: list[dict],
) -> str:
    """Submit a batch of message requests for 50% cost discount.

    Args:
        requests: List of dicts, each with:
            - custom_id: str (your identifier to match results)
            - prompt: str (user message)
            - system_prompt: str | None (system message, cached)
            - max_tokens: int (default 4096)

    Returns:
        batch_id: str — use with poll_batch() / get_batch_results()
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise AnthropicError("ANTHROPIC_API_KEY not configured")

    batch_requests = []
    for req in requests:
        body = {
            "model": settings.anthropic_model,
            "max_tokens": req.get("max_tokens", 4096),
            "messages": [{"role": "user", "content": req["prompt"]}],
            "temperature": 0.3,
        }
        if req.get("system_prompt"):
            body["system"] = [
                {
                    "type": "text",
                    "text": req["system_prompt"],
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        batch_requests.append({
            "custom_id": req["custom_id"],
            "params": body,
        })

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            ANTHROPIC_BATCH_URL,
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={"requests": batch_requests},
        )

    if resp.status_code not in (200, 201):
        raise AnthropicError(f"Batch creation failed: {resp.status_code} {resp.text[:300]}")

    data = resp.json()
    batch_id = data["id"]
    logger.info("Created batch %s with %d requests", batch_id, len(requests))
    return batch_id


async def poll_batch(batch_id: str) -> dict:
    """Check batch status.

    Returns dict with:
        - status: "in_progress" | "ended" | "canceling" | "canceled" | "expired"
        - counts: {processing, succeeded, errored, canceled, expired}
        - results_url: str | None (available when ended)
    """
    settings = get_settings()
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{ANTHROPIC_BATCH_URL}/{batch_id}",
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
            },
        )

    if resp.status_code != 200:
        raise AnthropicError(f"Batch poll failed: {resp.status_code}")

    data = resp.json()
    return {
        "status": data.get("processing_status", "unknown"),
        "counts": data.get("request_counts", {}),
        "results_url": data.get("results_url"),
    }


async def get_batch_results(batch_id: str) -> list[dict]:
    """Fetch completed batch results.

    Returns list of dicts with:
        - custom_id: str
        - result: parsed JSON or raw text
        - error: str | None
    """
    settings = get_settings()

    # Get the results URL
    status = await poll_batch(batch_id)
    if status["status"] != "ended":
        raise AnthropicError(f"Batch not complete: {status['status']}")

    results_url = status.get("results_url")
    if not results_url:
        raise AnthropicError("No results URL available")

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(
            results_url,
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
            },
        )

    if resp.status_code != 200:
        raise AnthropicError(f"Batch results fetch failed: {resp.status_code}")

    # Results are JSONL (one JSON object per line)
    results = []
    for line in resp.text.strip().split("\n"):
        if not line.strip():
            continue
        entry = json.loads(line)
        custom_id = entry.get("custom_id", "")
        result_data = entry.get("result", {})

        if result_data.get("type") == "succeeded":
            message = result_data.get("message", {})
            try:
                text = message["content"][0]["text"]
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    parsed = text
                results.append({"custom_id": custom_id, "result": parsed, "error": None})
            except (KeyError, IndexError):
                results.append({"custom_id": custom_id, "result": None, "error": "Parse error"})
        else:
            error_msg = result_data.get("error", {}).get("message", "Unknown error")
            results.append({"custom_id": custom_id, "result": None, "error": error_msg})

    logger.info("Batch %s: %d results fetched", batch_id, len(results))
    return results
