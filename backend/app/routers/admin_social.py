"""Admin router for Social Drafts review page.

Mounted at /admin/social (prefix set in main.py). Requires get_current_admin.

GET /admin/social/drafts — read-only listing of social_posts rows with
  status IN ('draft', 'archived'), grouped by (source_kind, source_slug)
  with Twitter and LinkedIn side-by-side per source.

Actions (publish, edit, discard) ship in session (b).

RCA-008 caution: body content comes from DB as plain text. We always pass it
through html.escape() before embedding in HTML. No f-string body interpolation
without escaping — use the esc() alias throughout.
"""

from __future__ import annotations

import json
from html import escape as esc
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_admin
from app.db import get_db
from app.models.user import User
from app.utils.time_fmt import fmt_ist, FMT_SHORT

router = APIRouter()

# Import shared admin UI constants from admin.py
from app.routers.admin import ADMIN_CSS, ADMIN_NAV


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
    if status == "archived":
        return (
            '<span style="background:#2a1510;color:#d97757;border:1px solid #4a3025;'
            'padding:2px 8px;border-radius:3px;font-family:\'IBM Plex Mono\',monospace;'
            'font-size:10px;letter-spacing:0.08em;text-transform:uppercase">Archived</span>'
        )
    return esc(status)


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


def _render_post_card(row: Any) -> str:
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

    return f"""
<div style="background:#1a2030;border-radius:6px;padding:16px;margin-bottom:12px;
            border:1px solid #2a323d">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
    {platform_html}
    {status_html}
    <span style="color:#5a6472;font-size:11px;font-family:'IBM Plex Mono',monospace;
                 margin-left:auto">#{esc(str(row.id))}</span>
  </div>
  <div style="background:#0f1419;border-radius:4px;padding:12px;margin-bottom:10px;
              white-space:pre-wrap;font-size:13px;color:#d0cbc2;
              font-family:'IBM Plex Sans',system-ui,sans-serif;line-height:1.6">{body_safe}</div>
  <div style="margin-bottom:6px;font-size:12px;color:#6a7280">
    Hashtags: {hashtags_html}
  </div>
  {archive_note}
  {reasoning_html}
  <div style="margin-top:10px;border-top:1px solid #2a323d;padding-top:8px;
              font-size:11px;color:#5a6472;font-family:'IBM Plex Mono',monospace">
    created: {esc(fmt_ist(row.created_at))} &nbsp;&bull;&nbsp;
    updated: {esc(fmt_ist(row.updated_at))}
  </div>
  <p style="color:#5a6472;font-size:11px;margin-top:8px;margin-bottom:0;
            font-style:italic">Actions ship in session (b)</p>
</div>"""


# ---- Route -------------------------------------------------------------------


@router.get("/drafts", response_class=HTMLResponse)
async def admin_social_drafts(
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Read-only listing of social_posts with status in (draft, archived).

    Grouped by (source_kind, source_slug) — Twitter and LinkedIn side-by-side.
    """
    from app.models.social import SocialPost  # slice-1 symbol

    stmt = (
        select(SocialPost)
        .where(SocialPost.status.in_(["draft", "archived"]))
        .order_by(
            SocialPost.source_kind,
            SocialPost.source_slug,
            SocialPost.platform,
            SocialPost.id.desc(),
        )
    )
    rows = (await db.execute(stmt)).scalars().all()

    # Group by (source_kind, source_slug)
    groups: dict[tuple[str, str], list[Any]] = {}
    for row in rows:
        key = (row.source_kind, row.source_slug)
        groups.setdefault(key, []).append(row)

    if not groups:
        content = (
            '<div style="background:#1d242e;border-radius:8px;padding:32px;'
            'text-align:center;color:#6a7280;margin-top:24px">'
            '<p style="font-size:16px;margin:0">No social drafts yet.</p>'
            '<p style="font-size:13px;margin:8px 0 0">Run <code>auto_curate_social.sh</code> '
            'to generate drafts.</p>'
            '</div>'
        )
    else:
        sections: list[str] = []
        for (kind, slug), post_rows in groups.items():
            source_link = _source_link(kind, slug)
            # Split by platform for side-by-side layout
            twitter_rows = [r for r in post_rows if r.platform == "twitter"]
            linkedin_rows = [r for r in post_rows if r.platform == "linkedin"]

            twitter_html = "".join(_render_post_card(r) for r in twitter_rows) or (
                '<div style="color:#5a6472;font-size:13px;padding:12px">No Twitter draft</div>'
            )
            linkedin_html = "".join(_render_post_card(r) for r in linkedin_rows) or (
                '<div style="color:#5a6472;font-size:13px;padding:12px">No LinkedIn draft</div>'
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

        content = "\n".join(sections)

    total_count = len(rows)
    draft_count = sum(1 for r in rows if r.status == "draft")
    archived_count = sum(1 for r in rows if r.status == "archived")

    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Social Drafts — Admin</title>
<style>{ADMIN_CSS}</style>
</head><body>
{ADMIN_NAV}
<div class="page">
<h1>Social Drafts</h1>
<div class="subtitle">Opus-curated drafts pending publish &bull; session (b) adds publish actions</div>
<div style="display:flex;gap:12px;margin-bottom:24px;flex-wrap:wrap">
  <div class="stat">
    <div class="num">{total_count}</div>
    <div class="lbl">Total rows</div>
  </div>
  <div class="stat">
    <div class="num" style="color:#6db585">{draft_count}</div>
    <div class="lbl">Draft</div>
  </div>
  <div class="stat">
    <div class="num" style="color:#d97757">{archived_count}</div>
    <div class="lbl">Archived</div>
  </div>
</div>
{content}
</div>
</body></html>"""
