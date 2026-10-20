# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The accessibility audit itself: it must catch what it promises (docs/RAZ.md §13)."""
import os
import re
import unittest
from pathlib import Path

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor, QIcon, QPalette
    from PyQt6.QtWidgets import (QApplication, QLabel, QLineEdit, QPushButton, QSpinBox, QToolButton, QTreeWidget,
                                 QVBoxLayout, QWidget)
    HAVE_QT = True
except ImportError:  # the audit needs Qt; the rest of Raz does not
    if os.environ.get("DAI_REQUIRE_QT"):  # CI: a gate that skips is no gate
        raise
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class AuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])
        from dai_raz import a11y
        cls.a11y = a11y

    def window(self, *children, sheet=""):
        root = QWidget()
        root.setObjectName("Root")
        root.setStyleSheet(sheet or "QWidget { background: #0B1020; color: #E6E9F5; }")
        layout = QVBoxLayout(root)
        for child in children:
            layout.addWidget(child)
        self.addCleanup(root.deleteLater)
        return root

    def rules(self, root):
        return [(issue.rule, issue.widget.split(" < ")[0]) for issue in self.a11y.audit(root)]

    def test_a_clean_window_passes(self):
        label = QLabel("&Name")
        field = QLineEdit()
        label.setBuddy(field)  # the label names the field, as Orca reads it
        icon = QToolButton()
        icon.setIcon(QIcon.fromTheme("edit-copy"))
        icon.setAccessibleName("Copy")
        icon.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        count = QSpinBox()
        count.setAccessibleName("Copies")
        self.assertEqual(self.a11y.audit(self.window(label, field, QPushButton("Save"), icon, count)), [])
        self.assertEqual(self.rules(self.window(QSpinBox())), [("name", "QSpinBox")])

    def test_an_icon_button_without_a_name_fails(self):
        icon = QToolButton()
        icon.setIcon(QIcon.fromTheme("edit-copy"))
        icon.setToolTip("Copy")  # a tooltip is not a name
        icon.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.assertEqual(self.rules(self.window(icon)), [("name", "QToolButton")])

    def test_a_placeholder_is_not_a_label(self):
        field = QLineEdit()
        field.setPlaceholderText("Search")
        self.assertEqual(self.rules(self.window(field)), [("name", "QLineEdit")])

    def test_tab_must_reach_every_control(self):
        button = QPushButton("Delete")
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.assertEqual(self.rules(self.window(button)), [("keyboard", "QPushButton")])

    def test_hidden_and_disabled_controls_are_left_alone(self):
        hidden = QToolButton()
        hidden.setVisible(False)
        disabled = QToolButton()
        disabled.setEnabled(False)
        self.assertEqual(self.a11y.audit(self.window(hidden, disabled)), [])

    def test_low_contrast_text_fails(self):
        label = QLabel("Faint")
        label.setStyleSheet("color: #3A4060;")  # on #0B1020: about 1.9:1
        found = self.a11y.audit(self.window(label))
        self.assertEqual([(i.rule, i.widget.split(" < ")[0]) for i in found], [("contrast", "QLabel")])
        self.assertIn("needs 4.5:1", found[0].detail)

    def test_a_style_rule_for_a_sub_control_is_checked_too(self):
        tree = QTreeWidget()
        tree.setHeaderLabels(["App"])
        root = self.window(tree, sheet="QWidget { background: #0B1020; color: #E6E9F5; }"
                                       "QHeaderView::section { background: #141B33; color: #2A3563; }"
                                       "QPushButton:disabled { background: #141B33; color: #2A3563; }")
        self.assertEqual([i.widget for i in self.a11y.audit(root)], ["style QHeaderView::section"])

    def test_the_ratio_matches_wcag(self):
        black, white = QColor("#000000"), QColor("#FFFFFF")
        self.assertAlmostEqual(self.a11y.contrast(black, white), 21.0, places=1)
        self.assertAlmostEqual(self.a11y.contrast(QColor("#767676"), white), 4.54, places=2)
        half = QColor(255, 255, 255, 128)  # translucent text is blended first
        self.assertLess(self.a11y.contrast(half, black), self.a11y.contrast(white, black))
        self.assertEqual(self.a11y.qss_issues("QLabel { color: #4a4a4a !important; background: #000000; }")[0].rule,
                         "contrast")

    def test_what_is_painted_is_measured(self):
        # A list nobody styled is white; light window text on it must fail, however the palette reads.
        from PyQt6.QtWidgets import QListWidget
        listing = QListWidget()
        listing.setAccessibleName("Apps")
        listing.addItem("Clip")
        root = self.window(listing, sheet="QWidget { color: #E6E9F5; } QWidget#Root { background: #0B1020; }")
        found = self.a11y.audit(root)
        self.assertEqual([i.widget.split(" < ")[0] for i in found], ["QListWidget"])
        self.assertIn("needs 4.5:1", found[0].detail)

    def test_a_gradient_is_judged_by_its_weak_side(self):
        button = QPushButton("Next")
        button.setStyleSheet("QPushButton { color: #FFFFFF; border: none; padding: 8px 40px;"
                             " background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #5B3FD6, stop:1 #4C8DF0); }")
        self.assertEqual([i.rule for i in self.a11y.audit(self.window(button))], ["contrast"])
        button.setStyleSheet(button.styleSheet().replace("#4C8DF0", "#2F6BD0"))
        self.assertEqual(self.a11y.audit(self.window(button)), [])

    def test_letters_at_the_edge_of_a_narrow_field_are_not_its_background(self):
        count = QSpinBox()
        count.setMaximum(99999)
        count.setValue(88888)
        count.setFixedWidth(40)  # the digits fill the field to its edges
        count.setAccessibleName("Copies")
        root = self.window(count, sheet="QWidget { background: #0B1020; color: #E6E9F5; font-size: 14pt; }")
        self.assertEqual(self.a11y.audit(root), [])

    def test_large_text_and_symbols_need_three_to_one(self):
        big = QLabel("D.Ai")
        big.setStyleSheet("color: #7C5CFF; font-size: 30pt;")  # 4.4:1 on the window: fine for large text
        dot = QLabel("●")
        dot.setStyleSheet("color: #2A3563;")  # a step marker is a graphic: 3:1 (WCAG 1.4.11)
        found = self.a11y.audit(self.window(big, dot))
        self.assertEqual(len(found), 1)
        self.assertIn("(graphic)", found[0].detail)

    def test_keys_scroll_bars_and_qt_parts(self):
        from PyQt6.QtGui import QAction, QKeySequence
        from PyQt6.QtWidgets import QScrollBar
        keyed = QToolButton()
        action = QAction("New", keyed)
        action.setShortcut(QKeySequence("Ctrl+N"))
        keyed.setDefaultAction(action)
        keyed.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # a toolbar button: Ctrl+N reaches it
        bar = QScrollBar()
        bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.assertEqual(self.a11y.audit(self.window(keyed, bar)), [])

    def test_touch_targets_are_44_px(self):
        """docs/MOBILE.md A1: with touch on, a small button is a problem; the touch stylesheet makes it pass."""
        small = QPushButton("Go")
        small.setFixedSize(28, 22)
        big = QPushButton("Go on")
        big.setMinimumSize(44, 44)
        root = self.window(small, big)
        self.assertEqual(self.a11y.audit(root), [])  # the mouse profile does not mind
        found = self.a11y.audit(root, touch=True)
        self.assertEqual([(i.rule, i.widget.split(" < ")[0]) for i in found], [("target", "QPushButton")])
        self.assertIn("28x22 px", found[0].detail)
        grows = QPushButton("Grows")  # no size of its own: the touch sheet's min-height lifts it to 44
        root = self.window(grows)
        root.show()
        restore = self.a11y._with_touch(root)
        try:
            self.assertGreaterEqual(grows.height(), 44)
            self.assertEqual(self.a11y.audit(root, touch=True), [])
        finally:
            restore()
        self.assertLess(grows.height(), 44)

    def test_every_page_is_audited_and_turned_back(self):
        from PyQt6.QtWidgets import QStackedWidget
        stack = QStackedWidget()
        stack.addWidget(QPushButton("First"))
        stack.addWidget(QToolButton())  # on the page nobody sees first: no name
        root = self.window(stack)
        self.assertEqual([i.rule for i in self.a11y.audit(root)], ["name"])
        self.assertEqual(stack.currentIndex(), 0)

    def test_the_palette_is_what_is_checked_without_a_style_sheet(self):
        label = QLabel("Plain")
        palette = label.palette()
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#BBBBBB"))
        palette.setColor(QPalette.ColorRole.Window, QColor("#FFFFFF"))
        label.setPalette(palette)
        label.setAutoFillBackground(True)
        root = self.window(label, sheet="QPushButton { color: #000000; }")
        self.assertEqual([i.rule for i in self.a11y.audit(root)], ["contrast"])


class CoverageTests(unittest.TestCase):
    """The gate covers every window: an app with a window must audit it in its own tests (docs/RAZ.md §13)."""

    WINDOW = re.compile(r"^class \w+\((?:[\w.]*\.)?(?:QWidget|QDialog|QMainWindow|QFrame|QWizard|QPushButton|QToolButton)\b", re.M)
    NO_WINDOW = {"dai-privacy": "a tray icon and its menu, no window of its own"}

    def test_every_app_with_a_window_audits_it(self):
        apps = Path(__file__).resolve().parents[2]
        missing = []
        for app in sorted(p for p in apps.iterdir() if (p / "tests").is_dir()):
            sources = [f for f in app.glob("dai_*/*.py")]
            if not any(self.WINDOW.search(f.read_text(encoding="utf-8")) for f in sources):
                continue
            tests = " ".join(f.read_text(encoding="utf-8") for f in (app / "tests").glob("test_*.py"))
            if "assert_accessible(" not in tests and app.name not in self.NO_WINDOW:
                missing.append(app.name)
        self.assertEqual(missing, [], "these apps have windows that Raz's audit never sees")


if __name__ == "__main__":
    unittest.main()
