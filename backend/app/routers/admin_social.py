"""Admin router for Social Drafts review page.

Mounted at /admin/social (prefix set in main.py). Requires get_current_admin.

GET /admin/social/drafts — read-only listing of social_posts rows with
  status IN ('draft', 'archived'), grouped by (source_kind, source_slug)
  with Twitter and LinkedIn side-by-side per source.

POST /admin/social/publish/{id}    — publish Twitter draft via X API v2
POST /admin/social/mark-posted/{id} — record external publish URL (LinkedIn
                                       or Twitter fallback)
POST /admin/social/discard/{id}    — archive a draft with optional reason
POST /admin/social/edit/{id}       — update body + hashtags on a draft

RCA-008 caution: body content comes from DB as plain text. We always pass it
through html.escape() before embedding in HTML. No f-string body interpolation
without escaping — use the esc() alias throughout.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from html import escape as esc
from typing import Any, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_admin
from app.config import get_settings
from app.db import get_db
from app.models.user import User
from app.services import twitter_client
from app.services.share_copy import _TAG_DISPLAY
from app.utils.time_fmt import fmt_ist, FMT_SHORT

router = APIRouter()

# Import shared admin UI constants from admin.py
from app.routers.admin import ADMIN_CSS, ADMIN_NAV

# Hashtag input validation. Mirrors SocialDraftSchema rules from ai/schemas.py
# but keyed on _TAG_DISPLAY for additional brand-canonicality enforcement on
# admin edits (an admin should not be able to invent #SomeNewTag).
_BRAND_TAG = "#AutomateEdge"
_VALID_TAGS: frozenset[str] = frozenset(_TAG_DISPLAY.values()) | {_BRAND_TAG}
_HASHTAG_RE = re.compile(r"^#[A-Z][A-Za-z0-9]+$")
_TWITTER_BODY_MAX = 280
_LINKEDIN_BODY_MAX = 3000


def _csrf_check(request: Request) -> None:
    """Strict-equality origin check per RCA-012.

    Rejects when neither Origin nor Referer is present, AND when their
    parsed hostname does not exactly match the request Host header.
    """
    origin = request.headers.get("origin", "").strip()
    referer = request.headers.get("referer", "").strip()
    host = request.headers.get("host", "").strip()
    if not (origin or referer):
        raise HTTPException(status_code=403, detail="Origin or Referer required")
    src = origin or referer
    src_host = (urlparse(src).hostname or "").lower()
    expected = (urlparse(f"http://{host}").hostname or "").lower()
    if not src_host or not expected or src_host != expected:
        raise HTTPException(status_code=403, detail="Origin mismatch")


def _validate_published_url(url: str) -> str:
    """Validate a Mark-as-posted URL: http(s), real hostname, ≤500 chars.

    Note: we do NOT fetch the URL (per RCA-011 SSRF principles), only
    structurally validate it. The admin is trusted to paste a legit URL.
    """
    url = (url or "").strip()
    if not url or len(url) > 500:
        raise ValueError("published_url must be 1-500 chars")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("published_url must be http(s)")
    if not parsed.hostname:
        raise ValueError("published_url must have a hostname")
    return url


def _validate_hashtags(hashtags: list[str], platform: str) -> list[str]:
    """Validate platform-specific hashtag rules. Raise ValueError on any failure."""
    if not isinstance(hashtags, list) or not all(isinstance(t, str) for t in hashtags):
        raise ValueError("hashtags must be a list of strings")
    cleaned = [t.strip() for t in hashtags]
    for tag in cleaned:
        if tag == _BRAND_TAG:
            continue
        if not _HASHTAG_RE.match(tag):
            raise ValueError(
                f"hashtag {tag!r} is not canonical form ^#[A-Z][A-Za-z0-9]+$"
            )
        if tag not in _VALID_TAGS:
            raise ValueError(
                f"hashtag {tag!r} is not in the brand-canonical _TAG_DISPLAY map"
            )
    if platform == "twitter":
        if not (1 <= len(cleaned) <= 2):
            raise ValueError(f"Twitter requires 1-2 hashtags, got {len(cleaned)}")
        if _BRAND_TAG in cleaned:
            raise ValueError("Twitter must not include #AutomateEdge")
    elif platform == "linkedin":
        if not (3 <= len(cleaned) <= 5):
            raise ValueError(f"LinkedIn requires 3-5 hashtags, got {len(cleaned)}")
        if cleaned[-1] != _BRAND_TAG:
            raise ValueError(f"LinkedIn hashtags must end with #AutomateEdge, got {cleaned[-1]!r}")
    else:
        raise ValueError(f"unknown platform: {platform!r}")
    return cleaned


def _validate_body(body: str, platform: str) -> str:
    """Validate body length per platform + reject inline '#' (hashtags must live
    in hashtags field per §3.11 voice rules)."""
    body = (body or "").strip()
    if not body:
        raise ValueError("body must be non-empty")
    if "#" in body:
        raise ValueError("body must not contain '#' (hashtags belong in hashtags field)")
    cap = _TWITTER_BODY_MAX if platform == "twitter" else _LINKEDIN_BODY_MAX
    if len(body) > cap:
        raise ValueError(f"{platform} body {len(body)} chars exceeds {cap}")
    return body


# ---- Request models ----------------------------------------------------------


class _MarkAsPostedRequest(BaseModel):
    published_url: str = Field(..., min_length=1, max_length=500)

    @field_validator("published_url")
    @classmethod
    def _v(cls, v: str) -> str:
        return _validate_published_url(v)


class _DiscardRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=200)


class _EditDraftRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=3500)
    hashtags: list[str] = Field(..., min_length=1, max_length=5)


# ---- Helpers -----------------------------------------------------------------


def _parse_json_field(raw: str | None, fallback: Any = None) -> Any:
    """Safely parse a JSON column. Returns fallback on error or None."""
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback


def _render_hashtags(hashtags_json: str | None) -> str:
    tags = _parse_json_field(hashtags_json, [])
    if not tags or not isinstance(tags, list):
        return '<span style="color:#5a6472">—</span>'
    parts = []
    for t in tags:
        if isinstance(t, str) and t.strip():
            tag = t.strip().lstrip("#")
            parts.append(
                f'<span style="color:#6db585;font-family:\'IBM Plex Mono\',monospace;font-size:11px">'
                f'#{esc(tag)}</span>'
            )
    return " ".join(parts) if parts else '<span style="color:#5a6472">—</span>'


def _render_reasoning(reasoning_json: str | None, status: str) -> str:
    """Render a collapsible reasoning trail block."""
    data = _parse_json_field(reasoning_json, {})
    if not data or not isinstance(data, dict):
        return ""

    # For archived rows, surface the archive reason prominently
    if status == "archived":
        archive_reason = esc(str(data.get("archive_reason", "unknown")))
        retry_count = data.get("retry_count", "")
        archived_at = esc(str(data.get("archived_at", "")))
        return (
            f'<div style="background:#2a1510;border-left:3px solid #d97757;'
            f'padding:8px 12px;border-radius:0 4px 4px 0;margin-top:8px;font-size:12px">'
            f'<strong style="color:#d97757">Archived</strong>: {archive_reason}'
            f'{(" &mdash; retry_count: " + esc(str(retry_count))) if retry_count else ""}'
            f'{(" &mdash; at: " + archived_at) if archived_at else ""}'
            f'</div>'
        )

    rows_html = ""
    for field, label in [
        ("score_justification", "Score justification"),
        ("evidence_sources", "Evidence sources"),
        ("uncertainty_factors", "Uncertainty factors"),
    ]:
        val = data.get(field)
        if val is None:
            continue
        if isinstance(val, list):
            val_html = "<ul style='margin:4px 0;padding-left:18px'>" + "".join(
                f"<li>{esc(str(v))}</li>" for v in val
            ) + "</ul>"
        else:
            val_html = f"<p style='margin:4px 0'>{esc(str(val))}</p>"
        rows_html += (
            f'<div style="margin-bottom:8px">'
            f'<strong style="color:#8a92a0;font-size:11px;text-transform:uppercase;'
            f'letter-spacing:0.1em">{label}</strong>'
            f'{val_html}</div>'
        )

    if not rows_html:
        return ""

    return (
        f'<details style="margin-top:8px">'
        f'<summary style="cursor:pointer;color:#6a7280;font-size:12px;'
        f'font-family:\'IBM Plex Mono\',monospace">Reasoning trail</summary>'
        f'<div style="background:#1a2030;border-radius:4px;padding:10px 14px;'
        f'margin-top:6px;font-size:13px;color:#b0aaa0">'
        f'{rows_html}'
        f'</div></details>'
    )


def _platform_badge(platform: str) -> str:
    if platform == "twitter":
        return (
            '<span style="background:#1a2d3d;color:#1d9bf0;border:1px solid #2a4d6d;'
            'padding:2px 8px;border-radius:3px;font-family:\'IBM Plex Mono\',monospace;'
            'font-size:10px;letter-spacing:0.08em;text-transform:uppercase">Twitter</span>'
        )
    if platform == "linkedin":
        return (
            '<span style="background:#1a2a3a;color:#0a66c2;border:1px solid #2a4a6a;'
            'padding:2px 8px;border-radius:3px;font-family:\'IBM Plex Mono\',monospace;'
            'font-size:10px;letter-spacing:0.08em;text-transform:uppercase">LinkedIn</span>'
        )
    return esc(platform)


def _status_badge(status: str) -> str:
    if status == "draft":
        return (
            '<span style="background:#143a2e;color:#6db585;border:1px solid #2a5a45;'
            'padding:2px 8px;border-radius:3px;font-family:\'IBM Plex Mono\',monospace;'
            'font-size:10px;letter-spacing:0.08em;text-transform:uppercase">Draft</span>'
        )
    if status == "published":
        return (
            '<span style="background:#0d2a3a;color:#4ab0f0;border:1px solid #1d4060;'
            'padding:2px 8px;border-radius:3px;font-family:\'IBM Plex Mono\',monospace;'
            'font-size:10px;letter-spacing:0.08em;text-transform:uppercase">Published</span>'
        )
    if status == "archived":
        return (
            '<span style="background:#2a1510;color:#d97757;border:1px solid #4a3025;'
            'padding:2px 8px;border-radius:3px;font-family:\'IBM Plex Mono\',monospace;'
            'font-size:10px;letter-spacing:0.08em;text-transform:uppercase">Archived</span>'
        )
    return esc(status)


def _render_tab_nav(active: str, drafts_count: int = 0, pub_count: int = 0,
                    arch_count: int = 0) -> str:
    """Tab nav between Drafts / Published / Archived. `active` is the slug
    matching the current route (drafts | published | archived)."""
    tabs = [
        ("drafts", "Drafts", drafts_count),
        ("published", "Published", pub_count),
        ("archived", "Archived", arch_count),
    ]
    items: list[str] = []
    for slug, label, count in tabs:
        is_active = (slug == active)
        bg = "#1d242e" if is_active else "transparent"
        color = "#e8a849" if is_active else "#6a7280"
        border = "2px solid #e8a849" if is_active else "2px solid transparent"
        count_html = (
            f' <span style="opacity:0.7;font-size:10px">({count})</span>'
        ) if count > 0 else ""
        items.append(
            f'<a href="/admin/social/{slug}" '
            f'style="padding:10px 18px;background:{bg};color:{color};'
            f'border-bottom:{border};text-decoration:none;'
            f"font-family:'IBM Plex Mono',monospace;font-size:12px;"
            f'text-transform:uppercase;letter-spacing:0.1em">{label}{count_html}</a>'
        )
    return (
        '<div style="display:flex;gap:0;margin-bottom:24px;'
        'border-bottom:1px solid #2a323d">' + "".join(items) + '</div>'
    )


def _render_filter_form(source_kind: str, platform: str, action: str) -> str:
    """Render filter dropdowns for Published/Archived tabs. `action` is the
    GET action URL (already begins with /admin/social/...)."""
    def _opt(value: str, label: str, current: str) -> str:
        sel = " selected" if value == current else ""
        return f'<option value="{esc(value)}"{sel}>{esc(label)}</option>'

    sk = source_kind or ""
    pl = platform or ""
    return f'''
<form method="get" action="{esc(action)}" style="display:flex;gap:8px;margin-bottom:20px;
            font-family:'IBM Plex Mono',monospace;font-size:12px;align-items:center">
  <label style="color:#6a7280">Source:
    <select name="source_kind" style="background:#1a2030;color:#d0cbc2;
            border:1px solid #2a323d;padding:4px 8px;margin-left:6px">
      {_opt("", "All", sk)}
      {_opt("blog", "Blog", sk)}
      {_opt("course", "Course", sk)}
    </select>
  </label>
  <label style="color:#6a7280">Platform:
    <select name="platform" style="background:#1a2030;color:#d0cbc2;
            border:1px solid #2a323d;padding:4px 8px;margin-left:6px">
      {_opt("", "All", pl)}
      {_opt("twitter", "Twitter", pl)}
      {_opt("linkedin", "LinkedIn", pl)}
    </select>
  </label>
  <button type="submit" style="background:#e8a849;color:#0f1419;border:none;
          padding:6px 14px;font-family:'IBM Plex Mono',monospace;font-size:11px;
          text-transform:uppercase;letter-spacing:0.1em;cursor:pointer">Filter</button>
  <a href="{esc(action)}" style="color:#6a7280;text-decoration:underline;
          font-size:11px;margin-left:8px">Clear</a>
</form>'''


def _source_link(source_kind: str, source_slug: str) -> str:
    if source_kind == "blog":
        url = f"/blog/{esc(source_slug)}"
    else:
        url = f"/roadmap/{esc(source_slug)}"
    label = esc(f"{source_kind}: {source_slug}")
    return (
        f'<a href="{url}" target="_blank" '
        f'style="color:#e8a849;font-family:\'IBM Plex Mono\',monospace;font-size:12px">'
        f'{label}</a>'
    )


def _render_post_card(row: Any, *, x_publish_enabled: bool = False) -> str:
    """Render a single social_posts row as a card."""
    platform_html = _platform_badge(row.platform)
    status_html = _status_badge(row.status)
    body_safe = esc(row.body or "")
    hashtags_html = _render_hashtags(row.hashtags_json)
    reasoning_html = _render_reasoning(row.reasoning_json, row.status)

    archive_note = ""
    if row.status == "archived":
        archive_note = (
            f'<div style="font-size:12px;color:#d97757;margin-top:6px">'
            f'retry_count: {esc(str(row.retry_count or 0))} '
            f'&mdash; last attempt: {esc(fmt_ist(row.updated_at))}'
            f'</div>'
        )

    published_note = ""
    if row.status == "published" and row.published_url:
        published_note = (
            f'<div style="font-size:12px;color:#4ab0f0;margin-top:6px">'
            f'Published <a href="{esc(row.published_url)}" target="_blank" rel="noopener"'
            f' style="color:#4ab0f0;text-decoration:underline">'
            f'↗ {esc(fmt_ist(row.published_at) if row.published_at else "")}</a>'
            f'</div>'
        )

    # Action buttons — draft rows OR published rows (Re-publish).
    # Archived is terminal — no buttons.
    action_row_html = ""
    if row.status == "draft":
        pid = esc(str(row.id))
        plat = esc(row.platform)
        sk = esc(row.source_kind)
        ss = esc(row.source_slug)
        # body and hashtags passed as data-attrs so JS can read without re-fetch
        body_attr = esc(row.body or "")
        hashtags_raw = _parse_json_field(row.hashtags_json, [])
        hashtags_attr = esc(json.dumps(hashtags_raw if isinstance(hashtags_raw, list) else []))

        def _btn(action: str, label: str) -> str:
            return (
                f'<button type="button" class="action-btn"'
                f' data-action="{esc(action)}" data-post-id="{pid}"'
                f' data-platform="{plat}"'
                f' data-source-kind="{sk}"'
                f' data-source-slug="{ss}"'
                f' data-body="{body_attr}"'
                f' data-hashtags-json="{hashtags_attr}"'
                f'>{label}</button>'
            )

        if row.platform == "twitter" and x_publish_enabled:
            buttons = (
                _btn("edit", "Edit")
                + _btn("publish", "Publish to X")
                + _btn("discard", "Discard")
            )
        elif row.platform == "twitter":
            # x_publish_enabled=False: fallback copy-open flow
            buttons = (
                _btn("edit", "Edit")
                + _btn("copy-open", "📋 Copy + Open X")
                + _btn("mark-posted", "Mark as posted")
                + _btn("discard", "Discard")
            )
        else:
            # linkedin (always copy-open + mark-posted)
            buttons = (
                _btn("edit", "Edit")
                + _btn("copy-open", "📋 Copy + Open LinkedIn")
                + _btn("mark-posted", "Mark as posted")
                + _btn("discard", "Discard")
            )

        action_row_html = f'<div class="action-row" style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">{buttons}</div>'

    elif row.status == "published":
        pid = esc(str(row.id))
        plat = esc(row.platform)
        sk = esc(row.source_kind)
        ss = esc(row.source_slug)
        # Re-publish queues a fresh pending pair with prior-draft markers so
        # the cron's repub-mode pickup can inject the prior body into the
        # next Opus prompt for a different-angle take.
        rep_btn = (
            f'<button type="button" class="action-btn"'
            f' data-action="re-publish" data-post-id="{pid}"'
            f' data-platform="{plat}"'
            f' data-source-kind="{sk}"'
            f' data-source-slug="{ss}">Re-publish (different angle)</button>'
        )
        action_row_html = f'<div class="action-row" style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">{rep_btn}</div>'

    return f"""
