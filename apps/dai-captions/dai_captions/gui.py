# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The captions bar: a small always-on-top window at the bottom of the screen with the last lines."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PyQt6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from dai_i18n import pick, qt_direction, ui_lang
from dai_style import app_font, color, rgba, with_touch

from . import __author__, __version__
from .engine import Captions, VoiceError, file_chunks, live_chunks, run_pipeline, transcribe_chunk

APP_ID = "dai-captions"
BG_900, BG_800, BORDER, TEXT, MUTED = color("bg_900"), color("bg_800"), color("border"), color("text"), color("muted")
ACCENT, ACCENT_2, ACCENT_STRONG, DISABLED = color("accent"), color("accent_2"), color("accent_strong"), color("disabled")
SURFACE, DANGER = color("surface"), color("danger")

STYLE = f"""
QWidget#Captions {{ background: {rgba('bg_900', 0.96)}; border: 1px solid {BORDER}; border-top: 3px solid {ACCENT}; border-radius: 18px; }}
QWidget {{ color: {TEXT}; font-size: 11pt; }}
QLabel#Lines {{ font-size: 19pt; font-weight: 600; padding: 6px 10px; }}
QLabel#Status {{ color: {MUTED}; font-size: 10pt; }}
QFrame#ErrorBox {{ background: {rgba('danger', 0.14)}; border: 1px solid {DANGER}; border-radius: 10px; }}  /* the frame carries the border; Raz reads the label against the tint */
QPushButton {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; padding: 8px 16px; }}
QPushButton:hover {{ border: 1px solid {ACCENT}; background: {rgba('accent', 0.18)}; }}
QPushButton:focus {{ border: 2px solid {ACCENT_2}; }}
QPushButton:disabled {{ color: {DISABLED}; border: 1px solid {BORDER}; background: {BG_800}; }}
"""

STRINGS = {
    "title": ("D.Ai Live Captions", "כתוביות חיות D.Ai"),
    "listening": ("Listening to what the computer plays…", "מאזין למה שהמחשב משמיע…"),
    "paused": ("Paused", "מושהה"),
    "from_file": ("Reading {name}…", "קורא את {name}…"),
    "finished": ("Finished", "הסתיים"),
    "pause": ("Pause", "השהיה"),
    "resume": ("Resume", "המשך"),
    "close": ("Close", "סגירה"),
    "waiting": ("The first words appear a few seconds after they are said.", "המילים הראשונות מופיעות כמה שניות אחרי שנאמרו."),
    "privacy": ("On this computer only: no network, nothing saved.", "על המחשב הזה בלבד: בלי רשת, בלי שמירה."),
    "no_model": ("No speech model yet. Run: dai-models install whisper-small", "עדיין אין מודל דיבור. הריצו: dai-models install whisper-small"),
}


class Worker(QObject):
    line = pyqtSignal(str)
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, source: Path | None, lang: str | None, transcriber: Callable[[Path], str] | None = None) -> None:
        super().__init__()
        self.source, self.lang, self.stopping, self.paused = source, lang, False, False
        self.transcriber = transcriber or (lambda path: transcribe_chunk(path, self.lang))

    @pyqtSlot()
    def run(self) -> None:
        try:
            chunks = file_chunks(self.source) if self.source else live_chunks(lambda: self.stopping or self.paused)
            run_pipeline(chunks, self.transcriber, emit=self.line.emit, stop=lambda: self.stopping)
        except (VoiceError, OSError, EOFError) as exc:
            self.failed.emit(str(exc))
        self.finished.emit()


