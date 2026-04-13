"""Certificate PDF rendering — HTML template → WeasyPrint → bytes.

Isolated so the heavy weasyprint import only happens when a user actually
requests a PDF. Also keeps the hot path (issuance) free of pango/cairo.
"""

from __future__ import annotations

import base64
import io
import logging
from pathlib import Path
from urllib.parse import urljoin

import qrcode
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import get_settings
from app.models.certificate import Certificate

logger = logging.getLogger("roadmap.cert_pdf")

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)

# Amber brand — matched to site CSS. Tier adjusts the accent.
_TIER_COLORS = {
    "completion": "#b45309",
    "distinction": "#92400e",
    "honors":     "#713f12",
}

_MONTHS = ["January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"]


def _verify_url(credential_id: str) -> str:
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/verify/{credential_id}"


def _qr_png_base64(payload: str) -> str:
    """Generate a QR PNG as base64 — embedded inline in the HTML."""
    img = qrcode.make(payload, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def render_certificate_pdf(cert: Certificate) -> bytes:
    """Render a certificate to PDF bytes.

    Imports weasyprint lazily — only the PDF download endpoint triggers it.
    """
    # Lazy import — weasyprint loads native libs on import.
    from weasyprint import HTML

    verify_url = _verify_url(cert.credential_id)
    qr_b64 = _qr_png_base64(verify_url)

    issued = cert.issued_at
    issued_long = f"{_MONTHS[issued.month - 1]} {issued.day}, {issued.year}"
    issued_short = issued.strftime("%Y-%m-%d")

    ctx = {
        "credential_id": cert.credential_id,
        "course_title": cert.course_title,
        "display_name": cert.display_name,
        "level": cert.level.capitalize(),
        "duration_months": cert.duration_months,
        "total_hours": cert.total_hours,
        "checks_done": cert.checks_done,
        "checks_total": cert.checks_total,
        "repos_linked": cert.repos_linked,
        "tier": cert.tier,
        "tier_color": _TIER_COLORS.get(cert.tier, "#b45309"),
        "issued_at_long": issued_long,
        "issued_at_short": issued_short,
        "qr_base64": qr_b64,
        "verify_domain": get_settings().public_base_url.replace("https://", "").replace("http://", "").rstrip("/"),
    }

    html = _env.get_template("certificate.html").render(**ctx)
    pdf_bytes = HTML(string=html, base_url=str(TEMPLATE_DIR)).write_pdf()
    return pdf_bytes
