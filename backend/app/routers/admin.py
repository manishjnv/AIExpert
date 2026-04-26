"""
Admin router — dashboard stats, user management, curriculum proposals.

All endpoints under /admin (prefix set in main.py). Protected by get_current_admin.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape as esc

from app.utils.time_fmt import fmt_ist, FMT_SHORT, FMT_DATE, iso_utc_z
from app.utils.admin_ui import workflow_steps

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_admin
from app.db import get_db
from app.models.curriculum import CurriculumProposal, LinkHealth
from app.models.plan import UserPlan
from app.models.user import User

router = APIRouter()


def _check_origin(request: Request) -> None:
    """Basic CSRF mitigation: verify Origin/Referer matches our host."""
    origin = request.headers.get("origin") or request.headers.get("referer", "")
    host = request.headers.get("host", "")
    if origin and host and host not in origin:
        raise HTTPException(status_code=403, detail="Origin mismatch")


# ---- API endpoints ----

@router.get("/api/dashboard")
async def dashboard(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin dashboard stats."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    total_users = await db.scalar(select(func.count()).select_from(User)) or 0

    # DAU/WAU/MAU based on session issued_at (approximation)
    from app.models.user import Session as SessionModel
    dau = await db.scalar(
        select(func.count(func.distinct(SessionModel.user_id)))
        .where(SessionModel.issued_at > now - timedelta(days=1))
    ) or 0
    wau = await db.scalar(
        select(func.count(func.distinct(SessionModel.user_id)))
        .where(SessionModel.issued_at > now - timedelta(days=7))
    ) or 0
    mau = await db.scalar(
        select(func.count(func.distinct(SessionModel.user_id)))
        .where(SessionModel.issued_at > now - timedelta(days=30))
    ) or 0

    # Recent signups (last 7 days)
    recent_signups = (
        await db.execute(
            select(User.id, User.email, User.name, User.created_at)
            .where(User.created_at > now - timedelta(days=7))
            .order_by(User.created_at.desc())
            .limit(20)
        )
    ).all()

    # Dead links count
    dead_links = await db.scalar(
        select(func.count()).select_from(LinkHealth)
        .where(LinkHealth.consecutive_failures > 2)
    ) or 0

    return {
        "total_users": total_users,
        "dau": dau,
        "wau": wau,
        "mau": mau,
        "dead_links": dead_links,
        "recent_signups": [
            {"id": r.id, "email": r.email, "name": r.name,
             "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in recent_signups
        ],
    }


@router.get("/api/users")
async def list_users(
    q: str = Query("", description="Search by email or name"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Paginated user listing."""
    query = select(User)
    if q:
        query = query.where(
            User.email.contains(q) | User.name.contains(q)
        )
    query = query.order_by(User.created_at.desc())

    total = await db.scalar(
        select(func.count()).select_from(query.subquery())
    ) or 0

    rows = (
        await db.execute(
            query.offset((page - 1) * per_page).limit(per_page)
        )
    ).scalars().all()

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "name": u.name,
                "provider": u.provider,
                "is_admin": u.is_admin,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in rows
        ],
    }


