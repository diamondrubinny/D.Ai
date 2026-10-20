# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The D.Ai VM window (docs/VM.md §1, §4): the machines on the left, the chosen one on the right with its
buttons and the "what Windows can see" panel, the hardware check at the top, and the wizard for a new machine.

The screen of a running machine is a separate window (remote-viewer over SPICE); this window manages.
Right-to-left in Hebrew, in the person's theme, every control named for screen readers and reachable with Tab.
"""
from __future__ import annotations

import datetime
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
                             QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSpinBox, QVBoxLayout,
                             QWidget)

from dai_i18n import pick, qt_direction, ui_lang
from dai_style import color
from dai_style.panes import Panes, WrapRow, touch_scrolling

from . import control, drivers, hardware, iso, machine, usb

APP_ID = "dai-vm"
REFRESH_MS = 3000
WINDOWS_DOWNLOAD_PAGE = "https://www.microsoft.com/software-download/windows11"  # Microsoft's own page; D.Ai never mirrors it

BG, BG2, SURFACE, BORDER, TEXT, MUTED = (color(r) for r in ("bg_900", "bg_800", "surface", "border", "text", "muted"))
ACCENT, ACCENT_STRONG, ACCENT_2, WARN, OK, DANGER = (color(r) for r in ("accent", "accent_strong", "accent_2", "warn",
                                                                        "ok", "danger"))
DISABLED = color("disabled")
STYLE = f"""
QWidget#Window, QDialog {{ background: {BG}; color: {TEXT}; }}
QLabel {{ color: {TEXT}; }}
#AppTitle {{ font-size: 12pt; font-weight: 700; color: {MUTED}; }}
#Title {{ font-size: 14pt; font-weight: 700; }}
#Muted {{ color: {MUTED}; }}
#Ok {{ color: {OK}; }}
#Warn {{ color: {WARN}; }}
#Fail {{ color: {DANGER}; }}
#Panel {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
QListWidget {{ background: {BG2}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 10px; outline: none;
    font-size: 11pt; padding: 4px; }}
