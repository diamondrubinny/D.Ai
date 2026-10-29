# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The Explain window: a small panel over everything with Diamond's answer as it arrives, and one safe
button when a D.Ai Tune sentence would help (it opens D.Ai Command; nothing is applied from here)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Callable

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PyQt6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget

from dai_i18n import pick, qt_direction, ui_lang
from dai_style import app_font, color, rgba, with_touch

from . import __author__, __version__
from .engine import ExplainError, Explanation, explain, where_label

APP_ID = "dai-explain"
BG_900, BG_800, BORDER, TEXT, MUTED = color("bg_900"), color("bg_800"), color("border"), color("text"), color("muted")
ACCENT, ACCENT_2, ACCENT_STRONG, DISABLED = color("accent"), color("accent_2"), color("accent_strong"), color("disabled")
SURFACE, DANGER = color("surface"), color("danger")

STYLE = f"""
QWidget#Explain {{ background: {rgba('bg_900', 0.97)}; border: 1px solid {BORDER}; border-top: 3px solid {ACCENT}; border-radius: 18px; }}
QWidget {{ color: {TEXT}; font-size: 11pt; }}
QLabel#Title {{ font-size: 15pt; font-weight: 700; }}
QLabel#Status {{ color: {MUTED}; font-size: 10pt; }}
QTextEdit#Answer {{ background: {BG_800}; border: 1px solid {BORDER}; border-radius: 12px; padding: 10px; font-size: 12pt; }}
QFrame#ErrorBox {{ background: {rgba('danger', 0.14)}; border: 1px solid {DANGER}; border-radius: 10px; }}
QFrame#SuggestBox {{ background: {rgba('accent', 0.14)}; border: 1px solid {ACCENT}; border-radius: 12px; }}
QPushButton {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; padding: 8px 16px; }}
QPushButton:hover {{ border: 1px solid {ACCENT}; background: {rgba('accent', 0.18)}; }}
QPushButton:focus {{ border: 2px solid {ACCENT_2}; }}
QPushButton#DoIt {{ background: {ACCENT_STRONG}; color: #FFFFFF; font-weight: 700; border: 1px solid {ACCENT_STRONG}; }}
QPushButton:disabled {{ color: {DISABLED}; border: 1px solid {BORDER}; background: {BG_800}; }}
"""

STRINGS = {
    "title": ("D.Ai Explain", "D.Ai מסביר"),
    "reading": ("Reading the screen…", "קורא את המסך…"),
    "thinking": ("Diamond is looking at it…", "Diamond מסתכל…"),
    "done": ("Done", "הסתיים"),
    "again": ("Explain again", "הסבר שוב"),
    "copy": ("Copy", "העתקה"),
    "close": ("Close", "סגירה"),
    "do_it": ("Do it: {sentence}", "עשה את זה: {sentence}"),
    "suggest": ("Diamond suggests a D.Ai Tune step. It opens in D.Ai Command, where you see the plan and approve it.",
                "Diamond מציע צעד של D.Ai Tune. הוא נפתח ב־D.Ai Command, שם רואים את התוכנית ומאשרים."),
    "answer": ("Diamond's explanation", "ההסבר של Diamond"),
    "empty": ("No text was found on the screen.", "לא נמצא טקסט על המסך."),
    "read": ("Read aloud", "הקראה"),
    "read_stop": ("Stop reading", "עצירת ההקראה"),
}


class Worker(QObject):
    piece = pyqtSignal(str)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, gather: Callable[[], str], lang: str, chat: Callable | None = None) -> None:
        super().__init__()
        self.gather, self.lang, self.chat = gather, lang, chat

    @pyqtSlot()
    def run(self) -> None:
        try:
            text = self.gather()
            result = explain(text, self.lang, chat=self.chat, on_piece=self.piece.emit)
        except (ExplainError, OSError) as exc:
            self.failed.emit(str(exc))
            return
        self.done.emit(result)


