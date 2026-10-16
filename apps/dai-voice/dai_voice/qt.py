# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""A push-to-talk microphone button for D.Ai's Qt apps.

Click to record, click again to stop; the text arrives through the
`transcribed` signal. Recording and transcription run in `dai-voice`
(QProcess, never blocking the UI), so the sandbox rules stay in one place.
"""

from __future__ import annotations

import os

from PyQt6.QtCore import QProcess, QSize, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QToolButton

TEXT = {
    "idle": ("Speak (local, Whisper)", "דיבור (מקומי, Whisper)"),
    "recording": ("Recording… click to finish", "מקליט… לחצו לסיום"),
    "working": ("Transcribing…", "מתמלל…"),
}


def _he() -> bool:
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if value:
            return value.startswith("he")
    return False


class VoiceButton(QToolButton):
    transcribed = pyqtSignal(str)
    failed = pyqtSignal(str)
    state_changed = pyqtSignal(str)  # idle | recording | working

    def __init__(self, parent=None, program: str = "dai-voice") -> None:
        super().__init__(parent)
        self.program = program
        self.state = "idle"
        self.process: QProcess | None = None
        self.setObjectName("Mic")
        self.setIcon(QIcon.fromTheme("audio-input-microphone"))
        self.setIconSize(QSize(22, 22))
        self.setCheckable(True)
        self.clicked.connect(self.toggle)
        self._set_state("idle")

    def _label(self, key: str) -> str:
        en, he = TEXT[key]
        return he if _he() else en

    def _set_state(self, state: str) -> None:
        self.state = state
        self.setChecked(state == "recording")
        self.setEnabled(state != "working")
        self.setProperty("recording", state == "recording")
        self.style().unpolish(self)
        self.style().polish(self)
        self.setToolTip(self._label(state))
        self.setAccessibleName(self._label(state))
        self.state_changed.emit(state)

    def toggle(self) -> None:
        if self.state == "idle":
            self._start(["start"], self._on_started)
        elif self.state == "recording":
            self._set_state("working")
            self._start(["stop", "--to", "print"], self._on_stopped)

    def _start(self, args: list[str], done) -> None:
        process = QProcess(self)
        process.finished.connect(lambda code, _status: done(code, process))
        process.errorOccurred.connect(lambda _error: self._fail(process.errorString()))
        self.process = process
        process.start(self.program, args)

    def _on_started(self, code: int, process: QProcess) -> None:
        if code == 0:
            self._set_state("recording")
        else:
            self._fail(bytes(process.readAllStandardError()).decode("utf-8", "replace"))

    def _on_stopped(self, code: int, process: QProcess) -> None:
        out = bytes(process.readAllStandardOutput()).decode("utf-8", "replace").strip()
        err = bytes(process.readAllStandardError()).decode("utf-8", "replace").strip()
        self._set_state("idle")
        if code == 0 and out:
            self.transcribed.emit(out)
        elif code != 3:  # 3: nothing was said
            self.failed.emit(err.removeprefix("dai-voice: ") or "speech recognition failed")

    def _fail(self, message: str) -> None:
        self._set_state("idle")
        self.failed.emit(message.strip().removeprefix("dai-voice: ") or "speech recognition failed")
