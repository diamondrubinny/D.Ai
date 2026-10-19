#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Draws the pictures of the way to the desktop (docs/V2.md D2) from the diamond's SVG and the night wallpaper.

  QT_QPA_PLATFORM=offscreen python3 build/scripts/make-boot-art.py

Writes, under build/live-build/common/includes.chroot_after_packages:
  usr/share/dai/branding/boot/syslinux-splash.png   640x480, the USB boot menu on BIOS computers
  usr/share/dai/branding/boot/grub-splash.png       1920x1080, the boot menu on UEFI and on the installed system
  usr/share/plymouth/themes/dai/watermark.png       the diamond and the name, while the system loads
  usr/share/plymouth/themes/dai/throbber-NNNN.png   the loading animation

The PNGs are committed, so building the image needs no extra tools; run this again after changing the
diamond or the wallpaper. Needs PyQt6 with Qt's SVG image plugin.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QBrush, QColor, QFont, QGuiApplication, QImage, QImageReader, QLinearGradient, QPainter,
                         QRadialGradient)

ROOT = Path(__file__).resolve().parents[2]
CHROOT = ROOT / "build/live-build/common/includes.chroot_after_packages"
LOGO = CHROOT / "usr/share/dai/branding/dai-logo.svg"
WALLPAPER = CHROOT / "usr/share/dai/branding/wallpaper-night.jpg"
BOOT = CHROOT / "usr/share/dai/branding/boot"
PLYMOUTH = CHROOT / "usr/share/plymouth/themes/dai"

BG_900, DEEP = QColor("#0B1020"), QColor("#10173A")
TEXT, MUTED, ACCENT, ACCENT_2 = QColor("#E6E9F5"), QColor("#A9B1D3"), QColor("#7C5CFF"), QColor("#22D3EE")
FRAMES = 24


def logo(size: int) -> QImage:
    reader = QImageReader(str(LOGO))
    reader.setScaledSize(reader.size().scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio))
    image = reader.read()
    if image.isNull():
        raise SystemExit(f"cannot draw {LOGO}: {reader.errorString()}")
    return image


def font(pixels: int, bold: bool = True) -> QFont:
    face = QFont("Noto Sans")
    face.setPixelSize(pixels)
    face.setWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
    return face


def background(width: int, height: int, darken: float) -> QImage:
    """The night wallpaper, cropped to fill, with a dark veil so menu text stays readable."""
    image = QImage(width, height, QImage.Format.Format_RGB32)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    wallpaper = QImage(str(WALLPAPER))
    scaled = wallpaper.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                              Qt.TransformationMode.SmoothTransformation)
    painter.drawImage(QPointF((width - scaled.width()) / 2, (height - scaled.height()) / 2), scaled)
    veil = QLinearGradient(0, 0, 0, height)
    veil.setColorAt(0, QColor(11, 16, 32, int(255 * darken * 0.7)))
    veil.setColorAt(0.45, QColor(11, 16, 32, int(255 * darken)))
    veil.setColorAt(1, QColor(11, 16, 32, int(255 * min(1.0, darken + 0.1))))
    painter.fillRect(0, 0, width, height, QBrush(veil))
    painter.end()
    return image


def brand(painter: QPainter, center_x: float, top: float, size: int, title_px: int, line: str = "") -> None:
    """The diamond with its glow, "D.Ai OS" under it, and an optional line under that."""
    glow = QRadialGradient(QPointF(center_x, top + size / 2), size * 1.1)
    glow.setColorAt(0, QColor(124, 92, 255, 110))
    glow.setColorAt(0.6, QColor(34, 211, 238, 28))
    glow.setColorAt(1, QColor(0, 0, 0, 0))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(glow))
    painter.drawEllipse(QPointF(center_x, top + size / 2), size * 1.1, size * 1.1)
    painter.drawImage(QPointF(center_x - size / 2, top), logo(size))
    painter.setPen(TEXT)
    painter.setFont(font(title_px))
    title = QRectF(center_x - 600, top + size + title_px * 0.35, 1200, title_px * 1.4)
    painter.drawText(title, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, "D.Ai OS")
    if line:
        painter.setPen(MUTED)
        painter.setFont(font(max(11, title_px // 2), bold=False))
        painter.drawText(QRectF(center_x - 600, title.bottom(), 1200, title_px), Qt.AlignmentFlag.AlignHCenter, line)


def splash(width: int, height: int, logo_top: float, logo_size: int, title_px: int) -> QImage:
    image = background(width, height, darken=0.72)
    painter = QPainter(image)
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
                           | QPainter.RenderHint.SmoothPixmapTransform)
    brand(painter, width / 2, logo_top, logo_size, title_px, "Fast · Private · Secure · Open source")
    painter.end()
    return image


def watermark() -> QImage:
    image = QImage(440, 340, QImage.Format.Format_ARGB32_Premultiplied)  # room for the whole glow
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
                           | QPainter.RenderHint.SmoothPixmapTransform)
    brand(painter, 220, 76, 120, 36)
    painter.end()
    return image


def throbber(frame: int) -> QImage:
    """Eight small diamonds in a ring; the bright one moves around, purple to turquoise."""
    size, dots = 56, 8
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    head = frame / FRAMES * dots
    for index in range(dots):
        angle = 2 * math.pi * index / dots - math.pi / 2
        x, y = size / 2 + 20 * math.cos(angle), size / 2 + 20 * math.sin(angle)
        behind = (head - index) % dots
        strength = max(0.18, 1 - behind / 4.5)
        color = QColor(ACCENT).toRgb()
        mix = index / (dots - 1)
        color.setRgb(int(ACCENT.red() * (1 - mix) + ACCENT_2.red() * mix),
                     int(ACCENT.green() * (1 - mix) + ACCENT_2.green() * mix),
                     int(ACCENT.blue() * (1 - mix) + ACCENT_2.blue() * mix), int(255 * strength))
        r = 3.2 + 1.8 * strength
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPolygon([QPointF(x, y - r), QPointF(x + r, y), QPointF(x, y + r), QPointF(x - r, y)])
    painter.end()
    return image


def main() -> int:
    app = QGuiApplication(sys.argv)  # fonts need it alive while drawing
    BOOT.mkdir(parents=True, exist_ok=True)
    PLYMOUTH.mkdir(parents=True, exist_ok=True)
    outputs = {
        BOOT / "syslinux-splash.png": splash(640, 480, 26, 88, 30),       # the menu starts at row 12 (y=192)
        BOOT / "grub-splash.png": splash(1920, 1080, 120, 230, 72),       # the menu starts at 52%
        PLYMOUTH / "watermark.png": watermark(),
    }
    for frame in range(FRAMES):
        outputs[PLYMOUTH / f"throbber-{frame + 1:04d}.png"] = throbber(frame)
    for path, image in outputs.items():
        if not image.save(str(path), "PNG"):
            raise SystemExit(f"cannot write {path}")
    print(f"wrote {len(outputs)} images")
    app.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
