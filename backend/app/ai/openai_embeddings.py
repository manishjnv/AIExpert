"""
OpenAI embeddings client — the ONLY approved use of OpenAI in this project.

Used for semantic topic deduplication in topic_discovery. We do NOT use
OpenAI for generation, review, refinement, chat, or evaluation — those
stages run on the free-tier fallback chain or Claude.

Rationale: text-embedding-3-small is best-in-class quality/$ for embeddings
($0.02 per 1M tokens). Gemini/Groq/etc. do not offer competitive embeddings.
"""

from __future__ import annotations

import hashlib
import logging
import math
import time
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.pricing import check_cost_limit, CostLimitExceeded
from app.config import get_settings

logger = logging.getLogger("roadmap.ai.openai_embeddings")


class OpenAIEmbeddingError(Exception):
    pass


def _cache_key(text: str, model: str) -> str:
    h = hashlib.sha256(f"{model}::{text}".encode("utf-8")).hexdigest()
    return h[:24]


async def embed(
    texts: list[str],
    *,
    db: Optional[AsyncSession] = None,
    task: str = "embedding",
    subtask: Optional[str] = None,
) -> list[list[float]]:
    """Embed a batch of texts. Returns one vector per input.

    - Caches per-text (SHA256) via ai_cache (embeddings are deterministic).
    - Enforces admin-configured daily cost cap (raises CostLimitExceeded).
    - Logs the call to ai_usage_log with task='embedding' when db is provided.
    """
    if not texts:
        return []

    settings = get_settings()
    if not settings.openai_api_key:
        raise OpenAIEmbeddingError("OPENAI_API_KEY not configured")

    model = settings.openai_embedding_model

    # Cost-limit gate (raises if today's spend ≥ configured cap)
    if db is not None:
        await check_cost_limit(db, "openai", model)

    # Cache lookup
    from app.services.ai_cache import cache_get, cache_set

    vectors: list[Optional[list[float]]] = []
    to_fetch_idx: list[int] = []
    to_fetch_texts: list[str] = []

    for i, t in enumerate(texts):
        cached = cache_get("embedding", _cache_key(t, model))
        if cached is not None and isinstance(cached, dict) and "v" in cached:
            vectors.append(list(cached["v"]))
        else:
            vectors.append(None)
            to_fetch_idx.append(i)
            to_fetch_texts.append(t)

    tokens_used = 0
    if to_fetch_texts:
        # Lazy import so the package is optional at runtime
        try:
            from openai import AsyncOpenAI
        except ImportError as e:
            raise OpenAIEmbeddingError("openai package not installed") from e

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        start = time.time()
        try:
            resp = await client.embeddings.create(model=model, input=to_fetch_texts)
        except Exception as e:
            latency = int((time.time() - start) * 1000)
            if db is not None:
                from app.ai.health import log_usage
                await log_usage(
                    db, "openai", model, task, "error",
                    subtask=subtask, error_message=str(e)[:500],
                    latency_ms=latency,
                )
            raise OpenAIEmbeddingError(f"OpenAI embeddings API error: {e}") from e

        latency = int((time.time() - start) * 1000)
        tokens_used = getattr(resp.usage, "total_tokens", 0) or 0

        for local_idx, item in enumerate(resp.data):
            global_idx = to_fetch_idx[local_idx]
            v = list(item.embedding)
            vectors[global_idx] = v
            cache_set(
                "embedding",
                _cache_key(to_fetch_texts[local_idx], model),
                {"v": v},
                ttl=86400 * 90,  # 90 days — embeddings are stable
            )

        if db is not None:
            from app.ai.health import log_usage
            await log_usage(
                db, "openai", model, task, "ok",
                subtask=subtask,
                tokens_estimated=tokens_used,
                latency_ms=latency,
            )

    return [v for v in vectors if v is not None]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Standard cosine similarity. Both vectors assumed non-empty and same length."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def pack_vector(v: list[float]) -> bytes:
    """Pack a float list into a compact bytes blob (float32)."""
    import struct
    return struct.pack(f"{len(v)}f", *v)


def unpack_vector(b: bytes) -> list[float]:
    import struct
    n = len(b) // 4
    return list(struct.unpack(f"{n}f", b))


__all__ = [
    "embed",
    "cosine_similarity",
    "pack_vector",
    "unpack_vector",
    "OpenAIEmbeddingError",
    "CostLimitExceeded",
]
