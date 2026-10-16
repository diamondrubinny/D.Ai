# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""D.Ai Forge window: ask for something, review it, and the system does it.

  ask ──► recipe / AI recipe ──► plan cards ──► confirm ──► polkit ──► done (undo)
      └─► app (local AI) ──► live code ──► permissions ──► run in the sandbox

The window never bypasses anything: plans go through the same D.Ai Tune
planner, root helper and journal as dai-tune; apps go through the same checks
and bubblewrap sandbox as dai-forge. Long work runs in background threads.
"""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import QObject, QPoint, QRect, QSize, Qt, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont, QFontDatabase, QGuiApplication, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QLayout, QLineEdit, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from dai_tune.ai import model_installed
from dai_tune.catalog import CATALOG
from dai_tune.cli import apply_plan, cmd_undo
from dai_tune.context import Context, detect_lang
from dai_tune.planner import Plan, build_plan

from . import __author__, __version__, apps
from .ai import author_recipe, generate_app, partial_code
from .cli import is_admin, policy
from .intent import Intent, classify
from .recipes import Recipe, install_requests, load_library, remove_requests, save_user_recipe

APP_ID = "dai-forge"
LOGO = Path(os.environ.get("DAI_BRANDING_DIR", "/usr/share/dai/branding")) / "dai-logo.svg"

# D.Ai Night tokens (docs/DESIGN.md §2).
BG_900, BG_800, SURFACE, BORDER = "#0B1020", "#141B33", "#1C2547", "#2A3563"
TEXT, MUTED, ACCENT, ACCENT_STRONG, ACCENT_2, ACCENT_SOFT = "#E6E9F5", "#9AA3C7", "#7C5CFF", "#5B3FD6", "#22D3EE", "#B8A6FF"
OK_GREEN, WARN_AMBER, DANGER = "#34D399", "#FBBF24", "#F87171"

STYLE = f"""
QWidget#Forge {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {BG_900}, stop:1 #10173A); }}
QWidget {{ color: {TEXT}; font-size: 11pt; }}
QLabel#Title {{ font-size: 20pt; font-weight: 700; }}
QLabel#Subtitle, QLabel#Muted {{ color: {MUTED}; }}
QLabel#Section {{ color: {ACCENT_SOFT}; font-weight: 700; font-size: 10pt; letter-spacing: 1px; }}
QLabel#Badge {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 9px; padding: 2px 10px; color: {ACCENT_SOFT}; }}
QLabel#BadgeAI {{ background: rgba(124, 92, 255, 0.25); border: 1px solid {ACCENT}; border-radius: 9px; padding: 2px 10px; color: #FFFFFF; }}
QFrame#Prompt {{ background: {BG_800}; border: 1px solid {BORDER}; border-radius: 16px; }}
QFrame#Prompt[focused="true"] {{ border: 2px solid {ACCENT_2}; }}
QLineEdit#Ask {{ background: transparent; border: none; font-size: 14pt; padding: 10px 6px; selection-background-color: {ACCENT_STRONG}; }}
QPushButton {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; padding: 8px 16px; }}
QPushButton:hover {{ border: 1px solid {ACCENT}; background: rgba(124, 92, 255, 0.18); }}
QPushButton:focus {{ border: 2px solid {ACCENT_2}; }}
QPushButton:disabled {{ color: #5D668C; border: 1px solid {BORDER}; background: {BG_800}; }}
QPushButton#Primary {{ color: #FFFFFF; font-weight: 700; border: none;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT_STRONG}, stop:1 #4C8DF0); }}
QPushButton#Primary:hover {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT}, stop:1 {ACCENT_2}); }}
QPushButton#Primary:disabled {{ background: {SURFACE}; color: #5D668C; }}
QPushButton#Chip {{ border-radius: 15px; padding: 6px 14px; background: rgba(28, 37, 71, 0.85); }}
QFrame#Card {{ background: rgba(20, 27, 51, 0.92); border: 1px solid {BORDER}; border-radius: 14px; }}
QFrame#Step {{ background: {BG_800}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame#Warn {{ background: rgba(251, 191, 36, 0.10); border: 1px solid {WARN_AMBER}; border-radius: 12px; }}
QLineEdit#Confirm {{ background: {BG_900}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 10px; }}
QLineEdit#Confirm:focus {{ border: 2px solid {ACCENT_2}; }}
QPlainTextEdit#Code {{ background: #070B17; border: 1px solid {BORDER}; border-radius: 12px; padding: 8px;
    font-family: "Noto Sans Mono", monospace; font-size: 10pt; color: #CFE8FF; }}
QToolButton#Mic {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; padding: 7px; }}
QToolButton#Mic:hover {{ border: 1px solid {ACCENT}; }}
QToolButton#Mic:focus {{ border: 2px solid {ACCENT_2}; }}
QToolButton#Mic[recording="true"] {{ background: #B4233A; border: 2px solid {DANGER}; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid {BORDER}; background: {BG_900}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border: 1px solid {ACCENT}; }}
QCheckBox:focus {{ color: {ACCENT_2}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {ACCENT}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; height: 0; }}
QFrame#Actions {{ border-top: 1px solid {BORDER}; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
"""

STRINGS = {
    "title": ("D.Ai Forge", "D.Ai Forge"),
    "subtitle": ("Tell the computer what it should be able to do — it builds and sets it up for you.",
                 "כתבו מה המחשב צריך לדעת לעשות, והוא יבנה ויקים את זה בשבילכם."),
    "placeholder": ("e.g. install antivirus · build an app for a shopping list", "למשל: תתקין אנטי וירוס · תבנה אפליקציה לרשימת קניות"),
    "go": ("Create ✦", "צור ✦"),
    "ask_name": ("What should the computer do?", "מה המחשב צריך לעשות?"),
    "admin": ("Administrator", "מנהל"),
    "not_admin": ("Only an administrator can add capabilities. You can still look around.",
                  "רק מנהל המחשב יכול להוסיף יכולות. אפשר לעיין."),
    "ideas": ("IDEAS", "רעיונות"),
    "recipes": ("READY TO SET UP", "מוכן להקמה"),
    "my_apps": ("MY APPS", "האפליקציות שלי"),
    "no_apps": ("No apps yet — ask for one above.", "עדיין אין אפליקציות. בקשו אחת למעלה."),
    "run": ("Run ▶", "הפעלה ▶"),
    "setup": ("Set up", "הקמה"),
    "remove": ("Remove", "הסרה"),
    "cancel": ("Back", "חזרה"),
    "plan_of": ("What will change", "מה ישתנה"),
    "weakens": ("This lowers security. Type “yes” to confirm:", "זה מחליש את האבטחה. הקלידו „כן” לאישור:"),
    "ai_recipe": ("Written by the local AI — review every step", "נכתב ע״י ה־AI המקומי — בדקו כל צעד"),
    "ai_reviewed": ("I reviewed all the steps", "בדקתי את כל הצעדים"),
    "working": ("Working on it…", "עובד על זה…"),
    "applying": ("Setting it up. Enter the administrator password when asked.", "מקים. הזינו את סיסמת המנהל כשתתבקשו."),
    "writing_recipe": ("The local AI is writing a recipe…", "ה־AI המקומי כותב מתכון…"),
    "writing_app": ("The local AI is writing your app — on this computer, nothing leaves it.",
                    "ה־AI המקומי כותב את האפליקציה, במחשב הזה. שום דבר לא יוצא ממנו."),
    "done": ("Done ✓", "בוצע ✓"),
    "done_recipe": ("Everything is set up. You can undo it at any time.", "הכל הוקם. אפשר לבטל בכל רגע."),
    "undo": ("Undo", "ביטול השינוי"),
    "undone": ("Undone. The system is back to how it was.", "בוטל. המערכת חזרה למצב הקודם."),
    "failed": ("Something went wrong", "משהו השתבש"),
    "try_again": ("Try again", "לנסות שוב"),
    "app_ready": ("Your app is ready", "האפליקציה מוכנה"),
    "app_where": ("It is in the Start menu. It runs in a sandbox: no internet and no access to your files unless you allow it.",
                  "היא בתפריט התחל. היא רצה בארגז חול: בלי אינטרנט ובלי גישה לקבצים שלכם, אלא אם תאשרו."),
    "perm_network": ("Allow internet access", "לאפשר גישה לאינטרנט"),
    "perm_documents": ("Allow access to ~/Documents", "לאפשר גישה ל־~/Documents"),
    "findings": ("Worth knowing about the code:", "כדאי לדעת על הקוד:"),
    "open_code": ("Open the code", "פתיחת הקוד"),
    "change": ("Change it…", "לשנות…"),
    "older": ("Previous version", "לגרסה הקודמת"),
    "no_model": ("Building needs a local AI model (about 1.1 GB, downloaded once and verified).",
                 "בנייה דורשת מודל AI מקומי (כ־1.1GB, הורדה חד־פעמית עם אימות)."),
    "get_model": ("Download the coding model", "הורדת מודל הקוד"),
    "downloading": ("Downloading and verifying the model…", "מוריד ומאמת את המודל…"),
    "no_match": ("There is no ready recipe for this, and the local AI is not installed yet.",
                 "אין מתכון מוכן לזה, וה־AI המקומי עוד לא מותקן."),
    "footer": ("Runs on this computer · system changes need the administrator password · every change can be undone",
               "רץ במחשב הזה · שינויי מערכת דורשים סיסמת מנהל · אפשר לבטל כל שינוי"),
    "lines": ("lines", "שורות"),
}
IDEAS = {
    "he": [("🛡", "תתקין אנטי וירוס"), ("🔄", "תוסיף סנכרון קבצים בין המחשבים שלי"), ("📝", "תבנה אפליקציה לרשימת קניות"),
           ("🌐", "תבנה אתר של מחשבון משכנתא"), ("⏱", "תבנה אפליקציה של טיימר פומודורו"), ("💬", "תתקין טלגרם")],
    "en": [("🛡", "install antivirus"), ("🔄", "add file sync between my computers"), ("📝", "build an app for a shopping list"),
           ("🌐", "build a web page with a mortgage calculator"), ("⏱", "build a pomodoro timer app"), ("💬", "install telegram")],
}
EFFECT_ICON = {"hardens": "🛡", "weakens": "⚠", "neutral": "•"}
EFFECT_COLOR = {"hardens": OK_GREEN, "weakens": WARN_AMBER, "neutral": MUTED}
LABELS = {
    "scope": {"user": ("your account", "החשבון שלך"), "system": ("system", "מערכת")},
    "risk": {"low": ("low risk", "סיכון נמוך"), "medium": ("medium risk", "סיכון בינוני"), "high": ("high risk", "סיכון גבוה")},
    "effect": {"hardens": ("hardens security", "מחזק אבטחה"), "weakens": ("weakens security", "מחליש אבטחה"),
               "neutral": ("neutral", "ניטרלי")},
}


class Worker(QObject):
    """Runs fn(progress) in a thread; emits the result or the error text."""

    progress = pyqtSignal(str)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn: Callable[[Callable[[str], None]], Any]) -> None:
        super().__init__()
        self.fn = fn

    def run(self) -> None:
        try:
            self.finished.emit(self.fn(self.progress.emit))
        except Exception as exc:  # shown to the user, never swallowed
            self.failed.emit(str(exc) or exc.__class__.__name__)


class FlowLayout(QLayout):
    """Wraps chips onto new lines; lays them out right-to-left in Hebrew."""

    def __init__(self, spacing: int = 8) -> None:
        super().__init__()
        self.items = []
        self.gap = spacing

    def addItem(self, item) -> None:  # noqa: N802 - Qt API
        self.items.append(item)

    def count(self) -> int:
        return len(self.items)

    def itemAt(self, index: int):  # noqa: N802
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index: int):  # noqa: N802
        return self.items.pop(index) if 0 <= index < len(self.items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._layout(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self.items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _layout(self, rect: QRect, apply: bool) -> int:
        rtl = self.parentWidget() is not None and self.parentWidget().layoutDirection() == Qt.LayoutDirection.RightToLeft
        x, y, line = 0, rect.y(), 0
        for item in self.items:
            hint = item.sizeHint()
            width = min(hint.width(), rect.width())
            if x and x + width > rect.width():
                x, y, line = 0, y + line + self.gap, 0
            if apply:
                left = rect.right() - x - width + 1 if rtl else rect.x() + x
                item.setGeometry(QRect(QPoint(left, y), QSize(width, hint.height())))
            x += width + self.gap
            line = max(line, hint.height())
        return y + line - rect.y()


class Bridge(QObject):
    """Lives in the GUI thread so callbacks run there (a plain lambda would
    run in the worker thread and touch widgets from it)."""

    def __init__(self, parent: QObject, done: Callable[[Any], None], progress: Callable[[str], None] | None,
                 ended: Callable[[], None]) -> None:
        super().__init__(parent)
        self.done_cb, self.progress_cb, self.ended_cb = done, progress, ended

    @pyqtSlot(object)
    def on_finished(self, result: Any) -> None:
        self.done_cb(result)

    @pyqtSlot(str)
    def on_progress(self, text: str) -> None:
        if self.progress_cb:
            self.progress_cb(text)

    @pyqtSlot()
    def on_ended(self) -> None:
        self.ended_cb()
        self.deleteLater()


class ForgeWindow(QWidget):
    def __init__(self, lang: str, request: str = "") -> None:
        super().__init__(objectName="Forge")
        self.lang = lang
        self.ctx = Context(lang=lang)
        self.admin = is_admin()
        self.threads: list[tuple[QThread, Worker]] = []
        self.plan: Plan | None = None
        self.recipe: Recipe | None = None
        self.removing = False
        self.last_entry = ""
        self.app: apps.App | None = None

        self.setWindowTitle("D.Ai Forge")
        if LOGO.is_file():
            self.setWindowIcon(QIcon(str(LOGO)))
        self.resize(820, 700)
        self.setMinimumSize(QSize(560, 480))

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 16)
        root.setSpacing(14)
        root.addLayout(self._header())
        root.addWidget(self._prompt())
        self.pages = QStackedWidget()
        root.addWidget(self.pages, 1)
        footer = QHBoxLayout()
        for text, stretch in ((self.t("footer"), 1), (f"D.Ai Forge {__version__} · {__author__}", 0)):
            label = QLabel(text, objectName="Muted")
            label.setWordWrap(bool(stretch))
            label.setStyleSheet("font-size: 9pt;")
            footer.addWidget(label, stretch)
        root.addLayout(footer)

        QShortcut(QKeySequence("Esc"), self, self._escape)
        self.show_home()
        if request:
            self.ask.setText(request)
            QTimer.singleShot(0, self.submit)

    # -- helpers ------------------------------------------------------------

    def t(self, key: str) -> str:
        en, he = STRINGS[key]
        return he if self.lang == "he" else en

    def label(self, kind: str, value: str) -> str:
        en, he = LABELS[kind][value]
        return he if self.lang == "he" else en

    def _header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        logo = QLabel("◆")
        logo.setStyleSheet(f"color: {ACCENT}; font-size: 30pt;")
        pixmap = QIcon(str(LOGO)).pixmap(QSize(52, 52)) if LOGO.is_file() else None
        if pixmap is not None and not pixmap.isNull():  # glyph fallback without Qt's SVG plugin
            logo.setPixmap(pixmap)
        logo.setAccessibleName("D.Ai")
        row.addWidget(logo)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        texts.addWidget(QLabel(self.t("title"), objectName="Title"))
        subtitle = QLabel(self.t("subtitle"), objectName="Subtitle")
        subtitle.setWordWrap(True)
        texts.addWidget(subtitle)
        row.addLayout(texts, 1)
        if self.admin:
            row.addWidget(QLabel("🔑 " + self.t("admin"), objectName="Badge"), 0, Qt.AlignmentFlag.AlignTop)
        return row

    def _prompt(self) -> QFrame:
        frame = QFrame(objectName="Prompt")
        row = QHBoxLayout(frame)
        row.setContentsMargins(14, 4, 6, 4)
        spark = QLabel("✦")
        spark.setStyleSheet(f"color: {ACCENT_2}; font-size: 16pt;")
        row.addWidget(spark)
        self.ask = QLineEdit(objectName="Ask", placeholderText=self.t("placeholder"))
        self.ask.setAccessibleName(self.t("ask_name"))
        self.ask.returnPressed.connect(self.submit)
        row.addWidget(self.ask, 1)
        try:  # D.Ai Voice: say the request instead of typing it
            from dai_voice.qt import VoiceButton

            self.mic = VoiceButton(self)
            self.mic.transcribed.connect(lambda text: (self.ask.setText(text), self.ask.setFocus()))
            self.mic.failed.connect(lambda message: self.ask.setPlaceholderText("🎙 " + message))
            row.addWidget(self.mic)
        except ImportError:
            self.mic = None
        self.go = QPushButton(self.t("go"), objectName="Primary")
        self.go.setAccessibleName(self.t("go"))
        self.go.clicked.connect(self.submit)
        row.addWidget(self.go)
        self.prompt_frame = frame
        self.ask.installEventFilter(self)
        return frame

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt API
        if obj is self.ask and event.type() in (event.Type.FocusIn, event.Type.FocusOut):
            self.prompt_frame.setProperty("focused", event.type() == event.Type.FocusIn)
            self.prompt_frame.style().unpolish(self.prompt_frame)
            self.prompt_frame.style().polish(self.prompt_frame)
        return super().eventFilter(obj, event)

    def _escape(self) -> None:
        if self.pages.currentIndex() != 0 and not self.threads:
            self.show_home()
        elif not self.threads:
            self.close()

    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        """A fresh page: scrollable content and an action bar that stays visible."""
        while self.pages.count():
            widget = self.pages.widget(0)
            self.pages.removeWidget(widget)
            widget.deleteLater()
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 4, 6, 4)
        layout.setSpacing(10)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)
        bar = QFrame(objectName="Actions")
        self.actions = QHBoxLayout(bar)
        self.actions.setContentsMargins(0, 10, 0, 0)
        self.actions.addStretch(1)
        bar.setVisible(False)
        self.actions_bar = bar
        outer.addWidget(bar)
        self.pages.addWidget(page)
        return inner, layout

    def _card(self, layout: QVBoxLayout, name: str = "Card") -> QVBoxLayout:
        frame = QFrame(objectName=name)
        inner = QVBoxLayout(frame)
        inner.setContentsMargins(16, 12, 16, 12)
        inner.setSpacing(6)
        layout.addWidget(frame)
        return inner

    def _wrap(self, text: str, name: str = "") -> QLabel:
        label = QLabel(text, objectName=name) if name else QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    def _buttons(self, layout: QVBoxLayout, *buttons: QPushButton) -> None:
        """Buttons go to the page's action bar, which never scrolls away."""
        for button in buttons:
            button.setAccessibleName(button.text())
            self.actions.addWidget(button)
        self.actions_bar.setVisible(True)

    def _run(self, fn: Callable[[Callable[[str], None]], Any], done: Callable[[Any], None],
             progress: Callable[[str], None] | None = None) -> None:
        thread, worker = QThread(self), Worker(fn)
        bridge = Bridge(self, done, progress, lambda: self._forget(thread))
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(bridge.on_progress)
        worker.finished.connect(bridge.on_finished)
        worker.failed.connect(self.show_error)
        for signal in (worker.finished, worker.failed):
            signal.connect(thread.quit)
        thread.finished.connect(bridge.on_ended)
        self.threads.append((thread, worker))
        self._busy(True)
        thread.start()

    def _forget(self, thread: QThread) -> None:
        self.threads = [(t, w) for t, w in self.threads if t is not thread]
        self._busy(bool(self.threads))

    def _busy(self, busy: bool) -> None:
        self.ask.setEnabled(not busy)
        self.go.setEnabled(not busy)

    # -- home ---------------------------------------------------------------

    def show_home(self) -> None:
        _, layout = self._page()
        if not self.admin:
            layout.addWidget(self._wrap("ℹ " + self.t("not_admin"), "Muted"))
        layout.addWidget(QLabel(self.t("ideas"), objectName="Section"))
        self._chips(layout, [f"{icon}  {text}" for icon, text in IDEAS[self.lang]], strip_icon=True)

        library = load_library()
        layout.addWidget(QLabel(self.t("recipes"), objectName="Section"))
        self._chips(layout, [r.title(self.lang) for r in sorted(library.recipes.values(), key=lambda r: r.id)])

        layout.addWidget(QLabel(self.t("my_apps"), objectName="Section"))
        built = apps.list_apps()
        if not built:
            layout.addWidget(self._wrap(self.t("no_apps"), "Muted"))
        for app in built:
            row = QHBoxLayout()
            icon = {"gui": "🪟", "web": "🌐", "cli": "⌨"}[app.kind]
            name = self._wrap(f"{icon}  <b>{app.title}</b>  <span style='color:{MUTED}'>· {app.name} · v{app.version}</span>")
            name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            row.addWidget(name, 1)
            run = QPushButton(self.t("run"))
            run.setAccessibleName(f"{self.t('run')} {app.title}")
            run.clicked.connect(lambda _=False, name=app.name: self.run_app(name))
            row.addWidget(run)
            frame = QFrame(objectName="Step")
            frame.setLayout(row)
            row.setContentsMargins(14, 8, 10, 8)
            layout.addWidget(frame)
        layout.addStretch(1)
        self.ask.setFocus()

    def _chips(self, layout: QVBoxLayout, texts: list[str], strip_icon: bool = False) -> None:
        holder = QWidget()
        flow = FlowLayout()
        holder.setLayout(flow)
        for text in texts:
            chip = QPushButton(text, objectName="Chip")
            request = text.split("  ", 1)[1] if strip_icon and "  " in text else text
            chip.setAccessibleName(request)
            chip.clicked.connect(lambda _=False, r=request: (self.ask.setText(r), self.submit()))
            flow.addWidget(chip)
        layout.addWidget(holder)

    # -- requests -----------------------------------------------------------

    def submit(self) -> None:
        text = self.ask.text().strip().lstrip("+").strip()
        if not text or self.threads:
            return
        intent = classify(text, load_library(), (a.name for a in apps.list_apps()))
        if intent.kind in ("recipe", "remove") and intent.recipe is not None:
            self.show_recipe(intent.recipe, removing=intent.kind == "remove")
        elif intent.kind in ("app", "edit"):
            self.build(intent)
        elif intent.kind == "unknown":
            self.ai_recipe(text)
        else:
            self.show_home()

    def ai_recipe(self, text: str) -> None:
        if not model_installed():
            self.show_no_model(self.t("no_match"))
            return
        self.show_working(self.t("writing_recipe"))
        self._run(lambda progress: author_recipe(text), lambda recipe: self.show_recipe(recipe, removing=False))

    # -- plans --------------------------------------------------------------

    def show_recipe(self, recipe: Recipe, removing: bool) -> None:
        self.recipe, self.removing = recipe, removing
        requests = remove_requests(recipe) if removing else install_requests(recipe)
        self.plan = build_plan(requests, self.ctx)
        _, layout = self._page()
        card = self._card(layout)
        head = QHBoxLayout()
        verb = self.t("remove") if removing else self.t("setup")
        head.addWidget(QLabel(f"<span style='font-size:15pt; font-weight:700'>{verb}: {recipe.title(self.lang)}</span>"), 1)
        source = {"builtin": ("built-in", "מובנה"), "admin": ("administrator", "של המנהל"),
                  "user": ("your recipe", "מתכון שלך"), "ai": ("AI", "AI")}.get(recipe.source, ("", ""))
        head.addWidget(QLabel(source[self.lang == "he"], objectName="BadgeAI" if recipe.source == "ai" else "Badge"))
        card.addLayout(head)
        if recipe.about(self.lang) and not removing:
            card.addWidget(self._wrap(recipe.about(self.lang), "Muted"))

        layout.addWidget(QLabel(self.t("plan_of"), objectName="Section"))
        for step in self.plan.steps:
            spec = CATALOG[step.action]
            step_card = self._card(layout, "Step")
            title = QHBoxLayout()
            icon = QLabel(EFFECT_ICON[step.effect])
            icon.setStyleSheet(f"color: {EFFECT_COLOR[step.effect]}; font-size: 15pt;")
            icon.setFixedWidth(28)
            title.addWidget(icon)
            title.addWidget(self._wrap(f"<b>{spec.summary(step.params, self.lang)}</b>"), 1)
            step_card.addLayout(title)
            tags = " · ".join([self.label("scope", step.scope), self.label("risk", step.risk), self.label("effect", step.effect)])
            tag = QLabel(tags)
            tag.setStyleSheet(f"color: {EFFECT_COLOR[step.effect] if step.effect != 'neutral' else MUTED};")
            tag.setContentsMargins(34, 0, 34, 0)
            step_card.addWidget(tag)
            note = spec.note(step.params, self.lang)
            if note:
                note_label = self._wrap("↳ " + note, "Muted")
                note_label.setContentsMargins(34, 0, 0, 0)
                step_card.addWidget(note_label)
        for problem in [*self.plan.errors, *self.plan.unknown]:
            layout.addWidget(self._wrap(f"<span style='color:{DANGER}'>✗ {problem}</span>"))

        self.confirm_field: QLineEdit | None = None
        self.reviewed: QCheckBox | None = None
        if self.plan.weakens:
            warn = self._card(layout, "Warn")
            warn.addWidget(self._wrap("⚠ " + self.t("weakens")))
            self.confirm_field = QLineEdit(objectName="Confirm")
            self.confirm_field.setAccessibleName(self.t("weakens"))
            self.confirm_field.textChanged.connect(self._update_apply)
            warn.addWidget(self.confirm_field)
        if recipe.source == "ai":
            note = self._card(layout, "Warn")
            note.addWidget(self._wrap("✦ " + self.t("ai_recipe")))
            self.reviewed = QCheckBox(self.t("ai_reviewed"))
            self.reviewed.toggled.connect(self._update_apply)
            note.addWidget(self.reviewed)

        back = QPushButton(self.t("cancel"))
        back.clicked.connect(self.show_home)
        self.apply_button = QPushButton(verb, objectName="Primary")
        self.apply_button.clicked.connect(self.apply)
        self._buttons(layout, back, self.apply_button)
        layout.addStretch(1)
        self._update_apply()
        (self.confirm_field or self.apply_button).setFocus()

    def _update_apply(self, *_args) -> None:
        ok = bool(self.plan and self.plan.ok and self.admin)
        if self.confirm_field is not None:
            ok = ok and self.confirm_field.text().strip().casefold() in ("yes", "כן")
        if self.reviewed is not None:
            ok = ok and self.reviewed.isChecked()
        self.apply_button.setEnabled(ok)

    def apply(self) -> None:
        if not self.apply_button.isEnabled() or self.plan is None or self.recipe is None:
            return
        plan, recipe = self.plan, self.recipe
        verb = self.t("remove") if self.removing else self.t("setup")
        label = f"Forge: {verb} {recipe.title(self.lang)}"
        self.show_working(self.t("applying"))
        self._run(lambda progress: apply_plan(plan, self.ctx, label), self.applied)

    def applied(self, result) -> None:
        if not result.ok:
            self.show_error(result.error)
            return
        self.last_entry = result.entry_id
        if self.recipe is not None and self.recipe.source == "ai":
            save_user_recipe(Recipe(**{**self.recipe.__dict__, "source": "user"}))
        _, layout = self._page()
        card = self._card(layout)
        card.addWidget(QLabel(f"<span style='font-size:17pt; font-weight:700; color:{OK_GREEN}'>{self.t('done')}</span>"))
        card.addWidget(self._wrap(self.t("done_recipe"), "Muted"))
        home = QPushButton(self.t("cancel"))
        home.clicked.connect(self.show_home)
        undo = QPushButton(self.t("undo"))
        undo.clicked.connect(self.undo)
        self._buttons(layout, undo, home)
        layout.addStretch(1)
        home.setFocus()

    def undo(self) -> None:
        entry = self.last_entry or "last"

        def work(progress):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                status = cmd_undo(entry, self.ctx)
            if status != 0:
                raise RuntimeError(out.getvalue().strip() or "undo failed")
            return out.getvalue()

        self.show_working(self.t("applying"))
        self._run(work, lambda _out: self.show_message(self.t("undone")))

    # -- apps ---------------------------------------------------------------

    def build(self, intent: Intent) -> None:
        if not (self.admin or policy().get("apps_for_all_users") is True):
            self.show_error(self.t("not_admin"))
            return
        if not model_installed():
            self.show_no_model(self.t("no_model"))
            return
        current = apps.load(intent.app_name) if intent.kind == "edit" else None
        request = intent.instruction if current else intent.text
        kind = current.kind if current else intent.app_kind
        existing = current.code_path.read_text(encoding="utf-8") if current else None

        _, layout = self._page()
        layout.addWidget(QLabel(f"<span style='font-size:14pt; font-weight:700'>✦ {self.t('writing_app')}</span>"))
        self.status = QLabel("", objectName="Muted")
        layout.addWidget(self.status)
        self.code_view = QPlainTextEdit(objectName="Code")
        self.code_view.setReadOnly(True)
        self.code_view.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.code_view.setAccessibleName("code")
        layout.addWidget(self.code_view, 1)

        def stream(reply: str) -> None:
            code = partial_code(reply)
            self.status.setText(f"{code.count(chr(10))} {self.t('lines')} · {len(reply):,}")
            self.code_view.setPlainText(code)
            self.code_view.verticalScrollBar().setValue(self.code_view.verticalScrollBar().maximum())

        def work(progress):
            result = generate_app(request, kind, existing, progress=progress)
            name = current.name if current else apps.unique_name(result["name"])
            title = current.title if current else result["title"]
            permissions = {"network": result["network"], "documents": result["documents"]}
            return apps.save(name, title, kind, result["code"], permissions, request, generator="ai")

        self._run(work, self.show_app, stream)

    def show_app(self, saved) -> None:
        app, findings = saved
        self.app = app
        _, layout = self._page()
        card = self._card(layout)
        icon = {"gui": "🪟", "web": "🌐", "cli": "⌨"}[app.kind]
        card.addWidget(QLabel(f"<span style='font-size:17pt; font-weight:700; color:{OK_GREEN}'>{self.t('app_ready')} ✓</span>"))
        lines = app.code_path.read_text(encoding="utf-8").count("\n")
        card.addWidget(QLabel(f"{icon}  <b>{app.title}</b>  <span style='color:{MUTED}'>· {app.name} · v{app.version} · "
                              f"{lines} {self.t('lines')}</span>"))
        card.addWidget(self._wrap(self.t("app_where"), "Muted"))

        self.permission_boxes: dict[str, QCheckBox] = {}
        for permission in app.pending_permissions:
            box = QCheckBox(self.t(f"perm_{permission}"))
            self.permission_boxes[permission] = box
            card.addWidget(box)
        if findings:
            layout.addWidget(QLabel(self.t("findings"), objectName="Section"))
            for finding in findings:
                layout.addWidget(self._wrap(("🌐 " if finding.network else "• ") + finding.text(self.lang)))

        open_code = QPushButton(self.t("open_code"))
        open_code.clicked.connect(lambda: subprocess.Popen(["xdg-open", str(app.code_path)], start_new_session=True))
        change = QPushButton(self.t("change"))
        change.clicked.connect(lambda: (self.ask.setText(("שנה את " if self.lang == "he" else "change ") + f"{app.name}: "),
                                        self.ask.setFocus()))
        older = QPushButton(self.t("older"))
        older.setEnabled(bool(apps.versions(app)))
        older.clicked.connect(self.previous_version)
        run = QPushButton(self.t("run"), objectName="Primary")
        run.clicked.connect(self.run_current)
        self._buttons(layout, older, change, open_code, run)
        layout.addStretch(1)
        run.setFocus()

    def run_current(self) -> None:
        if self.app is None:
            return
        app = self.app
        granted = [p for p, box in self.permission_boxes.items() if box.isChecked()]
        if granted:
            app = apps.approve(app, granted)
        for permission, box in self.permission_boxes.items():
            if not box.isChecked():
                app = apps.revoke(app, permission)
        self.app = app
        self.run_app(app.name)

    def previous_version(self) -> None:
        if self.app is None:
            return
        try:
            restored = apps.undo(self.app)
        except apps.AppError as exc:
            self.show_error(str(exc))
            return
        self.show_app((restored, apps.check_code(restored.code_path.read_text(encoding="utf-8"), restored.kind)))

    def run_app(self, name: str) -> None:
        try:
            app = apps.load(name)
            argv = apps.run_argv(app)
        except apps.AppError as exc:
            self.show_error(str(exc))
            return
        if argv[0] == "bwrap" and not shutil.which("bwrap"):
            self.show_error("bubblewrap is missing; apps never run outside the sandbox")
            return
        if app.kind == "cli":
            argv = ["x-terminal-emulator", "-e", "dai-forge", "app", "run", name]
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)

    # -- model --------------------------------------------------------------

    def show_no_model(self, text: str) -> None:
        _, layout = self._page()
        card = self._card(layout)
        card.addWidget(self._wrap("✦ " + text))
        back = QPushButton(self.t("cancel"))
        back.clicked.connect(self.show_home)
        get = QPushButton(self.t("get_model"), objectName="Primary")
        get.clicked.connect(self.download_model)
        get.setEnabled(self.admin)
        self._buttons(layout, back, get)
        layout.addStretch(1)

    def download_model(self) -> None:
        def work(progress):
            from dai_ai import models

            catalog = models.load_catalog()
            model = catalog["qwen2.5-coder-1.5b"]
            models.install(model, progress=lambda done, total: progress(f"{done * 100 // max(total, 1)}%"))
            return model.name

        self.show_working(self.t("downloading"))
        self._run(work, lambda name: self.show_message(f"✓ {name}"), lambda text: self.status.setText(text))

    # -- generic pages ------------------------------------------------------

    def show_working(self, text: str) -> None:
        _, layout = self._page()
        layout.addStretch(1)
        spinner = QLabel("✦")
        spinner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        spinner.setStyleSheet(f"color: {ACCENT}; font-size: 40pt;")
        layout.addWidget(spinner)
        message = QLabel(text)
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setWordWrap(True)
        layout.addWidget(message)
        self.status = QLabel("", objectName="Muted")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status)
        layout.addStretch(2)
        colors = [ACCENT, "#6C7BFA", "#4C8DF0", ACCENT_2, "#4C8DF0", "#6C7BFA"]
        timer = QTimer(spinner)
        timer.timeout.connect(lambda: spinner.setStyleSheet(
            f"color: {colors[timer.property('i') or 0]}; font-size: 40pt;") or timer.setProperty(
            "i", ((timer.property("i") or 0) + 1) % len(colors)))
        timer.start(160)

    def show_message(self, text: str) -> None:
        _, layout = self._page()
        card = self._card(layout)
        card.addWidget(QLabel(f"<span style='font-size:15pt; font-weight:700; color:{OK_GREEN}'>{text}</span>"))
        home = QPushButton(self.t("cancel"))
        home.clicked.connect(self.show_home)
        self._buttons(layout, home)
        layout.addStretch(1)
        home.setFocus()

    @pyqtSlot(str)
    def show_error(self, text: str) -> None:
        _, layout = self._page()
        card = self._card(layout, "Warn")
        card.addWidget(QLabel(f"<span style='font-size:15pt; font-weight:700; color:{DANGER}'>{self.t('failed')}</span>"))
        card.addWidget(self._wrap(text))
        home = QPushButton(self.t("try_again"), objectName="Primary")
        home.clicked.connect(self.show_home)
        self._buttons(layout, home)
        layout.addStretch(1)
        home.setFocus()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--version" in argv:
        print(f"dai-forge-gui {__version__} — {__author__}")
        return 0
    QGuiApplication.setDesktopFileName(APP_ID)
    app = QApplication(argv)
    app.setApplicationName("D.Ai Forge")
    app.setApplicationVersion(__version__)
    app.setOrganizationName(__author__)
    lang = detect_lang()
    if lang == "he":
        app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    if "Noto Sans" in QFontDatabase.families():
        app.setFont(QFont("Noto Sans", 11))
    app.setStyleSheet(STYLE)
    request = " ".join(a for a in argv[1:] if not a.startswith("--"))
    window = ForgeWindow(lang, request)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
