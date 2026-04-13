"""Public certificate verification page — /verify/{credential_id}.

No auth required. Pages are rate-limited per IP to prevent scraping.
The verified badge runs the server-side HMAC check on every render;
if the signature doesn't match or is revoked, the page still loads
but shows a red badge (tamper-evident, not a hard error).
"""

from __future__ import annotations

import html as _html
import logging
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models.certificate import Certificate
from app.services.certificates import verify_signature

router = APIRouter()
logger = logging.getLogger("roadmap.verify")

# Per-IP counter dedupes refresh-spam. value = (bucket_start_ts, count).
_view_budget: dict[str, tuple[float, int]] = defaultdict(lambda: (0.0, 0))
_RATE_WINDOW = 3600  # 1 hour
_RATE_LIMIT = 60      # 60 views per IP per hour

# Per-(IP, credential_id) cache — only the FIRST view in a 1h window
# increments verification_views. Prevents a single recruiter reload from
# inflating counts.
_view_dedup: dict[tuple[str, str], float] = {}
_DEDUP_WINDOW = 3600


def _client_ip(request: Request) -> str:
    return (
        request.headers.get("x-real-ip")
        or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )


def _rate_check(ip: str) -> bool:
    now = time.time()
    start, count = _view_budget[ip]
    if now - start > _RATE_WINDOW:
        _view_budget[ip] = (now, 1)
        return True
    if count >= _RATE_LIMIT:
        return False
    _view_budget[ip] = (start, count + 1)
    return True


def _should_increment(ip: str, credential_id: str) -> bool:
    now = time.time()
    key = (ip, credential_id)
    last = _view_dedup.get(key, 0.0)
    if now - last < _DEDUP_WINDOW:
        return False
    _view_dedup[key] = now
    return True


_TIER_LABEL = {
    "completion":  "Certificate of Completion",
    "distinction": "Certificate of Completion with Distinction",
    "honors":      "Certificate of Completion with Honors",
}


_INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Verify a Credential — AutomateEdge</title>
<meta name="description" content="Look up an AutomateEdge course completion certificate by credential ID.">
<style>
  :root{--amber:#b45309;--ink:#1f1610}
  *{box-sizing:border-box}
  html,body{margin:0;padding:0;background:#fffaf1;color:var(--ink);font-family:Georgia,serif;min-height:100vh}
  .nav{background:#0a0e13;border-bottom:1px solid #1f2937;padding:14px 28px;display:flex;align-items:center;justify-content:space-between}
  .brand{display:flex;align-items:center;gap:10px;font-weight:700;color:#e8a849;font-size:16px;text-decoration:none}
  .brand-dot{width:10px;height:10px;border-radius:50%;background:#e8a849}
  .home-link{color:#a8a29e;text-decoration:none;font-size:13px}
  .home-link:hover{color:#e8a849}
  .wrap{max-width:640px;margin:0 auto;padding:64px 24px}
  .eyebrow{font-family:system-ui,sans-serif;font-size:11px;letter-spacing:4px;text-transform:uppercase;color:var(--amber);text-align:center;margin-bottom:10px}
  h1{font-size:34px;font-weight:400;text-align:center;margin:0 0 12px;color:var(--ink)}
  .lede{text-align:center;color:#57534e;font-size:15px;line-height:1.55;font-family:system-ui,sans-serif;margin:0 0 36px;padding:0 8px}
  form{background:white;border:1px solid #e7e5e4;border-radius:8px;padding:24px 26px;margin-bottom:24px}
  label{display:block;font-family:system-ui,sans-serif;font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--amber);margin-bottom:8px;font-weight:600}
  .row{display:flex;gap:8px}
  input[type=text]{flex:1;padding:11px 14px;border:1px solid #d6d3d1;border-radius:5px;font-family:ui-monospace,monospace;font-size:14px;color:var(--ink);background:#fafaf9;letter-spacing:1px;text-transform:uppercase}
  input[type=text]:focus{outline:none;border-color:var(--amber);background:white}
  button{padding:11px 22px;border:none;border-radius:5px;background:var(--amber);color:white;font-family:system-ui,sans-serif;font-weight:600;font-size:14px;cursor:pointer}
  button:hover{background:#92400e}
  .hint{font-family:system-ui,sans-serif;font-size:12px;color:#78716c;margin-top:10px}
  .error{display:__ERR_DISP__;background:#fef2f2;border:1px solid #fca5a5;color:#b91c1c;padding:10px 14px;border-radius:5px;font-family:system-ui,sans-serif;font-size:13px;margin-bottom:18px}
  .info{background:white;border:1px solid #e7e5e4;border-radius:8px;padding:20px 24px;font-family:system-ui,sans-serif;font-size:13px;line-height:1.6;color:#44403c}
  .info strong{color:var(--ink)}
  .info code{font-family:ui-monospace,monospace;background:#f5f5f4;padding:2px 6px;border-radius:3px;color:var(--amber)}
</style>
</head>
<body>
<nav class="nav">
  <a class="brand" href="__BASE__"><span class="brand-dot"></span> AutomateEdge</a>
  <a class="home-link" href="__BASE__">← Back to roadmap</a>
</nav>
<div class="wrap">
  <div class="eyebrow">Credential Verification</div>
  <h1>Verify a Certificate</h1>
  <p class="lede">Enter the credential ID printed on the certificate (or scanned from its QR code) to confirm it was issued by AutomateEdge and has not been revoked.</p>

  <div class="error">__ERR_MSG__</div>

  <form method="get" action="/verify/lookup" autocomplete="off">
    <label for="cid">Credential ID</label>
    <div class="row">
      <input id="cid" name="id" type="text" placeholder="AER-2026-04-XXXXXX" pattern="AER-[0-9]{4}-[0-9]{2}-[A-Z0-9]{6}" required maxlength="18" autofocus>
      <button type="submit">Verify</button>
    </div>
    <div class="hint">Format: <code style="font-family:ui-monospace,monospace">AER-YYYY-MM-XXXXXX</code> — case-insensitive.</div>
  </form>

  <div class="info">
    <strong>How it works.</strong> Each certificate carries an HMAC-SHA256 signature
    over its credential ID, the recipient's user ID, and the issue timestamp. When
    you submit an ID we look it up, recompute the signature server-side, and show
    a green badge if it matches the stored hash and the certificate hasn't been
    revoked. Tampered or revoked credentials show a red badge.
  </div>
</div>
</body>
</html>"""


def _index_html(error: str = "") -> str:
    base = get_settings().public_base_url.rstrip("/")
    return (
        _INDEX_HTML
        .replace("__BASE__", base)
        .replace("__ERR_MSG__", _html.escape(error))
        .replace("__ERR_DISP__", "block" if error else "none")
    )


@router.get("/verify", response_class=HTMLResponse)
@router.get("/verify/", response_class=HTMLResponse)
async def verify_index():
    """Paste-an-ID lookup form. Recruiters who don't have the full URL
    (e.g. they only have the printed credential ID from a PDF) can land
    here and look it up."""
    return HTMLResponse(_index_html())


@router.get("/verify/lookup", response_class=HTMLResponse)
async def verify_lookup(request: Request):
    """Form target — normalize the ID and either redirect to the cert
    page or re-render the form with an inline error."""
    raw = (request.query_params.get("id") or "").strip()
    # Allow users to paste the full URL — extract the trailing segment.
    lower = raw.lower()
    if "/verify/" in lower:
        idx = lower.index("/verify/") + len("/verify/")
        raw = raw[idx:].split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    raw = raw.upper()
    import re
    if not re.fullmatch(r"AER-\d{4}-\d{2}-[A-Z0-9]{6}", raw):
        return HTMLResponse(
            _index_html(f"That doesn't look like a valid credential ID. Expected format: AER-YYYY-MM-XXXXXX."),
            status_code=400,
        )
    # Redirect to the canonical verify page
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"/verify/{raw}", status_code=303)


@router.get("/verify/{credential_id}", response_class=HTMLResponse)
async def verify_page(
    credential_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    ip = _client_ip(request)
    if not _rate_check(ip):
        raise HTTPException(status_code=429, detail="Too many verification requests")

    cert = (
        await db.execute(
            select(Certificate).where(Certificate.credential_id == credential_id)
        )
    ).scalar_one_or_none()

    if cert is None:
        return HTMLResponse(_not_found_html(credential_id), status_code=404)

    if _should_increment(ip, credential_id):
        cert.verification_views += 1
        await db.flush()

    signature_ok = verify_signature(cert)
    is_revoked = cert.revoked_at is not None

    return HTMLResponse(_render(cert, signature_ok=signature_ok, is_revoked=is_revoked))


# ---- HTML rendering ----

def _esc(s: str | int | None) -> str:
    return _html.escape(str(s)) if s is not None else ""


def _not_found_html(credential_id: str) -> str:
    base = get_settings().public_base_url.rstrip("/")
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Credential not found — AutomateEdge</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{{font-family:system-ui,sans-serif;background:#0f1419;color:#f5f1e8;min-height:100vh;margin:0;display:flex;align-items:center;justify-content:center;text-align:center}}
.card{{max-width:480px;padding:48px}}h1{{color:#ef4444;margin:0 0 12px}}.code{{font-family:monospace;background:#1f2937;padding:4px 8px;border-radius:3px;color:#e8a849}}a{{color:#e8a849}}</style>
</head><body><div class="card">
<h1>✗ Credential Not Found</h1>
<p>We could not find a certificate with ID <span class="code">{_esc(credential_id)}</span>.</p>
<p>This may be a typo, a revoked credential, or a forged one. <a href="{base}">Return to AutomateEdge</a>.</p>
</div></body></html>"""


def _render(cert: Certificate, *, signature_ok: bool, is_revoked: bool) -> str:
    settings = get_settings()
    base = settings.public_base_url.rstrip("/")
    verify_url = f"{base}/verify/{cert.credential_id}"
    og_image_url = f"{base}/verify/{cert.credential_id}/og.svg"

    issued_iso = cert.issued_at.strftime("%B %d, %Y") if cert.issued_at else ""
    tier_label = _TIER_LABEL.get(cert.tier, "Certificate")

    # Badge state
    if is_revoked:
        badge_class = "badge bad"
        badge_icon = "✗"
        badge_text = "Revoked"
        badge_sub = f"Reason: {_esc(cert.revoke_reason or 'No reason provided')}"
    elif not signature_ok:
        badge_class = "badge bad"
        badge_icon = "✗"
        badge_text = "Signature mismatch"
        badge_sub = "The credential data does not match its signature. Possible tampering."
    else:
        badge_class = "badge ok"
        badge_icon = "✓"
        badge_text = "Credential verified"
        badge_sub = f"Cryptographically signed by AutomateEdge on {issued_iso}."

    og_title = f"{_esc(cert.display_name)} — {tier_label}"
    og_desc = f"{_esc(cert.course_title)} · {_esc(cert.duration_months)}-month {_esc(cert.level)} program · Verified at {_esc(settings.public_base_url)}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(cert.display_name)} — {_esc(tier_label)} | AutomateEdge</title>
<meta name="description" content="{og_desc}">
<meta property="og:title" content="{og_title}">
<meta property="og:description" content="{og_desc}">
<meta property="og:image" content="{og_image_url}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:url" content="{verify_url}">
<meta property="og:type" content="website">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{og_title}">
<meta name="twitter:description" content="{og_desc}">
<meta name="twitter:image" content="{og_image_url}">
<style>
  :root{{--amber:#b45309;--amber-light:#fffaf1;--ink:#1f1610}}
  *{{box-sizing:border-box}}
  body{{font-family:Georgia,"DejaVu Serif",serif;background:#fffaf1;color:var(--ink);margin:0;min-height:100vh}}
  .wrap{{max-width:760px;margin:0 auto;padding:48px 24px}}
  .eyebrow{{font-family:system-ui,sans-serif;font-size:11px;letter-spacing:4px;text-transform:uppercase;color:var(--amber);text-align:center;margin-bottom:8px}}
  h1{{font-size:34px;font-weight:400;text-align:center;margin:0 0 4px;color:var(--ink)}}
  .tier{{text-align:center;font-family:system-ui,sans-serif;font-size:13px;letter-spacing:2px;text-transform:uppercase;color:var(--amber);margin-bottom:32px}}
  .badge{{display:flex;gap:14px;align-items:flex-start;padding:18px 22px;border-radius:8px;margin:28px 0;font-family:system-ui,sans-serif}}
  .badge.ok{{background:#ecfdf5;border:1px solid #10b981}}
  .badge.bad{{background:#fef2f2;border:1px solid #ef4444}}
  .badge .icon{{font-size:28px;line-height:1;flex:0 0 auto}}
  .badge.ok .icon{{color:#047857}}
  .badge.bad .icon{{color:#b91c1c}}
  .badge .title{{font-weight:700;font-size:16px}}
  .badge.ok .title{{color:#047857}}
  .badge.bad .title{{color:#b91c1c}}
  .badge .sub{{font-size:13px;color:#44403c;margin-top:2px}}
  .details{{background:white;border:1px solid #e7e5e4;border-radius:8px;padding:28px 28px 24px}}
  .details h2{{font-family:system-ui,sans-serif;font-size:12px;letter-spacing:2px;text-transform:uppercase;color:var(--amber);margin:0 0 16px}}
  .details .name{{font-size:28px;font-style:italic;font-weight:400;color:var(--ink);margin-bottom:20px}}
  dl{{display:grid;grid-template-columns:160px 1fr;gap:10px 20px;margin:0;font-family:system-ui,sans-serif;font-size:14px}}
  dt{{color:#78716c;font-weight:500}}
  dd{{margin:0;color:var(--ink)}}
  dd code{{font-family:ui-monospace,monospace;font-size:13px;background:#f5f5f4;padding:2px 6px;border-radius:3px;color:var(--amber)}}
  .cta{{margin-top:28px;text-align:center}}
  .cta a{{display:inline-block;background:var(--amber);color:white;padding:10px 20px;border-radius:4px;text-decoration:none;font-family:system-ui,sans-serif;font-weight:600;font-size:14px}}
  .foot{{margin-top:32px;text-align:center;font-family:system-ui,sans-serif;font-size:12px;color:#78716c}}
  .foot a{{color:var(--amber)}}
</style>
</head>
<body>
  <div class="wrap">
    <div class="eyebrow">AutomateEdge Verified Credential</div>
    <h1>{_esc(cert.course_title)}</h1>
    <div class="tier">{_esc(tier_label)}</div>

    <div class="{badge_class}">
      <div class="icon">{badge_icon}</div>
      <div>
        <div class="title">{badge_text}</div>
        <div class="sub">{badge_sub}</div>
      </div>
    </div>

    <div class="details">
      <h2>Issued To</h2>
      <div class="name">{_esc(cert.display_name)}</div>
      <dl>
        <dt>Credential ID</dt><dd><code>{_esc(cert.credential_id)}</code></dd>
        <dt>Issued</dt><dd>{_esc(issued_iso)}</dd>
        <dt>Course</dt><dd>{_esc(cert.course_title)}</dd>
        <dt>Level</dt><dd>{_esc(cert.level.capitalize())}</dd>
        <dt>Duration</dt><dd>{_esc(cert.duration_months)} months · {_esc(cert.total_hours)} hours</dd>
        <dt>Milestones</dt><dd>{_esc(cert.checks_done)} / {_esc(cert.checks_total)} completed</dd>
        <dt>Projects shipped</dt><dd>{_esc(cert.repos_linked)} GitHub {'repository' if cert.repos_linked == 1 else 'repositories'}</dd>
      </dl>
    </div>

    <div class="cta" style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap">
      <a href="https://www.linkedin.com/sharing/share-offsite/?url={verify_url}" target="_blank" rel="noopener" style="background:#0a66c2">Share on LinkedIn</a>
      <a href="{base}">Start your own AI roadmap</a>
    </div>

    <div class="foot">
      To independently verify, re-enter the credential ID at
      <a href="{base}/verify">{_esc(settings.public_base_url.replace('https://','').replace('http://','').rstrip('/'))}/verify</a>
    </div>
  </div>
</body>
</html>"""


@router.get("/verify/{credential_id}/og.svg")
async def verify_og_image(
    credential_id: str,
    db: AsyncSession = Depends(get_db),
):
    """1200x630 SVG preview used by LinkedIn / Twitter link cards."""
    cert = (
        await db.execute(
            select(Certificate).where(Certificate.credential_id == credential_id)
        )
    ).scalar_one_or_none()
    if cert is None:
        raise HTTPException(status_code=404, detail="Not found")

    tier_label = _TIER_LABEL.get(cert.tier, "Certificate")
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630" width="1200" height="630">
  <rect width="1200" height="630" fill="#fffaf1"/>
  <rect x="0" y="0" width="1200" height="10" fill="#b45309"/>
  <rect x="0" y="620" width="1200" height="10" fill="#b45309"/>
  <text x="600" y="110" text-anchor="middle" fill="#b45309" font-family="system-ui,sans-serif" font-size="18" letter-spacing="6">AUTOMATEEDGE · VERIFIED CREDENTIAL</text>
  <text x="600" y="230" text-anchor="middle" fill="#1f1610" font-family="Georgia,serif" font-size="48">{_esc(cert.course_title)[:44]}</text>
  <text x="600" y="285" text-anchor="middle" fill="#b45309" font-family="system-ui,sans-serif" font-size="18" letter-spacing="3">{_esc(tier_label.upper())}</text>
  <text x="600" y="400" text-anchor="middle" fill="#1f1610" font-family="Georgia,serif" font-style="italic" font-size="54">{_esc(cert.display_name)[:36]}</text>
  <text x="600" y="470" text-anchor="middle" fill="#57534e" font-family="system-ui,sans-serif" font-size="20">{_esc(cert.duration_months)}-month {_esc(cert.level)} program · {_esc(cert.total_hours)} hours · {_esc(cert.repos_linked)} projects</text>
  <text x="600" y="560" text-anchor="middle" fill="#78716c" font-family="ui-monospace,monospace" font-size="16">{_esc(cert.credential_id)}</text>
</svg>"""
    return HTMLResponse(content=svg, media_type="image/svg+xml",
                        headers={"Cache-Control": "public, max-age=3600"})
