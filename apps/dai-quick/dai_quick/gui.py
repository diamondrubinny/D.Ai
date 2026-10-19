# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The D.Ai Quick window (docs/TASKBAR.md §2.4): opens from the clock or Super+N,
closes with Esc or when it loses focus. Everything is reachable with the
keyboard, every control has an accessible name, and it mirrors in Hebrew.
"""

from __future__ import annotations

import subprocess
import time

from PyQt6.QtCore import QEvent, QSize, Qt, QTimer
from PyQt6.QtGui import QFont, QFontDatabase, QIcon, QKeyEvent
from PyQt6.QtWidgets import (QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSlider,
                             QToolButton, QVBoxLayout, QWidget)

from dai_i18n import embed, is_rtl, pick, qt_direction, text, ui_lang
from dai_style import themed

from . import __author__, __version__
from .controls import TOGGLES, Controls

STRINGS = {
    "title": ("D.Ai Quick", "D.Ai Quick"),
    "wifi": ("Wi-Fi", "Wi‑Fi"),
    "bluetooth": ("Bluetooth", "Bluetooth"),
    "dnd": ("Do not disturb", "לא להפריע"),
    "saver": ("Battery saver", "חיסכון בסוללה"),
    "mic": ("Mute mic", "השתקת מיק׳"),
    "on": ("on", "פועל"),
    "off": ("off", "כבוי"),
    "volume": ("Volume", "עוצמת שמע"),
    "security": ("Security {score}/100", "אבטחה {score}/100"),
    "security_unknown": ("Security score unavailable", "ציון האבטחה לא זמין"),
    "improve": ("Improve", "לשפר"),
    "healthy": ("Everything works", "הכל עובד"),
    "problems": ("D.Ai Heal found {count} problem(s)", "D.Ai Heal מצא תקלות ({count})"),
    "help": ("Get help", "לקבל עזרה"),
    "quiet": ("Nothing is recording", "שום דבר לא מקליט"),
    "recording": ("Recording now: {apps}", "מקליט עכשיו: {apps}"),
    "log": ("Who used it", "מי השתמש"),
    "dnd_note": ("Pop-ups are hidden; recording and problems still show on the diamond.",
                 "ההתראות מוסתרות; הקלטה ותקלות עדיין מוצגות על היהלום."),
}

STYLE = themed("""
QFrame#Quick { background: rgba(20, 27, 51, 250); border: 1px solid rgba(124, 92, 255, 115); border-radius: 18px; }
QWidget { color: #E6E9F5; font-size: 10.5pt; }
QLabel#Title { color: #B8A6FF; font-weight: 700; letter-spacing: 1px; font-size: 10pt; }
QLabel#Muted { color: #9AA3C7; font-size: 9.5pt; }
QToolButton#Tile { background: #1C2547; border: 1px solid #2A3563; border-radius: 12px; padding: 8px 6px;
                   min-width: 108px; min-height: 52px; }
