"""Redaction filter must strip API keys from log records before formatting."""

from __future__ import annotations

import logging

from app.logging_redact import _redact, install_redacting_filter


def test_redact_query_string_key():
    s = "POST https://generativelanguage.googleapis.com/v1/models:gen?key=AIzaSyABC-DEF 200 OK"
    assert "AIzaSyABC-DEF" not in _redact(s)
    assert "key=[REDACTED]" in _redact(s)


def test_redact_preserves_other_query_params():
    s = "GET https://api.example.com/v1/q?page=2&key=secret123&size=10"
    out = _redact(s)
    assert "page=2" in out and "size=10" in out
    assert "secret123" not in out


def test_redact_authorization_header():
    s = "Authorization: Bearer sk-proj-abcdefghijk"
    out = _redact(s)
    assert "sk-proj-abcdefghijk" not in out
    assert "[REDACTED]" in out


def test_filter_scrubs_record_message(caplog):
    """End-to-end: install filter, log a secret, verify caplog output is clean."""
    install_redacting_filter()
    logger = logging.getLogger("httpx")
    with caplog.at_level(logging.INFO, logger="httpx"):
        logger.info("POST https://x.com/api?key=AIzaSyLIVE-LEAK 200 OK")
    combined = " ".join(r.getMessage() for r in caplog.records)
    assert "AIzaSyLIVE-LEAK" not in combined
    assert "[REDACTED]" in combined


def test_filter_scrubs_percent_args(caplog):
    """%-style logging (httpx uses this) must also get scrubbed via record.args."""
    install_redacting_filter()
    logger = logging.getLogger("httpx")
    with caplog.at_level(logging.INFO, logger="httpx"):
        logger.info("url=%s status=%s", "https://x.com/api?key=LEAK-XYZ", 200)
    combined = " ".join(r.getMessage() for r in caplog.records)
    assert "LEAK-XYZ" not in combined


def test_redact_oauth1_authorization_header():
    """OAuth 1.0a header — every parameter is sensitive (nonce, token,
    signature). Redact the whole comma-separated value, not just the first
    component."""
    s = (
        'Authorization: OAuth oauth_consumer_key="ABC123", '
        'oauth_nonce="N0NC3", oauth_signature="SIG_SECRET"'
    )
    out = _redact(s)
    assert "ABC123" not in out
    assert "N0NC3" not in out
    assert "SIG_SECRET" not in out
    assert "[REDACTED]" in out


def test_filter_handles_lowercase_authorization_header(caplog):
    """httpx and similar libs emit `authorization:` (lowercase). The early-
    out gate must be case-insensitive — previously it required capital
    'Authorization' so OAuth headers logged in lowercase bypassed redaction
    entirely."""
    install_redacting_filter()
    logger = logging.getLogger("httpx")
    with caplog.at_level(logging.INFO, logger="httpx"):
        logger.info('authorization: OAuth oauth_signature="LIVE_LEAK_SIG"')
    combined = " ".join(r.getMessage() for r in caplog.records)
    assert "LIVE_LEAK_SIG" not in combined
    assert "[REDACTED]" in combined
