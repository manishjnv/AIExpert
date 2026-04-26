"""Tests for the Twitter / X v2 OAuth 1.0a client.

The actual OAuth signing path is verified by the upstream authlib library;
these tests cover our wrapper: env loading, response parsing, error mapping,
length pre-flight, secret-redaction in __repr__.
"""

from __future__ import annotations

import httpx
import pytest

from app.services import twitter_client


# ---------- credentials_from_env / is_configured ----------

def test_credentials_from_env_returns_none_when_unset(monkeypatch):
    for k in ("TWITTER_API_KEY", "TWITTER_API_SECRET",
              "TWITTER_ACCESS_TOKEN", "TWITTER_ACCESS_TOKEN_SECRET"):
        monkeypatch.delenv(k, raising=False)
    assert twitter_client.credentials_from_env() is None
    assert twitter_client.is_configured() is False


def test_credentials_from_env_returns_none_on_partial(monkeypatch):
    monkeypatch.setenv("TWITTER_API_KEY", "k")
    monkeypatch.setenv("TWITTER_API_SECRET", "s")
    monkeypatch.delenv("TWITTER_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("TWITTER_ACCESS_TOKEN_SECRET", raising=False)
    assert twitter_client.credentials_from_env() is None


def test_credentials_from_env_loads_full(monkeypatch):
    monkeypatch.setenv("TWITTER_API_KEY", "key")
    monkeypatch.setenv("TWITTER_API_SECRET", "sec")
    monkeypatch.setenv("TWITTER_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("TWITTER_ACCESS_TOKEN_SECRET", "tok_sec")
    creds = twitter_client.credentials_from_env()
    assert creds is not None
    assert creds.consumer_key == "key"
    assert creds.access_token == "tok"
    assert twitter_client.is_configured() is True


def test_credentials_repr_does_not_leak_secrets():
    """Logging accidentally inlining a creds object must not echo any value."""
    creds = twitter_client.TwitterCredentials(
        consumer_key="K_SECRET", consumer_secret="S_SECRET",
        access_token="T_SECRET", access_token_secret="TS_SECRET",
    )
    rep = repr(creds)
    formatted = f"{creds}"
    assert "SECRET" not in rep
    assert "SECRET" not in formatted
    assert "redacted" in rep.lower()


# ---------- tweet_url ----------

def test_tweet_url():
    assert twitter_client.tweet_url("123456") == "https://twitter.com/i/web/status/123456"


# ---------- post_tweet (httpx mock transport) ----------

@pytest.fixture
def creds():
    return twitter_client.TwitterCredentials(
        consumer_key="ck", consumer_secret="cs",
        access_token="at", access_token_secret="ats",
    )


@pytest.mark.asyncio
async def test_post_tweet_rejects_empty(creds):
    with pytest.raises(ValueError, match="empty"):
        await twitter_client.post_tweet(creds, "")
    with pytest.raises(ValueError, match="empty"):
        await twitter_client.post_tweet(creds, "   ")


@pytest.mark.asyncio
async def test_post_tweet_rejects_too_long(creds):
    with pytest.raises(ValueError, match="280"):
        await twitter_client.post_tweet(creds, "x" * 281)


@pytest.mark.asyncio
async def test_post_tweet_success(creds):
    """Mock a 201 with the canonical X v2 success shape — verify we return
    the data dict and the request hit the right URL with the OAuth header."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization", "")
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(
            201,
            json={"data": {"id": "1789", "text": "hello"}},
        )

    transport = httpx.MockTransport(handler)
    out = await twitter_client.post_tweet(creds, "hello", transport=transport)
    assert out == {"id": "1789", "text": "hello"}
    assert captured["url"] == twitter_client.TWITTER_TWEETS_URL
    assert captured["auth"].startswith("OAuth ")  # OAuth 1.0a header
    assert '"text": "hello"' in captured["body"] or '"text":"hello"' in captured["body"]


@pytest.mark.asyncio
async def test_post_tweet_signature_does_not_include_oauth_body_hash(creds):
    """authlib auto-injects `oauth_body_hash` for non-form bodies (OAuth
    body-hash extension), but X v2 doesn't validate it and may reject
    signatures that carry it. We sign with body=b'' to suppress the hash;
    the actual JSON body is sent in the request unchanged."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization", "")
        captured["body"] = request.content
        return httpx.Response(201, json={"data": {"id": "1", "text": "ok"}})

    transport = httpx.MockTransport(handler)
    await twitter_client.post_tweet(creds, "ok", transport=transport)
    assert "oauth_body_hash" not in captured["auth"], (
        f"oauth_body_hash leaked into signature: {captured['auth']}"
    )
    # And the JSON body still travels — the signing dance must not eat it.
    assert b'"text"' in captured["body"]
    assert b"ok" in captured["body"]


@pytest.mark.asyncio
async def test_post_tweet_propagates_4xx_as_api_error(creds):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text='{"errors":[{"code":187,"message":"Status is a duplicate."}]}')

    transport = httpx.MockTransport(handler)
    with pytest.raises(twitter_client.TwitterAPIError) as ei:
        await twitter_client.post_tweet(creds, "hi", transport=transport)
    assert ei.value.status == 403
    assert "duplicate" in (ei.value.body_excerpt or "").lower()