<div class="draft-card" data-post-id="{esc(str(row.id))}"
     style="background:#1a2030;border-radius:6px;padding:16px;margin-bottom:12px;
            border:1px solid #2a323d">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
    {platform_html}
    {status_html}
    <span style="color:#5a6472;font-size:11px;font-family:'IBM Plex Mono',monospace;
                 margin-left:auto">#{esc(str(row.id))}</span>
  </div>
  <div class="draft-body" style="background:#0f1419;border-radius:4px;padding:12px;margin-bottom:10px;
              white-space:pre-wrap;font-size:13px;color:#d0cbc2;
              font-family:'IBM Plex Sans',system-ui,sans-serif;line-height:1.6">{body_safe}</div>
  <div style="margin-bottom:6px;font-size:12px;color:#6a7280">
    Hashtags: <span class="draft-hashtags">{hashtags_html}</span>
  </div>
  {archive_note}
  {published_note}
  {reasoning_html}
  <div style="margin-top:10px;border-top:1px solid #2a323d;padding-top:8px;
              font-size:11px;color:#5a6472;font-family:'IBM Plex Mono',monospace">
    created: {esc(fmt_ist(row.created_at))} &nbsp;&bull;&nbsp;
    updated: {esc(fmt_ist(row.updated_at))}
  </div>
  {action_row_html}
