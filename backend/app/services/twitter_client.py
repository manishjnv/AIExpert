"""Twitter / X API v2 client — OAuth 1.0a User Context.

Single function: post_tweet(creds, text). All four OAuth credentials live in
.env and are loaded by `credentials_from_env()`. Caller is the admin
"Post" endpoint; cron flow can also call it for full-auto mode (Phase C).

Secrets handling:
  - The TwitterCredentials dataclass overrides __repr__ / __str__ so accidental
    formatting (logger.info("creds=%s", creds)) cannot leak.
  - The httpx call's Authorization header is set by authlib and the redacting
    filter (logging_redact._OAUTH1_HEADER_RE) scrubs `Authorization: OAuth ...`
    from log lines as defense in depth.
  - On API errors we surface only `status` + a short body excerpt; never the
    request headers.

Response handling:
  - Success → {"data": {"id": "...", "text": "..."}} — we return that "data"
    dict so callers can store posted_tweet_id and build the live URL.
  - Non-2xx OR missing "data" → TwitterAPIError with status + body excerpt.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

import json as _json

import httpx
from authlib.oauth1.rfc5849.client_auth import ClientAuth

logger = logging.getLogger(__name__)

TWITTER_TWEETS_URL = "https://api.twitter.com/2/tweets"
TWEET_LIMIT = 280
DEFAULT_TIMEOUT_S = 15.0


@dataclass
class TwitterCredentials:
    """OAuth 1.0a User Context credentials. All four are required."""

    consumer_key: str
    consumer_secret: str
    access_token: str
    access_token_secret: str

    def __repr__(self) -> str:
        # Never echo secrets. __repr__ wins over %r and !r in f-strings.
        return "TwitterCredentials(<redacted>)"

    __str__ = __repr__


class TwitterAPIError(Exception):
    """Raised when the X API returns non-2xx or an unparsable response."""

    def __init__(self, message: str, *, status: Optional[int] = None,
                 body_excerpt: Optional[str] = None) -> None:
        super().__init__(message)
        self.status = status
        self.body_excerpt = body_excerpt


def credentials_from_env() -> Optional[TwitterCredentials]:
    """Read credentials from process env. Returns None if any are missing —
    caller should treat that as 'API not configured' (no posting).

    Env vars (all required):
      TWITTER_API_KEY              consumer key
      TWITTER_API_SECRET           consumer secret
      TWITTER_ACCESS_TOKEN         user access token
      TWITTER_ACCESS_TOKEN_SECRET  user access token secret
    """
    key = os.environ.get("TWITTER_API_KEY", "").strip()
    secret = os.environ.get("TWITTER_API_SECRET", "").strip()
    token = os.environ.get("TWITTER_ACCESS_TOKEN", "").strip()
    token_secret = os.environ.get("TWITTER_ACCESS_TOKEN_SECRET", "").strip()
    if not all((key, secret, token, token_secret)):
        return None
    return TwitterCredentials(
        consumer_key=key,
        consumer_secret=secret,
        access_token=token,
        access_token_secret=token_secret,
    )


def is_configured() -> bool:
    """Cheap check for callers that want to surface 'not configured' to UI
    without pulling secrets out of env."""
    return credentials_from_env() is not None


def tweet_url(tweet_id: str) -> str:
    """Build the public URL for a posted tweet. Uses /i/web/status which
    resolves regardless of which handle posted it."""
    return f"https://twitter.com/i/web/status/{tweet_id}"


async def post_tweet(
    creds: TwitterCredentials,
    text: str,
    *,
    transport: Optional[httpx.AsyncBaseTransport] = None,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> dict:
    """Post a tweet via OAuth 1.0a User Context.

    Args:
        creds: OAuth 1.0a credentials.
        text: Tweet body. Must be ≤ 280 chars; X enforces this server-side
            but we pre-flight to give a clearer error.
        transport: Optional httpx transport override — used by tests via
            pytest-httpx's MockTransport.
        timeout: Per-request timeout in seconds.

    Returns:
        The "data" dict from the X response: {"id": str, "text": str}.

    Raises:
        ValueError: text empty or > 280 chars.
        TwitterAPIError: any non-2xx response, network failure, or
            response missing the "data" key.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("post_tweet: text is empty")
    if len(text) > TWEET_LIMIT:
        raise ValueError(
            f"post_tweet: text is {len(text)} chars, limit is {TWEET_LIMIT}"
        )

    # Pre-sign the request via authlib's RFC 5849 primitive, then ship the
    # JSON body separately with plain httpx.
    #
    # Two compat traps sit between authlib and X v2:
    #
    #   (1) authlib's AsyncOAuth1Client strips JSON bodies during signing —
    #       fine for form-urlencoded, breaks v2's JSON contract. Manual
    #       signing via ClientAuth.sign() is the escape hatch.
    #
    #   (2) When body is non-empty AND content-type isn't form-urlencoded,
    #       ClientAuth adds an `oauth_body_hash` parameter (per the
    #       OAuth body-hash extension draft). Twitter v2 does NOT validate
    #       oauth_body_hash and may reject signatures that include it.
    #       Workaround: sign with body=b"" so the hash is never added; the
    #       OAuth signature base for non-form bodies is URL + method +
    #       oauth_params only, so the actual body bytes don't affect the
    #       signature. Then send the real JSON body in the dispatched call.
    auth = ClientAuth(
        client_id=creds.consumer_key,
        client_secret=creds.consumer_secret,
        token=creds.access_token,
        token_secret=creds.access_token_secret,
    )
    body_bytes = _json.dumps({"text": text}).encode("utf-8")
    signed_url, signed_headers, _empty = auth.sign(
        "POST", TWITTER_TWEETS_URL,
        headers={"Content-Type": "application/json"},
        body=b"",  # see (2) above
    )

    client_kwargs: dict = {"timeout": timeout}
    if transport is not None:
        client_kwargs["transport"] = transport

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.request(
                "POST", signed_url,
                content=body_bytes, headers=signed_headers,
            )
    except httpx.HTTPError as e:
        # Don't include the exception message verbatim — httpx error strings
        # sometimes echo the request URL with auth in scope.
        raise TwitterAPIError(
            f"network error talking to X API: {type(e).__name__}",
        ) from None

    if resp.status_code >= 400:
        # Body excerpt is safe to surface — X error responses contain
        # human-readable error codes/messages, no creds.
        body_excerpt = resp.text[:400] if resp.text else ""
        raise TwitterAPIError(
            f"X API returned status {resp.status_code}",
            status=resp.status_code,
            body_excerpt=body_excerpt,
        )

    try:
        payload = resp.json()
    except ValueError:
        raise TwitterAPIError(
            "X API returned non-JSON body",
            status=resp.status_code,
            body_excerpt=resp.text[:400],
        ) from None

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or "id" not in data:
        raise TwitterAPIError(
            "X API response missing 'data.id'",
            status=resp.status_code,
            body_excerpt=str(payload)[:400],
        )

    logger.info(
        "twitter_client: posted tweet id=%s len=%s",
        data.get("id"), len(text),
    )
    return data
