# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""D.Ai's design system (docs/V2.md D1): every theme keeps AA contrast, and themed() maps every Night color."""
import tempfile
import unittest
from pathlib import Path

import dai_style
from dai_style import PALETTES, ROLES, themed

TEXT_ROLES = ("text", "muted", "accent_2", "accent_soft", "ok", "warn", "danger")
BACKGROUNDS = ("bg_900", "bg_800", "surface")


def luminance(value: str) -> float:
    channels = []
    for i in (1, 3, 5):
        c = int(value[i:i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class PaletteTests(unittest.TestCase):
    def test_every_theme_has_every_role(self):
        for theme, palette in PALETTES.items():
            self.assertEqual(set(palette), set(ROLES), theme)

    def test_text_keeps_aa_contrast_in_every_theme(self):
        for theme, p in PALETTES.items():
            for role in TEXT_ROLES:
                for background in BACKGROUNDS:
                    with self.subTest(theme=theme, role=role, on=background):
                        self.assertGreaterEqual(contrast(p[role], p[background]), 4.5)
            with self.subTest(theme=theme, role="white on accent_strong"):
                self.assertGreaterEqual(contrast("#FFFFFF", p["accent_strong"]), 4.5)
            with self.subTest(theme=theme, role="focus ring"):
                self.assertGreaterEqual(contrast(p["accent_2"], p["bg_900"]), 3.0)  # WCAG 1.4.11

    def test_night_colours_are_unique_so_the_mapping_is_exact(self):
        night = [PALETTES["night"][role].upper() for role in ROLES]
        self.assertEqual(len(night), len(set(night)))


class ThemedTests(unittest.TestCase):
    def test_hex_and_rgba_and_unknown_colours(self):
        qss = "a { color: #E6E9F5; background: rgba(20, 27, 51, 0.92); border: 1px solid rgb(42, 53, 99) } b { color: #123456 }"
        self.assertEqual(themed(qss, "day"), "a { color: #141B33; background: rgba(255, 255, 255, 0.92); "
                                             "border: 1px solid rgb(185, 191, 217) } b { color: #123456 }")
        self.assertEqual(themed(qss, "night"), qss)
        self.assertIn("#FFFFFF", themed("<span style='color:#E6E9F5'>x</span>", "contrast"))  # rich text too

    def test_the_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.assertEqual(dai_style.current({}, home), "night")
            dai_style.save("day", home)
            self.assertEqual(dai_style.current({"XDG_CONFIG_HOME": str(home / ".config")}, home), "day")
            self.assertEqual(dai_style.current({"DAI_THEME": "contrast"}, home), "contrast")
            self.assertEqual(dai_style.current({"DAI_THEME": "pink"}, home), "night")
            with self.assertRaises(ValueError):
                dai_style.save("pink", home)


if __name__ == "__main__":
    unittest.main()
