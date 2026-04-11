"""
Streaming AI completion — yields text chunks from providers in fallback order.

Used by the chat endpoint for SSE streaming.
Chain: Gemini → Groq → Cerebras → Mistral → DeepSeek → Sambanova.
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
CEREBRAS_URL = "https://api.cerebras.ai/v1/chat/completions"
MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
SAMBANOVA_URL = "https://api.sambanova.ai/v1/chat/completions"


async def stream_gemini(messages: list[dict]) -> AsyncGenerator[str, None]:
    """Stream text chunks from Gemini."""
    settings = get_settings()
    if not settings.gemini_api_key:
        yield "[AI not configured]"
        return

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
                raise Exception(f"Gemini stream error: {resp.status_code}")
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


async def _stream_openai_compat(
    url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    provider_name: str,
) -> AsyncGenerator[str, None]:
    """Stream from any OpenAI-compatible API (Groq, Cerebras, Mistral, DeepSeek, Sambanova)."""
    body = {
        "model": model,
        "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
        "temperature": 0.5,
        "max_tokens": 1024,
        "stream": True,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream(
            "POST", url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
        ) as resp:
            if resp.status_code != 200:
                raise Exception(f"{provider_name} stream error: {resp.status_code}")
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


async def stream_groq(messages: list[dict]) -> AsyncGenerator[str, None]:
    """Stream text chunks from Groq (OpenAI-compatible SSE)."""
    settings = get_settings()
    async for chunk in _stream_openai_compat(
        GROQ_URL, settings.groq_api_key, settings.groq_model, messages, "Groq"
    ):
        yield chunk


async def stream_cerebras(messages: list[dict]) -> AsyncGenerator[str, None]:
    """Stream text chunks from Cerebras."""
    settings = get_settings()
    async for chunk in _stream_openai_compat(
        CEREBRAS_URL, settings.cerebras_api_key, settings.cerebras_model, messages, "Cerebras"
    ):
        yield chunk


async def stream_mistral(messages: list[dict]) -> AsyncGenerator[str, None]:
    """Stream text chunks from Mistral."""
    settings = get_settings()
    async for chunk in _stream_openai_compat(
        MISTRAL_URL, settings.mistral_api_key, settings.mistral_model, messages, "Mistral"
    ):
        yield chunk


async def stream_deepseek(messages: list[dict]) -> AsyncGenerator[str, None]:
    """Stream text chunks from DeepSeek."""
    settings = get_settings()
    async for chunk in _stream_openai_compat(
        DEEPSEEK_URL, settings.deepseek_api_key, settings.deepseek_model, messages, "DeepSeek"
    ):
        yield chunk


async def stream_sambanova(messages: list[dict]) -> AsyncGenerator[str, None]:
    """Stream text chunks from Sambanova."""
    settings = get_settings()
    async for chunk in _stream_openai_compat(
        SAMBANOVA_URL, settings.sambanova_api_key, settings.sambanova_model, messages, "Sambanova"
    ):
        yield chunk


# Ordered list of streaming providers: (name, key_field, stream_fn)
_STREAM_PROVIDERS = [
    ("Gemini", "gemini_api_key", stream_gemini),
    ("Groq", "groq_api_key", stream_groq),
    ("Cerebras", "cerebras_api_key", stream_cerebras),
    ("Mistral", "mistral_api_key", stream_mistral),
    ("DeepSeek", "deepseek_api_key", stream_deepseek),
    ("Sambanova", "sambanova_api_key", stream_sambanova),
]


async def stream_complete(messages: list[dict]) -> AsyncGenerator[str, None]:
    """Stream from the best available provider with fallback through all configured providers."""
    settings = get_settings()

    for name, key_field, stream_fn in _STREAM_PROVIDERS:
        api_key = getattr(settings, key_field, "")
        if not api_key:
            continue

        try:
            async for chunk in stream_fn(messages):
                yield chunk
            return
        except Exception as e:
            logger.warning("%s stream failed (%s), trying next provider", name, e)

    yield "[AI temporarily unavailable — please try again later]"