</div>"""


# ---- Route helpers -----------------------------------------------------------


_STALE_DRAFT_AGE_DAYS = 30


def _utcnow() -> datetime:
    """Return a UTC-naive datetime to match the migration's TIMESTAMP storage."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _status_counts(db: AsyncSession) -> dict[str, int]:
    """Single query to populate the tab-nav row counts."""
    from sqlalchemy import func
    from app.models.social import SocialPost

    rows = (
        await db.execute(
            select(SocialPost.status, func.count())
            .group_by(SocialPost.status)
        )
    ).all()
    counts = {"draft": 0, "published": 0, "archived": 0, "pending": 0}
    for status, count in rows:
        counts[status] = count
    return counts


def _render_grouped_sections(rows: list[Any], x_enabled: bool) -> str:
    """Group rows by (source_kind, source_slug) with Twitter/LinkedIn columns."""
    groups: dict[tuple[str, str], list[Any]] = {}
    for row in rows:
        key = (row.source_kind, row.source_slug)
        groups.setdefault(key, []).append(row)

    if not groups:
        return ""

    sections: list[str] = []
    for (kind, slug), post_rows in groups.items():
        source_link = _source_link(kind, slug)
        twitter_rows = [r for r in post_rows if r.platform == "twitter"]
        linkedin_rows = [r for r in post_rows if r.platform == "linkedin"]

        twitter_html = "".join(
            _render_post_card(r, x_publish_enabled=x_enabled) for r in twitter_rows
        ) or (
            '<div style="color:#5a6472;font-size:13px;padding:12px">No Twitter row</div>'
        )
        linkedin_html = "".join(
            _render_post_card(r, x_publish_enabled=x_enabled) for r in linkedin_rows
        ) or (
            '<div style="color:#5a6472;font-size:13px;padding:12px">No LinkedIn row</div>'
        )

        sections.append(f"""
<div style="margin-bottom:32px;border:1px solid #2a323d;border-radius:8px;overflow:hidden">
  <div style="background:#1d242e;padding:14px 18px;border-bottom:1px solid #2a323d;
              display:flex;align-items:center;gap:12px">
    <span style="font-family:'Fraunces',Georgia,serif;font-size:15px;color:#e8a849">
      Source
    </span>
    {source_link}
    <span style="color:#5a6472;font-size:11px;margin-left:auto;
                 font-family:'IBM Plex Mono',monospace">
      {esc(str(len(post_rows)))} row(s)
    </span>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:0">
    <div style="padding:16px;border-right:1px solid #2a323d">
      <div style="font-family:'IBM Plex Mono',monospace;font-size:11px;
                  text-transform:uppercase;letter-spacing:0.1em;
                  color:#6a7280;margin-bottom:12px">Twitter</div>
      {twitter_html}
    </div>
    <div style="padding:16px">
      <div style="font-family:'IBM Plex Mono',monospace;font-size:11px;
                  text-transform:uppercase;letter-spacing:0.1em;
                  color:#6a7280;margin-bottom:12px">LinkedIn</div>
      {linkedin_html}
    </div>
  </div>
</div>""")
    return "\n".join(sections)


