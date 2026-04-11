"""
Contact form — sends user messages to the maintainer via SMTP.
"""

import logging

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)
logger = logging.getLogger("roadmap.contact")


class ContactBody(BaseModel):
    name: str
    email: EmailStr
    message: str


@router.post("/contact", status_code=204)
@limiter.limit("3/hour")
async def contact(body: ContactBody, request: Request):
    """Send a contact form message to the maintainer."""
    if len(body.message) < 10:
        raise HTTPException(status_code=400, detail="Message too short")
    if len(body.message) > 2000:
        raise HTTPException(status_code=400, detail="Message too long (max 2000 chars)")

    settings = get_settings()

    if not settings.smtp_host:
        logger.info("DEV MODE — Contact from %s <%s>: %s", body.name, body.email, body.message)
        return Response(status_code=204)

    try:
        import aiosmtplib
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from}>"
        msg["To"] = settings.maintainer_email
        msg["Subject"] = f"[AI Roadmap] Contact from {body.name}"
        msg["Reply-To"] = body.email
        msg.set_content(
            f"Name: {body.name}\n"
            f"Email: {body.email}\n\n"
            f"Message:\n{body.message}\n"
        )

        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password,
            start_tls=True,
        )
        logger.info("Contact form sent from %s <%s>", body.name, body.email)
    except Exception as e:
        logger.error("Failed to send contact email: %s", e)
        raise HTTPException(status_code=500, detail="Failed to send message. Please try again.")

    return Response(status_code=204)
