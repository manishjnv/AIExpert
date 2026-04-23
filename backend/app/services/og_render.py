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


def _render_card(kicker: str, title: str, subtitle: Optional[str] = None) -> bytes:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    # Wordmark (top-left) + gold accent bar
    wm_font = _font("mono", 24)
    draw.text((PAD_X, 56), "AUTOMATEEDGE", font=wm_font, fill=ACCENT)
    draw.rectangle([(PAD_X, 98), (PAD_X + 180, 102)], fill=ACCENT)

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
