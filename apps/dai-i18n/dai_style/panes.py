# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Responsive pieces for D.Ai windows (docs/MOBILE.md A2).

Panes is a QSplitter that lays its panes side by side when it is wide and one above the other when it is narrower
than NARROW pixels, so the same window works on a desktop and on a phone-sized screen. touch_scrolling() lets a
finger scroll every list and page of a window with inertia. WrapRow is a toolbar row that wraps when narrow.
"""

from __future__ import annotations

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtWidgets import (QAbstractScrollArea, QLayout, QLayoutItem, QScroller, QSizePolicy, QSpacerItem, QSplitter,
                             QWidget)

NARROW = 700  # px: under this, panes stack (docs/MOBILE.md A2)


class Panes(QSplitter):
    """A splitter that stacks its panes vertically when it is narrower than `narrow` pixels."""

    def __init__(self, parent: QWidget | None = None, narrow: int = NARROW) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.narrow = narrow
        self._sizes: dict[Qt.Orientation, list[int]] = {}

    def setSizes(self, sizes) -> None:  # noqa: N802 (Qt's name)
        self._sizes[self.orientation()] = list(sizes)
        super().setSizes(sizes)

    def stacked(self) -> bool:
        return self.orientation() == Qt.Orientation.Vertical

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt's name)
        super().resizeEvent(event)
        wanted = Qt.Orientation.Vertical if event.size().width() < self.narrow else Qt.Orientation.Horizontal
        if wanted != self.orientation():
            self._sizes[self.orientation()] = self.sizes()
            self.setOrientation(wanted)
            remembered = self._sizes.get(wanted)
            if remembered and len(remembered) == self.count():
                super().setSizes(remembered)


def touch_scrolling(root: QWidget, on: bool | None = None) -> int:
    """A finger scrolls every scroll area under root (lists, trees, text, pages); returns how many got it.

    on=None asks dai_style.touch(); the gesture is Qt's touch gesture, so the mouse behaves as before.
    """
    if on is None:
        from dai_style import touch
        on = touch()
    if not on:
        return 0
    count = 0
    for area in root.findChildren(QAbstractScrollArea):
        QScroller.grabGesture(area.viewport(), QScroller.ScrollerGestureType.TouchGesture)
        count += 1
    return count


def fit_width(wanted: int, margin: int = 24) -> int:
    """`wanted` pixels, or the screen's available width minus a margin when the screen is narrower (a phone)."""
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    if screen is None:
        return wanted
    return max(240, min(wanted, screen.availableGeometry().width() - margin))


class WrapRow(QLayout):
    """A row of widgets that wraps onto more rows when the window is narrow (Qt's flow layout, for toolbars).

    Items keep their order; in a right-to-left window the row runs right to left like every other layout.
    """

    def __init__(self, parent: QWidget | None = None, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 (Qt's name)
        self._items.append(item)

    def addSpacing(self, size: int) -> None:  # noqa: N802 (QBoxLayout's name, so callers need no change)
        self.addItem(QSpacerItem(size, 1, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum))

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._arrange(QRect(0, 0, width, 0), dry=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._arrange(rect, dry=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        left, top, right, bottom = self.getContentsMargins()
        return size + QSize(left + right, top + bottom)

    def _arrange(self, rect: QRect, dry: bool) -> int:
        left, top, right, bottom = self.getContentsMargins()
        inner = rect.adjusted(left, top, -right, -bottom)
        x, y, row_height = inner.x(), inner.y(), 0
        spacing = self.spacing()
        rtl = self.parentWidget() is not None and self.parentWidget().isRightToLeft()
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > inner.right() + 1 and row_height > 0:
                x, y, row_height = inner.x(), y + row_height + spacing, 0
            if not dry:
                place = QRect(x, y, hint.width(), hint.height())
                if rtl:
                    place.moveLeft(inner.right() + 1 - (x - inner.x()) - hint.width())
                item.setGeometry(place)
            x += hint.width() + spacing
            row_height = max(row_height, hint.height())
        return y + row_height - rect.y() + bottom
