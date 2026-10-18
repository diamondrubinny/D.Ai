# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Raz's accessibility audit of a Qt window (docs/RAZ.md §13).

It works out the name a screen reader gets the way Qt's accessibility does
(PyQt6 has no QAccessible), so a button without a name fails here when Orca
would say only "button". A placeholder is not a name (WCAG 3.3.2). Three
rules, for every visible, enabled, interactive widget:

- name: the accessible name is not empty (text, accessibleName or a label's buddy);
- keyboard: Tab can reach it (focus policy), unless it lives inside a widget
  that is itself reached by Tab and handles the keys (a view's viewport);
- contrast: text against what is really painted behind it is at least 4.5:1
  (WCAG 2.1 AA, 1.4.3; 3:1 for large text and for symbols that are graphics,
  1.4.11), and the same for every style sheet rule that sets
  both a color and a background (sub-controls such as ::section never reach
  the palette).

Disabled widgets are exempt from contrast, as in WCAG. The audit only reads.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QColor, QFontInfo, QImage, QPalette
from PyQt6.QtWidgets import (QAbstractButton, QAbstractItemView, QAbstractSlider, QAbstractSpinBox, QComboBox,
                             QApplication, QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QScrollBar, QStackedWidget,
                             QTabBar, QTextEdit, QToolButton, QWidget)

AA_TEXT = 4.5
AA_LARGE = 3.0

INTERACTIVE = (QAbstractButton, QLineEdit, QComboBox, QAbstractSpinBox, QAbstractSlider, QTextEdit, QPlainTextEdit,
               QAbstractItemView, QTabBar)

# The palette role each kind of widget draws its text with (the background is measured, not looked up).
TEXT_ROLE = {
    QAbstractButton: QPalette.ColorRole.ButtonText,
    QComboBox: QPalette.ColorRole.ButtonText,
    QLineEdit: QPalette.ColorRole.Text,
    QTextEdit: QPalette.ColorRole.Text,
    QPlainTextEdit: QPalette.ColorRole.Text,
    QAbstractItemView: QPalette.ColorRole.Text,
    QLabel: QPalette.ColorRole.WindowText,
}


@dataclass(frozen=True)
class Issue:
    rule: str      # "name", "keyboard" or "contrast"
    widget: str    # class and objectName, or the path to it
    detail: str = ""

    def __str__(self) -> str:
        return f"{self.rule}: {self.widget}" + (f" ({self.detail})" if self.detail else "")


def luminance(color: QColor) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(color.red()) + 0.7152 * channel(color.green()) + 0.0722 * channel(color.blue())


def contrast(fg: QColor, bg: QColor) -> float:
    """WCAG contrast ratio; a translucent foreground is blended over the background first."""
    if fg.alpha() < 255:
        a = fg.alphaF()
        fg = QColor(round(fg.red() * a + bg.red() * (1 - a)), round(fg.green() * a + bg.green() * (1 - a)),
                    round(fg.blue() * a + bg.blue() * (1 - a)))
    hi, lo = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def describe(widget: QWidget) -> str:
    parts = []
    w: QWidget | None = widget
    while w is not None and len(parts) < 4:
        parts.append(type(w).__name__ + (f"#{w.objectName()}" if w.objectName() else ""))
        w = w.parentWidget()
    return " < ".join(parts)


def _strip_amp(text: str) -> str:
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&").strip()


def accessible_name(widget: QWidget, labels: dict[int, str] | None = None) -> str:
    """accessibleName, else the widget's own text, else the label whose buddy it is."""
    name = widget.accessibleName().strip()
    if not name and isinstance(widget, QAbstractButton):
        name = _strip_amp(widget.text())
        if not name and isinstance(widget, QToolButton) and widget.defaultAction() is not None:
            name = _strip_amp(widget.defaultAction().text())
    if not name and labels is not None:
        name = labels.get(id(widget), "")
    return name


def _buddies(root: QWidget) -> dict[int, str]:
    found = {}
    for label in root.findChildren(QLabel):
        buddy = label.buddy()
        if buddy is not None and label.text().strip():
            found[id(buddy)] = _strip_amp(label.text())
    return found


def _shown(widget: QWidget, root: QWidget) -> bool:
    """Shown on some page: hidden widgets are skipped, but every page of a stack or tabs is audited."""
    w: QWidget | None = widget
    while w is not None and w is not root:
        parent = w.parentWidget()
        if w.isHidden() and not isinstance(parent, QStackedWidget):
            return False
        w = parent
    return True


def _tab_reachable(widget: QWidget) -> bool:
    if isinstance(widget, QToolButton) and widget.defaultAction() is not None \
            and not widget.defaultAction().shortcut().isEmpty():
        return True  # a toolbar button with its own key (Ctrl+N): the keyboard reaches it directly
    if widget.focusPolicy() & Qt.FocusPolicy.TabFocus:
        return True
    proxy = widget.focusProxy()
    return proxy is not None and bool(proxy.focusPolicy() & Qt.FocusPolicy.TabFocus)


def _inside_reachable_view(widget: QWidget) -> bool:
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, (QAbstractItemView, QAbstractSpinBox, QComboBox)) and _tab_reachable(parent):
            return True
        parent = parent.parentWidget()
    return False


def _text_role(widget: QWidget):
    return next((role for kind, role in TEXT_ROLE.items() if isinstance(widget, kind)), None)


def threshold(widget: QWidget) -> tuple[float, str]:
    """4.5:1 for text; 3:1 for large text (WCAG: 18pt, or 14pt bold) and for symbols that are graphics (1.4.11)."""
    text = widget.text() if isinstance(widget, (QLabel, QAbstractButton)) else "x"
    if text and not any(unicodedata.category(ch)[0] in "LN" for ch in text):
        return AA_LARGE, "graphic"
    info = QFontInfo(widget.font())
    if info.pixelSize() >= 24 or (info.bold() and info.pixelSize() >= 19):
        return AA_LARGE, "large text"
    return AA_TEXT, ""


def _ring(image: QImage, rect: QRect, inset: int) -> list[QColor]:
    """What is painted just inside the widget's edge: its background, where text rarely reaches.

    Controls are inset past their border; a label's own edge is its background (line spacing). A gradient
    gives many colors, and all of them count.
    """
    rect = rect.intersected(image.rect())
    if rect.width() < 2 or rect.height() < 2:
        return []
    if rect.width() <= 4 * inset or rect.height() <= 4 * inset:
        inset = 0
    inner = rect.adjusted(inset, inset, -inset, -inset)
    xs = range(inner.left(), inner.right() + 1, max(1, inner.width() // 64))
    ys = range(inner.top(), inner.bottom() + 1, max(1, inner.height() // 16))
    points = [(x, inner.top()) for x in xs] + [(x, inner.bottom()) for x in xs]
    points += [(inner.left(), y) for y in ys] + [(inner.right(), y) for y in ys]
    return [QColor(image.pixel(x, y)) for x, y in points]


def _weak_background(fg: QColor, ring: list[QColor]) -> tuple[QColor, float]:
    """The background at the 20th percentile of contrast: a gradient's weak side counts, a stray letter does not."""
    scored = sorted((contrast(fg, color), color.name()) for color in ring)
    ratio, name = scored[len(scored) // 5]
    return QColor(name), ratio


def _check(widget: QWidget, root: QWidget, image: QImage, labels: dict[int, str], issues: list[Issue]) -> None:
    # A scroll bar is for the mouse (the keys scroll the view); qt_* parts (a toolbar's overflow arrow, a tab
    # bar's scroll buttons) belong to the widget that owns them.
    interactive = isinstance(widget, INTERACTIVE) and not isinstance(widget, QScrollBar) \
        and not widget.objectName().startswith("qt_")
    enabled = widget.isEnabled()
    if interactive and enabled and not _inside_reachable_view(widget):
        if not accessible_name(widget, labels) and not isinstance(widget, (QAbstractItemView, QTabBar)):
            issues.append(Issue("name", describe(widget)))
        if not _tab_reachable(widget) and not isinstance(widget, QTabBar):
            issues.append(Issue("keyboard", describe(widget), "Tab cannot reach it"))
    role = _text_role(widget)
    if role is None or not enabled or isinstance(widget, QHeaderView):  # sections: see qss_issues
        return
    if isinstance(widget, (QLabel, QAbstractButton)) and not widget.text().strip():
        return  # an image, an icon or a spacer: no text to read (an icon button needs only its name)
    scale = image.devicePixelRatio()
    origin = widget.mapTo(root, QPoint(0, 0))
    ring = _ring(image, QRect(round(origin.x() * scale), round(origin.y() * scale),
                              round(widget.width() * scale), round(widget.height() * scale)),
                 0 if isinstance(widget, QLabel) else round(3 * scale))
    if not ring:
        return
    fg = widget.palette().color(QPalette.ColorGroup.Active, role)
    bg, ratio = _weak_background(fg, ring)
    needed, kind = threshold(widget)
    if ratio < needed:
        issues.append(Issue("contrast", describe(widget),
                            f"{fg.name()} on {bg.name()} is {ratio:.2f}:1, needs {needed}:1" + (f" ({kind})" if kind else "")))


def _stacks_to(widget: QWidget, root: QWidget) -> list[tuple[QStackedWidget, QWidget]]:
    """The stacks (and tab pages) that must turn for widget to be on screen, outermost first."""
    chain = []
    child, parent = widget, widget.parentWidget()
    while parent is not None and child is not root:
        if isinstance(parent, QStackedWidget):
            chain.append((parent, child))
        child, parent = parent, parent.parentWidget()
    return chain[::-1]


def audit(root: QWidget) -> list[Issue]:
    """Every problem in root and its children, on every page; an empty list means the window passes.

    The window is shown (offscreen in CI) and painted once per page, so contrast is measured on what is
    really drawn, style sheets and all. Pages are turned back afterwards.
    """
    issues: list[Issue] = []
    was_visible = root.isVisible()
    if not was_visible:
        root.show()
    labels = _buddies(root)
    seen: set[int] = set()
    stacks = [stack for stack in root.findChildren(QStackedWidget) if _shown(stack, root)]
    original = {id(stack): stack.currentIndex() for stack in stacks}

    def paint_and_check() -> None:
        QApplication.processEvents()
        image = root.grab().toImage()
        for widget in [root, *root.findChildren(QWidget)]:
            if id(widget) in seen or not widget.isVisible() or not _shown(widget, root):
                continue
            seen.add(id(widget))
            widget.ensurePolished()
            _check(widget, root, image, labels, issues)

    paint_and_check()
    for stack in stacks:
        for index in range(stack.count()):
            for outer, page in _stacks_to(stack.widget(index), root):
                outer.setCurrentWidget(page)
            paint_and_check()
    for stack in stacks:
        stack.setCurrentIndex(original[id(stack)])
    if not was_visible:
        root.hide()

    sheets = {widget.styleSheet() for widget in [root, *root.findChildren(QWidget)]}
    app = QApplication.instance()
    if app is not None:
        sheets.add(app.styleSheet())
    for sheet in sorted(sheet for sheet in sheets if sheet):
        issues.extend(qss_issues(sheet))
    return issues


_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_COLOR = re.compile(r"(?:^|;)\s*color\s*:\s*([^;]+)")
_BACKGROUND = re.compile(r"(?:^|;)\s*background(?:-color)?\s*:\s*([^;]+)")


def _qcolor(value: str) -> QColor | None:
    value = re.sub(r"\s*!important\s*$", "", value.strip())
    match = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)", value)
    if match:
        r, g, b, a = match.groups()
        alpha = float(a) if a is not None else 1.0
        return QColor(int(r), int(g), int(b), round(alpha * 255 if alpha <= 1 else alpha))
    color = QColor(value)
    return color if color.isValid() and value.startswith("#") else None


def qss_issues(sheet: str) -> list[Issue]:
    """Rules that set both a text color and a solid background, below AA."""
    issues = []
    sheet = re.sub(r"/\*.*?\*/", "", sheet, flags=re.S)
    for selector, body in _RULE.findall(sheet):
        selector = " ".join(selector.split())
        if ":disabled" in selector:
            continue  # disabled controls are exempt (WCAG 1.4.3)
        fg_match, bg_match = _COLOR.search(body), _BACKGROUND.search(body)
        if not fg_match or not bg_match:
            continue
        fg, bg = _qcolor(fg_match.group(1)), _qcolor(bg_match.group(1))
        if fg is None or bg is None or bg.alpha() < 255:
            continue  # a gradient or a see-through background: the palette check covers what shows through
        ratio = contrast(fg, bg)
        if ratio < AA_TEXT:
            issues.append(Issue("contrast", f"style {selector}",
                                f"{fg.name()} on {bg.name()} is {ratio:.2f}:1, needs {AA_TEXT}:1"))
    return issues


def assert_accessible(case, window: QWidget) -> None:
    """For the apps' own tests: fail with every problem listed, in one message."""
    issues = audit(window)
    case.assertEqual([str(issue) for issue in issues], [], f"{type(window).__name__} has accessibility problems")
