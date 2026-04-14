"""IndexNow — notify Bing/Yandex when a URL is published or updated.

One-shot POST per publish event. Fire-and-forget; failure never blocks publish.
No-op when indexnow_key is empty (dev). See docs/JOBS.md §7.5.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

import httpx

from app.config import get_settings

logger = logging.getLogger("roadmap.indexnow")

ENDPOINT = "https://api.indexnow.org/indexnow"


async def ping(urls: list[str]) -> None:
    """Notify IndexNow of 1-N URLs. Never raises."""
    settings = get_settings()
    key = settings.indexnow_key
    if not key or not urls:
        return

    base = (settings.public_base_url or "").rstrip("/")
    host = urlparse(base).hostname
    if not host:
        logger.warning("indexnow: could not parse host from public_base_url=%s", base)
        return

    payload = {
        "host": host,
        "key": key,
        "keyLocation": f"{base}/{key}.txt",
        "urlList": urls[:10000],
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(ENDPOINT, json=payload)
            if resp.status_code >= 400:
                logger.warning("indexnow returned %d: %s", resp.status_code, resp.text[:200])
            else:
                logger.info("indexnow: pinged %d urls", len(urls))
    except Exception as exc:
        logger.exception("indexnow ping failed: %s", exc)


def ping_async(urls: list[str]) -> None:
    """Fire-and-forget wrapper. Use from inside request handlers."""
    try:
        asyncio.create_task(ping(urls))
    except RuntimeError:
        # No running loop (unit test / sync context) — skip silently.
        pass