class CaptionsWindow(QWidget):
    def __init__(self, lang: str, source: Path | None = None, speech_lang: str | None = None,
                 transcriber: Callable[[Path], str] | None = None) -> None:
        super().__init__(objectName="Captions")
        self.lang, self.source, self.speech_lang, self.transcriber = lang, source, speech_lang, transcriber
        self.captions = Captions()
        self.thread: QThread | None = None
        self.worker: Worker | None = None
        self.paused = False
        self.setWindowTitle(self.t("title"))
        self.setLayoutDirection(qt_direction(lang))
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)   # the bar's own tint, border and accent line
        self.setMinimumSize(520, 150)
        self.resize(900, 170)
        self.setStyleSheet(with_touch(STYLE))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 12, 18, 12)
        outer.setSpacing(8)
        self.lines = QLabel(self.t("waiting"), objectName="Lines")
        self.lines.setWordWrap(True)
        self.lines.setAccessibleName(self.t("title"))
        self.lines.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(self.lines, 1)
        self.error_box = QFrame(objectName="ErrorBox")
        box = QVBoxLayout(self.error_box)
        box.setContentsMargins(10, 8, 10, 8)
        self.error = QLabel("")
        self.error.setWordWrap(True)
        box.addWidget(self.error)
        self.error_box.hide()
        outer.addWidget(self.error_box)
        row = QHBoxLayout()
        self.status = QLabel(self.t("listening"), objectName="Status")
        row.addWidget(self.status, 1)
        self.pause_button = QPushButton(self.t("pause"))
        self.pause_button.setAccessibleName(self.t("pause"))
        self.pause_button.clicked.connect(self.toggle_pause)
        row.addWidget(self.pause_button)
        close = QPushButton(self.t("close"))
        close.setAccessibleName(self.t("close"))
        close.clicked.connect(self.close)
        row.addWidget(close)
        outer.addLayout(row)
        QShortcut(QKeySequence("Escape"), self, activated=self.close)
        QShortcut(QKeySequence("Space"), self, activated=self.toggle_pause)
        self.setToolTip(self.t("privacy"))
        self.place_at_bottom()

    def t(self, key: str, **kwargs: object) -> str:
        return pick(self.lang, *STRINGS[key]).format(**kwargs)

    def place_at_bottom(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        width = min(self.width(), area.width() - 40)
        self.resize(width, self.height())
        self.move(area.x() + (area.width() - width) // 2, area.y() + area.height() - self.height() - 24)

    def start(self) -> None:
        if self.thread is not None:
            return
        self.worker = Worker(self.source, self.speech_lang, self.transcriber)
        self.thread = QThread()
        self.worker.moveToThread(self.thread)
        self.worker.line.connect(self.show_line)
        self.worker.failed.connect(self.show_error)
        self.worker.finished.connect(self.finished)
        self.thread.started.connect(self.worker.run)
        self.thread.start()
        if self.source:
            self.status.setText(self.t("from_file", name=self.source.name))

    @pyqtSlot(str)
    def show_line(self, text: str) -> None:
        self.error_box.hide()
        self.lines.setText(text)
        self.lines.setLayoutDirection(Qt.LayoutDirection.RightToLeft if any("֐" <= ch <= "׿" for ch in text)
                                      else Qt.LayoutDirection.LeftToRight)  # i18n: ok (the text's own direction)

    @pyqtSlot(str)
    def show_error(self, message: str) -> None:
        friendly = self.t("no_model") if "no speech model" in message else message
        self.error.setText(friendly)
        self.error_box.show()

    @pyqtSlot()
    def finished(self) -> None:
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait(2000)
        self.thread, self.worker = None, None
        if self.source:
            self.status.setText(self.t("finished"))
            self.pause_button.setEnabled(False)

    def toggle_pause(self) -> None:
        if self.source and self.thread is None:
            return
        self.paused = not self.paused
        if self.worker is not None:
            self.worker.paused = self.paused
        self.pause_button.setText(self.t("resume") if self.paused else self.t("pause"))
        self.pause_button.setAccessibleName(self.pause_button.text())
        self.status.setText(self.t("paused") if self.paused else self.t("listening"))
        if not self.paused and self.thread is None:
            self.start()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt
        if self.worker is not None:
            self.worker.stopping = True
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait(8000)
        event.accept()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--version" in argv:
        print(f"dai-captions {__version__} — {__author__}")
        return 0
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName(APP_ID)
    app.setDesktopFileName(APP_ID)
    if (font := app_font()) is not None:   # Inter when installed, Noto Sans otherwise (docs/LOOK.md)
        app.setFont(font)
    app.setStyleSheet(with_touch(STYLE))
    source = Path(argv[argv.index("--from-file") + 1]) if "--from-file" in argv else None
    speech_lang = argv[argv.index("--lang") + 1] if "--lang" in argv and argv.index("--lang") + 1 < len(argv) else None
    window = CaptionsWindow(ui_lang(), source, speech_lang)
    window.show()
    window.start()
    return app.exec()
