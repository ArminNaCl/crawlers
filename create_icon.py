"""
Generates assets/icon.ico for the EComCrawler Windows build.

Tries to render the 🐙 emoji using the system emoji font.
Falls back to a clean geometric octopus shape when the font
is unavailable (e.g. on Linux CI).

Run before PyInstaller:
    pip install pillow
    python create_icon.py
"""

from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


# Purple gradient colours matching the app UI
_BG       = (102, 126, 234, 255)   # #667eea
_BG_DARK  = (118,  75, 162, 255)   # #764ba2
_BODY     = (160, 120, 220, 255)
_TENTACLE = (130,  90, 200, 255)
_WHITE    = (255, 255, 255, 255)
_PUPIL    = ( 40,  30,  70, 255)


def _draw_gradient_circle(draw: ImageDraw.ImageDraw, size: int) -> None:
    """Fill the background with a soft radial gradient approximation."""
    for r in range(size // 2, 0, -1):
        t = r / (size // 2)
        c = tuple(int(_BG[i] * t + _BG_DARK[i] * (1 - t)) for i in range(3)) + (255,)
        cx, cy = size // 2, size // 2
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c)


def _draw_octopus(draw: ImageDraw.ImageDraw, size: int) -> None:
    s = size / 256  # scale factor relative to 256 px master

    # ── body (head) ────────────────────────────────────────────────────────
    bx0, by0 = int(55 * s), int(30 * s)
    bx1, by1 = int(201 * s), int(160 * s)
    draw.ellipse([bx0, by0, bx1, by1], fill=_BODY)

    # ── eyes ───────────────────────────────────────────────────────────────
    er = int(22 * s)
    for ex in (int(93 * s), int(163 * s)):
        ey = int(84 * s)
        draw.ellipse([ex - er, ey - er, ex + er, ey + er], fill=_WHITE)
        pr = int(11 * s)
        draw.ellipse([ex - pr, ey - pr, ex + pr, ey + pr], fill=_PUPIL)

    # ── tentacles (8, alternating lengths) ─────────────────────────────────
    cx = size // 2
    base_y = int(148 * s)
    offsets = [-84, -56, -28, 0, 28, 56, 84, 112]  # x offsets at 256 px
    lengths = [80, 96, 80, 96, 80, 96, 80, 72]      # total drop

    for dx, length in zip(offsets, lengths):
        tx = cx + int(dx * s)
        ty0 = base_y
        ty1 = ty0 + int(length * s)
        tw = int(14 * s)
        # Simple rounded tentacle: wide at top, narrow at tip
        draw.ellipse([tx - tw, ty0, tx + tw, ty1], fill=_TENTACLE)
        # tiny sucker dots
        for dot_y in range(ty0 + int(10 * s), ty1 - int(6 * s), int(18 * s)):
            dr = int(4 * s)
            draw.ellipse([tx - dr, dot_y - dr, tx + dr, dot_y + dr], fill=_WHITE)


def _try_emoji(draw: ImageDraw.ImageDraw, size: int) -> bool:
    """Attempt to render 🐙 with the system emoji font. Returns True on success."""
    candidates = [
        "seguiemj.ttf",                              # Windows (GitHub Actions)
        "C:/Windows/Fonts/seguiemj.ttf",
        "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",   # Debian/Ubuntu
        "/System/Library/Fonts/Apple Color Emoji.ttc",          # macOS
    ]
    font_size = int(150 * (size / 256))
    for path in candidates:
        try:
            font = ImageFont.truetype(path, font_size)
            bbox = draw.textbbox((0, 0), "🐙", font=font)
            x = (size - (bbox[2] - bbox[0])) // 2 - bbox[0]
            y = (size - (bbox[3] - bbox[1])) // 2 - bbox[1]
            draw.text((x, y), "🐙", font=font, embedded_color=True)
            return True
        except Exception:
            continue
    return False


def make_frame(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _draw_gradient_circle(draw, size)
    if not _try_emoji(draw, size):
        _draw_octopus(draw, size)
    return img


def main() -> None:
    Path("assets").mkdir(exist_ok=True)
    master = make_frame(256)
    master.save(
        "assets/icon.ico",
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (256, 256)],
    )
    print("OK: Generated assets/icon.ico")


if __name__ == "__main__":
    main()
