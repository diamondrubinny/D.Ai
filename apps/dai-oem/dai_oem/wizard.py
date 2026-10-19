# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The first-boot setup the new owner sees (docs/OEM.md §1).

  language ──► you ──► computer ──► encryption (if the disk is encrypted) ──► summary ──► working ──► done

Runs full screen in the dai-oem session (labwc, no panel). Nothing changes
before "Finish"; the root part is dai-oem-helper through pkexec.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import Qt, QThread, QTimer
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from dai_forge.gui import ACCENT_2, BG_900, BORDER, DANGER, STYLE as FORGE_STYLE, Bridge, Worker

from dai_i18n import pick

from . import __author__, __version__
from .core import Machine, Owner, suggest_username, validation_errors

APP_ID = "dai-oem-setup"
HELPER = "/usr/lib/dai/dai-oem-helper"
STYLE = FORGE_STYLE.replace("QWidget#Forge", "QWidget#Oem") + f"""
QLabel#Hero {{ font-size: 26pt; font-weight: 700; }}
QLabel#Error {{ color: {DANGER}; }}
QLineEdit {{ background: {BG_900}; border: 1px solid {BORDER}; border-radius: 8px; padding: 8px 10px; font-size: 12pt; }}
QLineEdit:focus {{ border: 2px solid {ACCENT_2}; }}
QLineEdit[invalid="true"] {{ border: 2px solid {DANGER}; }}
"""

STRINGS = {
    "window": ("Set up your computer", "הגדרת המחשב שלך"),
    "hello": ("Hello! Let's set up your computer", "שלום! בואו נגדיר את המחשב שלך"),
    "hello_d": ("It takes two minutes. Choose a language:", "זה לוקח שתי דקות. בחרו שפה:"),
    "you": ("About you", "עליך"),
    "full_name": ("Your name", "השם שלך"),
    "username": ("User name (English letters, for signing in)", "שם משתמש (באנגלית, לכניסה למחשב)"),
    "password": ("Password (at least 8 characters)", "סיסמה (לפחות 8 תווים)"),
    "password2": ("Password again", "שוב את הסיסמה"),
    "computer": ("Computer name", "שם המחשב"),
    "computer_d": ("How the computer appears on the network.", "כך המחשב יופיע ברשת."),
    "luks": ("Disk encryption password", "סיסמת ההצפנה של הדיסק"),
    "luks_d": ("Your files are encrypted. This password is asked every time the computer starts, before "
               "anything else. It replaces the temporary one you got with the computer.",
               "הקבצים שלך מוצפנים. הסיסמה הזו נשאלת בכל הדלקה, לפני כל דבר אחר. "
               "היא מחליפה את הסיסמה הזמנית שקיבלת עם המחשב."),
    "luks1": ("New encryption password (at least 8 characters)", "סיסמת הצפנה חדשה (לפחות 8 תווים)"),
    "luks2": ("Encryption password again", "שוב את סיסמת ההצפנה"),
    "luks_ack": ("I wrote it down. Without it nobody, not even a technician, can open my files.",
                 "רשמתי אותה. בלעדיה אף אחד, גם לא טכנאי, לא יוכל לפתוח את הקבצים שלי."),
    "summary": ("Ready", "מוכנים"),
    "summary_d": ("Name: {name}\nUser: {user} (administrator)\nComputer: {host}\n{luks}\n\n"
                  "After “Finish” the computer restarts. The temporary user it came with is deleted.",
                  "שם: {name}\nמשתמש: {user} (מנהל)\nמחשב: {host}\n{luks}\n\n"
                  "אחרי „סיום” המחשב יופעל מחדש. המשתמש הזמני שהגיע עם המחשב יימחק."),
    "luks_yes": ("Disk encryption: new password", "הצפנת דיסק: סיסמה חדשה"),
    "luks_no": ("Disk encryption: off", "הצפנת דיסק: כבויה"),
    "working": ("Setting up… do not turn the computer off.", "מגדירים… לא לכבות את המחשב."),
    "done": ("All set. Restarting…", "הכל מוכן. מפעילים מחדש…"),
    "failed": ("Something went wrong: {error}\nNothing was lost. Check the details and try again.",
               "משהו השתבש: {error}\nשום דבר לא אבד. בדקו את הפרטים ונסו שוב."),
    "back": ("Back", "חזרה"),
    "next": ("Next", "הבא"),
    "finish": ("Finish ✦", "סיום ✦"),
    "e_full_name": ("Type your name.", "כתבו את השם שלך."),
    "e_username": ("A user name in small English letters, digits or -, starting with a letter (and not taken).",
                   "שם משתמש באותיות אנגליות קטנות, ספרות או -, שמתחיל באות (ושלא תפוס)."),
    "e_password": ("At least 8 characters.", "לפחות 8 תווים."),
    "e_match": ("The two passwords are not the same.", "שתי הסיסמאות לא זהות."),
    "e_hostname": ("English letters, digits and -, up to 63.", "אותיות אנגליות, ספרות ו־-, עד 63."),
    "e_luks_password": ("At least 8 characters, and confirm you wrote it down.", "לפחות 8 תווים, ואישור שרשמת אותה."),
}


