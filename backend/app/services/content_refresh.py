"""
Content refresh service — checks existing templates for staleness.

Per Normalization Blueprint:
- Lifecycle state machine for template versions
- Idempotent operations: safe to re-run

Per AI Enrichment Blueprint:
- Cache-first, budget-gated, schema-enforced
- AI reviews topic currency
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import ipaddress
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.curriculum import CurriculumSettings, LinkHealth
from app.services.ai_cache import cache_get, cache_set
from app.services.budget import BudgetExceeded, check_budget, track_tokens

logger = logging.getLogger("roadmap.refresh")

REVIEW_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "review_currency.txt"
TEMPLATES_DIR = Path(__file__).parent.parent / "curriculum" / "templates"

REVIEW_TOKENS_ESTIMATE = 1500
LINK_CHECK_TIMEOUT = 10  # seconds

# SSRF protection: block internal/metadata IPs
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local / cloud metadata
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _is_safe_url(url: str) -> bool:
    """Check if a URL is safe for outbound requests (no SSRF)."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        # Block common metadata hostnames
        blocked_hosts = {"metadata.google.internal", "metadata.google", "instance-data"}
        if hostname in blocked_hosts:
            return False
        # Try to parse as IP and check against blocked ranges
        try:
            addr = ipaddress.ip_address(hostname)
            for net in _BLOCKED_NETWORKS:
                if addr in net:
                    return False
        except ValueError:
            pass  # hostname, not IP — allowed
        return True
    except Exception:
        return False


class CurrencyReviewSchema(BaseModel):
    """Schema for AI currency review response."""
    is_current: bool
    currency_score: int = Field(ge=0, le=100)
    issues: list[str] = []
    suggestions: list[str] = []
    reason: str


async def check_link_health(db: AsyncSession) -> dict:
    """Check all resource URLs across all templates for broken links.

    Updates LinkHealth table with results.
    """
    from app.curriculum.loader import list_templates, load_template

    keys = list_templates()
    total_checked = 0
    total_broken = 0
    total_ok = 0

    async with httpx.AsyncClient(
        timeout=LINK_CHECK_TIMEOUT,
        follow_redirects=False,  # disable redirect following to prevent SSRF via redirect
        headers={"User-Agent": "AIRoadmap-LinkChecker/1.0"},
    ) as client:
        for key in keys:
            try:
                tpl = load_template(key)
            except Exception:
                continue

            for month in tpl.months:
                for week in month.weeks:
                    for idx, resource in enumerate(week.resources):
                        url = resource.url
                        if not url or not url.startswith("http"):
                            continue
                        if not _is_safe_url(url):
                            logger.warning("Skipping unsafe URL: %s", url)
                            continue

                        # Check or create LinkHealth record
                        result = await db.execute(
                            select(LinkHealth).where(
                                LinkHealth.template_key == key,
                                LinkHealth.week_num == week.n,
                                LinkHealth.resource_idx == idx,
                            )
                        )
                        health = result.scalar_one_or_none()
                        if health is None:
                            health = LinkHealth(
                                template_key=key,
                                week_num=week.n,
                                resource_idx=idx,
                                url=url,
                            )
                            db.add(health)

                        # HTTP HEAD check
                        try:
                            resp = await client.head(url)
                            health.last_status = resp.status_code
                            health.last_checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
                            if resp.status_code >= 400:  # 3xx is OK (redirects disabled)
                                health.consecutive_failures += 1
                                total_broken += 1
                            else:
                                health.consecutive_failures = 0
                                total_ok += 1
                        except httpx.HTTPError:
                            health.consecutive_failures += 1
                            health.last_checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
                            total_broken += 1

                        total_checked += 1

        await db.flush()

    summary = {
        "total_checked": total_checked,
        "ok": total_ok,
        "broken": total_broken,
    }
    logger.info("Link health check complete: %s", summary)
    return summary


