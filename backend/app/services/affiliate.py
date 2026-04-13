"""
Coursera affiliate link rewriter.

When COURSERA_AFFILIATE_ID is set, URLs on coursera.org matching
/learn/* or /specializations/* get an ?irclickid=<token> query param
appended. Existing query strings are preserved — parsing goes through
urllib.parse so we never double-encode.

Scope by design:
- Applied when templates are served to authenticated learners (plan
  endpoints). The actual call site passes the rewritten plan to the user.
- NEVER applied on /public/{slug}, /share/*, /verify/*. Recruiters are
  not an affiliate context, so links stay canonical.

The irclickid is generated per-rewrite so each render is a distinct click
in Impact's tracker. The affiliate ID is included as a prefix so the
partner half of the click ID is stable even if you rotate the secret.
"""

from __future__ import annotations

import secrets
from copy import deepcopy
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from app.config import get_settings


_REWRITABLE_PATH_PREFIXES: tuple[str, ...] = ("/learn/", "/specializations/")


def _should_rewrite(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.netloc or "").lower()
    if not (host == "coursera.org" or host.endswith(".coursera.org")):
        return False
    path = parsed.path or "/"
    # Normalise: treat /learn and /learn/foo both as matchable; require a
    # slug after the prefix so we don't rewrite the bare category page.
    for prefix in _REWRITABLE_PATH_PREFIXES:
        if path.startswith(prefix) and len(path) > len(prefix):
            return True
    return False


def _generate_clickid(affiliate_id: str) -> str:
    """Per-render click ID: '<affiliate>-<16 hex chars>'."""
    return f"{affiliate_id}-{secrets.token_hex(8)}"


def rewrite_url(url: str, affiliate_id: str | None = None) -> str:
    """Rewrite a single URL. Returns the original if no rewrite applies.

    affiliate_id: explicit override (tests); falls back to settings.
    """
    aff = affiliate_id if affiliate_id is not None else get_settings().coursera_affiliate_id
    if not aff:
        return url
    if not _should_rewrite(url):
        return url

    parsed = urlparse(url)
    qs = parse_qsl(parsed.query, keep_blank_values=True)
    # If irclickid is already present, leave as-is (idempotent).
    if any(k == "irclickid" for k, _ in qs):
        return url
    qs.append(("irclickid", _generate_clickid(aff)))
    return urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))


def _rewrite_resource_list(items: Iterable[dict[str, Any]] | None, aff: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for it in items or []:
        r = dict(it)
        if "url" in r and isinstance(r["url"], str):
            r["url"] = rewrite_url(r["url"], affiliate_id=aff)
        out.append(r)
    return out


def rewrite_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Deep-copy a serialized plan and rewrite every eligible Coursera URL.

    Covers: week resources, top_resources, certifications. Safe to call
    when affiliate_id is empty — returns the input plan structure.
    """
    aff = get_settings().coursera_affiliate_id
    if not aff:
        return plan

    out = deepcopy(plan)

    for month in out.get("months", []) or []:
        for week in month.get("weeks", []) or []:
            if "resources" in week:
                week["resources"] = _rewrite_resource_list(week.get("resources"), aff)

    if "top_resources" in out:
        out["top_resources"] = _rewrite_resource_list(out.get("top_resources"), aff)

    if "certifications" in out:
        out["certifications"] = _rewrite_resource_list(out.get("certifications"), aff)

    return out