class ExplainWindow(QWidget):
    def __init__(self, lang: str, gather: Callable[[], str], chat: Callable | None = None,
                 spawn: Callable[..., None] | None = None) -> None:
        super().__init__(objectName="Explain")
        self.lang, self.gather, self.chat = lang, gather, chat
        self.spawn = spawn or _spawn
        self.thread: QThread | None = None
        self.worker: Worker | None = None
        self.result: Explanation | None = None
        self.setWindowTitle(self.t("title"))
        self.setLayoutDirection(qt_direction(lang))
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumSize(560, 360)
        self.resize(720, 440)
        self.setStyleSheet(with_touch(STYLE))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 14)
        outer.setSpacing(10)
        head = QHBoxLayout()
        title = QLabel(self.t("title"), objectName="Title")
        head.addWidget(title, 1)
        self.status = QLabel(self.t("reading"), objectName="Status")
        head.addWidget(self.status)
        outer.addLayout(head)
        self.answer = QTextEdit(objectName="Answer")
        self.answer.setReadOnly(True)
        self.answer.setAccessibleName(self.t("answer"))
        outer.addWidget(self.answer, 1)
        self.error_box = QFrame(objectName="ErrorBox")
        box = QVBoxLayout(self.error_box)
        box.setContentsMargins(10, 8, 10, 8)
        self.error = QLabel("")
        self.error.setWordWrap(True)
        box.addWidget(self.error)
        self.error_box.hide()
        outer.addWidget(self.error_box)
        self.suggest_box = QFrame(objectName="SuggestBox")
        sbox = QVBoxLayout(self.suggest_box)
        sbox.setContentsMargins(12, 10, 12, 10)
        self.suggest_text = QLabel(self.t("suggest"))
        self.suggest_text.setWordWrap(True)
        sbox.addWidget(self.suggest_text)
        self.do_it = QPushButton("", objectName="DoIt")
        self.do_it.clicked.connect(self.run_suggestion)
        sbox.addWidget(self.do_it)
        self.suggest_box.hide()
        outer.addWidget(self.suggest_box)
        row = QHBoxLayout()
        self.privacy = QLabel(where_label(lang), objectName="Status")
        self.privacy.setWordWrap(True)
        row.addWidget(self.privacy, 1)
        self.again = QPushButton(self.t("again"))
        self.again.setAccessibleName(self.t("again"))
        self.again.clicked.connect(self.start)
        row.addWidget(self.again)
        self.read = QPushButton(self.t("read"))
        self.read.setAccessibleName(self.t("read"))
        self.read.setEnabled(False)
        self.read.clicked.connect(self.toggle_reading)
        row.addWidget(self.read)
        self.reading = False
        copy = QPushButton(self.t("copy"))
        copy.setAccessibleName(self.t("copy"))
        copy.clicked.connect(self.copy_answer)
        row.addWidget(copy)
        close = QPushButton(self.t("close"))
        close.setAccessibleName(self.t("close"))
        close.clicked.connect(self.close)
        row.addWidget(close)
        outer.addLayout(row)
        QShortcut(QKeySequence("Escape"), self, activated=self.close)
        self.place()

    def t(self, key: str, **kwargs: object) -> str:
        return pick(self.lang, *STRINGS[key]).format(**kwargs)

    def place(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(area.x() + area.width() - self.width() - 24, area.y() + 24)

    def start(self) -> None:
        if self.thread is not None:
            return
        if self.reading:
            self.toggle_reading()
        self.read.setEnabled(False)
        self.result = None
        self.answer.clear()
        self.error_box.hide()
        self.suggest_box.hide()
        self.again.setEnabled(False)
        self.status.setText(self.t("reading"))
        self.worker = Worker(self.gather, self.lang, self.chat)
        self.thread = QThread()
        self.worker.moveToThread(self.thread)
        self.worker.piece.connect(self.show_piece)
        self.worker.done.connect(self.show_result)
        self.worker.failed.connect(self.show_error)
        self.thread.started.connect(self.worker.run)
        self.thread.start()

    @pyqtSlot(str)
    def show_piece(self, piece: str) -> None:
        self.status.setText(self.t("thinking"))
        self.answer.setPlainText(self.answer.toPlainText() + piece)
        self.answer.setLayoutDirection(Qt.LayoutDirection.RightToLeft if any("֐" <= ch <= "׿" for ch in piece)
                                       else self.layoutDirection())  # i18n: ok (the text's own direction)

    @pyqtSlot(object)
    def show_result(self, result: Explanation) -> None:
        self.result = result
        self.answer.setPlainText(result.text)
        if result.suggestion:
            self.do_it.setText(self.t("do_it", sentence=result.suggestion))
            self.do_it.setAccessibleName(self.do_it.text())
            self.suggest_box.show()
        self.status.setText(self.t("done"))
        self.read.setEnabled(bool(result.text.strip()) and shutil.which("dai-speak") is not None)
        self._finish()

    @pyqtSlot(str)
    def show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error_box.show()
        self.status.setText(self.t("done"))
        self._finish()

    def _finish(self) -> None:
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait(2000)
        self.thread, self.worker = None, None
        self.again.setEnabled(True)

    def run_suggestion(self) -> None:
        if self.result and self.result.suggestion:
            self.spawn(["dai-command", "--query", self.result.suggestion])

    def toggle_reading(self) -> None:
        """D.Ai Speak (docs/SPEAK.md): the explanation through dai-speak's standard input; the same button stops."""
        if self.reading:
            self.spawn(["dai-speak", "--stop"])
            self.reading = False
        else:
            words = self.answer.toPlainText().strip()
            if not words:
                return
            self.spawn(["dai-speak", "--stdin", "--lang", self.lang], words)
            self.reading = True
        self.read.setText(self.t("read_stop") if self.reading else self.t("read"))
        self.read.setAccessibleName(self.read.text())

    def copy_answer(self) -> None:
        QApplication.clipboard().setText(self.answer.toPlainText())

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt
        if self.reading:
            self.toggle_reading()
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait(8000)
        event.accept()


def _spawn(argv: list[str], stdin_text: str | None = None) -> None:
    """Start a program detached; `stdin_text`, when given, goes through its standard input (never on a command line)."""
    try:
        child = subprocess.Popen(argv, stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        if stdin_text is not None and child.stdin is not None:
            try:
                child.stdin.write(stdin_text.encode("utf-8"))
                child.stdin.close()
            except OSError:
                pass
    except OSError as exc:
        print(f"dai-explain: cannot start {argv[0]}: {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--version" in argv:
        print(f"dai-explain {__version__} — {__author__}")
        return 0
    from .cli import gather_text
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName(APP_ID)
    app.setDesktopFileName(APP_ID)
    if (font := app_font()) is not None:
        app.setFont(font)
    app.setStyleSheet(with_touch(STYLE))
    lang = argv[argv.index("--lang") + 1] if "--lang" in argv and argv.index("--lang") + 1 < len(argv) else ui_lang()
    args = argv[1:]
    window = ExplainWindow(lang, lambda: gather_text(args, lang))
    window.show()
    window.start()
    return app.exec()
