"""
Email sender for OTP codes via aiosmtplib + Brevo SMTP.

In dev mode (smtp_host empty), logs the code instead of sending.
"""

from __future__ import annotations

import logging

import aiosmtplib
from email.message import EmailMessage

from app.config import get_settings

logger = logging.getLogger("roadmap.email")


async def send_otp_email(to_email: str, code: str) -> None:
    """Send a 6-digit OTP code to the given email address."""
    settings = get_settings()

    if not settings.smtp_host:
        logger.info("DEV MODE — OTP code for %s: %s", to_email, code)
        return

    html = f"""\
<div style="font-family:sans-serif;max-width:400px;margin:0 auto;padding:20px">
  <h2 style="color:#333">Your sign-in code</h2>
  <p style="font-size:32px;font-weight:bold;letter-spacing:8px;text-align:center;
     background:#f5f5f5;padding:16px;border-radius:8px;margin:24px 0">{code}</p>
  <p style="color:#666;font-size:14px">This code expires in 10 minutes.
     If you didn't request this, you can safely ignore this email.</p>
  <p style="color:#999;font-size:12px">— {settings.smtp_from_name}</p>
</div>"""

    msg = EmailMessage()
    msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from}>"
    msg["To"] = to_email
    msg["Subject"] = f"{code} is your sign-in code"
    msg.set_content(f"Your sign-in code is: {code}\n\nThis code expires in 10 minutes.")
    msg.add_alternative(html, subtype="html")

    await aiosmtplib.send(
        msg,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user,
        password=settings.smtp_password,
        start_tls=True,
    )
    logger.info("OTP email sent to %s", to_email)
