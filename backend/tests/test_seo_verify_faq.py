"""SEO-12 (EducationalOccupationalCredential JSON-LD) + SEO-15 (FAQPage
visible/schema parity) tests."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

import app.db as db_module
import app.models  # noqa: F401
from app.db import Base, close_db, init_db


FRONTEND_INDEX = Path(__file__).resolve().parents[2] / "frontend" / "index.html"


async def _setup():
    await init_db(url="sqlite+aiosqlite:///:memory:")
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Reset the in-memory per-IP rate-limit buckets so prior test runs
    # (test_certificates_e2e drains the 60/hr budget) don't 429 us.
    from app.routers import verify as verify_mod
    verify_mod._view_budget.clear()
    verify_mod._view_dedup.clear()


def _app():
    from app.main import app
    return app


# ---- SEO-12: EducationalOccupationalCredential JSON-LD ---------------------


@pytest.mark.asyncio
async def test_verify_page_emits_credential_json_ld():
    """/verify/{id} must embed a parseable EducationalOccupationalCredential
    JSON-LD block with credentialCategory='certificate' and dateCreated in
    ISO-8601. Rich Results Test depends on these exact fields."""
    from app.models.certificate import Certificate
    from app.models.plan import UserPlan
    from app.models.user import User

    await _setup()
    async with db_module.async_session_factory() as s:
        u = User(email="v@t", name="Viv", provider="otp")
        s.add(u); await s.flush()
        p = UserPlan(user_id=u.id, template_key="generalist",
                     plan_version="v1", status="active")
        s.add(p); await s.flush()
        issued = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc).replace(tzinfo=None)
        s.add(Certificate(
            user_id=u.id, user_plan_id=p.id, template_key="generalist",
            credential_id="AER-2026-04-TESTAA", tier="completion",
            display_name="Viv", course_title="AI Generalist",
            level="beginner", duration_months=6,
            signed_hash="deadbeef" * 8,
            issued_at=issued,
        ))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/verify/AER-2026-04-TESTAA")
        assert r.status_code == 200
        html = r.text
        # Locate the EducationalOccupationalCredential JSON-LD block.
        marker = '"@type": "EducationalOccupationalCredential"'
        assert marker in html, "EducationalOccupationalCredential JSON-LD missing"
        # Extract + parse the block to catch malformed JSON early.
        start = html.rfind('<script type="application/ld+json">',
                           0, html.index(marker))
        end = html.index('</script>', start)
        raw = html[start + len('<script type="application/ld+json">'):end]
        data = json.loads(raw)
        assert data["@type"] == "EducationalOccupationalCredential"
        assert data["credentialCategory"] == "certificate"
        assert data["url"].endswith("/verify/AER-2026-04-TESTAA")
        # dateCreated must be ISO-8601
        assert data["dateCreated"].startswith("2026-04-01")
        # name includes tier label + course
        assert "AI Generalist" in data["name"]
        # recognizedBy is the issuing org
        assert data["recognizedBy"]["name"] == "AutomateEdge"
        # about.name = course topic
        assert data["about"]["name"] == "AI Generalist"
        # educationalLevel is capitalized
        assert data["educationalLevel"] == "Beginner"
    await close_db()


@pytest.mark.asyncio
async def test_verify_page_still_works_for_revoked_cert_with_json_ld():
    """Even for a revoked cert (red badge), the JSON-LD is emitted so
    the credential record is still schema-discoverable."""
    from app.models.certificate import Certificate
    from app.models.plan import UserPlan
    from app.models.user import User

    await _setup()
    async with db_module.async_session_factory() as s:
        u = User(email="rev@t", name="Rev", provider="otp")
        s.add(u); await s.flush()
        p = UserPlan(user_id=u.id, template_key="generalist",
                     plan_version="v1", status="active")
        s.add(p); await s.flush()
        s.add(Certificate(
            user_id=u.id, user_plan_id=p.id, template_key="generalist",
            credential_id="AER-2026-04-REVOKX", tier="completion",
            display_name="Rev", course_title="AI Generalist",
            level="beginner", duration_months=6,
            signed_hash="deadbeef" * 8,
            issued_at=datetime(2026, 1, 1).replace(tzinfo=None),
            revoked_at=datetime(2026, 3, 1).replace(tzinfo=None),
            revoke_reason="test",
        ))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/verify/AER-2026-04-REVOKX")
        assert r.status_code == 200
        assert '"@type": "EducationalOccupationalCredential"' in r.text
    await close_db()


# ---- SEO-15: FAQ section ↔ JSON-LD parity -----------------------------------


def test_faq_section_present_and_every_jsonld_question_is_visible():
    """Every FAQPage Question in the JSON-LD must render as a <summary>
    on the page. Google requires schema content to be visible; mismatch
    causes the rich result to be dropped."""
    html = FRONTEND_INDEX.read_text(encoding="utf-8")

    # Visible FAQ section exists
    assert '<section id="faq"' in html
    assert 'class="faq-section"' in html

    # Pull the FAQPage JSON-LD block. The file has three ld+json blocks; we
    # find the one whose @type is FAQPage.
    import re
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>',
                        html, flags=re.DOTALL)
    faq_data = None
    for b in blocks:
        try:
            d = json.loads(b)
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict) and d.get("@type") == "FAQPage":
            faq_data = d
            break
    assert faq_data is not None, "FAQPage JSON-LD block not found"

    # Every schema question name must appear inside a <summary> tag in
    # the visible FAQ section so Google's validator treats the rich
    # result as legitimate.
    faq_section_start = html.index('<section id="faq"')
    faq_section_end = html.index('</section>', faq_section_start)
    faq_section = html[faq_section_start:faq_section_end]

    missing = []
    for qa in faq_data["mainEntity"]:
        q = qa["name"]
        if f"<summary>{q}</summary>" not in faq_section:
            missing.append(q)
    assert not missing, f"JSON-LD FAQ questions not rendered visibly: {missing}"