def run_helper(owner: Owner) -> dict:
    payload = json.dumps(owner.__dict__)
    result = subprocess.run(["pkexec", HELPER, "complete"], input=payload, capture_output=True, text=True,
                            timeout=600, check=False)
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        return {"ok": False, "error": (result.stderr or "no answer").strip()[-200:]}


def reboot() -> None:
    subprocess.run(["pkexec", HELPER, "reboot"], capture_output=True, timeout=60, check=False)


class SetupWindow(QWidget):
    def __init__(self, machine: Machine, finisher: Callable[[Owner], dict] = run_helper,
                 restarter: Callable[[], None] = reboot) -> None:
        super().__init__()
        self.machine = machine
        self.finisher = finisher
        self.restarter = restarter
        self.needs_luks = bool(machine.state().get("luks")) and not machine.state().get("luks_done")
        self.taken = set(machine.users())
        self.language = "he"
        self.threads: list[tuple[QThread, Worker]] = []
        self.setObjectName("Oem")
        self.setStyleSheet(STYLE)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("Card")
        card.setMaximumWidth(720)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(card, 4)
        row.addStretch(1)
        outer.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)
        self.body = QVBoxLayout(card)
        self.body.setContentsMargins(36, 28, 36, 24)
        self.pages = QStackedWidget()
        self.body.addWidget(self.pages)
        self.error = QLabel()
        self.error.setObjectName("Error")
        self.error.setWordWrap(True)
        self.body.addWidget(self.error)
        buttons = QHBoxLayout()
        self.back_button = QPushButton()
        self.back_button.clicked.connect(self.back)
        self.next_button = QPushButton()
        self.next_button.setObjectName("Primary")
        self.next_button.clicked.connect(self.next)
        buttons.addWidget(self.back_button)
        buttons.addStretch(1)
        buttons.addWidget(self.next_button)
        self.body.addLayout(buttons)
        self._language_page()
        self.show_page(0)

    def tr(self, key: str, **kwargs: object) -> str:  # noqa: D401 (not QObject.tr)
        return pick(self.language, *STRINGS[key]).format(**kwargs)

    # -- pages -------------------------------------------------------------------

    def _page(self, title: str, text: str = "") -> QVBoxLayout:
        page = QWidget()
        layout = QVBoxLayout(page)
        heading = QLabel(title)
        heading.setObjectName("Hero" if self.pages.count() == 0 else "Title")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        if text:
            label = QLabel(text)
            label.setObjectName("Muted")
            label.setWordWrap(True)
            layout.addWidget(label)
        self.pages.addWidget(page)
        return layout

    def _field(self, layout: QVBoxLayout, key: str, secret: bool = False) -> QLineEdit:
        label = QLabel(self.tr(key))
        edit = QLineEdit()
        edit.setAccessibleName(self.tr(key))
        label.setBuddy(edit)
        if secret:
            edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(label)
        layout.addWidget(edit)
        return edit

    def _language_page(self) -> None:
        layout = self._page("שלום! · Hello!", "בחרו שפה · Choose a language")
        for code, name in (("he", "עברית"), ("en", "English")):
            button = QPushButton(name)
            button.setObjectName("Primary" if code == "he" else "")
            button.setAccessibleName(name)
            button.clicked.connect(lambda _=False, c=code: self.choose_language(c))
            layout.addWidget(button)
        layout.addStretch(1)

    def choose_language(self, code: str) -> None:
        self.language = code
        direction = Qt.LayoutDirection.RightToLeft if code == "he" else Qt.LayoutDirection.LeftToRight
        self.setLayoutDirection(direction)
        self.setWindowTitle(self.tr("window"))
        while self.pages.count() > 1:  # rebuild in the chosen language
            widget = self.pages.widget(1)
            self.pages.removeWidget(widget)
            widget.deleteLater()
        you = self._page(self.tr("you"))
        self.full_name = self._field(you, "full_name")
        self.username = self._field(you, "username")
        self.password = self._field(you, "password", secret=True)
        self.password2 = self._field(you, "password2", secret=True)
        self.full_name.textEdited.connect(self._suggest)
        you.addStretch(1)
        computer = self._page(self.tr("computer"), self.tr("computer_d"))
        self.hostname = self._field(computer, "computer")
        computer.addStretch(1)
        self.luks_page = None
        if self.needs_luks:
            luks = self._page(self.tr("luks"), self.tr("luks_d"))
            self.luks1 = self._field(luks, "luks1", secret=True)
            self.luks2 = self._field(luks, "luks2", secret=True)
            self.luks_ack = QCheckBox(self.tr("luks_ack"))
            luks.addWidget(self.luks_ack)
            luks.addStretch(1)
            self.luks_page = self.pages.count() - 1
        self.summary_layout = self._page(self.tr("summary"))
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_layout.addWidget(self.summary_label)
        self.summary_layout.addStretch(1)
        self.summary_page = self.pages.count() - 1
        self.status_layout = self._page(self.tr("working"))
        self.status_page = self.pages.count() - 1
        self.show_page(1)

    def _suggest(self, text: str) -> None:
        if not self.username.isModified():
            name = suggest_username(text)
            self.username.setText(name)
            if not self.hostname.isModified():
                self.hostname.setText(f"{name}-pc" if name else "")

    # -- navigation ----------------------------------------------------------------

    def show_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        self.error.clear()
        first, last = index == 0, index >= getattr(self, "status_page", 99)
        self.back_button.setVisible(not first and not last)
        self.next_button.setVisible(not first and not last)
        if not first:
            self.back_button.setText(self.tr("back"))
            self.next_button.setText(self.tr("finish") if index == getattr(self, "summary_page", -1) else self.tr("next"))
        if index == getattr(self, "summary_page", -1):
            owner = self.owner()
            self.summary_label.setText(self.tr("summary_d", name=owner.full_name, user=owner.username, host=owner.hostname,
                                               luks=self.tr("luks_yes" if self.needs_luks else "luks_no")))

    def back(self) -> None:
        self.show_page(max(1, self.pages.currentIndex() - 1))

    def owner(self) -> Owner:
        return Owner(self.full_name.text(), self.username.text().strip(), self.password.text(),
                     self.hostname.text().strip().lower(),
                     self.luks1.text() if self.needs_luks else None, self.language)

    def page_problems(self, index: int) -> list[str]:
        problems = validation_errors(self.owner(), self.taken, self.needs_luks)
        if index == 1:
            found = [p for p in problems if p in ("full_name", "username", "password")]
            if not found and self.password.text() != self.password2.text():
                found.append("match")
            return found
        if index == 2:
            return [p for p in problems if p == "hostname"]
        if index == self.luks_page:
            ok = "luks_password" not in problems and self.luks1.text() == self.luks2.text() and self.luks_ack.isChecked()
            return [] if ok else ["luks_password"]
        return []

    def next(self) -> None:
        index = self.pages.currentIndex()
        problems = self.page_problems(index)
        for edit, key in self._fields():
            edit.setProperty("invalid", key in problems)
            edit.style().unpolish(edit)
            edit.style().polish(edit)
        if problems:
            self.error.setText(" ".join(self.tr(f"e_{p}") for p in problems))
            return
        if index == self.summary_page:
            self.finish()
            return
        self.show_page(index + 1)

    def _fields(self) -> list[tuple[QLineEdit, str]]:
        fields = [(self.full_name, "full_name"), (self.username, "username"), (self.password, "password"),
                  (self.password2, "match"), (self.hostname, "hostname")]
        if self.needs_luks:
            fields += [(self.luks1, "luks_password"), (self.luks2, "luks_password")]
        return fields

    # -- finish ------------------------------------------------------------------------

    def finish(self) -> None:
        self.show_page(self.status_page)
        owner = self.owner()
        thread, worker = QThread(self), Worker(lambda _progress: self.finisher(owner))
        bridge = Bridge(self, self.finished, None, lambda: None)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(bridge.on_finished)
        worker.failed.connect(lambda error: self.finished({"ok": False, "error": error}))
        for signal in (worker.finished, worker.failed):
            signal.connect(thread.quit)
        thread.finished.connect(bridge.on_ended)
        self.threads.append((thread, worker))
        thread.start()

    def finished(self, reply: dict) -> None:
        if reply.get("ok"):
            label = QLabel(self.tr("done"))
            label.setObjectName("Title")
            self.status_layout.addWidget(label)
            QTimer.singleShot(3000, self.restarter)
            return
        # Back to the summary: the owner can fix a field and try again.
        self.show_page(self.summary_page)
        self.error.setText(self.tr("failed", error=str(reply.get("error", "?"))[:200]))


def main() -> int:
    app = QApplication(sys.argv[:1])
    app.setApplicationName("D.Ai Setup")
    app.setApplicationVersion(f"{__version__} — {__author__}")
    QGuiApplication.setDesktopFileName(APP_ID)
    machine = Machine(root=Path("/"))
    if machine.state().get("phase") != "pending":
        return 0  # finished or never prepared: nothing to show
    window = SetupWindow(machine)
    window.showFullScreen()
    app.exec()
    # Closed while still pending: non-zero, so the session starts the setup again.
    return 0 if machine.state().get("phase") != "pending" else 3
