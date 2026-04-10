"""
Google OAuth2 via Authlib.

Provides the OAuth2 client configuration and helper to exchange the
authorization code for user info. The actual endpoints live in
routers/auth.py.
"""

from __future__ import annotations

from authlib.integrations.starlette_client import OAuth

from app.config import get_settings

oauth = OAuth()


def register_google_oauth() -> None:
    """Register the Google OAuth client. Call once at startup."""
    settings = get_settings()
    if not settings.google_client_id:
        return  # Skip in dev when no Google creds configured

    oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