async def review_template_currency(
    template_key: str,
    db: AsyncSession,
) -> dict | None:
    """AI reviews whether a template's content is still current.

    Returns review result or None if skipped.
    """
    from app.curriculum.loader import load_template

    try:
        tpl = load_template(template_key)
    except FileNotFoundError:
        return None

    # Budget check
    try:
        await check_budget(db)
    except BudgetExceeded:
        return None

    # Cache check
    cache_params = f"review:{template_key}"
    cached = cache_get("currency_review", cache_params)
    if cached is not None:
        try:
            return CurrencyReviewSchema(**cached).model_dump()
        except Exception:
            pass

    # Count dead links for this template
    dead_count = 0
    result = await db.execute(
        select(LinkHealth).where(
            LinkHealth.template_key == template_key,
            LinkHealth.consecutive_failures > 2,
        )
    )
    dead_count = len(result.scalars().all())

    # Gather sample resources — sanitize to prevent prompt injection
    sample_resources = []
    for month in tpl.months[:2]:  # first 2 months only to limit prompt size
        for week in month.weeks[:2]:
            for r in week.resources:
                safe_name = r.name[:100].replace("\n", " ")
                safe_url = r.url[:200].replace("\n", " ") if r.url else ""
                sample_resources.append(f"- {safe_name}: {safe_url}")
    resources_str = "\n".join(sample_resources[:10])

    # Build prompt — truncate template-sourced strings
    prompt_template = REVIEW_PROMPT_PATH.read_text(encoding="utf-8")
    prompt = prompt_template.format(
        topic_title=tpl.title[:100].replace("\n", " "),
        level=tpl.level[:30].replace("\n", " "),
        created_date="unknown",
        dead_link_count=dead_count,
        sample_resources=resources_str,
    )

    try:
        from app.ai.provider import complete as ai_complete
        raw_result, model_used = await ai_complete(prompt, json_response=True)
        await track_tokens(db, REVIEW_TOKENS_ESTIMATE)

        if isinstance(raw_result, str):
            raw_result = json.loads(raw_result)

        validated = CurrencyReviewSchema(**raw_result)
        cache_set("currency_review", cache_params, raw_result, ttl=86400 * 7)

        return validated.model_dump()

    except Exception as e:
        logger.error("Currency review failed for %s: %s", template_key, e)
        return None


async def run_content_refresh(db: AsyncSession) -> dict:
    """Run full content refresh: link checks + currency reviews.

    Returns summary of all checks.
    """
    from app.curriculum.loader import list_templates
    from app.services.budget import get_settings as get_budget_settings

    settings = await get_budget_settings(db)

    logger.info("Starting content refresh")

    # 1. Link health checks
    link_results = await check_link_health(db)

    # 2. AI currency review for each template
    reviews = {}
    auto_unpublished = []
    keys = list_templates()
    for key in keys:
        review = await review_template_currency(key, db)
        if review:
            reviews[key] = review

            # Auto-unpublish templates with low currency score
            from app.curriculum.loader import get_template_status, unpublish_template
            CURRENCY_UNPUBLISH_THRESHOLD = 40
            status_info = get_template_status(key)
            if (status_info.get("status") == "published"
                    and review.get("currency_score", 100) < CURRENCY_UNPUBLISH_THRESHOLD):
                unpublish_template(key)
                auto_unpublished.append(key)
                logger.warning(
                    "Auto-unpublished %s: currency score %d < %d",
                    key, review["currency_score"], CURRENCY_UNPUBLISH_THRESHOLD,
                )

    # Update last run timestamp
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    settings.last_refresh_run = now
    await db.flush()

    summary = {
        "status": "ok",
        "link_health": link_results,
        "currency_reviews": reviews,
        "templates_reviewed": len(reviews),
        "auto_unpublished": auto_unpublished,
    }
    logger.info("Content refresh complete: %d links checked, %d templates reviewed, %d auto-unpublished",
                link_results["total_checked"], len(reviews), len(auto_unpublished))
    return summary