QToolButton#Tile:hover { border: 1px solid #7C5CFF; }
QToolButton#Tile:checked { background: rgba(91, 63, 214, 90); border: 2px solid #7C5CFF; }  /* the same text colour in every theme */
QToolButton#Tile:focus, QPushButton:focus, QSlider:focus { border: 2px solid #22D3EE; }
QFrame#Row { background: rgba(11, 16, 32, 160); border-radius: 10px; }
QPushButton { background: transparent; border: 1px solid transparent; border-radius: 8px; color: #22D3EE; padding: 3px 8px; }
QPushButton:hover { border: 1px solid #22D3EE; }
QSlider::groove:horizontal { height: 6px; border-radius: 3px; background: #2A3563; }
QSlider::sub-page:horizontal { border-radius: 3px; background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7C5CFF, stop:1 #22D3EE); }
QSlider::handle:horizontal { background: #FFFFFF; width: 14px; margin: -5px 0; border-radius: 7px; }
""")


def _spawn(argv: list[str]) -> None:
    subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)


def _terminal(*command: str) -> list[str]:
    return ["x-terminal-emulator", "-e", "bash", "-c", '"$@"; echo; read -r -p "Enter ↵" _', "dai", *command]


class QuickWindow(QWidget):
    def __init__(self, controls: Controls | None = None, lang: str | None = None, spawn=_spawn,
                 close_on_blur: bool = True) -> None:
        super().__init__(objectName="QuickWindow")
        self.controls = controls or Controls()
        self.lang = lang or ui_lang()
        self.spawn = spawn
        self.close_on_blur = close_on_blur
        self.tiles: dict[str, QToolButton] = {}
        self.setWindowTitle("D.Ai Quick")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setLayoutDirection(qt_direction(self.lang))
        self.setStyleSheet(STYLE)
        self.setFixedWidth(420)

        card = QFrame(self, objectName="Quick")  # a child paints its rounded background; a translucent window does not
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        layout.addWidget(QLabel(self.t("title").upper(), objectName="Title"))

        grid = QGridLayout()
        grid.setSpacing(8)
        shown = 0
        for toggle in TOGGLES:
            state = self.controls.read(toggle.key)
            if state is None:
                continue  # this computer does not have it
            tile = QToolButton(objectName="Tile")
            tile.setCheckable(True)
            tile.setChecked(state)
            icon = next((QIcon.fromTheme(n) for n in toggle.icon.split("|") if QIcon.hasThemeIcon(n)), QIcon())
            if icon.isNull():
                tile.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            else:
                tile.setIcon(icon)
                tile.setIconSize(QSize(22, 22))
                tile.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            tile.clicked.connect(lambda checked, key=toggle.key: self.toggle(key, checked))
            self.tiles[toggle.key] = tile
            self._label_tile(toggle.key)
            grid.addWidget(tile, shown // 3, shown % 3)
            shown += 1
        layout.addLayout(grid)
        self.dnd_note = QLabel(self.t("dnd_note"), objectName="Muted")
        self.dnd_note.setWordWrap(True)
        self.dnd_note.setVisible(bool(self.tiles.get("dnd") and self.tiles["dnd"].isChecked()))
        layout.addWidget(self.dnd_note)

        volume = self.controls.volume()
        self.slider = None
        if volume is not None:
            row = self._row(layout)
            row.addWidget(QLabel("🔊"))
            self.slider = QSlider(Qt.Orientation.Horizontal)
            self.slider.setRange(0, 100)
            self.slider.setValue(volume)
            self.slider.setAccessibleName(self.t("volume"))
            self.slider.valueChanged.connect(self._volume_later)
            row.addWidget(self.slider, 1)
            self._volume_timer = QTimer(self, singleShot=True, interval=120)
            self._volume_timer.timeout.connect(lambda: self.controls.set_volume(self.slider.value()))

        score = self.controls.security(self.lang)
        row = self._row(layout)
        self.security_label = QLabel(self.t("security", score=score) if score is not None else self.t("security_unknown"))
        row.addWidget(self.security_label, 1)
        improve = QPushButton(embed(self.t("improve") + " ›", self.lang))
        improve.clicked.connect(lambda: self._open(_terminal("dai-tune", "status")))
        row.addWidget(improve)

        status = self.controls.status()
        heal = int(status.get("heal", 0) or 0)
        row = self._row(layout)
        self.heal_label = QLabel("🩺 " + (self.t("problems", count=heal) if heal else self.t("healthy")))
        row.addWidget(self.heal_label, 1)
        if heal:
            help_button = QPushButton(embed(self.t("help") + " ›", self.lang))
            help_button.clicked.connect(lambda: self._open(["dai-heal"]))
            row.addWidget(help_button)

        recording = [str(a) for a in status.get("privacy", []) if isinstance(a, str)][:3]
        row = self._row(layout)
        self.privacy_label = QLabel(("🔴 " + self.t("recording", apps=", ".join(recording))) if recording
                                    else "🔒 " + self.t("quiet"))
        self.privacy_label.setTextFormat(Qt.TextFormat.PlainText)  # app names are never markup
        row.addWidget(self.privacy_label, 1)
        log = QPushButton(embed(self.t("log") + " ›", self.lang))
        log.clicked.connect(lambda: self._open(_terminal("dai-privacy", "log")))
        row.addWidget(log)

        date = QLabel(time.strftime("%A %d.%m.%Y · %H:%M"), objectName="Muted")
        date.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(date)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def t(self, key: str, **kwargs: object) -> str:
        return text(self.lang, *STRINGS[key], **kwargs) if kwargs else pick(self.lang, *STRINGS[key])

    def _row(self, layout: QVBoxLayout) -> QHBoxLayout:
        frame = QFrame(objectName="Row")
        row = QHBoxLayout(frame)
        row.setContentsMargins(10, 6, 6, 6)
        layout.addWidget(frame)
        return row

    def _label_tile(self, key: str) -> None:
        tile = self.tiles[key]
        state = self.t("on") if tile.isChecked() else self.t("off")
        fallback = next(t.fallback for t in TOGGLES if t.key == key)
        tile.setText(self.t(key) if not tile.icon().isNull() else f"{fallback}\n{self.t(key)}")
        tile.setAccessibleName(f"{self.t(key)}: {state}")
        tile.setToolTip(f"{self.t(key)}: {state}")

    def toggle(self, key: str, wanted: bool) -> None:
        self.controls.set(key, wanted)
        actual = self.controls.read(key)  # show what is true, not what was asked for
        tile = self.tiles[key]
        tile.setChecked(bool(actual))
        self._label_tile(key)
        if key == "dnd":
            self.dnd_note.setVisible(bool(actual))

    def _volume_later(self, _value: int) -> None:
        self._volume_timer.start()  # one wpctl call when the slider settles

    def _open(self, argv: list[str]) -> None:
        self.spawn(argv)
        self.close()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        # Like a popup: clicking elsewhere closes it.
        if event.type() == QEvent.Type.ActivationChange and self.close_on_blur and not self.isActiveWindow():
            QTimer.singleShot(150, lambda: None if self.isActiveWindow() else self.close())
        super().changeEvent(event)


def main(controls: Controls | None = None) -> int:
    lang = ui_lang()
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("D.Ai Quick")
    app.setApplicationVersion(__version__)
    app.setOrganizationName(__author__)
    # labwc places the window by app id (rc.xml): next to the clock, which is on the left in Hebrew.
    app.setDesktopFileName("dai-quick-rtl" if is_rtl(lang) else "dai-quick")
    app.setLayoutDirection(qt_direction(lang))
    if "Noto Sans" in QFontDatabase.families():
        app.setFont(QFont("Noto Sans", 10))
    window = QuickWindow(controls, lang)
    window.show()
    window.activateWindow()
    first = next(iter(window.tiles.values()), None)
    if first is not None:
        first.setFocus()
    return app.exec()
