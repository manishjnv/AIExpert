"""OG card renderer (SEO-11). 1200x630 PNG cards for social share previews.

Uses Pillow + DejaVu fonts (installed via fonts-dejavu-core in the backend
Dockerfile). Falls back to PIL default on dev hosts where DejaVu is missing,
so tests run on Windows/macOS without extra setup.

Palette matches frontend/index.html: dark charcoal bg, gold accent, bone text.
Layout is type-led — wordmark top-left, gold separator, kicker line, title
(wrapped, max 3 lines), subtitle, domain footer. No stock imagery, no gradients.

Cards are pure functions of their inputs. Caching lives in routers/og.py —
this module just returns bytes.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

# Palette — matches the site
BG = (15, 20, 25)        # #0f1419
FG = (232, 228, 216)     # #e8e4d8
ACCENT = (232, 168, 73)  # #e8a849
MUTED = (140, 148, 160)

WIDTH, HEIGHT = 1200, 630
PAD_X = 64

_FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
_FONT_PATHS = {
    "bold": _FONT_DIR / "DejaVuSans-Bold.ttf",
    "regular": _FONT_DIR / "DejaVuSans.ttf",
    "mono": _FONT_DIR / "DejaVuSansMono-Bold.ttf",
}


def _font(name: str, size: int) -> ImageFont.ImageFont:
    path = _FONT_PATHS.get(name)
    if path and path.exists():
        return ImageFont.truetype(str(path), size)
    # Dev fallback (DejaVu not installed) — tests only check dimensions.
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str,
          font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current: list[str] = []
    for w in words:
        trial = " ".join(current + [w])
        bbox = draw.textbbox((0, 0), trial, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current.append(w)
        else:
            if current:
                lines.append(" ".join(current))
            current = [w]
    if current:
        lines.append(" ".join(current))
    return lines


def _draw_logo(img: Image.Image, x: int, y: int, size: int) -> None:
    """Draw the site favicon (frontend/favicon.svg, a 32x32 mark) into
    img at (x, y) scaled to `size` x `size`. Uses PIL primitives so we
    don't take on a new SVG-renderer dep. Geometry mirrors the SVG:
    rounded gold square, dark inverted-V stroke, dark dot at the apex,
    dark horizontal crossbar — read as an abstract "A" / peak."""
    s = size / 32  # SVG → output scale
    draw = ImageDraw.Draw(img)
    # Gold rounded background
    rx = max(3, int(6 * s))
    draw.rounded_rectangle(
        [(x, y), (x + size, y + size)],
        radius=rx, fill=ACCENT,
    )
    # The "A" stroke: M9,23 → L16,8 → L23,23 (SVG stroke width 2.5)
    sw = max(2, int(2.5 * s))
    pts = [
        (x + int(9 * s), y + int(23 * s)),
        (x + int(16 * s), y + int(8 * s)),
        (x + int(23 * s), y + int(23 * s)),
    ]
    draw.line(pts, fill=BG, width=sw, joint="curve")
    # Round-cap the apex (PIL's line caps are square) by overlaying a
    # small filled circle at the peak.
    cap_r = sw // 2
    apex = pts[1]
    draw.ellipse(
        [(apex[0] - cap_r, apex[1] - cap_r), (apex[0] + cap_r, apex[1] + cap_r)],
        fill=BG,
    )
    # Filled dot just below apex: (16, 13) r=2.5
    cx, cy = x + int(16 * s), y + int(13 * s)
    cr = max(2, int(2.5 * s))
    draw.ellipse(
        [(cx - cr, cy - cr), (cx + cr, cy + cr)],
        fill=BG,
    )
    # Horizontal crossbar: (12, 19) → (20, 19), stroke width 2
    bw = max(2, int(2 * s))
    draw.line(
        [(x + int(12 * s), y + int(19 * s)),
         (x + int(20 * s), y + int(19 * s))],
        fill=BG, width=bw,
    )


def _render_card(kicker: str, title: str, subtitle: Optional[str] = None) -> bytes:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    # Logo (top-left) + wordmark to its right + gold accent bar below.
    # Logo is a real visual element — gives the OG card recognizable
    # brand identity in a feed before any text is read.
    logo_size = 80
    logo_x, logo_y = PAD_X, 48
    _draw_logo(img, logo_x, logo_y, logo_size)
    wm_font = _font("mono", 30)
    wm_y = logo_y + (logo_size - 30) // 2 - 2
    draw.text((logo_x + logo_size + 22, wm_y), "AUTOMATEEDGE",
              font=wm_font, fill=ACCENT)
    draw.rectangle(
        [(PAD_X, logo_y + logo_size + 18), (PAD_X + 220, logo_y + logo_size + 22)],
        fill=ACCENT,
    )

    # Kicker (small, muted, uppercase)
    k_font = _font("mono", 22)
    draw.text((PAD_X, 180), kicker.upper(), font=k_font, fill=MUTED)

    # Title (bold, wrapped, max 3 lines)
    t_font = _font("bold", 64)
    title_lines = _wrap(draw, title, t_font, WIDTH - 2 * PAD_X)[:3]
    y = 230
    for line in title_lines:
        draw.text((PAD_X, y), line, font=t_font, fill=FG)
        y += 82

    # Subtitle (muted, wrapped, max 2 lines)
    if subtitle:
        s_font = _font("regular", 28)
        sub_lines = _wrap(draw, subtitle, s_font, WIDTH - 2 * PAD_X)[:2]
        sub_y = max(y + 20, HEIGHT - 150)
        for line in sub_lines:
            draw.text((PAD_X, sub_y), line, font=s_font, fill=MUTED)
            sub_y += 40

    # Domain footer (bottom-right, gold)
    f_font = _font("mono", 22)
    footer = "automateedge.cloud"
    fb = draw.textbbox((0, 0), footer, font=f_font)
    fw = fb[2] - fb[0]
    draw.text((WIDTH - PAD_X - fw, HEIGHT - 56), footer,
              font=f_font, fill=ACCENT)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ---- Public render functions (one per type) ---------------------------------


def render_course() -> bytes:
    """Landing-page Course card. Referenced by frontend/index.html og:image."""
    return _render_card(
        kicker="AI Generalist Roadmap",
        title="From zero to AI-ready in 24 weeks",
        subtitle="Free, community-driven, updated quarterly",
    )


TRACK_TITLES = {
    "generalist": "AI Generalist Roadmap",
    "ai-engineer": "AI Engineer Roadmap",
    "ml-engineer": "ML Engineer Roadmap",
    "data-scientist": "Data Scientist Roadmap",
}


def render_roadmap(track: str) -> Optional[bytes]:
    title = TRACK_TITLES.get(track)
    if not title:
        return None
    return _render_card(
        kicker="24-Week Track",
        title=title,
        subtitle="Weekly milestones / curated resources / community progress",
    )


def render_blog(title: str, published: str = "", author: str = "AutomateEdge") -> bytes:
    kicker = f"Blog · {published}" if published else "Blog"
    return _render_card(
        kicker=kicker,
        title=title,
        subtitle=f"by {author}" if author else None,
    )


def render_jobs(role: str, company: str, location: str = "",
                salary: str = "") -> bytes:
    kicker = f"AI Job · {company}" if company else "AI Job"
    parts = [p for p in (location, salary) if p]
    return _render_card(
        kicker=kicker,
        title=role,
        subtitle=" · ".join(parts) if parts else None,
    )