@pytest.mark.asyncio
async def test_post_tweet_handles_non_json_body(creds):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    transport = httpx.MockTransport(handler)
    with pytest.raises(twitter_client.TwitterAPIError, match="non-JSON"):
        await twitter_client.post_tweet(creds, "hi", transport=transport)


@pytest.mark.asyncio
async def test_post_tweet_handles_missing_data_id(creds):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errors": ["nope"]})  # no "data"

    transport = httpx.MockTransport(handler)
    with pytest.raises(twitter_client.TwitterAPIError, match="data.id"):
        await twitter_client.post_tweet(creds, "hi", transport=transport)


@pytest.mark.asyncio
async def test_post_tweet_wraps_network_error_without_leaking(creds):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    transport = httpx.MockTransport(handler)
    with pytest.raises(twitter_client.TwitterAPIError) as ei:
        await twitter_client.post_tweet(creds, "hi", transport=transport)
    # Error message must NOT echo the underlying exception's message which
    # could contain the request URL.
    assert "boom" not in str(ei.value)
    assert "ConnectError" in str(ei.value)


# ---------- post_tweet media_ids backwards-compat + forward path ----------

@pytest.mark.asyncio
async def test_post_tweet_without_media_ids_omits_media_field(creds):
    """Backwards compat: text-only posts ship the same body shape they
    always have — {"text": "..."} with no `media` key."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(201, json={"data": {"id": "1", "text": "hi"}})

    transport = httpx.MockTransport(handler)
    await twitter_client.post_tweet(creds, "hi", transport=transport)
    import json as _json
    body = _json.loads(captured["body"])
    assert body == {"text": "hi"}
    assert "media" not in body  # explicit — schema must NOT carry an empty `media`


@pytest.mark.asyncio
async def test_post_tweet_with_media_ids_nests_under_media(creds):
    """v2 schema nests media_ids under "media" — DON'T confuse with v1.1's
    top-level `media_ids`. Regression that the body shape is exactly:
    {"text": "...", "media": {"media_ids": ["..."]}}."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(201, json={"data": {"id": "2", "text": "hi"}})

    transport = httpx.MockTransport(handler)
    out = await twitter_client.post_tweet(
        creds, "hi", media_ids=["11111", "22222"], transport=transport,
    )
    assert out["id"] == "2"
    import json as _json
    body = _json.loads(captured["body"])
    assert body == {"text": "hi", "media": {"media_ids": ["11111", "22222"]}}


@pytest.mark.asyncio
async def test_post_tweet_rejects_invalid_media_ids(creds):
    """Bad media_ids shapes must short-circuit to ValueError before any
    network request — defense against passing garbage through to X."""
    with pytest.raises(ValueError, match="media_ids"):
        await twitter_client.post_tweet(creds, "hi", media_ids="not-a-list")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="media_ids"):
        await twitter_client.post_tweet(creds, "hi", media_ids=[""])
    with pytest.raises(ValueError, match="media_ids"):
        await twitter_client.post_tweet(creds, "hi", media_ids=[None])  # type: ignore[list-item]


