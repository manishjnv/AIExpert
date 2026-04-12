"""
Central AI pricing table + cost computation.

Prices in USD per 1,000,000 tokens. Free-tier providers are priced at 0.
Used by the AI Usage admin dashboard and daily cost-limit enforcement.

Update when providers change pricing. Source of truth for every cost cell
shown in the admin UI.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession


# (input_price_per_1M, output_price_per_1M) in USD
# Free tier entries are (0.0, 0.0) — we still log tokens for visibility.
PRICING: dict[tuple[str, str], tuple[float, float]] = {
    # ---- Free-tier providers (zero cost — no billing account attached) ----
    ("groq", "*"): (0.0, 0.0),
    ("cerebras", "*"): (0.0, 0.0),
    ("mistral", "*"): (0.0, 0.0),
    ("sambanova", "*"): (0.0, 0.0),
    ("deepseek", "*"): (0.0, 0.0),

    # ---- Gemini (paid tier, billing enabled with ₹1000 credit) ----
    # Free tier still applies first — paid pricing kicks in after daily quota.
    # Numbers shown are the paid-tier list prices ($/1M tokens).
    ("gemini", "gemini-2.5-flash"): (0.075, 0.30),
    ("gemini", "gemini-2.5-pro"): (1.25, 5.00),
    ("gemini", "gemini-1.5-flash"): (0.075, 0.30),
    ("gemini", "gemini-2.0-flash-lite"): (0.075, 0.30),
    ("gemini", "*"): (0.075, 0.30),

    # ---- Paid providers ----
    # Anthropic Claude Sonnet 4.x ($3 in / $15 out per 1M)
    ("anthropic", "claude-sonnet-4-6"): (3.00, 15.00),
    ("anthropic", "claude-sonnet-4-5"): (3.00, 15.00),
    ("anthropic", "claude-haiku-4-5-20251001"): (0.80, 4.00),
    ("anthropic", "*"): (3.00, 15.00),  # default to Sonnet pricing

    # OpenAI embeddings (no output tokens)
    ("openai", "text-embedding-3-small"): (0.02, 0.0),
    ("openai", "text-embedding-3-large"): (0.13, 0.0),
    ("openai", "*"): (0.02, 0.0),
}


# Admin reference info — shown in the Daily Cost Caps section. Edit when
# credits are topped up or caps are re-tuned. Not used for enforcement —
# enforcement reads ai_cost_limit rows set by the admin UI.
PROVIDER_INFO: dict[str, dict] = {
    "openai": {
        "balance_usd": 10.00,
        "recommended_cap_usd": 0.50,
        "paid": True,
        "primary_model": "text-embedding-3-small",
        "price_note": "$0.02 / 1M tokens (embeddings)",
        "use": "Semantic topic dedup (embeddings only)",
    },
    "gemini": {
        "balance_usd": 12.00,   # ~₹1000
        "recommended_cap_usd": 0.40,
        "paid": True,
        "primary_model": "gemini-2.5-flash",
        "price_note": "$0.075 in / $0.30 out per 1M (free tier first)",
        "use": "Generation, review, refine — hot path",
    },
    "anthropic": {
        "balance_usd": 10.00,
        "recommended_cap_usd": 0.50,
        "paid": True,
        "primary_model": "claude-sonnet-4-6",
        "price_note": "$3 in / $15 out per 1M (batch = 50% off, caching ~90% off input)",
        "use": "Surgical refinement only",
    },
    "groq":      {"balance_usd": 0, "recommended_cap_usd": 0, "paid": False,
                   "primary_model": "llama-3.3-70b-versatile", "price_note": "Free tier",
                   "use": "Triage, fallback"},
    "cerebras":  {"balance_usd": 0, "recommended_cap_usd": 0, "paid": False,
                   "primary_model": "llama3.1-8b", "price_note": "Free tier",
                   "use": "Ultra-fast fallback"},
    "mistral":   {"balance_usd": 0, "recommended_cap_usd": 0, "paid": False,
                   "primary_model": "mistral-small-latest", "price_note": "Free tier",
                   "use": "Classifier fallback"},
    "sambanova": {"balance_usd": 0, "recommended_cap_usd": 0, "paid": False,
                   "primary_model": "Meta-Llama-3.3-70B-Instruct", "price_note": "Free tier",
                   "use": "Fast Llama fallback"},
    "deepseek":  {"balance_usd": 0, "recommended_cap_usd": 0, "paid": False,
                   "primary_model": "deepseek-chat", "price_note": "Free tier (currently 402)",
                   "use": "Reasoning fallback (disabled)"},
}


def get_price(provider: str, model: str) -> tuple[float, float]:
    """Return (input_per_1M, output_per_1M) USD prices for a provider+model."""
    key = (provider.lower(), model)
    if key in PRICING:
        return PRICING[key]
    wildcard = (provider.lower(), "*")
    return PRICING.get(wildcard, (0.0, 0.0))


def compute_cost(
    provider: str,
    model: str,
    tokens_in: int,
    tokens_out: int = 0,
) -> float:
    """Compute cost in USD for a single call."""
    in_price, out_price = get_price(provider, model)
    return (tokens_in / 1_000_000.0) * in_price + (tokens_out / 1_000_000.0) * out_price


def is_free(provider: str, model: str) -> bool:
    in_p, out_p = get_price(provider, model)
    return in_p == 0.0 and out_p == 0.0


# ---- Daily cost-limit enforcement ----

class CostLimitExceeded(Exception):
    """Raised when a provider/model has exceeded its admin-configured daily cost cap."""


async def get_today_cost(
    db: AsyncSession,
    provider: str,
    model: Optional[str] = None,
) -> float:
    """Sum today's USD cost for a provider (optionally filtered to one model)."""
    from app.models.curriculum import AIUsageLog

    today = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0, tzinfo=None
    )

    q = select(AIUsageLog.model, func.sum(AIUsageLog.tokens_estimated)).where(
        and_(
            AIUsageLog.provider == provider,
            AIUsageLog.called_at >= today,
            AIUsageLog.status == "ok",
        )
    )
    if model:
        q = q.where(AIUsageLog.model == model)
    q = q.group_by(AIUsageLog.model)

    total = 0.0
    for row_model, tok_total in (await db.execute(q)).all():
        # We store total tokens (in + out combined) in tokens_estimated.
        # Approximate cost using input price (sufficient for daily cap check;
        # for embeddings output_price is 0 so this is exact).
        in_price, _ = get_price(provider, row_model)
        total += ((tok_total or 0) / 1_000_000.0) * in_price
    return total


async def check_cost_limit(
    db: AsyncSession,
    provider: str,
    model: Optional[str] = None,
) -> None:
    """Raise CostLimitExceeded if today's spend has passed the admin-set cap.

    No-op if no limit is configured for this provider/model.
    """
    from app.models.curriculum import AICostLimit

    # Model-specific limit takes precedence over provider-wide
    q = select(AICostLimit).where(AICostLimit.provider == provider)
    rows = (await db.execute(q)).scalars().all()
    if not rows:
        return

    # Prefer an exact model match; fall back to provider-level ("*")
    specific = next((r for r in rows if r.model == model), None)
    wildcard = next((r for r in rows if r.model == "*"), None)
    limit_row = specific or wildcard
    if limit_row is None or limit_row.daily_cost_usd <= 0:
        return

    # Sum today across all models if the limit is provider-wide
    scope_model = model if specific else None
    spent = await get_today_cost(db, provider, scope_model)
    if spent >= limit_row.daily_cost_usd:
        raise CostLimitExceeded(
            f"Daily cost cap reached for {provider}"
            f"{'/' + model if specific else ''}: "
            f"${spent:.4f} / ${limit_row.daily_cost_usd:.2f}"
        )
