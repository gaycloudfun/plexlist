"""
Generate a Plex-styled app icon and package it as a .icns file.
Colors: Plex orange #E5A00D on dark #1C1C1E background.
"""

import math
import os
import shutil
import subprocess
from PIL import Image, ImageDraw

PLEX_ORANGE = (229, 160, 13, 255)
PLEX_DARK   = (28, 28, 30, 255)
WHITE       = (255, 255, 255, 220)

SIZES = [16, 32, 64, 128, 256, 512, 1024]


def draw_icon(size: int) -> Image.Image:
    img = Image.new("RGB", (size, size), (0, 0, 0))
    d = ImageDraw.Draw(img)

    # Rounded rect background
    radius = size // 5
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius,
                         fill=(28, 28, 30))

    # Plex-style play triangle (centered, slightly left)
    cx = size * 0.42
    cy = size * 0.50
    tri_h = size * 0.44
    tri_w = tri_h * 0.87

    tri = [
        (cx - tri_w * 0.38, cy - tri_h * 0.50),  # top-left
        (cx - tri_w * 0.38, cy + tri_h * 0.50),  # bottom-left
        (cx + tri_w * 0.62, cy),                  # right point
    ]
    d.polygon(tri, fill=(229, 160, 13))

    # Playlist lines (right of triangle)
    line_x_start = size * 0.62
    line_x_end   = size * 0.87
    line_y_positions = [size * 0.38, size * 0.50, size * 0.62]
    lw = max(2, size // 52)

    for ly in line_y_positions:
        d.rounded_rectangle(
            [line_x_start, ly - lw, line_x_end, ly + lw],
            radius=lw,
            fill=(255, 255, 255),
        )

    # Convert to RGBA for transparency support in icns
    return img.convert("RGBA")


def build_icns(out_path: str = "AppIcon.icns"):
    iconset_dir = "AppIcon.iconset"
    os.makedirs(iconset_dir, exist_ok=True)

    for size in SIZES:
        img = draw_icon(size)
        img.save(f"{iconset_dir}/icon_{size}x{size}.png")
        if size <= 512:
            img2x = draw_icon(size * 2)
            img2x.save(f"{iconset_dir}/icon_{size}x{size}@2x.png")

    subprocess.run(["iconutil", "-c", "icns", iconset_dir, "-o", out_path], check=True)
    shutil.rmtree(iconset_dir)
    print(f"Icon saved: {out_path}")


if __name__ == "__main__":
    build_icns("AppIcon.icns")
    # Also save a preview PNG
    preview = draw_icon(512)
    preview.save("AppIcon_preview.png")
    print("Preview saved: AppIcon_preview.png")
