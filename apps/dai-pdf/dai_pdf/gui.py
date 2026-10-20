# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The D.Ai PDF window (docs/PDF.md §4): pages in the middle, a side panel (pages, outline, search,
attachments), the file bar at the top when the file "wants" something, and the tools above.

The window never touches the file: a Reader (dai_pdf.reader) asks the sandboxed helper for page images, text
and link rectangles, and this module only shows them. Right-to-left in Hebrew, in the person's theme, every
control named for screen readers and reachable with Tab; the current page's text is its accessible description.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QGuiApplication, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame,
                             QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                             QPlainTextEdit, QPushButton, QScrollArea, QTabWidget, QTreeWidget, QTreeWidgetItem,
                             QVBoxLayout, QWidget)

from dai_i18n import pick, qt_direction, ui_lang
from dai_style import color
from dai_style.panes import Panes, WrapRow, touch_scrolling

from .edit import EditError, Editor, human_size, ocr_langs
from .reader import Document, PdfError, Reader
from .text import find_all

APP_ID = "dai-pdf"
POINT = 96 / 72                      # pixels per point at 100 %
ZOOMS = (50, 75, 100, 125, 150, 200, 300, 400)
PAGE_GAP = 14
MARGIN = 24
CACHE_PAGES = 12
THUMB_WIDTH = 140
MAX_THUMBS = 400
SEARCH_CONTEXT = 40
MAX_RESULTS = 500

BG, BG2, SURFACE, BORDER, TEXT, MUTED = (color(r) for r in ("bg_900", "bg_800", "surface", "border", "text", "muted"))
ACCENT, ACCENT_STRONG, ACCENT_2, WARN, OK, DANGER = (color(r) for r in ("accent", "accent_strong", "accent_2", "warn",
                                                                        "ok", "danger"))
DISABLED = color("disabled")
STYLE = f"""
QWidget#Window, QDialog {{ background: {BG}; color: {TEXT}; }}
QLabel {{ color: {TEXT}; }}
#AppTitle {{ font-size: 12pt; font-weight: 700; color: {MUTED}; }}
#Title {{ font-size: 13pt; font-weight: 700; }}
#Muted {{ color: {MUTED}; }}
#Banner {{ background: {SURFACE}; border: 1px solid {WARN}; border-radius: 10px; }}
#BannerText {{ color: {TEXT}; }}
#Pages {{ background: {BG2}; }}
#Message {{ font-size: 13pt; color: {TEXT}; padding: 24px; }}
QScrollArea {{ border: 1px solid {BORDER}; border-radius: 10px; background: {BG2}; }}
QScrollArea:focus {{ border: 2px solid {ACCENT_2}; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 10px; background: {BG2}; }}
QTabBar::tab {{ background: {SURFACE}; color: {TEXT}; padding: 6px 12px; border: 1px solid {BORDER};
    border-bottom: none; border-top-left-radius: 8px; border-top-right-radius: 8px; }}
QTabBar::tab:selected {{ background: {BG2}; border: 1px solid {ACCENT}; border-bottom: none; }}
QTabBar::tab:focus {{ border: 2px solid {ACCENT_2}; }}
QListWidget, QTreeWidget {{ background: {BG2}; color: {TEXT}; border: none; outline: none; font-size: 10.5pt; }}
QListWidget::item, QTreeWidget::item {{ padding: 4px; border-radius: 6px; }}
QListWidget::item:selected, QTreeWidget::item:selected {{ background: {SURFACE}; color: {TEXT};
    border: 1px solid {ACCENT}; }}
QListWidget:focus, QTreeWidget:focus {{ border: 2px solid {ACCENT_2}; }}
QLineEdit, QComboBox {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 5px 10px; font-size: 11pt; selection-background-color: {ACCENT_STRONG}; }}
QLineEdit:focus, QComboBox:focus {{ border: 2px solid {ACCENT_2}; }}
QComboBox QAbstractItemView {{ background: {SURFACE}; color: {TEXT}; selection-background-color: {ACCENT_STRONG}; }}
QPushButton {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 12px; }}
QPushButton:hover {{ border: 1px solid {ACCENT}; }}
QPushButton:focus {{ border: 2px solid {ACCENT_2}; }}
QPushButton#Primary {{ background: {ACCENT_STRONG}; color: #FFFFFF; border: 1px solid {ACCENT_STRONG}; }}
QPushButton#Primary:focus {{ border: 2px solid {ACCENT_2}; }}
QPushButton:disabled {{ background: {SURFACE}; color: {DISABLED}; border: 1px solid {BORDER}; }}
QLineEdit:disabled, QComboBox:disabled {{ color: {DISABLED}; }}
QPlainTextEdit {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 8px; font-size: 11pt; }}
QPlainTextEdit:focus {{ border: 2px solid {ACCENT_2}; }}
QCheckBox {{ color: {TEXT}; spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border: 1px solid {BORDER}; border-radius: 4px; background: {SURFACE}; }}
QCheckBox::indicator:checked {{ background: {ACCENT_STRONG}; border: 1px solid {ACCENT_STRONG}; }}
QCheckBox:focus {{ color: {ACCENT_2}; }}
#FormHint {{ color: {MUTED}; font-size: 10pt; }}
#FormBody {{ background: {BG2}; }}
"""


def say(lang: str, en: str, he: str, **kwargs: object) -> str:
    return pick(lang, en, he).format(**kwargs)


def default_open_url(url: str) -> None:
    subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def human_size(size: int) -> str:
    if size < 0:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def findings_sentences(doc: Document, lang: str) -> list[str]:
    """The file bar's lines: what the file wants, and that none of it is done (docs/PDF.md §0)."""
    f = doc.findings
    lines: list[str] = []
    if not doc.inspected:
        lines.append(say(lang, "This file could not be inspected for scripts and attachments; it is still shown "
                               "only inside the sandbox.",
                         "לא ניתן היה לבדוק בקובץ זה סקריפטים וקבצים מצורפים; הוא עדיין מוצג רק בתוך ארגז החול."))
    if f.javascript:
        lines.append(say(lang, "This PDF contains JavaScript ({n}). It is not run.",
                         "קובץ ה-PDF מכיל JavaScript ({n}). הוא לא מופעל.", n=f.javascript))
    if f.launch:
        lines.append(say(lang, "It asks to run a program on this computer ({n}). Refused.",
                         "הוא מבקש להריץ תוכנית על המחשב הזה ({n}). נדחה.", n=f.launch))
    if f.remote:
        lines.append(say(lang, "It asks to open another file ({n}). Not opened.",
                         "הוא מבקש לפתוח קובץ אחר ({n}). לא נפתח.", n=f.remote))
    if f.submit:
        lines.append(say(lang, "A form in it would send data to an address ({n}). Blocked.",
                         "טופס בו היה שולח נתונים לכתובת ({n}). נחסם.", n=f.submit))
    if f.attachments:
        lines.append(say(lang, "{n} attached files. They are listed in the side panel and never opened.",
                         "{n} קבצים מצורפים. הם מופיעים בלוח הצד ולעולם לא נפתחים.", n=len(f.attachments)))
    if f.xfa:
        lines.append(say(lang, "This is an XFA form; only its static page is shown.",
                         "זהו טופס XFA; מוצג רק הדף הסטטי שלו."))
    if f.truncated:
        lines.append(say(lang, "The file is very large; the inspection stopped early.",
                         "הקובץ גדול מאוד; הבדיקה נעצרה מוקדם."))
    return lines


