"""Logging filter that redacts API keys from emitted log records.

httpx and google-generativeai both log full URLs at INFO level, which means
`?key=AIza...` ends up in container logs, log aggregators, and any stack
trace that bubbles a request URL. This filter scrubs those before the
record is formatted.

Applied once from app.main startup and also from script entrypoints so
both the live backend and one-off tools (backfill, ingest, scheduler) emit
redacted lines.
"""

from __future__ import annotations

import logging
import re

# Known secret-bearing query params across the providers we call.
# Add new ones as we onboard providers. Case-insensitive.
_QS_SECRET_PARAMS = r"(?:key|api[_-]?key|access[_-]?token|x-api-key|token)"

# Matches:  ?key=abc123&x=1   or  &key=abc123  etc.
_QS_SECRET_RE = re.compile(rf"([?&]{_QS_SECRET_PARAMS}=)[^&\s\"']+", re.I)

# Matches common authorization header echoes: "Authorization: Bearer abc..."
_AUTH_HEADER_RE = re.compile(
    r"(Authorization:\s*(?:Bearer|Token)\s+)[A-Za-z0-9._\-]+", re.I
)

# OAuth 1.0a "Authorization: OAuth oauth_consumer_key="...", ..." — every
# parameter (nonce, signature, token) is sensitive. Redact the entire
# parameter list rather than each field individually.
_OAUTH1_HEADER_RE = re.compile(
    r"(Authorization:\s*OAuth\s+)[^\r\n]+", re.I
)


def _redact(text: str) -> str:
    text = _QS_SECRET_RE.sub(r"\1[REDACTED]", text)
    text = _AUTH_HEADER_RE.sub(r"\1[REDACTED]", text)
    text = _OAUTH1_HEADER_RE.sub(r"\1[REDACTED]", text)
    return text


class RedactingFilter(logging.Filter):
    """Apply secret redaction to every record's message + args.

    We must mutate `record.msg` and `record.args` before the formatter runs
    so that both %-formatted and f-string-formatted records are scrubbed.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # Pre-format path — message still has %s placeholders. Early-out
        # gating is case-insensitive: httpx and similar libs frequently emit
        # `authorization:` (lowercase) which previously bypassed the regex
        # path entirely, leaving OAuth headers visible in logs.
        if isinstance(record.msg, str):
            lower = record.msg.lower()
            if "key=" in lower or "authorization" in lower or "token=" in lower:
                record.msg = _redact(record.msg)
        if record.args:
            record.args = tuple(
                _redact(a) if isinstance(a, str) else a for a in record.args
            ) if isinstance(record.args, tuple) else record.args
        return True


def install_redacting_filter() -> None:
    """Attach the filter to the root logger and to noisy library loggers."""
    filt = RedactingFilter()
    root = logging.getLogger()
    if not any(isinstance(f, RedactingFilter) for f in root.filters):
        root.addFilter(filt)
    # httpx + googleapiclient write URLs at INFO; cover them explicitly in
    # case they install their own handlers that bypass root filters.
    for name in ("httpx", "httpcore", "urllib3", "google", "google.generativeai"):
        lg = logging.getLogger(name)
        if not any(isinstance(f, RedactingFilter) for f in lg.filters):
            lg.addFilter(filt)
