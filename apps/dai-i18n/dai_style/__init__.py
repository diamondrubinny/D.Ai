# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""One design system for every D.Ai window (docs/V2.md D1): the palette of each theme, and themed().

Every app writes its stylesheet once, in the colors of "D.Ai Night" (docs/DESIGN.md §2). themed() turns any
stylesheet, or any rich text, into the theme the person chose: every Night color, as #RRGGBB or rgb()/rgba(), is
replaced by the same role's color in the other theme. So a new app gets all three themes by writing Night.

  night     D.Ai Night: the default (dark)
  day       D.Ai Day: light, for daylight
  contrast  high contrast: black, white and strong accents, for low vision

The choice is ~/.config/dai/theme (one word; D.Ai Tune "light theme" writes it), or DAI_THEME for one app.
Raz's accessibility audit checks every window in all three themes (dai_raz.a11y.assert_accessible).

Touch (docs/MOBILE.md A1): on a touch screen every control is at least 44 px tall and the text a little bigger.
touch() decides from ~/.config/dai/touch (on, off or auto; D.Ai Tune "touch mode" writes it) or DAI_TOUCH for one
app; auto means "a touch screen is attached" (the kernel's INPUT_PROP_DIRECT bit on an input device).
with_touch(sheet) appends the touch rules to a stylesheet when touch is on.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

__version__ = "0.1.0"
__author__ = "Diamond Rubinny (d.Ai)"

THEMES = ("night", "day", "contrast")
ROLES = ("bg_900", "bg_800", "surface", "border", "text", "muted", "accent", "accent_strong", "accent_2",
         "accent_soft", "ok", "warn", "danger", "deep", "code_bg", "code_text", "disabled", "dot", "panel")

# Every role in every theme. Text roles keep AA contrast (4.5:1) on bg_900, bg_800 and surface of their theme;
# accent is decorative only (borders, gradients), never text. Checked by tests/test_style.py.
PALETTES: dict[str, dict[str, str]] = {
    "night": {
        "bg_900": "#0B1020", "bg_800": "#141B33", "surface": "#1C2547", "border": "#2A3563", "text": "#E6E9F5",
        "muted": "#9AA3C7", "accent": "#7C5CFF", "accent_strong": "#5B3FD6", "accent_2": "#22D3EE",
        "accent_soft": "#B8A6FF", "ok": "#34D399", "warn": "#FBBF24", "danger": "#F87171", "deep": "#10173A",
        "code_bg": "#070B17", "code_text": "#CFE8FF", "disabled": "#5D668C", "dot": "#66709A", "panel": "#2F6BD0",
    },
    "day": {
        "bg_900": "#F6F7FB", "bg_800": "#FFFFFF", "surface": "#ECEEF7", "border": "#B9BFD9", "text": "#141B33",
        "muted": "#4A5375", "accent": "#7C5CFF", "accent_strong": "#5B3FD6", "accent_2": "#0B6E84",
        "accent_soft": "#4A2EBC", "ok": "#06703F", "warn": "#8A4B00", "danger": "#B42318", "deep": "#E9EDFA",
        "code_bg": "#F1F3FA", "code_text": "#1D3557", "disabled": "#6E7594", "dot": "#7A82A3", "panel": "#2F6BD0",
    },
    "contrast": {
        "bg_900": "#000000", "bg_800": "#000000", "surface": "#0D0D0D", "border": "#FFFFFF", "text": "#FFFFFF",
        "muted": "#E6E6E6", "accent": "#FFFFFF", "accent_strong": "#4B2FC4", "accent_2": "#FFFF00",
        "accent_soft": "#FFFF00", "ok": "#66FF99", "warn": "#FFD24D", "danger": "#FF8080", "deep": "#000000",
        "code_bg": "#000000", "code_text": "#FFFFFF", "disabled": "#BFBFBF", "dot": "#BFBFBF", "panel": "#4B2FC4",
    },
}
TOUCH_MODES = ("auto", "on", "off")
TOUCH_TARGET = 44  # px: WCAG 2.5.5 target size, Apple's and Android's guidance alike
# Appended to a window's stylesheet when touch is on: bigger targets, bigger indicators, bigger scroll bars, a
# touch of extra text size. Later rules win in QSS, so an app's own selectors with an objectName still apply.
TOUCH_SHEET = f"""
QWidget {{ font-size: 12pt; }}
QPushButton, QToolButton, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox, QRadioButton, QSlider {{
    min-height: {TOUCH_TARGET}px; min-width: {TOUCH_TARGET}px; }}
QTabBar::tab {{ min-height: {TOUCH_TARGET}px; padding: 8px 18px; }}
QAbstractItemView::item {{ min-height: {TOUCH_TARGET}px; padding: 6px 10px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 28px; height: 28px; }}
QScrollBar:vertical {{ width: 20px; }}
QScrollBar:horizontal {{ height: 20px; }}
QSlider::handle:horizontal {{ width: 32px; margin: -10px 0; }}
QSlider::groove:horizontal {{ height: 12px; }}
"""
_INPUT_PROP_DIRECT = 1 << 1  # linux/input-event-codes.h: a touch screen or a drawing tablet
_HEX = re.compile(r"#([0-9A-Fa-f]{6})\b")
_RGB = re.compile(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(,\s*[\d.]+\s*)?\)")


def current(environ: dict[str, str] | None = None, home: Path | None = None) -> str:
    """The theme this person chose; "night" when nothing (or something unknown) is set."""
    env = os.environ if environ is None else environ
    wanted = env.get("DAI_THEME", "").strip().lower()
    if not wanted:
        try:
            config = Path(env.get("XDG_CONFIG_HOME") or (home or Path.home()) / ".config")
            wanted = (config / "dai" / "theme").read_text(encoding="ascii").strip().lower()
        except (OSError, UnicodeError):
            wanted = ""
    return wanted if wanted in THEMES else "night"


def color(role: str, theme: str | None = None) -> str:
    return PALETTES[theme or current()][role]


def rgba(role: str, alpha: float, theme: str | None = None) -> str:
    """A see-through role color for QSS, e.g. rgba("accent", 0.25) -> "rgba(124, 92, 255, 0.25)"."""
    r, g, b = _rgb(color(role, theme))
    return f"rgba({r}, {g}, {b}, {alpha})"


def _rgb(value: str) -> tuple[int, int, int]:
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def _mapping(source: str, target: str) -> dict[tuple[int, int, int], str]:
    return {_rgb(PALETTES[source][role]): PALETTES[target][role] for role in ROLES}


def themed(text: str, theme: str | None = None, source: str = "night") -> str:
    """A stylesheet or rich text written in `source` colors, in `theme` (default: the person's choice)."""
    theme = theme or current()
    if theme == source:
        return text
    mapping = _mapping(source, theme)

    def hex_colour(match: re.Match) -> str:
        new = mapping.get(_rgb("#" + match.group(1)))
        return new if new else match.group(0)

    def rgb_colour(match: re.Match) -> str:
        new = mapping.get((int(match.group(1)), int(match.group(2)), int(match.group(3))))
        if not new:
            return match.group(0)
        r, g, b = _rgb(new)
        return f"rgba({r}, {g}, {b}{match.group(4)})" if match.group(4) else f"rgb({r}, {g}, {b})"

    return _RGB.sub(rgb_colour, _HEX.sub(hex_colour, text))


def save(theme: str, home: Path | None = None) -> Path:
    """Write the person's choice (D.Ai Tune's appearance.theme does this, with undo)."""
    if theme not in THEMES:
        raise ValueError(f"unknown theme: {theme}")
    path = (home or Path.home()) / ".config" / "dai" / "theme"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(theme + "\n", encoding="ascii")
    return path


def touchscreen_present(sys_input: Path = Path("/sys/class/input")) -> bool:
    """Whether the kernel knows a direct-touch input device (a touch screen; a pen tablet counts too)."""
    try:
        entries = list(sys_input.iterdir())
    except OSError:
        return False
    for entry in entries:
        try:
            words = (entry / "device" / "properties").read_text(encoding="ascii").split()
            if words and int(words[-1], 16) & _INPUT_PROP_DIRECT:
                return True
        except (OSError, ValueError, UnicodeError):
            continue
    return False


def touch_mode(environ: dict[str, str] | None = None, home: Path | None = None) -> str:
    """What the person asked for: "on", "off" or "auto" (the default, and anything unknown)."""
    env = os.environ if environ is None else environ
    wanted = env.get("DAI_TOUCH", "").strip().lower()
    wanted = {"1": "on", "true": "on", "yes": "on", "0": "off", "false": "off", "no": "off"}.get(wanted, wanted)
    if not wanted:
        try:
            config = Path(env.get("XDG_CONFIG_HOME") or (home or Path.home()) / ".config")
            wanted = (config / "dai" / "touch").read_text(encoding="ascii").strip().lower()
        except (OSError, UnicodeError):
            wanted = ""
    return wanted if wanted in TOUCH_MODES else "auto"


def touch(environ: dict[str, str] | None = None, home: Path | None = None, sys_input: Path | None = None) -> bool:
    """Whether this window should be laid out for fingers."""
    mode = touch_mode(environ, home)
    if mode != "auto":
        return mode == "on"
    return touchscreen_present(sys_input) if sys_input is not None else touchscreen_present()


UI_FONTS = ("Inter", "Noto Sans")
UI_POINT_SIZE = {"Inter": 10.5, "Noto Sans": 11}


def app_font(families: list[str] | tuple[str, ...] | None = None):
    """The interface font for a QApplication (docs/LOOK.md): Inter when installed, Noto Sans otherwise, or None."""
    from PyQt6.QtGui import QFont, QFontDatabase

    installed = set(families if families is not None else QFontDatabase.families())
    for family in UI_FONTS:
        if family in installed:
            font = QFont(family)
            font.setPointSizeF(UI_POINT_SIZE[family])
            return font
    return None


def controls(theme: str | None = None) -> str:
    """One look for check boxes and radio buttons in every D.Ai window (docs/POLISH.md §2).

    A checked box is an accent tint with an accent border and a check mark (an image, so no text color is
    involved): Raz reads the label's text against the tint in every theme. A chosen radio is an accent ring.
    """
    theme = theme or current()
    dark = theme == "day"
    mark = Path(__file__).parent / ("check-dark.png" if dark else "check-light.png")
    dot = Path(__file__).parent / ("dot-dark.png" if dark else "dot-light.png")
    accent, accent_2, border, bg = color("accent", theme), color("accent_2", theme), color("border", theme), color("bg_900", theme)
    tint = rgba("accent", 0.28, theme)
    return f"""
QCheckBox {{ spacing: 10px; }}
QCheckBox::indicator {{ width: 22px; height: 22px; border-radius: 6px; border: 1px solid {border}; background: {bg}; }}
QCheckBox::indicator:hover {{ border: 1px solid {accent}; }}
QCheckBox::indicator:checked {{ background: {tint}; border: 1px solid {accent}; image: url({mark.as_posix()}); }}
QCheckBox::indicator:disabled {{ border: 1px solid {border}; background: {rgba("bg_800", 0.6, theme)}; }}
QCheckBox:focus {{ color: {accent_2}; }}
QRadioButton {{ spacing: 10px; }}
QRadioButton::indicator {{ width: 22px; height: 22px; border-radius: 11px; border: 1px solid {border}; background: {bg}; }}
QRadioButton::indicator:hover {{ border: 1px solid {accent}; }}
QRadioButton::indicator:checked {{ background: {tint}; border: 1px solid {accent}; image: url({dot.as_posix()}); }}
QRadioButton:focus {{ color: {accent_2}; }}
"""


def with_touch(sheet: str, on: bool | None = None) -> str:
    """A stylesheet with the touch rules appended when touch is on (default: touch())."""
    return sheet + TOUCH_SHEET if (touch() if on is None else on) else sheet


def save_touch(mode: str, home: Path | None = None) -> Path:
    """Write the person's choice (D.Ai Tune's appearance.touch does this, with undo)."""
    if mode not in TOUCH_MODES:
        raise ValueError(f"unknown touch mode: {mode}")
    path = (home or Path.home()) / ".config" / "dai" / "touch"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(mode + "\n", encoding="ascii")
    return path
