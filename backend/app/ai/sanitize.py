"""
Secret sanitizer — scrub filenames and file contents before sending to LLMs.

CLAUDE.md rule 7: AI evaluation never reveals secrets.
"""

from __future__ import annotations

import re
from fnmatch import fnmatch

# Files to exclude entirely
EXCLUDED_PATTERNS = [
    ".env", ".env.*", "*.env",
    "*secret*", "*secrets*",
    "*credential*", "*credentials*",
    "*.pem", "*.key", "*.p12", "*.pfx",
    "id_rsa", "id_rsa.*", "id_ed25519", "id_ed25519.*",
    "*.keystore", "*.jks",
    "config.json",  # often contains secrets
    "service-account*.json",
    "*.secret", "*.private",
]

# Regexes that match common API key / token formats
SECRET_CONTENT_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),          # OpenAI / Stripe
    re.compile(r"ghp_[a-zA-Z0-9]{36,}"),          # GitHub PAT
    re.compile(r"gho_[a-zA-Z0-9]{36,}"),          # GitHub OAuth
    re.compile(r"ghu_[a-zA-Z0-9]{36,}"),          # GitHub user token
    re.compile(r"ghs_[a-zA-Z0-9]{36,}"),          # GitHub server token
    re.compile(r"ghr_[a-zA-Z0-9]{36,}"),          # GitHub refresh token
    re.compile(r"AIza[a-zA-Z0-9_-]{35}"),         # Google API key
    re.compile(r"GOCSPX-[a-zA-Z0-9_-]{28,}"),    # Google client secret
    re.compile(r"xox[bpsa]-[a-zA-Z0-9-]+"),      # Slack tokens
    re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"),
    re.compile(r"aws_secret_access_key\s*=\s*\S+", re.IGNORECASE),
    re.compile(r"AKIA[0-9A-Z]{16}"),              # AWS access key ID
]

# High-entropy string detector (base64-like blocks > 30 chars)
_HIGH_ENTROPY = re.compile(r"[A-Za-z0-9+/=_-]{40,}")


def is_excluded_file(filename: str) -> bool:
    """Check if a filename matches any excluded pattern."""
    name = filename.rsplit("/", 1)[-1].lower()
    return any(fnmatch(name, pat.lower()) for pat in EXCLUDED_PATTERNS)


def contains_secrets(content: str) -> bool:
    """Check if content contains common secret patterns."""
    for pat in SECRET_CONTENT_PATTERNS:
        if pat.search(content):
            return True
    return False


def redact_secrets(content: str) -> str:
    """Replace detected secrets with [REDACTED]."""
    result = content
    for pat in SECRET_CONTENT_PATTERNS:
        result = pat.sub("[REDACTED]", result)
    return result


def sanitize_file_list(files: list[dict]) -> list[dict]:
    """Filter and sanitize a list of file dicts with 'path' and 'content' keys.

    - Removes files matching excluded patterns
    - Redacts secret patterns from remaining file contents
    """
    sanitized = []
    for f in files:
        path = f.get("path", "")
        if is_excluded_file(path):
            continue
        content = f.get("content", "")
        if contains_secrets(content):
            content = redact_secrets(content)
        sanitized.append({"path": path, "content": content})
    return sanitized