# ---------- upload_media ----------

@pytest.mark.asyncio
async def test_upload_media_rejects_empty(creds):
    with pytest.raises(ValueError, match="empty"):
        await twitter_client.upload_media(creds, b"")


@pytest.mark.asyncio
async def test_upload_media_rejects_oversize(creds):
    big = b"x" * (twitter_client.MEDIA_SINGLE_SHOT_LIMIT + 1)
    with pytest.raises(ValueError, match="single-shot"):
        await twitter_client.upload_media(creds, big)


@pytest.mark.asyncio
async def test_upload_media_success_returns_media_id_string(creds):
    """v1.1 returns both `media_id` (int — JS-precision-loss risk) and
    `media_id_string`. We must always return the string form."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization", "")
        captured["content_type"] = request.headers.get("content-type", "")
        captured["body"] = request.content
        return httpx.Response(
            200,
            json={
                "media_id": 1234567890123456789,  # int — must NOT be returned
                "media_id_string": "1234567890123456789",
                "media_key": "3_1234567890123456789",
                "size": 50000,
            },
        )

    transport = httpx.MockTransport(handler)
    out = await twitter_client.upload_media(
        creds, b"\x89PNG\r\n\x1a\n" + b"\x00" * 100, transport=transport,
    )
    assert out == "1234567890123456789"
    assert isinstance(out, str)  # NOT the int form
    assert captured["url"] == twitter_client.TWITTER_UPLOAD_URL
    assert captured["auth"].startswith("OAuth ")  # OAuth 1.0a header attached
    # httpx must set a multipart boundary — Content-Type comes from the
    # files= dispatch, NOT the application/octet-stream we used during signing.
    assert captured["content_type"].startswith("multipart/form-data")
    assert b"\x89PNG" in captured["body"]  # the image bytes traveled


@pytest.mark.asyncio
async def test_upload_media_signature_does_not_include_oauth_body_hash(creds):
    """Same body-hash trap as post_tweet: authlib auto-injects oauth_body_hash
    for non-form bodies, but X v1.1 doesn't validate it. body=b'' workaround
    must hold for the upload path too."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"media_id_string": "1"})

    transport = httpx.MockTransport(handler)
    await twitter_client.upload_media(creds, b"PNG", transport=transport)
    assert "oauth_body_hash" not in captured["auth"], (
        f"oauth_body_hash leaked into upload signature: {captured['auth']}"
    )


@pytest.mark.asyncio
async def test_upload_media_propagates_4xx_as_api_error(creds):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"errors": [{"code": 324, "message": "Invalid media format."}]},
        )

    transport = httpx.MockTransport(handler)
    with pytest.raises(twitter_client.TwitterAPIError) as ei:
        await twitter_client.upload_media(creds, b"not-an-image", transport=transport)
    assert ei.value.status == 400
    assert "Invalid media" in (ei.value.body_excerpt or "")


@pytest.mark.asyncio
async def test_upload_media_handles_non_json_body(creds):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    transport = httpx.MockTransport(handler)
    with pytest.raises(twitter_client.TwitterAPIError, match="non-JSON"):
        await twitter_client.upload_media(creds, b"PNG", transport=transport)


@pytest.mark.asyncio
async def test_upload_media_handles_missing_media_id_string(creds):
    """Response is JSON but lacks `media_id_string` — tolerating only
    the int form would re-introduce the JS precision risk."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"media_id": 12345})

    transport = httpx.MockTransport(handler)
    with pytest.raises(twitter_client.TwitterAPIError, match="media_id_string"):
        await twitter_client.upload_media(creds, b"PNG", transport=transport)


@pytest.mark.asyncio
async def test_upload_media_wraps_network_error_without_leaking(creds):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom-host-leak")

    transport = httpx.MockTransport(handler)
    with pytest.raises(twitter_client.TwitterAPIError) as ei:
        await twitter_client.upload_media(creds, b"PNG", transport=transport)
    assert "boom-host-leak" not in str(ei.value)
    assert "ConnectError" in str(ei.value)
