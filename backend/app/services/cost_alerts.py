"""
Proactive cost-tracking alerts.

Three rules, checked once per day by the pipeline scheduler:
  1. cap_breach    — a paid provider hit its daily cap (a call was blocked)
  2. balance_low   — balance < 30d-avg-spend × 15 days (runway < 2 weeks)
  3. pricing_drift — provider_daily_spend shows >20% delta between our
                     local cost estimate and the provider-reported cost

Alerts are deduped by (kind, key). Writing an alert that already exists
(and is unresolved) is a no-op. Resolution happens either manually (admin
clicks dismiss) or automatically if the condition clears on next check.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.pricing import get_price
from app.models.curriculum import (
    AdminAlert, AIUsageLog, ProviderBalance, ProviderDailySpend,
)

logger = logging.getLogger("roadmap.cost_alerts")


# Drift threshold (%) above which we alert
DRIFT_THRESHOLD_PCT = 20.0
# Balance low = runway < this many days at recent avg spend
RUNWAY_DAYS_WARN = 15
# Minimum meaningful daily spend to bother alerting on (avoid div-by-zero + noise)
MIN_DAILY_SPEND_USD = 0.01


async def _upsert_alert(
    db: AsyncSession, kind: str, key: str, severity: str, message: str,
) -> None:
    existing = (await db.execute(
        select(AdminAlert).where(AdminAlert.kind == kind, AdminAlert.key == key)
    )).scalar_one_or_none()
    if existing is None:
        db.add(AdminAlert(kind=kind, key=key, severity=severity, message=message))
    else:
        # If previously resolved, un-resolve and update the message
        existing.resolved_at = None
        existing.severity = severity
        existing.message = message


async def _auto_resolve_alert(db: AsyncSession, kind: str, key: str) -> None:
    """Mark an alert resolved if the condition no longer holds."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    existing = (await db.execute(
        select(AdminAlert).where(
            AdminAlert.kind == kind,
            AdminAlert.key == key,
            AdminAlert.resolved_at.is_(None),
        )
    )).scalar_one_or_none()
    if existing is not None:
        existing.resolved_at = now


# ---- Rule 1: cap breach ----

async def check_cap_breaches(db: AsyncSession) -> int:
    """Scan today's ai_usage_log for CostLimitExceeded error messages."""
    from app.models.curriculum import AICostLimit

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0, tzinfo=None
    )

    # Error messages from CostLimitExceeded look like:
    #   "Daily cost cap reached for anthropic: $0.51 / $0.50"
    rows = (await db.execute(
        select(AIUsageLog.provider, func.count().label("n"))
        .where(
            AIUsageLog.called_at >= today_start,
            AIUsageLog.error_message.like("%cost cap reached%"),
        )
        .group_by(AIUsageLog.provider)
    )).all()

    breached_providers = {r.provider for r in rows}

    # Alert on each provider with a breach
    for r in rows:
        await _upsert_alert(
            db, "cap_breach", r.provider, "critical",
            f"{r.provider}: {r.n} call(s) blocked today after hitting the daily cost cap. "
            f"Review caps or top up balance.",
        )

    # Auto-resolve cap_breach alerts for providers that had no breach today
    # (leave them resolved; they'll re-fire tomorrow if it happens again)
    all_caps = (await db.execute(select(AICostLimit.provider).distinct())).all()
    for (prov,) in all_caps:
        if prov not in breached_providers:
            await _auto_resolve_alert(db, "cap_breach", prov)

    return len(breached_providers)


# ---- Rule 2: balance low ----

async def check_balance_runway(db: AsyncSession) -> int:
    """Alert if balance_usd < avg daily spend × RUNWAY_DAYS_WARN."""
    thirty_days_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)

    # Compute 30d-avg daily spend per paid provider (from our local log)
    spend_rows = (await db.execute(
        select(AIUsageLog.provider, AIUsageLog.model,
                func.sum(AIUsageLog.tokens_estimated).label("tok"))
        .where(AIUsageLog.called_at >= thirty_days_ago, AIUsageLog.status == "ok")
        .group_by(AIUsageLog.provider, AIUsageLog.model)
    )).all()
    total_by_provider: dict[str, float] = {}
    for r in spend_rows:
        in_price, _ = get_price(r.provider, r.model)
        total_by_provider[r.provider] = total_by_provider.get(r.provider, 0.0) + \
            ((r.tok or 0) / 1_000_000.0) * in_price
    avg_daily_by_provider = {p: t / 30.0 for p, t in total_by_provider.items()}

    # Compare against stored balances (only paid providers have > 0 balance)
    balances = (await db.execute(select(ProviderBalance))).scalars().all()
    alerted = 0
    for b in balances:
        if b.balance_usd <= 0:
            continue
        avg_daily = avg_daily_by_provider.get(b.provider, 0.0)
        if avg_daily < MIN_DAILY_SPEND_USD:
            # No meaningful spend — auto-resolve any prior alert
            await _auto_resolve_alert(db, "balance_low", b.provider)
            continue
        runway_days = b.balance_usd / avg_daily
        if runway_days < RUNWAY_DAYS_WARN:
            severity = "critical" if runway_days < 5 else "warn"
            await _upsert_alert(
                db, "balance_low", b.provider, severity,
                f"{b.provider}: balance ${b.balance_usd:.2f} covers ~{runway_days:.1f} "
                f"days at current spend (${avg_daily:.4f}/day avg over last 30d). "
                f"Top up or lower daily cap.",
            )
            alerted += 1
        else:
            await _auto_resolve_alert(db, "balance_low", b.provider)

    return alerted


# ---- Rule 3: pricing drift ----

async def check_pricing_drift(db: AsyncSession) -> int:
    """Alert when local cost estimate diverges >20% from provider-reported cost."""
    thirty_days_ago_str = (datetime.now(timezone.utc) -
                            timedelta(days=30)).date().isoformat()

    rows = (await db.execute(
        select(ProviderDailySpend)
        .where(
            ProviderDailySpend.day >= thirty_days_ago_str,
            ProviderDailySpend.cost_usd_provider > 0.01,  # ignore noise
            ProviderDailySpend.drift_pct.is_not(None),
        )
    )).scalars().all()

    # Aggregate drift per (provider, model) — if most recent days show drift > threshold, alert
    latest_by_key: dict[tuple[str, str], ProviderDailySpend] = {}
    for r in rows:
        k = (r.provider, r.model)
        if k not in latest_by_key or r.day > latest_by_key[k].day:
            latest_by_key[k] = r

    alerted = 0
    for (provider, model), r in latest_by_key.items():
        key = f"{provider}:{model}"
        if r.drift_pct is not None and abs(r.drift_pct) > DRIFT_THRESHOLD_PCT:
            await _upsert_alert(
                db, "pricing_drift", key, "warn",
                f"{provider}/{model}: local estimate drifts {r.drift_pct:+.1f}% from "
                f"provider-reported cost on {r.day} (provider ${r.cost_usd_provider:.4f} "
                f"vs local ${r.cost_usd_local:.4f}). Check ai/pricing.py PRICING table "
                f"or token-capture logic.",
            )
            alerted += 1
        else:
            await _auto_resolve_alert(db, "pricing_drift", key)

    return alerted


# ---- Orchestrator ----

async def run_all_checks(db: AsyncSession) -> dict:
    """Run all three rules. Idempotent — safe to call repeatedly."""
    try:
        b = await check_cap_breaches(db)
        l = await check_balance_runway(db)
        p = await check_pricing_drift(db)
        await db.commit()
        return {"cap_breach": b, "balance_low": l, "pricing_drift": p}
    except Exception:
        await db.rollback()
        raise
