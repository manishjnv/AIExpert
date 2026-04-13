"""Certificate issuance engine.

Threshold detection, tier determination, idempotent issue, tier upgrades.
Called from progress tick, repo link, and AI eval completion hooks.

See docs/CERTIFICATES.md for the full design.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets as _secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.curriculum.loader import load_template
from app.models.certificate import Certificate
from app.models.plan import Evaluation, Progress, RepoLink, UserPlan
from app.models.user import User

logger = logging.getLogger("roadmap.certificates")

# Tier ordering: higher index = better. Upgrades only go up.
TIER_ORDER = {"completion": 1, "distinction": 2, "honors": 3}

# Credential ID: AER-YYYY-MM-XXXXXX
_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def _cert_secret() -> bytes:
    """Secret used to sign certificates.

    Prefers CERT_HMAC_SECRET env var. Falls back to a value derived from
    jwt_secret so dev environments still produce deterministic signatures
    without any extra setup.
    """
    env = os.environ.get("CERT_HMAC_SECRET", "").strip()
    if env:
        return env.encode("utf-8")
    # Derivation: HKDF-style prefix separation so the cert secret can't be
    # confused with the JWT secret even though they share an origin.
    base = get_settings().jwt_secret.encode("utf-8")
    return hashlib.sha256(b"cert-hmac-v1|" + base).digest()


def generate_credential_id(now: Optional[datetime] = None) -> str:
    """Generate an AER-YYYY-MM-XXXXXX credential ID.

    The 6-character suffix is random uppercase alphanumeric — 36^6 ≈ 2.1B
    combos per month, collision-resistant in practice. Uniqueness is also
    enforced at the DB layer (see model).
    """
    now = now or datetime.now(timezone.utc)
    suffix = "".join(_secrets.choice(_ALPHABET) for _ in range(6))
    return f"AER-{now.year:04d}-{now.month:02d}-{suffix}"


def sign_credential(credential_id: str, user_id: int, issued_at: datetime) -> str:
    """Return HMAC-SHA256 hex digest for the credential tuple."""
    issued_iso = issued_at.replace(microsecond=0).isoformat()
    payload = f"{credential_id}|{user_id}|{issued_iso}".encode("utf-8")
    return hmac.new(_cert_secret(), payload, hashlib.sha256).hexdigest()


def verify_signature(cert: Certificate) -> bool:
    """Recompute signature and compare in constant time."""
    expected = sign_credential(cert.credential_id, cert.user_id, cert.issued_at)
    return hmac.compare_digest(expected, cert.signed_hash)


def _determine_tier(
    *,
    total_checks: int,
    checks_done: int,
    capstone_total: int,
    capstone_done: int,
    repos_required: int,
    repos_linked: int,
    has_honors_eval: bool,
) -> Optional[str]:
    """Decide which tier (if any) the learner qualifies for.

    Returns None if no threshold is crossed yet. Gates:
      - completion:  ≥90% overall AND capstone 100%
      - distinction: 100% overall AND ≥80% repos_required linked
      - honors:      distinction AND ≥1 capstone-week eval with score ≥8
    """
    if total_checks == 0:
        return None

    overall_ratio = checks_done / total_checks
    capstone_ratio = 1.0 if capstone_total == 0 else (capstone_done / capstone_total)

    # Capstone 100% is a hard gate on everything.
    if capstone_ratio < 1.0:
        return None
    if overall_ratio < 0.90:
        return None

    tier = "completion"

    if overall_ratio >= 1.0:
        # Distinction requires repo coverage. If the template has no repo
        # deliverables at all, we don't gate — 100% completion alone wins it.
        repo_ratio = 1.0 if repos_required == 0 else (repos_linked / repos_required)
        if repo_ratio >= 0.80:
            tier = "distinction"
            if has_honors_eval:
                tier = "honors"

    return tier


async def _collect_plan_stats(db: AsyncSession, plan: UserPlan) -> dict:
    """Pull everything needed to evaluate the tier gates."""
    tpl = load_template(plan.template_key)

    # All progress rows
    progress_rows = (
        await db.execute(select(Progress).where(Progress.user_plan_id == plan.id))
    ).scalars().all()
    done_set = {(p.week_num, p.check_idx) for p in progress_rows if p.done}

    total_checks = 0
    capstone_total = 0
    capstone_done = 0
    capstone_weeks: set[int] = set()
    if tpl.months:
        capstone_month = tpl.months[-1]
        capstone_weeks = {w.n for w in capstone_month.weeks}

    for m in tpl.months:
        is_capstone = (m is tpl.months[-1]) if tpl.months else False
        for w in m.weeks:
            for idx in range(len(w.checks)):
                total_checks += 1
                is_done = (w.n, idx) in done_set
                if is_capstone:
                    capstone_total += 1
                    if is_done:
                        capstone_done += 1

    checks_done = sum(1 for (_w, _i) in done_set)

    # Repo links + capstone-week evaluations
    repo_links = (
        await db.execute(select(RepoLink).where(RepoLink.user_plan_id == plan.id))
    ).scalars().all()
    repos_linked = len(repo_links)
    capstone_link_ids = [rl.id for rl in repo_links if rl.week_num in capstone_weeks]

    has_honors_eval = False
    if capstone_link_ids:
        top_score = await db.scalar(
            select(Evaluation.score)
            .where(Evaluation.repo_link_id.in_(capstone_link_ids))
            .order_by(Evaluation.score.desc())
            .limit(1)
        )
        has_honors_eval = bool(top_score is not None and top_score >= 8)

    return {
        "template": tpl,
        "total_checks": total_checks,
        "checks_done": checks_done,
        "capstone_total": capstone_total,
        "capstone_done": capstone_done,
        "repos_required": tpl.repos_required,
        "repos_linked": repos_linked,
        "has_honors_eval": has_honors_eval,
    }


async def check_and_issue(
    db: AsyncSession, user: User, plan: UserPlan,
) -> Optional[Certificate]:
    """Evaluate gates and issue (or upgrade) a certificate for this plan.

    Idempotent:
      - No crossing → returns None
      - First crossing → issues a new row
      - Subsequent crossing into a higher tier → upgrades tier + stats in place
        (credential_id and issued_at are preserved)
      - Same or lower tier than existing → returns existing row unchanged
    """
    stats = await _collect_plan_stats(db, plan)
    tier = _determine_tier(
        total_checks=stats["total_checks"],
        checks_done=stats["checks_done"],
        capstone_total=stats["capstone_total"],
        capstone_done=stats["capstone_done"],
        repos_required=stats["repos_required"],
        repos_linked=stats["repos_linked"],
        has_honors_eval=stats["has_honors_eval"],
    )

    existing = (
        await db.execute(
            select(Certificate).where(
                Certificate.user_id == user.id,
                Certificate.user_plan_id == plan.id,
            )
        )
    ).scalar_one_or_none()

    if tier is None:
        return existing  # nothing to do — learner hasn't crossed any gate

    tpl = stats["template"]

    if existing is None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        credential_id = generate_credential_id(now)
        signed = sign_credential(credential_id, user.id, now)
        cert = Certificate(
            user_id=user.id,
            user_plan_id=plan.id,
            template_key=plan.template_key,
            credential_id=credential_id,
            tier=tier,
            display_name=(user.name or user.email.split("@")[0]).strip(),
            course_title=tpl.title,
            level=tpl.level,
            duration_months=tpl.duration_months,
            total_hours=tpl.total_hours,
            checks_done=stats["checks_done"],
            checks_total=stats["total_checks"],
            repos_linked=stats["repos_linked"],
            repos_required=stats["repos_required"],
            issued_at=now,
            signed_hash=signed,
        )
        db.add(cert)
        await db.flush()
        logger.info(
            "Certificate issued: user=%s plan=%s tier=%s credential=%s",
            user.id, plan.id, tier, credential_id,
        )
        return cert

    # Upgrade path — tier only moves up, never down.
    if TIER_ORDER[tier] > TIER_ORDER[existing.tier]:
        logger.info(
            "Certificate upgrade: user=%s plan=%s %s → %s",
            user.id, plan.id, existing.tier, tier,
        )
        existing.tier = tier
        existing.checks_done = stats["checks_done"]
        existing.checks_total = stats["total_checks"]
        existing.repos_linked = stats["repos_linked"]
        existing.repos_required = stats["repos_required"]
        await db.flush()

    return existing


async def safe_check_and_issue(
    db: AsyncSession, user: User, plan: UserPlan,
) -> Optional[Certificate]:
    """Wrapper that never raises — certificate issuance must not break the
    hot path of the caller (progress tick, repo link, eval completion)."""
    try:
        return await check_and_issue(db, user, plan)
    except Exception:
        logger.exception("Certificate issuance failed (non-fatal)")
        return None