def _render_page(*, title: str, subtitle: str, tab_html: str, body_html: str) -> str:
    """Outer page layout shared by drafts/published/archived."""
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} &mdash; Admin</title>
<style>{ADMIN_CSS}</style>
<link rel="stylesheet" href="/admin-social.css">
<script src="/admin-social.js" defer></script>
</head><body>
{ADMIN_NAV}
<div class="page">
<h1>{esc(title)}</h1>
<div class="subtitle">{subtitle}</div>
{tab_html}
{body_html}
</div>
</body></html>"""


# ---- Route -------------------------------------------------------------------


@router.get("/drafts", response_class=HTMLResponse)
async def admin_social_drafts(
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Listing of pending publish — only status='draft' rows newer than the
    auto-archive cutoff (default 30 days).

    Includes action buttons for draft rows (publish / copy-open / mark-posted /
    discard / edit) wired via /admin-social.js.
    """
    from app.models.social import SocialPost  # slice-1 symbol

    settings = get_settings()
    x_enabled = settings.x_publish_enabled

    counts = await _status_counts(db)
    cutoff = _utcnow() - timedelta(days=_STALE_DRAFT_AGE_DAYS)

    # Visible drafts: created_at within the last 30 days. Stale drafts hide
    # by default; the cron's auto-archive sweep will flip them to archived
    # on the next pass.
    stmt = (
        select(SocialPost)
        .where(SocialPost.status == "draft", SocialPost.created_at >= cutoff)
        .order_by(
            SocialPost.source_kind,
            SocialPost.source_slug,
            SocialPost.platform,
            SocialPost.id.desc(),
        )
    )
    rows = (await db.execute(stmt)).scalars().all()

    # Stale-draft banner — count drafts older than the cutoff so admin knows
    # what's queued for the next auto-archive pass.
    stale_count_stmt = (
        select(func.count()).select_from(SocialPost)
        .where(SocialPost.status == "draft", SocialPost.created_at < cutoff)
    )
    stale_count = (await db.execute(stale_count_stmt)).scalar_one() or 0

    stale_banner = ""
    if stale_count > 0:
        stale_banner = (
            f'<div style="background:#2a1510;border:1px solid #4a3025;border-radius:6px;'
            f'padding:12px 16px;margin-bottom:24px;color:#d97757;font-size:13px;'
            f"font-family:'IBM Plex Mono',monospace\">"
            f'<strong>{esc(str(stale_count))} stale draft(s) ≥ {_STALE_DRAFT_AGE_DAYS} days old</strong> '
            f'&mdash; auto-archive runs after the daily cron. '
            f'<button type="button" class="action-btn"'
            f' data-action="archive-stale-now" style="margin-left:12px;'
            f'background:#4a3025;color:#d97757;border:1px solid #d97757;'
            f"font-family:'IBM Plex Mono',monospace;font-size:11px\">"
            f'Run sweep now</button>'
            f'</div>'
        )

    if not rows:
        body_html = stale_banner + (
            '<div style="background:#1d242e;border-radius:8px;padding:32px;'
            'text-align:center;color:#6a7280;margin-top:24px">'
            '<p style="font-size:16px;margin:0">No social drafts to review.</p>'
            '<p style="font-size:13px;margin:8px 0 0">The daily cron <code>auto_curate_social.sh</code> '
            'generates new drafts at 06:30 IST.</p>'
            '</div>'
        )
    else:
        body_html = stale_banner + _render_grouped_sections(rows, x_enabled)

    tab_html = _render_tab_nav(
        "drafts",
        drafts_count=counts.get("draft", 0),
        pub_count=counts.get("published", 0),
        arch_count=counts.get("archived", 0),
    )
    return _render_page(
        title="Social Drafts",
        subtitle="Opus-curated drafts &bull; publish / edit / discard via action buttons",
        tab_html=tab_html,
        body_html=body_html,
    )


