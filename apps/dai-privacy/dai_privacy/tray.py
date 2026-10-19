# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The panel indicator: a red dot only while something records or films.

Checks every 2 seconds (read-only), logs changes locally and shows a
notification when an app starts. Without a status-notifier area it still
logs and notifies through notify-send.
"""

from __future__ import annotations

import subprocess
import sys

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from dai_style import color

from .log import append, changes, log_path
from .sensors import current
from .text import describe, lang, t

INTERVAL_MS = 2000
DANGER = color("danger")


def dot_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(DANGER))
    painter.drawEllipse(14, 14, 36, 36)
    painter.end()
    return QIcon(pixmap)


def _mirror(apps: list[str]) -> None:
    """The red dot on the Start diamond too (docs/TASKBAR.md §2.1); optional, never fatal."""
    try:
        from dai_status import update
    except ImportError:
        return
    update("privacy", apps)


class Indicator:
    def __init__(self, app: QApplication, sense=current, notify=None) -> None:
        self.app = app
        self.sense = sense
        self.language = lang()
        self.uses: set = set()
        self.tray = QSystemTrayIcon(dot_icon())
        self.notify = notify or self._notify
        menu = QMenu()
        for key, slot in (("show_log", self.show_log), ("block_camera", self.block_camera), ("quit", app.quit)):
            action = QAction(t(key, self.language), menu)
            action.triggered.connect(slot)
            menu.addAction(action)
        self.menu = menu
        self.tray.setContextMenu(menu)
        self.tray.setToolTip(t("nothing", self.language))
        self.timer = QTimer()
        self.timer.timeout.connect(self.check)

    def start(self) -> None:
        self.check()
        self.timer.start(INTERVAL_MS)

    def check(self) -> None:
        now = set(self.sense())
        events = changes(self.uses, now)
        if events:
            append(log_path(), events)
        for kind, use in events:
            if kind == "start":
                self.notify(describe(use, self.language))
        self.uses = now
        _mirror(sorted({use.app for use in now}))
        tooltip = "\n".join(describe(u, self.language) for u in sorted(now)) or t("nothing", self.language)
        self.tray.setToolTip(tooltip)
        self.tray.setVisible(bool(now))  # nothing in use → nothing in the panel

    def _notify(self, text: str) -> None:
        if QSystemTrayIcon.isSystemTrayAvailable() and self.tray.isVisible():
            self.tray.showMessage(t("title", self.language), text, QSystemTrayIcon.MessageIcon.Information, 5000)
        else:
            subprocess.Popen(["notify-send", "-a", "D.Ai", t("title", self.language), text],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def show_log(self) -> None:
        subprocess.Popen(["x-terminal-emulator", "-e", "bash", "-c",
                          'dai-privacy log; echo; read -r -p "Enter ↵" _'], start_new_session=True)

    def block_camera(self) -> None:
        # The plan, the password and undo are D.Ai Tune's.
        subprocess.Popen(["x-terminal-emulator", "-e", "bash", "-c",
                          'dai-tune "block the camera"; echo; read -r -p "Enter ↵" _'], start_new_session=True)


def main() -> int:
    app = QApplication(sys.argv[:1])
    app.setApplicationName("D.Ai Privacy")
    app.setQuitOnLastWindowClosed(False)
    indicator = Indicator(app)
    indicator.start()
    return app.exec()
