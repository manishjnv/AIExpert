"""
Background scheduler for the auto-curriculum pipeline.

Runs discovery, generation, and refresh on configured schedules.
Uses simple sleep-based scheduling (no external dependencies needed).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.curriculum import CurriculumSettings

logger = logging.getLogger("roadmap.pipeline_scheduler")

# Check schedule every 6 hours
CHECK_INTERVAL = 6 * 3600

FREQUENCY_DAYS = {
    "weekly": 7,
    "monthly": 30,
    "quarterly": 90,
}


async def pipeline_scheduler(session_factory: async_sessionmaker) -> None:
    """Background task that checks if pipeline jobs need to run.

    Runs periodically, checks configured frequencies vs last-run timestamps,
    and triggers discovery/generation/refresh as needed.
    """
    logger.info("Pipeline scheduler started (check interval: %ds)", CHECK_INTERVAL)

    while True:
        await asyncio.sleep(CHECK_INTERVAL)

        try:
            async with session_factory() as db:
                try:
                    result = await db.execute(select(CurriculumSettings).limit(1))
                    settings = result.scalar_one_or_none()
                    if settings is None:
                        continue  # no settings configured yet

                    now = datetime.now(timezone.utc).replace(tzinfo=None)

                    # Check discovery schedule
                    discovery_days = FREQUENCY_DAYS.get(settings.discovery_frequency, 30)
                    if settings.last_discovery_run is None or \
                       (now - settings.last_discovery_run) > timedelta(days=discovery_days):
                        logger.info("Scheduled discovery run triggered")
                        from app.services.topic_discovery import run_discovery
                        result = await run_discovery(db)
                        logger.info("Scheduled discovery result: %s", result.get("status"))

                        # Auto-generate if enabled and topics were approved
                        if settings.auto_generate_variants and result.get("saved", 0) > 0:
                            from app.services.batch_generator import run_batch_generation
                            gen_result = await run_batch_generation(db)
                            logger.info("Auto-generation result: %s", gen_result.get("status"))

                    # Check refresh schedule
                    refresh_days = FREQUENCY_DAYS.get(settings.refresh_frequency, 90)
                    if settings.last_refresh_run is None or \
                       (now - settings.last_refresh_run) > timedelta(days=refresh_days):
                        logger.info("Scheduled content refresh triggered")
                        from app.services.content_refresh import run_content_refresh
                        refresh_result = await run_content_refresh(db)
                        logger.info("Scheduled refresh result: %s", refresh_result.get("status"))

                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise
        except asyncio.CancelledError:
            logger.info("Pipeline scheduler cancelled")
            return
        except Exception as e:
            logger.error("Pipeline scheduler error: %s", e, exc_info=True)
            # Continue running — don't crash the scheduler on transient errors