class PageView(QLabel):
    """One page: a rendered picture, the links on it, and the search highlights."""

    def __init__(self, window: "PdfWindow", index: int, points: tuple[float, float]) -> None:
        super().__init__()
        self.window_, self.index, self.points = window, index, points
        self.extra = 0  # the page's own turn, from an edit (docs/PDF.md stage 2)
        self.links: list[dict] | None = None
        self.highlights: list[tuple[float, float, float, float]] = []
        self.drag_start: QPoint | None = None
        self.drag_rect: QRect | None = None
        self.rendered_key: tuple | None = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setObjectName("Page")
        self.setAccessibleName(say(window.lang, "Page {n}", "עמוד {n}", n=index + 1))
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    @property
    def rotation(self) -> int:
        return (self.window_.rotation + self.extra) % 360

    def pixel_size(self) -> QSize:
        scale, rotation = self.window_.scale, self.rotation
        w, h = self.points
        if rotation in (90, 270):
            w, h = h, w
        return QSize(max(1, round(w * scale)), max(1, round(h * scale)))

    def placeholder(self) -> None:
        size = self.pixel_size()
        self.setFixedSize(size)
        if self.rendered_key is not None:
            self.rendered_key = None
            self.setPixmap(QPixmap())
        self.setStyleSheet(f"background: {SURFACE}; border: 1px solid {BORDER};")

    def show_image(self, image: QImage) -> None:
        pixmap = QPixmap.fromImage(image)
        if self.rotation:
            from PyQt6.QtGui import QTransform
            pixmap = pixmap.transformed(QTransform().rotate(self.rotation))
        marks = self.window_.marks_for(self.index)
        if self.highlights or marks:
            pixmap = self.with_highlights(pixmap, marks)
        self.setFixedSize(pixmap.size())
        self.setStyleSheet(f"border: 1px solid {BORDER};")
        self.setPixmap(pixmap)
        self.rendered_key = self.window_.render_key(self)

    def with_highlights(self, pixmap: QPixmap, marks: list[dict] | None = None) -> QPixmap:
        painted = QPixmap(pixmap)
        painter = QPainter(painted)
        for mark in marks or ():
            self.draw_mark(painter, mark)
        painter.setPen(QPen(QColor(ACCENT_2), 2))
        fill = QColor(ACCENT_2)
        fill.setAlpha(70)
        painter.setBrush(fill)
        for rect in self.highlights:
            painter.drawRect(self.to_pixels(rect))
        painter.end()
        return painted

    def draw_mark(self, painter: QPainter, mark: dict) -> None:
        """An unsaved mark (docs/PDF.md stage 2b) drawn over the page the way the saved file will show it."""
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QFont, QTextOption

        rect = self.to_pixels(tuple(mark["rect"]))
        colour = QColor(mark.get("color") or "#FFEB3B")
        kind = mark["kind"]
        painter.save()
        if kind == "highlight":
            colour.setAlpha(110)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(colour)
            painter.drawRect(rect)
        elif kind in ("underline", "strikeout"):
            painter.setPen(QPen(colour, max(1, round(2 * self.window_.scale))))
            y = rect.bottom() if kind == "underline" else rect.center().y()
            painter.drawLine(rect.left(), y, rect.right(), y)
        elif kind == "note":
            size = max(10, round(20 * self.window_.scale))
            painter.setPen(QPen(QColor("#333333"), 1))
            painter.setBrush(colour)
            painter.drawRoundedRect(QRect(rect.x(), rect.y(), size, size), 3, 3)
        elif kind == "text":
            painter.setPen(QColor(mark.get("color") or "#111111"))
            font = QFont("Noto Sans")
            font.setPixelSize(max(4, round(float(mark.get("size", 12)) * self.window_.scale)))
            painter.setFont(font)
            text = str(mark.get("text", ""))
            rtl = any("\u0590" <= ch <= "\u08ff" for ch in text)
            option = QTextOption(Qt.AlignmentFlag.AlignTop | (Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft))
            option.setWrapMode(QTextOption.WrapMode.WordWrap)
            option.setTextDirection(Qt.LayoutDirection.RightToLeft if rtl else Qt.LayoutDirection.LeftToRight)
            painter.drawText(QRectF(rect), text, option)
        elif kind == "stamp":
            picture = self.window_.picture(mark.get("image", -1))
            if picture is not None and not picture.isNull():
                painter.drawPixmap(rect, picture)
        elif kind == "redact":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#000000"))
            painter.drawRect(rect)
        painter.restore()

    def to_pixels(self, rect: tuple[float, float, float, float]) -> QRect:
        """A rectangle in page points (top-left origin, unrotated) on this rotated, scaled picture."""
        x, y, w, h = rect
        pw, ph = self.points
        r = self.rotation
        if r == 90:
            x, y, w, h = ph - y - h, x, h, w
        elif r == 180:
            x, y = pw - x - w, ph - y - h
        elif r == 270:
            x, y, w, h = y, pw - x - w, h, w
        s = self.window_.scale
        return QRect(round(x * s), round(y * s), max(2, round(w * s)), max(2, round(h * s)))

    def to_points(self, pos: QPoint) -> tuple[float, float]:
        """A pixel on this picture, as a point on the unrotated page."""
        s = self.window_.scale
        x, y = pos.x() / s, pos.y() / s
        pw, ph = self.points
        r = self.rotation
        if r == 90:
            x, y = y, ph - x
        elif r == 180:
            x, y = pw - x, ph - y
        elif r == 270:
            x, y = pw - y, x
        return x, y

    def link_at(self, pos: QPoint) -> dict | None:
        if not self.links:
            return None
        x, y = self.to_points(pos)
        for link in self.links:
            lx, ly, lw, lh = link.get("rect", (0, 0, 0, 0))
            if lx <= x <= lx + lw and ly <= y <= ly + lh:
                return link
        return None

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt's name
        if self.drag_start is not None:
            self.drag_rect = QRect(self.drag_start, event.pos()).normalized()
            self.update()
            return
        if self.window_.tool != "select":
            self.setCursor(Qt.CursorShape.CrossCursor)
            return
        self.setCursor(Qt.CursorShape.PointingHandCursor if self.link_at(event.pos()) else Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt's name
        if event.button() == Qt.MouseButton.LeftButton:
            if self.window_.tool != "select":
                self.drag_start = event.pos()
                self.drag_rect = QRect(self.drag_start, self.drag_start)
                return
            link = self.link_at(event.pos())
            if link is not None:
                self.window_.follow_link(link)
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt's name
        if self.drag_start is not None and event.button() == Qt.MouseButton.LeftButton:
            rect, self.drag_start, self.drag_rect = QRect(self.drag_start, event.pos()).normalized(), None, None
            self.update()
            self.window_.drawn(self.index, rect)
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().paintEvent(event)
        if self.drag_rect is not None:
            painter = QPainter(self)
            painter.setPen(QPen(QColor(ACCENT_2), 1, Qt.PenStyle.DashLine))
            painter.drawRect(self.drag_rect)
            painter.end()

    def rect_points(self, rect: QRect) -> tuple[float, float, float, float]:
        """A pixel rectangle on this picture as (left, top, width, height) in points on the unrotated page."""
        x1, y1 = self.to_points(rect.topLeft())
        x2, y2 = self.to_points(rect.bottomRight())
        left, top = min(x1, x2), min(y1, y2)
        return round(left, 2), round(top, 2), round(abs(x2 - x1), 2), round(abs(y2 - y1), 2)


class PasswordDialog(QDialog):
    def __init__(self, parent: QWidget, lang: str, name: str, wrong: bool) -> None:
        super().__init__(parent)
        self.setWindowTitle(say(lang, "This PDF is locked", "קובץ ה-PDF נעול"))
        self.setLayoutDirection(qt_direction(lang))
        self.setStyleSheet(STYLE)
        layout = QVBoxLayout(self)
        text = say(lang, "{name} needs a password to open.", "{name} דורש סיסמה כדי להיפתח.", name=name)
        if wrong:
            text = say(lang, "That password did not open {name}. Try again.",
                       "הסיסמה הזו לא פתחה את {name}. נסו שוב.", name=name)
        label = QLabel(text)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setAccessibleName(say(lang, "Password", "סיסמה"))
        self.password.returnPressed.connect(self.accept)
        layout.addWidget(self.password)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(say(lang, "Cancel", "ביטול"))
        cancel.setAccessibleName(cancel.text())
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        ok = QPushButton(say(lang, "Open", "פתיחה"))
        ok.setObjectName("Primary")
        ok.setAccessibleName(ok.text())
        ok.clicked.connect(self.accept)
        buttons.addWidget(ok)
        layout.addLayout(buttons)


class LinkDialog(QDialog):
    """A link is shown whole, and opened only on a click here (docs/PDF.md §2)."""

    def __init__(self, parent: QWidget, lang: str, url: str, allowed: bool) -> None:
        super().__init__(parent)
        self.setWindowTitle(say(lang, "A link in this PDF", "קישור בקובץ ה-PDF"))
        self.setLayoutDirection(qt_direction(lang))
        self.setStyleSheet(STYLE)
        layout = QVBoxLayout(self)
        if allowed:
            lead = say(lang, "Open this address in the browser?", "לפתוח את הכתובת הזו בדפדפן?")
        else:
            lead = say(lang, "This link would open a file or a program on this computer. D.Ai PDF does not do that.",
                       "הקישור הזה היה פותח קובץ או תוכנית על המחשב הזה. D.Ai PDF לא עושה את זה.")
        label = QLabel(lead)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.address = QLabel(url[:2000])
        self.address.setObjectName("Muted")
        self.address.setWordWrap(True)
        self.address.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.address.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.address.setAccessibleName(say(lang, "The address", "הכתובת"))
        layout.addWidget(self.address)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(say(lang, "Close", "סגירה") if not allowed else say(lang, "Cancel", "ביטול"))
        cancel.setAccessibleName(cancel.text())
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        if allowed:
            ok = QPushButton(say(lang, "Open the link", "פתיחת הקישור"))
            ok.setObjectName("Primary")
            ok.setAccessibleName(ok.text())
            ok.clicked.connect(self.accept)
            buttons.addWidget(ok)
        layout.addLayout(buttons)


class InfoDialog(QDialog):
    def __init__(self, parent: QWidget, lang: str, doc: Document, sandboxed: bool) -> None:
        super().__init__(parent)
        self.setWindowTitle(say(lang, "About this PDF", "על קובץ ה-PDF הזה"))
        self.setLayoutDirection(qt_direction(lang))
        self.setStyleSheet(STYLE)
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        rows = [
            (say(lang, "File", "קובץ"), Path(doc.path).name),
            (say(lang, "Pages", "עמודים"), str(doc.count)),
            (say(lang, "Title", "כותרת"), doc.metadata.get("title", "")),
            (say(lang, "Author", "מחבר"), doc.metadata.get("author", "")),
            (say(lang, "Subject", "נושא"), doc.metadata.get("subject", "")),
            (say(lang, "Keywords", "מילות מפתח"), doc.metadata.get("keywords", "")),
            (say(lang, "Created with", "נוצר באמצעות"), " · ".join(filter(None, (doc.metadata.get("creator", ""),
                                                                            doc.metadata.get("producer", ""))))),
            (say(lang, "Created", "נוצר"), doc.metadata.get("created", "")),
            (say(lang, "Modified", "שונה"), doc.metadata.get("modified", "")),
            (say(lang, "Encrypted", "מוצפן"), say(lang, "yes", "כן") if doc.findings.encrypted else say(lang, "no", "לא")),
            (say(lang, "Opened in a sandbox", "נפתח בארגז חול"),
             say(lang, "yes", "כן") if sandboxed else say(lang, "no (test mode)", "לא (מצב בדיקה)")),
        ]
        for name, value in rows:
            label = QLabel(value or "—")
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setAccessibleName(name)
            form.addRow(name, label)
        layout.addLayout(form)
        wants = findings_sentences(doc, lang)
        if wants:
            title = QLabel(say(lang, "What this file wants to do (and does not get to)",
                               "מה הקובץ הזה רוצה לעשות (ולא מקבל)"))
            title.setObjectName("Title")
            layout.addWidget(title)
            for line in wants:
                item = QLabel("• " + line)
                item.setWordWrap(True)
                layout.addWidget(item)
        note = QLabel(say(lang, "Nothing about this file leaves this computer.", "שום דבר על הקובץ הזה לא יוצא מהמחשב הזה."))
        note.setObjectName("Muted")
        layout.addWidget(note)
        close = QPushButton(say(lang, "Close", "סגירה"))
        close.setAccessibleName(close.text())
        close.clicked.connect(self.accept)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)


