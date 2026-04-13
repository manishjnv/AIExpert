"""Unit tests for the certificate issuance engine.

Covers: credential ID format, HMAC determinism/verification, tier
gating (capstone, distinction, honors), idempotence, and upgrade path.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import pytest

from app.db import Base, close_db, init_db
import app.db as db_module
import app.models  # noqa: F401 — register all models
from app.curriculum.loader import load_template
from app.models.certificate import Certificate
from app.models.plan import Evaluation, Progress, RepoLink, UserPlan
from app.models.user import User
from app.services.certificates import (
    _determine_tier,
    check_and_issue,
    generate_credential_id,
    sign_credential,
    verify_signature,
)


async def _setup():
    await init_db(url="sqlite+aiosqlite:///:memory:")
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ---- credential ID + HMAC ----

def test_credential_id_format():
    cid = generate_credential_id(datetime(2026, 4, 13, tzinfo=timezone.utc))
    assert re.fullmatch(r"AER-2026-04-[A-Z0-9]{6}", cid)


def test_credential_id_uniqueness():
    ids = {generate_credential_id() for _ in range(200)}
    assert len(ids) == 200


def test_signature_is_deterministic():
    t = datetime(2026, 4, 13, 12, 0, 0, tzinfo=timezone.utc).replace(tzinfo=None)
    s1 = sign_credential("AER-2026-04-ABCDEF", 42, t)
    s2 = sign_credential("AER-2026-04-ABCDEF", 42, t)
    assert s1 == s2
    assert len(s1) == 64  # sha256 hex


def test_signature_differs_per_user():
    t = datetime(2026, 4, 13, tzinfo=timezone.utc).replace(tzinfo=None)
    assert sign_credential("AER-X", 1, t) != sign_credential("AER-X", 2, t)


# ---- tier logic ----

def test_tier_none_below_completion():
    assert _determine_tier(
        total_checks=100, checks_done=80,
        capstone_total=20, capstone_done=20,
        repos_required=5, repos_linked=5,
        has_honors_eval=False,
    ) is None


def test_tier_capstone_gate_blocks_completion():
    # 95% overall but capstone incomplete — no cert
    assert _determine_tier(
        total_checks=100, checks_done=95,
        capstone_total=20, capstone_done=18,
        repos_required=5, repos_linked=5,
        has_honors_eval=True,
    ) is None


def test_tier_completion():
    assert _determine_tier(
        total_checks=100, checks_done=92,
        capstone_total=20, capstone_done=20,
        repos_required=5, repos_linked=3,
        has_honors_eval=False,
    ) == "completion"


def test_tier_distinction_requires_repo_coverage():
    # 100% checks, only 60% repos — stays at completion
    assert _determine_tier(
        total_checks=100, checks_done=100,
        capstone_total=20, capstone_done=20,
        repos_required=5, repos_linked=3,
        has_honors_eval=False,
    ) == "completion"


def test_tier_distinction():
    assert _determine_tier(
        total_checks=100, checks_done=100,
        capstone_total=20, capstone_done=20,
        repos_required=5, repos_linked=4,
        has_honors_eval=False,
    ) == "distinction"


def test_tier_honors_requires_distinction():
    # Honors eval but not 100% — only completion
    assert _determine_tier(
        total_checks=100, checks_done=95,
        capstone_total=20, capstone_done=20,
        repos_required=5, repos_linked=5,
        has_honors_eval=True,
    ) == "completion"


def test_tier_honors():
    assert _determine_tier(
        total_checks=100, checks_done=100,
        capstone_total=20, capstone_done=20,
        repos_required=5, repos_linked=5,
        has_honors_eval=True,
    ) == "honors"


# ---- issuance flow ----

async def _make_user_and_plan(template_key="generalist_6mo_intermediate"):
    async with db_module.async_session_factory() as db:
        user = User(email="cert@test.com", provider="otp", name="Test Learner")
        db.add(user)
        await db.flush()
        tpl = load_template(template_key)
        plan = UserPlan(
            user_id=user.id,
            template_key=template_key,
            plan_version=tpl.version,
            status="active",
        )
        db.add(plan)
        await db.flush()
        await db.commit()
        return user.id, plan.id


async def _tick_all_checks(plan_id: int, fraction: float = 1.0, capstone_only_fraction: float | None = None):
    """Mark checks done in the DB. fraction is overall; capstone_only_fraction
    overrides the fraction for capstone-month checks."""
    from app.models.plan import Progress as _P
    async with db_module.async_session_factory() as db:
        plan = await db.get(UserPlan, plan_id)
        tpl = load_template(plan.template_key)
        capstone_weeks = {w.n for w in tpl.months[-1].weeks}
        all_items: list[tuple[int, int, bool]] = []
        for m in tpl.months:
            for w in m.weeks:
                is_capstone = w.n in capstone_weeks
                for idx in range(len(w.checks)):
                    all_items.append((w.n, idx, is_capstone))
        # Deterministic order
        all_items.sort()
        total = len(all_items)
        target_overall = int(total * fraction)
        capstone_items = [x for x in all_items if x[2]]
        non_capstone = [x for x in all_items if not x[2]]

        done_set: set[tuple[int, int]] = set()
        # Mark capstone according to its own fraction if provided
        cap_fraction = 1.0 if capstone_only_fraction is None else capstone_only_fraction
        cap_target = int(len(capstone_items) * cap_fraction)
        for w, idx, _ in capstone_items[:cap_target]:
            done_set.add((w, idx))
        # Fill remainder from non-capstone to hit overall target
        remaining = max(0, target_overall - len(done_set))
        for w, idx, _ in non_capstone[:remaining]:
            done_set.add((w, idx))

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        from sqlalchemy import select as _sel
        existing_rows = (await db.execute(
            _sel(_P).where(_P.user_plan_id == plan_id)
        )).scalars().all()
        existing_map = {(p.week_num, p.check_idx): p for p in existing_rows}
        for w, idx in done_set:
            row = existing_map.get((w, idx))
            if row:
                row.done = True
                row.completed_at = now
                row.updated_at = now
            else:
                db.add(_P(
                    user_plan_id=plan_id, week_num=w, check_idx=idx,
                    done=True, completed_at=now, updated_at=now,
                ))
        await db.commit()


@pytest.mark.asyncio
async def test_issue_nothing_when_below_threshold():
    await _setup()
    user_id, plan_id = await _make_user_and_plan()
    await _tick_all_checks(plan_id, fraction=0.5)
    async with db_module.async_session_factory() as db:
        user = await db.get(User, user_id)
        plan = await db.get(UserPlan, plan_id)
        cert = await check_and_issue(db, user, plan)
        assert cert is None
    await close_db()


@pytest.mark.asyncio
async def test_issue_completion_and_is_idempotent():
    await _setup()
    user_id, plan_id = await _make_user_and_plan()
    # 95% overall, capstone 100%
    await _tick_all_checks(plan_id, fraction=0.95, capstone_only_fraction=1.0)
    async with db_module.async_session_factory() as db:
        user = await db.get(User, user_id)
        plan = await db.get(UserPlan, plan_id)
        cert1 = await check_and_issue(db, user, plan)
        assert cert1 is not None
        assert cert1.tier == "completion"
        assert cert1.credential_id.startswith("AER-")
        assert verify_signature(cert1)
        await db.commit()

        # Second call with same state — returns same row, no new cert
        cert2 = await check_and_issue(db, user, plan)
        assert cert2.id == cert1.id
        assert cert2.credential_id == cert1.credential_id
    await close_db()


@pytest.mark.asyncio
async def test_upgrade_path_completion_to_distinction():
    await _setup()
    user_id, plan_id = await _make_user_and_plan()
    # Start at completion
    await _tick_all_checks(plan_id, fraction=0.92, capstone_only_fraction=1.0)
    async with db_module.async_session_factory() as db:
        user = await db.get(User, user_id)
        plan = await db.get(UserPlan, plan_id)
        cert = await check_and_issue(db, user, plan)
        assert cert.tier == "completion"
        orig_id = cert.credential_id
        orig_issued = cert.issued_at
        await db.commit()

    # Finish everything + link enough repos for distinction
    await _tick_all_checks(plan_id, fraction=1.0, capstone_only_fraction=1.0)
    async with db_module.async_session_factory() as db:
        plan = await db.get(UserPlan, plan_id)
        tpl = load_template(plan.template_key)
        # Link repos_required worth of distinct weeks (pick any week numbers)
        week_numbers = [w.n for m in tpl.months for w in m.weeks][: tpl.repos_required]
        for wn in week_numbers:
            db.add(RepoLink(
                user_plan_id=plan_id, week_num=wn,
                repo_owner="o", repo_name=f"r{wn}",
            ))
        await db.commit()

    async with db_module.async_session_factory() as db:
        user = await db.get(User, user_id)
        plan = await db.get(UserPlan, plan_id)
        cert = await check_and_issue(db, user, plan)
        assert cert.tier == "distinction"
        # credential_id and issued_at preserved across upgrade
        assert cert.credential_id == orig_id
        assert cert.issued_at == orig_issued
    await close_db()


@pytest.mark.asyncio
async def test_honors_requires_capstone_repo_eval():
    await _setup()
    user_id, plan_id = await _make_user_and_plan()
    await _tick_all_checks(plan_id, fraction=1.0, capstone_only_fraction=1.0)

    async with db_module.async_session_factory() as db:
        plan = await db.get(UserPlan, plan_id)
        tpl = load_template(plan.template_key)
        capstone_week = tpl.months[-1].weeks[0].n
        non_capstone_week = tpl.months[0].weeks[0].n

        # Link all repos required — covers distinction
        for wn in [w.n for m in tpl.months for w in m.weeks][: tpl.repos_required]:
            db.add(RepoLink(
                user_plan_id=plan_id, week_num=wn, repo_owner="o", repo_name=f"r{wn}",
            ))
        await db.flush()

        # Add a high-scoring eval on a NON-capstone repo → should NOT unlock honors
        non_cap_link = (await db.execute(
            RepoLink.__table__.select().where(
                (RepoLink.user_plan_id == plan_id) & (RepoLink.week_num == non_capstone_week)
            )
        )).first()
        if non_cap_link:
            db.add(Evaluation(
                repo_link_id=non_cap_link.id, score=10, summary="",
                strengths_json="[]", improvements_json="[]",
                deliverable_met=True, commit_sha="x", model="test",
            ))
        await db.commit()

    async with db_module.async_session_factory() as db:
        user = await db.get(User, user_id)
        plan = await db.get(UserPlan, plan_id)
        cert = await check_and_issue(db, user, plan)
        assert cert.tier == "distinction"
        await db.commit()

    # Now add a high-scoring eval on a CAPSTONE repo → unlocks honors
    async with db_module.async_session_factory() as db:
        plan = await db.get(UserPlan, plan_id)
        tpl = load_template(plan.template_key)
        capstone_week = tpl.months[-1].weeks[0].n
        cap_link_row = (await db.execute(
            RepoLink.__table__.select().where(
                (RepoLink.user_plan_id == plan_id) & (RepoLink.week_num == capstone_week)
            )
        )).first()
        # Ensure we have a capstone link (may not be in the "repos_required"-sized slice)
        if cap_link_row is None:
            db.add(RepoLink(
                user_plan_id=plan_id, week_num=capstone_week,
                repo_owner="o", repo_name="capstone",
            ))
            await db.flush()
            cap_link_row = (await db.execute(
                RepoLink.__table__.select().where(
                    (RepoLink.user_plan_id == plan_id) & (RepoLink.week_num == capstone_week)
                )
            )).first()
        db.add(Evaluation(
            repo_link_id=cap_link_row.id, score=9, summary="",
            strengths_json="[]", improvements_json="[]",
            deliverable_met=True, commit_sha="x", model="test",
        ))
        await db.commit()

    async with db_module.async_session_factory() as db:
        user = await db.get(User, user_id)
        plan = await db.get(UserPlan, plan_id)
        cert = await check_and_issue(db, user, plan)
        assert cert.tier == "honors"
    await close_db()


@pytest.mark.asyncio
async def test_tier_never_downgrades():
    await _setup()
    user_id, plan_id = await _make_user_and_plan()
    await _tick_all_checks(plan_id, fraction=1.0, capstone_only_fraction=1.0)
    async with db_module.async_session_factory() as db:
        plan = await db.get(UserPlan, plan_id)
        tpl = load_template(plan.template_key)
        for wn in [w.n for m in tpl.months for w in m.weeks][: tpl.repos_required]:
            db.add(RepoLink(
                user_plan_id=plan_id, week_num=wn, repo_owner="o", repo_name=f"r{wn}",
            ))
        await db.commit()

    async with db_module.async_session_factory() as db:
        user = await db.get(User, user_id)
        plan = await db.get(UserPlan, plan_id)
        cert = await check_and_issue(db, user, plan)
        assert cert.tier == "distinction"
        await db.commit()

    # Delete some progress rows — overall drops below 100%. Cert should NOT
    # downgrade: we only move up, never down.
    async with db_module.async_session_factory() as db:
        rows = (await db.execute(
            Progress.__table__.select().where(Progress.user_plan_id == plan_id)
        )).all()
        # Mark first 5 as not done
        for r in rows[:5]:
            p = await db.get(Progress, r.id)
            p.done = False
        await db.commit()

    async with db_module.async_session_factory() as db:
        user = await db.get(User, user_id)
        plan = await db.get(UserPlan, plan_id)
        cert = await check_and_issue(db, user, plan)
        # Tier still distinction (or whatever it was); we don't flip it back
        assert cert.tier == "distinction"
    await close_db()
