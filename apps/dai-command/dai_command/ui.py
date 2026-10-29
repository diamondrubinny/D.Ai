# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""PyQt6 user interface for D.Ai Command."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QEvent, QModelIndex, QObject, QRect, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QIcon, QKeyEvent, QPainter, QPalette, QTextOption
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QTextBrowser,
    QStyleOptionViewItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dai_style import color, with_touch
from dai_style.panes import fit_width

from . import __author__, __version__
from .core import Action, History, build_actions, load_apps, tr

APP_ID = "dai-command"
LOGO = Path(os.environ.get("DAI_BRANDING_DIR", "/usr/share/dai/branding")) / "dai-logo.svg"
ACTION_ROLE = Qt.ItemDataRole.UserRole + 1
MAX_ROWS = 8

# Design tokens (docs/DESIGN.md §2)
BG = color("bg_900")  # in the person's theme (docs/V2.md D1)
SURFACE = color("surface")
BORDER = color("border")
TEXT = color("text")
MUTED = color("muted")
ACCENT = color("accent")
ACCENT_STRONG = color("accent_strong")
ACCENT_2 = color("accent_2")
DANGER = color("danger")

STYLE = f"""
#Card {{
    background: {BG};
    border: 1px solid {BORDER};
    border-top: 2px solid {ACCENT};
    border-radius: 14px;
}}
#Query {{
    background: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 10px 14px;
    font-size: 16pt;
    selection-background-color: {ACCENT_STRONG};
}}
#Query:focus {{ border: 2px solid {ACCENT_2}; }}
#Logo {{ color: {ACCENT}; font-size: 20pt; padding: 0 4px; }}
#Mic {{
    background: {SURFACE};
    color: {MUTED};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 8px;
    font-size: 14pt;
}}
#Results {{
    background: transparent;
    border: none;
    color: {TEXT};
    outline: none;
}}
#Hints {{ color: {MUTED}; font-size: 9pt; padding: 2px 6px; }}
#Answer {{
    background: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-left: 3px solid {ACCENT_2};
    border-radius: 10px;
    padding: 8px 12px;
    font-size: 11pt;
}}
#Mic:disabled {{ background: {SURFACE}; }}
#Mic:hover {{ border: 1px solid {ACCENT}; }}
#Mic:focus {{ border: 2px solid {ACCENT_2}; }}
#Mic[recording="true"] {{ background: #B4233A; border: 2px solid {DANGER}; }}
QToolTip {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; }}
"""


def socket_path() -> str:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/dai-{os.getuid()}"
    Path(runtime).mkdir(mode=0o700, parents=True, exist_ok=True)
    return str(Path(runtime) / f"{APP_ID}.sock")


_HEBREW = re.compile(r"[\u0590-\u05ff]")


def bidi_safe(text: str) -> str:
    """Keep Latin-only text (commands, results) left-to-right in RTL layouts."""
    if text and not _HEBREW.search(text):
        return f"\u202a{text}\u202c"  # LEFT-TO-RIGHT EMBEDDING ... POP DIRECTIONAL FORMATTING
    return text