@router.get("/api/proposals")
async def list_proposals(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List curriculum proposals."""
    rows = (
        await db.execute(
            select(CurriculumProposal).order_by(CurriculumProposal.created_at.desc())
        )
    ).scalars().all()

    return [
        {
            "id": p.id,
            "source_run": p.source_run,
            "status": p.status,
            "notes": p.notes,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "reviewed_at": p.reviewed_at.isoformat() if p.reviewed_at else None,
        }
        for p in rows
    ]


@router.post("/api/proposals/{proposal_id}/apply")
async def apply_proposal(
    proposal_id: int,
    request: Request,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Mark a proposal as applied."""
    _check_origin(request)
    proposal = await db.get(CurriculumProposal, proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    proposal.status = "applied"
    proposal.reviewer_id = user.id
    proposal.reviewed_at = now
    await db.flush()
    return {"ok": True, "status": "applied"}


@router.post("/api/proposals/{proposal_id}/reject")
async def reject_proposal(
    proposal_id: int,
    request: Request,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Mark a proposal as rejected."""
    _check_origin(request)
    proposal = await db.get(CurriculumProposal, proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    proposal.status = "rejected"
    proposal.reviewer_id = user.id
    proposal.reviewed_at = now
    await db.flush()
    return {"ok": True, "status": "rejected"}


@router.post("/api/generate-template")
async def generate_template(
    request: Request,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Generate a new curriculum template using AI."""
    _check_origin(request)
    body = await request.json()
    topic = body.get("topic", "").strip()
    duration = int(body.get("duration", 6))
    level = body.get("level", "intermediate")

    if not topic:
        raise HTTPException(status_code=400, detail="Topic is required")
    if duration not in (3, 6, 9, 12):
        raise HTTPException(status_code=400, detail="Duration must be 3, 6, 9, or 12 months")
    if level not in ("beginner", "intermediate", "advanced"):
        raise HTTPException(status_code=400, detail="Level must be beginner, intermediate, or advanced")

    from app.services.curriculum_generator import generate_curriculum, save_curriculum_draft
    from app.ai.provider import AIProviderError

    try:
        plan_data = await generate_curriculum(topic, duration, level, db=db)
        path = await save_curriculum_draft(plan_data)
        return {
            "ok": True,
            "key": plan_data.get("key"),
            "title": plan_data.get("title"),
            "weeks": sum(len(m.get("weeks", [])) for m in plan_data.get("months", [])),
            "path": path,
        }
    except AIProviderError as e:
        raise HTTPException(status_code=503, detail=f"AI unavailable: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")


@router.get("/api/templates")
async def list_admin_templates(
    _user: User = Depends(get_current_admin),
):
    """List all templates with file details and publish status for admin."""
    from app.curriculum.loader import list_templates, load_template, get_template_status
    grandfathered = {"generalist_3mo_intermediate", "generalist_6mo_intermediate", "generalist_12mo_beginner"}
    keys = list_templates()
    result = []
    for key in sorted(keys):
        try:
            tpl = load_template(key)
            status_info = get_template_status(key)
            pub_status = status_info.get("status", "draft")
            if key in grandfathered and pub_status == "draft":
                pub_status = "published"
            result.append({
                "key": tpl.key,
                "title": tpl.title,
                "goal": tpl.goal,
                "level": tpl.level,
                "duration_months": tpl.duration_months,
                "total_weeks": tpl.total_weeks,
                "total_checks": tpl.total_checks,
                "publish_status": pub_status,
                "quality_score": status_info.get("quality_score", 0),
            })
        except Exception:
            continue
    return result


@router.get("/api/templates/{key}")
async def get_template_detail(
    key: str,
    _user: User = Depends(get_current_admin),
):
    """Get full template content for admin review."""
    from app.curriculum.loader import load_template
    try:
        tpl = load_template(key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Template not found")
    return tpl.model_dump()


@router.get("/templates/{key}", response_class=HTMLResponse)
async def admin_template_view(
    key: str,
    _user: User = Depends(get_current_admin),
):
    """Admin template detail page — view full curriculum content."""
    from app.curriculum.loader import load_template, get_template_status

    try:
        tpl = load_template(key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Template not found")

    status_info = get_template_status(key)
    pub_status = status_info.get("status", "draft")
    grandfathered = {"generalist_3mo_intermediate", "generalist_6mo_intermediate", "generalist_12mo_beginner"}
    if key in grandfathered and pub_status == "draft":
        pub_status = "published"
    q_score = status_info.get("quality_score", 0)

    status_color = "#6db585" if pub_status == "published" else "#e8a849"
    score_color = "#6db585" if q_score >= 90 else "#e8a849" if q_score >= 70 else "#d97757" if q_score > 0 else "#8a92a0"

    months_html = ""
    for m in tpl.months:
        weeks_html = ""
        for w in m.weeks:
            resources_html = "".join(
                f'<li><a href="{esc(r.url)}" target="_blank" style="color:#e8a849">{esc(r.name)}</a> <span style="color:#8a92a0">({r.hrs}h)</span></li>'
                for r in w.resources
            )
            checks_html = "".join(f"<li>{esc(c)}</li>" for c in w.checks)
            focus_html = " · ".join(esc(f) for f in w.focus)
            deliv_html = "".join(f"<li>{esc(d)}</li>" for d in w.deliv)

            weeks_html += f"""
            <div style="background:#0f1419;border-radius:6px;padding:16px;margin-bottom:12px">
                <h4 style="margin:0 0 8px">Week {w.n}: {esc(w.t)} <span style="color:#8a92a0;font-weight:400;font-size:12px">({w.hours}h)</span></h4>
                <div style="font-size:12px;color:#8a92a0;margin-bottom:8px">{focus_html}</div>
                {'<div style="margin-bottom:8px"><strong style="font-size:12px;color:#e8a849">Deliverables</strong><ul style="margin:4px 0;padding-left:20px;font-size:13px">' + deliv_html + '</ul></div>' if w.deliv else ''}
                {'<div style="margin-bottom:8px"><strong style="font-size:12px;color:#6db585">Resources</strong><ul style="margin:4px 0;padding-left:20px;font-size:13px">' + resources_html + '</ul></div>' if w.resources else ''}
                {'<div><strong style="font-size:12px;color:#d0cbc2">Checklist</strong><ul style="margin:4px 0;padding-left:20px;font-size:13px">' + checks_html + '</ul></div>' if w.checks else ''}
            </div>"""

        months_html += f"""
        <div style="margin-bottom:24px">
            <h3 style="color:#e8a849;margin-bottom:4px">{esc(m.label)}: {esc(m.title)}</h3>
            <p style="font-size:13px;color:#8a92a0;margin-bottom:4px"><em>{esc(m.tagline)}</em></p>
            <p style="font-size:12px;color:#6db585;margin-bottom:12px">Checkpoint: {esc(m.checkpoint)}</p>
            {weeks_html}
        </div>"""

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>{esc(tpl.title)}</title>
<style>{ADMIN_CSS}</style></head><body>
{ADMIN_NAV}
<div class="page">
<div style="margin-bottom:16px"><a href="/admin/templates" style="color:#8a92a0;font-size:13px">&larr; Back to Templates</a></div>
<h1>{esc(tpl.title)}</h1>
<div style="display:flex;gap:12px;align-items:center;margin-bottom:16px">
    <span style="color:{status_color};font-weight:600">{pub_status.title()}</span>
    <span style="color:#8a92a0">·</span>
    <span>{esc(tpl.level)} · {tpl.duration_months}mo · {tpl.total_weeks} weeks · {tpl.total_checks} checks</span>
    <span style="color:#8a92a0">·</span>
    <span style="color:{score_color};font-weight:600">Quality: {q_score if q_score else '—'}</span>
</div>
<p style="color:#8a92a0;font-size:13px;margin-bottom:24px">{esc(tpl.goal)}</p>
{months_html}
</div></body></html>"""


@router.delete("/api/templates/{key}")
async def delete_template(
    key: str,
    request: Request,
    _user: User = Depends(get_current_admin),
):
    """Delete a template file."""
    _check_origin(request)
    from pathlib import Path
    path = Path(__file__).parent.parent / "curriculum" / "templates" / f"{key}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Template not found")
    # Don't delete the 3 original generalist templates
    if key.startswith("generalist_"):
        raise HTTPException(status_code=400, detail="Cannot delete default generalist templates")
    path.unlink()
    from app.curriculum.loader import load_template
    load_template.cache_clear()
    return {"ok": True, "deleted": key}


# ---- Jinja2 admin UI ----

ADMIN_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,400;9..144,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');
body { font-family: 'IBM Plex Sans', system-ui, sans-serif; background: #0f1419; color: #e0dbd2; margin: 0; padding: 0; -webkit-font-smoothing: antialiased; font-size: 14px; line-height: 1.6; }
.page { max-width: 100%; margin: 0; padding: 32px 48px; }
h1 { font-family: 'Fraunces', Georgia, serif; color: #e8a849; font-size: 28px; font-weight: 300; margin-bottom: 4px; }
h2 { font-family: 'Fraunces', Georgia, serif; color: #e8a849; font-size: 18px; margin-top: 24px; }
h3 { font-family: 'Fraunces', Georgia, serif; color: #e8a849; font-size: 15px; }
p { color: #b0aaa0; line-height: 1.6; }
.subtitle { color: #6a7280; font-size: 13px; margin-bottom: 24px; font-family: 'IBM Plex Mono', monospace; letter-spacing: 0.03em; }
.stat { display: inline-block; background: #1d242e; padding: 16px 24px; border-radius: 6px; margin: 4px; text-align: center; }
.stat .num { font-family: 'Fraunces', Georgia, serif; font-size: 28px; font-weight: 400; color: #e8a849; }
.stat .lbl { font-family: 'IBM Plex Mono', monospace; font-size: 9px; text-transform: uppercase; letter-spacing: 0.12em; color: #6a7280; margin-top: 2px; }
table { width: 100%; border-collapse: collapse; margin-top: 12px; }
th { text-align: left; padding: 10px 8px; font-family: 'IBM Plex Mono', monospace; font-size: 10px; text-transform: uppercase; letter-spacing: 0.12em; color: #6a7280; border-bottom: 1px solid #2a323d; }
td { padding: 10px 8px; font-size: 13px; border-bottom: 1px solid #1d242e; color: #d0cbc2; }
.btn { font-family: 'IBM Plex Mono', monospace; font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; padding: 8px 14px; background: transparent; border: 1px solid #3a4452; color: #e8e2d3; cursor: pointer; transition: all 0.2s; border-radius: 2px; }
.btn:hover { border-color: #e8a849; color: #e8a849; }
.btn.success { border-color: #6db585; color: #6db585; }
.btn.danger { border-color: #d97757; color: #d97757; }
.card { background: #1d242e; padding: 16px; border-radius: 6px; }
@media (max-width: 768px) { .page { padding: 20px 16px; } .stat { padding: 12px 14px; } .stat .num { font-size: 22px; } }
"""

ADMIN_NAV = '<link rel="stylesheet" href="/nav.css"><script src="/nav.js"></script>'


# ---------------- Blog prompt generator ----------------
#
# Mirrors the Claude-Opus-manual workflow used for curriculum templates:
# admin supplies a title (and optional thesis), backend renders the
# full editorial prompt with placeholders substituted, admin copies
# into Claude.ai Max and pastes the returned markdown into docs/blog/
# + backend/app/routers/blog.py. No AI call on our dime, no DB state,
# no auto-publish — learner-first content gating is preserved.


def _next_blog_slug() -> str:
    """Read docs/blog/ for existing NN-*.md files and return NN+1 zero-padded."""
    from pathlib import Path as _Path
    import re as _re
    blog_dir = _Path(__file__).parent.parent.parent.parent / "docs" / "blog"
    max_n = 0
    if blog_dir.exists():
        for f in blog_dir.glob("*.md"):
            m = _re.match(r"(\d+)-", f.stem)
            if m:
                try:
                    max_n = max(max_n, int(m.group(1)))
                except ValueError:
                    pass
    return f"{max_n + 1:02d}"


def _slugify_title(title: str) -> str:
    import re as _re
    s = _re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:60]


def _build_internal_url_manifest() -> str:
    """Bulleted list of every internal URL a pillar post may link to.
    Injected into the pillar prompt so Claude hits the >=40 internal-link
    gate without hallucinating routes. Anything not in this manifest will
    404 on visitors and fail the validator's internal-link count."""
    from app.routers.track_pages import all_track_slugs, all_section_slugs
    from app.routers.compare import all_slugs as _vs_slugs
    from app.services.blog_publisher import list_published

    tracks = all_track_slugs()
    sections = all_section_slugs()
    vs_slugs = _vs_slugs()
    published_posts = list_published()

    lines: list[str] = []
    lines.append("HOME + HUBS")
    lines.append("  /                  (home)")
    lines.append("  /roadmap           (roadmap hub — 5 tracks)")
    lines.append("  /jobs              (AI jobs board)")
    lines.append("  /leaderboard       (learner leaderboard)")
    lines.append("  /blog              (blog index)")
    lines.append("  /vs                (comparison index)")
    lines.append("  /verify            (credential verification)")
    lines.append("")

    lines.append(f"TRACK HUBS ({len(tracks)} tracks)")
    for t in tracks:
        lines.append(f"  /roadmap/{t}")
    lines.append("")

    lines.append(
        f"TRACK QUINTET PAGES ({len(tracks)} tracks x {len(sections)} sections "
        f"= {len(tracks) * len(sections)} pages — use these liberally, they target long-tail queries)"
    )
    for t in tracks:
        for s in sections:
            lines.append(f"  /roadmap/{t}/{s}")
    lines.append("")

    if vs_slugs:
        lines.append(f"COMPARISON PAGES ({len(vs_slugs)})")
        for s in vs_slugs:
            lines.append(f"  /vs/{s}")
        lines.append("")

    lines.append("EXISTING BLOG POSTS")
    lines.append("  /blog/01           (Building AutomateEdge Solo — build-in-public retrospective)")
    for p in published_posts:
        slug = str(p.get("slug") or "").strip()
        if not slug or slug == "01":
            continue
        title = str(p.get("title") or "").strip()[:70]
        lines.append(f"  /blog/{slug:<18} ({title})")

    return "\n".join(lines)


def _build_trusted_sources_digest() -> str:
    """Grouped list of trusted citation domains (SEO-25 allowlist),
    rendered compactly for the pillar prompt. Claude must pick >=5
    distinct URLs across >=3 categories from this list."""
    from app.services.blog_validator import load_trusted_sources
    trusted = load_trusted_sources()
    by_cat = trusted.get("by_category", {})
    if not by_cat:
        return "(trusted_sources.json missing — pillar validation will fail)"

    cat_order = ["papers", "lab-docs", "framework-docs", "statistics",
                 "academic", "textbook", "standards"]
    seen: set[str] = set()
    ordered: list[str] = [c for c in cat_order if c in by_cat] + \
                        [c for c in sorted(by_cat) if c not in cat_order]

    lines: list[str] = []
    for cat in ordered:
        if cat in seen:
            continue
        seen.add(cat)
        domains = sorted(by_cat.get(cat, set()))
        if not domains:
            continue
        lines.append(f"{cat.upper()} ({len(domains)})")
        for d in domains:
            lines.append(f"  {d}")
        lines.append("")
    return "\n".join(lines).rstrip()


@router.post("/api/render-blog-prompt")
async def render_blog_prompt(
    request: Request,
    user: User = Depends(get_current_admin),
):
    """Render a blog prompt (standard or pillar) with the admin's inputs
    substituted. Returns prompt text + derived slug so the admin can
    paste straight into Claude.ai. Tier determines the template + gates:
      - standard  → claude_blog_manual.txt (800-1500 word essay)
      - pillar    → claude_blog_pillar.txt, SEO-21 bar, >=3000 words
      - flagship  → claude_blog_pillar.txt, SEO-21 bar, >=4500 words
    """
    _check_origin(request)
    from pathlib import Path as _Path
    from datetime import date as _date
    import json as _json

    body = await request.json()
    title = (body.get("title") or "").strip()
    angle = (body.get("angle") or "").strip()
    tier = (body.get("tier") or "standard").strip().lower()

    if tier not in {"standard", "pillar", "flagship"}:
        raise HTTPException(status_code=400, detail="tier must be 'standard', 'pillar', or 'flagship'")
    if not title:
        raise HTTPException(status_code=400, detail="title required")
    if len(title) > 150:
        raise HTTPException(status_code=400, detail="title too long (max 150 chars)")

    prefix = _next_blog_slug()
    slug_body = _slugify_title(title)
    slug = f"{prefix}-{slug_body}" if slug_body else prefix

    prompts_dir = _Path(__file__).parent.parent / "prompts"

    if tier == "standard":
        template = (prompts_dir / "claude_blog_manual.txt").read_text(encoding="utf-8")
        rendered = (
            template
            .replace("{{TITLE}}", title)
            .replace("{{ANGLE}}", angle or "(none — use your judgement, but stay on-topic)")
            .replace("{{SLUG}}", slug)
            .replace("{{PUBLISHED_DATE}}", _date.today().isoformat())
            .replace("{{AUTHOR}}", user.name or "AutomateEdge team")
        )
        return {"prompt": rendered, "slug": slug, "title": title, "tier": tier}

    target_query = (body.get("target_query") or "").strip()
    if not target_query:
        raise HTTPException(status_code=400, detail="target_query required for pillar/flagship tier")
    if len(target_query) > 150:
        raise HTTPException(status_code=400, detail="target_query too long (max 150 chars)")

    comparative = bool(body.get("comparative"))
    requested_stack = body.get("schema_stack")
    if isinstance(requested_stack, list) and requested_stack:
        stack = [str(s).strip() for s in requested_stack if str(s).strip()]
    else:
        stack = ["Article", "FAQPage", "DefinedTerm"]
    if "Article" not in stack:
        stack = ["Article"] + stack
    if "FAQPage" not in stack:
        stack = stack + ["FAQPage"]
    valid_satisfiers = {"HowTo", "DefinedTerm", "VideoObject", "ItemList"}
    if not (set(stack) & valid_satisfiers):
        raise HTTPException(
            status_code=400,
            detail=f"schema_stack must include one of {sorted(valid_satisfiers)}",
        )

    min_words = 4500 if tier == "flagship" else 3000

    template = (prompts_dir / "claude_blog_pillar.txt").read_text(encoding="utf-8")
    rendered = (
        template
        .replace("{{TITLE}}", title)
        .replace("{{ANGLE}}", angle or "(none — default to the most beatable angle on this query)")
        .replace("{{SLUG}}", slug)
        .replace("{{PUBLISHED_DATE}}", _date.today().isoformat())
        .replace("{{AUTHOR}}", user.name or "AutomateEdge team")
        .replace("{{TARGET_QUERY}}", target_query)
        .replace("{{PILLAR_TIER}}", tier)
        .replace("{{MIN_WORDS}}", str(min_words))
        .replace("{{SCHEMA_STACK}}", ", ".join(stack))
        .replace("{{SCHEMA_STACK_JSON}}", _json.dumps(stack))
        .replace("{{COMPARATIVE}}", "true" if comparative else "false")
        .replace("{{INTERNAL_URL_MANIFEST}}", _build_internal_url_manifest())
        .replace("{{TRUSTED_SOURCES}}", _build_trusted_sources_digest())
    )
    return {"prompt": rendered, "slug": slug, "title": title, "tier": tier}


@router.post("/api/blog/validate")
async def admin_blog_validate(request: Request, _user: User = Depends(get_current_admin)):
    """Run the blog-publisher validator on a pasted JSON payload.
    Does not save. Returns errors / warnings / stats so the admin can
    fix before saving a draft."""
    _check_origin(request)
    from app.services.blog_publisher import validate_payload
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Body must be JSON — paste Claude's output directly.")
    report = validate_payload(payload)
    return report


@router.post("/api/blog/draft")
async def admin_blog_save_draft(request: Request, user: User = Depends(get_current_admin)):
    """Validate + save a draft. Blocks on errors. Warnings are allowed."""
    _check_origin(request)
    from app.services.blog_publisher import validate_payload, save_draft
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Body must be JSON.")
    report = validate_payload(payload)
    if not report["ok"]:
        raise HTTPException(status_code=400, detail={"errors": report["errors"], "warnings": report["warnings"]})
    save_draft(payload, admin_name=user.name or user.email)
    return {"ok": True, "slug": payload["slug"], "warnings": report["warnings"], "stats": report["stats"]}


@router.post("/api/blog/publish")
async def admin_blog_publish(request: Request, user: User = Depends(get_current_admin)):
    """Move a validated draft → published. Stamps reviewer + date."""
    _check_origin(request)
    from app.services.blog_publisher import publish_draft
    from app.services.indexnow import ping_async
    from app.config import get_settings
    body = await request.json()
    slug = (body.get("slug") or "").strip()
    if not slug:
        raise HTTPException(status_code=400, detail="slug required")
    try:
        published = publish_draft(slug, admin_name=user.name or user.email)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"No draft with slug '{slug}'")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # SEO-07 — ping IndexNow so Bing picks up the new post near-instantly.
    base = (get_settings().public_base_url or "").rstrip("/")
    if base:
        ping_async([f"{base}/blog/{slug}"])
    return {
        "ok": True,
        "slug": slug,
        "last_reviewed_by": published["last_reviewed_by"],
        "last_reviewed_on": published["last_reviewed_on"],
    }


@router.post("/api/blog/unpublish")
async def admin_blog_unpublish(request: Request, _user: User = Depends(get_current_admin)):
    _check_origin(request)
    from app.services.blog_publisher import unpublish
    body = await request.json()
    slug = (body.get("slug") or "").strip()
    if not slug:
        raise HTTPException(status_code=400, detail="slug required")
    if not unpublish(slug):
        raise HTTPException(status_code=404, detail=f"No published post '{slug}'")
    return {"ok": True, "slug": slug, "status": "moved to drafts"}


@router.post("/api/blog/legacy-toggle")
async def admin_blog_legacy_toggle(request: Request, user: User = Depends(get_current_admin)):
    """Hide or show a legacy (hardcoded) blog post. Non-destructive —
    toggles a flag file consulted by the public route at request time."""
    _check_origin(request)
    from app.services.blog_publisher import set_legacy_hidden
    body = await request.json()
    slug = (body.get("slug") or "").strip()
    hidden = bool(body.get("hidden", False))
    if not slug:
        raise HTTPException(status_code=400, detail="slug required")
    set_legacy_hidden(slug, hidden, admin_name=user.name or user.email)
    return {"ok": True, "slug": slug, "hidden": hidden}


@router.delete("/api/blog/draft")
async def admin_blog_delete_draft(request: Request, _user: User = Depends(get_current_admin)):
    _check_origin(request)
    from app.services.blog_publisher import delete_draft
    body = await request.json()
    slug = (body.get("slug") or "").strip()
    if not slug:
        raise HTTPException(status_code=400, detail="slug required")
    if not delete_draft(slug):
        raise HTTPException(status_code=404, detail=f"No draft '{slug}'")
    return {"ok": True, "slug": slug}


@router.get("/blog", response_class=HTMLResponse)
async def admin_blog_page(_user: User = Depends(get_current_admin)):
    """Admin-only page: generate a ready-to-paste Claude blog prompt
    from a title + optional angle. Matches the manual template workflow."""
    import json as _json
    from app.services.blog_publisher import list_drafts, list_published
    drafts = list_drafts()
    published = list_published()
    published_list_json = _json.dumps(
        [{"slug": p["slug"], "title": p["title"], "target_query": p.get("target_query", "")} for p in published],
        ensure_ascii=False,
    )

    # Unified list, newest slug first (slugs are NN-prefixed, so lexical
    # reverse sort matches publication order). Each row knows its status
    # and renders status-aware action buttons.
    rows = []
    for p in published:
        rows.append({"type": "published", "data": p})
    for d in drafts:
        rows.append({"type": "draft", "data": d})

    # Legacy hardcoded posts — baked into routers/blog.py as Python strings,
    # not in the JSON pipeline. Surface them here so the admin sees the full
    # state of /blog/*. Content is code-managed, but visibility is togglable
    # via /admin/api/blog/legacy-toggle.
    try:
        from app.routers.blog import POST_01_TITLE, POST_01_PUBLISHED
        from app.services.blog_publisher import is_legacy_hidden as _is_hidden
        rows.append({
            "type": "legacy",
            "data": {
                "slug": "01",
                "title": POST_01_TITLE,
                "published": POST_01_PUBLISHED,
                "_hidden": _is_hidden("01"),
            },
        })
    except Exception:
        pass

    rows.sort(key=lambda r: r["data"].get("slug", ""), reverse=True)

    def _tier_pill(tier: str, post_type: str) -> str:
        """Colour-coded tier pill for the admin Section-3 Type column.
        Standard = muted amber, Pillar = solid amber, Flagship = red-amber,
        Legacy = slate grey (hardcoded posts pre-date the tier concept)."""
        if post_type == "legacy":
            return (
                '<span style="display:inline-block;font-family:\'IBM Plex Mono\',ui-monospace,monospace;'
                'font-size:10px;letter-spacing:0.1em;text-transform:uppercase;padding:3px 10px;border-radius:10px;'
                'background:rgba(148,163,184,0.15);color:#94a3b8;border:1px solid rgba(148,163,184,0.35)" '
                'title="Legacy hardcoded post — predates the tier system">Legacy</span>'
            )
        t = (tier or "").strip().lower()
        if t == "pillar":
            return (
                '<span style="display:inline-block;font-family:\'IBM Plex Mono\',ui-monospace,monospace;'
                'font-size:10px;letter-spacing:0.1em;text-transform:uppercase;padding:3px 10px;border-radius:10px;'
                'background:rgba(232,168,73,0.22);color:#f5c06a;border:1px solid rgba(232,168,73,0.55)" '
                'title="SEO-21 pillar post — ≥3000 words, 40+ internal links, 5+ trusted citations">Pillar</span>'
            )
        if t == "flagship":
            return (
                '<span style="display:inline-block;font-family:\'IBM Plex Mono\',ui-monospace,monospace;'
                'font-size:10px;letter-spacing:0.1em;text-transform:uppercase;padding:3px 10px;border-radius:10px;'
                'background:rgba(217,119,87,0.22);color:#f5a58a;border:1px solid rgba(217,119,87,0.55)" '
                'title="Flagship pillar post — ≥4500 words, same SEO-21 bar">Flagship</span>'
            )
        return (
            '<span style="display:inline-block;font-family:\'IBM Plex Mono\',ui-monospace,monospace;'
            'font-size:10px;letter-spacing:0.1em;text-transform:uppercase;padding:3px 10px;border-radius:10px;'
            'background:rgba(192,196,204,0.08);color:#c0c4cc;border:1px solid rgba(192,196,204,0.28)" '
            'title="Standard build-in-public essay — 800–1500 words, no SEO gates">Standard</span>'
        )

    def _row_html(r):
        d = r["data"]
        slug = esc(d.get("slug", ""))
        title = esc(d.get("title", ""))
        tier_pill = _tier_pill(d.get("pillar_tier", ""), r["type"])
        if r["type"] == "legacy":
            hidden = bool(d.get("_hidden"))
            if hidden:
                status_pill = (
                    '<span style="display:inline-block;font-family:\'IBM Plex Mono\',ui-monospace,monospace;'
                    'font-size:10px;letter-spacing:0.1em;text-transform:uppercase;padding:3px 10px;border-radius:10px;'
                    'background:rgba(148,163,184,0.15);color:#94a3b8;border:1px solid rgba(148,163,184,0.35)">Hidden</span>'
                    '<span style="display:inline-block;margin-left:6px;font-family:\'IBM Plex Mono\',ui-monospace,monospace;'
                    'font-size:9px;letter-spacing:0.1em;text-transform:uppercase;padding:2px 8px;border-radius:10px;'
                    'background:rgba(148,163,184,0.15);color:#94a3b8;border:1px solid rgba(148,163,184,0.35)" '
                    'title="Hardcoded in backend/app/routers/blog.py — predates the JSON pipeline">Legacy</span>'
                )
                meta = f'published on {esc(d.get("published", "—"))} · currently returning 404 to visitors'
                title_link = f'<span style="color:#94a3b8;text-decoration:line-through">{title}</span>'
                actions = (
                    f'<button class="btn success" onclick="toggleLegacy(\'{slug}\', false)" title="Restore the post — /blog/{slug} goes live again">Republish</button>'
                )
            else:
                status_pill = (
                    '<span style="display:inline-block;font-family:\'IBM Plex Mono\',ui-monospace,monospace;'
                    'font-size:10px;letter-spacing:0.1em;text-transform:uppercase;padding:3px 10px;border-radius:10px;'
                    'background:rgba(109,181,133,0.18);color:#8fd0a5;border:1px solid rgba(109,181,133,0.4)">Published</span>'
                    '<span style="display:inline-block;margin-left:6px;font-family:\'IBM Plex Mono\',ui-monospace,monospace;'
                    'font-size:9px;letter-spacing:0.1em;text-transform:uppercase;padding:2px 8px;border-radius:10px;'
                    'background:rgba(148,163,184,0.15);color:#94a3b8;border:1px solid rgba(148,163,184,0.35)" '
                    'title="Hardcoded in backend/app/routers/blog.py — predates the JSON pipeline">Legacy</span>'
                )
                meta = f'published on {esc(d.get("published", "—"))} · content is code-managed, visibility is togglable'
                title_link = f'<a href="/blog/{slug}" target="_blank" style="color:#e8a849">{title}</a>'
                actions = (
                    f'<a class="btn" href="/blog/{slug}" target="_blank" title="View live">View ↗</a> '
                    f'<button class="btn danger" onclick="toggleLegacy(\'{slug}\', true)" title="Hide — /blog/{slug} starts returning 404. Non-destructive.">Unpublish</button>'
                )
            return (
                f'<tr>'
                f'<td>{title_link}<div style="font-size:11px;color:#94a3b8;font-family:monospace;margin-top:2px">{slug}</div></td>'
                f'<td>{tier_pill}</td>'
                f'<td>{status_pill}</td>'
                f'<td style="font-size:12px;color:#94a3b8">{meta}</td>'
                f'<td style="text-align:right;white-space:nowrap">{actions}</td>'
                f'</tr>'
            )
        if r["type"] == "published":
            status_pill = (
                '<span style="display:inline-block;font-family:\'IBM Plex Mono\',ui-monospace,monospace;'
                'font-size:10px;letter-spacing:0.1em;text-transform:uppercase;padding:3px 10px;border-radius:10px;'
                'background:rgba(109,181,133,0.18);color:#8fd0a5;border:1px solid rgba(109,181,133,0.4)">Published</span>'
            )
            meta = (
                f'reviewed <strong>{esc(d.get("last_reviewed_on","—"))}</strong> by '
                f'<strong>{esc(d.get("last_reviewed_by","—"))}</strong>'
            )
            title_link = f'<a href="/blog/{slug}" target="_blank" style="color:#e8a849">{title}</a>'
            actions = (
                f'<a class="btn" href="/blog/{slug}" target="_blank" title="View live">View ↗</a> '
                f'<button class="btn" onclick="validateDraft(\'{slug}\')" title="Re-run validator">Re-check</button> '
                f'<button class="btn danger" onclick="unpublish(\'{slug}\')" title="Move back to drafts (non-destructive)">Unpublish</button>'
            )
        else:
            status_pill = (
                '<span style="display:inline-block;font-family:\'IBM Plex Mono\',ui-monospace,monospace;'
                'font-size:10px;letter-spacing:0.1em;text-transform:uppercase;padding:3px 10px;border-radius:10px;'
                'background:rgba(232,168,73,0.14);color:#f5c06a;border:1px solid rgba(232,168,73,0.4)">Draft</span>'
            )
            meta = f'saved by <strong>{esc(d.get("saved_by","—"))}</strong> on {esc(d.get("saved_at","")[:10])}'
            # Clickable title opens the rendered preview (admin-only route)
            # so the admin sees exactly what a reader would see, with an
            # amber "DRAFT PREVIEW" banner at the top.
            title_link = (
                f'<a href="/admin/blog/{slug}/preview" target="_blank" '
                f'style="color:#f5c06a;text-decoration:none;font-weight:600" '
                f'title="Preview the rendered draft (opens in new tab)">{title} ↗</a>'
            )
            actions = (
                f'<a class="btn" href="/admin/blog/{slug}/edit" title="Edit fields">Edit</a> '
                f'<a class="btn" href="/admin/blog/{slug}/preview" target="_blank" title="Render + eyeball">Preview ↗</a> '
                f'<button class="btn" onclick="validateDraft(\'{slug}\')" title="Re-run validator">Re-check</button> '
                f'<button class="btn success" onclick="publishDraft(\'{slug}\')" title="Go live at /blog/{slug}">Publish</button> '
                f'<button class="btn danger" onclick="deleteDraft(\'{slug}\')" title="Hard delete">Delete</button>'
            )
        return (
            f'<tr>'
            f'<td>{title_link}<div style="font-size:11px;color:#94a3b8;font-family:monospace;margin-top:2px">{slug}</div></td>'
            f'<td>{tier_pill}</td>'
            f'<td>{status_pill}</td>'
            f'<td style="font-size:12px;color:#94a3b8">{meta}</td>'
            f'<td style="text-align:right;white-space:nowrap">{actions}</td>'
            f'</tr>'
        )

    if rows:
        posts_html = "".join(_row_html(r) for r in rows)
    else:
        posts_html = (
            '<tr><td colspan="5" style="text-align:center;color:#94a3b8;padding:22px">'
            "No posts yet. Generate a prompt above, paste Claude's JSON, save as draft, then publish."
            '</td></tr>'
        )

    counts_line = (
        f'<span style="margin-right:18px">📝 <strong>{len(drafts)}</strong> draft'
        f'{"s" if len(drafts)!=1 else ""}</span>'
        f'<span>✅ <strong>{len(published)}</strong> published</span>'
    )
    # Build the page HTML without f-string brace hell — use .replace() on a
    # plain string for the data substitutions we actually need. This matches
    # what verify.py does and avoids f-string issues with CSS + JS braces.
    html = _BLOG_ADMIN_HTML.replace("{{ADMIN_CSS}}", ADMIN_CSS) \
                            .replace("{{ADMIN_NAV}}", ADMIN_NAV) \
                            .replace("{{POSTS_ROWS}}", posts_html) \
                            .replace("{{COUNTS_LINE}}", counts_line) \
                            .replace("{{PUBLISHED_LIST_JSON}}", published_list_json)
    return HTMLResponse(html)


# HTML template kept as a module-level string so the route function stays
# readable and the f-string / CSS / JS brace landmine is avoided entirely.
# Substitutions: {{ADMIN_CSS}}, {{ADMIN_NAV}}, {{DRAFTS_ROWS}}, {{PUBLISHED_ROWS}}.
_BLOG_ADMIN_HTML = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><title>Blog — Admin</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{{ADMIN_CSS}}
  .form-grid { display:grid; grid-template-columns:1fr auto; gap:10px; align-items:end; margin-bottom:12px; }
  .form-grid label { font-size:11px; text-transform:uppercase; letter-spacing:0.1em; color:#94a3b8; display:block; margin-bottom:4px; }
  .form-grid input, .form-grid textarea { width:100%; padding:9px 11px; background:#0f1419; border:1px solid #2a323d; color:#f5f1e8; border-radius:3px; font-family:inherit; font-size:14px; }
  .form-grid textarea { grid-column:1 / -1; min-height:70px; resize:vertical; }
  details.how-to { background:#0f1419; border:1px solid #2a323d; border-radius:4px; padding:10px 14px; margin-bottom:16px; font-size:13px; line-height:1.6; }
  details.how-to summary { cursor:pointer; color:#e8a849; font-weight:600; user-select:none; }
  details.how-to ol { margin:10px 0 4px 18px; padding:0; color:#d0cbc2; }
  #blogPromptOutput, #blogJsonInput { width:100%; min-height:320px; padding:10px; background:#0f1419; border:1px solid #2a323d; color:#e8e2d3; border-radius:3px; font-family:'IBM Plex Mono',ui-monospace,monospace; font-size:12px; line-height:1.5; resize:vertical; margin-top:8px; }
  .row-actions { display:flex; gap:8px; justify-content:space-between; margin-top:12px; flex-wrap:wrap; }
  .meta-line { font-size:12px; color:#94a3b8; min-height:18px; margin-top:6px; }
  .section-card { background:#1d242e; border:1px solid #2a323d; border-radius:6px; padding:18px 20px; margin:18px 0; }
  .section-card h2 { margin:0 0 10px; font-size:15px; color:#e8a849; font-family:'Fraunces',Georgia,serif; font-weight:500; }
  .section-card .note { font-size:12px; color:#94a3b8; margin-bottom:12px; line-height:1.5; }
  .val-result { margin-top:10px; padding:10px 14px; border-radius:4px; font-family:'IBM Plex Mono',ui-monospace,monospace; font-size:12px; line-height:1.6; white-space:pre-wrap; }
  .val-ok { background:rgba(109,181,133,0.1); border:1px solid rgba(109,181,133,0.35); color:#8fd0a5; }
  .val-err { background:rgba(239,68,68,0.1); border:1px solid rgba(239,68,68,0.35); color:#fca5a5; }
  .val-warn { background:rgba(232,168,73,0.08); border:1px solid rgba(232,168,73,0.3); color:#f5c06a; margin-top:6px; }
  table.admin { width:100%; border-collapse:collapse; }
  table.admin td { padding:10px 8px; border-bottom:1px solid #2a323d; font-size:13px; vertical-align:top; }
  .btn { font-family:'IBM Plex Mono',ui-monospace,monospace; font-size:11px; letter-spacing:0.08em; text-transform:uppercase; padding:6px 12px; background:transparent; border:1px solid #3a4452; color:#e8e2d3; cursor:pointer; border-radius:3px; }
  .btn:hover { border-color:#e8a849; color:#e8a849; }
  .btn.primary { background:#e8a849; color:#0f1419; border-color:#e8a849; }
  .btn.primary:hover { background:#c98e2f; border-color:#c98e2f; color:#0f1419; }
  .btn.success { border-color:#6db585; color:#6db585; }
  .btn.danger { border-color:#d97757; color:#d97757; }
  .type-picker { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:16px; }
  .type-picker .type-opt { flex:1 1 210px; min-width:210px; background:#0f1419; border:1px solid #2a323d; border-radius:4px; padding:10px 14px; cursor:pointer; transition:all 0.15s; position:relative; }
  .type-picker .type-opt:hover { border-color:#e8a849; }
  .type-picker .type-opt.active { background:rgba(232,168,73,0.08); border-color:#e8a849; }
  .type-picker .type-opt input { position:absolute; opacity:0; pointer-events:none; }
  .type-picker .tpl strong { display:block; color:#f5f1e8; font-size:13px; margin-bottom:3px; }
  .type-picker .tpl small { display:block; color:#94a3b8; font-size:11px; font-family:'IBM Plex Mono',ui-monospace,monospace; letter-spacing:0.02em; line-height:1.45; }
  #bpPillarFields { margin-top:12px; padding-top:14px; border-top:1px dashed #2a323d; }
  #bpPillarFields select { width:100%; padding:9px 11px; background:#0f1419; border:1px solid #2a323d; color:#f5f1e8; border-radius:3px; font-family:inherit; font-size:14px; }
  .suggest-block { margin-top:16px; padding:14px 16px; background:rgba(232,168,73,0.04); border:1px solid rgba(232,168,73,0.2); border-radius:4px; }
  .suggest-block h3 { margin:0 0 8px; font-size:13px; color:#e8a849; font-family:'IBM Plex Mono',ui-monospace,monospace; letter-spacing:0.04em; font-weight:600; }
  .suggest-block p { font-size:12px; color:#94a3b8; margin:0 0 12px; line-height:1.55; }
  .suggest-step { margin-bottom:14px; }
  .suggest-step label { display:block; font-size:11px; text-transform:uppercase; letter-spacing:0.08em; color:#94a3b8; margin-bottom:5px; }
  #suggestionPrompt { width:100%; min-height:160px; padding:9px 10px; background:#0f1419; border:1px solid #2a323d; color:#e8e2d3; border-radius:3px; font-family:'IBM Plex Mono',ui-monospace,monospace; font-size:11px; line-height:1.5; resize:vertical; box-sizing:border-box; }
  #suggestionsJsonInput { width:100%; min-height:90px; padding:9px 10px; background:#0f1419; border:1px solid #2a323d; color:#e8e2d3; border-radius:3px; font-family:'IBM Plex Mono',ui-monospace,monospace; font-size:11px; line-height:1.5; resize:vertical; box-sizing:border-box; }
  #suggestionsPreview { margin-top:12px; }
  .sug-row { padding:9px 10px; border:1px solid #2a323d; border-radius:3px; margin-bottom:7px; background:#0f1419; }
  .sug-row-head { display:flex; align-items:flex-start; gap:10px; flex-wrap:wrap; }
  .sug-row-title { font-size:13px; color:#f5f1e8; line-height:1.4; flex:1 1 200px; }
  .sug-row-meta { font-size:11px; color:#94a3b8; font-family:'IBM Plex Mono',ui-monospace,monospace; margin-top:3px; }
  .sug-row-why { font-size:11px; color:#7a8290; font-style:italic; margin-top:3px; line-height:1.4; }
  .sug-err { font-size:11px; color:#fca5a5; background:rgba(239,68,68,0.08); border:1px solid rgba(239,68,68,0.3); border-radius:3px; padding:5px 8px; margin-top:6px; line-height:1.5; }
  .sug-warn { font-size:11px; color:#f5c06a; background:rgba(232,168,73,0.06); border:1px solid rgba(232,168,73,0.25); border-radius:3px; padding:5px 8px; margin-top:4px; line-height:1.5; }
  .sug-apply-row { display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-top:10px; padding-top:10px; border-top:1px solid #2a323d; }
  .sug-count { font-size:12px; color:#94a3b8; margin-left:auto; }
  .sug-confirm { font-size:12px; color:#8fd0a5; margin-top:8px; }
  .pillar-divider { border:none; border-top:1px dashed rgba(232,168,73,0.3); margin:16px 0 10px; }
</style>
</head>
<body>
{{ADMIN_NAV}}
<main class="page" style="max-width:100%;margin:0 auto;padding:28px clamp(20px,4vw,64px) 80px">
  <header style="margin-bottom:18px">
    <h1 style="font-family:'Fraunces',Georgia,serif;color:#e8a849;font-weight:400;font-size:28px;margin:0 0 6px">Blog</h1>
    <p style="color:#94a3b8;font-size:14px;line-height:1.6;max-width:780px">
      Three-step flow for every post:
      <strong style="color:#e8e2d3">(1)</strong> generate a title-tailored prompt,
      <strong style="color:#e8e2d3">(2)</strong> paste Claude's JSON output and let the auto-validator scan for format + branding issues,
      <strong style="color:#e8e2d3">(3)</strong> publish when green. No auto-publish path.
    </p>
  </header>

  <details class="how-to">
    <summary>End-to-end steps (click to expand)</summary>
    <ol>
      <li>Pick <strong>Post type</strong>: <em>Standard</em> for build-in-public essays, <em>Pillar</em> for SEO authority posts (SEO-21), <em>Flagship</em> for 4500+ word deep-dives.</li>
      <li>Enter a <strong>Title</strong> + optional <strong>Angle</strong>. Pillar/flagship also need a <strong>Target query</strong> + schema stack. Click <strong>Generate prompt</strong>.</li>
      <li><strong>Copy prompt</strong> → <strong>Open Claude.ai ↗</strong> → fresh chat, Opus, paste, send. Pillar posts take 2-4 minutes.</li>
      <li>Claude returns a JSON artifact. Download or copy the content.</li>
      <li>Scroll to <strong>Upload Claude's JSON</strong> below, paste or upload, click <strong>Validate</strong>.</li>
      <li>Validator scans schema, banned terms, length, structure. For pillar posts it also enforces ≥40 internal links, ≥5 trusted citations, 8-12 H2s, 8-15 FAQs, comparison table (if comparative).</li>
      <li>Click <strong>Save as draft</strong> when errors clear. Draft appears in the list.</li>
      <li>Generate the hero image using the <code>image_brief.hero_prompt</code> field. Drop PNG at <code>docs/blog/assets/&lt;slug&gt;-hero.png</code>.</li>
      <li>Click <strong>Publish</strong> on the draft row. Reviewer + date get stamped; post goes live at <code>/blog/&lt;slug&gt;</code>.</li>
    </ol>
    <div style="margin-top:8px;color:#94a3b8;font-size:12px">
      <strong>Cost:</strong> zero — Claude Max chat is unmetered; no backend AI call.
      <strong>Runbook:</strong> <a href="https://github.com/manishjnv/AIExpert/blob/master/docs/blog/ADMIN_GUIDE.md" target="_blank" style="color:#e8a849">ADMIN_GUIDE.md</a>
      · <strong>Rules:</strong> <a href="https://github.com/manishjnv/AIExpert/blob/master/docs/blog/STYLE.md" target="_blank" style="color:#e8a849">STYLE.md</a>
    </div>
  </details>

  <details class="how-to" style="border-color:rgba(232,168,73,0.4)">
    <summary>📌 Pillar post quick-pick — the 5 next-up briefs (click to expand)</summary>
    <div style="color:#94a3b8;font-size:12px;margin-top:6px;line-height:1.55">
      Pre-curated SEO-21 pillar posts queued after the existing 6-post slate.
      Click <strong style="color:#e8a849">Load brief</strong> on any row to auto-fill the
      Generate form below — picks the right tier, target query, angle, schema stack, and
      the comparative checkbox. Then scroll to <strong>Section 1</strong> and click
      <strong>Generate prompt</strong>. Execute in order — priority reflects commercial
      intent + SERP beatability + product-fit moat.
    </div>
    <div class="suggest-block">
      <h3>🔮 Suggest next 5 pillar topics</h3>
      <p>Generate a Claude prompt that encodes published posts and the current slate as context,
         paste it into Claude Max chat, then load Claude&apos;s JSON back here to preview and
         selectively replace the slate below.</p>
      <div class="suggest-step">
        <label>Step 1 — generate the suggestion prompt</label>
        <button class="btn primary" onclick="buildSuggestionPrompt()">Generate suggestion prompt</button>
        <div style="margin-top:8px;display:flex;gap:8px;align-items:flex-start">
          <textarea id="suggestionPrompt" readonly placeholder="Click Generate suggestion prompt to build the Claude prompt."></textarea>
        </div>
        <div style="margin-top:6px">
          <button class="btn" onclick="copySuggestionPrompt()">Copy prompt</button>
          <span id="suggestionCopyMsg" style="font-size:11px;color:#8fd0a5;margin-left:8px"></span>
        </div>
      </div>
      <div class="suggest-step">
        <label>Step 2 — paste Claude&apos;s JSON return</label>
        <textarea id="suggestionsJsonInput" placeholder='Paste the JSON array of 5 suggestion objects Claude returned.'></textarea>
        <div style="margin-top:6px">
          <button class="btn primary" onclick="parseAndValidateSuggestions()">Validate &amp; preview</button>
        </div>
      </div>
      <div id="suggestionsPreview"></div>
      <div id="suggestionsFooter" style="display:flex;align-items:center;gap:10px;margin-top:10px;padding-top:10px;border-top:1px solid rgba(232,168,73,0.15)">
        <button class="btn" id="sugUndoBtn" onclick="undoSuggestionsReplace()" disabled>Undo</button>
        <span id="sugConfirmMsg" style="font-size:12px;color:#8fd0a5;line-height:1.4"></span>
      </div>
    </div>
    <hr class="pillar-divider">
    <p style="font-size:11px;color:#94a3b8;margin:0 0 6px">Pre-curated slate — load a brief directly or replace via the AI suggestion flow above.</p>
    <table class="admin" style="margin-top:12px">
      <thead>
        <tr>
          <th style="text-align:left;padding:6px 8px;color:#94a3b8;font-size:10px;text-transform:uppercase;letter-spacing:0.08em;border-bottom:1px solid #2a323d;width:48px">#</th>
          <th style="text-align:left;padding:6px 8px;color:#94a3b8;font-size:10px;text-transform:uppercase;letter-spacing:0.08em;border-bottom:1px solid #2a323d">Title (target query)</th>
          <th style="text-align:left;padding:6px 8px;color:#94a3b8;font-size:10px;text-transform:uppercase;letter-spacing:0.08em;border-bottom:1px solid #2a323d;width:90px">Tier</th>
          <th style="text-align:left;padding:6px 8px;color:#94a3b8;font-size:10px;text-transform:uppercase;letter-spacing:0.08em;border-bottom:1px solid #2a323d;width:140px">Schema satisfier</th>
          <th style="text-align:left;padding:6px 8px;color:#94a3b8;font-size:10px;text-transform:uppercase;letter-spacing:0.08em;border-bottom:1px solid #2a323d;width:100px">Status</th>
          <th style="text-align:right;padding:6px 8px;color:#94a3b8;font-size:10px;text-transform:uppercase;letter-spacing:0.08em;border-bottom:1px solid #2a323d;width:130px">Action</th>
        </tr>
      </thead>
      <tbody id="pillarBriefsTbody"></tbody>
    </table>
    <div style="margin-top:12px;padding:10px 12px;background:rgba(232,168,73,0.06);border-left:3px solid #e8a849;font-size:12px;color:#d0cbc2;line-height:1.55">
      <strong style="color:#e8a849">Validator gates auto-applied to every pillar post:</strong>
      <ul style="margin:6px 0 0 18px;padding:0">
        <li>Word count ≥3000 (pillar) or ≥4500 (flagship)</li>
        <li>≥40 internal links to <code>automateedge.cloud/*</code> — anchor-only links don't count</li>
        <li>≥5 external citations to domains in <code>backend/data/trusted_sources.json</code> (arXiv, lab docs, BLS, Stanford AI Index, etc.)</li>
        <li>8–12 H2 sections · 8–15 FAQ Q&amp;A pairs · first paragraph after the lede must be a 40–60 word definitional snippet</li>
        <li>Schema stack: Article + FAQPage + at least one of HowTo / DefinedTerm / VideoObject / ItemList</li>
        <li>If <em>comparative</em> is checked, body MUST contain at least one <code>&lt;table&gt;</code></li>
      </ul>
      Red errors block. Amber warnings (paragraphs &gt;4 sentences, sentences &gt;30 words) are editorial — fix before publish.
    </div>
    <div style="margin-top:10px;font-size:11px;color:#94a3b8;line-height:1.6">
      <strong style="color:#e8e2d3">Two ways to land Claude's JSON</strong> — both end up at <code>/data/blog/drafts/&lt;slug&gt;.json</code>:
      <ul style="margin:4px 0 0 18px;padding:0">
        <li><strong>Direct:</strong> paste / upload in Section 2 below → Validate → Save as draft.</li>
        <li><strong>Git archive (audit trail):</strong> save Claude's file as <code>docs/blog/&lt;slug&gt;.json</code>, commit + push, then on VPS run <code>docker compose exec -T backend python scripts/stage_blog_draft.py --all</code> (idempotent — skips already-published).</li>
      </ul>
      <strong style="color:#e8e2d3">After Save as draft</strong> → click the new draft row in Section 3 → edit / preview / Publish.
      <strong style="color:#e8e2d3">After Publish</strong> → run the live URL through
      <a href="https://search.google.com/test/rich-results" target="_blank" style="color:#e8a849">Google Rich Results Test</a>
      (validator checks structure; Google checks semantics — both must pass).
    </div>
  </details>

  <section class="section-card">
    <h2>1 · Generate Claude prompt</h2>
    <label style="font-size:11px;text-transform:uppercase;letter-spacing:0.1em;color:#94a3b8;display:block;margin-bottom:6px;">Post type</label>
    <div class="type-picker">
      <label class="type-opt active" data-tier="standard">
        <input type="radio" name="bpTier" value="standard" checked onchange="onTierChange()">
        <span class="tpl"><strong>Standard</strong><small>build-in-public essay · 800–1500 words · no SEO gates</small></span>
      </label>
      <label class="type-opt" data-tier="pillar">
        <input type="radio" name="bpTier" value="pillar" onchange="onTierChange()">
        <span class="tpl"><strong>Pillar (SEO-21)</strong><small>authority post · ≥3000 words · 40+ internal · 5+ trusted citations · 8–15 FAQs</small></span>
      </label>
      <label class="type-opt" data-tier="flagship">
        <input type="radio" name="bpTier" value="flagship" onchange="onTierChange()">
        <span class="tpl"><strong>Flagship</strong><small>deep-dive pillar · ≥4500 words · same SEO-21 bar</small></span>
      </label>
    </div>
    <div class="form-grid">
      <div>
        <label>Title</label>
        <input id="bpTitle" placeholder="e.g. Why AutomateEdge stopped auto-publishing curricula" maxlength="150">
      </div>
      <button class="btn primary" onclick="generateBlogPrompt()">Generate prompt</button>
      <div style="grid-column:1 / -1">
        <label>Angle / thesis <span style="color:#64748b;text-transform:none;letter-spacing:0">(optional — one or two sentences on the message)</span></label>
        <textarea id="bpAngle" placeholder="e.g. Policy beats tools. Every AI pipeline needs a human button."></textarea>
      </div>
    </div>
    <div id="bpPillarFields" style="display:none">
      <div class="form-grid">
        <div style="grid-column:1 / -1">
          <label>Target query <span style="color:#fca5a5">*</span> <span style="color:#64748b;text-transform:none;letter-spacing:0">(the SERP query this pillar targets — drives FAQ sourcing + intent)</span></label>
          <input id="bpTargetQuery" placeholder='e.g. AI engineer vs ML engineer' maxlength="150">
        </div>
        <div>
          <label>Schema stack</label>
          <select id="bpSchemaStack">
            <option value="DefinedTerm">Article + FAQPage + DefinedTerm  (role / concept / comparison)</option>
            <option value="HowTo">Article + FAQPage + HowTo  (step-by-step learning guides)</option>
            <option value="VideoObject">Article + FAQPage + VideoObject  (video-embedded posts)</option>
            <option value="ItemList">Article + FAQPage + ItemList  (curated cert / tool lists)</option>
          </select>
        </div>
        <div style="display:flex;align-items:center">
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;margin:0;padding-top:22px;text-transform:none;letter-spacing:0">
            <input type="checkbox" id="bpComparative">
            <span style="font-size:13px;color:#e8e2d3;">Comparative (body must include a &lt;table&gt;)</span>
          </label>
        </div>
      </div>
    </div>
    <div id="bpMeta" class="meta-line"></div>
    <textarea id="blogPromptOutput" readonly placeholder="Prompt will appear here after you click Generate."></textarea>
    <div class="row-actions">
      <button class="btn danger" onclick="clearBlogPrompt()">Clear</button>
      <div style="display:flex;gap:8px">
        <button class="btn success" onclick="copyBlogPromptToClipboard()">Copy prompt</button>
        <a href="https://claude.ai" target="_blank" rel="noopener" class="btn" style="text-decoration:none">Open Claude.ai ↗</a>
      </div>
    </div>
  </section>

  <section class="section-card">
    <h2>2 · Upload Claude's JSON</h2>
    <div class="note">Paste Claude's full response — one raw JSON object starting with <code>{</code> — or upload a <code>.json</code> file exported from the chat. Validate first; fix any red errors before saving as draft.</div>
    <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap">
      <label for="blogJsonFile" class="btn" style="cursor:pointer;margin:0">📂 Upload JSON file</label>
      <input id="blogJsonFile" type="file" accept="application/json,.json,.txt" style="display:none" onchange="handleJsonFile(event)">
      <span id="bpFileName" style="font-size:12px;color:#94a3b8;font-family:'IBM Plex Mono',ui-monospace,monospace"></span>
    </div>
    <textarea id="blogJsonInput" placeholder='Paste Claude&apos;s JSON here, or click Upload JSON file above.&#10;&#10;{&#10;  "title": "...",&#10;  "slug": "02-...",&#10;  "author": "...",&#10;  "published": "...",&#10;  "tags": [...],&#10;  "og_description": "...",&#10;  "lede": "...",&#10;  "body_html": "...",&#10;  "word_count": 1200,&#10;  "image_brief": {...},&#10;  "quotable_lines": [...]&#10;}'></textarea>
    <div id="validationResult"></div>
    <div class="row-actions">
      <button class="btn danger" onclick="clearJsonInput()">Clear</button>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn" onclick="validateJson()">Validate</button>
        <button class="btn primary" onclick="saveDraft()">Save as draft</button>
      </div>
    </div>
    <div class="note" style="margin-top:10px;font-size:11px;color:#64748b;font-family:'IBM Plex Mono',ui-monospace,monospace;letter-spacing:0.03em">
      Saved drafts → <code>/data/blog/drafts/&lt;slug&gt;.json</code> on the VPS.
      Published posts → <code>/data/blog/published/&lt;slug&gt;.json</code>.
      Both persist across container rebuilds via the <code>/data</code> volume mount.
    </div>
  </section>

  <section class="section-card">
    <h2>3 · All blog posts</h2>
    <div class="note" style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap">
      <div>Single list of drafts + published. Actions change based on status. Unpublish is non-destructive — the post returns to drafts with its content intact.</div>
      <div style="font-size:12px;color:#94a3b8;white-space:nowrap">{{COUNTS_LINE}}</div>
    </div>
    <table class="admin" style="margin-top:8px">
      <thead>
        <tr>
          <th style="text-align:left;padding:8px;color:#94a3b8;font-size:11px;text-transform:uppercase;letter-spacing:0.08em;border-bottom:1px solid #2a323d">Post</th>
          <th style="text-align:left;padding:8px;color:#94a3b8;font-size:11px;text-transform:uppercase;letter-spacing:0.08em;border-bottom:1px solid #2a323d">Type</th>
          <th style="text-align:left;padding:8px;color:#94a3b8;font-size:11px;text-transform:uppercase;letter-spacing:0.08em;border-bottom:1px solid #2a323d">Status</th>
          <th style="text-align:left;padding:8px;color:#94a3b8;font-size:11px;text-transform:uppercase;letter-spacing:0.08em;border-bottom:1px solid #2a323d">Reviewer / Save</th>
          <th style="text-align:right;padding:8px;color:#94a3b8;font-size:11px;text-transform:uppercase;letter-spacing:0.08em;border-bottom:1px solid #2a323d">Actions</th>
        </tr>
      </thead>
      <tbody>
        {{POSTS_ROWS}}
      </tbody>
    </table>
  </section>
</main>

<script>
// --------------- Prompt generator ---------------
function onTierChange() {
  const tier = (document.querySelector('input[name="bpTier"]:checked') || {}).value || 'standard';
  document.querySelectorAll('.type-picker .type-opt').forEach(el => {
    el.classList.toggle('active', el.dataset.tier === tier);
  });
  const isPillar = (tier === 'pillar' || tier === 'flagship');
  document.getElementById('bpPillarFields').style.display = isPillar ? 'block' : 'none';
  const titleEl = document.getElementById('bpTitle');
  if (tier === 'pillar') {
    titleEl.placeholder = 'e.g. AI Engineer vs ML Engineer: The 2026 Role Split';
  } else if (tier === 'flagship') {
    titleEl.placeholder = 'e.g. How to Learn AI From Scratch — The 2026 Roadmap';
  } else {
    titleEl.placeholder = 'e.g. Why AutomateEdge stopped auto-publishing curricula';
  }
}

async function generateBlogPrompt() {
  const title = document.getElementById('bpTitle').value.trim();
  const angle = document.getElementById('bpAngle').value.trim();
  const tier = (document.querySelector('input[name="bpTier"]:checked') || {}).value || 'standard';
  const meta = document.getElementById('bpMeta');
  if (!title) { meta.textContent = 'Title is required.'; meta.style.color = '#fca5a5'; return; }
  const payload = { title: title, angle: angle, tier: tier };
  if (tier === 'pillar' || tier === 'flagship') {
    const tq = document.getElementById('bpTargetQuery').value.trim();
    if (!tq) { meta.textContent = 'Target query is required for pillar posts.'; meta.style.color = '#fca5a5'; return; }
    const satisfier = document.getElementById('bpSchemaStack').value;
    payload.target_query = tq;
    payload.schema_stack = ['Article', 'FAQPage', satisfier];
    payload.comparative = document.getElementById('bpComparative').checked;
  }
  meta.style.color = '#94a3b8'; meta.textContent = 'Rendering prompt…';
  try {
    const resp = await fetch('/admin/api/render-blog-prompt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      credentials: 'same-origin',
    });
    if (!resp.ok) {
      const d = await resp.json().catch(() => ({}));
      meta.style.color = '#fca5a5';
      meta.textContent = d.detail || 'Render failed.';
      return;
    }
    const data = await resp.json();
    document.getElementById('blogPromptOutput').value = data.prompt;
    meta.style.color = '#8fd0a5';
    meta.textContent = '✓ Slug: ' + data.slug + '  ·  tier: ' + data.tier + '  ·  ' + data.prompt.length.toLocaleString() + ' chars. Copy → paste into Claude.ai.';
  } catch (e) { meta.style.color = '#fca5a5'; meta.textContent = 'Network error.'; }
}
function copyBlogPromptToClipboard() {
  const text = document.getElementById('blogPromptOutput').value;
  if (!text) return;
  navigator.clipboard.writeText(text).then(() => {
    const el = document.getElementById('bpMeta');
    const prev = el.textContent;
    el.style.color = '#8fd0a5'; el.textContent = '✓ Copied.';
    setTimeout(() => { el.textContent = prev; }, 2000);
  });
}
function clearBlogPrompt() {
  document.getElementById('bpTitle').value = '';
  document.getElementById('bpAngle').value = '';
  document.getElementById('blogPromptOutput').value = '';
  document.getElementById('bpMeta').textContent = '';
  const tq = document.getElementById('bpTargetQuery'); if (tq) tq.value = '';
  const cmp = document.getElementById('bpComparative'); if (cmp) cmp.checked = false;
}

// --------------- Pillar quick-pick briefs ---------------
// Published posts injected server-side for duplicate-query detection in the
// AI suggestion flow. Shape: [{slug, title, target_query}, ...].
const PUBLISHED_POSTS = {{PUBLISHED_LIST_JSON}};

// Curated SEO-21 pillar slate (posts 06-10). Schema satisfier picks the
// 3rd schema beyond the mandatory Article + FAQPage — must match the
// dropdown values in #bpSchemaStack (HowTo / DefinedTerm / VideoObject / ItemList).
// Posts that need an extra schema (e.g. Dataset for the salary post) get a
// "extra" note shown in the row; the admin adds it to schemas[] in the editor.
// `let` so the AI suggestion flow can replace the slate in-place.
let PILLAR_BRIEFS = [
  {
    n: 1,
    tier: 'flagship',
    title: 'AI Engineer Salary 2026: Real Data by Experience, Stack, and Region',
    target_query: 'AI engineer salary 2026',
    angle: 'Levels.fyi is a database. Glassdoor is stale. We have 25 live job sources refreshed daily — here is what AI engineers actually earn in 2026 by years of experience, AI stack, and metro, with the gaps nobody else surfaces.',
    schema: 'ItemList',
    schema_extra: 'Dataset',
    comparative: true,
    why: 'highest commercial intent on the topic graph; jobs DB is a primary-source moat',
  },
  {
    n: 2,
    tier: 'pillar',
    title: 'AI Engineer Interview Prep: The 50 Questions Actually Asked in 2026',
    target_query: 'AI engineer interview questions 2026',
    angle: 'Glassdoor lists are theoretical. Reddit threads are anecdotal. We mined 25 live job sources for what 2026 employers actually screen for — 50 questions grouped by role tier with answer scaffolding, sourced from real JDs not LeetCode.',
    schema: 'ItemList',
    schema_extra: '',
    comparative: false,
    why: 'FAQPage schema IS the content shape — perfect rich-result fit; massive year-round volume',
  },
  {
    n: 3,
    tier: 'pillar',
    title: 'AI Portfolio Projects That Get Interviews in 2026 (Ranked by Hiring Signal)',
    target_query: 'best AI projects for portfolio',
    angle: 'Towards Data Science listicles rank by GitHub stars. We rank by interview conversion — projects scored against real hiring-manager response data from our learner cohort, with one project reverse-engineered end-to-end.',
    schema: 'HowTo',
    schema_extra: 'ItemList',
    comparative: false,
    why: 'GitHub-eval product fit; only platform with hiring-response data on real learner repos',
  },
  {
    n: 4,
    tier: 'pillar',
    title: 'How to Build a RAG System From Scratch in 2026 (Without LangChain)',
    target_query: 'build RAG from scratch 2026',
    angle: 'LangChain hides the moving parts. Vendor blogs are biased. Here is the vendor-neutral, 350-line implementation of retrieval-augmented generation in 2026 — every choice justified, every benchmark reproduced.',
    schema: 'HowTo',
    schema_extra: 'VideoObject',
    comparative: true,
    why: 'highest practitioner search volume in applied AI; "from scratch" + year-qualified is open',
  },
  {
    n: 5,
    tier: 'pillar',
    title: 'Open-Source LLMs vs API LLMs: Which to Learn First in 2026',
    target_query: 'open source LLM vs OpenAI 2026',
    angle: 'Vendor blogs sell their stack. Medium posts are stale (Llama 3 era). The honest 2026 trade-off across cost, latency, quality, and learning curve — and the path that gets you hireable fastest depending on which segment of the market you target.',
    schema: 'DefinedTerm',
    schema_extra: '',
    comparative: true,
    why: 'every learner hits this fork; ancestor for future /vs/llama-vs-gpt programmatic pages',
  },
];

function _esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
                  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function renderPillarBriefs() {
  const tbody = document.getElementById('pillarBriefsTbody');
  if (!tbody) return;
  const tierBadge = (t) => {
    if (t === 'flagship') return '<span style="display:inline-block;font-family:\\'IBM Plex Mono\\',ui-monospace,monospace;font-size:9px;letter-spacing:0.1em;text-transform:uppercase;padding:2px 8px;border-radius:10px;background:rgba(217,119,87,0.22);color:#f5a58a;border:1px solid rgba(217,119,87,0.55)">Flagship</span>';
    return '<span style="display:inline-block;font-family:\\'IBM Plex Mono\\',ui-monospace,monospace;font-size:9px;letter-spacing:0.1em;text-transform:uppercase;padding:2px 8px;border-radius:10px;background:rgba(232,168,73,0.22);color:#f5c06a;border:1px solid rgba(232,168,73,0.55)">Pillar</span>';
  };
  const statusBadge = (b) => {
    // Match on title first — published JSONs reliably store title (verbatim
    // from prompt input), but target_query isn't in the Claude output schema
    // so it's empty for every published post.
    const titleNorm = (b.title || '').trim().toLowerCase();
    const tqNorm = (b.target_query || '').trim().toLowerCase();
    const hit = PUBLISHED_POSTS.some(p => {
      const pt = (p.title || '').trim().toLowerCase();
      const pq = (p.target_query || '').trim().toLowerCase();
      return (titleNorm && pt === titleNorm) || (tqNorm && pq && pq === tqNorm);
    });
    if (hit) return '<span title="A published post already targets this query" style="display:inline-block;font-family:\\'IBM Plex Mono\\',ui-monospace,monospace;font-size:9px;letter-spacing:0.1em;text-transform:uppercase;padding:2px 8px;border-radius:10px;background:rgba(143,208,165,0.18);color:#8fd0a5;border:1px solid rgba(143,208,165,0.45)">Published</span>';
    return '<span title="Not yet published" style="display:inline-block;font-family:\\'IBM Plex Mono\\',ui-monospace,monospace;font-size:9px;letter-spacing:0.1em;text-transform:uppercase;padding:2px 8px;border-radius:10px;background:rgba(148,163,184,0.15);color:#94a3b8;border:1px solid rgba(148,163,184,0.35)">Queued</span>';
  };
  tbody.innerHTML = PILLAR_BRIEFS.map((b, i) => {
    const extra = b.schema_extra
      ? '<div style="font-size:10px;color:#94a3b8;margin-top:2px">+ ' + _esc(b.schema_extra) + ' (add in editor)</div>'
      : '';
    const cmp = b.comparative
      ? '<span style="font-size:10px;color:#f5c06a">comparative — table required</span>'
      : '<span style="font-size:10px;color:#94a3b8">non-comparative</span>';
    return ''
      + '<tr>'
      + '<td style="padding:10px 8px;color:#94a3b8;font-family:monospace;font-size:13px;vertical-align:top">' + b.n + '</td>'
      + '<td style="padding:10px 8px;vertical-align:top">'
      +   '<div style="color:#f5f1e8;font-size:13px;line-height:1.45;margin-bottom:3px">' + _esc(b.title) + '</div>'
      +   '<div style="font-size:11px;color:#94a3b8;font-family:monospace;margin-bottom:3px">target: ' + _esc(b.target_query) + '</div>'
      +   '<div style="font-size:11px;color:#7a8290;line-height:1.4;font-style:italic">why now: ' + _esc(b.why) + '</div>'
      + '</td>'
      + '<td style="padding:10px 8px;vertical-align:top">' + tierBadge(b.tier) + '</td>'
      + '<td style="padding:10px 8px;vertical-align:top">'
      +   '<div style="font-size:11px;color:#e8e2d3">Article + FAQPage + ' + _esc(b.schema) + '</div>'
      +   extra
      +   '<div style="margin-top:4px">' + cmp + '</div>'
      + '</td>'
      + '<td style="padding:10px 8px;vertical-align:top">' + statusBadge(b) + '</td>'
      + '<td style="padding:10px 8px;text-align:right;vertical-align:top">'
      +   '<button class="btn primary" onclick="loadPillarBrief(' + i + ')" title="Auto-fill the Generate form below with this brief">Load brief</button>'
      + '</td>'
      + '</tr>';
  }).join('');
}

function loadPillarBrief(idx) {
  const b = PILLAR_BRIEFS[idx];
  if (!b) return;
  // 1. Pick the right tier radio + reveal pillar fields
  const radio = document.querySelector('input[name="bpTier"][value="' + b.tier + '"]');
  if (radio) { radio.checked = true; }
  onTierChange();
  // 2. Fill the form
  document.getElementById('bpTitle').value = b.title;
  document.getElementById('bpAngle').value = b.angle;
  document.getElementById('bpTargetQuery').value = b.target_query;
  document.getElementById('bpSchemaStack').value = b.schema;
  document.getElementById('bpComparative').checked = !!b.comparative;
  // 3. Confirmation + scroll the Generate section into view
  const meta = document.getElementById('bpMeta');
  meta.style.color = '#8fd0a5';
  meta.textContent = '✓ Loaded brief #' + b.n + ' — review fields and click Generate prompt.';
  document.querySelector('.section-card').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// --------------- AI suggestion flow ---------------

function buildSuggestionPrompt() {
  const publishedLines = PUBLISHED_POSTS.map(function(p) {
    return p.target_query ? ('- ' + p.title + '  (target: ' + p.target_query + ')') : ('- ' + p.title);
  });
  const queuedLines = PILLAR_BRIEFS.map(function(b) {
    return b.target_query ? ('- ' + b.title + '  (target: ' + b.target_query + ')') : ('- ' + b.title);
  });
  const lines = [
    'You are picking the next 5 pillar/flagship blog topics for automateedge.cloud,',
    'an AI learning platform with: a live AI-jobs DB (25 sources, refreshed daily),',
    'GitHub-eval that scores learner repos against real hiring-response data,',
    'and an auto-refreshing AI curriculum.',
    '',
    'ALREADY PUBLISHED (do not propose anything that cannibalizes these target queries):',
  ].concat(publishedLines).concat([
    '',
    'CURRENTLY QUEUED IN SLATE (do not propose duplicates of these either):',
  ]).concat(queuedLines).concat([
    '',
    'NON-NEGOTIABLE TOPIC CRITERIA — every suggestion MUST satisfy at least ONE:',
    '  (a) primary-source data moat — uses the jobs DB, GitHub-eval, or learner-cohort data',
    '      that competitor SEO sites cannot replicate',
    '  (b) year-qualified gap — "<topic> 2026" / "from scratch 2026" where SERP top-3',
    '      is stale (2024 / Llama-3 era / pre-tool-use) and refreshable annually',
    '  (c) ancestor for programmatic pages — a hub that legitimately spawns 10+',
    '      child /vs/ or /how-to/ pages without thin-content risk',
    '',
    'REJECT topics that are:',
    '  - generic LLM comparisons without a data hook (e.g. "GPT-4 vs Claude")',
    '  - listicle-bait without a primary-source angle (e.g. "10 best AI tools")',
    '  - already saturated by Towards Data Science / Medium / vendor blogs',
    '',
    'Return EXACTLY this JSON shape (an array of 5 objects, no prose, no code fence):',
    '[',
    '  {',
    '    "n": 1,',
    '    "tier": "flagship" | "pillar",',
    '    "title": "Full post title, year-qualified where natural",',
    '    "target_query": "lowercase SEO query, 2-5 words",',
    '    "angle": "1-2 sentences. Names the competitor the post beats AND the moat used.",',
    '    "schema": "HowTo" | "DefinedTerm" | "VideoObject" | "ItemList",',
    '    "schema_extra": "Optional 4th schema, empty string if none",',
    '    "comparative": true | false,',
    '    "why": "Short why-now. Names the moat criterion (a/b/c) and the SERP gap."',
    '  }',
    ']',
    '',
    'Schema enum mapping (the `schema` field must be exactly one of these):',
    '  - HowTo          (step-by-step build / setup posts)',
    '  - DefinedTerm    (concept / vs-comparison posts)',
    '  - VideoObject    (posts that ship with a paired video)',
    '  - ItemList       (ranked / curated lists)',
    '',
    'Set `comparative: true` ONLY if the post is X-vs-Y or a ranked comparison —',
    'this triggers a hard validator gate requiring at least one <table> in body.',
    '',
    'Order the 5 by descending priority: commercial intent x SERP beatability x',
    'which moat criterion (a/b/c) it leans on. Tier "flagship" only for topics',
    'where the moat is exclusive — at most 1 flagship per batch of 5.',
  ]);
  document.getElementById('suggestionPrompt').value = lines.join('\\n');
}

function copySuggestionPrompt() {
  const ta = document.getElementById('suggestionPrompt');
  const msg = document.getElementById('suggestionCopyMsg');
  const text = ta.value;
  if (!text) return;
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(function() {
      msg.textContent = '✓ Copied.';
      setTimeout(function() { msg.textContent = ''; }, 2000);
    });
  } else {
    ta.select();
    document.execCommand('copy');
    msg.textContent = '✓ Copied.';
    setTimeout(function() { msg.textContent = ''; }, 2000);
  }
}

function parseAndValidateSuggestions() {
  const raw = document.getElementById('suggestionsJsonInput').value.trim();
  if (!raw) { _renderSuggestionsError('Paste Claude\\'s JSON first.'); return; }
  const stripped = raw.replace(/^\\s*```(?:json)?/i, '').replace(/```\\s*$/, '').trim();
  var suggestions;
  try { suggestions = JSON.parse(stripped); }
  catch (e) { _renderSuggestionsError('Invalid JSON: ' + e.message); return; }

  var errors = {};   // rowIndex -> [msg, ...]
  var warnings = {}; // rowIndex -> [msg, ...]
  var globalErrs = [];

  if (!Array.isArray(suggestions)) { _renderSuggestionsError('Expected a JSON array.'); return; }
  if (suggestions.length !== 5) { _renderSuggestionsError('Expected exactly 5 items, got ' + suggestions.length + '.'); return; }

  var REQUIRED_STR = ['tier', 'title', 'target_query', 'angle', 'schema', 'why'];
  var seenQueries = {};
  var flagshipCount = 0;
  var publishedQueries = {};
  var publishedTitles = {};
  var slateQueries = {};
  var slateTitles = {};
  // Published JSONs reliably store title but not target_query (not in the
  // Claude output schema), so dedup must check title too — otherwise a
  // suggestion that re-targets a shipped post slips through.
  PUBLISHED_POSTS.forEach(function(p) {
    if (p.target_query) publishedQueries[p.target_query.trim().toLowerCase()] = true;
    if (p.title) publishedTitles[p.title.trim().toLowerCase()] = true;
  });
  PILLAR_BRIEFS.forEach(function(b) {
    if (b.target_query) slateQueries[b.target_query.trim().toLowerCase()] = true;
    if (b.title) slateTitles[b.title.trim().toLowerCase()] = true;
  });

  suggestions.forEach(function(s, i) {
    var rowErrs = [];
    var rowWarns = [];

    // Missing required fields
    REQUIRED_STR.forEach(function(k) {
      if (s[k] === undefined || s[k] === null) rowErrs.push('Missing field: ' + k);
      else if (typeof s[k] !== 'string') rowErrs.push('Field ' + k + ' must be a string, got ' + typeof s[k]);
    });
    if (s.n === undefined || s.n === null) rowErrs.push('Missing field: n');
    else if (typeof s.n !== 'number') rowErrs.push('Field n must be a number');
    if (s.comparative === undefined || s.comparative === null) rowErrs.push('Missing field: comparative');
    else if (typeof s.comparative !== 'boolean') rowErrs.push('Field comparative must be a boolean, got ' + typeof s.comparative);
    if (s.schema_extra === undefined) s.schema_extra = '';

    // Enum checks (only if field is a string)
    if (typeof s.tier === 'string' && s.tier !== 'flagship' && s.tier !== 'pillar')
      rowErrs.push('tier must be "flagship" or "pillar", got: ' + _esc(s.tier));
    if (typeof s.schema === 'string' && ['HowTo','DefinedTerm','VideoObject','ItemList'].indexOf(s.schema) === -1)
      rowErrs.push('schema must be HowTo / DefinedTerm / VideoObject / ItemList, got: ' + _esc(s.schema));

    // Duplicate target_query checks
    if (typeof s.target_query === 'string') {
      var tq = s.target_query.trim().toLowerCase();
      if (publishedQueries[tq]) rowErrs.push('target_query duplicates an already-published post: ' + _esc(tq));
      if (slateQueries[tq]) rowErrs.push('target_query duplicates current slate entry: ' + _esc(tq));
      if (seenQueries[tq]) rowErrs.push('target_query duplicates another suggestion in this batch: ' + _esc(tq));
      seenQueries[tq] = true;
    }

    // Duplicate title checks (matches retroactively against shipped posts
    // whose published JSON predates target_query being persisted)
    if (typeof s.title === 'string') {
      var ttl = s.title.trim().toLowerCase();
      if (publishedTitles[ttl]) rowErrs.push('title duplicates an already-published post: ' + _esc(s.title));
      if (slateTitles[ttl]) rowErrs.push('title duplicates current slate entry: ' + _esc(s.title));
    }

    // Flagship count (only count if tier is valid string)
    if (typeof s.tier === 'string' && s.tier === 'flagship') flagshipCount++;

    // Soft warnings
    if (typeof s.angle === 'string' && s.angle.length < 80) rowWarns.push('angle is short (' + s.angle.length + ' chars) — aim for 80+ chars naming competitor + moat');
    if (typeof s.why === 'string' && !/moat|primary[- ]source|jobs|github|data/i.test(s.why)) rowWarns.push('why does not mention a moat signal (moat / primary-source / jobs / github / data)');
    if (typeof s.title === 'string' && typeof s.target_query === 'string' &&
        s.title.indexOf('2026') === -1 && /rag|agent|llm|gpt|claude|gemini/i.test(s.target_query))
      rowWarns.push('fast-decay topic — consider year-qualifying the title (add "2026")');

    if (rowErrs.length) errors[i] = rowErrs;
    if (rowWarns.length) warnings[i] = rowWarns;
  });

  if (flagshipCount > 1) {
    for (var j = 0; j < suggestions.length; j++) {
      if (suggestions[j].tier === 'flagship') {
        if (!errors[j]) errors[j] = [];
        if (j > 0) errors[j].push('Only 1 flagship allowed per batch — this is the 2nd+');
      }
    }
  }

  renderSuggestionsPreview({ suggestions: suggestions, errors: errors, warnings: warnings });
}

function _renderSuggestionsError(msg) {
  var el = document.getElementById('suggestionsPreview');
  el.innerHTML = '<div class="sug-err" style="margin-top:8px">' + _esc(msg) + '</div>';
}

function renderSuggestionsPreview(result) {
  var suggestions = result.suggestions;
  var errors = result.errors || {};
  var warnings = result.warnings || {};
  var el = document.getElementById('suggestionsPreview');
  el.innerHTML = '';

  var TIER_BADGE_FN = function(t) {
    if (t === 'flagship')
      return '<span style="display:inline-block;font-family:\\'IBM Plex Mono\\',ui-monospace,monospace;font-size:9px;letter-spacing:0.1em;text-transform:uppercase;padding:2px 8px;border-radius:10px;background:rgba(217,119,87,0.22);color:#f5a58a;border:1px solid rgba(217,119,87,0.55)">Flagship</span>';
    return '<span style="display:inline-block;font-family:\\'IBM Plex Mono\\',ui-monospace,monospace;font-size:9px;letter-spacing:0.1em;text-transform:uppercase;padding:2px 8px;border-radius:10px;background:rgba(232,168,73,0.22);color:#f5c06a;border:1px solid rgba(232,168,73,0.55)">Pillar</span>';
  };

  var headerDiv = document.createElement('div');
  headerDiv.id = 'sugCountLine';
  headerDiv.style.cssText = 'font-size:12px;color:#94a3b8;margin-bottom:8px';
  el.appendChild(headerDiv);

  suggestions.forEach(function(s, i) {
    var hasErr = !!errors[i];
    var hasWarn = !!warnings[i];
    var rowDiv = document.createElement('div');
    rowDiv.className = 'sug-row';
    if (hasErr) rowDiv.style.borderColor = 'rgba(239,68,68,0.4)';
    else if (hasWarn) rowDiv.style.borderColor = 'rgba(232,168,73,0.35)';

    var checked = hasErr ? '' : 'checked';
    var cmpTag = s.comparative
      ? '<span style="font-size:10px;color:#f5c06a">comparative</span>'
      : '<span style="font-size:10px;color:#94a3b8">non-comparative</span>';
    var schemaStr = 'Article + FAQPage + ' + _esc(s.schema || '') + (s.schema_extra ? ' + ' + _esc(s.schema_extra) : '');
    var angleHtml = s.angle ? '<div style="font-size:11px;color:#d0cbc2;margin-top:3px;line-height:1.4"><em>' + _esc(s.angle) + '</em></div>' : '';

    var inner = ''
      + '<div class="sug-row-head">'
      +   '<label style="display:flex;align-items:flex-start;gap:8px;cursor:pointer;margin:0">'
      +     '<input type="checkbox" class="sug-chk" data-idx="' + i + '" ' + checked + ' style="margin-top:3px" onchange="_updateSugApply()">'
      +     '<div>'
      +       '<div class="sug-row-title">' + _esc(s.title || '') + '</div>'
      +       '<div class="sug-row-meta">target: <code>' + _esc(s.target_query || '') + '</code> &nbsp; ' + TIER_BADGE_FN(s.tier) + ' &nbsp; ' + cmpTag + '</div>'
      +       '<div class="sug-row-meta" style="margin-top:2px">schema: ' + schemaStr + '</div>'
      +       '<div class="sug-row-why">why: ' + _esc(s.why || '') + '</div>'
      +       angleHtml
      +     '</div>'
      +   '</label>'
      + '</div>';

    if (hasErr) {
      inner += '<div class="sug-err">' + errors[i].map(function(e) { return '✗ ' + _esc(e); }).join('<br>') + '</div>';
    }
    if (hasWarn) {
      inner += '<div class="sug-warn">' + warnings[i].map(function(w) { return '⚠ ' + _esc(w); }).join('<br>') + '</div>';
    }

    rowDiv.innerHTML = inner;
    el.appendChild(rowDiv);
  });

  var applyRow = document.createElement('div');
  applyRow.className = 'sug-apply-row';
  applyRow.id = 'sugApplyRow';
  applyRow.innerHTML = ''
    + '<button class="btn primary" id="sugApplyBtn" onclick="applyCheckedSuggestions()">Replace slate with checked</button>'
    + '<span class="sug-count" id="sugCountBadge"></span>';
  el.appendChild(applyRow);
  // Undo button + confirmation message live in the persistent #suggestionsFooter,
  // so they survive after the preview area is cleared on Replace.
  _updateSugApply();
}

function _updateSugApply() {
  var chks = document.querySelectorAll('.sug-chk');
  if (!chks.length) return;
  var checked = 0;
  var checkedHasErr = false;
  chks.forEach(function(chk) {
    if (chk.checked) {
      checked++;
      // check if this row has a hard error by looking at its sibling .sug-err
      var row = chk.closest('.sug-row');
      if (row && row.querySelector('.sug-err')) checkedHasErr = true;
    }
  });
  var badge = document.getElementById('sugCountBadge');
  if (badge) badge.textContent = checked + ' checked / ' + chks.length;
  var applyBtn = document.getElementById('sugApplyBtn');
  if (applyBtn) applyBtn.disabled = (checked === 0 || checkedHasErr);
  var hdr = document.getElementById('sugCountLine');
  if (hdr) hdr.textContent = checked + ' checked / ' + chks.length + ' ready';
}

// Multi-level undo: each Replace pushes the prior PILLAR_BRIEFS onto a
// localStorage history stack capped at PILLAR_HISTORY_MAX entries (oldest
// drops on overflow). Undo pops the most recent. Persists across reloads.
var PILLAR_HISTORY_KEY = '_pillarBriefsHistory';
var PILLAR_HISTORY_MAX = 10;

function _readPillarHistory() {
  try {
    var raw = localStorage.getItem(PILLAR_HISTORY_KEY);
    if (!raw) return [];
    var arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr : [];
  } catch (e) { return []; }
}

function _writePillarHistory(arr) {
  var trimmed = arr.slice(-PILLAR_HISTORY_MAX);
  localStorage.setItem(PILLAR_HISTORY_KEY, JSON.stringify(trimmed));
}

function _updateUndoState() {
  var btn = document.getElementById('sugUndoBtn');
  if (!btn) return;
  var depth = _readPillarHistory().length;
  btn.disabled = (depth === 0);
  btn.textContent = depth > 0 ? ('Undo (' + depth + ')') : 'Undo';
  btn.title = depth > 0
    ? ('Restore prior slate \\u00b7 ' + depth + ' undo level' + (depth !== 1 ? 's' : '') + ' available')
    : 'No prior slate to restore';
}

function applyCheckedSuggestions() {
  var chks = document.querySelectorAll('.sug-chk');
  var chosen = [];
  chks.forEach(function(chk) {
    if (chk.checked) {
      var idx = parseInt(chk.getAttribute('data-idx'), 10);
      var s = _lastSuggestions && _lastSuggestions[idx];
      if (s) chosen.push(s);
    }
  });
  if (!chosen.length) return;
  // Push current slate onto the history stack (multi-level undo)
  var history = _readPillarHistory();
  history.push(PILLAR_BRIEFS);
  _writePillarHistory(history);
  PILLAR_BRIEFS = chosen.map(function(s, i) {
    return {
      n: i + 1,
      tier: s.tier,
      title: s.title,
      target_query: s.target_query,
      angle: s.angle || '',
      schema: s.schema,
      schema_extra: s.schema_extra || '',
      comparative: !!s.comparative,
      why: s.why || '',
    };
  });
  renderPillarBriefs();
  var tbl = document.getElementById('pillarBriefsTbody');
  if (tbl) tbl.scrollIntoView({ behavior: 'smooth', block: 'start' });
  document.getElementById('suggestionsPreview').innerHTML = '';
  document.getElementById('suggestionsJsonInput').value = '';
  _lastSuggestions = null;
  // Persistent footer message survives the preview clear.
  var depth = _readPillarHistory().length;
  var msg = document.getElementById('sugConfirmMsg');
  if (msg) msg.textContent = '\\u2713 Replaced slate with ' + chosen.length + ' brief' + (chosen.length !== 1 ? 's' : '') + ' \\u00b7 ' + depth + ' undo level' + (depth !== 1 ? 's' : '') + ' available';
  _updateUndoState();
}

function undoSuggestionsReplace() {
  var history = _readPillarHistory();
  if (!history.length) return;
  var prev = history.pop();
  _writePillarHistory(history);
  if (!Array.isArray(prev)) {
    var msgErr = document.getElementById('sugConfirmMsg');
    if (msgErr) { msgErr.style.color = '#fca5a5'; msgErr.textContent = '\\u2717 Could not restore \\u2014 saved slate was malformed; popped from history.'; }
    _updateUndoState();
    return;
  }
  PILLAR_BRIEFS = prev;
  renderPillarBriefs();
  var msg = document.getElementById('sugConfirmMsg');
  if (msg) {
    msg.style.color = '#8fd0a5';
    msg.textContent = '\\u21a9 Restored prior slate \\u00b7 ' + history.length + ' undo level' + (history.length !== 1 ? 's' : '') + ' remaining';
  }
  _updateUndoState();
}

// Holds last parsed suggestions so applyCheckedSuggestions() can read them.
// Set inside parseAndValidateSuggestions() after renderSuggestionsPreview().
var _lastSuggestions = null;
// Patch parseAndValidateSuggestions to store _lastSuggestions after render.
(function() {
  var _orig = parseAndValidateSuggestions;
  parseAndValidateSuggestions = function() {
    _orig();
    // After render, extract suggestions from rendered checkboxes index map
    // by re-reading the JSON (already validated above). Simpler: re-parse here.
    var raw = document.getElementById('suggestionsJsonInput').value.trim();
    if (!raw) return;
    var stripped = raw.replace(/^\\s*```(?:json)?/i, '').replace(/```\\s*$/, '').trim();
    try { _lastSuggestions = JSON.parse(stripped); } catch (e) { _lastSuggestions = null; }
  };
})();

document.addEventListener('DOMContentLoaded', function() {
  renderPillarBriefs();
  // One-shot migration: old single-key backup ('_pillarBriefsBackup') becomes
  // a single-element history. Then drop the legacy key.
  try {
    var legacy = localStorage.getItem('_pillarBriefsBackup');
    if (legacy) {
      var hist = _readPillarHistory();
      if (!hist.length) {
        var parsed = JSON.parse(legacy);
        if (Array.isArray(parsed)) { hist.push(parsed); _writePillarHistory(hist); }
      }
      localStorage.removeItem('_pillarBriefsBackup');
    }
  } catch (e) { /* corrupt legacy entry \\u2014 drop and move on */ }
  _updateUndoState();
});

// --------------- Upload / validate / save draft ---------------
function parseJsonInput() {
  const raw = document.getElementById('blogJsonInput').value.trim();
  if (!raw) return { error: 'Paste Claude\\'s JSON first.' };
  // Strip accidental code fences
  const stripped = raw.replace(/^\\s*```(?:json)?/i, '').replace(/```\\s*$/, '').trim();
  try { return { data: JSON.parse(stripped) }; }
  catch (e) { return { error: 'Invalid JSON: ' + e.message }; }
}
function renderValidationReport(report) {
  const el = document.getElementById('validationResult');
  el.innerHTML = '';
  if (report.errors && report.errors.length) {
    const d = document.createElement('div');
    d.className = 'val-result val-err';
    d.textContent = '✗ ' + report.errors.length + ' blocking error(s):\\n\\n' + report.errors.map(e => '  • ' + e).join('\\n');
    el.appendChild(d);
  } else {
    const d = document.createElement('div');
    d.className = 'val-result val-ok';
    const s = report.stats || {};
    d.textContent = '✓ No blocking errors. Ready to save as draft.\\n\\n' +
      'Word count: ' + (s.word_count || '?') + '  ·  H2 sections: ' + (s.h2_count || '?') +
      '  ·  Paragraphs: ' + (s.paragraphs || '?') + '  ·  Long paragraphs: ' + (s.long_paragraphs || 0) +
      '  ·  Long sentences: ' + (s.long_sentences || 0) + '  ·  OG length: ' + (s.og_length || 0) +
      '  ·  Quotables: ' + (s.quotable_lines || 0);
    el.appendChild(d);
  }
  if (report.warnings && report.warnings.length) {
    const w = document.createElement('div');
    w.className = 'val-result val-warn';
    w.textContent = '⚠ ' + report.warnings.length + ' warning(s) — review but not blocking:\\n\\n' + report.warnings.map(e => '  • ' + e).join('\\n');
    el.appendChild(w);
  }
}
async function validateJson() {
  const parsed = parseJsonInput();
  if (parsed.error) { renderValidationReport({ errors: [parsed.error], warnings: [], stats: {} }); return; }
  try {
    const resp = await fetch('/admin/api/blog/validate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin', body: JSON.stringify(parsed.data),
    });
    const report = await resp.json();
    renderValidationReport(report);
  } catch (e) { renderValidationReport({ errors: ['Network: ' + e.message], warnings: [], stats: {} }); }
}
async function saveDraft() {
  const parsed = parseJsonInput();
  if (parsed.error) { renderValidationReport({ errors: [parsed.error], warnings: [], stats: {} }); return; }
  try {
    const resp = await fetch('/admin/api/blog/draft', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin', body: JSON.stringify(parsed.data),
    });
    if (!resp.ok) {
      const d = await resp.json().catch(() => ({}));
      const errs = (d.detail && d.detail.errors) || [d.detail || 'Save failed.'];
      const warns = (d.detail && d.detail.warnings) || [];
      renderValidationReport({ errors: errs, warnings: warns, stats: {} });
      return;
    }
    const data = await resp.json();
    const el = document.getElementById('validationResult');
    el.innerHTML = '<div class="val-result val-ok">✓ Draft saved: ' + data.slug + '. Reloading…</div>';
    setTimeout(() => location.reload(), 900);
  } catch (e) { renderValidationReport({ errors: ['Network: ' + e.message], warnings: [], stats: {} }); }
}
function clearJsonInput() {
  document.getElementById('blogJsonInput').value = '';
  document.getElementById('validationResult').innerHTML = '';
  document.getElementById('bpFileName').textContent = '';
  document.getElementById('blogJsonFile').value = '';
}

function handleJsonFile(evt) {
  const file = evt.target.files && evt.target.files[0];
  if (!file) return;
  const fileNameEl = document.getElementById('bpFileName');
  if (file.size > 2 * 1024 * 1024) {
    fileNameEl.textContent = '✗ File too large (2 MB max).';
    fileNameEl.style.color = '#fca5a5';
    return;
  }
  const reader = new FileReader();
  reader.onload = function(e) {
    const text = (e.target.result || '').toString();
    const stripped = text.replace(/^\\s*```(?:json)?/i, '').replace(/```\\s*$/, '').trim();
    document.getElementById('blogJsonInput').value = stripped;
    fileNameEl.textContent = '✓ Loaded: ' + file.name + ' (' + (file.size / 1024).toFixed(1) + ' KB) — click Validate.';
    fileNameEl.style.color = '#8fd0a5';
    document.getElementById('validationResult').innerHTML = '';
  };
  reader.onerror = function() {
    fileNameEl.textContent = '✗ Failed to read file.';
    fileNameEl.style.color = '#fca5a5';
  };
  reader.readAsText(file);
}

// --------------- Draft actions ---------------
async function publishDraft(slug) {
  if (!confirm('Publish "' + slug + '" to /blog/' + slug + '? This stamps you as the reviewer and makes it live.')) return;
  const resp = await fetch('/admin/api/blog/publish', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin', body: JSON.stringify({ slug: slug }),
  });
  if (!resp.ok) { const d = await resp.json().catch(() => ({})); alert('Publish failed: ' + (d.detail || 'unknown')); return; }
  location.reload();
}
async function deleteDraft(slug) {
  if (!confirm('Delete draft "' + slug + '"? This cannot be undone.')) return;
  const resp = await fetch('/admin/api/blog/draft', {
    method: 'DELETE', headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin', body: JSON.stringify({ slug: slug }),
  });
  if (!resp.ok) { alert('Delete failed.'); return; }
  location.reload();
}
async function validateDraft(slug) {
  const resp = await fetch('/admin/api/blog/validate-draft?slug=' + encodeURIComponent(slug), { credentials: 'same-origin' });
  if (!resp.ok) { alert('Re-check failed.'); return; }
  const report = await resp.json();
  renderValidationReport(report);
  window.scrollTo({ top: document.body.scrollHeight / 2, behavior: 'smooth' });
}
async function unpublish(slug) {
  if (!confirm('Unpublish "' + slug + '"? It moves back to drafts (not deleted).')) return;
  const resp = await fetch('/admin/api/blog/unpublish', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin', body: JSON.stringify({ slug: slug }),
  });
  if (!resp.ok) { alert('Unpublish failed.'); return; }
  location.reload();
}
</script>
</body></html>"""


@router.get("/api/blog/validate-draft")
async def admin_blog_validate_draft(slug: str, _user: User = Depends(get_current_admin)):
    """Re-run validation on a saved draft without re-pasting."""
    from app.services.blog_publisher import load_draft, validate_payload
    d = load_draft(slug)
    if not d:
        raise HTTPException(status_code=404, detail=f"No draft '{slug}'")
    return validate_payload(d)


@router.post("/api/blog/image")
async def admin_blog_image_upload(request: Request, user: User = Depends(get_current_admin)):
    """Upload a hero image for a blog post. Stores under
    /data/blog/assets/<slug>-hero.<ext> and returns the public URL
    the editor can drop into body_html / image_brief."""
    _check_origin(request)
    from app.services.blog_publisher import save_image

    form = await request.form()
    slug = (form.get("slug") or "").strip()
    upload = form.get("image")
    if upload is None or not hasattr(upload, "filename"):
        raise HTTPException(status_code=400, detail="Image file is required (form field: image).")
    if not slug:
        raise HTTPException(status_code=400, detail="slug required")
    data = await upload.read()
    try:
        result = save_image(slug, upload.filename, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "slug": slug, **result}


@router.post("/api/blog/draft/update")
async def admin_blog_update_draft(request: Request, user: User = Depends(get_current_admin)):
    """Update an existing draft. Body must include every field (full replace).
    Re-runs validator before saving. Errors block, warnings allowed."""
    _check_origin(request)
    from app.services.blog_publisher import validate_payload, save_draft, load_draft
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Body must be JSON.")
    slug = (body.get("slug") or "").strip()
    if not slug:
        raise HTTPException(status_code=400, detail="slug required")
    if not load_draft(slug):
        raise HTTPException(status_code=404, detail=f"No draft '{slug}'")
    report = validate_payload(body)
    if not report["ok"]:
        raise HTTPException(status_code=400, detail={"errors": report["errors"], "warnings": report["warnings"]})
    save_draft(body, admin_name=user.name or user.email)
    return {"ok": True, "slug": slug, "warnings": report["warnings"], "stats": report["stats"]}


@router.get("/blog/{slug}/edit", response_class=HTMLResponse)
async def admin_blog_edit_page(slug: str, _user: User = Depends(get_current_admin)):
    """Full-form editor for a draft. All fields editable. Save runs
    the validator and updates the JSON on disk."""
    from app.services.blog_publisher import load_draft
    draft = load_draft(slug)
    if not draft:
        raise HTTPException(status_code=404, detail=f"No draft '{slug}'")

    import json as _json

    title = esc(draft.get("title", ""))
    old_slug = esc(draft.get("slug", slug))
    author = esc(draft.get("author", ""))
    published = esc(draft.get("published", ""))
    og = esc(draft.get("og_description", ""))
    lede = esc(draft.get("lede", ""))
    body_html = esc(draft.get("body_html", ""))
    tags_csv = esc(", ".join(draft.get("tags", []) or []))
    quotables = esc("\n".join(draft.get("quotable_lines", []) or []))
    word_count = int(draft.get("word_count", 0) or 0)
    ib = draft.get("image_brief", {}) or {}
    hero_prompt = esc(ib.get("hero_prompt", ""))
    hero_alt = esc(ib.get("hero_alt", ""))
    hero_filename = esc(ib.get("hero_filename", ""))
    angle_note = esc(draft.get("angle_note", "") or "")

    # The full draft JSON inline so the JS has one source of truth for
    # unchanged fields (avoids losing _saved_at, _saved_by, etc.).
    full_json_b64 = _json.dumps(draft)

    return HTMLResponse(_BLOG_EDIT_HTML
        .replace("{{ADMIN_CSS}}", ADMIN_CSS)
        .replace("{{ADMIN_NAV}}", ADMIN_NAV)
        .replace("{{SLUG}}", esc(slug))
        .replace("{{TITLE}}", title)
        .replace("{{OLD_SLUG}}", old_slug)
        .replace("{{AUTHOR}}", author)
        .replace("{{PUBLISHED}}", published)
        .replace("{{OG}}", og)
        .replace("{{LEDE}}", lede)
        .replace("{{BODY_HTML}}", body_html)
        .replace("{{TAGS_CSV}}", tags_csv)
        .replace("{{QUOTABLES}}", quotables)
        .replace("{{WORD_COUNT}}", str(word_count))
        .replace("{{HERO_PROMPT}}", hero_prompt)
        .replace("{{HERO_ALT}}", hero_alt)
        .replace("{{HERO_FILENAME}}", hero_filename)
        .replace("{{ANGLE_NOTE}}", angle_note)
        .replace("{{FULL_JSON_B64}}", full_json_b64.replace("</", "<\\/"))
    )


_BLOG_EDIT_HTML = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><title>Edit Draft — Admin</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{{ADMIN_CSS}}
  .edit-layout { display:grid; grid-template-columns:1fr; gap:14px; max-width:100%; margin:0 auto; }
  .field { display:flex; flex-direction:column; gap:6px; }
  .field label { font-family:'IBM Plex Mono',ui-monospace,monospace; font-size:11px; letter-spacing:0.1em; text-transform:uppercase; color:#94a3b8; }
  .field label .hint { color:#64748b; font-size:10px; letter-spacing:0.05em; margin-left:8px; text-transform:none; }
  .field input, .field textarea { padding:10px 12px; background:#0f1419; border:1px solid #2a323d; color:#f5f1e8; border-radius:4px; font-family:inherit; font-size:14px; }
  .field textarea { font-family:'IBM Plex Mono',ui-monospace,monospace; font-size:13px; line-height:1.55; resize:vertical; }
  .field textarea.body-html { min-height:380px; }
  .field textarea.med { min-height:80px; }
  .field textarea.sm { min-height:50px; }
  .row-2 { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
  .row-3 { display:grid; grid-template-columns:2fr 1fr 1fr; gap:14px; }
  @media (max-width:720px) { .row-2, .row-3 { grid-template-columns:1fr; } }
  .card { background:#1d242e; border:1px solid #2a323d; border-radius:6px; padding:18px 20px; margin-bottom:14px; }
  .card h2 { margin:0 0 12px; font-size:14px; color:#e8a849; font-family:'Fraunces',Georgia,serif; font-weight:500; }
  .actions-sticky { position:sticky; bottom:0; background:rgba(15,20,25,0.95); backdrop-filter:blur(8px); padding:14px 0; border-top:1px solid #2a323d; display:flex; gap:10px; justify-content:space-between; align-items:center; flex-wrap:wrap; z-index:10; }
  .val-result { padding:10px 14px; border-radius:4px; font-family:'IBM Plex Mono',ui-monospace,monospace; font-size:12px; line-height:1.55; white-space:pre-wrap; }
  .val-ok { background:rgba(109,181,133,0.1); border:1px solid rgba(109,181,133,0.35); color:#8fd0a5; }
  .val-err { background:rgba(239,68,68,0.1); border:1px solid rgba(239,68,68,0.35); color:#fca5a5; }
  .val-warn { background:rgba(232,168,73,0.08); border:1px solid rgba(232,168,73,0.3); color:#f5c06a; margin-top:6px; }
  .btn { font-family:'IBM Plex Mono',ui-monospace,monospace; font-size:11px; letter-spacing:0.1em; text-transform:uppercase; padding:9px 16px; background:transparent; border:1px solid #3a4452; color:#e8e2d3; cursor:pointer; border-radius:3px; text-decoration:none; display:inline-block; }
  .btn:hover { border-color:#e8a849; color:#e8a849; }
  .btn.primary { background:#e8a849; color:#0f1419; border-color:#e8a849; }
  .btn.primary:hover { background:#c98e2f; border-color:#c98e2f; color:#0f1419; }
  .btn.success { border-color:#6db585; color:#6db585; }
  .btn.danger { border-color:#d97757; color:#d97757; }
</style>
</head>
<body>
{{ADMIN_NAV}}
<main class="page" style="max-width:100%;margin:0 auto;padding:28px clamp(20px,4vw,64px) 80px">
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:10px;flex-wrap:wrap">
    <a href="/admin/blog" class="btn">← Back to blog admin</a>
    <a href="/admin/blog/{{SLUG}}/preview" target="_blank" class="btn">Preview ↗</a>
    <div style="font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:11px;color:#94a3b8;letter-spacing:0.08em">editing draft · <code style="color:#e8a849">{{SLUG}}</code></div>
  </div>
  <h1 style="font-family:'Fraunces',Georgia,serif;color:#e8a849;font-weight:400;font-size:26px;margin:0 0 6px">Edit draft</h1>
  <p style="color:#94a3b8;font-size:13px;line-height:1.55;margin:0 0 14px;max-width:880px">
    Tune copy, tighten prose, fix tags, swap the hero image, or rewrite sections that didn't land.
    <strong style="color:#f5c06a">Save</strong> re-runs the validator and writes back to
    <code style="color:#e8a849">/data/blog/drafts/{{SLUG}}.json</code>. Publish from the main list when ready.
  </p>

  <details class="how-to" style="background:#0f1419;border:1px solid #2a323d;border-radius:4px;padding:12px 16px;margin-bottom:18px;font-size:13px;line-height:1.65">
    <summary style="cursor:pointer;color:#e8a849;font-weight:600;user-select:none">Editing guidelines (click to expand)</summary>
    <div style="margin-top:12px;color:#d0cbc2">
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px">
        <div>
          <h4 style="color:#e8a849;font-family:'Fraunces',Georgia,serif;font-weight:500;margin:0 0 6px;font-size:14px">Voice &amp; tone</h4>
          <ul style="margin:0;padding-left:20px;color:#c0c4cc">
            <li>Simple English, active voice, short sentences (&lt; 30 words).</li>
            <li>One dry observational line per 4–6 paragraphs. No memes.</li>
            <li>"You" and "I" — never generic "we".</li>
            <li>Specific numbers and real moments beat fuzzy claims.</li>
          </ul>
        </div>
        <div>
          <h4 style="color:#e8a849;font-family:'Fraunces',Georgia,serif;font-weight:500;margin:0 0 6px;font-size:14px">Structure</h4>
          <ul style="margin:0;padding-left:20px;color:#c0c4cc">
            <li>Body starts with <code>&lt;p class="lede"&gt;</code>.</li>
            <li>At least 3 <code>&lt;h2&gt;</code> section headings.</li>
            <li><strong style="color:#f5c06a">Zero paragraphs over 4 sentences</strong> — this is the warning that bites most drafts.</li>
            <li>Target 800–1500 words, one clear takeaway.</li>
          </ul>
        </div>
        <div>
          <h4 style="color:#e8a849;font-family:'Fraunces',Georgia,serif;font-weight:500;margin:0 0 6px;font-size:14px">Banned content</h4>
          <ul style="margin:0;padding-left:20px;color:#c0c4cc">
            <li>No stack names (FastAPI, SQLite, nginx, etc.).</li>
            <li>No AI provider names (Claude, Gemini, OpenAI, Groq…).</li>
            <li>No repo URLs, session numbers, commit hashes, field names.</li>
            <li>No exact credit balances or per-call costs.</li>
          </ul>
        </div>
        <div>
          <h4 style="color:#e8a849;font-family:'Fraunces',Georgia,serif;font-weight:500;margin:0 0 6px;font-size:14px">Image</h4>
          <ul style="margin:0;padding-left:20px;color:#c0c4cc">
            <li>One hero image, 16:9, realistic-digital (no cartoons, no flat vectors).</li>
            <li>Dark-palette friendly — warm amber / slate accents.</li>
            <li>No text baked into the image — captions go in alt text.</li>
            <li>Upload PNG/JPG/WEBP ≤ 5 MB in the Hero image brief card below.</li>
          </ul>
        </div>
        <div>
          <h4 style="color:#e8a849;font-family:'Fraunces',Georgia,serif;font-weight:500;margin:0 0 6px;font-size:14px">Publish flow</h4>
          <ul style="margin:0;padding-left:20px;color:#c0c4cc">
            <li>Edit → Validate → Save draft → Preview ↗ → Publish.</li>
            <li>Warnings are judgement calls; errors block publication.</li>
            <li>Slug rename keeps one file on disk, but breaks any old links.</li>
            <li>Full rules in <a href="https://github.com/manishjnv/AIExpert/blob/master/docs/blog/STYLE.md" target="_blank" style="color:#e8a849">STYLE.md</a> + <a href="https://github.com/manishjnv/AIExpert/blob/master/docs/blog/ADMIN_GUIDE.md" target="_blank" style="color:#e8a849">ADMIN_GUIDE.md</a>.</li>
          </ul>
        </div>
      </div>
    </div>
  </details>

  <div class="edit-layout">
    <div class="card">
      <h2>Identity</h2>
      <div class="field">
        <label>Title</label>
        <input id="fTitle" value="{{TITLE}}" maxlength="150">
      </div>
      <div class="row-3" style="margin-top:10px">
        <div class="field">
          <label>Slug <span class="hint">changing breaks existing links</span></label>
          <input id="fSlug" value="{{OLD_SLUG}}">
        </div>
        <div class="field"><label>Author</label><input id="fAuthor" value="{{AUTHOR}}"></div>
        <div class="field"><label>Published (ISO)</label><input id="fPublished" value="{{PUBLISHED}}" placeholder="YYYY-MM-DD"></div>
      </div>
      <div class="field" style="margin-top:10px">
        <label>Tags <span class="hint">comma-separated, 3–5, first must be build-in-public</span></label>
        <input id="fTags" value="{{TAGS_CSV}}">
      </div>
      <div class="field" style="margin-top:10px">
        <label>OG description <span class="hint">≤ 200 chars, shown in link previews</span></label>
        <textarea id="fOg" class="sm">{{OG}}</textarea>
      </div>
    </div>

    <div class="card">
      <h2>Body</h2>
      <div class="field">
        <label>Lede <span class="hint">plain text, one sentence, under 30 words</span></label>
        <textarea id="fLede" class="sm">{{LEDE}}</textarea>
      </div>
      <div class="field" style="margin-top:10px">
        <label>Body HTML <span class="hint">opens with &lt;p class="lede"&gt;, ≥3 &lt;h2&gt; sections, ≤4 sentences per paragraph</span></label>
        <textarea id="fBody" class="body-html">{{BODY_HTML}}</textarea>
      </div>
      <div class="field" style="margin-top:10px">
        <label>Word count <span class="hint">we'll re-measure from body_html on save</span></label>
        <input id="fWordCount" value="{{WORD_COUNT}}" type="number" min="0" style="max-width:160px">
      </div>
    </div>

    <div class="card">
      <h2>Hero image</h2>
      <div style="display:grid;grid-template-columns:minmax(220px,280px) 1fr;gap:18px;align-items:start">
        <div style="display:flex;flex-direction:column;gap:8px">
          <div id="heroPreview" style="border:1px dashed #3a4452;border-radius:6px;background:#0f1419;aspect-ratio:16/9;display:flex;align-items:center;justify-content:center;overflow:hidden;color:#64748b;font-size:12px;font-family:'IBM Plex Mono',ui-monospace,monospace;text-align:center;padding:8px">No image uploaded yet<br><span style="opacity:0.7">(16:9 preview appears here)</span></div>
          <label for="blogHeroFile" class="btn" style="cursor:pointer;text-align:center">📤 Upload image</label>
          <input id="blogHeroFile" type="file" accept="image/png,image/jpeg,image/webp,.png,.jpg,.jpeg,.webp" style="display:none" onchange="uploadHeroImage(event)">
          <div id="heroUploadStatus" style="font-size:11px;color:#94a3b8;font-family:'IBM Plex Mono',ui-monospace,monospace;min-height:16px;line-height:1.4"></div>
          <div style="font-size:10px;color:#64748b;line-height:1.5">PNG / JPG / WEBP · ≤ 5 MB · 16:9 recommended · goes to <code>/data/blog/assets/</code> on the VPS.</div>
        </div>
        <div style="display:flex;flex-direction:column;gap:10px">
          <div class="field">
            <label>Hero prompt <span class="hint">40–90 words, photoreal + digital, dark palette</span></label>
            <textarea id="fHeroPrompt" class="med">{{HERO_PROMPT}}</textarea>
          </div>
          <div class="field">
            <label>Alt text <span class="hint">literal description — screen readers + SEO fallback</span></label>
            <input id="fHeroAlt" value="{{HERO_ALT}}">
          </div>
          <div class="field">
            <label>Filename <span class="hint">auto-filled when you upload; stored at /blog/assets/&lt;filename&gt;</span></label>
            <input id="fHeroFilename" value="{{HERO_FILENAME}}">
          </div>
        </div>
      </div>
    </div>

    <div class="card">
      <h2>Quotable lines + editor notes</h2>
      <div class="field">
        <label>Quotable lines <span class="hint">one per line — 1 or 2 shareable sentences</span></label>
        <textarea id="fQuotables" class="med">{{QUOTABLES}}</textarea>
      </div>
      <div class="field" style="margin-top:10px">
        <label>Angle note <span class="hint">not published — editorial commentary for you</span></label>
        <textarea id="fAngleNote" class="sm">{{ANGLE_NOTE}}</textarea>
      </div>
    </div>

    <div id="validationResult"></div>

    <div class="actions-sticky">
      <a href="/admin/blog" class="btn danger">Discard changes</a>
      <div style="display:flex;gap:8px">
        <button class="btn" onclick="validateEdit()">Validate</button>
        <button class="btn primary" onclick="saveEdit()">Save changes</button>
      </div>
    </div>
  </div>
</main>

<script>
const ORIGINAL_JSON = {{FULL_JSON_B64}};
const ORIGINAL_SLUG = ORIGINAL_JSON.slug;

// --------------- Hero image upload + preview ---------------
function _applyHeroPreview(url) {
  const el = document.getElementById('heroPreview');
  el.innerHTML = '<img src="' + url + '" style="width:100%;height:100%;object-fit:cover;display:block" alt="hero preview">';
}
// If the draft already has a filename, show the image.
(function() {
  const existing = (document.getElementById('fHeroFilename').value || '').trim();
  if (existing) { _applyHeroPreview('/blog/assets/' + encodeURIComponent(existing)); }
})();

async function uploadHeroImage(evt) {
  const file = evt.target.files && evt.target.files[0];
  if (!file) return;
  const statusEl = document.getElementById('heroUploadStatus');
  if (file.size > 5 * 1024 * 1024) {
    statusEl.textContent = '✗ File too large (5 MB max).'; statusEl.style.color = '#fca5a5';
    return;
  }
  const slug = document.getElementById('fSlug').value.trim() || ORIGINAL_SLUG;
  const fd = new FormData();
  fd.append('image', file, file.name);
  fd.append('slug', slug);
  statusEl.style.color = '#94a3b8';
  statusEl.textContent = 'Uploading ' + (file.size / 1024).toFixed(1) + ' KB…';
  try {
    const resp = await fetch('/admin/api/blog/image', {
      method: 'POST', credentials: 'same-origin', body: fd,
    });
    if (!resp.ok) {
      const d = await resp.json().catch(() => ({}));
      statusEl.style.color = '#fca5a5';
      statusEl.textContent = '✗ ' + (d.detail || 'Upload failed.');
      return;
    }
    const data = await resp.json();
    document.getElementById('fHeroFilename').value = data.filename;
    if (!document.getElementById('fHeroAlt').value.trim()) {
      // Leave alt blank for admin to fill; just nudge with a placeholder pattern
    }
    // Cache-bust so the preview updates even if the filename hasn't changed
    _applyHeroPreview(data.url + '?t=' + Date.now());
    statusEl.style.color = '#8fd0a5';
    statusEl.textContent = '✓ Saved as ' + data.filename + ' (' + (data.size / 1024).toFixed(1) + ' KB).';
  } catch (e) {
    statusEl.style.color = '#fca5a5';
    statusEl.textContent = '✗ Network error: ' + e.message;
  }
}

function buildPayload() {
  // Preserve any fields we don't edit (like _saved_at). Overlay edited.
  const p = Object.assign({}, ORIGINAL_JSON);
  p.title = document.getElementById('fTitle').value.trim();
  p.slug = document.getElementById('fSlug').value.trim();
  p.author = document.getElementById('fAuthor').value.trim();
  p.published = document.getElementById('fPublished').value.trim();
  p.tags = document.getElementById('fTags').value.split(',').map(s => s.trim()).filter(Boolean);
  p.og_description = document.getElementById('fOg').value.trim();
  p.lede = document.getElementById('fLede').value.trim();
  p.body_html = document.getElementById('fBody').value;
  p.word_count = parseInt(document.getElementById('fWordCount').value, 10) || 0;
  p.image_brief = Object.assign({}, p.image_brief || {}, {
    hero_prompt: document.getElementById('fHeroPrompt').value.trim(),
    hero_alt: document.getElementById('fHeroAlt').value.trim(),
    hero_filename: document.getElementById('fHeroFilename').value.trim(),
  });
  p.quotable_lines = document.getElementById('fQuotables').value
    .split('\\n').map(s => s.trim()).filter(Boolean);
  p.angle_note = document.getElementById('fAngleNote').value.trim();
  // Include the ORIGINAL slug so the backend can find the source draft
  // even if we renamed the slug field.
  p._original_slug = ORIGINAL_SLUG;
  return p;
}

function renderReport(report) {
  const el = document.getElementById('validationResult');
  el.innerHTML = '';
  if (report.errors && report.errors.length) {
    const d = document.createElement('div');
    d.className = 'val-result val-err';
    d.textContent = '✗ ' + report.errors.length + ' blocking error(s):\\n\\n' + report.errors.map(e => '  • ' + e).join('\\n');
    el.appendChild(d);
  } else if (!(report.warnings && report.warnings.length)) {
    const d = document.createElement('div');
    d.className = 'val-result val-ok';
    d.textContent = '✓ Clean — all checks pass.';
    el.appendChild(d);
  } else {
    const d = document.createElement('div');
    d.className = 'val-result val-ok';
    d.textContent = '✓ No blocking errors.';
    el.appendChild(d);
  }
  if (report.warnings && report.warnings.length) {
    const w = document.createElement('div');
    w.className = 'val-result val-warn';
    w.textContent = '⚠ ' + report.warnings.length + ' warning(s):\\n\\n' + report.warnings.map(e => '  • ' + e).join('\\n');
    el.appendChild(w);
  }
}

async function validateEdit() {
  const payload = buildPayload();
  delete payload._original_slug;  // validator doesn't expect this
  const resp = await fetch('/admin/api/blog/validate', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin', body: JSON.stringify(payload),
  });
  const report = await resp.json();
  renderReport(report);
  window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
}

async function saveEdit() {
  const payload = buildPayload();
  const originalSlug = payload._original_slug;
  delete payload._original_slug;

  // If slug changed, save under new slug then clean up the old file.
  const resp = await fetch('/admin/api/blog/draft/update', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify(Object.assign({}, payload, { _original_slug: originalSlug })),
  });
  if (!resp.ok) {
    const d = await resp.json().catch(() => ({}));
    const errs = (d.detail && d.detail.errors) || [d.detail || 'Save failed.'];
    const warns = (d.detail && d.detail.warnings) || [];
    renderReport({ errors: errs, warnings: warns });
    window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
    return;
  }
  const data = await resp.json();
  const el = document.getElementById('validationResult');
  el.innerHTML = '<div class="val-result val-ok">✓ Draft saved — redirecting…</div>';
  setTimeout(() => { window.location = '/admin/blog'; }, 700);
}
</script>
</body></html>"""


@router.get("/blog/{slug}/preview", response_class=HTMLResponse)
async def admin_blog_preview(slug: str, _user: User = Depends(get_current_admin)):
    """Render a draft (or published post) using the public /blog
    template so the admin can eyeball it before clicking Publish.
    A visible amber banner marks it as a preview so it can never be
    confused with the live page."""
    from app.services.blog_publisher import load_draft, load_published
    from app.routers.blog import _render_post

    is_draft = False
    payload = load_published(slug)
    if payload is None:
        payload = load_draft(slug)
        is_draft = True
    if payload is None:
        raise HTTPException(status_code=404, detail=f"No post '{slug}' — not in drafts or published.")

    post_html = _render_post(
        slug=payload.get("slug", slug),
        title=payload.get("title", ""),
        description=payload.get("og_description", ""),
        body_html=payload.get("body_html", ""),
        published=payload.get("published", ""),
    )
    # Inject a preview banner at the top of <body>. The _render_post
    # output is a full HTML document, so we splice the banner in just
    # after the opening <body> tag — same pattern as our other admin
    # page-header injections.
    badge_label = "DRAFT PREVIEW" if is_draft else "PUBLISHED (LIVE) — PREVIEW VIEW"
    badge_bg = "#b45309" if is_draft else "#15803d"
    banner = (
        f'<div style="position:sticky;top:0;z-index:1000;background:{badge_bg};'
        f'color:#fffaf1;font-family:\'IBM Plex Mono\',ui-monospace,monospace;'
        f'font-size:12px;letter-spacing:0.12em;text-transform:uppercase;'
        f'padding:10px 18px;text-align:center;font-weight:600;'
        f'border-bottom:2px solid rgba(0,0,0,0.3)">'
        f'{badge_label} · slug: {esc(slug)} · '
        f'<a href="/admin/blog" style="color:#fffaf1;text-decoration:underline">← Back to admin</a>'
        f'</div>'
    )
    post_html = post_html.replace("<body>", "<body>\n" + banner, 1)
    return HTMLResponse(post_html)


@router.get("/", response_class=HTMLResponse)
async def admin_dashboard_page(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin dashboard — platform-wide overview."""
    from app.curriculum.loader import list_templates
    from app.models.curriculum import DiscoveredTopic

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    total_users = await db.scalar(select(func.count()).select_from(User)) or 0
    enrolled = await db.scalar(
        select(func.count(func.distinct(UserPlan.user_id)))
        .where(UserPlan.status == "active")
    ) or 0

    # ---- Content ----
    template_count = len(list_templates())
    total_topics = await db.scalar(select(func.count()).select_from(DiscoveredTopic)) or 0
    generated_topics = await db.scalar(
        select(func.count()).select_from(DiscoveredTopic)
        .where(DiscoveredTopic.status == "generated")
    ) or 0
    pending_topics = await db.scalar(
        select(func.count()).select_from(DiscoveredTopic)
        .where(DiscoveredTopic.status == "pending")
    ) or 0
    dead_links = await db.scalar(
        select(func.count()).select_from(LinkHealth)
        .where(LinkHealth.consecutive_failures > 2)
    ) or 0

    # ---- Recent signups ----
    recent = (await db.execute(
        select(User).where(User.created_at > now - timedelta(days=7))
        .order_by(User.created_at.desc()).limit(5)
    )).scalars().all()

    signups_html = "".join(
        f'<tr><td>{esc(u.name or "-")}</td><td style="color:#8a92a0">{esc(u.email)}</td><td>{esc(u.provider)}</td><td>{fmt_ist(u.created_at, default="-")}</td></tr>'
        for u in recent
    )

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Admin</title><style>{ADMIN_CSS}</style></head><body>
{ADMIN_NAV}
<div class="page">
<h1>Dashboard</h1>
<div class="subtitle">Platform overview</div>

<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:24px">
<div class="stat"><div class="num">{total_users}</div><div class="lbl">Total Users</div></div>
<div class="stat"><div class="num">{enrolled}</div><div class="lbl">Enrolled</div></div>
<div class="stat"><div class="num">{template_count}</div><div class="lbl">Templates</div></div>
<div class="stat"><div class="num">{total_topics}</div><div class="lbl">Topics</div></div>
<div class="stat"><div class="num">{generated_topics}</div><div class="lbl">Generated</div></div>
<div class="stat"><div class="num">{pending_topics}</div><div class="lbl">Pending Review</div></div>
<div class="stat"><div class="num" style="color:{'#d97757' if dead_links > 0 else '#6db585'}">{dead_links}</div><div class="lbl">Broken Links</div></div>
</div>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-bottom:24px">

<div>
<h2>Recent Signups</h2>
{f'<table><tr><th>Name</th><th>Email</th><th>Auth</th><th>Joined</th></tr>{signups_html}</table>' if signups_html else '<p style="color:#8a92a0;font-size:13px">No signups this week</p>'}
</div>

<div>
<h2>Quick Actions</h2>
<div style="display:flex;flex-direction:column;gap:8px">
<a href="/admin/users" class="btn" style="text-align:center">Manage Users</a>
<a href="/admin/pipeline/" class="btn" style="text-align:center">Run Pipeline</a>
<a href="/admin/templates" class="btn" style="text-align:center">Manage Templates</a>
<a href="/admin/pipeline/ai-usage" class="btn" style="text-align:center">AI Usage</a>
<a href="/admin/jobs-guide" class="btn" style="text-align:center">Jobs Guide</a>
</div>
</div>

</div>

</div></body></html>"""


@router.get("/users", response_class=HTMLResponse)
async def admin_users_page(
    q: str = Query(""),
    page: int = Query(1, ge=1),
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin users list with stats, session history, device info."""
    from app.models.user import Session as SessionModel

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # ---- Anonymous stats ----
    from app.main import get_anon_stats
    anon = get_anon_stats()

    # ---- Summary stats ----
    total_users = await db.scalar(select(func.count()).select_from(User)) or 0
    users_with_plans = await db.scalar(
        select(func.count(func.distinct(UserPlan.user_id)))
        .where(UserPlan.status == "active")
    ) or 0
    active_sessions = await db.scalar(
        select(func.count()).select_from(SessionModel)
        .where(SessionModel.expires_at > now, SessionModel.revoked_at.is_(None))
    ) or 0
    google_users = await db.scalar(
        select(func.count()).select_from(User).where(User.provider == "google")
    ) or 0
    otp_users = await db.scalar(
        select(func.count()).select_from(User).where(User.provider == "otp")
    ) or 0
    today_logins = await db.scalar(
        select(func.count(func.distinct(SessionModel.user_id)))
        .where(SessionModel.issued_at > now - timedelta(days=1))
    ) or 0
    week_logins = await db.scalar(
        select(func.count(func.distinct(SessionModel.user_id)))
        .where(SessionModel.issued_at > now - timedelta(days=7))
    ) or 0
    new_this_week = await db.scalar(
        select(func.count()).select_from(User)
        .where(User.created_at > now - timedelta(days=7))
    ) or 0

    # ---- User list ----
    query = select(User)
    if q:
        query = query.where(User.email.contains(q) | User.name.contains(q))
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (await db.execute(query.order_by(User.created_at.desc()).offset((page-1)*20).limit(20))).scalars().all()

    # Get last session for each user (for IP, user_agent, last login)
    user_ids = [u.id for u in rows]
    last_sessions = {}
    if user_ids:
        for uid in user_ids:
            sess = (await db.execute(
                select(SessionModel)
                .where(SessionModel.user_id == uid)
                .order_by(SessionModel.issued_at.desc())
                .limit(1)
            )).scalar_one_or_none()
            if sess:
                last_sessions[uid] = sess

    # Get plan info per user
    user_plans = {}
    if user_ids:
        plan_rows = (await db.execute(
            select(UserPlan.user_id, UserPlan.template_key, UserPlan.status)
            .where(UserPlan.user_id.in_(user_ids), UserPlan.status == "active")
        )).all()
        for pr in plan_rows:
            user_plans[pr.user_id] = pr.template_key

    # ---- Recent profile audit log (last 50 changes) ----
    from app.models.user_audit import UserAuditLog
    audit_rows = (await db.execute(
        select(UserAuditLog, User.email)
        .join(User, User.id == UserAuditLog.user_id, isouter=True)
        .order_by(UserAuditLog.changed_at.desc())
        .limit(50)
    )).all()

    def _truncate(s: str | None, n: int = 40) -> str:
        if s is None:
            return '<span style="color:#5a6472">null</span>'
        s = s if len(s) <= n else s[:n] + "…"
        return esc(s)

    audit_html = ""
    for a, email in audit_rows:
        audit_html += (
            f"<tr>"
            f"<td style='font-size:12px;white-space:nowrap'>{fmt_ist(a.changed_at)}</td>"
            f"<td style='font-size:12px'>{esc(email or f'user#{a.user_id}')}</td>"
            f"<td style='font-size:12px'><strong>{esc(a.field)}</strong></td>"
            f"<td style='font-size:12px;color:#8a92a0'>{_truncate(a.old_value)}</td>"
            f"<td style='font-size:12px;color:#d0cbc2'>{_truncate(a.new_value)}</td>"
            f"<td style='font-size:12px;color:#8a92a0'>{esc(a.source)}</td>"
            f"</tr>"
        )

    rows_html = ""
    for u in rows:
        sess = last_sessions.get(u.id)
        last_ip = esc(sess.ip or "-") if sess else "-"
        last_login = fmt_ist(sess.issued_at, default="-") if sess else "-"

        # Parse user agent for device info
        ua_raw = sess.user_agent if sess else ""
        device = _parse_device(ua_raw)

        plan = user_plans.get(u.id, "")
        plan_badge = f'<span style="color:#6db585;font-size:12px">{esc(plan)}</span>' if plan else '<span style="color:#8a92a0;font-size:12px">No plan</span>'

        provider_icon = "G" if u.provider == "google" else "✉"
        admin_badge = ' <span style="color:#e8a849;font-size:12px">ADMIN</span>' if u.is_admin else ""

        created = fmt_ist(u.created_at, FMT_DATE, default="-")

        rows_html += f"""<tr>
<td>{u.id}</td>
<td>
  <div><strong>{esc(u.name or '-')}</strong>{admin_badge}</div>
  <div style="font-size:12px;color:#8a92a0">{esc(u.email)}</div>
</td>
<td><span title="{esc(u.provider)}">{provider_icon}</span></td>
<td>{plan_badge}</td>
<td style="font-size:12px">{last_login}</td>
<td style="font-size:12px;color:#8a92a0">{last_ip}</td>
<td style="font-size:12px;color:#8a92a0" data-ip="{esc(sess.ip or '') if sess else ''}" class="loc-cell">—</td>
<td style="font-size:12px;color:#8a92a0" title="{esc((ua_raw or '')[:100])}">{esc(device)}</td>
<td style="font-size:12px">{created}</td>
</tr>"""

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Users</title><style>{ADMIN_CSS}</style></head><body>
{ADMIN_NAV}
<div class="page">
<h1>Users</h1>
<div class="subtitle">User activity, sessions, and enrollment</div>

<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px">
<div class="stat"><div class="num">{total_users}</div><div class="lbl">Total Users</div></div>
<div class="stat"><div class="num">{today_logins}</div><div class="lbl">Logged In Today</div></div>
<div class="stat"><div class="num">{week_logins}</div><div class="lbl">This Week</div></div>
<div class="stat"><div class="num">{new_this_week}</div><div class="lbl">New This Week</div></div>
<div class="stat"><div class="num">{active_sessions}</div><div class="lbl">Active Sessions</div></div>
<div class="stat"><div class="num">{users_with_plans}</div><div class="lbl">Enrolled</div></div>
<div class="stat"><div class="num">{google_users}</div><div class="lbl">Google SSO</div></div>
<div class="stat"><div class="num">{otp_users}</div><div class="lbl">Email OTP</div></div>
</div>
<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:24px">
<div class="stat" style="border-left:3px solid #5d9be8"><div class="num">{anon['today_hits']}</div><div class="lbl">Anonymous Today</div></div>
<div class="stat" style="border-left:3px solid #5d9be8"><div class="num">{anon['today_unique']}</div><div class="lbl">Unique Visitors Today</div></div>
<div class="stat" style="border-left:3px solid #5d9be8"><div class="num">{anon['total_hits']}</div><div class="lbl">Total Anonymous</div></div>
<div class="stat" style="border-left:3px solid #5d9be8"><div class="num">{anon['unique_visitors']}</div><div class="lbl">Unique All Time</div></div>
</div>

<form style="margin-bottom:12px"><input name="q" value="{esc(q)}" placeholder="Search email or name" style="padding:8px 12px;background:#1d242e;border:1px solid #2a323d;color:#f5f1e8;border-radius:3px;width:250px"> <button class="btn" type="submit">Search</button></form>

<table>
<tr><th>ID</th><th>User</th><th>Auth</th><th>Plan</th><th>Last Login</th><th>IP</th><th>Location</th><th>Device</th><th>Joined</th></tr>
{rows_html}
</table>
<div style="margin-top:12px;font-size:12px;color:#8a92a0">
  Showing {len(rows)} of {total} users
  {'  <a href="/admin/users?page='+str(page-1)+'&q='+esc(q)+'" class="btn">Prev</a>' if page>1 else ''}
  {'  <a href="/admin/users?page='+str(page+1)+'&q='+esc(q)+'" class="btn">Next</a>' if page*20<total else ''}
</div>

<script>
// Geo-lookup for IP addresses (free ip-api.com, no key needed)
(async function() {{
  const cells = document.querySelectorAll('.loc-cell');
  const ips = new Set();
  cells.forEach(c => {{ const ip = c.dataset.ip; if (ip && ip !== '-' && !ip.startsWith('127.') && !ip.startsWith('10.')) ips.add(ip); }});
  if (ips.size === 0) return;

  // Batch lookup (ip-api supports batch POST for up to 100 IPs)
  try {{
    const ipList = [...ips].slice(0, 100);
    const resp = await fetch('http://ip-api.com/batch?fields=query,city,country,countryCode', {{
      method: 'POST',
      body: JSON.stringify(ipList.map(ip => ({{ query: ip }})))
    }});
    const results = await resp.json();
    const lookup = {{}};
    for (const r of results) {{
      if (r.city && r.countryCode) lookup[r.query] = r.city + ', ' + r.countryCode;
      else if (r.country) lookup[r.query] = r.country;
    }}
    cells.forEach(c => {{
      const ip = c.dataset.ip;
      if (lookup[ip]) c.textContent = lookup[ip];
    }});
  }} catch(e) {{
    // Geo-lookup failed silently — locations stay as "—"
  }}
}})();
</script>

<h2 style="margin-top:32px">Recent Profile Changes</h2>
<div style="font-size:13px;color:#8a92a0;margin-bottom:8px">
  Every write to a user's profile field is logged here (source: <code>profile_patch</code>, <code>google_login</code>). Use this to trace any accidental clearing or unexpected change.
</div>
{'<p style="color:#8a92a0;font-size:13px">No profile changes logged yet.</p>' if not audit_html else f'''<table>
<tr><th>When (IST)</th><th>User</th><th>Field</th><th>Old</th><th>New</th><th>Source</th></tr>
{audit_html}
</table>
<div style="margin-top:6px;font-size:12px;color:#8a92a0">Showing last 50 entries.</div>'''}
</div></body></html>"""


def _parse_device(ua: str) -> str:
    """Extract a short device description from User-Agent string."""
    if not ua:
        return "-"
    ua_lower = ua.lower()

    # OS
    if "iphone" in ua_lower:
        os_name = "iPhone"
    elif "ipad" in ua_lower:
        os_name = "iPad"
    elif "android" in ua_lower:
        os_name = "Android"
    elif "macintosh" in ua_lower or "mac os" in ua_lower:
        os_name = "Mac"
    elif "windows" in ua_lower:
        os_name = "Windows"
    elif "linux" in ua_lower:
        os_name = "Linux"
    elif "cli-test" in ua_lower:
        return "CLI"
    else:
        os_name = "Other"

    # Browser
    if "edg/" in ua_lower:
        browser = "Edge"
    elif "chrome" in ua_lower and "safari" in ua_lower:
        browser = "Chrome"
    elif "firefox" in ua_lower:
        browser = "Firefox"
    elif "safari" in ua_lower:
        browser = "Safari"
    else:
        browser = ""

    return f"{os_name} · {browser}" if browser else os_name


@router.get("/proposals", response_class=HTMLResponse)
async def admin_proposals_page(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin proposals list HTML page."""
    rows = (await db.execute(
        select(CurriculumProposal).order_by(CurriculumProposal.created_at.desc())
    )).scalars().all()

    rows_html = ""
    for p in rows:
        actions = ""
        if p.status == "pending":
            actions = f'<form method="post" action="/admin/api/proposals/{p.id}/apply" style="display:inline"><button class="btn success">Apply</button></form> <form method="post" action="/admin/api/proposals/{p.id}/reject" style="display:inline"><button class="btn danger">Reject</button></form>'
        rows_html += f"<tr><td>{p.id}</td><td>{esc(p.source_run)}</td><td>{esc(p.status)}</td><td>{esc(p.notes or '-')}</td><td>{p.created_at}</td><td>{actions}</td></tr>"

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Proposals</title><style>{ADMIN_CSS}</style></head><body>
{ADMIN_NAV}
<div class="page">
<h1>Curriculum Proposals</h1>
<table><tr><th>ID</th><th>Source Run</th><th>Status</th><th>Notes</th><th>Created</th><th>Actions</th></tr>{rows_html}</table>
</div></body></html>"""


@router.get("/templates", response_class=HTMLResponse)
async def admin_templates_page(
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin templates management page."""
    from app.curriculum.loader import list_templates, load_template, get_template_status, get_review_stamp
    from app.models.plan import UserPlan

    # Get subscriber counts per template (active enrollments only)
    sub_rows = await db.execute(
        select(UserPlan.template_key, func.count(UserPlan.id))
        .where(UserPlan.status == "active")
        .group_by(UserPlan.template_key)
    )
    subscriber_counts = {row[0]: row[1] for row in sub_rows}

    grandfathered = {"generalist_3mo_intermediate", "generalist_6mo_intermediate", "generalist_12mo_beginner"}
    keys = list_templates()
    rows_html = ""
    for key in sorted(keys):
        try:
            tpl = load_template(key)
            is_default = key in grandfathered

            status_info = get_template_status(key)
            pub_status = status_info.get("status", "draft")
            q_score = status_info.get("quality_score", 0)
            if is_default and pub_status == "draft":
                pub_status = "published"

            if pub_status == "published":
                status_badge = '<span style="background:#1d3525;color:#6db585;padding:2px 8px;border-radius:10px;font-size:11px">Published</span>'
            else:
                status_badge = '<span style="background:#2a2520;color:#e8a849;padding:2px 8px;border-radius:10px;font-size:11px">Draft</span>'

            stamp = get_review_stamp(key)
            if stamp.get("last_reviewed_on") and stamp.get("last_reviewed_by"):
                status_badge += (
                    f'<div style="font-size:10px;color:#8a92a0;margin-top:3px;white-space:nowrap">'
                    f'reviewed {esc(stamp["last_reviewed_on"])}<br>by {esc(stamp["last_reviewed_by"])}'
                    f'</div>'
                )
            elif is_default:
                status_badge += '<div style="font-size:10px;color:#8a92a0;margin-top:3px">grandfathered</div>'

            score_color = "#6db585" if q_score >= 90 else "#e8a849" if q_score >= 70 else "#d97757" if q_score > 0 else "#8a92a0"
            if q_score == 0:
                score_display = '<span style="color:#8a92a0" title="Not yet scored — click Check quality">—</span>'
            elif q_score >= 90:
                score_display = f'<span style="color:{score_color};font-weight:600" title="At or above publish threshold (90)">{q_score} ✓ ready</span>'
            elif pub_status == "published":
                score_display = f'<span style="color:{score_color};font-weight:600">{q_score}</span>'
            else:
                score_display = f'<span style="color:{score_color};font-weight:600" title="Below publish threshold (90). Run Pipeline → Refine Quality.">{q_score} · needs refine</span>'

            subs = subscriber_counts.get(key, 0)
            subs_display = f'<span style="font-weight:600">{subs}</span>' if subs > 0 else '<span style="color:#8a92a0">0</span>'

            # Action buttons by state
            actions = []
            if pub_status == "published" and not is_default:
                actions.append(f'<button class="btn" onclick="unpublishTemplate(&quot;{key}&quot;)" title="Hide from users, return to draft">Unpublish</button>')
            elif pub_status == "draft":
                if q_score >= 90:
                    actions.append(f'<button class="btn success" onclick="publishTemplate(&quot;{key}&quot;)" title="Make this template available to users">Publish</button>')
                elif q_score == 0:
                    actions.append(f'<button class="btn primary" onclick="checkQuality(&quot;{key}&quot;)" title="Score this draft against the 15-dim rubric. Does NOT publish — admin must click Publish manually.">Check quality</button>')
                else:
                    actions.append(f'<button class="btn" onclick="refineOne(&quot;{key}&quot;)" title="Score {q_score} below 90. Run quality pipeline on this template only.">Refine</button>')
            if not is_default:
                actions.append(f'<button class="btn danger" onclick="deleteTemplate(&quot;{key}&quot;)">Delete</button>')
            actions_html = " ".join(actions)

            cert_n = tpl.certification_count
            gh_n = tpl.repos_required
            cert_cell = f'<span style="color:#6db585;font-weight:600" title="{cert_n} resource(s)/deliverable(s) reference a certification">{cert_n}</span>' if cert_n else '<span style="color:#5a6472">0</span>'
            gh_cell = f'<span style="color:#6db585;font-weight:600" title="{gh_n} GitHub-linkable deliverable(s) the learner must produce (repos, notebooks, demos, services). User progress: linked / required.">{gh_n}</span>' if gh_n else '<span style="color:#5a6472">0</span>'

            rows_html += f"<tr><td><a href='/admin/templates/{key}' style='color:#e8a849'>{esc(tpl.title)}</a></td><td>{esc(tpl.level)}</td><td>{tpl.duration_months}mo</td><td>{tpl.total_weeks}</td><td>{tpl.total_hours}</td><td>{tpl.total_focus_areas}</td><td>{tpl.total_checks}</td><td style='text-align:center'>{cert_cell}</td><td style='text-align:center'>{gh_cell}</td><td style='text-align:center'>{subs_display}</td><td style='text-align:center'>{status_badge}</td><td style='text-align:center'>{score_display}</td><td style='white-space:nowrap'>{actions_html}</td></tr>"
        except Exception:
            continue

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Templates</title><style>{ADMIN_CSS}</style></head><body>
{ADMIN_NAV}
<div class="page">
<h1>Plan Templates</h1>
{workflow_steps(3)}
<div style="background:#1d242e;border-left:3px solid #e8a849;padding:12px 16px;border-radius:4px;margin-bottom:16px;font-size:13px;line-height:1.6">
  <div style="color:#e8a849;font-weight:600;margin-bottom:6px">Your workflow — what to do on this page</div>
  <ol style="margin:0 0 8px 18px;padding:0;color:#d0cbc2">
    <li><strong>Generate</strong> a new template using the form below (or let the Pipeline auto-generate from approved Topics).</li>
    <li><strong>Check quality</strong> on new drafts — click <em>Check quality</em> in the Actions column. AI scores 0–100 across 15 dimensions.</li>
    <li><strong>If score ≥ 90</strong> → click <em>Publish</em>. Users can now enroll.</li>
    <li><strong>If score &lt; 90</strong> → click <em>Refine →</em> to jump to Pipeline → Refine Quality, then re-check.</li>
    <li><strong>Unpublish</strong> if a template becomes stale, or <strong>Delete</strong> to remove entirely.</li>
  </ol>
  <div style="color:#8a92a0;font-size:12px">Score legend: <span style="color:#6db585">≥90 ready</span> · <span style="color:#e8a849">70–89 needs refine</span> · <span style="color:#d97757">&lt;70 weak, regenerate</span> · <span style="color:#8a92a0">— not yet scored</span></div>
  <div style="color:#8a92a0;font-size:12px;margin-top:4px"><strong style="color:#d0cbc2">Terminology:</strong> <strong>Topic</strong> = course subject (<a href="/admin/pipeline/topics" style="color:#e8a849">Topics</a> tab). <strong>Template</strong> = a specific course variant (level × duration). <strong>Focus areas</strong> = subtopics covered inside a week.</div>
</div>

<div style="background:#1d242e;padding:16px;border-radius:6px;margin-bottom:24px">
  <h2 style="font-size:16px;margin-bottom:12px">Generate New Template</h2>
  <div style="display:grid;grid-template-columns:2fr 1fr 1fr auto;gap:8px;align-items:end">
    <div><label style="font-size:12px;text-transform:uppercase;letter-spacing:0.1em;color:#8a92a0;display:block;margin-bottom:4px">Topic</label><input id="genTopic" placeholder="e.g. NLP, Computer Vision, MLOps" style="width:100%;padding:8px;background:#0f1419;border:1px solid #2a323d;color:#f5f1e8;border-radius:3px"></div>
    <div><label style="font-size:12px;text-transform:uppercase;letter-spacing:0.1em;color:#8a92a0;display:block;margin-bottom:4px">Duration</label><select id="genDuration" style="width:100%;padding:8px;background:#0f1419;border:1px solid #2a323d;color:#f5f1e8;border-radius:3px"><option value="3">3 months</option><option value="6" selected>6 months</option><option value="9">9 months</option><option value="12">12 months</option></select></div>
    <div><label style="font-size:12px;text-transform:uppercase;letter-spacing:0.1em;color:#8a92a0;display:block;margin-bottom:4px">Level</label><select id="genLevel" style="width:100%;padding:8px;background:#0f1419;border:1px solid #2a323d;color:#f5f1e8;border-radius:3px"><option value="beginner">Beginner</option><option value="intermediate" selected>Intermediate</option><option value="advanced">Advanced</option></select></div>
    <button class="btn success" onclick="generateTemplate()" id="genBtn" style="padding:8px 16px">Generate</button>
  </div>
  <div id="genStatus" style="margin-top:8px;font-size:12px;color:#8a92a0"></div>
</div>

<div style="overflow-x:auto;border:1px solid #2a323d;border-radius:4px">
<table style="min-width:1100px;margin:0"><tr><th>Title</th><th>Level</th><th>Duration</th><th>Weeks</th><th>Hours</th><th title="Sum of per-week focus areas across all weeks in this template (not to be confused with Topic, which is the course subject on the Topics tab)">Focus areas</th><th>Checks</th><th title="Count of resources/deliverables/checks that reference a certification">Certs</th><th title="Deliverables the learner must produce as a GitHub-trackable artifact (repo, notebook, demo, service). User progress on /account shows as linked/required (e.g. 4/15).">Repos Required</th><th title="Active subscribers / enrollments">Subs</th><th>Status</th><th>Quality</th><th>Actions</th></tr>{rows_html}</table>
</div>

<script>
async function generateTemplate() {{
  const btn = document.getElementById('genBtn');
  const status = document.getElementById('genStatus');
  const topic = document.getElementById('genTopic').value.trim();
  if (!topic) {{ status.textContent = 'Enter a topic'; return; }}
  btn.disabled = true;
  btn.textContent = 'Generating...';
  status.textContent = 'AI is generating curriculum... this takes 15-30 seconds.';
  try {{
    const resp = await fetch('/admin/api/generate-template', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      credentials: 'same-origin',
      body: JSON.stringify({{
        topic: topic,
        duration: document.getElementById('genDuration').value,
        level: document.getElementById('genLevel').value,
      }})
    }});
    const data = await resp.json();
    if (resp.ok) {{
      status.innerHTML = '<span style="color:#6db585">✓ Generated: ' + data.title + ' (' + data.weeks + ' weeks). Refreshing...</span>';
      setTimeout(() => window.location.reload(), 1500);
    }} else {{
      status.innerHTML = '<span style="color:#d97757">✗ ' + (data.detail || 'Failed') + '</span>';
    }}
  }} catch(e) {{
    status.innerHTML = '<span style="color:#d97757">✗ Error: ' + e.message + '</span>';
  }}
  btn.disabled = false;
  btn.textContent = 'Generate';
}}

async function deleteTemplate(key) {{
  if (!confirm('Delete template: ' + key + '?')) return;
  const resp = await fetch('/admin/api/templates/' + key, {{method: 'DELETE', credentials: 'same-origin'}});
  if (resp.ok) window.location.reload();
  else alert('Delete failed');
}}

async function publishTemplate(key) {{
  const resp = await fetch('/admin/pipeline/api/quality/' + key + '/publish', {{method: 'POST', credentials: 'same-origin'}});
  const data = await resp.json().catch(() => ({{}}));
  if (resp.ok) window.location.reload();
  else alert('Publish failed: ' + (data.detail || resp.statusText));
}}

async function unpublishTemplate(key) {{
  if (!confirm('Unpublish ' + key + '? Users currently enrolled will keep their plan, but no new enrollments will be possible.')) return;
  const resp = await fetch('/admin/pipeline/api/quality/' + key + '/unpublish', {{method: 'POST', credentials: 'same-origin'}});
  if (resp.ok) window.location.reload();
  else alert('Unpublish failed');
}}

async function refineOne(key) {{
  const btn = event.target;
  const orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Refining…';
  try {{
    const resp = await fetch('/admin/pipeline/api/refine-one/' + encodeURIComponent(key), {{
      method: 'POST', credentials: 'same-origin',
    }});
    const data = await resp.json().catch(() => ({{}}));
    if (resp.ok) {{
      const before = data.score_before, after = data.score_after;
      const msg = data.improved
        ? `Score: ${{before}} → ${{after}} ✓ improved`
        : `Score: ${{before}} → ${{after}} (no improvement saved)`;
      const stages = 'Stages: ' + (data.stages_run||[]).join(', ');
      const models = Object.keys(data.models_used||{{}}).length
        ? 'Models: ' + Object.entries(data.models_used).map(([k,v])=>k+'='+v).join(', ')
        : '';
      const skipped = (data.skipped && data.skipped.length)
        ? 'Skipped:\\n  • ' + data.skipped.join('\\n  • ')
        : '';
      alert([msg, stages, models, skipped].filter(Boolean).join('\\n'));
      window.location.reload();
    }} else {{
      alert('Refine failed: ' + (data.detail || resp.statusText));
      btn.disabled = false; btn.textContent = orig;
    }}
  }} catch(e) {{
    alert('Network error: ' + e.message);
    btn.disabled = false; btn.textContent = orig;
  }}
}}

async function checkQuality(key) {{
  const btn = event.target;
  const orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Scoring…';
  const resp = await fetch('/admin/pipeline/api/quality/' + key + '/publish', {{method: 'POST', credentials: 'same-origin'}});
  const data = await resp.json().catch(() => ({{}}));
  if (resp.ok) {{
    alert('Score: ' + data.score + ' — Published ✓');
    window.location.reload();
  }} else {{
    alert((data.detail || 'Scoring failed') + ' Refine via Pipeline, then re-check.');
    btn.disabled = false;
    btn.textContent = orig;
    window.location.reload();
  }}
}}
</script>
</div></body></html>"""


# ---- Jobs Admin Guide (Jinja2 template — RCA-027 prevention) ------------------
#
# Migrated from a 313-line f-string to a Jinja2 template after RCA-027 (an
# admin-doc edit added literal {json} to a code block, Python tried to
# interpret it as f-string interpolation, container crashed for ~5min).
# Jinja2 inverts the brace semantics: { is literal by default, {{ var }}
# is interpolation. Adding HTML/JSON/code samples can no longer crash the
# import. See docs/JOBS_CLASSIFICATION.md "Jinja2 migration" section.

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pathlib import Path as _Path

_ADMIN_TEMPLATE_DIR = _Path(__file__).parent.parent / "templates"
_admin_template_env = Environment(
    loader=FileSystemLoader(str(_ADMIN_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


@router.get("/jobs-guide", response_class=HTMLResponse)
async def admin_jobs_guide(_user: User = Depends(get_current_admin)):
    """Admin guide — how to publish, review, and expire jobs."""
    html = _admin_template_env.get_template("admin/jobs_guide.html").render(
        admin_css=ADMIN_CSS,
        admin_nav=ADMIN_NAV,
    )
    return HTMLResponse(html)


# ---- Tweet drafts (Phase B daily X auto-post queue) --------------------------
#
# Daily 8am IST cron queues a draft per slot rotation (Mon/Wed/Fri blog teaser,
# Tue/Thu quotable line). Admin reviews on /admin/social, optionally edits the
# text, and clicks Post — that calls twitter_client and updates the row.
#
# When TWITTER_* env vars aren't set, "Post" returns a 503 with "not configured"
# so the admin can verify the queue + UI flow before connecting credentials.

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.models.tweet_draft import TweetDraft
from app.services import twitter_client as _twitter
from app.services.tweet_curator import (
    PROSE_BUDGET as _TWEET_PROSE_BUDGET,
    TWITTER_HARD_LIMIT as _TWEET_HARD_LIMIT,
    queue_today as _queue_today,
)

# Per-IP rate limit on the X post endpoint. X free tier is 50 posts/24h
# total — a hijacked admin session shouldn't be able to burn that in
# seconds. 5/hour = 120/day per IP, plenty for legitimate manual review,
# tight enough to limit damage. Layered on top of existing admin auth.
_tweet_limiter = Limiter(key_func=get_remote_address)


@router.get("/api/tweets")
async def list_tweets(
    limit: int = Query(40, ge=1, le=200),
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """30-ish most recent drafts, newest first. Single JSON payload — the
    /admin/social page renders rows from this."""
    stmt = (
        select(TweetDraft)
        .order_by(TweetDraft.created_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "configured": _twitter.is_configured(),
        "drafts": [
            {
                "id": r.id,
                "scheduled_date": r.scheduled_date,
                "slot_type": r.slot_type,
                "source_kind": r.source_kind,
                "source_ref": r.source_ref,
                "draft_text": r.draft_text,
                "status": r.status,
                "posted_tweet_id": r.posted_tweet_id,
                "posted_url": (
                    _twitter.tweet_url(r.posted_tweet_id) if r.posted_tweet_id else None
                ),
                "posted_at": iso_utc_z(r.posted_at) if r.posted_at else None,
                "error_message": r.error_message,
                "created_at": iso_utc_z(r.created_at),
            }
            for r in rows
        ],
    }


@router.patch("/api/tweets/{draft_id}")
async def edit_tweet(
    draft_id: int,
    payload: dict,
    request: Request,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Edit draft_text before posting. Only valid while status='pending'."""
    _check_origin(request)
    draft = await db.get(TweetDraft, draft_id)
    if not draft:
        raise HTTPException(404, "draft not found")
    if draft.status != "pending":
        raise HTTPException(409, f"cannot edit draft in status={draft.status}")
    text = (payload.get("draft_text") or "").strip()
    if not text:
        raise HTTPException(400, "draft_text required")
    if len(text) > _TWEET_HARD_LIMIT:
        raise HTTPException(
            400, f"draft_text is {len(text)} chars, X limit is {_TWEET_HARD_LIMIT}"
        )
    draft.draft_text = text
    await db.commit()
    return {"ok": True, "id": draft.id, "draft_text": draft.draft_text}


@router.post("/api/tweets/{draft_id}/skip")
async def skip_tweet(
    draft_id: int,
    request: Request,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Mark a draft as skipped — no posting, but the row stays for audit."""
    _check_origin(request)
    draft = await db.get(TweetDraft, draft_id)
    if not draft:
        raise HTTPException(404, "draft not found")
    if draft.status != "pending":
        raise HTTPException(409, f"cannot skip draft in status={draft.status}")
    draft.status = "skipped"
    await db.commit()
    return {"ok": True, "id": draft.id, "status": draft.status}


@router.post("/api/tweets/{draft_id}/post")
@_tweet_limiter.limit("5/hour")
async def post_tweet_now(
    draft_id: int,
    request: Request,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Post the draft to X via the OAuth 1.0a client.

    Concurrency: the X API call is non-idempotent — two concurrent admin
    requests racing on the same draft would post twice. We guard with an
    atomic UPDATE that flips status pending|failed → 'posting'; the loser
    sees 0 rows updated and gets 409.

    Failure semantics:
      - 4xx/5xx from X (TwitterAPIError with status set) → known failure,
        flip status to 'failed' so admin can edit + retry.
      - Network error before the X server saw the request (or with no
        status info) → status STAYS 'posting'. We don't know whether the
        post actually landed, so an automatic retry could double-post.
        Admin investigates the X timeline and either re-flags pending
        (via /skip then /queue-now or a manual DB tweak) or accepts the
        ambiguity. Fail-safe over fail-fast.

    503 when env credentials are not set so the admin sees a clear
    'not configured' state instead of a cryptic API error."""
    _check_origin(request)

    creds = _twitter.credentials_from_env()
    if creds is None:
        raise HTTPException(
            503,
            "X API not configured — set TWITTER_API_KEY / TWITTER_API_SECRET / "
            "TWITTER_ACCESS_TOKEN / TWITTER_ACCESS_TOKEN_SECRET in .env",
        )

    # Atomic claim — only one request wins the pending|failed → posting
    # transition. Subsequent concurrent requests see the row already in
    # 'posting' and can't claim it.
    from sqlalchemy import update
    claim_stmt = (
        update(TweetDraft)
        .where(
            TweetDraft.id == draft_id,
            TweetDraft.status.in_(("pending", "failed")),
        )
        .values(status="posting", error_message=None)
    )
    result = await db.execute(claim_stmt)
    await db.commit()
    if result.rowcount == 0:
        # Either the draft doesn't exist, or another request already claimed it.
        existing = await db.get(TweetDraft, draft_id)
        if existing is None:
            raise HTTPException(404, "draft not found")
        raise HTTPException(409, f"cannot post draft in status={existing.status}")

    draft = await db.get(TweetDraft, draft_id)
    # Refresh to see the post-claim state (status='posting').

    try:
        media_ids = [draft.media_id] if draft.media_id else None
        data = await _twitter.post_tweet(
            creds, draft.draft_text, media_ids=media_ids,
        )
    except _twitter.TwitterAPIError as e:
        if e.status is not None:
            # Server returned a definitive non-2xx — tweet did NOT post.
            # Safe to mark failed and let admin retry.
            body = (e.body_excerpt or "")[:400]
            draft.status = "failed"
            draft.error_message = f"{e}{(' — ' + body) if body else ''}"
            await db.commit()
            return {"ok": False, "id": draft.id, "error": str(e), "body": body}
        # No status → network/transport ambiguity. The tweet MAY have landed.
        # Don't auto-retry; surface the ambiguity to the admin.
        draft.error_message = (
            f"{e} — tweet status unknown. Check the X timeline before retrying."
        )
        await db.commit()  # status stays 'posting'
        raise HTTPException(
            502,
            f"X API transport error — draft is now in 'posting' state with "
            f"unknown post outcome. Check the X account before any retry. "
            f"Underlying: {e}",
        )
    except ValueError as e:
        # Pre-flight validation failure (empty text, > 280). The X API was
        # never called. Roll back the claim so admin can fix and retry.
        draft.status = "pending"
        draft.error_message = f"validation: {e}"
        await db.commit()
        raise HTTPException(400, str(e))

    draft.status = "posted"
    draft.posted_tweet_id = data["id"]
    draft.posted_at = datetime.now(timezone.utc)
    draft.error_message = None
    await db.commit()
    return {
        "ok": True,
        "id": draft.id,
        "posted_tweet_id": draft.posted_tweet_id,
        "posted_url": _twitter.tweet_url(draft.posted_tweet_id),
    }


# ---- Programmatic notification endpoint (for scheduled remote agents) -------
#
# Token-gated SMTP-send endpoint. Designed for the claude.ai routine
# infrastructure (or any other automated client) that can't use the Gmail
# MCP connector — Google's OAuth blocked re-auth on this account, and the
# MCP-token-expiry semantics are unreliable across days.
#
# Recipient is HARDCODED to settings.maintainer_email. A leaked token can
# only spam the maintainer (irritating but not abusive); it can't be used
# to email arbitrary recipients via our SMTP transport.

import os as _os


@router.post("/api/notify")
@_tweet_limiter.limit("10/hour")
async def admin_notify(
    request: Request,
    payload: dict,
):
    """Send a plain-text email to the maintainer via SMTP. Auth is a
    Bearer token in Authorization header, checked against env var
    NOTIFY_API_TOKEN. No cookie/session — programmatic clients only.

    503 when NOTIFY_API_TOKEN isn't set (endpoint disabled).
    401 when the token is missing or wrong.
    400 when subject/body missing.
    502 on SMTP failure (e.g. Brevo down).
    """
    expected = _os.environ.get("NOTIFY_API_TOKEN", "").strip()
    if not expected:
        raise HTTPException(503, "notification endpoint disabled — set NOTIFY_API_TOKEN")
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer ") or auth[7:].strip() != expected:
        raise HTTPException(401, "invalid token")

    if not isinstance(payload, dict):
        raise HTTPException(400, "JSON body required")
    subject = (payload.get("subject") or "").strip()
    body = (payload.get("body") or "").strip()
    if not subject:
        raise HTTPException(400, "subject required")
    if not body:
        raise HTTPException(400, "body required")
    # Don't echo arbitrary HTML — keep this plain text only. The recipient
    # is fixed (maintainer_email); we don't accept a `to` field on purpose
    # so a leaked token can only spam one inbox.
    if len(subject) > 300:
        raise HTTPException(400, "subject too long (max 300)")
    if len(body) > 20000:
        raise HTTPException(400, "body too long (max 20000)")

    from app.services.email_sender import send_admin_notification
    try:
        await send_admin_notification(subject=subject, body=body)
    except Exception as e:
        # Don't echo SMTP error verbatim — could leak SMTP creds in
        # rare auth-failure error strings.
        raise HTTPException(502, f"email send failed: {type(e).__name__}")
    return {"ok": True}


@router.post("/api/tweets/queue-now")
async def queue_now(
    request: Request,
    _user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger today's curator (instead of waiting for 8am IST).
    Useful for testing the rotation + previewing the day's draft."""
    _check_origin(request)
    from app.config import get_settings
    base = get_settings().public_base_url.rstrip("/")
    draft = await _queue_today(db, base)
    if draft is None:
        return {"ok": True, "queued": False, "reason": "no eligible source for today"}
    await db.commit()
    return {
        "ok": True, "queued": True,
        "id": draft.id, "slot_type": draft.slot_type,
        "draft_text": draft.draft_text,
    }


_TWEETS_ADMIN_HTML = """<!doctype html><html><head>
<meta charset="utf-8"><title>Social drafts · Admin</title>
<style>{{ADMIN_CSS}}</style></head><body>
{{ADMIN_NAV}}
<div class="page">
  <h1>Social drafts</h1>
  <div class="subtitle">Daily X queue · curator picks at 8am IST · click Post to ship</div>

  <div id="cfgBanner" style="display:none;margin:16px 0;padding:12px 16px;
       background:rgba(217,119,87,0.1);border:1px solid rgba(217,119,87,0.4);
       border-radius:6px;color:#d97757;font-size:13px;">
    ⚠ X API not configured. Drafts will queue but Post will return 503 until
    you set <code>TWITTER_API_KEY / TWITTER_API_SECRET / TWITTER_ACCESS_TOKEN /
    TWITTER_ACCESS_TOKEN_SECRET</code> in <code>.env</code>.
  </div>

  <div style="margin:16px 0">
    <button class="btn" id="queueBtn">Queue today's draft now</button>
    <button class="btn" id="refreshBtn">Refresh</button>
  </div>

  <table id="tweetsTable">
    <thead><tr>
      <th>Date</th><th>Slot</th><th>Source</th><th style="width:36%">Draft</th>
      <th>Status</th><th style="width:20%">Actions</th>
    </tr></thead>
    <tbody id="tweetsTbody"></tbody>
  </table>

</div>
<script>
const HARD_LIMIT = {{TWEET_HARD_LIMIT}};

function escapeHtml(s) {
  return (s || '').replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  })[c]);
}

function statusPill(status) {
  const colors = {
    pending: ['#e8a849', 'rgba(232,168,73,0.15)'],
    posting: ['#67a5d1', 'rgba(103,165,209,0.15)'],
    posted:  ['#6db585', 'rgba(109,181,133,0.15)'],
    skipped: ['#94a3b8', 'rgba(148,163,184,0.15)'],
    failed:  ['#d97757', 'rgba(217,119,87,0.15)'],
  };
  const [fg, bg] = colors[status] || ['#94a3b8', 'rgba(148,163,184,0.15)'];
  return `<span style="font-family:'IBM Plex Mono',monospace;font-size:10px;
    letter-spacing:0.1em;text-transform:uppercase;padding:3px 10px;border-radius:10px;
    color:${fg};background:${bg};border:1px solid ${fg}40">${status}</span>`;
}

function row(d) {
  const sourceLink = d.source_kind === 'blog'
    ? `<a href="/blog/${escapeHtml(d.source_ref)}" target="_blank">${escapeHtml(d.source_ref)}</a>`
    : escapeHtml(d.source_ref);
  let actions = '';
  if (d.status === 'pending' || d.status === 'failed') {
    actions = `<button class="btn" data-act="edit" data-id="${d.id}">Edit</button>
               <button class="btn success" data-act="post" data-id="${d.id}">Post</button>
               <button class="btn danger" data-act="skip" data-id="${d.id}">Skip</button>`;
  } else if (d.status === 'posted' && d.posted_url) {
    actions = `<a class="btn" href="${escapeHtml(d.posted_url)}" target="_blank">View on X ↗</a>`;
  }
  const errLine = d.error_message
    ? `<div style="color:#d97757;font-size:11px;margin-top:6px;font-family:'IBM Plex Mono',monospace">${escapeHtml(d.error_message)}</div>`
    : '';
  return `<tr data-id="${d.id}">
    <td>${escapeHtml(d.scheduled_date)}</td>
    <td><code style="font-size:11px;color:#94a3b8">${escapeHtml(d.slot_type)}</code></td>
    <td>${sourceLink}</td>
    <td>
      <textarea data-edit-for="${d.id}" rows="3" maxlength="${HARD_LIMIT}"
        style="width:100%;background:#0f1419;color:#e8e4d8;border:1px solid #2a323d;
        border-radius:4px;padding:6px 8px;font:inherit;font-size:12px;line-height:1.5;
        ${d.status === 'pending' || d.status === 'failed' ? '' : 'pointer-events:none;opacity:0.7'}"
      >${escapeHtml(d.draft_text)}</textarea>
      <div style="font-size:10px;color:#6a7280;margin-top:2px;font-family:'IBM Plex Mono',monospace"
           data-count-for="${d.id}">${d.draft_text.length} / ${HARD_LIMIT}</div>
      ${errLine}
    </td>
    <td>${statusPill(d.status)}</td>
    <td>${actions}</td>
  </tr>`;
}

async function load() {
  const r = await fetch('/admin/api/tweets', { credentials: 'include' });
  if (!r.ok) { document.getElementById('tweetsTbody').innerHTML =
    '<tr><td colspan="6" style="color:#d97757">Failed to load</td></tr>'; return; }
  const j = await r.json();
  document.getElementById('cfgBanner').style.display = j.configured ? 'none' : 'block';
  const tb = document.getElementById('tweetsTbody');
  tb.innerHTML = j.drafts.length
    ? j.drafts.map(row).join('')
    : '<tr><td colspan="6" style="color:#6a7280;text-align:center;padding:32px">No drafts yet — try "Queue today\\'s draft now".</td></tr>';
  // Char counters on each editable textarea
  document.querySelectorAll('textarea[data-edit-for]').forEach(ta => {
    ta.addEventListener('input', () => {
      const counter = document.querySelector(`[data-count-for="${ta.dataset.editFor}"]`);
      if (counter) {
        counter.textContent = `${ta.value.length} / ${HARD_LIMIT}`;
        counter.style.color = ta.value.length > HARD_LIMIT ? '#d97757' : '#6a7280';
      }
    });
  });
}

async function jsonReq(url, opts={}) {
  const r = await fetch(url, {
    method: opts.method || 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) {
    alert(`${url} → ${r.status}\\n${j.detail || j.error || JSON.stringify(j)}`);
    return null;
  }
  return j;
}

document.addEventListener('click', async (e) => {
  const btn = e.target.closest('button.btn[data-act]');
  if (!btn) return;
  const id = btn.dataset.id;
  const act = btn.dataset.act;
  if (act === 'edit') {
    const ta = document.querySelector(`textarea[data-edit-for="${id}"]`);
    if (!ta) return;
    btn.disabled = true; btn.textContent = 'Saving…';
    const ok = await jsonReq(`/admin/api/tweets/${id}`,
      { method: 'PATCH', body: { draft_text: ta.value } });
    btn.disabled = false; btn.textContent = 'Edit';
    if (ok) btn.style.borderColor = '#6db585';
  } else if (act === 'post') {
    if (!confirm('Post this tweet to X right now?')) return;
    btn.disabled = true; btn.textContent = 'Posting…';
    await jsonReq(`/admin/api/tweets/${id}/post`);
    await load();
  } else if (act === 'skip') {
    if (!confirm('Skip this draft? It stays on file but is not posted.')) return;
    btn.disabled = true;
    await jsonReq(`/admin/api/tweets/${id}/skip`);
    await load();
  }
});

document.getElementById('queueBtn').addEventListener('click', async (e) => {
  e.target.disabled = true; e.target.textContent = 'Queueing…';
  await jsonReq('/admin/api/tweets/queue-now');
  e.target.disabled = false; e.target.textContent = "Queue today's draft now";
  await load();
});
document.getElementById('refreshBtn').addEventListener('click', load);

load();
</script></body></html>"""


@router.get("/social", response_class=HTMLResponse)
async def admin_social_page(_user: User = Depends(get_current_admin)):
    """Admin UI for the daily social-post queue. Reads /admin/api/tweets and
    posts via /admin/api/tweets/{id}/post (API paths stay tweet-named until
    additional channels land)."""
    html = (_TWEETS_ADMIN_HTML
            .replace("{{ADMIN_CSS}}", ADMIN_CSS)
            .replace("{{ADMIN_NAV}}", ADMIN_NAV)
            .replace("{{TWEET_HARD_LIMIT}}", str(_TWEET_HARD_LIMIT)))
    return HTMLResponse(html)


