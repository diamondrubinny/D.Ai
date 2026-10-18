# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The history window (Super+V): search, Enter pastes, Shift+Enter copies only."""

from __future__ import annotations

import re
import subprocess
import sys
import time
from typing import Callable

from PyQt6.QtCore import QRect, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QKeyEvent, QPainter
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QStyle,
    QStyledItemDelegate, QStyleOptionViewItem, QVBoxLayout, QWidget,
)

from dai_i18n import qt_direction

from . import __author__, __version__
from .store import History, Item
from .text import age, lang, preview, t

APP_ID = "dai-clip"
TEXT_ROLE = Qt.ItemDataRole.UserRole + 1
META_ROLE = Qt.ItemDataRole.UserRole + 2
PASTE_DELAY_MS = 180  # let the compositor give focus back to the previous window

# Design tokens (docs/DESIGN.md §2), as in D.Ai Command.
BG, SURFACE, BORDER, TEXT, MUTED = "#0B1020", "#1C2547", "#2A3563", "#E6E9F5", "#9AA3C7"
ACCENT, ACCENT_STRONG, ACCENT_2 = "#7C5CFF", "#5B3FD6", "#22D3EE"
STYLE = f"""
#Card {{ background: {BG}; border: 1px solid {BORDER}; border-top: 2px solid {ACCENT}; border-radius: 14px; }}
#Title {{ color: {TEXT}; font-size: 13pt; font-weight: 700; }}
#Search {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 10px; padding: 8px 12px;
    font-size: 12pt; selection-background-color: {ACCENT_STRONG}; }}
#Search:focus {{ border: 2px solid {ACCENT_2}; }}
#Items {{ background: transparent; border: none; color: {TEXT}; outline: none; font-size: 11pt; }}
#Hint, #Empty {{ color: {MUTED}; font-size: 9pt; }}
#Empty {{ font-size: 11pt; padding: 24px; }}
QPushButton {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 8px; padding: 5px 12px; }}
QPushButton:hover {{ border: 1px solid {ACCENT}; }}
QPushButton:focus {{ border: 2px solid {ACCENT_2}; }}
"""
_HEBREW = re.compile(r"[\u0590-\u05ff]")


def bidi_safe(text: str) -> str:
    """Keep Latin-only text (code, links) left-to-right in an RTL window."""
    return f"\u202a{text}\u202c" if text and not _HEBREW.search(text) else text


