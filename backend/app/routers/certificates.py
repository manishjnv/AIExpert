"""Certificate router — list current user's certs + download PDF.

Public verification page lives separately in routers/verify.py so it can
mount at /verify/{credential_id} rather than under /api.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db import get_db
from app.models.certificate import Certificate
from app.models.user import User

router = APIRouter()
logger = logging.getLogger("roadmap.certificates_api")


def _cert_dict(cert: Certificate) -> dict:
    return {
        "credential_id": cert.credential_id,
        "tier": cert.tier,
        "template_key": cert.template_key,
        "course_title": cert.course_title,
        "level": cert.level,
        "duration_months": cert.duration_months,
        "total_hours": cert.total_hours,
        "checks_done": cert.checks_done,
        "checks_total": cert.checks_total,
        "repos_linked": cert.repos_linked,
        "repos_required": cert.repos_required,
        "display_name": cert.display_name,
        "issued_at": cert.issued_at.isoformat() if cert.issued_at else None,
        "revoked_at": cert.revoked_at.isoformat() if cert.revoked_at else None,
        "pdf_downloads": cert.pdf_downloads,
        "linkedin_shares": cert.linkedin_shares,
        "verification_views": cert.verification_views,
    }


@router.get("/certificates")
async def list_my_certificates(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all certificates issued to the current user, newest first."""
    rows = (
        await db.execute(
            select(Certificate)
            .where(Certificate.user_id == user.id)
            .order_by(Certificate.issued_at.desc())
        )
    ).scalars().all()
    return [_cert_dict(c) for c in rows]


@router.get("/certificates/{credential_id}/pdf")
async def download_certificate_pdf(
    credential_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stream the PDF for a certificate owned by the current user.

    Increments the pdf_downloads counter. Revoked certs return 410.
    """
    cert = (
        await db.execute(
            select(Certificate).where(Certificate.credential_id == credential_id)
        )
    ).scalar_one_or_none()
    if cert is None or cert.user_id != user.id:
        raise HTTPException(status_code=404, detail="Certificate not found")
    if cert.revoked_at is not None:
        raise HTTPException(status_code=410, detail="Certificate revoked")

    from app.services.certificate_pdf import render_certificate_pdf
    try:
        pdf_bytes = render_certificate_pdf(cert)
    except Exception:
        logger.exception("PDF render failed for %s", credential_id)
        raise HTTPException(status_code=500, detail="Could not render certificate")

    cert.pdf_downloads += 1
    await db.flush()

    filename = f"{credential_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # Prevent stale-cache regressions when the template changes.
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )


@router.post("/certificates/{credential_id}/share-linkedin", status_code=204)
async def record_linkedin_share(
    credential_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record a LinkedIn-share click. Frontend opens the share URL itself."""
    cert = (
        await db.execute(
            select(Certificate).where(Certificate.credential_id == credential_id)
        )
    ).scalar_one_or_none()
    if cert is None or cert.user_id != user.id:
        raise HTTPException(status_code=404, detail="Certificate not found")

    cert.linkedin_shares += 1
    await db.flush()
    return Response(status_code=204)