QListWidget::item {{ padding: 6px; border-radius: 8px; }}
QListWidget::item:selected {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {ACCENT}; }}
QListWidget:focus {{ border: 2px solid {ACCENT_2}; }}
QLineEdit, QComboBox, QSpinBox {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 5px 10px; font-size: 11pt; selection-background-color: {ACCENT_STRONG}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 2px solid {ACCENT_2}; }}
QComboBox QAbstractItemView {{ background: {SURFACE}; color: {TEXT}; selection-background-color: {ACCENT_STRONG}; }}
QCheckBox {{ color: {TEXT}; }}
QCheckBox:focus {{ border: 1px solid {ACCENT_2}; border-radius: 4px; }}
QPushButton {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 12px; }}
QPushButton:hover {{ border: 1px solid {ACCENT}; }}
QPushButton:focus {{ border: 2px solid {ACCENT_2}; }}
QPushButton#Primary {{ background: {ACCENT_STRONG}; color: #FFFFFF; border: 1px solid {ACCENT_STRONG}; }}
QPushButton#Primary:focus {{ border: 2px solid {ACCENT_2}; }}
QPushButton:disabled {{ background: {SURFACE}; color: {DISABLED}; border: 1px solid {BORDER}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: {DISABLED}; }}
"""


def say(lang: str, en: str, he: str, **kwargs: object) -> str:
    return pick(lang, en, he).format(**kwargs)


def default_open_url(url: str) -> None:
    subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def default_spawn(argv: list[str]) -> None:
    subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


STATE_WORDS = {
    "running": ("running", "פועל"), "paused": ("paused", "מושהה"), "shut off": ("off", "כבוי"),
    "missing": ("not defined", "לא מוגדר"), "in shutdown": ("shutting down", "נכבה"), "crashed": ("crashed", "קרס"),
}


def state_word(state: str, lang: str) -> str:
    en, he = STATE_WORDS.get(state, (state, state))
    return say(lang, en, he)


class DownloadThread(QThread):
    progress = pyqtSignal(int)
    done = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, entry: drivers.Driver, home: Path | None, fetch=None) -> None:
        super().__init__()
        self.entry, self.home, self.fetch = entry, home, fetch

    def run(self) -> None:
        try:
            kwargs = {"fetch": self.fetch} if self.fetch else {}
            path = drivers.download(self.entry, self.home, progress=lambda d, t: self.progress.emit(d * 100 // max(1, t)),
                                    **kwargs)
            self.done.emit(str(path))
        except (drivers.DriverError, OSError) as exc:
            self.failed.emit(str(exc))


class ConfirmDialog(QDialog):
    def __init__(self, parent: QWidget, lang: str, title: str, text: str, yes: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setLayoutDirection(qt_direction(lang))
        self.setStyleSheet(STYLE)
        layout = QVBoxLayout(self)
        label = QLabel(text)
        label.setWordWrap(True)
        layout.addWidget(label)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(say(lang, "Cancel", "ביטול"))
        cancel.setAccessibleName(cancel.text())
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        ok = QPushButton(yes)
        ok.setObjectName("Primary")
        ok.setAccessibleName(yes)
        ok.clicked.connect(self.accept)
        buttons.addWidget(ok)
        layout.addLayout(buttons)


class NewMachineDialog(QDialog):
    """The wizard: the media, the edition, memory, CPUs, the disk, and the plain words about licenses."""

    def __init__(self, parent: QWidget, lang: str, report: hardware.Report, drivers_ready: bool,
                 open_url: Callable[[str], None] = default_open_url) -> None:
        super().__init__(parent)
        self.lang, self.report, self.open_url = lang, report, open_url
        self.setWindowTitle(say(lang, "A new machine", "מכונה חדשה"))
        self.setLayoutDirection(qt_direction(lang))
        self.setStyleSheet(STYLE)
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        lead = QLabel(say(lang, "D.Ai never downloads Windows. Download the ISO from Microsoft's page, choose it here, and "
                                "type your own key into Windows setup. Whether your license may run in a virtual machine "
                                "is set by Microsoft's terms for its edition.",
                          "D.Ai לעולם לא מוריד Windows. הורידו את ה-ISO מהעמוד של Microsoft, בחרו אותו כאן, והקלידו את "
                          "המפתח שלכם בהתקנת Windows. האם הרישיון שלכם רשאי לרוץ במכונה וירטואלית נקבע בתנאי Microsoft "
                          "למהדורה שלו."))
        lead.setWordWrap(True)
        layout.addWidget(lead)
        get = QPushButton(say(lang, "Open Microsoft's download page", "פתיחת עמוד ההורדה של Microsoft"))
        get.setAccessibleName(get.text())
        get.clicked.connect(lambda: self.open_url(WINDOWS_DOWNLOAD_PAGE))
        layout.addWidget(get, alignment=Qt.AlignmentFlag.AlignLeft)

        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("windows11")
        self.name.setAccessibleName(say(lang, "Name", "שם"))
        self.name.textChanged.connect(self.refresh)
        form.addRow(say(lang, "Name", "שם"), self.name)
        row = QHBoxLayout()
        self.iso_field = QLineEdit()
        self.iso_field.setAccessibleName(say(lang, "The installation ISO", "ה-ISO של ההתקנה"))
        self.iso_field.textChanged.connect(self.refresh)
        row.addWidget(self.iso_field, 1)
        browse = QPushButton(say(lang, "Choose…", "בחירה…"))
        browse.setAccessibleName(say(lang, "Choose the ISO file", "בחירת קובץ ה-ISO"))
        browse.clicked.connect(self.browse)
        row.addWidget(browse)
        form.addRow(say(lang, "Installation ISO", "ISO להתקנה"), row)
        self.iso_note = QLabel("")
        self.iso_note.setObjectName("Muted")
        self.iso_note.setWordWrap(True)
        form.addRow("", self.iso_note)
        self.windows = QComboBox()
        self.windows.setAccessibleName(say(lang, "Which system", "איזו מערכת"))
        self.windows.addItem("Windows 11", "11")
        self.windows.addItem("Windows 10", "10")
        self.windows.addItem(say(lang, "Another system", "מערכת אחרת"), "other")
        form.addRow(say(lang, "System", "מערכת"), self.windows)
        self.memory = QSpinBox()
        self.memory.setRange(hardware.MIN_GUEST_MB, max(hardware.MIN_GUEST_MB, min(hardware.MAX_GUEST_MB,
                                                                                    report.memory_mb - hardware.MIN_HOST_MB)))
        self.memory.setSingleStep(512)
        self.memory.setSuffix(" MB")
        self.memory.setValue(max(hardware.MIN_GUEST_MB, report.recommended_memory_mb()))
        self.memory.setAccessibleName(say(lang, "Memory", "זיכרון"))
        form.addRow(say(lang, "Memory", "זיכרון"), self.memory)
        self.cpus = QSpinBox()
        self.cpus.setRange(1, max(1, os.cpu_count() or 1))
        self.cpus.setValue(max(1, min(4, (os.cpu_count() or 2) // 2)))
        self.cpus.setAccessibleName(say(lang, "Processors", "מעבדים"))
        form.addRow(say(lang, "Processors", "מעבדים"), self.cpus)
        self.disk = QSpinBox()
        self.disk.setRange(machine.MIN_DISK_GB, machine.MAX_DISK_GB)
        self.disk.setValue(64)
        self.disk.setSuffix(" GB")
        self.disk.setAccessibleName(say(lang, "Disk size (grows as used)", "גודל דיסק (גדל לפי השימוש)"))
        form.addRow(say(lang, "Disk", "דיסק"), self.disk)
        self.attach_drivers = QCheckBox(say(lang, "Attach the VirtIO drivers CD (Windows setup needs it to see the disk)",
                                            "צירוף דיסק דרייברי VirtIO (התקנת Windows צריכה אותו כדי לראות את הדיסק)"))
        self.attach_drivers.setChecked(drivers_ready)
        self.attach_drivers.setEnabled(drivers_ready)
        self.attach_drivers.setAccessibleName(self.attach_drivers.text())
        form.addRow("", self.attach_drivers)
        layout.addLayout(form)
        if not drivers_ready:
            note = QLabel(say(lang, "The drivers are not downloaded yet: use the Download button in the main window first.",
                              "הדרייברים עדיין לא הורדו: השתמשו קודם בכפתור ההורדה בחלון הראשי."))
            note.setObjectName("Warn")
            note.setWordWrap(True)
            layout.addWidget(note)

        self.problem = QLabel("")
        self.problem.setObjectName("Fail")
        self.problem.setWordWrap(True)
        layout.addWidget(self.problem)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(say(lang, "Cancel", "ביטול"))
        cancel.setAccessibleName(cancel.text())
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.create_button = QPushButton(say(lang, "Create the machine", "יצירת המכונה"))
        self.create_button.setObjectName("Primary")
        self.create_button.setAccessibleName(self.create_button.text())
        self.create_button.clicked.connect(self.accept)
        buttons.addWidget(self.create_button)
        layout.addLayout(buttons)
        self.refresh()

    def browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, say(self.lang, "The installation ISO", "ה-ISO של ההתקנה"), "",
                                              say(self.lang, "Disc images (*.iso);;All files (*)", "תמונות דיסק (*.iso);;כל הקבצים (*)"))
        if path:
            self.iso_field.setText(path)

    def refresh(self) -> None:
        problems = []
        if not self.report.can_run:
            problems.append(say(self.lang, "This computer cannot run a machine yet (see the top of the window).",
                                "המחשב הזה עדיין לא יכול להריץ מכונה (ראו בראש החלון)."))
        if not machine.NAME_RE.match(self.name.text().strip()):
            problems.append(say(self.lang, "A name: letters, digits, dots, dashes, underscores.", "שם: אותיות, ספרות, נקודות, מקפים, קו תחתון."))
        path = self.iso_field.text().strip()
        self.iso_note.setText("")
        if path:
            try:
                info = iso.inspect(path)
                hint = say(self.lang, "label {label}, {gb:.1f} GB", "תווית {label}, {gb:.1f} GB", label=info.label, gb=info.size / 1024 ** 3)
                if not info.windows_hint:
                    hint += " · " + say(self.lang, "does not look like Windows media", "לא נראה כמו מדיה של Windows")
                self.iso_note.setText(hint)
            except iso.IsoError as exc:
                problems.append(str(exc))
        else:
            problems.append(say(self.lang, "Choose the installation ISO.", "בחרו את ה-ISO של ההתקנה."))
        self.problem.setText("\n".join(problems))
        self.create_button.setEnabled(not problems)

    def machine(self, drivers_iso: str | None) -> machine.Machine:
        return machine.Machine(
            name=self.name.text().strip(), memory_mb=self.memory.value(), cpus=self.cpus.value(), disk_gb=self.disk.value(),
            iso=self.iso_field.text().strip() or None,
            drivers_iso=drivers_iso if self.attach_drivers.isChecked() else None,
            windows=str(self.windows.currentData()), created=datetime.datetime.now().isoformat(timespec="seconds"),
        )


class VmWindow(QWidget):
    def __init__(self, lang: str | None = None, home: Path | None = None, virsh: control.Virsh | None = None,
                 report: hardware.Report | None = None, run=subprocess.run, spawn: Callable[[list[str]], None] = default_spawn,
                 open_url: Callable[[str], None] = default_open_url, fetch=None) -> None:
        super().__init__()
        self.lang = lang or ui_lang()
        self.home, self.run, self.spawn, self.open_url, self.fetch = home, run, spawn, open_url, fetch
        self.virsh = virsh or control.Virsh(run)
        self.report = report or hardware.check(self.lang, home=home)
        self.entry = drivers.catalog().get("virtio-win")
        self.thread: DownloadThread | None = None
        self.setObjectName("Window")
        self.setWindowTitle("D.Ai VM")
        self.setLayoutDirection(qt_direction(self.lang))
        self.setStyleSheet(STYLE)
        self.resize(980, 640)
        self._build()
        touch_scrolling(self)
        self.refresh_machines()
        self.timer = QTimer(self)
        self.timer.setInterval(REFRESH_MS)
        self.timer.timeout.connect(self.refresh_states)
        self.timer.start()

    def _button(self, text: str, slot: Callable, layout, primary: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setAccessibleName(text)
        if primary:
            button.setObjectName("Primary")
        button.clicked.connect(slot)
        layout.addWidget(button)
        return button

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        title = QLabel("💎 D.Ai VM")
        title.setObjectName("AppTitle")
        outer.addWidget(title)

        # the hardware check
        self.check_box = QFrame()
        self.check_box.setObjectName("Panel")
        check_layout = QVBoxLayout(self.check_box)
        for finding in self.report.findings:
            label = QLabel({"ok": "✓ ", "warn": "! ", "fail": "✗ "}[finding.level] + finding.text)
            label.setObjectName({"ok": "Ok", "warn": "Warn", "fail": "Fail"}[finding.level])
            label.setWordWrap(True)
            check_layout.addWidget(label)
        outer.addWidget(self.check_box)

        splitter = Panes()  # machines beside the details; above them when narrow (docs/MOBILE.md A2)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.machines = QListWidget()
        self.machines.setAccessibleName(say(self.lang, "Machines", "מכונות"))
        self.machines.currentRowChanged.connect(lambda _row: self.show_machine())
        left_layout.addWidget(self.machines, 1)
        self.new_button = self._button(say(self.lang, "＋ New machine…", "＋ מכונה חדשה…"), self.new_machine, left_layout, primary=True)
        self.new_button.setEnabled(self.report.can_run)
        drivers_row = QHBoxLayout()
        self.drivers_label = QLabel("")
        self.drivers_label.setObjectName("Muted")
        self.drivers_label.setWordWrap(True)
        drivers_row.addWidget(self.drivers_label, 1)
        self.download_button = self._button(say(self.lang, "Download drivers", "הורדת דרייברים"), self.download_drivers, drivers_row)
        left_layout.addLayout(drivers_row)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.machine_title = QLabel(say(self.lang, "Choose a machine, or make one.", "בחרו מכונה, או צרו אחת."))
        self.machine_title.setObjectName("Title")
        right_layout.addWidget(self.machine_title)
        self.details = QLabel("")
        self.details.setObjectName("Muted")
        self.details.setWordWrap(True)
        right_layout.addWidget(self.details)
        buttons = WrapRow()  # the actions wrap onto more rows when the window is narrow (docs/MOBILE.md A2)
        self.start_button = self._button(say(self.lang, "Start", "הפעלה"), lambda: self.act("start"), buttons, primary=True)
        self.show_button = self._button(say(self.lang, "Show the screen", "הצגת המסך"), lambda: self.act("show"), buttons)
        self.pause_button = self._button(say(self.lang, "Pause", "השהיה"), lambda: self.act("pause"), buttons)
        self.resume_button = self._button(say(self.lang, "Resume", "המשך"), lambda: self.act("resume"), buttons)
        self.stop_button = self._button(say(self.lang, "Shut down", "כיבוי"), lambda: self.act("stop"), buttons)
        self.poweroff_button = self._button(say(self.lang, "Force off", "כיבוי בכוח"), lambda: self.act("poweroff"), buttons)
        self.delete_button = self._button(say(self.lang, "Delete…", "מחיקה…"), self.delete_machine, buttons)
        right_layout.addLayout(buttons)

        sees = QFrame()
        sees.setObjectName("Panel")
        sees_layout = QVBoxLayout(sees)
        sees_title = QLabel(say(self.lang, "What Windows can see", "מה Windows רואה"))
        sees_title.setObjectName("Title")
        sees_layout.addWidget(sees_title)
        self.sees_labels = []
        for text in (say(self.lang, "Network: the internet through D.Ai, as a NAT client (passt). Nothing of the local "
                                    "network reaches in.", "רשת: האינטרנט דרך D.Ai, כלקוח NAT ‏(passt). שום דבר מהרשת המקומית לא נכנס."),
                     say(self.lang, "Your files: only what you share below.", "הקבצים שלכם: רק מה שתשתפו למטה.")):
            label = QLabel("• " + text)
            label.setWordWrap(True)
            sees_layout.addWidget(label)
            self.sees_labels.append(label)
        # Stage 2 (docs/VM.md): each thing Windows may see is a switch, off by default, saved per machine.
        self.clipboard_box = QCheckBox(say(self.lang, "Share the clipboard (both directions; takes effect at the next start)",
                                           "שיתוף הלוח (לשני הכיוונים; נכנס לתוקף בהפעלה הבאה)"))
        self.clipboard_box.setAccessibleName(say(self.lang, "Share the clipboard", "שיתוף הלוח"))
        self.clipboard_box.toggled.connect(self._clipboard_toggled)
        sees_layout.addWidget(self.clipboard_box)
        folder_row = WrapRow()
        self.folder_label = QLabel(say(self.lang, "Shared folder: none.", "תיקייה משותפת: אין."))
        self.folder_label.setWordWrap(True)
        folder_row.addWidget(self.folder_label)
        self.folder_button = self._button(say(self.lang, "Choose a folder…", "בחירת תיקייה…"), self.choose_folder, folder_row)
        self.unshare_button = self._button(say(self.lang, "Stop sharing", "הפסקת השיתוף"), lambda: self.set_folder(None), folder_row)
        sees_layout.addLayout(folder_row)
        self.writable_box = QCheckBox(say(self.lang, "Windows may also write into the folder", "Windows רשאי גם לכתוב לתיקייה"))
        self.writable_box.setAccessibleName(self.writable_box.text())
        self.writable_box.toggled.connect(self._writable_toggled)
        sees_layout.addWidget(self.writable_box)
        usb_title = QLabel(say(self.lang, "USB devices (tick one to give it to the machine; D.Ai loses it meanwhile)",
                               "התקני USB (סמנו כדי לתת למכונה; D.Ai מאבד אותו בינתיים)"))
        usb_title.setWordWrap(True)
        sees_layout.addWidget(usb_title)
        self.usb_list = QListWidget()
        self.usb_list.setAccessibleName(say(self.lang, "USB devices", "התקני USB"))
        self.usb_list.setMaximumHeight(140)
        self.usb_list.itemChanged.connect(self._usb_toggled)
        sees_layout.addWidget(self.usb_list)
        self.usb_refresh_button = self._button(say(self.lang, "Look again", "בדיקה מחדש"), self.refresh_usb, sees_layout)
        right_layout.addWidget(sees)

        snaps = QFrame()
        snaps.setObjectName("Panel")
        snaps_layout = QVBoxLayout(snaps)
        snaps_title = QLabel(say(self.lang, "Snapshots", "תמונות מצב"))
        snaps_title.setObjectName("Title")
        snaps_layout.addWidget(snaps_title)
        snaps_hint = QLabel(say(self.lang, "A snapshot keeps the whole machine as it is now; go back to it after a bad update.",
                                "תמונת מצב שומרת את המכונה כולה כמו שהיא עכשיו; חוזרים אליה אחרי עדכון גרוע."))
        snaps_hint.setObjectName("Muted")
        snaps_hint.setWordWrap(True)
        snaps_layout.addWidget(snaps_hint)
        self.snapshot_list = QListWidget()
        self.snapshot_list.setAccessibleName(say(self.lang, "Snapshots", "תמונות מצב"))
        self.snapshot_list.setMaximumHeight(140)
        self.snapshot_list.currentRowChanged.connect(lambda _r: self._snapshot_buttons())
        snaps_layout.addWidget(self.snapshot_list)
        snap_row = WrapRow()
        self.snapshot_button = self._button(say(self.lang, "Take a snapshot", "צילום מצב"), self.take_snapshot, snap_row, primary=True)
        self.revert_button = self._button(say(self.lang, "Go back to it", "חזרה אליה"), self.revert_snapshot, snap_row)
        self.snapshot_delete_button = self._button(say(self.lang, "Delete it", "מחיקתה"), self.delete_snapshot, snap_row)
        snaps_layout.addLayout(snap_row)
        right_layout.addWidget(snaps)
        right_layout.addStretch(1)
        self._syncing = False
        scroll = QScrollArea()  # the details scroll when the window is short or narrow (docs/MOBILE.md A2)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        scroll.setWidget(right)
        splitter.addWidget(scroll)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 680])
        outer.addWidget(splitter, 1)

        self.status = QLabel(say(self.lang, "Machines run as you, in your home folder; nothing about them leaves this computer.",
                                 "מכונות רצות כמוכם, בתיקיית הבית; שום דבר עליהן לא יוצא מהמחשב הזה."))
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        self.refresh_drivers()

    # --- machines ----------------------------------------------------------------------------------------------

    def current(self) -> machine.Machine | None:
        row = self.machines.currentRow()
        if row < 0 or row >= len(self.loaded):
            return None
        return self.loaded[row]

    def refresh_machines(self) -> None:
        chosen = self.current().name if self.current() else None
        self.loaded = machine.list_machines(self.home)
        self.machines.clear()
        for m in self.loaded:
            self.machines.addItem(f"{m.name} · {state_word(self.virsh.state(m.name) if self.virsh.available() else 'missing', self.lang)}")
        if self.loaded:
            index = next((i for i, m in enumerate(self.loaded) if m.name == chosen), 0)
            self.machines.setCurrentRow(index)
        self.show_machine()

    def refresh_states(self) -> None:
        if not self.virsh.available():
            return
        for i, m in enumerate(self.loaded):
            item = self.machines.item(i)
            if item is not None:
                item.setText(f"{m.name} · {state_word(self.virsh.state(m.name), self.lang)}")
        self.show_machine()

    def show_machine(self) -> None:
        m = self.current()
        running = paused = False
        if m is None:
            self.machine_title.setText(say(self.lang, "Choose a machine, or make one.", "בחרו מכונה, או צרו אחת."))
            self.details.setText("")
        else:
            state = self.virsh.state(m.name) if self.virsh.available() else "missing"
            running, paused = state == "running", state == "paused"
            self.machine_title.setText(f"{m.name} · {state_word(state, self.lang)}")
            self.details.setText(say(self.lang, "{mb} MB memory · {cpus} processors · {gb} GB disk · Windows {win} · media: {iso}",
                                     "{mb} MB זיכרון · {cpus} מעבדים · דיסק {gb} GB · Windows {win} · מדיה: {iso}",
                                     mb=m.memory_mb, cpus=m.cpus, gb=m.disk_gb, win=m.windows,
                                     iso=Path(m.iso).name if m.iso else say(self.lang, "none", "אין")))
        self._fill_sharing(m, running or paused)
        self.start_button.setEnabled(m is not None and not running and not paused)
        self.show_button.setEnabled(running or paused)
        self.pause_button.setEnabled(running)
        self.resume_button.setEnabled(paused)
        self.stop_button.setEnabled(running)
        self.poweroff_button.setEnabled(running or paused)
        self.delete_button.setEnabled(m is not None)

    def act(self, verb: str) -> None:
        m = self.current()
        if m is None:
            return
        try:
            if verb == "start":
                if self.virsh.state(m.name) == "missing":
                    self.virsh.define(machine.machine_dir(m.name, self.home) / "domain.xml")
                self.virsh.start(m.name)
                self.status.setText(say(self.lang, "{name} is starting. Its screen opens in its own window.",
                                        "{name} מופעל. המסך שלו נפתח בחלון משלו.", name=m.name))
                self.spawn(control.viewer_argv(f"{m.name} · D.Ai VM", self.virsh.display(m.name)))
            elif verb == "show":
                self.spawn(control.viewer_argv(f"{m.name} · D.Ai VM", self.virsh.display(m.name)))
            elif verb == "pause":
                self.virsh.pause(m.name)
            elif verb == "resume":
                self.virsh.resume(m.name)
            elif verb == "stop":
                self.virsh.shutdown(m.name)
                self.status.setText(say(self.lang, "{name} was asked to shut down, the way Windows likes it.",
                                        "{name} התבקש להיכבות, כמו ש-Windows אוהב.", name=m.name))
            elif verb == "poweroff":
                self.virsh.poweroff(m.name)
        except control.VmError as exc:
            self.status.setText(say(self.lang, "That did not work: {why}", "זה לא הצליח: {why}", why=exc))
        self.refresh_states()

    # --- sharing, USB, snapshots (stage 2) ---------------------------------------------------------------------

    def _fill_sharing(self, m: machine.Machine | None, live: bool) -> None:
        self._syncing = True
        try:
            has = m is not None
            for widget in (self.clipboard_box, self.folder_button, self.unshare_button, self.writable_box, self.usb_list,
                           self.usb_refresh_button, self.snapshot_list, self.snapshot_button):
                widget.setEnabled(has)
            self.clipboard_box.setChecked(bool(m and m.clipboard))
            if m and m.shared_folder:
                self.folder_label.setText(say(self.lang, "Shared folder: {path}", "תיקייה משותפת: {path}", path=m.shared_folder))
                self.writable_box.setChecked(not m.shared_readonly)
                self.writable_box.setEnabled(True)
                self.unshare_button.setEnabled(True)
            else:
                self.folder_label.setText(say(self.lang, "Shared folder: none.", "תיקייה משותפת: אין."))
                self.writable_box.setChecked(False)
                self.writable_box.setEnabled(False)
                self.unshare_button.setEnabled(False)
            self.refresh_usb(m)
            self.refresh_snapshots(m)
        finally:
            self._syncing = False

    def refresh_usb(self, m: machine.Machine | None = None) -> None:
        m = self.current() if m is None else m
        self._syncing = True
        try:
            self.usb_list.clear()
            for device in usb.list_devices():
                item = QListWidgetItem(device.label)
                item.setData(Qt.ItemDataRole.UserRole, device.usb_id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if m and device.usb_id in m.usb else Qt.CheckState.Unchecked)
                self.usb_list.addItem(item)
            if self.usb_list.count() == 0:
                self.usb_list.addItem(say(self.lang, "No USB devices plugged in (hubs are not listed).", "אין התקני USB מחוברים (רכזות לא מוצגות)."))
        finally:
            self._syncing = False

    def _save_sharing(self, m: machine.Machine, done: str) -> None:
        try:
            definition = machine.update(m, self.home)
            if self.virsh.available() and self.virsh.state(m.name) != "missing":
                self.virsh.redefine(definition)
        except (machine.MachineError, control.VmError) as exc:
            self.status.setText(say(self.lang, "Not changed: {why}", "לא שונה: {why}", why=exc))
            self.refresh_machines()
            return
        self.status.setText(done)
        self.refresh_machines()

    def _clipboard_toggled(self, on: bool) -> None:
        m = self.current()
        if self._syncing or m is None:
            return
        m.clipboard = bool(on)
        self._save_sharing(m, say(self.lang, "Clipboard {state} for {name}; takes effect at the next start.",
                                  "הלוח {state} עבור {name}; נכנס לתוקף בהפעלה הבאה.", name=m.name,
                                  state=say(self.lang, "shared", "משותף") if on else say(self.lang, "not shared", "לא משותף")))

    def choose_folder(self) -> None:
        if self.current() is None:
            return
        path = QFileDialog.getExistingDirectory(self, say(self.lang, "A folder Windows may see", "תיקייה ש-Windows יראה"),
                                                str(self.home or Path.home()))
        if path:
            self.set_folder(path)

    def set_folder(self, path: str | None) -> None:
        m = self.current()
        if m is None:
            return
        m.shared_folder = path
        self._save_sharing(m, say(self.lang, "{name} will see {path} (read-only unless you allow writing) at its next start.",
                                  "{name} יראה את {path} (לקריאה בלבד, אלא אם תאפשרו כתיבה) בהפעלה הבאה.", name=m.name, path=path)
                           if path else say(self.lang, "{name} sees no folder of yours.", "{name} לא רואה שום תיקייה שלכם.", name=m.name))

    def _writable_toggled(self, on: bool) -> None:
        m = self.current()
        if self._syncing or m is None or not m.shared_folder:
            return
        m.shared_readonly = not on
        self._save_sharing(m, say(self.lang, "Windows may write into the folder.", "Windows רשאי לכתוב לתיקייה.") if on
                           else say(self.lang, "The folder is read-only for Windows.", "התיקייה לקריאה בלבד עבור Windows."))

    def _usb_toggled(self, item: QListWidgetItem) -> None:
        m = self.current()
        usb_id = item.data(Qt.ItemDataRole.UserRole)
        if self._syncing or m is None or not usb_id:
            return
        give = item.checkState() == Qt.CheckState.Checked
        if give and usb_id not in m.usb:
            m.usb.append(usb_id)
        if not give:
            m.usb = [x for x in m.usb if x != usb_id]
        try:
            definition = machine.update(m, self.home)
            if self.virsh.available() and self.virsh.state(m.name) != "missing":
                self.virsh.redefine(definition)
                if self.virsh.state(m.name) == "running":
                    (self.virsh.attach_usb if give else self.virsh.detach_usb)(m.name, usb_id)
        except (machine.MachineError, control.VmError) as exc:
            self.status.setText(say(self.lang, "That did not work: {why}", "זה לא הצליח: {why}", why=exc))
            return
        self.status.setText(say(self.lang, "{id} now belongs to {name}. D.Ai does not see it while the machine has it.",
                                "{id} שייך עכשיו ל-{name}. D.Ai לא רואה אותו כל עוד המכונה מחזיקה בו.", id=usb_id, name=m.name) if give
                            else say(self.lang, "{id} is back with D.Ai.", "{id} חזר ל-D.Ai.", id=usb_id))

    def refresh_snapshots(self, m: machine.Machine | None = None) -> None:
        m = self.current() if m is None else m
        self.snapshot_list.clear()
        if m is not None and self.virsh.available():
            for snap in self.virsh.snapshots(m.name):
                item = QListWidgetItem(("★ " if snap["current"] else "") + f"{snap['label']} · {snap['when']}")
                item.setData(Qt.ItemDataRole.UserRole, snap["label"])
                self.snapshot_list.addItem(item)
        self._snapshot_buttons()

    def _snapshot_buttons(self) -> None:
        chosen = self.snapshot_list.currentItem()
        has = chosen is not None and bool(chosen.data(Qt.ItemDataRole.UserRole))
        self.revert_button.setEnabled(has)
        self.snapshot_delete_button.setEnabled(has)

    def take_snapshot(self, label: str | None = None) -> None:
        m = self.current()
        if m is None:
            return
        if label is None:
            from PyQt6.QtWidgets import QInputDialog
            label, ok = QInputDialog.getText(self, say(self.lang, "Take a snapshot", "צילום מצב"),
                                             say(self.lang, "A name for it (letters, digits, dots, dashes):", "שם (אותיות, ספרות, נקודות, מקפים):"),
                                             text=datetime.datetime.now().strftime("%Y-%m-%d-%H%M"))
            if not ok:
                return
        if not machine.NAME_RE.match(label or ""):
            self.status.setText(say(self.lang, "A snapshot name is letters, digits, dots, dashes and underscores.",
                                    "שם תמונת מצב הוא אותיות, ספרות, נקודות, מקפים וקווים תחתונים."))
            return
        try:
            self.virsh.snapshot_take(m.name, label)
        except control.VmError as exc:
            self.status.setText(say(self.lang, "That did not work: {why}", "זה לא הצליח: {why}", why=exc))
            return
        self.status.setText(say(self.lang, "Snapshot {label} of {name} taken.", "תמונת המצב {label} של {name} נשמרה.", label=label, name=m.name))
        self.refresh_snapshots(m)

    def _chosen_snapshot(self) -> str | None:
        item = self.snapshot_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def revert_snapshot(self) -> None:
        m, label = self.current(), self._chosen_snapshot()
        if m is None or not label:
            return
        dialog = ConfirmDialog(self, self.lang, say(self.lang, "Go back to {label}?", "לחזור ל-{label}?", label=label),
                               say(self.lang, "Everything done in the machine since then is lost, unless it is in a later snapshot.",
                                   "כל מה שנעשה במכונה מאז יאבד, אלא אם הוא בתמונת מצב מאוחרת יותר."),
                               say(self.lang, "Go back", "חזרה"))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.virsh.snapshot_revert(m.name, label)
        except control.VmError as exc:
            self.status.setText(say(self.lang, "That did not work: {why}", "זה לא הצליח: {why}", why=exc))
            return
        self.status.setText(say(self.lang, "{name} is back at {label}.", "{name} חזר ל-{label}.", name=m.name, label=label))
        self.refresh_states()

    def delete_snapshot(self) -> None:
        m, label = self.current(), self._chosen_snapshot()
        if m is None or not label:
            return
        try:
            self.virsh.snapshot_delete(m.name, label)
        except control.VmError as exc:
            self.status.setText(say(self.lang, "That did not work: {why}", "זה לא הצליח: {why}", why=exc))
            return
        self.status.setText(say(self.lang, "Snapshot {label} deleted.", "תמונת המצב {label} נמחקה.", label=label))
        self.refresh_snapshots(m)

    def new_machine(self) -> None:
        ready = bool(self.entry and drivers.present(self.entry, self.home))
        dialog = NewMachineDialog(self, self.lang, self.report, ready, self.open_url)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.create_from(dialog)

    def create_from(self, dialog: NewMachineDialog) -> bool:
        drivers_iso = str(drivers.iso_path(self.entry, self.home)) if self.entry and drivers.present(self.entry, self.home) else None
        try:
            m = dialog.machine(drivers_iso)
            definition = machine.create(m, self.home, self.run)
            self.virsh.define(definition)
        except (machine.MachineError, control.VmError, ValueError) as exc:
            self.status.setText(say(self.lang, "Not created: {why}", "לא נוצר: {why}", why=exc))
            return False
        self.status.setText(say(self.lang, "{name} is ready. Start it, and Windows setup begins in its window.",
                                "{name} מוכן. הפעילו אותו, והתקנת Windows תתחיל בחלון שלו.", name=m.name))
        self.refresh_machines()
        for i, loaded in enumerate(self.loaded):
            if loaded.name == m.name:
                self.machines.setCurrentRow(i)
        return True

    def delete_machine(self) -> None:
        m = self.current()
        if m is None:
            return
        dialog = ConfirmDialog(self, self.lang, say(self.lang, "Delete {name}?", "למחוק את {name}?", name=m.name),
                               say(self.lang, "This deletes the machine and its disk, with everything installed in it. "
                                              "There is no undo.", "זה מוחק את המכונה ואת הדיסק שלה, עם כל מה שמותקן בה. אין ביטול."),
                               say(self.lang, "Delete", "מחיקה"))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.really_delete(m)

    def really_delete(self, m: machine.Machine) -> None:
        try:
            if self.virsh.available():
                if self.virsh.state(m.name) == "running":
                    self.virsh.poweroff(m.name)
                self.virsh.undefine(m.name)
        except control.VmError:
            pass
        shutil.rmtree(machine.machine_dir(m.name, self.home), ignore_errors=True)
        self.status.setText(say(self.lang, "{name} was deleted.", "{name} נמחק.", name=m.name))
        self.refresh_machines()

    # --- drivers -----------------------------------------------------------------------------------------------

    def refresh_drivers(self) -> None:
        if self.entry is None:
            self.drivers_label.setText(say(self.lang, "No driver catalog.", "אין קטלוג דרייברים."))
            self.download_button.setEnabled(False)
            return
        if drivers.present(self.entry, self.home):
            self.drivers_label.setText(say(self.lang, "VirtIO drivers {v}: ready.", "דרייברי VirtIO ‏{v}: מוכנים.", v=self.entry.version))
            self.download_button.setEnabled(False)
        else:
            self.drivers_label.setText(say(self.lang, "VirtIO drivers for Windows: not downloaded ({mb} MB, from Fedora, "
                                                      "checked against a pinned SHA-256).",
                                           "דרייברי VirtIO ל-Windows: לא הורדו ({mb} MB, מ-Fedora, נבדקים מול SHA-256 קבוע).",
                                           mb=self.entry.size // (1024 * 1024)))
            self.download_button.setEnabled(self.entry.pinned and self.thread is None)

    def download_drivers(self) -> None:
        if self.entry is None or self.thread is not None:
            return
        self.thread = DownloadThread(self.entry, self.home, self.fetch)
        self.thread.progress.connect(lambda pct: self.drivers_label.setText(
            say(self.lang, "Downloading the drivers… {pct}%", "מוריד את הדרייברים… {pct}%", pct=pct)))
        self.thread.done.connect(self._download_done)
        self.thread.failed.connect(self._download_failed)
        self.download_button.setEnabled(False)
        self.thread.start()

    def _download_done(self, path: str) -> None:
        self.thread = None
        self.status.setText(say(self.lang, "Drivers downloaded and verified.", "הדרייברים הורדו ואומתו."))
        self.refresh_drivers()

    def _download_failed(self, why: str) -> None:
        self.thread = None
        self.status.setText(say(self.lang, "The download failed: {why}", "ההורדה נכשלה: {why}", why=why))
        self.refresh_drivers()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt's name
        if self.thread is not None:
            self.thread.wait(2000)
        super().closeEvent(event)


def main(argv: list[str] | None = None) -> int:
    app = QApplication(list(sys.argv if argv is None else argv))
    app.setDesktopFileName(APP_ID)
    window = VmWindow()
    window.show()
    return app.exec()
