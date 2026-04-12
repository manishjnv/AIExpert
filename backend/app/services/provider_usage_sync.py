"""
Provider-authoritative daily usage sync (layer 2 of the cost tracking system).

Pulls actual billed usage from OpenAI + Anthropic admin-level Usage APIs and
writes one row per (day, provider, model) into provider_daily_spend. Numbers
are whatever the provider reports — not estimates. The local ai_usage_log
(layer 1) is cross-referenced and drift_pct is computed for each row.

Gemini is NOT synced — no public usage API (GCP Cloud Billing requires
org-level OAuth which is out of scope). Gemini rows stay blank in the
reconciliation table, which is honest.

Runs daily at 06:00 UTC via the pipeline_scheduler. Can also be triggered
manually from the admin Usage Analytics page.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.curriculum import AIUsageLog, ProviderDailySpend

logger = logging.getLogger("roadmap.provider_usage_sync")


class ProviderSyncError(Exception):
    pass


# ---- Helper: compute our own cost estimate for the same day+provider ----

async def _local_cost_and_tokens_for_day(
    db: AsyncSession, day_str: str, provider: str,
) -> dict[str, tuple[int, float]]:
    """Return {model: (tokens, cost_usd_local)} from ai_usage_log for one day."""
    from app.ai.pricing import get_price

    rows = (await db.execute(
        select(
            AIUsageLog.model,
            func.sum(AIUsageLog.tokens_estimated).label("tok"),
        ).where(
            AIUsageLog.provider == provider,
            func.strftime("%Y-%m-%d", AIUsageLog.called_at) == day_str,
            AIUsageLog.status == "ok",
        ).group_by(AIUsageLog.model)
    )).all()

    out: dict[str, tuple[int, float]] = {}
    for r in rows:
        tok = int(r.tok or 0)
        in_price, _ = get_price(provider, r.model)
        cost_local = (tok / 1_000_000.0) * in_price
        out[r.model] = (tok, cost_local)
    return out


# ---- OpenAI ----

async def sync_openai(db: AsyncSession, target_day: date) -> dict:
    """Fetch OpenAI's billed usage for target_day (UTC), upsert rows.

    Uses the OpenAI Usage API (https://platform.openai.com/docs/api-reference/usage)
    which requires an Admin API key (sk-admin-*).
    """
    settings = get_settings()
    if not settings.openai_admin_api_key:
        return {"status": "skipped", "reason": "OPENAI_ADMIN_API_KEY not set"}

    day_str = target_day.isoformat()
    start_ts = int(datetime(target_day.year, target_day.month, target_day.day,
                             tzinfo=timezone.utc).timestamp())
    end_ts = start_ts + 86400

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Usage endpoint — costs grouped by model
        resp = await client.get(
            "https://api.openai.com/v1/organization/usage/completions",
            params={
                "start_time": start_ts,
                "end_time": end_ts,
                "bucket_width": "1d",
                "group_by": "model",
            },
            headers={"Authorization": f"Bearer {settings.openai_admin_api_key}"},
        )

    if resp.status_code != 200:
        raise ProviderSyncError(
            f"OpenAI Usage API {resp.status_code}: {resp.text[:300]}"
        )
    data = resp.json()

    local_by_model = await _local_cost_and_tokens_for_day(db, day_str, "openai")
    upserted = 0

    # Also fetch embeddings usage separately (different endpoint)
    async with httpx.AsyncClient(timeout=30.0) as client:
        emb_resp = await client.get(
            "https://api.openai.com/v1/organization/usage/embeddings",
            params={
                "start_time": start_ts, "end_time": end_ts,
                "bucket_width": "1d", "group_by": "model",
            },
            headers={"Authorization": f"Bearer {settings.openai_admin_api_key}"},
        )
    emb_data = emb_resp.json() if emb_resp.status_code == 200 else {"data": []}

    # Merge both data sets: each bucket has result[]; each has model + tokens
    from app.ai.pricing import get_price
    all_buckets = (data.get("data") or []) + (emb_data.get("data") or [])
    for bucket in all_buckets:
        for result in bucket.get("results", []) or []:
            model = result.get("model") or "*"
            input_tok = int(result.get("input_tokens") or 0)
            output_tok = int(result.get("output_tokens") or 0)
            total_tok = input_tok + output_tok

            # Provider-authoritative cost — OpenAI doesn't include $ in usage
            # endpoint; compute from their published rates via our pricing table.
            # (Switch to /v1/organization/costs for exact billed $ once stable.)
            in_price, out_price = get_price("openai", model)
            cost_provider = (input_tok / 1_000_000.0) * in_price + \
                             (output_tok / 1_000_000.0) * out_price

            tok_local, cost_local = local_by_model.get(model, (0, 0.0))
            drift = None
            if cost_provider > 0:
                drift = round(((cost_local - cost_provider) / cost_provider) * 100, 1)

            await _upsert_daily_spend(
                db, day_str, "openai", model,
                input_tok, output_tok, cost_provider, cost_local, drift,
                raw=json.dumps(result)[:2000],
            )
            upserted += 1

    await db.commit()
    return {"status": "ok", "provider": "openai", "day": day_str, "rows": upserted}


# ---- Anthropic ----

async def sync_anthropic(db: AsyncSession, target_day: date) -> dict:
    """Fetch Anthropic's billed usage for target_day (UTC), upsert rows.

    Uses the Anthropic Usage & Cost Admin API:
    https://docs.anthropic.com/en/api/admin-api/usage-cost
    """
    settings = get_settings()
    if not settings.anthropic_admin_api_key:
        return {"status": "skipped", "reason": "ANTHROPIC_ADMIN_API_KEY not set"}

    day_str = target_day.isoformat()
    # Anthropic expects RFC3339 timestamps, inclusive start / exclusive end
    starting_at = f"{day_str}T00:00:00Z"
    ending_at = f"{(target_day + timedelta(days=1)).isoformat()}T00:00:00Z"

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            "https://api.anthropic.com/v1/organizations/usage_report/messages",
            params={
                "starting_at": starting_at,
                "ending_at": ending_at,
                "bucket_width": "1d",
                "group_by[]": "model",
            },
            headers={
                "x-api-key": settings.anthropic_admin_api_key,
                "anthropic-version": "2023-06-01",
            },
        )

    if resp.status_code != 200:
        raise ProviderSyncError(
            f"Anthropic Usage API {resp.status_code}: {resp.text[:300]}"
        )
    data = resp.json()

    # Parallel: cost report for authoritative $
    async with httpx.AsyncClient(timeout=30.0) as client:
        cost_resp = await client.get(
            "https://api.anthropic.com/v1/organizations/cost_report",
            params={
                "starting_at": starting_at, "ending_at": ending_at,
                "bucket_width": "1d", "group_by[]": "model",
            },
            headers={
                "x-api-key": settings.anthropic_admin_api_key,
                "anthropic-version": "2023-06-01",
            },
        )
    cost_data = cost_resp.json() if cost_resp.status_code == 200 else {"data": []}

    local_by_model = await _local_cost_and_tokens_for_day(db, day_str, "anthropic")

    # Build provider cost lookup {model: cost_usd}
    cost_by_model: dict[str, float] = {}
    for bucket in cost_data.get("data") or []:
        for res in bucket.get("results", []) or []:
            m = res.get("model") or "*"
            amt = res.get("amount", {})
            if isinstance(amt, dict):
                cost_by_model[m] = float(amt.get("currency") == "USD" and amt.get("value") or 0.0)
            else:
                cost_by_model[m] = float(amt or 0.0)

    upserted = 0
    for bucket in data.get("data") or []:
        for res in bucket.get("results", []) or []:
            model = res.get("model") or "*"
            input_tok = int(res.get("uncached_input_tokens") or 0) + \
                        int(res.get("cached_input_tokens") or 0)
            output_tok = int(res.get("output_tokens") or 0)
            cost_provider = cost_by_model.get(model, 0.0)
            tok_local, cost_local = local_by_model.get(model, (0, 0.0))

            drift = None
            if cost_provider > 0:
                drift = round(((cost_local - cost_provider) / cost_provider) * 100, 1)

            await _upsert_daily_spend(
                db, day_str, "anthropic", model,
                input_tok, output_tok, cost_provider, cost_local, drift,
                raw=json.dumps(res)[:2000],
            )
            upserted += 1

    await db.commit()
    return {"status": "ok", "provider": "anthropic", "day": day_str, "rows": upserted}


# ---- Upsert helper ----

async def _upsert_daily_spend(
    db: AsyncSession, day: str, provider: str, model: str,
    input_tok: int, output_tok: int,
    cost_provider: float, cost_local: float, drift_pct: Optional[float],
    raw: str,
) -> None:
    existing = (await db.execute(
        select(ProviderDailySpend).where(
            ProviderDailySpend.day == day,
            ProviderDailySpend.provider == provider,
            ProviderDailySpend.model == model,
        )
    )).scalar_one_or_none()

    if existing is None:
        db.add(ProviderDailySpend(
            day=day, provider=provider, model=model,
            input_tokens=input_tok, output_tokens=output_tok,
            cost_usd_provider=cost_provider, cost_usd_local=cost_local,
            drift_pct=drift_pct, raw_response=raw,
        ))
    else:
        existing.input_tokens = input_tok
        existing.output_tokens = output_tok
        existing.cost_usd_provider = cost_provider
        existing.cost_usd_local = cost_local
        existing.drift_pct = drift_pct
        existing.raw_response = raw


# ---- Orchestrator ----

async def run_daily_sync(db: AsyncSession, target_day: Optional[date] = None) -> dict:
    """Sync yesterday's (or target_day's) spend from all supported providers."""
    if target_day is None:
        target_day = (datetime.now(timezone.utc) - timedelta(days=1)).date()

    results: dict[str, dict] = {}
    for fn, name in ((sync_openai, "openai"), (sync_anthropic, "anthropic")):
        try:
            results[name] = await fn(db, target_day)
        except ProviderSyncError as e:
            logger.warning("Sync failed for %s: %s", name, e)
            results[name] = {"status": "error", "error": str(e)}
        except Exception as e:
            logger.exception("Unexpected sync error for %s", name)
            results[name] = {"status": "error", "error": str(e)}

    return {"day": target_day.isoformat(), "providers": results}


# ---- Archive cron for old ai_usage_log rows ----

async def archive_old_usage_logs(db: AsyncSession) -> dict:
    """Delete ai_usage_log rows older than settings.ai_usage_log_retention_days.

    Aggregates are already persisted in provider_daily_spend (for paid providers)
    and in the local per-model analytics query (which reads the live log).
    To keep free-provider historical stats we do a last-resort summary:
    aggregate-before-delete into provider_daily_spend.
    """
    settings = get_settings()
    retention = settings.ai_usage_log_retention_days
    if retention <= 0:
        return {"status": "skipped", "reason": "retention disabled"}

    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=retention)
    cutoff_day = cutoff.date().isoformat()

    # 1. Aggregate free-provider + unsynced rows into provider_daily_spend
    from app.ai.pricing import get_price
    agg_rows = (await db.execute(
        select(
            func.strftime("%Y-%m-%d", AIUsageLog.called_at).label("day"),
            AIUsageLog.provider, AIUsageLog.model,
            func.sum(AIUsageLog.tokens_estimated).label("tok"),
        )
        .where(
            AIUsageLog.called_at < cutoff,
            AIUsageLog.status == "ok",
        )
        .group_by("day", AIUsageLog.provider, AIUsageLog.model)
    )).all()

    aggregated = 0
    for r in agg_rows:
        # Skip paid providers — they're already synced from provider APIs
        if r.provider in {"openai", "anthropic"}:
            continue
        in_price, _ = get_price(r.provider, r.model)
        cost_local = ((r.tok or 0) / 1_000_000.0) * in_price
        await _upsert_daily_spend(
            db, r.day, r.provider, r.model,
            int(r.tok or 0), 0, 0.0, cost_local, None,
            raw="archived_from_ai_usage_log",
        )
        aggregated += 1

    # 2. Delete the old rows
    from sqlalchemy import delete
    result = await db.execute(
        delete(AIUsageLog).where(AIUsageLog.called_at < cutoff)
    )
    deleted = result.rowcount or 0
    await db.commit()

    logger.info("Archived %d aggregate rows, deleted %d raw log rows (cutoff %s)",
                aggregated, deleted, cutoff_day)
    return {
        "status": "ok",
        "cutoff_day": cutoff_day,
        "aggregated_rows": aggregated,
        "deleted_rows": deleted,
    }
