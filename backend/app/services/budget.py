"""
Token budget enforcement for AI calls.

Per AI Enrichment Blueprint: every LLM call must be preceded by a budget check.
Three-tier system: <80% normal, 80-90% warning, 90-100% fallback, >=100% hard stop.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.curriculum import CurriculumSettings

logger = logging.getLogger("roadmap.budget")


class BudgetExceeded(Exception):
    """Token budget for this month has been fully consumed."""
    pass


class BudgetWarning(Exception):
    """Token budget is running low (80-90%)."""
    pass


async def get_settings(db: AsyncSession) -> CurriculumSettings:
    """Get or create the singleton CurriculumSettings row."""
    result = await db.execute(select(CurriculumSettings).limit(1))
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = CurriculumSettings()
        db.add(settings)
        await db.flush()
    return settings


async def check_budget(db: AsyncSession) -> tuple[str, float]:
    """Check token budget before an AI call.

    Returns (status, used_pct) where status is one of:
    - "ok": <80% used, proceed normally
    - "warning": 80-90% used, use default model but emit warning
    - "fallback": 90-100% used, switch to cheaper model
    - "exceeded": >=100% used, hard stop

    Raises BudgetExceeded if budget is fully consumed.
    """
    settings = await get_settings(db)
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")

    # Reset counter if new month
    if settings.budget_month != current_month:
        settings.tokens_used_this_month = 0
        settings.budget_month = current_month
        await db.flush()

    if settings.max_tokens_per_run == 0:
        return "ok", 0.0

    used_pct = (settings.tokens_used_this_month / settings.max_tokens_per_run) * 100

    if used_pct >= 100:
        logger.error("Budget exceeded: %.1f%% (%d/%d tokens)",
                      used_pct, settings.tokens_used_this_month, settings.max_tokens_per_run)
        raise BudgetExceeded(
            f"Monthly token budget exceeded ({settings.tokens_used_this_month}/{settings.max_tokens_per_run})"
        )
    elif used_pct >= 90:
        logger.warning("Budget fallback zone: %.1f%%", used_pct)
        return "fallback", used_pct
    elif used_pct >= 80:
        logger.warning("Budget warning: %.1f%%", used_pct)
        return "warning", used_pct
    else:
        return "ok", used_pct


async def track_tokens(db: AsyncSession, tokens_used: int) -> None:
    """Record token usage after an AI call."""
    settings = await get_settings(db)
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")

    if settings.budget_month != current_month:
        settings.tokens_used_this_month = 0
        settings.budget_month = current_month

    settings.tokens_used_this_month += tokens_used
    await db.flush()
    logger.info("Tracked %d tokens (total this month: %d/%d)",
                tokens_used, settings.tokens_used_this_month, settings.max_tokens_per_run)
