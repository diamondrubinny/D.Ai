# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The small window where Diamond answers (docs/MOM.md §11).

Diamond's words are shown as plain text, never as rich text or links. The
buttons under them come from MOM (diamond.suggestions), and each one does what
the same button elsewhere in MOM does. "What was sent to Diamond" shows the
exact facts, so nothing is hidden from the person asking.
"""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from dai_i18n import embed, qt_direction

from .diamond import Suggestion, answer
from .text import t

Prepare = Callable[[], tuple[list[dict[str, str]], str]]   # → (the messages for Diamond, the local answer)

_LIVE: set = set()   # answers still being written, kept alive after their window closes


class _Work(QObject):
    finished = pyqtSignal(str, str, bool)   # the answer, what was sent, from Diamond (False: the local answer)

    def __init__(self, prepare: Prepare, ai: Callable[[list[dict[str, str]]], str]) -> None:
        super().__init__()
        self.prepare, self.ai = prepare, ai

    def run(self) -> None:
        messages, local = self.prepare()
        sent = messages[-1]["content"] if messages else ""
        said = self.ai(messages) if messages else ""
        self.finished.emit(said or local, sent, bool(said))


class DiamondDialog(QDialog):
    def __init__(self, lang: str, title: str, prepare: Prepare, suggestions: list[Suggestion],
                 on_suggestion: Callable[[Suggestion], None], ai: Callable | None = None, inline: bool = False,
                 parent=None) -> None:
        super().__init__(parent)
        self.lang = lang
        self.on_suggestion = on_suggestion
        self.setWindowTitle(title)
        self.setLayoutDirection(qt_direction(lang))
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        heading = QLabel(title, objectName="Big")
        layout.addWidget(heading)

        self.answer = QLabel(t("diamond_thinking", lang))
        self.answer.setTextFormat(Qt.TextFormat.PlainText)  # Diamond's words are never markup or links
        self.answer.setWordWrap(True)
        self.answer.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                            | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.answer.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # a screen reader reaches the answer with Tab
        self.answer.setAccessibleName(title)
        layout.addWidget(self.answer)
        self.note = QLabel(t("diamond_local", lang), objectName="Muted")
        self.note.setWordWrap(True)
        self.note.hide()
        layout.addWidget(self.note)

        self.buttons: list[QPushButton] = []
        row = QHBoxLayout()
        for suggestion in suggestions:
            button = QPushButton(embed(suggestion.label, lang))
            button.clicked.connect(lambda _=False, s=suggestion: self._choose(s))
            row.addWidget(button)
            self.buttons.append(button)
        row.addStretch(1)
        layout.addLayout(row)

        self.sent = QPlainTextEdit(readOnly=True)
        self.sent.setAccessibleName(t("diamond_sent", lang))
        self.sent.setToolTip(t("diamond_sent_note", lang))
        self.sent.setMaximumHeight(160)
        self.sent.hide()
        bottom = QHBoxLayout()
        self.show_sent = QPushButton(embed(t("diamond_sent", lang), lang), checkable=True)
        self.show_sent.toggled.connect(self.sent.setVisible)
        close = QPushButton(embed(t("close", lang), lang))
        close.clicked.connect(self.reject)
        bottom.addWidget(self.show_sent)
        bottom.addStretch(1)
        bottom.addWidget(close)
        layout.addWidget(self.sent)
        layout.addLayout(bottom)

        work = _Work(prepare, ai or answer)
        work.finished.connect(self._show)
        if inline:
            work.run()
            return
        # No parent: a slow model may still be answering when the window closes; the thread ends on its own.
        thread = QThread()
        work.moveToThread(thread)
        thread.started.connect(work.run)
        work.finished.connect(thread.quit)
        pair = (thread, work)
        _LIVE.add(pair)
        thread.finished.connect(lambda: _LIVE.discard(pair))
        thread.start()

    def _show(self, said: str, sent: str, from_diamond: bool) -> None:
        self.answer.setText(said)
        self.note.setVisible(not from_diamond)
        self.sent.setPlainText(sent)
        self.answer.setFocus()

    def _choose(self, suggestion: Suggestion) -> None:
        self.accept()
        self.on_suggestion(suggestion)
