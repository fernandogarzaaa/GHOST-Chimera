"""Draw the Ghost Chimera mark and export desktop icons.

Master: 1024px PNG (dark rounded square + green ghost silhouette).
Outputs: icon.png, ghost.ico (multi-size), ghost.icns (macOS bundle).

Usage:
    python packaging/assets/generate_icons.py [--out packaging/assets]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 1024
BG = (10, 12, 16, 255)  # --bg
ACCENT = (95, 224, 168, 255)  # --accent
DARK = (5, 20, 13, 255)  # eyes on accent


def draw_mark() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Rounded-square backdrop.
    d.rounded_rectangle([0, 0, SIZE, SIZE], radius=232, fill=BG)
    # Ghost body: head circle + torso, centered.
    cx, top, w = SIZE // 2, 200, 560
    d.ellipse([cx - w // 2, top, cx + w // 2, top + w], fill=ACCENT)
    body_top, body_bottom = top + w // 2 - 40, 824
    d.rectangle([cx - w // 2, body_top, cx + w // 2, body_bottom], fill=ACCENT)
    # Scalloped sheet bottom: three semicircular cutouts.
    foot_w = w // 3
    for i in range(3):
        x0 = cx - w // 2 + i * foot_w
        d.pieslice([x0, body_bottom - foot_w, x0 + foot_w, body_bottom], 0, 180, fill=BG)
    # Eyes.
    eye_y, eye_r, eye_dx = 430, 44, 118
    d.ellipse([cx - eye_dx - eye_r, eye_y - eye_r, cx - eye_dx + eye_r, eye_y + eye_r], fill=DARK)
    d.ellipse([cx + eye_dx - eye_r, eye_y - eye_r, cx + eye_dx + eye_r, eye_y + eye_r], fill=DARK)
    return img


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="packaging/assets")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    master = draw_mark()
    master.save(out / "icon.png")
    master.save(out / "ghost.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    master.save(out / "ghost.icns")
    print(f"icons written to {out}: icon.png, ghost.ico, ghost.icns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