@router.get("/published", response_class=HTMLResponse)
async def admin_social_published(
    source_kind: Optional[str] = Query(default=None),
    platform: Optional[str] = Query(default=None),
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Published rows — admin can Re-publish for a different angle."""
    from app.models.social import SocialPost

    settings = get_settings()
    x_enabled = settings.x_publish_enabled

    counts = await _status_counts(db)

    # Normalize empty-string query params (the filter form's "All" option
    # submits as `?source_kind=` not by omitting the key) and constrain to
    # the known enum to avoid silently filtering on garbage input.
    source_kind = source_kind if source_kind in ("blog", "course") else None
    platform = platform if platform in ("twitter", "linkedin") else None

    where = [SocialPost.status == "published"]
    if source_kind:
        where.append(SocialPost.source_kind == source_kind)
    if platform:
        where.append(SocialPost.platform == platform)

    stmt = (
        select(SocialPost)
        .where(*where)
        .order_by(
            SocialPost.published_at.desc(),
            SocialPost.id.desc(),
        )
    )
    rows = (await db.execute(stmt)).scalars().all()

    filter_html = _render_filter_form(source_kind or "", platform or "",
                                      "/admin/social/published")
    if not rows:
        body_html = filter_html + (
            '<div style="background:#1d242e;border-radius:8px;padding:32px;'
            'text-align:center;color:#6a7280;margin-top:24px">'
            '<p style="font-size:16px;margin:0">No published posts yet.</p>'
            '</div>'
        )
    else:
        body_html = filter_html + _render_grouped_sections(rows, x_enabled)

    tab_html = _render_tab_nav(
        "published",
        drafts_count=counts.get("draft", 0),
        pub_count=counts.get("published", 0),
        arch_count=counts.get("archived", 0),
    )
    return _render_page(
        title="Social Published",
        subtitle="Live posts &bull; Re-publish for a different angle",
        tab_html=tab_html,
        body_html=body_html,
    )


@router.get("/archived", response_class=HTMLResponse)
async def admin_social_archived(
    source_kind: Optional[str] = Query(default=None),
    platform: Optional[str] = Query(default=None),
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Archived rows — terminal. Includes admin discards, max-retry archives,
    and the 30-day stale-draft sweep."""
    from app.models.social import SocialPost

    settings = get_settings()
    x_enabled = settings.x_publish_enabled

    counts = await _status_counts(db)

    source_kind = source_kind if source_kind in ("blog", "course") else None
    platform = platform if platform in ("twitter", "linkedin") else None

    where = [SocialPost.status == "archived"]
    if source_kind:
        where.append(SocialPost.source_kind == source_kind)
    if platform:
        where.append(SocialPost.platform == platform)

    stmt = (
        select(SocialPost)
        .where(*where)
        .order_by(
            SocialPost.archived_at.desc(),
            SocialPost.id.desc(),
        )
    )
    rows = (await db.execute(stmt)).scalars().all()

    filter_html = _render_filter_form(source_kind or "", platform or "",
                                      "/admin/social/archived")
    if not rows:
        body_html = filter_html + (
            '<div style="background:#1d242e;border-radius:8px;padding:32px;'
            'text-align:center;color:#6a7280;margin-top:24px">'
            '<p style="font-size:16px;margin:0">No archived rows.</p>'
            '</div>'
        )
    else:
        body_html = filter_html + _render_grouped_sections(rows, x_enabled)

    tab_html = _render_tab_nav(
        "archived",
        drafts_count=counts.get("draft", 0),
        pub_count=counts.get("published", 0),
        arch_count=counts.get("archived", 0),
    )
    return _render_page(
        title="Social Archived",
        subtitle="Terminal rows &bull; admin discards, max-retry archives, stale-30d",
        tab_html=tab_html,
        body_html=body_html,
    )


# ============================================================================
# POST endpoints — publish loop (slice 1 of session b)
# ============================================================================


@router.post("/publish/{post_id}")
async def publish_post(
    post_id: int,
    request: Request,
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Publish a Twitter draft directly via X API v2.

    Race-condition guard: only proceeds if the row is currently in 'draft'
    status. Concurrent publishes on the same row collide on the WHERE clause.

    Returns 200 with {"id", "published_url", "published_at", "tweet_id"} on success.
    Returns 503 if x_publish_enabled is False.
    Returns 400 for non-Twitter rows (LinkedIn uses Mark-as-posted only).
    Returns 409 if the row is missing or not in draft status.
    Returns 502 + body excerpt if the X API call fails.
    """
    _csrf_check(request)
    settings = get_settings()
    if not settings.x_publish_enabled:
        raise HTTPException(
            status_code=503,
            detail="X publishing disabled — use Mark-as-posted flow instead",
        )

    from app.models.social import SocialPost

    row = (await db.execute(
        select(SocialPost).where(SocialPost.id == post_id, SocialPost.status == "draft")
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=409, detail="Row not found or not in draft state")
    if row.platform != "twitter":
        raise HTTPException(
            status_code=400,
            detail="Publish endpoint is Twitter-only; use /mark-posted for LinkedIn",
        )
    if not row.body:
        raise HTTPException(status_code=400, detail="Row has no body to publish")

    creds = twitter_client.credentials_from_env()
    if creds is None:
        raise HTTPException(status_code=503, detail="Twitter credentials not configured")

    try:
        data = await twitter_client.post_tweet(creds, row.body)
    except twitter_client.TwitterAPIError as exc:
        excerpt = (exc.body_excerpt or "")[:200]
        raise HTTPException(
            status_code=502,
            detail=f"X API error (status={exc.status}): {excerpt}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    tweet_id = data.get("id")
    if not tweet_id:
        raise HTTPException(status_code=502, detail="X API returned no tweet id")
    published_url = twitter_client.tweet_url(str(tweet_id))
    now = _utcnow()

    # Atomic state flip — only updates if still in draft (defense in depth)
    result = await db.execute(
        update(SocialPost)
        .where(SocialPost.id == post_id, SocialPost.status == "draft")
        .values(
            status="published",
            published_at=now,
            published_url=published_url,
            updated_at=now,
        )
    )
    if result.rowcount == 0:
        # Row was concurrently modified; tweet is already posted but state lost
        # — log loudly so admin can manually reconcile.
        import logging
        logging.getLogger(__name__).error(
            "publish_post: tweet posted (id=%s) but row %s no longer in draft — manual reconcile needed",
            tweet_id, post_id,
        )
        raise HTTPException(
            status_code=409,
            detail=f"Tweet posted at {published_url} but DB state was concurrently modified — reconcile manually",
        )
    await db.commit()
    return {
        "id": post_id,
        "published_url": published_url,
        "published_at": now.isoformat(),
        "tweet_id": str(tweet_id),
    }


@router.post("/mark-posted/{post_id}")
async def mark_posted(
    post_id: int,
    request: Request,
    payload: _MarkAsPostedRequest = Body(...),
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Manual flow: admin posted the draft externally (LinkedIn or Twitter
    when x_publish_enabled=False), now records the live URL.

    Race-condition guard: only proceeds if status='draft'.
    """
    _csrf_check(request)

    from app.models.social import SocialPost

    now = _utcnow()
    result = await db.execute(
        update(SocialPost)
        .where(SocialPost.id == post_id, SocialPost.status == "draft")
        .values(
            status="published",
            published_at=now,
            published_url=payload.published_url,
            updated_at=now,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=409, detail="Row not found or not in draft state")
    await db.commit()
    return {
        "id": post_id,
        "published_url": payload.published_url,
        "published_at": now.isoformat(),
    }


@router.post("/discard/{post_id}")
async def discard_post(
    post_id: int,
    request: Request,
    payload: _DiscardRequest = Body(...),
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin discards a draft. Status flips draft → archived; reason recorded
    in reasoning_json under archive_reason."""
    _csrf_check(request)

    from app.models.social import SocialPost

    row = (await db.execute(
        select(SocialPost).where(SocialPost.id == post_id, SocialPost.status == "draft")
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=409, detail="Row not found or not in draft state")

    # Append archive metadata to reasoning_json (preserve existing fields)
    existing = _parse_json_field(row.reasoning_json, {}) or {}
    if not isinstance(existing, dict):
        existing = {"_legacy": existing}
    now = _utcnow()
    existing["archive_reason"] = (payload.reason or "admin_discard")
    existing["archived_at"] = now.isoformat()

    result = await db.execute(
        update(SocialPost)
        .where(SocialPost.id == post_id, SocialPost.status == "draft")
        .values(
            status="archived",
            archived_at=now,
            updated_at=now,
            reasoning_json=json.dumps(existing),
        )
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=409, detail="Row was concurrently modified")
    await db.commit()
    return {"id": post_id, "status": "archived", "archived_at": now.isoformat()}


@router.post("/edit/{post_id}")
async def edit_draft(
    post_id: int,
    request: Request,
    payload: _EditDraftRequest = Body(...),
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Persist body + hashtag edits on a draft row. Validates against
    platform-specific length + brand-canonical hashtag rules."""
    _csrf_check(request)

    from app.models.social import SocialPost

    row = (await db.execute(
        select(SocialPost).where(SocialPost.id == post_id, SocialPost.status == "draft")
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=409, detail="Row not found or not in draft state")

    try:
        validated_body = _validate_body(payload.body, row.platform)
        validated_tags = _validate_hashtags(payload.hashtags, row.platform)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    now = _utcnow()
    result = await db.execute(
        update(SocialPost)
        .where(SocialPost.id == post_id, SocialPost.status == "draft")
        .values(
            body=validated_body,
            hashtags_json=json.dumps(validated_tags),
            updated_at=now,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=409, detail="Row was concurrently modified")
    await db.commit()
    return {"id": post_id, "body": validated_body, "hashtags": validated_tags}


# ============================================================================
# Slice 2 — Re-publish + auto-archive sweep
# ============================================================================


@router.post("/re-publish/{post_id}")
async def re_publish_post(
    post_id: int,
    request: Request,
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Queue a fresh pending pair for the source of an already-published row.

    The new rows carry markers in reasoning_json (`_re_publish: true`,
    `_parent_post_id: N`) so the cron's repub-mode pickup can fetch the prior
    body and inject it into the next Opus prompt as `prior_drafts` context —
    asking Opus for a different angle, not a regeneration.

    The old `published` row is preserved as-is for history.

    Returns 409 if the source already has active pending/draft rows (the
    partial UNIQUE index `uq_social_posts_active` blocks double-queueing).
    """
    _csrf_check(request)

    from app.models.social import SocialPost

    parent = (await db.execute(
        select(SocialPost).where(
            SocialPost.id == post_id, SocialPost.status == "published"
        )
    )).scalar_one_or_none()
    if parent is None:
        raise HTTPException(
            status_code=409, detail="Row not found or not in published state"
        )

    # Block if any pending/draft rows already exist for this source — the
    # partial UNIQUE index would also block, but a friendly 409 is nicer than
    # a 500.
    blocker = (await db.execute(
        select(func.count()).select_from(SocialPost)
        .where(
            SocialPost.source_kind == parent.source_kind,
            SocialPost.source_slug == parent.source_slug,
            SocialPost.status.in_(["pending", "draft"]),
        )
    )).scalar_one() or 0
    if blocker > 0:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Source already has {blocker} active pending/draft row(s); "
                "discard or publish them first before re-queuing."
            ),
        )

    now = _utcnow()
    marker = json.dumps({
        "_re_publish": True,
        "_parent_post_id": parent.id,
    })
    twitter_row = SocialPost(
        source_kind=parent.source_kind,
        source_slug=parent.source_slug,
        platform="twitter",
        status="pending",
        body=None,
        hashtags_json=None,
        reasoning_json=marker,
        retry_count=0,
        published_url=None,
        created_at=now,
        updated_at=now,
    )
    linkedin_row = SocialPost(
        source_kind=parent.source_kind,
        source_slug=parent.source_slug,
        platform="linkedin",
        status="pending",
        body=None,
        hashtags_json=None,
        reasoning_json=marker,
        retry_count=0,
        published_url=None,
        created_at=now,
        updated_at=now,
    )
    db.add(twitter_row)
    db.add(linkedin_row)
    try:
        await db.commit()
    except Exception as exc:
        # The partial UNIQUE index uq_social_posts_active catches the rare
        # race where two re-publish clicks land within microseconds of each
        # other (between blocker check and commit). Surface a friendly 409
        # rather than a 500.
        await db.rollback()
        msg = str(exc).lower()
        if "unique" in msg or "constraint" in msg:
            raise HTTPException(
                status_code=409,
                detail="Source already has an active pending/draft row (race) — refresh and try again",
            )
        raise

    return {
        "id": post_id,
        "queued": [twitter_row.id, linkedin_row.id],
        "status": "pending",
    }


@router.post("/archive-stale-now")
async def archive_stale_now(
    request: Request,
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger the 30-day stale-draft sweep. Same logic as the cron's
    auto_archive_stale.py — flips drafts ≥ _STALE_DRAFT_AGE_DAYS old to
    archived with reason='stale_30d'."""
    _csrf_check(request)

    from app.models.social import SocialPost

    cutoff = _utcnow() - timedelta(days=_STALE_DRAFT_AGE_DAYS)
    rows = (await db.execute(
        select(SocialPost).where(
            SocialPost.status == "draft",
            SocialPost.created_at < cutoff,
        )
    )).scalars().all()

    archived = 0
    now = _utcnow()
    for row in rows:
        existing = _parse_json_field(row.reasoning_json, {}) or {}
        if not isinstance(existing, dict):
            existing = {"_legacy": existing}
        existing["archive_reason"] = "stale_30d"
        existing["archived_at"] = now.isoformat()
        result = await db.execute(
            update(SocialPost)
            .where(SocialPost.id == row.id, SocialPost.status == "draft")
            .values(
                status="archived",
                archived_at=now,
                updated_at=now,
                reasoning_json=json.dumps(existing),
            )
        )
        if result.rowcount == 1:
            archived += 1
    await db.commit()
    return {"archived": archived}