class ResultDelegate(QStyledItemDelegate):
    """Two-line rows: icon, title and a muted subtitle."""

    ROW_HEIGHT = 52

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        return QSize(option.rect.width(), self.ROW_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        action: Action = index.data(ACTION_ROLE)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(4, 2, -4, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(ACCENT_STRONG))
            painter.drawRoundedRect(rect, 10, 10)

        rtl = option.direction == Qt.LayoutDirection.RightToLeft
        icon_size = 28
        icon_x = rect.right() - 12 - icon_size if rtl else rect.left() + 12
        icon_rect = QRect(icon_x, rect.center().y() - icon_size // 2, icon_size, icon_size)
        icon = QIcon.fromTheme(action.icon) if action.icon and not action.icon.startswith("/") else QIcon(action.icon)
        if icon.isNull():
            icon = QIcon.fromTheme("application-x-executable")
        icon.paint(painter, icon_rect)

        text_left = rect.left() + 12 if rtl else icon_rect.right() + 12
        text_right = icon_rect.left() - 12 if rtl else rect.right() - 12
        # AlignAbsolute: Qt would otherwise mirror Left/Right again in RTL.
        align = (Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignAbsolute

        title_font = QFont(option.font)
        title_font.setPointSizeF(option.font.pointSizeF() * 1.15)
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.setPen(QColor("#FFFFFF" if selected else TEXT))
        title_rect = QRect(text_left, rect.top() + 6, text_right - text_left, rect.height() // 2)
        painter.drawText(title_rect, align | Qt.AlignmentFlag.AlignVCenter, bidi_safe(action.title))

        painter.setFont(option.font)
        painter.setPen(QColor("#E6E0FF" if selected else MUTED))
        sub_rect = QRect(text_left, rect.center().y(), text_right - text_left, rect.height() // 2 - 6)
        painter.drawText(sub_rect, align | Qt.AlignmentFlag.AlignVCenter, bidi_safe(action.subtitle))
        painter.restore()


class AskWorker(QObject):
    """Streams an answer from the local AI service (daid) off the UI thread."""

    delta = pyqtSignal(str)
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, question: str) -> None:
        super().__init__()
        self.question = question

    def run(self) -> None:
        try:
            from dai_ai.client import AIUnavailable, ask  # installed in /usr/lib/dai
        except ImportError:
            self.failed.emit(tr("ai_missing"))
            self.finished.emit()
            return
        try:
            for piece in ask(self.question):
                self.delta.emit(piece)
        except AIUnavailable as exc:
            self.failed.emit(f"{tr('ai_missing')}\n{exc}")
        self.finished.emit()


class CommandWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("D.Ai Command")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(with_touch(STYLE))
        self.setFixedWidth(fit_width(720))

        self.history = History(History.default_path())
        self.apps = load_apps()

        self.card = card = QFrame(self, objectName="Card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 10)
        layout.setSpacing(8)

        row = QHBoxLayout()
        logo = QLabel("◆", objectName="Logo")
        pixmap = QIcon(str(LOGO)).pixmap(QSize(34, 34)) if LOGO.is_file() else None
        if pixmap is not None and not pixmap.isNull():  # the faceted D.Ai diamond; the glyph is the fallback
            logo.setPixmap(pixmap)
        logo.setAccessibleName("D.Ai")
        self.query = QLineEdit(objectName="Query")
        self.query.setPlaceholderText(tr("placeholder"))
        self.query.setAccessibleName(tr("query_name"))
        self.query.setClearButtonEnabled(True)
        try:  # D.Ai Voice: push-to-talk, transcribed locally (installed next to dai_command)
            from dai_voice.qt import VoiceButton

            mic = VoiceButton(self)
            mic.transcribed.connect(self._voice_text)
            mic.failed.connect(self._voice_failed)
            mic.state_changed.connect(self._voice_state)
        except ImportError:
            mic = QToolButton(objectName="Mic")
            mic.setIcon(QIcon.fromTheme("audio-input-microphone"))
            mic.setIconSize(QSize(22, 22))
            mic.setEnabled(False)
            mic.setToolTip(tr("mic"))
            mic.setAccessibleName(tr("mic"))
        row.addWidget(logo)
        row.addWidget(self.query, 1)
        row.addWidget(mic)
        layout.addLayout(row)

        self.results = QListWidget(objectName="Results")
        self.results.setItemDelegate(ResultDelegate(self.results))
        self.results.setAccessibleName(tr("results_name"))
        self.results.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.results.itemActivated.connect(lambda _item: self.activate_current())
        self.results.itemClicked.connect(lambda _item: self.activate_current())
        layout.addWidget(self.results)

        self.answer = QTextBrowser(objectName="Answer")
        self.answer.setAccessibleName("D.Ai")
        self.answer.setOpenLinks(False)
        self.answer.setMinimumHeight(140)
        self.answer.setVisible(False)
        layout.addWidget(self.answer)
        self._thread: QThread | None = None

        footer = QHBoxLayout()
        hints = QLabel(tr("hints"), objectName="Hints")
        hints.setWordWrap(True)  # a narrow window wraps the hints (docs/MOBILE.md A2)
        footer.addWidget(hints, 1)
        credit = QLabel(f"D.Ai Command {__version__} · {__author__}", objectName="Hints")
        credit.setWordWrap(True)
        footer.addWidget(credit)
        layout.addLayout(footer)

        self.query.textChanged.connect(self.refresh)
        self.query.installEventFilter(self)
        self.refresh("")

    # -- results -----------------------------------------------------------

    def refresh(self, text: str) -> None:
        self.results.clear()
        if not text.startswith("?"):
            self.answer.setVisible(False)
        for action in build_actions(text, self.apps, self.history.load())[:MAX_ROWS]:
            item = QListWidgetItem(action.title)
            item.setData(ACTION_ROLE, action)
            item.setToolTip(action.subtitle)
            self.results.addItem(item)
        if self.results.count():
            self.results.setCurrentRow(0)
        rows = self.results.count()
        self.results.setFixedHeight(rows * ResultDelegate.ROW_HEIGHT + (4 if rows else 0))
        self.results.setVisible(rows > 0)
        # Resize after Qt has processed the layout change, or we lag one step.
        QTimer.singleShot(0, self._fit_to_content)

    def _fit_to_content(self) -> None:
        for layout in (self.card.layout(), self.layout()):
            layout.invalidate()
            layout.activate()
        self.resize(self.width(), self.layout().sizeHint().height())

    def move_selection(self, delta: int) -> None:
        count = self.results.count()
        if count:
            self.results.setCurrentRow((self.results.currentRow() + delta) % count)

    # -- activation --------------------------------------------------------

    def activate_current(self) -> None:
        item = self.results.currentItem()
        # Like bash HISTCONTROL=ignorespace: a leading space keeps it private.
        private = self.query.text().startswith(" ")
        if item is None:
            return
        action: Action = item.data(ACTION_ROLE)
        if action.kind == "history":
            self.query.setText(str(action.payload))
            return
        if action.kind == "app":
            app = action.payload
            argv = list(app.exec_args)
            if app.terminal:
                argv = ["x-terminal-emulator", "-e", *argv]
            self._spawn(argv)
            remembered = app.name
        elif action.kind in ("calc", "layout", "fact"):
            QGuiApplication.clipboard().setText(str(action.payload))
            remembered = ""
        elif action.kind == "run":
            self._spawn(["sh", "-c", str(action.payload)])
            remembered = f"${action.payload}"
        elif action.kind == "terminal":
            command = f"{action.payload}; echo; read -r -p 'Enter ↵' _"
            self._spawn(["x-terminal-emulator", "-e", "bash", "-c", command])
            remembered = f">{action.payload}"
        elif action.kind == "tune":
            # Review, confirmation and authorization happen in dai-tune.
            request = str(action.payload)
            command = ["dai-tune", request] if request else ["dai-tune", "help"]
            self._spawn(["x-terminal-emulator", "-e", "bash", "-c", 'dai-tune "$@"; echo; read -r -p "Enter ↵" _', "dai-tune", *command[1:]])
            remembered = f"!{request}" if request else ""
        elif action.kind == "forge":
            # Review, permissions and authorization happen in the D.Ai Forge window.
            request = str(action.payload)
            self._spawn(["dai-forge-gui", *([request] if request else [])])
            remembered = f"+{request}" if request else ""
        elif action.kind == "file":
            if not action.payload:  # a hint row: keep the bar open
                return
            self._spawn(["xdg-open", str(action.payload)])
            remembered = self.query.text().strip()
        elif action.kind == "doctor":
            # Fixes are offered and confirmed there; system ones go through D.Ai Tune.
            self._spawn(["x-terminal-emulator", "-e", "bash", "-c",
                         'dai-doctor "$1"; echo; read -r -p "Enter ↵" _', "dai-doctor", str(action.payload)])
            remembered = self.query.text().strip()
        elif action.kind == "move":
            self._spawn(["x-terminal-emulator", "-e", "bash", "-c", 'dai-move; echo; read -r -p "Enter ↵" _'])
            remembered = self.query.text().strip()
        elif action.kind == "backup":
            self._spawn(["x-terminal-emulator", "-e", "bash", "-c",
                         'dai-backup "$1"; echo; read -r -p "Enter ↵" _', "dai-backup", str(action.payload)])
            remembered = self.query.text().strip()
        elif action.kind == "heal":
            self._spawn(["dai-heal"])
            remembered = self.query.text().strip()
        elif action.kind == "clip":
            self._spawn(["dai-clip"])
            remembered = self.query.text().strip()
        elif action.kind == "store":
            self._spawn(["dai-store"])
            remembered = self.query.text().strip()
        elif action.kind == "settings":
            self._spawn(["dai-settings"])
            remembered = self.query.text().strip()
        elif action.kind == "captions":
            self._spawn(["dai-captions"])
            remembered = self.query.text().strip()
        elif action.kind == "explain":
            # A moment for this window to close, so the screen Diamond reads is the person's, not ours.
            self._spawn(["sh", "-c", "sleep 0.4; exec dai-explain"])
            remembered = self.query.text().strip()
        elif action.kind == "speak":
            answer = "" if self.answer.isHidden() else self.answer.toPlainText().strip()
            if action.payload == "stop":
                self._spawn(["dai-speak", "--stop"])
            elif answer:
                # Diamond's answer, through dai-speak's standard input (never on a command line).
                self._spawn_with_input(["dai-speak", "--stdin"], answer)
            else:
                # A moment for this window to close, so the selection Diamond reads is the person's, not ours.
                self._spawn(["sh", "-c", "sleep 0.3; exec dai-speak"])
            remembered = self.query.text().strip()
        elif action.kind == "focus":
            argv = {"stop": ["dai-focus", "stop"], "game": ["dai-focus", "game"], "game-stop": ["dai-focus", "game", "stop"]}
            self._spawn(argv.get(str(action.payload), ["dai-focus", "start", str(action.payload)]))
            remembered = self.query.text().strip()
        elif action.kind == "ocr":
            # A moment for this window to close, so the area chooser covers the screen and not us.
            self._spawn(["sh", "-c", "sleep 0.4; exec dai-ocr"])
            remembered = self.query.text().strip()
        elif action.kind == "chat":
            # In this process: the message never goes on another program's command line (visible in `ps`).
            try:
                from dai_chat.quick import send_text

                public, words = action.payload
                send_text(public, words)
            except (ImportError, OSError, ValueError):
                return
            remembered = ""  # a sent message is not kept in the bar's history
        elif action.kind == "privacy":
            self._spawn(["x-terminal-emulator", "-e", "bash", "-c", 'dai-privacy log; echo; read -r -p "Enter ↵" _'])
            remembered = self.query.text().strip()
        elif action.kind == "evolve":
            # The suggestion opens Forge, Tune or Heal, where it is reviewed before anything changes.
            try:
                from dai_evolve.cli import open_suggestion

                open_suggestion(action.payload, spawn=self._spawn)
            except ImportError:
                return
            remembered = ""
        elif action.kind == "ai":
            self.ask_ai(str(action.payload))
            return
        else:
            return
        if remembered and not private:
            self.history.add(remembered)
            if remembered.startswith((">", "$")):
                self._count(remembered)
        self.hide()

    @staticmethod
    def _count(entry: str) -> None:
        try:
            from dai_evolve.store import count_command
        except ImportError:
            return
        count_command(entry)

    def dismiss_current(self) -> bool:
        item = self.results.currentItem()
        action = item.data(ACTION_ROLE) if item is not None else None
        if action is None or action.kind != "evolve":
            return False
        try:
            from dai_evolve.scan import dismiss
        except ImportError:
            return False
        dismiss(action.payload.key)
        self.results.takeItem(self.results.row(item))
        return True

    def _voice_text(self, text: str) -> None:
        self.query.setText(text)
        self.query.setFocus()
        self.query.end(False)

    def _voice_failed(self, message: str) -> None:
        self.query.clear()
        self.query.setPlaceholderText("🎙 " + message)
        QTimer.singleShot(5000, lambda: self.query.setPlaceholderText(tr("placeholder")))

    def _voice_state(self, state: str) -> None:
        if state == "recording":
            self.query.setPlaceholderText(tr("listening"))
        elif state == "working":
            self.query.setPlaceholderText(tr("transcribing"))
        else:
            self.query.setPlaceholderText(tr("placeholder"))

    def ask_ai(self, question: str) -> None:
        if not question or (self._thread and self._thread.isRunning()):
            return
        self.answer.clear()
        self.answer.setVisible(True)
        self.answer.setPlaceholderText(tr("ai_thinking"))
        self._thread = QThread(self)
        self._worker = AskWorker(question)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.delta.connect(self._append_answer)
        self._worker.failed.connect(lambda text: (self.answer.setPlainText(text), self._orient_answer()))
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()
        QTimer.singleShot(0, self._fit_to_content)

    def _append_answer(self, text: str) -> None:
        self.answer.moveCursor(self.answer.textCursor().MoveOperation.End)
        self.answer.insertPlainText(text)
        self._orient_answer()

    def _orient_answer(self) -> None:
        """Right-to-left when most letters are Hebrew, even if it starts with "TCP"."""
        text = self.answer.toPlainText()
        rtl = len(_HEBREW.findall(text)) > len(re.findall(r"[A-Za-z]", text))
        option = QTextOption(Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft)
        option.setTextDirection(Qt.LayoutDirection.RightToLeft if rtl else Qt.LayoutDirection.LeftToRight)
        option.setWrapMode(QTextOption.WrapMode.WordWrap)
        self.answer.document().setDefaultTextOption(option)

    @staticmethod
    def _spawn(argv: list[str]) -> None:
        try:
            subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                cwd=str(Path.home()),
            )
        except OSError as exc:
            print(f"dai-command: cannot start {argv[0]}: {exc}", file=sys.stderr)

    @staticmethod
    def _spawn_with_input(argv: list[str], text: str) -> None:
        try:
            child = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True, cwd=str(Path.home()))
        except OSError as exc:
            print(f"dai-command: cannot start {argv[0]}: {exc}", file=sys.stderr)
            return
        try:
            assert child.stdin is not None
            child.stdin.write(text.encode("utf-8"))
            child.stdin.close()
        except OSError:
            pass

    # -- window behaviour --------------------------------------------------

    def show_query(self, text: str) -> None:
        """Open with text typed elsewhere (the panel field) and keep typing here."""
        if not self.isVisible():
            self.apps = load_apps()
            self.show()
        self.raise_()
        self.activateWindow()
        self.query.setText(text)
        self.query.setFocus()
        self.query.end(False)

    def toggle(self) -> None:
        if self.isVisible():
            self.hide()
            return
        self.apps = load_apps()  # pick up newly installed apps
        self.query.clear()
        self.refresh("")
        self.show()
        self.raise_()
        self.activateWindow()
        self.query.setFocus()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.query and isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self.hide()
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.activate_current()
                return True
            if key == Qt.Key.Key_Delete and not self.query.text() and self.dismiss_current():
                return True
            if key == Qt.Key.Key_Down:
                self.move_selection(1)
                return True
            if key == Qt.Key.Key_Up:
                self.move_selection(-1)
                return True
        return super().eventFilter(obj, event)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        # Close like a popup when the user clicks elsewhere.
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow() and self.isVisible():
            QTimer.singleShot(150, lambda: None if self.isActiveWindow() else self.hide())
        super().changeEvent(event)


def _send_to_running(command: bytes) -> bool:
    sock = QLocalSocket()
    sock.connectToServer(socket_path())
    if not sock.waitForConnected(300):
        return False
    sock.write(command)
    sock.flush()
    sock.waitForBytesWritten(300)
    sock.disconnectFromServer()
    return True


def main(argv: list[str]) -> int:
    if "--version" in argv:
        print(f"dai-command {__version__} — {__author__}")
        return 0

    QGuiApplication.setDesktopFileName(APP_ID)  # Wayland app_id for labwc window rules
    app = QApplication(argv)
    app.setApplicationName("D.Ai Command")
    app.setApplicationVersion(__version__)
    app.setOrganizationName(__author__)

    initial = None
    if "--query" in argv and argv.index("--query") + 1 < len(argv):
        initial = argv[argv.index("--query") + 1]
    message = b"quit" if "--quit" in argv else (b"query:" + initial.encode("utf-8") if initial is not None else b"toggle")
    if _send_to_running(message):
        return 0
    if "--quit" in argv:
        return 0

    window = CommandWindow()
    server = QLocalServer()
    QLocalServer.removeServer(socket_path())  # stale socket from a crash
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    if not server.listen(socket_path()):
        print(f"dai-command: cannot listen on {socket_path()}: {server.errorString()}", file=sys.stderr)

    def on_connection() -> None:
        conn = server.nextPendingConnection()
        if conn is None:
            return

        def on_ready() -> None:
            data = bytes(conn.readAll())[:4096]
            if data == b"quit":
                app.quit()
            elif data.startswith(b"query:"):
                window.show_query(data[6:].decode("utf-8", "replace"))
            else:
                window.toggle()

        conn.readyRead.connect(on_ready)
        conn.disconnected.connect(conn.deleteLater)

    server.newConnection.connect(on_connection)

    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(MUTED))
    app.setPalette(palette)

    if initial is not None:
        window.show_query(initial)
    elif "--background" not in argv:
        window.toggle()
    return app.exec()
