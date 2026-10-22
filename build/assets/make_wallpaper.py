#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Generate the D.Ai OS "Night 2" wallpaper (deterministic; docs/LOOK.md §2).

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
MAGENTA = np.array([255, 122, 158], dtype=np.float64)  # #FF7A9E
DEEP = np.array([7, 10, 24], dtype=np.float64)         # under the taskbar


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
    """A gradient mesh: three large soft lights on deep blue, the diamond as a faint line, fine grain."""
    rng = np.random.default_rng(1452)  # fixed seed: reproducible output
    py, px = np.mgrid[0:height, 0:width].astype(np.float64)
    x, y = px / width, py / height
    aspect = width / height

    img = BG_TOP + (DEEP - BG_TOP) * (y ** 1.6)[..., None]

    def light(cx, cy, rx, ry, angle, color, strength):
        g = glow(x * aspect, y, cx * aspect, cy, rx, ry, angle)
        return (g ** 1.15)[..., None] * (color - img) * strength

    img += light(0.22, 0.18, 0.62, 0.34, -0.35, VIOLET, 0.78)        # a wide violet light, top left
    img += light(0.84, 0.30, 0.40, 0.26, 0.55, CYAN, 0.62)           # cyan, upper right
    img += light(0.58, 0.72, 0.52, 0.20, 0.15, MAGENTA, 0.30)        # a warm low band, soft
    img += light(0.50, 0.46, 0.30, 0.16, 0.0, np.array([230, 224, 255.0]), 0.16)   # a pale core
    # The violet and the cyan meet in a soft ribbon, the brand gradient.
    img += 0.45 * ribbon(x, y, 0.42, -0.22, 0.05, 1.0, 0.6, 0.06, -0.2, 1.2)[..., None] * (CYAN * 0.5 + VIOLET * 0.5 - img) * 0.5

    # Large, soft diamond outline on the right: the brand mark.
    dx, dy = (x - 0.76) * aspect, y - 0.42
    diamond = np.abs(dx) + np.abs(dy)
    outline = np.exp(-(((diamond - 0.17) / 0.0035) ** 2))
    img += outline[..., None] * (np.array([200, 190, 255.0]) - img) * 0.20

    # A faint diamond lattice, only where there is light.
    cell = height / 18.0
    u = (px + py) / cell
    v = (px - py) / cell
    edge = np.minimum(np.abs(u - np.round(u)), np.abs(v - np.round(v)))
    lines = np.clip(1.0 - edge * cell / 1.2, 0, 1)
    vignette = glow(x, y, 0.5, 0.42, 0.7, 0.55, 0.0)
    img += (lines * vignette * 4.0)[..., None]

    # Keep the bottom calm (the taskbar floats there), add grain against banding.
    img *= (0.86 + 0.14 * vignette)[..., None]
    img += rng.normal(0, 1.4, img.shape)
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    width = int(sys.argv[2]) if len(sys.argv) > 2 else 2560
    height = int(sys.argv[3]) if len(sys.argv) > 3 else 1440
    render(width, height).save(
        sys.argv[1], quality=90, optimize=True, progressive=True,
        comment=b"D.Ai OS wallpaper - (c) 2026 Diamond Rubinny (d.Ai) - Apache-2.0",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
