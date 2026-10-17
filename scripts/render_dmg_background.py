"""Render the macOS DMG background for the Yunmell desktop installer.

Upstream Octop ships an English "Drag Octop ..." background.  This fork must
not ship upstream branding, so the DMG background is regenerated here.

The image is intentionally text-only: Finder draws the application icon and
the Applications alias on top of it, so a drawn arrow would land at a
different place than the real drop target.

Usage::

    python scripts/render_dmg_background.py
    python scripts/render_dmg_background.py --out /tmp/background.jpeg

The output size (2560x1696) matches the upstream asset so
``desktop/src/build/darwin/Taskfile.yml`` keeps resampling it to the exact
1200x800 @144dpi window.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 2560, 1696
HEADER_HEIGHT = 452

# Same pink/peach band as upstream so the desktop icon and the Applications
# alias keep their contrast, but without any upstream copy.
BAND_LEFT = (255, 150, 178)
BAND_RIGHT = (255, 226, 196)
CANVAS = (250, 250, 250)
TEXT = (24, 24, 27)
SUBTEXT = (82, 82, 91)

DEFAULT_OUT = Path("desktop/src/build/darwin/dmg-background.jpeg")


def _find_chinese_font(bold: bool) -> Path:
    """Pick an installed CJK-capable font, cross-platform."""
    candidates = [
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
        if bold
        else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file():
            return path
    raise SystemExit("no CJK font found; install Noto Sans CJK or Microsoft YaHei first")


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
    """Pillow <8 has no ``textbbox``; ``textsize`` works on every version."""
    if hasattr(draw, "textbbox"):  # Pillow >= 8
        left, _, right, _ = draw.textbbox((0, 0), text, font=font)
        return right - left
    return draw.textsize(text, font=font)[0]


def _band(draw: ImageDraw.ImageDraw) -> None:
    """Fill the header band with a left-to-right pink/peach gradient."""
    for x in range(WIDTH):
        t = x / max(WIDTH - 1, 1)
        color = tuple(round(BAND_LEFT[i] + (BAND_RIGHT[i] - BAND_LEFT[i]) * t) for i in range(3))
        draw.line([(x, 0), (x, HEADER_HEIGHT)], fill=color)


def render(out: Path) -> None:
    bold = _find_chinese_font(bold=True)
    regular = _find_chinese_font(bold=False)

    image = Image.new("RGB", (WIDTH, HEIGHT), CANVAS)
    draw = ImageDraw.Draw(image)
    _band(draw)

    title = _font(bold, 168)
    body = _font(regular, 76)

    headline = "拖入「应用程序」文件夹"
    headline_width = _text_width(draw, headline, title)
    draw.text(
        ((WIDTH - headline_width) / 2, 96),
        headline,
        font=title,
        fill=TEXT,
    )

    subtitle = "Drag 云迈智能体 into Applications to install"
    subtitle_width = _text_width(draw, subtitle, body)
    draw.text(
        ((WIDTH - subtitle_width) / 2, 294),
        subtitle,
        font=body,
        fill=SUBTEXT,
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out, format="JPEG", quality=95, optimize=True)
    print(f"wrote {out} ({WIDTH}x{HEIGHT})", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"output path (default: {DEFAULT_OUT})",
    )
    args = parser.parse_args(argv)
    render(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
