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
# X never released a v2 media endpoint — v1.1 is the only path. Single-shot
# multipart upload works for files < 5MB; chunked INIT/APPEND/FINALIZE is
# only needed beyond that (our OG cards are ~50KB).
TWITTER_UPLOAD_URL = "https://upload.twitter.com/1.1/media/upload.json"
TWEET_LIMIT = 280
MEDIA_SINGLE_SHOT_LIMIT = 5 * 1024 * 1024  # 5MB
DEFAULT_TIMEOUT_S = 15.0
# Media upload is multipart (image bytes) so the timeout budget is wider —
# 15s for a 50KB POST is generous, but a flaky edge route can drag.
DEFAULT_UPLOAD_TIMEOUT_S = 30.0


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
    media_ids: Optional[list[str]] = None,
    transport: Optional[httpx.AsyncBaseTransport] = None,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> dict:
    """Post a tweet via OAuth 1.0a User Context.

    Args:
        creds: OAuth 1.0a credentials.
        text: Tweet body. Must be ≤ 280 chars; X enforces this server-side
            but we pre-flight to give a clearer error.
        media_ids: Optional list of media_id strings (from upload_media) to
            attach. When set, the request body is
            {"text": ..., "media": {"media_ids": [...]}}. When None, the
            payload stays {"text": ...} (backwards-compat with text-only
            posts). The v2 schema nests media_ids under "media" — different
            from v1.1's top-level `media_ids` form.
        transport: Optional httpx transport override — used by tests via
            httpx.MockTransport.
        timeout: Per-request timeout in seconds.

    Returns:
        The "data" dict from the X response: {"id": str, "text": str}.

    Raises:
        ValueError: text empty or > 280 chars, or media_ids empty list.
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
    if media_ids is not None and not isinstance(media_ids, list):
        raise ValueError("post_tweet: media_ids must be a list of strings or None")
    if media_ids is not None and not all(
        isinstance(m, str) and m for m in media_ids
    ):
        raise ValueError("post_tweet: media_ids must contain non-empty strings")

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
    body_dict: dict = {"text": text}
    if media_ids:
        # v2 schema: media_ids nest under "media" — see RCA notes on the
        # upload module about v1.1 vs v2 confusion.
        body_dict["media"] = {"media_ids": list(media_ids)}
    body_bytes = _json.dumps(body_dict).encode("utf-8")
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
        "twitter_client: posted tweet id=%s len=%s media=%s",
        data.get("id"), len(text), len(media_ids) if media_ids else 0,
    )
    return data


async def upload_media(
    creds: TwitterCredentials,
    image_bytes: bytes,
    *,
    media_type: str = "image/png",
    transport: Optional[httpx.AsyncBaseTransport] = None,
    timeout: float = DEFAULT_UPLOAD_TIMEOUT_S,
) -> str:
    """Single-shot upload of a small (< 5MB) image to X v1.1 media endpoint.

    X v2 has no media endpoint — v1.1 is the only supported path. The v1.1
    response schema returns both `media_id` (int) and `media_id_string`
    (str). Always use the string — JS clients (and X v2 itself when posting
    with attached media) lose precision on the int form for IDs > 2^53.

    OAuth 1.0a signing trap: the signature base string for non-form-urlencoded
    bodies excludes the body bytes (the spec only includes form fields).
    authlib's ClientAuth nevertheless tries to add an `oauth_body_hash`
    parameter for non-form bodies (per the OAuth body-hash extension draft);
    X v1.1 doesn't validate it and may reject signatures that include it.
    Same `body=b""` workaround as post_tweet — sign with an empty body so
    no hash is added, then dispatch the multipart payload via httpx.
    Crucially, we strip the pre-sign Content-Type from signed_headers so
    httpx can set its own multipart Content-Type with a fresh per-request
    boundary; the Authorization header is independent of the body content
    type for our case.

    Args:
        creds: OAuth 1.0a credentials.
        image_bytes: Raw image bytes. < 5MB for single-shot upload.
        media_type: MIME type. Defaults to image/png (our OG cards).
        transport: Optional httpx transport override (test-only).
        timeout: Per-request timeout in seconds; defaults to 30s for media
            (wider than the v2 tweet timeout to absorb edge-network jitter
            on multipart bodies).

    Returns:
        media_id_string for use in post_tweet(media_ids=[...]).

    Raises:
        ValueError: image_bytes empty or > 5MB.
        TwitterAPIError: any non-2xx response, network failure, or response
            missing `media_id_string`.
    """
    if not image_bytes:
        raise ValueError("upload_media: image_bytes is empty")
    if len(image_bytes) > MEDIA_SINGLE_SHOT_LIMIT:
        raise ValueError(
            f"upload_media: image is {len(image_bytes)} bytes; "
            f"single-shot limit is {MEDIA_SINGLE_SHOT_LIMIT} (5MB). "
            "Larger files require chunked INIT/APPEND/FINALIZE — not implemented."
        )

    auth = ClientAuth(
        client_id=creds.consumer_key,
        client_secret=creds.consumer_secret,
        token=creds.access_token,
        token_secret=creds.access_token_secret,
    )
    signed_url, signed_headers, _empty = auth.sign(
        "POST", TWITTER_UPLOAD_URL,
        # application/octet-stream tells authlib "this is not form-urlencoded
        # so don't try to parse the body for the signature base"; combined
        # with body=b"" the oauth_body_hash branch is also skipped.
        headers={"Content-Type": "application/octet-stream"},
        body=b"",
    )
    # Drop the placeholder Content-Type so httpx can set the multipart
    # Content-Type (with boundary) for the actual files= upload.
    signed_headers = {
        k: v for k, v in signed_headers.items() if k.lower() != "content-type"
    }

    # Best-effort filename for X — they accept any reasonable name and
    # use it only for logging.
    ext = media_type.split("/")[-1].lower() or "png"
    files = {"media": (f"og.{ext}", image_bytes, media_type)}

    client_kwargs: dict = {"timeout": timeout}
    if transport is not None:
        client_kwargs["transport"] = transport

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.request(
                "POST", signed_url,
                files=files, headers=signed_headers,
            )
    except httpx.HTTPError as e:
        raise TwitterAPIError(
            f"network error uploading media to X: {type(e).__name__}",
        ) from None

    if resp.status_code >= 400:
        body_excerpt = resp.text[:400] if resp.text else ""
        raise TwitterAPIError(
            f"X media upload returned status {resp.status_code}",
            status=resp.status_code,
            body_excerpt=body_excerpt,
        )

    try:
        payload = resp.json()
    except ValueError:
        raise TwitterAPIError(
            "X media upload returned non-JSON body",
            status=resp.status_code,
            body_excerpt=resp.text[:400],
        ) from None

    media_id = payload.get("media_id_string") if isinstance(payload, dict) else None
    if not isinstance(media_id, str) or not media_id:
        raise TwitterAPIError(
            "X media upload response missing 'media_id_string'",
            status=resp.status_code,
            body_excerpt=str(payload)[:400],
        )

    logger.info(
        "twitter_client: uploaded media id=%s bytes=%s type=%s",
        media_id, len(image_bytes), media_type,
    )
    return media_id
