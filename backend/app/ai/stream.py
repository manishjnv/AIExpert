"""
Streaming AI completion — yields text chunks from Gemini (or Groq fallback).

Used by the chat endpoint for SSE streaming.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator

import httpx

from app.config import get_settings

logger = logging.getLogger("roadmap.ai.stream")

GEMINI_STREAM_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent"
)
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


async def stream_gemini(messages: list[dict]) -> AsyncGenerator[str, None]:
    """Stream text chunks from Gemini.

    Args:
        messages: list of {"role": "user"|"model", "content": "..."}
    """
    settings = get_settings()
    if not settings.gemini_api_key:
        yield "[AI not configured]"
        return

    # Convert messages to Gemini format
    contents = []
    for m in messages:
        role = "model" if m["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})

    url = GEMINI_STREAM_URL.format(model=settings.gemini_model)
    body = {
        "contents": contents,
        "generationConfig": {"temperature": 0.5, "maxOutputTokens": 1024},
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream(
            "POST", url, params={"key": settings.gemini_api_key, "alt": "sse"}, json=body,
        ) as resp:
            if resp.status_code != 200:
                yield "[AI error — try again]"
                return
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    text = chunk["candidates"][0]["content"]["parts"][0]["text"]
                    yield text
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue


async def stream_groq(messages: list[dict]) -> AsyncGenerator[str, None]:
    """Stream text chunks from Groq (OpenAI-compatible SSE)."""
    settings = get_settings()
    if not settings.groq_api_key:
        yield "[AI not configured]"
        return

    body = {
        "model": settings.groq_model,
        "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
        "temperature": 0.5,
        "max_tokens": 1024,
        "stream": True,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream(
            "POST", GROQ_URL,
            headers={"Authorization": f"Bearer {settings.groq_api_key}", "Content-Type": "application/json"},
            json=body,
        ) as resp:
            if resp.status_code != 200:
                yield "[AI error — try again]"
                return
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk["choices"][0]["delta"]
                    text = delta.get("content", "")
                    if text:
                        yield text
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue


async def stream_complete(messages: list[dict]) -> AsyncGenerator[str, None]:
    """Stream from the best available provider (Gemini first, Groq fallback)."""
    settings = get_settings()

    if settings.gemini_api_key:
        try:
            async for chunk in stream_gemini(messages):
                yield chunk
            return
        except Exception:
            logger.warning("Gemini stream failed, falling back to Groq")

    if settings.groq_api_key:
        async for chunk in stream_groq(messages):
            yield chunk
        return

    yield "[No AI provider configured]"