class PdfWindow(QWidget):
    def __init__(self, path: str | None = None, lang: str | None = None,
                 reader_factory: Callable[..., Reader] = Reader, open_url: Callable[[str], None] = default_open_url,
                 sandboxed: bool = True, ask_password: Callable[[str, bool], str | None] | None = None,
                 editor: Editor | None = None, confirm_discard: Callable[[], bool] | None = None) -> None:
        super().__init__()
        self.lang = lang or ui_lang()
        self.reader_factory, self.open_url, self.sandboxed = reader_factory, open_url, sandboxed
        self.ask_password = ask_password or self._ask_password
        self.editor = editor or Editor(sandboxed=sandboxed)
        self.confirm_discard = confirm_discard or self._confirm_discard
        self.reader: Reader | None = None
        self.doc: Document | None = None
        # Editing (docs/PDF.md stage 2): the window shows a plan, not the file. plan[i] says which source page
        # is at position i and how it is turned; the sources are the document and every inserted file. Nothing
        # is written until "Save": the sandboxed editor builds the file the plan describes.
        self.sources: list[Reader] = []
        self.plan: list[dict] = []
        self.undo_stack: list[tuple[list[dict], dict, list[dict]]] = []
        self.redo_stack: list[tuple[list[dict], dict, list[dict]]] = []
        self.fields: list[dict] = []
        self.field_values: dict[str, object] = {}
        self.field_widgets: dict[str, QWidget] = {}
        # Marks (docs/PDF.md stage 2b): each belongs to a source page, so it follows the page when pages move.
        self.marks: list[dict] = []
        self.pictures: list[str] = []          # stamp images, by index
        self.picture_cache: dict[int, QPixmap] = {}
        self.tool = "select"
        self.tool_color = "#FFEB3B"
        self.modified = False
        self.thumb_cache: dict[tuple, QIcon] = {}
        self.views: list[PageView] = []
        self.cache: dict[int, tuple[tuple, QImage]] = {}
        self.cache_order: list[int] = []
        self.zoom: str = "width"          # "width", "page", or a percentage as a string
        self.scale: float = POINT
        self.rotation = 0
        self.current_page = 0
        self.results: list[tuple[int, int, int]] = []  # (page, start, length)
        self.thumbs_done = 0
        self.setObjectName("Window")
        self.setWindowTitle("D.Ai PDF")
        self.setLayoutDirection(qt_direction(self.lang))
        self.setStyleSheet(STYLE)
        self.resize(1100, 760)
        self._build()
        touch_scrolling(self)
        self._shortcuts()
        self.render_timer = QTimer(self)
        self.render_timer.setSingleShot(True)
        self.render_timer.setInterval(40)
        self.render_timer.timeout.connect(self.render_visible)
        self.thumb_timer = QTimer(self)
        self.thumb_timer.setInterval(30)
        self.thumb_timer.timeout.connect(self._next_thumbnail)
        if path:
            self.open_path(path)
        else:
            self.show_message(say(self.lang, "Open a PDF to read it here, inside the sandbox.",
                                  "פתחו קובץ PDF כדי לקרוא אותו כאן, בתוך ארגז החול."))

    # --- building ----------------------------------------------------------------------------------------------

    def _button(self, text: str, name: str, slot: Callable, layout, primary: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setAccessibleName(name)
        button.setToolTip(name)
        if primary:
            button.setObjectName("Primary")
        button.clicked.connect(slot)
        layout.addWidget(button)
        return button

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        top = WrapRow()  # the toolbar wraps onto more rows when the window is narrow (docs/MOBILE.md A2)
        title = QLabel("💎 D.Ai PDF")
        title.setObjectName("AppTitle")
        top.addWidget(title)
        self.open_button = self._button(say(self.lang, "Open…", "פתיחה…"), say(self.lang, "Open a PDF", "פתיחת PDF"),
                                        self.open_dialog, top)
        self.prev_button = self._button("◀", say(self.lang, "Previous page", "העמוד הקודם"),
                                        lambda: self.go_to(self.current_page - 1), top)
        self.page_field = QLineEdit()
        self.page_field.setFixedWidth(64)
        self.page_field.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_field.setAccessibleName(say(self.lang, "Page number", "מספר עמוד"))
        self.page_field.returnPressed.connect(self._page_typed)
        top.addWidget(self.page_field)
        self.count_label = QLabel("")
        self.count_label.setObjectName("Muted")
        top.addWidget(self.count_label)
        self.next_button = self._button("▶", say(self.lang, "Next page", "העמוד הבא"),
                                        lambda: self.go_to(self.current_page + 1), top)
        top.addSpacing(12)
        self.zoom_out = self._button("－", say(self.lang, "Zoom out", "הקטנה"), lambda: self.step_zoom(-1), top)
        self.zoom_box = QComboBox()
        self.zoom_box.setAccessibleName(say(self.lang, "Zoom", "הגדלה"))
        self.zoom_box.addItem(say(self.lang, "Fit width", "לרוחב החלון"), "width")
        self.zoom_box.addItem(say(self.lang, "Whole page", "עמוד שלם"), "page")
        for z in ZOOMS:
            self.zoom_box.addItem(f"{z}%", str(z))
        self.zoom_box.currentIndexChanged.connect(self._zoom_chosen)
        top.addWidget(self.zoom_box)
        self.zoom_in = self._button("＋", say(self.lang, "Zoom in", "הגדלה"), lambda: self.step_zoom(1), top)
        self.rotate_button = self._button("⟳", say(self.lang, "Rotate the view", "סיבוב התצוגה"), self.rotate, top)
        top.addSpacing(12)
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText(say(self.lang, "Search in the file", "חיפוש בקובץ"))
        self.search_field.setAccessibleName(say(self.lang, "Search in the file", "חיפוש בקובץ"))
        self.search_field.setMinimumWidth(180)
        self.search_field.returnPressed.connect(self.search)
        top.addWidget(self.search_field)
        self.side_button = self._button("☰", say(self.lang, "Show or hide the side panel", "הצגה או הסתרה של לוח הצד"),
                                        self.toggle_side, top)
        self.info_button = self._button("ⓘ", say(self.lang, "About this PDF", "על קובץ ה-PDF הזה"), self.show_info, top)
        self.print_button = self._button("🖨", say(self.lang, "Print", "הדפסה"), self.print_, top)
        top.addSpacing(12)
        self.undo_button = self._button("↶", say(self.lang, "Undo", "ביטול"), self.undo, top)
        self.redo_button = self._button("↷", say(self.lang, "Redo", "ביצוע מחדש"), self.redo, top)
        self.save_button = self._button(say(self.lang, "Save as…", "שמירה בשם…"), say(self.lang, "Save the edited file", "שמירת הקובץ הערוך"),
                                        self.save_as, top, primary=True)
        outer.addLayout(top)
        tools = WrapRow()
        self.tool_buttons: dict[str, QPushButton] = {}
        for tool, text, name_en, name_he in (("select", "↖", "Select and follow links", "בחירה ומעקב אחר קישורים"),
                                             ("highlight", "▆", "Highlight", "הדגשה"), ("underline", "U̲", "Underline", "קו תחתון"),
                                             ("strikeout", "S̶", "Strike through", "קו חוצה"), ("note", "✎", "Note", "הערה"),
                                             ("text", "T", "Text (Hebrew too)", "טקסט (גם עברית)"), ("stamp", "🖼", "Stamp a picture or a signature", "חותמת תמונה או חתימה"),
                                             ("redact", "■", "Black out (the page becomes a picture; what is under the box is gone)", "השחרה (העמוד הופך לתמונה; מה שמתחת לתיבה נעלם)")):
            button = self._button(text, say(self.lang, name_en, name_he), lambda _c=False, t=tool: self.set_tool(t), tools)
            button.setCheckable(True)
            self.tool_buttons[tool] = button
        self.tool_buttons["select"].setChecked(True)
        self.color_button = self._button("", say(self.lang, "Colour of the next mark", "צבע הסימון הבא"), self.choose_color, tools)
        self._show_color()
        outer.addLayout(tools)

        self.banner = QFrame()
        self.banner.setObjectName("Banner")
        banner_layout = QHBoxLayout(self.banner)
        self.banner_text = QLabel("")
        self.banner_text.setObjectName("BannerText")
        self.banner_text.setWordWrap(True)
        self.banner_text.setAccessibleName(say(self.lang, "What this file wants to do", "מה הקובץ הזה רוצה לעשות"))
        banner_layout.addWidget(self.banner_text, 1)
        self.banner.hide()
        outer.addWidget(self.banner)

        self.splitter = Panes()  # side panel beside the page; above it when narrow (docs/MOBILE.md A2)
        self.side = QTabWidget()
        self.side.setAccessibleName(say(self.lang, "Side panel", "לוח הצד"))
        self.thumbs = QListWidget()
        self.thumbs.setViewMode(QListWidget.ViewMode.IconMode)
        self.thumbs.setIconSize(QSize(THUMB_WIDTH, THUMB_WIDTH))
        self.thumbs.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.thumbs.setMovement(QListWidget.Movement.Static)
        self.thumbs.setAccessibleName(say(self.lang, "Pages", "עמודים"))
        self.thumbs.currentRowChanged.connect(lambda row: self.go_to(row) if row >= 0 and not self._syncing else None)
        pages_tab = QWidget()
        pages_layout = QVBoxLayout(pages_tab)
        pages_layout.setContentsMargins(0, 0, 0, 0)
        pages_layout.addWidget(self.thumbs, 1)
        tools = WrapRow()
        self.rotate_page_button = self._button("⟳", say(self.lang, "Turn this page", "סיבוב העמוד הזה"), self.rotate_page, tools)
        self.up_button = self._button("↑", say(self.lang, "Move this page up", "הזזת העמוד למעלה"), lambda: self.move_page(-1), tools)
        self.down_button = self._button("↓", say(self.lang, "Move this page down", "הזזת העמוד למטה"), lambda: self.move_page(1), tools)
        self.delete_button = self._button("✕", say(self.lang, "Remove this page", "הסרת העמוד הזה"), self.delete_page, tools)
        self.insert_button = self._button("＋", say(self.lang, "Insert pages from another PDF", "הוספת עמודים מקובץ PDF אחר"),
                                          self.insert_dialog, tools)
        pages_layout.addLayout(tools)
        self.side.addTab(pages_tab, say(self.lang, "Pages", "עמודים"))
        self.outline = QTreeWidget()
        self.outline.setHeaderHidden(True)
        self.outline.setAccessibleName(say(self.lang, "Outline", "תוכן העניינים"))
        self.outline.itemActivated.connect(self._outline_chosen)
        self.outline.itemClicked.connect(self._outline_chosen)
        self.side.addTab(self.outline, say(self.lang, "Outline", "תוכן העניינים"))
        self.result_list = QListWidget()
        self.result_list.setAccessibleName(say(self.lang, "Search results", "תוצאות חיפוש"))
        self.result_list.currentRowChanged.connect(self._result_chosen)
        self.side.addTab(self.result_list, say(self.lang, "Search", "חיפוש"))
        self.attachments = QListWidget()
        self.attachments.setAccessibleName(say(self.lang, "Attachments (never opened)", "קבצים מצורפים (לעולם לא נפתחים)"))
        self.side.addTab(self.attachments, say(self.lang, "Attachments", "קבצים מצורפים"))
        self.form_scroll = QScrollArea()
        self.form_scroll.setWidgetResizable(True)
        self.form_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.form_scroll.setAccessibleName(say(self.lang, "Form", "טופס"))
        self.form_widget = QWidget()
        self.form_widget.setObjectName("FormBody")
        self.form_layout = QFormLayout(self.form_widget)
        self.form_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.form_scroll.setWidget(self.form_widget)
        self.side.addTab(self.form_scroll, say(self.lang, "Form", "טופס"))
        marks_tab = QWidget()
        marks_layout = QVBoxLayout(marks_tab)
        marks_layout.setContentsMargins(0, 0, 0, 0)
        self.marks_list = QListWidget()
        self.marks_list.setAccessibleName(say(self.lang, "Marks", "סימונים"))
        self.marks_list.itemActivated.connect(lambda item: self.go_to(int(item.data(Qt.ItemDataRole.UserRole + 1))))
        marks_layout.addWidget(self.marks_list, 1)
        marks_row = WrapRow()
        self.remove_mark_button = self._button("✕", say(self.lang, "Remove this mark", "הסרת הסימון הזה"), self.remove_mark, marks_row)
        marks_layout.addLayout(marks_row)
        self.side.addTab(marks_tab, say(self.lang, "Marks", "סימונים"))
        clean_tab = QWidget()
        clean_layout = QVBoxLayout(clean_tab)
        clean_hint = QLabel(say(self.lang, "Applied when you save. Everything runs in the sandbox on this computer.",
                                "חל בשמירה. הכול רץ בארגז החול במחשב הזה."))
        clean_hint.setObjectName("FormHint")
        clean_hint.setWordWrap(True)
        clean_layout.addWidget(clean_hint)
        self.ocr_box = QCheckBox(say(self.lang, "Make scanned pages searchable (OCR, {langs})", "הפיכת עמודים סרוקים לניתנים לחיפוש (OCR, {langs})",
                                     langs=ocr_langs(self.lang).replace("+", ", ")))
        self.ocr_box.setAccessibleName(say(self.lang, "Make scanned pages searchable", "הפיכת עמודים סרוקים לניתנים לחיפוש"))
        self.ocr_box.toggled.connect(lambda _on: self._clean_changed())
        clean_layout.addWidget(self.ocr_box)
        self.ocr_all_box = QCheckBox(say(self.lang, "Every page, not only scans (each becomes a picture with a text layer)",
                                         "כל העמודים, לא רק סריקות (כל אחד הופך לתמונה עם שכבת טקסט)"))
        self.ocr_all_box.setAccessibleName(say(self.lang, "OCR every page", "OCR לכל העמודים"))
        self.ocr_all_box.toggled.connect(lambda _on: self._clean_changed())
        clean_layout.addWidget(self.ocr_all_box)
        self.strip_box = QCheckBox(say(self.lang, "Remove the metadata (author, program, dates) before sharing",
                                       "הסרת המטא-דאטה (מחבר, תוכנה, תאריכים) לפני שיתוף"))
        self.strip_box.setAccessibleName(say(self.lang, "Remove the metadata", "הסרת המטא-דאטה"))
        self.strip_box.toggled.connect(lambda _on: self._clean_changed())
        clean_layout.addWidget(self.strip_box)
        redact_hint = QLabel(say(self.lang, "Black boxes (the ■ tool) make their page a picture when you save: what was under them is "
                                            "truly gone, and so is that page's text unless OCR is on.",
                                 "תיבות שחורות (הכלי ■) הופכות את העמוד שלהן לתמונה בשמירה: מה שהיה מתחתן נעלם באמת, וגם הטקסט של העמוד אלא אם OCR פועל."))
        redact_hint.setObjectName("FormHint")
        redact_hint.setWordWrap(True)
        clean_layout.addWidget(redact_hint)
        size_label = QLabel(say(self.lang, "Smaller file", "קובץ קטן יותר"))
        size_label.setObjectName("FormHint")
        clean_layout.addWidget(size_label)
        self.compress_choice = QComboBox()
        self.compress_choice.addItem(say(self.lang, "As it is", "כמו שהוא"), "")
        self.compress_choice.addItem(say(self.lang, "Smaller: pictures at most 2000 pixels wide", "קטן יותר: תמונות ברוחב עד 2000 פיקסלים"), "light")
        self.compress_choice.addItem(say(self.lang, "Much smaller: 1200 pixels, for e-mail", "קטן בהרבה: 1200 פיקסלים, לדוא\"ל"), "strong")
        self.compress_choice.setAccessibleName(say(self.lang, "Smaller file", "קובץ קטן יותר"))
        self.compress_choice.currentIndexChanged.connect(lambda _i: self._clean_changed())
        size_label.setBuddy(self.compress_choice)
        clean_layout.addWidget(self.compress_choice)
        self.size_button = self._button(say(self.lang, "Check the size", "בדיקת הגודל"),
                                        say(self.lang, "What the saved file would weigh, without writing it", "כמה ישקול הקובץ השמור, בלי לכתוב אותו"),
                                        self.check_size, clean_layout)
        self.export_button = self._button(say(self.lang, "Export pages as pictures…", "ייצוא עמודים כתמונות…"),
                                          say(self.lang, "Every page as a PNG picture", "כל עמוד כתמונת PNG"), self.export_dialog, clean_layout)
        clean_layout.addStretch(1)
        self.side.addTab(clean_tab, say(self.lang, "Clean", "ניקוי"))
        self.side.currentChanged.connect(lambda i: self._thumbnails_start() if i == 0 else None)
        self.splitter.addWidget(self.side)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setAccessibleName(say(self.lang, "The document", "המסמך"))
        self.scroll.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.pages_widget = QWidget()
        self.pages_widget.setObjectName("Pages")
        self.pages_layout = QVBoxLayout(self.pages_widget)
        self.pages_layout.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        self.pages_layout.setSpacing(PAGE_GAP)
        self.pages_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.message = QLabel("")
        self.message.setObjectName("Message")
        self.message.setWordWrap(True)
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pages_layout.addWidget(self.message)
        self.scroll.setWidget(self.pages_widget)
        self.scroll.verticalScrollBar().valueChanged.connect(self._scrolled)
        self.splitter.addWidget(self.scroll)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([240, 860])
        outer.addWidget(self.splitter, 1)

        self.status = QLabel(say(self.lang, "Every PDF opens in a sandbox: no network, no access to your files.",
                                 "כל PDF נפתח בארגז חול: בלי רשת, בלי גישה לקבצים שלכם."))
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        self._syncing = False

    def _shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.open_dialog)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=lambda: (self.search_field.setFocus(), self.search_field.selectAll()))
        QShortcut(QKeySequence("F3"), self, activated=self.next_result)
        QShortcut(QKeySequence("Ctrl+P"), self, activated=self.print_)
        QShortcut(QKeySequence("Ctrl+I"), self, activated=self.show_info)
        QShortcut(QKeySequence("Ctrl++"), self, activated=lambda: self.step_zoom(1))
        QShortcut(QKeySequence("Ctrl+="), self, activated=lambda: self.step_zoom(1))
        QShortcut(QKeySequence("Ctrl+-"), self, activated=lambda: self.step_zoom(-1))
        QShortcut(QKeySequence("Ctrl+0"), self, activated=lambda: self.set_zoom("width"))
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self.rotate)
        QShortcut(QKeySequence("Ctrl+C"), self, activated=lambda: self.copy_page(False))
        QShortcut(QKeySequence("Ctrl+Shift+C"), self, activated=lambda: self.copy_page(True))
        QShortcut(QKeySequence("F9"), self, activated=self.toggle_side)
        QShortcut(QKeySequence("Ctrl+W"), self, activated=self.close)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.save_as)
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self.undo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, activated=self.redo)
        QShortcut(QKeySequence("Ctrl+Y"), self, activated=self.redo)
        QShortcut(QKeySequence("Ctrl+Home"), self, activated=lambda: self.go_to(0))
        QShortcut(QKeySequence("Ctrl+End"), self, activated=lambda: self.go_to(self.count() - 1))

    # --- opening -----------------------------------------------------------------------------------------------

    def count(self) -> int:
        return len(self.plan) if self.doc else 0

    def _src(self, index: int) -> tuple[Reader, int]:
        """The reader and page that sit at position index of the plan."""
        entry = self.plan[index]
        return self.sources[int(entry["source"])], int(entry["index"])

    def _points(self, index: int) -> tuple[float, float]:
        """The page's size in points before the view's rotation (its own turn applied)."""
        reader, src = self._src(index)
        w, h = reader.document.pages[src] if reader.document else (1.0, 1.0)
        return (h, w) if int(self.plan[index].get("rotate", 0)) in (90, 270) else (w, h)

    def _ask_password(self, name: str, wrong: bool) -> str | None:
        dialog = PasswordDialog(self, self.lang, name, wrong)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.password.text()

    def open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, say(self.lang, "Open a PDF", "פתיחת PDF"), "",
                                              say(self.lang, "PDF files (*.pdf);;All files (*)",
                                                  "קובצי PDF (*.pdf);;כל הקבצים (*)"))
        if path:
            self.open_path(path)

    def open_path(self, path: str) -> bool:
        self.close_document()
        name = Path(path).name
        password, wrong = "", False
        while True:
            reader = self.reader_factory(path, password=password, sandboxed=self.sandboxed)
            try:
                doc = reader.open()
                break
            except PdfError as exc:
                reader.close()
                if exc.kind == "password":
                    answer = self.ask_password(name, wrong)
                    if answer is None:
                        self.show_message(say(self.lang, "{name} stays closed.", "{name} נשאר סגור.", name=name))
                        return False
                    password, wrong = answer, True
                    continue
                self.show_message(self._error_text(exc, name))
                return False
        self.reader, self.doc = reader, doc
        self.sources = [reader]
        self.plan = [{"source": 0, "index": i, "rotate": 0} for i in range(doc.count)]
        self.undo_stack, self.redo_stack = [], []
        self.field_values = {}
        self.marks, self.pictures, self.picture_cache = [], [], {}
        self.thumb_cache.clear()
        self.modified = False
        self._fill_marks()
        self._load_fields()
        self._title()
        self._fill_side()
        self._build_pages()
        self.update_banner()
        self.status.setText(say(self.lang, "{name} · {n} pages · opened in the sandbox", "{name} · {n} עמודים · נפתח בארגז החול",
                                name=name, n=doc.count) if self.sandboxed else
                            say(self.lang, "{name} · {n} pages", "{name} · {n} עמודים", name=name, n=doc.count))
        self.set_zoom(self.zoom)
        self.go_to(0)
        return True

    def _error_text(self, exc: PdfError, name: str) -> str:
        if exc.kind == "missing":
            return say(self.lang, "There is no file called {name}.", "אין קובץ בשם {name}.", name=name)
        if exc.kind == "sandbox":
            return say(self.lang, "The sandbox (bubblewrap) is missing, so {name} was not opened. D.Ai PDF never "
                                  "opens a file outside it.",
                       "ארגז החול (bubblewrap) חסר, ולכן {name} לא נפתח. D.Ai PDF לעולם לא פותח קובץ מחוצה לו.", name=name)
        if exc.kind in ("dead", "timeout"):
            return say(self.lang, "{name} could not be drawn: the sandboxed helper stopped.",
                       "לא ניתן היה לצייר את {name}: העוזר בארגז החול נעצר.", name=name)
        return say(self.lang, "{name} is not a PDF that can be opened.", "{name} אינו קובץ PDF שניתן לפתוח.", name=name)

    def close_document(self) -> None:
        for source in self.sources:
            source.close()
        if self.reader is not None and self.reader not in self.sources:
            self.reader.close()
        self.reader, self.doc = None, None
        self.sources, self.plan, self.fields, self.field_values = [], [], [], {}
        self.marks, self.pictures, self.picture_cache = [], [], {}
        self.undo_stack, self.redo_stack = [], []
        self.marks_list.clear()
        self.modified = False
        self.thumb_cache.clear()
        self._fill_form_tab()
        self.thumb_timer.stop()
        self.cache.clear()
        self.cache_order.clear()
        self.results.clear()
        for view in self.views:
            self.pages_layout.removeWidget(view)
            view.deleteLater()
        self.views = []
        self.thumbs.clear()
        self.outline.clear()
        self.result_list.clear()
        self.attachments.clear()
        self.banner.hide()
        self.count_label.setText("")
        self.page_field.setText("")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt's name
        if self.modified and not self.confirm_discard():
            event.ignore()
            return
        self.close_document()
        super().closeEvent(event)

    def _confirm_discard(self) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("D.Ai PDF")
        box.setText(say(self.lang, "The changes were not saved. Close anyway?", "השינויים לא נשמרו. לסגור בכל זאת?"))
        box.setStandardButtons(QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        return box.exec() == QMessageBox.StandardButton.Discard

    def _title(self) -> None:
        if self.doc:
            self.setWindowTitle(("• " if self.modified else "") + f"{self.doc.title} · D.Ai PDF")
        else:
            self.setWindowTitle("D.Ai PDF")

    def show_message(self, text: str) -> None:
        self.message.setText(text)
        self.message.show()

    def _fill_side(self) -> None:
        assert self.doc is not None
        self._syncing = True
        self.thumbs.clear()
        for i in range(self.count()):
            entry = self.plan[i]
            label = str(i + 1)
            if entry["source"] == 0 and entry["index"] < len(self.doc.labels) and self.doc.labels[entry["index"]]:
                label = self.doc.labels[entry["index"]]
            item = QListWidgetItem(label)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setToolTip(say(self.lang, "Page {n}", "עמוד {n}", n=i + 1))
            key = (entry["source"], entry["index"], entry.get("rotate", 0))
            if key in self.thumb_cache:
                item.setIcon(self.thumb_cache[key])
            self.thumbs.addItem(item)
        self.thumbs_done = 0
        self.outline.clear()
        parents: dict[int, QTreeWidgetItem] = {}
        for entry in self.doc.outline:
            level = int(entry.get("level", 0))
            item = QTreeWidgetItem([entry.get("title") or "…"])
            item.setData(0, Qt.ItemDataRole.UserRole, int(entry.get("page", -1)))
            parent = parents.get(level - 1)
            if level > 0 and parent is not None:
                parent.addChild(item)
            else:
                self.outline.addTopLevelItem(item)
            parents[level] = item
        self.outline.expandToDepth(0)
        self.attachments.clear()
        for att in self.doc.findings.attachments:
            self.attachments.addItem(f"{att.get('name', '')} · {human_size(int(att.get('size', -1)))}")
        if not self.doc.findings.attachments:
            self.attachments.addItem(say(self.lang, "No attached files", "אין קבצים מצורפים"))
        self._syncing = False

    def _build_pages(self) -> None:
        assert self.doc is not None
        self.message.hide()
        for i in range(self.count()):
            reader, src = self._src(i)
            view = PageView(self, i, reader.document.pages[src] if reader.document else (1.0, 1.0))
            view.extra = int(self.plan[i].get("rotate", 0))
            self.pages_layout.addWidget(view, alignment=Qt.AlignmentFlag.AlignHCenter)
            self.views.append(view)
        self.count_label.setText(say(self.lang, "of {n}", "מתוך {n}", n=self.count()))

    def update_banner(self) -> None:
        assert self.doc is not None
        lines = findings_sentences(self.doc, self.lang)
        if lines:
            self.banner_text.setText("⚠ " + "  ·  ".join(lines))
            self.banner.show()
        else:
            self.banner.hide()

    # --- zoom, rotation, layout --------------------------------------------------------------------------------

    def _zoom_chosen(self, index: int) -> None:
        if index >= 0 and not self._syncing:
            self.set_zoom(str(self.zoom_box.itemData(index)))

    def set_zoom(self, zoom: str) -> None:
        self.zoom = zoom
        self._syncing = True
        for i in range(self.zoom_box.count()):
            if str(self.zoom_box.itemData(i)) == zoom:
                self.zoom_box.setCurrentIndex(i)
        self._syncing = False
        self._relayout()

    def step_zoom(self, direction: int) -> None:
        current = round(self.scale / POINT * 100)
        candidates = sorted(set(ZOOMS) | {current})
        index = candidates.index(current) + direction
        index = max(0, min(len(candidates) - 1, index))
        self.set_zoom(str(candidates[index]))

    def rotate(self) -> None:
        self.rotation = (self.rotation + 90) % 360
        self._relayout()

    def _available_width(self) -> int:
        width = self.scroll.viewport().width() - 2 * MARGIN
        return max(120, width - self.scroll.verticalScrollBar().sizeHint().width())

    def _relayout(self) -> None:
        if not self.doc or not self.views:
            return
        w, h = self._points(min(self.current_page, self.count() - 1))
        if self.rotation in (90, 270):
            w, h = h, w
        if self.zoom == "width":
            self.scale = self._available_width() / max(1.0, w)
        elif self.zoom == "page":
            height = max(120, self.scroll.viewport().height() - 2 * MARGIN)
            self.scale = min(self._available_width() / max(1.0, w), height / max(1.0, h))
        else:
            self.scale = int(self.zoom) / 100 * POINT
        self.scale = max(0.05, min(12.0, self.scale))
        for view in self.views:
            view.placeholder()
        self.render_timer.start()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().resizeEvent(event)
        if self.zoom in ("width", "page"):
            self._relayout()

    # --- rendering ---------------------------------------------------------------------------------------------

    def _visible_pages(self) -> list[int]:
        if not self.views:
            return []
        top = self.scroll.verticalScrollBar().value()
        bottom = top + self.scroll.viewport().height()
        visible = []
        for view in self.views:
            y = view.pos().y()
            if y + view.height() >= top - 200 and y <= bottom + 200:
                visible.append(view.index)
        return visible

    def _render_image(self, index: int, size: QSize) -> QImage | None:
        assert self.reader is not None
        reader, src = self._src(index)
        key = (size.width(), size.height(), id(reader), src)
        cached = self.cache.get(index)
        if cached and cached[0] == key:
            return cached[1]
        try:
            png, _, _ = reader.render(src, size.width(), size.height())
        except PdfError:
            return None
        image = QImage.fromData(png, "PNG")
        if image.isNull():
            return None
        self.cache[index] = (key, image)
        self.cache_order.append(index)
        while len(self.cache_order) > CACHE_PAGES:
            old = self.cache_order.pop(0)
            if old != index and old in self.cache and old not in self.cache_order:
                del self.cache[old]
        return image

    def render_visible(self) -> None:
        if not self.doc or not self.reader:
            return
        for index in self._visible_pages():
            view = self.views[index]
            if view.rendered_key == self.render_key(view):
                continue
            w, h = view.points
            image = self._render_image(index, QSize(max(1, round(w * self.scale)), max(1, round(h * self.scale))))
            if image is None:
                view.setText(say(self.lang, "This page could not be drawn.", "לא ניתן היה לצייר את העמוד הזה."))
                continue
            view.show_image(image)
            if view.links is None:
                reader, src = self._src(index)
                view.links = reader.links(src)
        self._update_current()

    def _scrolled(self, _value: int) -> None:
        self.render_timer.start()
        self._update_current()

    def _update_current(self) -> None:
        if not self.views:
            return
        middle = self.scroll.verticalScrollBar().value() + self.scroll.viewport().height() // 3
        current = 0
        for view in self.views:
            if view.pos().y() <= middle:
                current = view.index
        if current != self.current_page or not self.page_field.text():
            self.current_page = current
            self.page_field.setText(str(current + 1))
            self._syncing = True
            self.thumbs.setCurrentRow(current)
            self._syncing = False
            self._describe_page(current)

    def _describe_page(self, index: int) -> None:
        """The current page's text is its accessible description, so a screen reader can read it."""
        if not self.reader or not self.doc or index >= self.count():
            return
        reader, src = self._src(index)
        try:
            text = reader.text(src)
        except PdfError:
            return
        self.views[index].setAccessibleDescription(text[:20000])
        self.scroll.setAccessibleDescription(say(self.lang, "Page {n}: {text}", "עמוד {n}: {text}", n=index + 1,
                                                 text=text[:4000]))

    def go_to(self, index: int) -> None:
        if not self.views:
            return
        index = max(0, min(len(self.views) - 1, index))
        view = self.views[index]
        self.scroll.verticalScrollBar().setValue(max(0, view.pos().y() - MARGIN // 2))
        self.current_page = index
        self.page_field.setText(str(index + 1))
        self.render_timer.start()
        self._describe_page(index)

    def _page_typed(self) -> None:
        text = self.page_field.text().strip()
        if self.doc and text and text in self.doc.labels:
            self.go_to(self.doc.labels.index(text))
            return
        try:
            self.go_to(int(text) - 1)
        except ValueError:
            self.page_field.setText(str(self.current_page + 1))

    def _outline_chosen(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        page = item.data(0, Qt.ItemDataRole.UserRole)
        if page is not None and int(page) >= 0:
            self.go_to(int(page))

    def toggle_side(self) -> None:
        self.side.setVisible(not self.side.isVisible())
        if self.side.isVisible() and self.side.currentIndex() == 0:
            self._thumbnails_start()

    # --- thumbnails --------------------------------------------------------------------------------------------

    def _thumbnails_start(self) -> None:
        if self.doc and self.thumbs_done < min(self.count(), MAX_THUMBS) and not self.thumb_timer.isActive():
            self.thumb_timer.start()

    def _next_thumbnail(self) -> None:
        if not self.doc or not self.reader or self.thumbs_done >= min(self.count(), MAX_THUMBS):
            self.thumb_timer.stop()
            return
        i = self.thumbs_done
        self.thumbs_done += 1
        entry = self.plan[i]
        key = (entry["source"], entry["index"], entry.get("rotate", 0))
        if key in self.thumb_cache:
            self.thumbs.item(i).setIcon(self.thumb_cache[key])
            return
        reader, src = self._src(i)
        w, h = reader.document.pages[src] if reader.document else (1.0, 1.0)
        height = max(1, round(THUMB_WIDTH * h / max(1.0, w)))
        try:
            png, _, _ = reader.render(src, THUMB_WIDTH, height)
        except PdfError:
            return
        pixmap = QPixmap.fromImage(QImage.fromData(png, "PNG"))
        if entry.get("rotate", 0):
            from PyQt6.QtGui import QTransform
            pixmap = pixmap.transformed(QTransform().rotate(int(entry["rotate"])))
        if not pixmap.isNull():
            self.thumb_cache[key] = QIcon(pixmap)
            self.thumbs.item(i).setIcon(self.thumb_cache[key])

    # --- search ------------------------------------------------------------------------------------------------

    def search(self) -> None:
        needle = self.search_field.text().strip()
        self.results = []
        self.result_list.clear()
        for view in self.views:
            if view.highlights:
                view.highlights = []
                view.rendered_key = None
        if not needle or not self.doc or not self.reader:
            self.render_timer.start()
            return
        for page in range(self.count()):
            reader, src = self._src(page)
            try:
                text = reader.text(src, as_extracted=True)
            except PdfError:
                continue
            for at in find_all(text, needle):
                self.results.append((page, at, len(needle)))
                before = text[max(0, at - SEARCH_CONTEXT):at].replace("\n", " ")
                after = text[at + len(needle):at + len(needle) + SEARCH_CONTEXT].replace("\n", " ")
                self.result_list.addItem(say(self.lang, "p. {n}: …{before}{hit}{after}…", "עמ׳ {n}: …{before}{hit}{after}…",
                                             n=page + 1, before=before, hit=text[at:at + len(needle)], after=after))
                if len(self.results) >= MAX_RESULTS:
                    break
            if len(self.results) >= MAX_RESULTS:
                break
        self.side.setCurrentIndex(2)
        if not self.side.isVisible():
            self.side.show()
        if self.results:
            self.result_list.setCurrentRow(0)
            self.status.setText(say(self.lang, "{n} results for “{q}”", "{n} תוצאות ל-“{q}”", n=len(self.results), q=needle))
        else:
            self.status.setText(say(self.lang, "Nothing found for “{q}”", "לא נמצא דבר עבור “{q}”", q=needle))
            self.render_timer.start()

    def _result_chosen(self, row: int) -> None:
        if row < 0 or row >= len(self.results) or not self.reader:
            return
        page, start, length = self.results[row]
        if page >= self.count():
            return
        reader, src = self._src(page)
        rects = reader.select(src, start, length)
        for view in self.views:
            if view.highlights and view.index != page:
                view.highlights = []
                view.rendered_key = None
        self.views[page].highlights = rects
        self.views[page].rendered_key = None
        self.go_to(page)
        if rects:
            y = self.views[page].pos().y() + self.views[page].to_pixels(rects[0]).y() - self.scroll.viewport().height() // 3
            self.scroll.verticalScrollBar().setValue(max(0, y))
        self.render_timer.start()

    def next_result(self) -> None:
        if self.results:
            self.result_list.setCurrentRow((self.result_list.currentRow() + 1) % len(self.results))

    # --- links, copy, info, print ------------------------------------------------------------------------------

    def follow_link(self, link: dict) -> None:
        url = str(link.get("url") or "")
        if not url:
            page = int(link.get("page", -1))
            if page >= 0:
                self.go_to(page)
            return
        allowed = url.lower().startswith(("http://", "https://", "mailto:"))
        dialog = LinkDialog(self, self.lang, url, allowed)
        if dialog.exec() == QDialog.DialogCode.Accepted and allowed:
            self.open_url(url)

    def copy_page(self, as_extracted: bool) -> None:
        if not self.reader or not self.doc:
            return
        reader, src = self._src(self.current_page)
        try:
            text = reader.text(src, as_extracted=as_extracted)
        except PdfError:
            return
        QGuiApplication.clipboard().setText(text)
        self.status.setText(say(self.lang, "The text of page {n} was copied ({c} characters).",
                                "הטקסט של עמוד {n} הועתק ({c} תווים).", n=self.current_page + 1, c=len(text)))

    def show_info(self) -> None:
        if self.doc:
            InfoDialog(self, self.lang, self.doc, self.sandboxed).exec()

    def print_(self) -> None:
        if not self.doc or not self.reader:
            return
        try:
            from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
        except ImportError:
            self.status.setText(say(self.lang, "Printing is not available on this computer.", "הדפסה אינה זמינה במחשב הזה."))
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.print_to(printer)

    def print_to(self, printer) -> int:
        """Every page drawn by the helper at the printer's resolution; returns how many were printed."""
        assert self.doc is not None and self.reader is not None
        painter = QPainter(printer)
        dpi = max(72, printer.resolution())
        printed = 0
        for index in range(self.count()):
            reader, src = self._src(index)
            w, h = reader.document.pages[src] if reader.document else (1.0, 1.0)
            if index:
                printer.newPage()
            try:
                png, _, _ = reader.render(src, round(w * dpi / 72), round(h * dpi / 72))
            except PdfError:
                continue
            image = QImage.fromData(png, "PNG")
            if image.isNull():
                continue
            if self.plan[index].get("rotate", 0):
                from PyQt6.QtGui import QTransform
                image = image.transformed(QTransform().rotate(int(self.plan[index]["rotate"])))
            target = painter.viewport()
            scaled = image.size().scaled(target.size(), Qt.AspectRatioMode.KeepAspectRatio)
            painter.drawImage(QRectF(target.x(), target.y(), scaled.width(), scaled.height()), image)
            printed += 1
        painter.end()
        return printed

    # --- editing (docs/PDF.md stage 2) -------------------------------------------------------------------------

    def _snapshot(self) -> None:
        self.undo_stack.append(([dict(e) for e in self.plan], dict(self.field_values), [dict(m) for m in self.marks]))
        del self.undo_stack[:-100]
        self.redo_stack.clear()

    def render_key(self, view: PageView) -> tuple:
        return (self.scale, self.rotation, tuple(view.highlights), tuple(repr(m) for m in self.marks_for(view.index)))

    def marks_for(self, index: int) -> list[dict]:
        """The marks on the source page shown at position index."""
        if not self.plan or index >= len(self.plan):
            return []
        entry = self.plan[index]
        return [m for m in self.marks if m["source"] == entry["source"] and m["index"] == entry["index"]]

    def picture(self, number: int) -> QPixmap | None:
        if not 0 <= number < len(self.pictures):
            return None
        if number not in self.picture_cache:
            self.picture_cache[number] = QPixmap(self.pictures[number])
        return self.picture_cache[number]

    def _apply_plan(self, current: int) -> None:
        """The views, thumbnails and counters follow the plan; the file itself is untouched until Save."""
        self.cache.clear()
        self.cache_order.clear()
        self.results.clear()
        self.result_list.clear()
        for view in self.views:
            self.pages_layout.removeWidget(view)
            view.deleteLater()
        self.views = []
        self.thumb_timer.stop()
        self._fill_side()
        self._fill_marks()
        if self.plan:
            self._build_pages()
            self._relayout()
            self.go_to(max(0, min(current, self.count() - 1)))
            if self.side.isVisible() and self.side.currentIndex() == 0:
                self._thumbnails_start()
        self.modified = True
        self._title()
        self.status.setText(say(self.lang, "{n} pages · not saved yet (Ctrl+S)", "{n} עמודים · עדיין לא נשמר (Ctrl+S)", n=self.count()))

    def rotate_page(self, index: int | None = None) -> None:
        if not self.doc:
            return
        index = self.current_page if index is None else index
        self._snapshot()
        self.plan[index]["rotate"] = (int(self.plan[index].get("rotate", 0)) + 90) % 360
        self._apply_plan(index)

    def move_page(self, delta: int, index: int | None = None) -> None:
        if not self.doc:
            return
        index = self.current_page if index is None else index
        target = index + delta
        if not 0 <= target < self.count():
            return
        self._snapshot()
        self.plan[index], self.plan[target] = self.plan[target], self.plan[index]
        self._apply_plan(target)

    def delete_page(self, index: int | None = None) -> None:
        if not self.doc or self.count() <= 1:
            self.status.setText(say(self.lang, "A file keeps at least one page.", "קובץ שומר לפחות עמוד אחד."))
            return
        index = self.current_page if index is None else index
        self._snapshot()
        del self.plan[index]
        self._apply_plan(index)

    def insert_dialog(self) -> None:
        if not self.doc:
            return
        path, _ = QFileDialog.getOpenFileName(self, say(self.lang, "Insert pages from a PDF", "הוספת עמודים מקובץ PDF"), "",
                                              say(self.lang, "PDF files (*.pdf);;All files (*)", "קובצי PDF (*.pdf);;כל הקבצים (*)"))
        if path:
            self.insert_pdf(path)

    def insert_pdf(self, path: str, at: int | None = None) -> bool:
        """Every page of another file, after the current page (or at `at`); the file opens in its own sandbox."""
        if not self.doc:
            return False
        name = Path(path).name
        password, wrong = "", False
        while True:
            reader = self.reader_factory(path, password=password, sandboxed=self.sandboxed)
            try:
                other = reader.open()
                break
            except PdfError as exc:
                reader.close()
                if exc.kind == "password":
                    answer = self.ask_password(name, wrong)
                    if answer is None:
                        return False
                    password, wrong = answer, True
                    continue
                self.status.setText(self._error_text(exc, name))
                return False
        self._snapshot()
        self.sources.append(reader)
        source = len(self.sources) - 1
        at = self.current_page + 1 if at is None else max(0, min(self.count(), at))
        self.plan[at:at] = [{"source": source, "index": i, "rotate": 0} for i in range(other.count)]
        self._apply_plan(at)
        self.status.setText(say(self.lang, "{n} pages from {name} were inserted · not saved yet (Ctrl+S)",
                                "{n} עמודים מ-{name} נוספו · עדיין לא נשמר (Ctrl+S)", n=other.count, name=name))
        return True

    def undo(self) -> None:
        if not self.undo_stack:
            return
        self.redo_stack.append(([dict(e) for e in self.plan], dict(self.field_values), [dict(m) for m in self.marks]))
        self.plan, self.field_values, self.marks = self.undo_stack.pop()
        self._apply_plan(self.current_page)
        self._fill_form_tab()
        self._fill_marks()

    def redo(self) -> None:
        if not self.redo_stack:
            return
        self.undo_stack.append(([dict(e) for e in self.plan], dict(self.field_values), [dict(m) for m in self.marks]))
        self.plan, self.field_values, self.marks = self.redo_stack.pop()
        self._apply_plan(self.current_page)
        self._fill_form_tab()
        self._fill_marks()

    # --- marks (docs/PDF.md stage 2b) --------------------------------------------------------------------------

    def set_tool(self, tool: str) -> None:
        if tool == "stamp" and self.tool != "stamp":
            path, _ = QFileDialog.getOpenFileName(self, say(self.lang, "A picture to stamp (your signature, a logo)", "תמונה לחותמת (החתימה שלכם, לוגו)"),
                                                  "", say(self.lang, "Pictures (*.png *.jpg *.jpeg)", "תמונות (*.png *.jpg *.jpeg)"))
            if not path:
                tool = "select"
            else:
                self.stamp_path = path
        self.tool = tool
        for name, button in self.tool_buttons.items():
            button.setChecked(name == tool)
        self.status.setText({
            "highlight": say(self.lang, "Drag over the words to highlight.", "גררו על המילים להדגשה."),
            "underline": say(self.lang, "Drag over the words to underline.", "גררו על המילים לקו תחתון."),
            "strikeout": say(self.lang, "Drag over the words to strike through.", "גררו על המילים לקו חוצה."),
            "note": say(self.lang, "Click where the note goes.", "לחצו היכן שההערה תהיה."),
            "text": say(self.lang, "Drag a box for the text.", "גררו תיבה לטקסט."),
            "stamp": say(self.lang, "Drag a box for the picture.", "גררו תיבה לתמונה."),
            "redact": say(self.lang, "Drag over what must disappear. The page becomes a picture when you save.",
                          "גררו על מה שחייב להיעלם. העמוד הופך לתמונה בשמירה."),
        }.get(tool, ""))

    def choose_color(self) -> None:
        from PyQt6.QtWidgets import QColorDialog
        colour = QColorDialog.getColor(QColor(self.tool_color), self, say(self.lang, "Colour of the next mark", "צבע הסימון הבא"))
        if colour.isValid():
            self.tool_color = colour.name()
            self._show_color()

    def _show_color(self) -> None:
        """The colour as a swatch icon (never as text colour: a yellow letter fails contrast on any theme)."""
        swatch = QPixmap(18, 18)
        swatch.fill(QColor(self.tool_color))
        self.color_button.setIcon(QIcon(swatch))
        self.color_button.setToolTip(self.tool_color)

    def drawn(self, index: int, rect: QRect) -> None:
        """A drag on page `index` with the current tool."""
        if self.tool == "select" or index >= len(self.views):
            return
        view = self.views[index]
        if self.tool == "note":
            x, y = view.to_points(rect.topLeft())
            points = (round(x, 2), round(y, 2), 20.0, 20.0)
        else:
            points = view.rect_points(rect)
            if points[2] < 2 or points[3] < 2:
                return
        kind = self.tool
        if kind == "redact":
            self.add_mark(kind, index, points)
            return
        if kind == "text" or kind == "note":
            text = self.ask_text(kind)
            if text is None:
                return
            self.add_mark(kind, index, points, text=text)
        elif kind == "stamp":
            picture = self.add_picture(getattr(self, "stamp_path", ""))
            if picture < 0:
                return
            self.add_mark(kind, index, points, image=picture)
        else:
            self.add_mark(kind, index, points)

    def ask_text(self, kind: str) -> str | None:
        from PyQt6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getMultiLineText(self, say(self.lang, "Text", "טקסט"),
                                                  say(self.lang, "The note's text:", "הטקסט של ההערה:") if kind == "note"
                                                  else say(self.lang, "The text to place (Hebrew is fine):", "הטקסט למיקום (גם עברית):"))
        return text if ok and text.strip() else None

    def add_picture(self, path: str) -> int:
        if not path or not Path(path).is_file():
            return -1
        if path in self.pictures:
            return self.pictures.index(path)
        self.pictures.append(path)
        return len(self.pictures) - 1

    def add_mark(self, kind: str, index: int, rect: tuple[float, float, float, float], text: str = "", image: int = -1,
                 size: float = 12.0) -> dict:
        """A mark on the source page at position index; shown at once, written by the sandbox on save."""
        entry = self.plan[index]
        mark = {"source": entry["source"], "index": entry["index"], "kind": kind, "rect": [float(v) for v in rect],
                "color": self.tool_color if kind not in ("text", "redact") else "#111111" if kind == "text" else "#000000",
                "text": text, "image": image, "size": size}
        self._snapshot()
        self.marks.append(mark)
        self._marks_changed(index)
        return mark

    def remove_mark(self) -> None:
        item = self.marks_list.currentItem()
        if item is None:
            return
        number = int(item.data(Qt.ItemDataRole.UserRole))
        if 0 <= number < len(self.marks):
            self._snapshot()
            del self.marks[number]
            self._marks_changed(self.current_page)

    def _marks_changed(self, index: int) -> None:
        for view in self.views:
            view.rendered_key = None
        self.modified = True
        self._title()
        self._fill_marks()
        self.render_timer.start()
        self.status.setText(say(self.lang, "{n} marks · not saved yet (Ctrl+S)", "{n} סימונים · עדיין לא נשמר (Ctrl+S)", n=len(self.marks)))

    def _fill_marks(self) -> None:
        self.marks_list.clear()
        names = {"highlight": say(self.lang, "Highlight", "הדגשה"), "underline": say(self.lang, "Underline", "קו תחתון"),
                 "strikeout": say(self.lang, "Strike through", "קו חוצה"), "note": say(self.lang, "Note", "הערה"),
                 "text": say(self.lang, "Text", "טקסט"), "stamp": say(self.lang, "Stamp", "חותמת"),
                 "redact": say(self.lang, "Black box", "תיבה שחורה")}
        for number, mark in enumerate(self.marks):
            position = next((i for i, e in enumerate(self.plan) if e["source"] == mark["source"] and e["index"] == mark["index"]), -1)
            where = say(self.lang, "p. {n}", "עמ׳ {n}", n=position + 1) if position >= 0 else say(self.lang, "(page removed)", "(העמוד הוסר)")
            item = QListWidgetItem(f"{names.get(mark['kind'], mark['kind'])} · {where}" + (f" · {mark['text'][:40]}" if mark.get("text") else ""))
            item.setData(Qt.ItemDataRole.UserRole, number)
            item.setData(Qt.ItemDataRole.UserRole + 1, max(0, position))
            self.marks_list.addItem(item)

    def _marks_for_save(self) -> list[dict]:
        out = []
        for position, entry in enumerate(self.plan):
            for mark in self.marks:
                if mark["kind"] != "redact" and mark["source"] == entry["source"] and mark["index"] == entry["index"]:
                    out.append({"page": position, "kind": mark["kind"], "rect": mark["rect"], "color": mark["color"],
                                "text": mark.get("text", ""), "image": mark.get("image", -1), "size": mark.get("size", 12)})
        return out

    def _redactions_for_save(self) -> list[dict]:
        return [{"page": position, "rect": mark["rect"]} for position, entry in enumerate(self.plan) for mark in self.marks
                if mark["kind"] == "redact" and mark["source"] == entry["source"] and mark["index"] == entry["index"]]

    def _clean_changed(self) -> None:
        if self.doc and not self.modified:
            self.modified = True
            self._title()

    def _save_options(self) -> dict:
        """Everything the Clean tab and the marks add to a save (or a measurement)."""
        return {"annotations": self._marks_for_save(), "pictures": list(self.pictures), "redactions": self._redactions_for_save(),
                "ocr": {"pages": "all" if self.ocr_all_box.isChecked() else "scans", "langs": ocr_langs(self.lang)}
                if self.ocr_box.isChecked() else None, "strip_metadata": self.strip_box.isChecked(),
                "compress": str(self.compress_choice.currentData() or "")}

    def check_size(self) -> int:
        """Runs the save in the sandbox without keeping it, and says what the file would weigh. Returns the bytes."""
        if not self.doc:
            return 0
        self.status.setText(say(self.lang, "Measuring in the sandbox…", "מודד בארגז החול…"))
        QApplication.processEvents()
        try:
            answer = self.editor.measure([s.path for s in self.sources], pages=[dict(e) for e in self.plan],
                                         fields=dict(self.field_values), passwords=[s.password for s in self.sources],
                                         **self._save_options())
        except EditError as exc:
            self.status.setText(self._edit_error_text(exc))
            return 0
        self.status.setText(say(self.lang, "Now {before}; after saving {after} ({n} pictures made smaller)",
                                "עכשיו {before}; אחרי השמירה {after} ({n} תמונות הוקטנו)",
                                before=human_size(answer.get("before", 0)), after=human_size(answer.get("bytes", 0)), n=answer.get("compressed", 0)))
        return int(answer.get("bytes", 0))

    def export_dialog(self) -> None:
        if not self.doc:
            return
        folder = QFileDialog.getExistingDirectory(self, say(self.lang, "A folder for the pictures", "תיקייה לתמונות"), "")
        if folder:
            self.export_to(folder)

    def export_to(self, folder: str, dpi: int = 150) -> list[str]:
        if not self.doc:
            return []
        self.status.setText(say(self.lang, "Drawing the pages in the sandbox…", "מצייר את העמודים בארגז החול…"))
        QApplication.processEvents()
        try:
            files = self.editor.export([s.path for s in self.sources], folder, pages=[dict(e) for e in self.plan], dpi=dpi,
                                       passwords=[s.password for s in self.sources])
        except EditError as exc:
            self.status.setText(self._edit_error_text(exc))
            return []
        self.status.setText(say(self.lang, "{n} pictures written to {folder}", "{n} תמונות נכתבו ל-{folder}", n=len(files), folder=folder))
        return files

    # --- forms -------------------------------------------------------------------------------------------------

    def _load_fields(self) -> None:
        self.fields = []
        if self.reader is not None:
            try:
                self.fields = self.editor.fields(self.reader.path, self.reader.password)
            except EditError as exc:
                self.fields = []
                if exc.kind == "sandbox":
                    self.status.setText(self._error_text(PdfError("sandbox"), Path(self.reader.path).name))
        self._fill_form_tab()

    def _fill_form_tab(self) -> None:
        while self.form_layout.count():
            item = self.form_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.field_widgets = {}
        if not self.fields:
            hint = QLabel(say(self.lang, "No form fields in this file.", "אין שדות טופס בקובץ הזה.") if self.doc else "")
            hint.setObjectName("FormHint")
            hint.setWordWrap(True)
            self.form_layout.addRow(hint)
            return
        hint = QLabel(say(self.lang, "Fill in, then save (Ctrl+S). Nothing is sent anywhere.",
                          "מלאו, ואז שמרו (Ctrl+S). שום דבר לא נשלח לשום מקום."))
        hint.setObjectName("FormHint")
        hint.setWordWrap(True)
        self.form_layout.addRow(hint)
        for field in self.fields:
            name = str(field["name"])
            value = self.field_values.get(name, field.get("value"))
            label = QLabel(name + (" *" if field.get("required") else ""))
            label.setWordWrap(True)
            widget: QWidget
            if field["kind"] == "checkbox":
                box = QCheckBox(say(self.lang, "Checked", "מסומן"))
                box.setChecked(bool(value))
                box.toggled.connect(lambda on, n=name: self._field_changed(n, bool(on)))
                widget = box
            elif field["kind"] in ("radio", "choice"):
                combo = QComboBox()
                if field["kind"] == "radio":
                    combo.addItem(say(self.lang, "(none)", "(ללא)"), "Off")
                    for option in field.get("options", []):
                        combo.addItem(str(option), str(option))
                else:
                    for option in field.get("options", []):
                        export, shown = (option[0], option[1]) if isinstance(option, list) else (str(option), str(option))
                        combo.addItem(str(shown), str(export))
                at = combo.findData(str(value))
                combo.setCurrentIndex(max(0, at))
                combo.currentIndexChanged.connect(lambda _i, n=name, c=combo: self._field_changed(n, str(c.currentData())))
                widget = combo
            elif field.get("multiline"):
                text = QPlainTextEdit()
                text.setPlainText(str(value or ""))
                text.setFixedHeight(90)
                text.textChanged.connect(lambda n=name, t=text: self._field_changed(n, t.toPlainText()))
                widget = text
            else:
                line = QLineEdit(str(value or ""))
                line.textEdited.connect(lambda text, n=name: self._field_changed(n, text))
                widget = line
            widget.setAccessibleName(name)
            widget.setEnabled(not field.get("readonly"))
            label.setBuddy(widget)
            self.form_layout.addRow(label, widget)
            self.field_widgets[name] = widget
        self.flatten_box = QCheckBox(say(self.lang, "Flatten when saving (the form can no longer be edited)",
                                         "שיטוח בשמירה (לא ניתן יהיה לערוך את הטופס יותר)"))
        self.flatten_box.setAccessibleName(self.flatten_box.text())
        self.form_layout.addRow(self.flatten_box)

    def _field_changed(self, name: str, value: object) -> None:
        self.field_values[name] = value
        if not self.modified:
            self.modified = True
            self._title()

    # --- saving ------------------------------------------------------------------------------------------------

    def save_as(self) -> None:
        if not self.doc or not self.reader:
            return
        suggested = str(Path(self.reader.path).with_name(Path(self.reader.path).stem + "-edited.pdf"))
        path, _ = QFileDialog.getSaveFileName(self, say(self.lang, "Save the PDF as", "שמירת ה-PDF בשם"), suggested,
                                              say(self.lang, "PDF files (*.pdf)", "קובצי PDF (*.pdf)"))
        if path:
            self.save_to(path)

    def save_to(self, path: str) -> bool:
        """The plan and the form, written by the sandboxed editor; then the saved file is opened here."""
        if not self.doc or not self.reader:
            return False
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        flatten = bool(getattr(self, "flatten_box", None) and self.flatten_box.isChecked())
        self.status.setText(say(self.lang, "Saving in the sandbox…", "שומר בארגז החול…"))
        QApplication.processEvents()
        try:
            answer = self.editor.save([s.path for s in self.sources], path, pages=[dict(e) for e in self.plan],
                                      fields=dict(self.field_values), flatten=flatten,
                                      passwords=[s.password for s in self.sources], **self._save_options())
        except EditError as exc:
            self.status.setText(self._edit_error_text(exc))
            return False
        self.modified = False
        saved = Path(path).name
        self.open_path(path)
        self.status.setText(say(self.lang, "Saved {name} · {n} pages", "נשמר {name} · {n} עמודים", name=saved, n=answer.get("pages", 0)))
        return True

    def _edit_error_text(self, exc: EditError) -> str:
        if exc.kind == "sandbox":
            return self._error_text(PdfError("sandbox"), "")
        if exc.kind == "timeout":
            return say(self.lang, "Saving took too long and was stopped; nothing was written.",
                       "השמירה ארכה יותר מדי ונעצרה; שום דבר לא נכתב.")
        if exc.kind == "missing":
            return say(self.lang, "One of the files is gone; nothing was written.", "אחד הקבצים נעלם; שום דבר לא נכתב.")
        return say(self.lang, "The file could not be saved ({detail}); nothing was written.",
                   "לא ניתן היה לשמור את הקובץ ({detail}); שום דבר לא נכתב.", detail=exc.detail or exc.kind)


def main(argv: list[str] | None = None, path: str | None = None) -> int:
    app = QApplication(list(sys.argv if argv is None else argv))
    app.setDesktopFileName(APP_ID)
    window = PdfWindow(path)
    window.show()
    return app.exec()
