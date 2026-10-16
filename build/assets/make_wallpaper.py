#!/usr/bin/env python3
"""Generate the D.Ai OS "Night" wallpaper (deterministic).

Usage: make_wallpaper.py <output.jpg> [width] [height]
Requires numpy and Pillow (build-time only; the image is committed).
"""

import sys

import numpy as np
from PIL import Image

BG_TOP = np.array([11, 16, 32], dtype=np.float64)      # #0B1020
BG_BOTTOM = np.array([20, 27, 51], dtype=np.float64)   # #141B33
VIOLET = np.array([124, 92, 255], dtype=np.float64)    # #7C5CFF
CYAN = np.array([34, 211, 238], dtype=np.float64)      # #22D3EE


def glow(x, y, cx, cy, rx, ry, angle):
    """Soft elliptical glow in [0, 1]."""
    c, s = np.cos(angle), np.sin(angle)
    dx, dy = x - cx, y - cy
    u = (dx * c + dy * s) / rx
    v = (-dx * s + dy * c) / ry
    return np.exp(-(u * u + v * v))


def ribbon(x, y, base, slope, amp, freq, phase, width, fade_from, fade_to):
    """Curved aurora ribbon: a soft band around a sine-modulated centre line."""
    centre = base + slope * x + amp * np.sin(2 * np.pi * freq * x + phase)
    thickness = width * (0.6 + 0.4 * np.sin(2 * np.pi * 0.7 * x + phase * 1.7) ** 2)
    band = np.exp(-(((y - centre) / thickness) ** 2))
    fade = np.clip((x - fade_from) / 0.25, 0, 1) * np.clip((fade_to - x) / 0.25, 0, 1)
    return band * fade


def render(width: int, height: int) -> Image.Image:
    rng = np.random.default_rng(1452)  # fixed seed: reproducible output
    py, px = np.mgrid[0:height, 0:width].astype(np.float64)
    x, y = px / width, py / height

    img = BG_TOP + (BG_BOTTOM - BG_TOP) * y[..., None]

    # Aurora: two violet ribbons and one cyan ribbon with a bright core.
    violet = (
        0.75 * ribbon(x, y, 0.46, -0.30, 0.05, 1.1, 0.4, 0.075, -0.2, 1.1)
        + 0.35 * ribbon(x, y, 0.36, -0.22, 0.07, 0.8, 2.1, 0.13, -0.1, 0.9)
    )
    cyan = 0.65 * ribbon(x, y, 0.80, -0.32, 0.04, 1.3, 4.0, 0.055, 0.15, 1.2)
    core = 0.35 * ribbon(x, y, 0.46, -0.30, 0.05, 1.1, 0.4, 0.018, 0.1, 0.8)
    img += np.clip(violet, 0, 1)[..., None] * (VIOLET - img) * 0.8
    img += np.clip(cyan, 0, 1)[..., None] * (CYAN - img) * 0.65
    img += core[..., None] * (np.array([220, 210, 255.0]) - img) * 0.5

    # Diamond lattice at 45 degrees in pixel space (the D.Ai mark), very faint.
    cell = height / 18.0
    u = (px + py) / cell
    v = (px - py) / cell
    edge = np.minimum(np.abs(u - np.round(u)), np.abs(v - np.round(v)))
    lines = np.clip(1.0 - edge * cell / 1.2, 0, 1)
    vignette = glow(x, y, 0.5, 0.5, 0.65, 0.6, 0.0)
    img += (lines * vignette * 7.0)[..., None]

    # Large, soft diamond outline on the right: the brand mark.
    dx, dy = (x - 0.76) * width / height, y - 0.42
    diamond = np.abs(dx) + np.abs(dy)
    outline = np.exp(-(((diamond - 0.17) / 0.0035) ** 2))
    img += outline[..., None] * (np.array([184, 166, 255.0]) - img) * 0.22

    # Darken edges slightly and dither to avoid gradient banding.
    img *= (0.80 + 0.20 * vignette)[..., None]
    img += rng.normal(0, 1.2, img.shape)
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    width = int(sys.argv[2]) if len(sys.argv) > 2 else 2560
    height = int(sys.argv[3]) if len(sys.argv) > 3 else 1440
    render(width, height).save(sys.argv[1], quality=90, optimize=True, progressive=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
