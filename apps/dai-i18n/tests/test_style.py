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


class TouchTests(unittest.TestCase):
    """docs/MOBILE.md A1: the touch profile is chosen from the hardware, the file or the environment."""

    def fake_input(self, root: Path, properties: str) -> Path:
        device = root / "event3" / "device"
        device.mkdir(parents=True)
        (device / "properties").write_text(properties)
        return root

    def test_a_touch_screen_is_the_direct_property_bit(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(dai_style.touchscreen_present(Path(tmp) / "missing"))
            self.assertFalse(dai_style.touchscreen_present(self.fake_input(Path(tmp) / "mouse", "0\n")))
            self.assertFalse(dai_style.touchscreen_present(self.fake_input(Path(tmp) / "touchpad", "5\n")))  # pointer+buttonpad
            self.assertTrue(dai_style.touchscreen_present(self.fake_input(Path(tmp) / "screen", "2\n")))
            self.assertTrue(dai_style.touchscreen_present(self.fake_input(Path(tmp) / "two", "0 2\n")))  # two words on big kernels
            self.assertFalse(dai_style.touchscreen_present(self.fake_input(Path(tmp) / "junk", "zz\n")))

    def test_the_choice_wins_over_the_hardware(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, screen = Path(tmp), self.fake_input(Path(tmp) / "screen", "2\n")
            none = Path(tmp) / "nothing"
            self.assertEqual(dai_style.touch_mode({}, home), "auto")
            self.assertTrue(dai_style.touch({}, home, screen))
            self.assertFalse(dai_style.touch({}, home, none))
            dai_style.save_touch("off", home)
            self.assertEqual(dai_style.touch_mode({}, home), "off")
            self.assertFalse(dai_style.touch({}, home, screen))
            dai_style.save_touch("on", home)
            self.assertTrue(dai_style.touch({}, home, none))
            self.assertFalse(dai_style.touch({"DAI_TOUCH": "0"}, home, screen))
            self.assertTrue(dai_style.touch({"DAI_TOUCH": "1"}, home, none))
            self.assertEqual(dai_style.touch_mode({"DAI_TOUCH": "maybe"}, home), "auto")
            with self.assertRaises(ValueError):
                dai_style.save_touch("sometimes", home)

    def test_the_touch_sheet_is_appended_only_when_on(self):
        self.assertEqual(dai_style.with_touch("a {}", on=False), "a {}")
        self.assertTrue(dai_style.with_touch("a {}", on=True).startswith("a {}\n"))
        self.assertIn(f"min-height: {dai_style.TOUCH_TARGET}px", dai_style.TOUCH_SHEET)
        self.assertGreaterEqual(dai_style.TOUCH_TARGET, 44)  # WCAG 2.5.5
        self.assertNotIn("#", dai_style.TOUCH_SHEET)  # no colors: themed() has nothing to miss


try:
    from PyQt6.QtWidgets import QApplication, QLabel, QListWidget, QWidget
    HAVE_QT = True
except ImportError:  # the design system's Qt pieces need PyQt6; the palette does not
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class PanesTests(unittest.TestCase):
    """docs/MOBILE.md A2: panes stack under 700 px and come back side by side, keeping their sizes."""

    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def test_panes_stack_when_narrow(self):
        from PyQt6.QtCore import Qt
        from dai_style.panes import Panes, touch_scrolling
        panes = Panes()
        panes.addWidget(QLabel("left"))
        panes.addWidget(QListWidget())
        panes.show()
        panes.resize(1000, 500)
        panes.setSizes([300, 700])
        self.app.processEvents()
        self.assertFalse(panes.stacked())
        panes.resize(600, 800)
        self.app.processEvents()
        self.assertTrue(panes.stacked())
        self.assertEqual(panes.orientation(), Qt.Orientation.Vertical)
        panes.resize(1000, 500)
        self.app.processEvents()
        self.assertFalse(panes.stacked())
        self.assertLess(abs(panes.sizes()[0] - 300) + abs(panes.sizes()[1] - 700), 8)  # the handle takes a few px
        self.assertEqual(touch_scrolling(panes, on=False), 0)
        self.assertEqual(touch_scrolling(panes, on=True), 1)  # the list's viewport
        panes.close()


if __name__ == "__main__":
    unittest.main()