class RowDelegate(QStyledItemDelegate):
    """Two lines per row: the copied text (one line, elided) and a muted age."""

    ROW_HEIGHT = 54

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:  # noqa: N802 (Qt API)
        return QSize(option.rect.width(), self.ROW_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(2, 2, -2, -2)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.setPen(QColor(ACCENT))
            painter.setBrush(QColor(SURFACE))
            painter.drawRoundedRect(rect, 8, 8)
        text_rect = rect.adjusted(12, 6, -12, -6)
        align = QStyle.visualAlignment(option.direction, Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignVCenter
        title_font = QFont(option.font)
        title_font.setPointSizeF(max(option.font.pointSizeF(), 11.0))
        painter.setFont(title_font)
        painter.setPen(QColor(TEXT))
        top = QRect(text_rect.left(), text_rect.top(), text_rect.width(), text_rect.height() // 2 + 2)
        title = painter.fontMetrics().elidedText(str(index.data(Qt.ItemDataRole.DisplayRole)), Qt.TextElideMode.ElideRight,
                                                 top.width())
        painter.drawText(top, int(align.value), title)
        meta_font = QFont(option.font)
        meta_font.setPointSizeF(max(option.font.pointSizeF() - 1.5, 8.0))
        painter.setFont(meta_font)
        painter.setPen(QColor(MUTED))
        bottom = QRect(text_rect.left(), top.bottom(), text_rect.width(), text_rect.bottom() - top.bottom())
        painter.drawText(bottom, int(align.value), str(index.data(META_ROLE) or ""))
        painter.restore()


def copy_text(text: str) -> None:
    # Through stdin: argv is visible to every user in `ps`.
    subprocess.run(["wl-copy", "--type", "text/plain;charset=utf-8"], input=text.encode(), timeout=5, check=False)


def paste() -> None:
    subprocess.run(["wtype", "-M", "ctrl", "v", "-m", "ctrl"], timeout=5, check=False)


class ClipWindow(QWidget):
    def __init__(self, history: History, copier: Callable[[str], None] = copy_text,
                 paster: Callable[[], None] = paste, clock: Callable[[], float] = time.time) -> None:
        super().__init__()
        self.history = history
        self.copier = copier
        self.paster = paster
        self.clock = clock
        self.language = lang()
        self.items: list[Item] = []
        self.setObjectName("Window")
        self.setWindowTitle(t("title", self.language))
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setLayoutDirection(qt_direction(self.language))
        self.setStyleSheet(STYLE)
        self.resize(560, 460)

        card = QFrame(self)
        card.setObjectName("Card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 10)

        top = QHBoxLayout()
        title = QLabel(f"✦ {t('title', self.language)}")
        title.setObjectName("Title")
        top.addWidget(title, 1)
        self.clear_button = QPushButton(t("clear_all", self.language))
        self.clear_button.setAccessibleName(t("clear_all", self.language))
        self.clear_button.clicked.connect(self.clear_all)
        top.addWidget(self.clear_button)
        layout.addLayout(top)

        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText(t("search", self.language))
        self.search.setAccessibleName(t("search", self.language))
        self.search.textChanged.connect(self.refresh)
        self.search.installEventFilter(self)
        layout.addWidget(self.search)

        self.list = QListWidget()
        self.list.setObjectName("Items")
        self.list.setAccessibleName(t("title", self.language))
        self.list.setItemDelegate(RowDelegate(self.list))
        self.list.itemActivated.connect(lambda _item: self.choose(paste_after=True))
        self.list.installEventFilter(self)
        layout.addWidget(self.list, 1)

        self.empty = QLabel()
        self.empty.setObjectName("Empty")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty, 1)

        hint = QLabel(t("hint", self.language))
        hint.setObjectName("Hint")
        layout.addWidget(hint)
        self.reload()

    # -- data ----------------------------------------------------------------

    def reload(self) -> None:
        self.items = self.history.items()
        self.refresh()

    def refresh(self) -> None:
        needle = self.search.text().strip().casefold()
        self.list.clear()
        now = self.clock()
        for item in self.items:
            if needle and needle not in item.text.casefold():
                continue
            lines = item.text.count("\n") + 1
            meta = age(item.time, now, self.language)
            if lines > 1:
                meta += " · " + t("lines", self.language, n=lines)
            row = QListWidgetItem(bidi_safe(preview(item.text)))
            row.setData(TEXT_ROLE, item.text)
            row.setData(META_ROLE, meta)
            row.setData(Qt.ItemDataRole.AccessibleDescriptionRole, meta)
            row.setToolTip(item.text[:500])
            self.list.addItem(row)
        has_rows = self.list.count() > 0
        self.list.setVisible(has_rows)
        self.empty.setVisible(not has_rows)
        self.empty.setText(t("no_match" if self.items else "empty", self.language))
        self.clear_button.setEnabled(bool(self.items))
        if has_rows:
            self.list.setCurrentRow(0)

    def current_text(self) -> str | None:
        row = self.list.currentItem()
        return row.data(TEXT_ROLE) if row is not None else None

    # -- actions -------------------------------------------------------------

    def choose(self, paste_after: bool) -> None:
        text = self.current_text()
        if text is None:
            return
        self.copier(text)
        self.hide()
        if paste_after:
            QTimer.singleShot(PASTE_DELAY_MS, self._paste_and_quit)
        else:
            self._quit()

    def _paste_and_quit(self) -> None:
        self.paster()
        self._quit()

    def _quit(self) -> None:
        app = QApplication.instance()
        if app is not None and not getattr(self, "keep_running", False):
            app.quit()

    def remove_current(self) -> None:
        text = self.current_text()
        if text is None:
            return
        row = self.list.currentRow()
        self.history.remove(text)
        self.reload()
        if self.list.count():
            self.list.setCurrentRow(min(row, self.list.count() - 1))

    def clear_all(self) -> None:
        self.history.clear()
        self.reload()
        self.search.setFocus()

    # -- keys ----------------------------------------------------------------

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 (Qt API)
        if isinstance(event, QKeyEvent) and event.type() == QKeyEvent.Type.KeyPress:
            return self.handle_key(event)
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt API)
        if not self.handle_key(event):
            super().keyPressEvent(event)

    def handle_key(self, event: QKeyEvent) -> bool:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.hide()
            self._quit()
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.choose(paste_after=not event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            return True
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Up) and self.list.count():
            step = 1 if key == Qt.Key.Key_Down else -1
            self.list.setCurrentRow((self.list.currentRow() + step) % self.list.count())
            return True
        if key == Qt.Key.Key_Delete and (self.list.hasFocus() or not self.search.text()):
            self.remove_current()
            return True
        return False


def main(history: History) -> int:
    app = QApplication(sys.argv[:1])
    app.setApplicationName("D.Ai Clip")
    app.setApplicationVersion(f"{__version__} — {__author__}")
    QGuiApplication.setDesktopFileName(APP_ID)  # Wayland app_id for the labwc window rule
    window = ClipWindow(history)
    window.show()
    window.activateWindow()
    window.search.setFocus()
    return app.exec()
