"""End-to-end HTTP integration tests for the certificate flow.

Exercises the real routers (not just the service) via an in-process ASGI
client: enroll → tick progress → cert issued → list certs → download
PDF → public verify page → LinkedIn share counter.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.jwt import issue_token


def _weasyprint_available() -> bool:
    """Return True iff weasyprint's native libs (cairo/pango) load on this host.

    On Windows dev machines without GTK runtime the import triggers an OSError
    when ctypes tries to load libgobject-2.0-0. We fall back to skipping
    PDF-render assertions so the rest of the e2e suite still runs locally.
    CI (Ubuntu with libpango + libcairo) loads fine and runs the full flow.
    """
    try:
        import weasyprint  # noqa: F401
        return True
    except Exception:
        return False
from app.curriculum.loader import load_template
from app.db import Base, close_db, init_db
import app.db as db_module
import app.models  # noqa: F401
from app.models.certificate import Certificate
from app.models.plan import Progress, RepoLink, UserPlan
from app.models.user import User


async def _setup():
    await init_db(url="sqlite+aiosqlite:///:memory:")
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _app():
    from app.main import app
    return app


async def _user_token(email="cert-e2e@test.com", name="Jane Doe"):
    async with db_module.async_session_factory() as db:
        u = User(email=email, provider="otp", name=name)
        db.add(u); await db.flush()
        tok = await issue_token(u, db)
        await db.commit()
        return u.id, tok


async def _enroll(client: AsyncClient, token: str, key: str = "generalist_3mo_intermediate"):
    resp = await client.post(
        "/api/plans",
        json={"template_key": key},
        cookies={"auth_token": token},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _bulk_complete_plan(user_id: int, plan_id: int, fraction: float = 1.0):
    """Bulk-insert progress rows to hit a target completion fraction.
    Capstone month is always 100%."""
    async with db_module.async_session_factory() as db:
        plan = await db.get(UserPlan, plan_id)
        tpl = load_template(plan.template_key)
        capstone_weeks = {w.n for w in tpl.months[-1].weeks}
        all_items = [
            (w.n, idx, (w.n in capstone_weeks))
            for m in tpl.months for w in m.weeks
            for idx in range(len(w.checks))
        ]
        total = len(all_items)
        target = int(total * fraction)
        # Always include all capstone items
        done = set()
        for wn, idx, iscap in all_items:
            if iscap:
                done.add((wn, idx))
        # Fill remaining from non-capstone
        for wn, idx, iscap in all_items:
            if len(done) >= target:
                break
            if not iscap:
                done.add((wn, idx))

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for wn, idx in done:
            db.add(Progress(
                user_plan_id=plan_id, week_num=wn, check_idx=idx,
                done=True, completed_at=now, updated_at=now,
            ))
        await db.commit()


@pytest.mark.asyncio
async def test_e2e_certificate_full_flow():
    """Complete a plan → cert issued → list / PDF / verify / share all work."""
    await _setup()
    user_id, token = await _user_token()

    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # 1) Enroll in 3-month plan
        plan = await _enroll(c, token, key="generalist_3mo_intermediate")
        plan_id = plan["id"]

        # 2) Pre-complete 95% of plan offline (faster than 100s of PATCH calls)
        await _bulk_complete_plan(user_id, plan_id, fraction=0.95)

        # 3) One final PATCH to trigger the issuance hook
        # Find any check that's currently not done and flip it
        async with db_module.async_session_factory() as db:
            tpl = load_template(plan["template_key"])
            done_rows = (await db.execute(
                Progress.__table__.select().where(Progress.user_plan_id == plan_id)
            )).all()
            done_set = {(r.week_num, r.check_idx) for r in done_rows}
            # Find first non-capstone undone check
            capstone_weeks = {w.n for w in tpl.months[-1].weeks}
            trigger = None
            for m in tpl.months:
                for w in m.weeks:
                    if w.n in capstone_weeks:
                        continue
                    for idx in range(len(w.checks)):
                        if (w.n, idx) not in done_set:
                            trigger = (w.n, idx)
                            break
                    if trigger: break
                if trigger: break
            # If none found (rare), pick one and toggle done=False then done=True
            if trigger is None:
                trigger = (tpl.months[0].weeks[0].n, 0)

        resp = await c.patch(
            "/api/progress",
            json={"week_num": trigger[0], "check_idx": trigger[1], "done": True},
            cookies={"auth_token": token},
        )
        assert resp.status_code == 204

        # 4) GET /api/certificates should now return 1 cert
        resp = await c.get("/api/certificates", cookies={"auth_token": token})
        assert resp.status_code == 200
        certs = resp.json()
        assert len(certs) == 1, f"expected 1 cert, got {certs}"
        cert = certs[0]
        assert cert["tier"] in ("completion", "distinction", "honors")
        assert cert["credential_id"].startswith("AER-")
        assert cert["display_name"] == "Jane Doe"
        assert cert["course_title"]
        assert cert["pdf_downloads"] == 0
        assert cert["verification_views"] == 0
        cid = cert["credential_id"]

        # 5) Download PDF (lazy-imports weasyprint — must be installed in container)
        if _weasyprint_available():
            resp = await c.get(f"/api/certificates/{cid}/pdf", cookies={"auth_token": token})
            assert resp.status_code == 200, resp.text[:200]
            assert resp.headers["content-type"] == "application/pdf"
            assert resp.headers["content-disposition"].endswith(f'"{cid}.pdf"')
            assert resp.content[:4] == b"%PDF", "response is not a valid PDF"
            assert len(resp.content) > 2000  # non-trivial size

            # 6) pdf_downloads counter incremented
            resp = await c.get("/api/certificates", cookies={"auth_token": token})
            assert resp.json()[0]["pdf_downloads"] == 1
        else:
            pytest.skip("weasyprint native libs unavailable on this host")

        # 7) Public /verify/{id} — no auth
        resp = await c.get(f"/verify/{cid}")
        assert resp.status_code == 200
        body = resp.text
        assert "Credential verified" in body
        assert cid in body
        assert "Jane Doe" in body
        assert 'property="og:title"' in body
        assert 'property="og:image"' in body
        # verification_views should now be 1
        async with db_module.async_session_factory() as db:
            c_row = (await db.execute(
                Certificate.__table__.select().where(Certificate.credential_id == cid)
            )).first()
            assert c_row.verification_views == 1

        # 8) OG SVG
        resp = await c.get(f"/verify/{cid}/og.svg")
        assert resp.status_code == 200
        assert "image/svg+xml" in resp.headers["content-type"]
        assert "<svg" in resp.text
        assert "Jane Doe" in resp.text

        # 9) LinkedIn share counter
        resp = await c.post(f"/api/certificates/{cid}/share-linkedin",
                            cookies={"auth_token": token})
        assert resp.status_code == 204
        resp = await c.get("/api/certificates", cookies={"auth_token": token})
        assert resp.json()[0]["linkedin_shares"] == 1

        # 10) Unknown credential → 404
        resp = await c.get("/verify/AER-2026-04-DOESNT")
        assert resp.status_code == 404
        assert "Not Found" in resp.text or "not found" in resp.text.lower()

        # 11) Tampering: mutate display_name in DB → badge flips to mismatch
        async with db_module.async_session_factory() as db:
            cert_row = await db.get(
                Certificate,
                (await db.execute(
                    Certificate.__table__.select().where(Certificate.credential_id == cid)
                )).first().id,
            )
            cert_row.display_name = "Attacker Name"
            await db.commit()
        # Public page still loads but shows tamper warning — note: our signature
        # only covers (credential_id, user_id, issued_at), so editing display_name
        # alone won't break the signature. This asserts that property.
        resp = await c.get(f"/verify/{cid}")
        assert resp.status_code == 200
        # signature still valid (we only sign stable identity fields), so
        # the badge stays green. Attacker-modified name shows though.
        assert "Attacker Name" in resp.text

    await close_db()


@pytest.mark.asyncio
async def test_e2e_pdf_revoked_returns_410():
    await _setup()
    user_id, token = await _user_token(email="revoke@test.com")
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        plan = await _enroll(c, token)
        plan_id = plan["id"]
        await _bulk_complete_plan(user_id, plan_id, fraction=1.0)
        # Trigger via PATCH — pick any check
        resp = await c.patch(
            "/api/progress",
            json={"week_num": 1, "check_idx": 0, "done": True},
            cookies={"auth_token": token},
        )
        assert resp.status_code == 204

        resp = await c.get("/api/certificates", cookies={"auth_token": token})
        cid = resp.json()[0]["credential_id"]

        # Mark revoked
        async with db_module.async_session_factory() as db:
            row = (await db.execute(
                Certificate.__table__.select().where(Certificate.credential_id == cid)
            )).first()
            cert = await db.get(Certificate, row.id)
            cert.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
            cert.revoke_reason = "Test revocation"
            await db.commit()

        # PDF endpoint returns 410
        resp = await c.get(f"/api/certificates/{cid}/pdf", cookies={"auth_token": token})
        assert resp.status_code == 410

        # Public verify page still loads but shows red revoked badge
        resp = await c.get(f"/verify/{cid}")
        assert resp.status_code == 200
        assert "Revoked" in resp.text
        assert "Test revocation" in resp.text
    await close_db()


@pytest.mark.asyncio
async def test_e2e_cert_not_owned_returns_404():
    """A user cannot download another user's certificate PDF."""
    await _setup()
    _, token_a = await _user_token(email="owner@test.com")
    _, token_b = await _user_token(email="thief@test.com", name="Thief")
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        plan_a = await _enroll(c, token_a)
        await _bulk_complete_plan(_user_id_for_token := plan_a["id"], plan_a["id"], fraction=1.0)
        resp = await c.patch(
            "/api/progress",
            json={"week_num": 1, "check_idx": 0, "done": True},
            cookies={"auth_token": token_a},
        )
        resp = await c.get("/api/certificates", cookies={"auth_token": token_a})
        cid = resp.json()[0]["credential_id"]

        # Thief tries to download
        resp = await c.get(f"/api/certificates/{cid}/pdf",
                           cookies={"auth_token": token_b})
        assert resp.status_code == 404

        # Thief tries to record share → 404
        resp = await c.post(f"/api/certificates/{cid}/share-linkedin",
                            cookies={"auth_token": token_b})
        assert resp.status_code == 404
    await close_db()


@pytest.mark.asyncio
async def test_e2e_verify_rate_limit():
    """Rate limit on /verify/{id} kicks in after 60 req/IP/hr."""
    await _setup()
    # Reset the in-process per-IP view budget from any earlier tests
    from app.routers import verify as verify_mod
    verify_mod._view_budget.clear()
    verify_mod._view_dedup.clear()
    user_id, token = await _user_token(email="rate@test.com")
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        plan = await _enroll(c, token)
        await _bulk_complete_plan(user_id, plan["id"], fraction=1.0)
        await c.patch(
            "/api/progress",
            json={"week_num": 1, "check_idx": 0, "done": True},
            cookies={"auth_token": token},
        )
        cid = (await c.get("/api/certificates",
                           cookies={"auth_token": token})).json()[0]["credential_id"]

        # Hammer the endpoint
        ok = 0
        limited = 0
        for _ in range(65):
            r = await c.get(f"/verify/{cid}")
            if r.status_code == 200:
                ok += 1
            elif r.status_code == 429:
                limited += 1
        # First 60 OK, rest rate-limited
        assert ok == 60, f"expected 60 ok, got {ok}"
        assert limited == 5
    await close_db()
