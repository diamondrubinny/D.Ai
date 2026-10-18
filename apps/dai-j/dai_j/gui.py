# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The J window (docs/MAIL.md §2, §6): folders, messages and the open message, side by side.

Everything works from the keyboard (the Gmail keys on the message list: c, r,
a, f, #, j, k, u), every row says all of itself to a screen reader, Hebrew
mirrors the window, and every paragraph finds its own direction. Network
work runs in the background; the window never waits for a server.
"""

from __future__ import annotations

import time
import urllib.parse
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QDesktopServices, QFont, QFontDatabase, QKeySequence, QShortcut, QTextBlockFormat, QTextCursor
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFormLayout, QGroupBox,
                             QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton,
                             QSpinBox, QSplitter, QStackedWidget, QTextBrowser, QTextEdit, QToolBar, QTreeWidget,
                             QTreeWidgetItem, QVBoxLayout, QWidget)

from dai_i18n import embed, qt_direction, ui_lang

from . import __author__, __version__, accounts as acc, compose, discover, engine, localmail, mail, sanitize
from .text import error, t

ROLE = Qt.ItemDataRole.UserRole
LRI, PDI = "\u2066", "\u2069"   # isolates: addresses keep their order inside Hebrew text
SYNC_EVERY = 3 * 60 * 1000

STYLE = """
QMainWindow, QDialog, QWidget#Page { background: #0B1020; }
QWidget { color: #E6E9F5; font-size: 10.5pt; }
QToolBar { background: #0B1020; border: 0; spacing: 6px; padding: 6px; }
QToolButton { background: #1C2547; border: 1px solid #2A3563; border-radius: 10px; padding: 5px 12px; }
QToolButton:hover { border: 1px solid #7C5CFF; }
QToolButton:focus, QPushButton:focus, QLineEdit:focus, QTextEdit:focus, QTreeWidget:focus, QListWidget:focus, QTextBrowser:focus,
QComboBox:focus, QSpinBox:focus, QCheckBox:focus { border: 2px solid #22D3EE; }
QTreeWidget, QListWidget, QTextBrowser, QTextEdit, QLineEdit, QComboBox, QSpinBox { background: #141B33; border: 1px solid #2A3563;
    border-radius: 10px; padding: 4px; selection-background-color: #5B3FD6; }
QTreeWidget::item { padding: 5px 2px; }
QTreeWidget::item:selected { background: #5B3FD6; color: #FFFFFF; }
QHeaderView::section { background: #141B33; color: #B8A6FF; border: 0; padding: 6px; font-weight: 600; }
QPushButton { background: #1C2547; border: 1px solid #2A3563; border-radius: 10px; padding: 6px 16px; }
QPushButton#Primary { background: #5B3FD6; border: 1px solid #7C5CFF; color: #FFFFFF; font-weight: 600; }
QPushButton:hover { border: 1px solid #7C5CFF; }
QLabel#Muted { color: #AEB6D9; }
QLabel#Notice { color: #FFD580; }
QLabel#Error { color: #FFB4B4; }
QLabel#Big { font-size: 16pt; font-weight: 700; }
QGroupBox { border: 1px solid #2A3563; border-radius: 10px; margin-top: 14px; padding: 10px; }
QGroupBox::title { subcontrol-origin: margin; padding: 0 6px; color: #B8A6FF; }
QSplitter::handle { background: #141B33; }
"""


# Background work

class _Signals(QObject):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)


class Task(QRunnable):
    def __init__(self, work: Callable[[], object]) -> None:
        super().__init__()
        self.work = work
        self.signals = _Signals()

    def run(self) -> None:
        try:
            result = self.work()
        except mail.MailError as exc:
            self.signals.failed.emit(str(exc))
        except ValueError as exc:
            self.signals.failed.emit(f"value:{exc}")
        except Exception as exc:  # noqa: BLE001 - shown to the user as "something went wrong"
            self.signals.failed.emit(type(exc).__name__)
        else:
            self.signals.done.emit(result)


class Runner:
    """Runs tasks in the background (or at once, for tests) and keeps them alive until they finish."""

    def __init__(self, inline: bool = False) -> None:
        self.inline = inline
        self.pool = QThreadPool.globalInstance()
        self.active: set[Task] = set()

    def start(self, work: Callable[[], object], done: Callable[[object], None], failed: Callable[[str], None]) -> None:
        task = Task(work)
        task.setAutoDelete(False)
        task.signals.done.connect(done)
        task.signals.failed.connect(failed)
        task.signals.done.connect(lambda _=None: self.active.discard(task))
        task.signals.failed.connect(lambda _=None: self.active.discard(task))
        self.active.add(task)
        if self.inline:
            task.run()
        else:
            self.pool.start(task)


def when(stamp: float, lang: str) -> str:
    if not stamp:
        return ""
    local = time.localtime(stamp)
    today = time.localtime()
    if local[:3] == today[:3]:
        return time.strftime("%H:%M", local)
    if local.tm_year == today.tm_year:
        return time.strftime("%d.%m %H:%M", local)
    return time.strftime("%d.%m.%Y", local)


# Account setup

class SetupDialog(QDialog):
    def __init__(self, lang: str, keyring: acc.Keyring, runner: Runner, finder=discover.discover,
                 checker=mail.check, parent=None) -> None:
        super().__init__(parent)
        self.lang = lang
        self.keyring = keyring
        self.runner = runner
        self.finder = finder
        self.checker = checker
        self.settings: discover.Settings | None = None
        self.account: acc.Account | None = None
        self.password = ""
        self.setWindowTitle(t("setup_title", lang))
        self.setLayoutDirection(qt_direction(lang))
        self.setStyleSheet(STYLE)
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        title = QLabel(t("setup_title", lang), objectName="Big")
        layout.addWidget(title)
        form = QFormLayout()
        self.name = QLineEdit()
        self.address = QLineEdit()
        self.address.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.address.setInputMethodHints(Qt.InputMethodHint.ImhEmailCharactersOnly)
        self.secret = QLineEdit(echoMode=QLineEdit.EchoMode.Password)
        self.secret.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        for label, field in ((t("your_name", lang), self.name), (t("address", lang), self.address),
                             (t("password", lang), self.secret)):
            field.setAccessibleName(label)
            form.addRow(label, field)
        layout.addLayout(form)
        self.remember = QCheckBox(t("remember", lang))
        self.remember.setChecked(keyring.available())
        self.remember.setEnabled(keyring.available())
        layout.addWidget(self.remember)
        if not keyring.available():
            layout.addWidget(QLabel(t("no_keyring", lang), objectName="Muted", wordWrap=True))

        self.status = QLabel(objectName="Muted", wordWrap=True)
        self.status.setAccessibleName(t("setup_title", lang))
        layout.addWidget(self.status)
        self.note = QLabel(objectName="Notice", wordWrap=True)
        self.note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.note.hide()
        layout.addWidget(self.note)

        self.advanced = QGroupBox(t("advanced", lang))
        self.advanced.setCheckable(True)
        self.advanced.setChecked(False)
        grid = QFormLayout(self.advanced)
        self.fields: dict[str, dict[str, QWidget]] = {}
        for kind in ("incoming", "outgoing"):
            host, port, security, user = QLineEdit(), QSpinBox(), QComboBox(), QLineEdit()
            port.setRange(1, 65535)
            security.addItem("SSL/TLS", "ssl")
            security.addItem("STARTTLS", "starttls")
            for widget in (host, user):
                widget.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
            grid.addRow(QLabel(t(kind, lang), objectName="Muted"))
            for label, widget in ((t("server", lang), host), (t("port", lang), port), (t("security", lang), security),
                                  (t("username", lang), user)):
                widget.setAccessibleName(f"{t(kind, lang)}: {label}")
                grid.addRow(label, widget)
            self.fields[kind] = {"host": host, "port": port, "security": security, "user": user}
        self.advanced.toggled.connect(self._show_advanced)
        self._show_advanced(False)
        layout.addWidget(self.advanced)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(embed(t("cancel", lang), lang))
        cancel.clicked.connect(self.reject)
        self.find_button = QPushButton(embed(t("find", lang), lang))
        self.find_button.clicked.connect(self.find)
        self.sign_in_button = QPushButton(embed(t("sign_in", lang), lang), objectName="Primary")
        self.sign_in_button.clicked.connect(self.sign_in)
        self.sign_in_button.setDefault(True)
        for button in (cancel, self.find_button, self.sign_in_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.address.editingFinished.connect(self._address_done)

    def _show_advanced(self, shown: bool) -> None:
        for row in self.fields.values():
            for widget in row.values():
                widget.setVisible(shown)
        for label in self.advanced.findChildren(QLabel):
            label.setVisible(shown)

    def _say(self, text: str, error_text: bool = False) -> None:
        self.status.setObjectName("Error" if error_text else "Muted")
        self.status.setStyleSheet("")  # re-apply the style for the new name
        self.status.setText(text)
        self.status.setAccessibleDescription(text)

    def _address_done(self) -> None:
        if self.settings is None and discover.valid_address(self.address.text()):
            self.find()

    def find(self) -> None:
        address = self.address.text().strip()
        if not discover.valid_address(address):
            self._say(t("bad_address", self.lang), True)
            self.address.setFocus()
            return
        self._say(t("finding", self.lang, domain=address.split("@", 1)[1]))
        self.find_button.setEnabled(False)
        self.runner.start(lambda: self.finder(address), self._found, self._failed)

    def _found(self, settings) -> None:
        self.find_button.setEnabled(True)
        if settings is None:
            self._say(t("bad_address", self.lang), True)
            return
        self.settings = settings
        for kind, server in (("incoming", settings.incoming), ("outgoing", settings.outgoing)):
            row = self.fields[kind]
            row["host"].setText(server.host)
            row["port"].setValue(server.port)
            row["security"].setCurrentIndex(0 if server.security == "ssl" else 1)
            row["user"].setText(server.username)
        key = "found_guess" if settings.source == "guess" else "found"
        self._say(t(key, self.lang, host=settings.incoming.host))
        notes = [t(f"note_{n}", self.lang) for n in settings.notes if n in ("oauth", "app_password")]
        self.note.setText("\n".join(notes))
        self.note.setVisible(bool(notes))
        if settings.source == "guess":
            self.advanced.setChecked(True)

    def _servers(self) -> tuple[discover.Server, discover.Server]:
        def server(kind: str) -> discover.Server:
            row = self.fields[kind]
            oauth = bool(self.settings and getattr(self.settings, kind).oauth_only)
            return discover.Server(row["host"].text().strip().lower(), row["port"].value(),
                                   row["security"].currentData(), row["user"].text().strip() or self.address.text().strip(),
                                   oauth)

        return server("incoming"), server("outgoing")

    def sign_in(self) -> None:
        address = self.address.text().strip()
        if not discover.valid_address(address):
            self._say(t("bad_address", self.lang), True)
            return
        if self.settings is None or self.settings.address != address:
            self.settings = None
            self.find()
            return
        incoming, outgoing = self._servers()
        if not discover.HOSTNAME.match(incoming.host) or not discover.HOSTNAME.match(outgoing.host):
            self.advanced.setChecked(True)
            self._say(t("e_unreachable", self.lang), True)
            return
        account = acc.Account(address=address, name=self.name.text().strip(), incoming=incoming, outgoing=outgoing)
        password = self.secret.text()
        self._say(t("signing_in", self.lang))
        self.sign_in_button.setEnabled(False)

        def done(folders) -> None:
            account.folders = {f.role: f.name for f in folders if f.role and f.role != "inbox"}
            self.account, self.password = account, password
            if self.remember.isChecked():
                self.keyring.store(account.id, password)
            else:
                self.keyring.memory[account.id] = password
            self.accept()

        def failed(key: str) -> None:
            self.sign_in_button.setEnabled(True)
            self._say(error(key, self.lang), True)

        self.runner.start(lambda: self.checker(account, password), done, failed)

    def _failed(self, key: str) -> None:
        self.find_button.setEnabled(True)
        self._say(error(key, self.lang), True)


# Writing

UNDO_SECONDS = 10


class ComposeWindow(QWidget):
    def __init__(self, lang: str, accounts: list[acc.Account], password_for: Callable[[acc.Account], str | None],
                 runner: Runner, draft: compose.Draft | None = None, sender=engine.send, on_sent=None,
                 undo_seconds: int = UNDO_SECONDS) -> None:
        super().__init__()
        self.lang = lang
        self.undo_seconds = undo_seconds
        self.pending = QTimer(self, singleShot=True)  # "undo send": the message leaves when this fires
        self.countdown = QTimer(self, interval=1000)
        self.left = 0
        self.waiting = None  # what the timer sends: one at a time, connected once (never sent twice)
        self.pending.timeout.connect(self._fire)
        self.accounts = accounts
        self.password_for = password_for
        self.runner = runner
        self.sender = sender
        self.on_sent = on_sent
        self.sent = False
        self.setWindowTitle(t("compose_title", lang))
        self.setLayoutDirection(qt_direction(lang))
        self.setStyleSheet(STYLE)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setObjectName("Page")
        self.resize(720, 560)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.account_box = QComboBox()
        for account in accounts:
            self.account_box.addItem(account.address, account.id)
        self.to, self.cc, self.subject = QLineEdit(), QLineEdit(), QLineEdit()
        for label, field in ((t("from", lang), self.account_box), (t("to", lang), self.to), (t("cc", lang), self.cc),
                             (t("subject", lang), self.subject)):
            field.setAccessibleName(label)
            form.addRow(label, field)
        for field in (self.to, self.cc):
            field.setLayoutDirection(Qt.LayoutDirection.LeftToRight)  # addresses read left to right
        layout.addLayout(form)

        tools = QHBoxLayout()
        self.rtl = QPushButton(embed("⇠ " + t("rtl", lang), lang))
        self.ltr = QPushButton(embed(t("ltr", lang) + " ⇢", lang))
        self.rtl.setToolTip(t("rtl", lang) + " · Ctrl+Shift+R")
        self.ltr.setToolTip(t("ltr", lang) + " · Ctrl+Shift+L")
        self.rtl.clicked.connect(lambda: self.set_direction(Qt.LayoutDirection.RightToLeft))
        self.ltr.clicked.connect(lambda: self.set_direction(Qt.LayoutDirection.LeftToRight))
        tools.addWidget(self.rtl)
        tools.addWidget(self.ltr)
        tools.addStretch(1)
        layout.addLayout(tools)

        self.body = QTextEdit()
        self.body.setAcceptRichText(False)
        self.body.setAccessibleName(t("body", lang))
        layout.addWidget(self.body, 1)

        bottom = QHBoxLayout()
        self.status = QLabel(objectName="Muted", wordWrap=True)
        bottom.addWidget(self.status, 1)
        self.send_button = QPushButton(embed(t("send", lang), lang), objectName="Primary")
        self.send_button.setToolTip("Ctrl+Enter")
        self.send_button.clicked.connect(self.send)
        self.undo_button = QPushButton(embed(t("undo_send", lang), lang))
        self.undo_button.setToolTip(t("undo_send", lang) + " · Esc")
        self.undo_button.clicked.connect(self.undo_send)
        self.undo_button.hide()
        bottom.addWidget(self.undo_button)
        bottom.addWidget(self.send_button)
        layout.addLayout(bottom)

        QShortcut(QKeySequence("Ctrl+Return"), self, self.send)
        QShortcut(QKeySequence("Ctrl+Enter"), self, self.send)
        QShortcut(QKeySequence("Ctrl+Shift+R"), self, lambda: self.set_direction(Qt.LayoutDirection.RightToLeft))
        QShortcut(QKeySequence("Ctrl+Shift+L"), self, lambda: self.set_direction(Qt.LayoutDirection.LeftToRight))
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, lambda: self.undo_send() if self.pending.isActive() else self.close())
        self.countdown.timeout.connect(self._tick)
        if draft is not None:
            self.load(draft)

    def load(self, draft: compose.Draft) -> None:
        index = self.account_box.findData(draft.sender_address.lower())
        if index >= 0:
            self.account_box.setCurrentIndex(index)
        self.to.setText(draft.to)
        self.cc.setText(draft.cc)
        self.subject.setText(draft.subject)
        self.in_reply_to, self.references = draft.in_reply_to, draft.references
        cursor = QTextCursor(self.body.document())
        for index, (line, direction) in enumerate(draft.paragraphs):
            if index:
                cursor.insertBlock()
            fmt = QTextBlockFormat()
            fmt.setLayoutDirection({"rtl": Qt.LayoutDirection.RightToLeft,
                                    "ltr": Qt.LayoutDirection.LeftToRight}.get(direction, Qt.LayoutDirection.LayoutDirectionAuto))
            cursor.setBlockFormat(fmt)
            cursor.insertText(line)
        self.body.moveCursor(QTextCursor.MoveOperation.Start)

    def set_direction(self, direction: Qt.LayoutDirection) -> None:
        cursor = self.body.textCursor()
        fmt = QTextBlockFormat()
        fmt.setLayoutDirection(direction)
        fmt.setAlignment(Qt.AlignmentFlag.AlignLeading)  # the start of the line in its own direction
        cursor.mergeBlockFormat(fmt)
        self.body.setTextCursor(cursor)

    def paragraphs(self) -> list[tuple[str, str]]:
        result = []
        block = self.body.document().begin()
        while block.isValid():
            direction = block.blockFormat().layoutDirection()
            name = {Qt.LayoutDirection.RightToLeft: "rtl", Qt.LayoutDirection.LeftToRight: "ltr"}.get(direction, "auto")
            result.append((block.text(), name))
            block = block.next()
        return result

    def draft(self) -> compose.Draft:
        return compose.Draft(sender_name="", sender_address="", to=self.to.text(), cc=self.cc.text(),
                             subject=self.subject.text(), paragraphs=self.paragraphs(),
                             in_reply_to=getattr(self, "in_reply_to", ""), references=getattr(self, "references", ""))

    def account(self) -> acc.Account | None:
        wanted = self.account_box.currentData()
        return next((a for a in self.accounts if a.id == wanted), None)

    def send(self) -> None:
        if not self.send_button.isEnabled():
            return  # already sending: never twice
        account = self.account()
        draft = self.draft()
        good, bad = compose.recipients(draft.to)
        bad += compose.recipients(draft.cc)[1]
        if bad:
            self._say(t("bad_recipients", self.lang, bad=", ".join(bad)), True)
            self.to.setFocus()
            return
        if not good:
            self._say(t("no_recipients", self.lang), True)
            self.to.setFocus()
            return
        password = self.password_for(account) if account else None
        if account is None or password is None:
            return
        self.send_button.setEnabled(False)
        if self.undo_seconds > 0:  # a few seconds to take it back; nothing has left the computer yet
            self.left = self.undo_seconds
            self.waiting = (account, password, draft)
            self.pending.start(self.undo_seconds * 1000)
            self.countdown.start()
            self.undo_button.show()
            self.undo_button.setFocus()
            self._tick(first=True)
            return
        self._deliver(account, password, draft)

    def _tick(self, first: bool = False) -> None:
        if not first:
            self.left -= 1
        self._say(t("sending_in", self.lang, seconds=max(self.left, 0)))

    def undo_send(self) -> None:
        if not self.pending.isActive():
            return
        self.pending.stop()
        self.countdown.stop()
        self.waiting = None
        self.undo_button.hide()
        self.send_button.setEnabled(True)
        self.send_button.setFocus()
        self._say(t("send_undone", self.lang))

    def _fire(self) -> None:
        waiting, self.waiting = self.waiting, None
        if waiting is not None:
            self._deliver(*waiting)

    def _deliver(self, account, password, draft) -> None:
        self.countdown.stop()
        self.undo_button.hide()
        self._say(t("sending", self.lang))

        def done(_result) -> None:
            self.sent = True
            self._say(t("sent_ok", self.lang))
            if self.on_sent:
                self.on_sent(account)
            QTimer.singleShot(600, self.close)

        def failed(key: str) -> None:
            self.send_button.setEnabled(True)
            self._say(error("send" if key.startswith("value:") else key, self.lang), True)

        self.runner.start(lambda: self.sender(account, password, draft), done, failed)

    def _say(self, text: str, problem: bool = False) -> None:
        self.status.setObjectName("Error" if problem else "Muted")
        self.status.setStyleSheet("")
        self.status.setText(text)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.pending.isActive():  # closing while "undo send" counts down: it is sent now, as asked, and the
            self.pending.stop()      # window closes by itself once the message has left
            self._fire()
            event.ignore()
            return
        if not self.sent and self.body.toPlainText().strip() and self.isVisible():
            box = QMessageBox(QMessageBox.Icon.Question, t("compose_title", self.lang), t("discard", self.lang),
                              parent=self)
            yes = box.addButton(t("discard_yes", self.lang), QMessageBox.ButtonRole.DestructiveRole)
            keep = box.addButton(t("cancel", self.lang), QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(keep)
            box.exec()
            if box.clickedButton() is not yes:
                event.ignore()
                return
        super().closeEvent(event)


# Importing (docs/MAIL.md §3.1)

class ImportDialog(QDialog):
    """The accounts other mail apps on this computer have; the checked ones are added (settings only)."""

    def __init__(self, lang: str, found: list, parent=None) -> None:
        super().__init__(parent)
        from PyQt6.QtWidgets import QListWidget, QListWidgetItem

        self.lang = lang
        self.found = found
        self.setWindowTitle(t("import_title", lang))
        self.setLayoutDirection(qt_direction(lang))
        self.setStyleSheet(STYLE)
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(t("import_title", lang), objectName="Big"))
        layout.addWidget(QLabel(t("import_hint", lang) if found else t("import_none", lang), objectName="Muted",
                                wordWrap=True))
        self.list = QListWidget()
        self.list.setAccessibleName(t("import_title", lang))
        names = {"thunderbird": "Thunderbird", "betterbird": "Betterbird", "evolution": "Evolution",
                 "claws": "Claws Mail", "mutt": "Mutt"}
        for account in found:
            host = account.incoming.host if account.incoming else "?"
            text = t("import_row", lang, address=f"{LRI}{account.address}{PDI}", source=names.get(account.source,
                     account.source), host=f"{LRI}{host}{PDI}")
            reasons = [t(f"import_{n}", lang) for n in account.notes if n in ("oauth", "insecure")]
            item = QListWidgetItem(text + ("\n    " + "; ".join(reasons) if reasons else ""))
            if account.usable and "oauth" not in account.notes:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked)
            else:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.list.addItem(item)
        layout.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(embed(t("cancel", lang), lang))
        cancel.clicked.connect(self.reject)
        add = QPushButton(embed(t("import_add", lang), lang), objectName="Primary")
        add.clicked.connect(self.accept)
        add.setEnabled(any(a.usable and "oauth" not in a.notes for a in found))
        buttons.addWidget(cancel)
        buttons.addWidget(add)
        layout.addLayout(buttons)

    def chosen(self) -> list[acc.Account]:
        result = []
        for index, account in enumerate(self.found):
            item = self.list.item(index)
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable and item.checkState() == Qt.CheckState.Checked:
                result.append(acc.Account(account.address, account.name, account.incoming, account.outgoing))
        return result


# Reading

class Reader(QTextBrowser):
    """Shows mail without loading anything: images and other resources come back empty."""

    def loadResource(self, kind, url):  # noqa: N802 - Qt API
        return None


class MainWindow(QMainWindow):
    def __init__(self, lang: str | None = None, directory: Path | None = None, keyring: acc.Keyring | None = None,
                 runner: Runner | None = None, ask_password=None, sync_on_start: bool = True) -> None:
        super().__init__()
        self.lang = lang or ui_lang()
        self.directory = directory or acc.data_dir()
        self.db = self.directory / "mail.sqlite"
        self.keyring = keyring or acc.Keyring()
        self.runner = runner or Runner()
        self.ask_password = ask_password or self._ask_password
        self.accounts = acc.load(self.directory)
        self.windows: list[QWidget] = []
        self.current: dict | None = None
        self.current_text = ""
        self.syncing: set[str] = set()
        from .store import Store

        self.store = Store(self.db)
        self.setWindowTitle(t("title", self.lang))
        self.setLayoutDirection(qt_direction(self.lang))
        self.setStyleSheet(STYLE)
        self.resize(1100, 680)

        self._toolbar()
        self.stack = QStackedWidget()
        self.stack.addWidget(self._empty_page())
        self.stack.addWidget(self._mail_page())
        self.setCentralWidget(self.stack)
        self.refresh_views()
        self._wake_later()  # messages snoozed in an earlier session come back on time
        self.timer = QTimer(self, interval=SYNC_EVERY)
        self.timer.timeout.connect(self.sync_all)
        if sync_on_start:
            QTimer.singleShot(200, self.sync_all)
            self.timer.start()

    # Building

    def _toolbar(self) -> None:
        bar = QToolBar(t("title", self.lang))
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(bar)
        self.actions_by_key: dict[str, QAction] = {}
        for key, shortcut, handler in (("new", "Ctrl+N", lambda: self.new_message()), ("reply", "Ctrl+R", lambda: self.reply(False)),
                                       ("reply_all", "Ctrl+Shift+R", lambda: self.reply(True)),
                                       ("forward", "Ctrl+Shift+F", self.forward), ("delete", "Delete", self.delete),
                                       ("mark_unread", "Ctrl+U", self.mark_unread), ("refresh", "F5", self.sync_all),
                                       ("add_account", "", self.add_account), ("import", "", lambda: self.import_accounts()),
                                       ("snooze", "", lambda: self.snooze_menu()),
                                       ("import_mail", "", lambda: self.import_mail())):
            action = QAction(t(key, self.lang), self)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
                action.setToolTip(f"{t(key, self.lang)} · {shortcut}")
            action.triggered.connect(handler)
            bar.addAction(action)
            if not shortcut:  # no key of its own: Tab reaches it instead
                bar.widgetForAction(action).setFocusPolicy(Qt.FocusPolicy.TabFocus)
            self.actions_by_key[key] = action

    def _empty_page(self) -> QWidget:
        page = QWidget(objectName="Page")
        layout = QVBoxLayout(page)
        layout.addStretch(1)
        title = QLabel(t("empty_title", self.lang), objectName="Big", alignment=Qt.AlignmentFlag.AlignCenter)
        body = QLabel(t("empty_body", self.lang), objectName="Muted", alignment=Qt.AlignmentFlag.AlignCenter)
        button = QPushButton(embed(t("add_account", self.lang), self.lang), objectName="Primary")
        button.clicked.connect(self.add_account)
        self.empty_button = button
        importing = QPushButton(embed(t("import", self.lang), self.lang))
        importing.clicked.connect(lambda: self.import_accounts())
        layout.addWidget(title)
        layout.addWidget(body)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button)
        row.addWidget(importing)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(2)
        return page

    def _mail_page(self) -> QWidget:
        splitter = QSplitter()
        self.folders = QTreeWidget()
        self.folders.setHeaderHidden(True)
        self.folders.setAccessibleName(t("folders", self.lang))
        self.folders.currentItemChanged.connect(lambda *_: self.show_folder())
        self.list = QTreeWidget()
        self.list.setColumnCount(3)
        self.list.setHeaderLabels([t("col_from", self.lang), t("col_subject", self.lang), t("col_date", self.lang)])
        self.list.setRootIsDecorated(False)
        self.list.setUniformRowHeights(True)
        self.list.setAccessibleName(t("messages", self.lang))
        header = self.list.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, header.ResizeMode.Interactive)
        header.setSectionResizeMode(1, header.ResizeMode.Stretch)
        header.setSectionResizeMode(2, header.ResizeMode.ResizeToContents)
        self.list.setColumnWidth(0, 150)
        self.list.currentItemChanged.connect(lambda *_: self.open_current())
        for key, handler in (("C", self.new_message), ("R", lambda: self.reply(False)), ("A", lambda: self.reply(True)),
                             ("F", self.forward), ("#", self.delete), ("U", self.mark_unread),
                             ("J", lambda: self._step(1)), ("K", lambda: self._step(-1)), ("B", self.snooze_menu)):
            shortcut = QShortcut(QKeySequence(key), self.list, handler)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)

        right = QWidget(objectName="Page")
        column = QVBoxLayout(right)
        column.setContentsMargins(6, 0, 0, 0)
        self.header = QLabel(objectName="Muted", wordWrap=True)
        self.header.setTextFormat(Qt.TextFormat.PlainText)  # names and subjects are never markup
        self.header.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.notice = QLabel(objectName="Notice", wordWrap=True)
        self.notice.hide()
        self.reader = Reader()
        self.reader.setOpenLinks(False)
        self.reader.anchorClicked.connect(self._open_link)
        self.reader.setAccessibleName(t("reader", self.lang))
        column.addWidget(self.header)
        column.addWidget(self.notice)
        column.addWidget(self.reader, 1)
        middle = QWidget(objectName="Page")
        stack = QVBoxLayout(middle)
        stack.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit(placeholderText=t("search", self.lang))
        self.search.setAccessibleName(t("search", self.lang))
        self.search.setToolTip(t("search", self.lang) + " · Ctrl+F")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda *_: self.show_folder())
        self.search.returnPressed.connect(self.list.setFocus)
        QShortcut(QKeySequence.StandardKey.Find, self, self.search.setFocus)
        stack.addWidget(self.search)
        stack.addWidget(self.list, 1)
        splitter.addWidget(self.folders)
        splitter.addWidget(middle)
        splitter.addWidget(right)
        splitter.setSizes([220, 420, 460])
        self.statusBar().showMessage("")
        return splitter

    # Views

    def refresh_views(self) -> None:
        self.stack.setCurrentIndex(1 if self.accounts or self.store.folders(localmail.LOCAL) else 0)
        for key, action in self.actions_by_key.items():
            action.setEnabled(bool(self.accounts) or key in ("add_account", "import", "import_mail"))
        selected = self._folder_key()
        self.folders.clear()
        ids = [a.id for a in self.accounts]
        unread = self.store.unread(ids)
        top = QTreeWidgetItem([t("all_inboxes", self.lang) + (f" ({unread})" if unread else "")])
        top.setData(0, ROLE, ("role", "inbox", None))
        self.folders.addTopLevelItem(top)
        for account in self.accounts:
            item = QTreeWidgetItem([account.address])
            item.setData(0, ROLE, None)
            self.folders.addTopLevelItem(item)
            for name, role in self.store.folders(account.id):
                label = t(role, self.lang) if role in ("inbox", "sent", "drafts", "trash", "junk", "archive", "all") else name
                child = QTreeWidgetItem([label])
                child.setData(0, ROLE, ("folder", name, account.id))
                child.setToolTip(0, name)
                item.addChild(child)
            item.setExpanded(True)
        local = self.store.folders(localmail.LOCAL)
        if local:  # mail imported from other apps: kept on this computer, no server
            item = QTreeWidgetItem([t("local_folders", self.lang)])
            item.setData(0, ROLE, None)
            self.folders.addTopLevelItem(item)
            for name, _role in local:
                child = QTreeWidgetItem([name])
                child.setData(0, ROLE, ("folder", name, localmail.LOCAL))
                child.setToolTip(0, name)
                item.addChild(child)
            item.setExpanded(True)
        match = self._find_folder(selected) or top
        self.folders.setCurrentItem(match)
        self.show_folder()

    def _folder_key(self):
        item = self.folders.currentItem() if hasattr(self, "folders") else None
        return item.data(0, ROLE) if item is not None else None

    def _find_folder(self, key):
        if key is None:
            return None
        for i in range(self.folders.topLevelItemCount()):
            top = self.folders.topLevelItem(i)
            if top.data(0, ROLE) == key:
                return top
            for c in range(top.childCount()):
                if top.child(c).data(0, ROLE) == key:
                    return top.child(c)
        return None

    def show_folder(self) -> None:
        key = self._folder_key()
        keep = self.current and (self.current["account"], self.current["folder"], self.current["uid"])
        self.list.clear()
        if not key:
            return
        kind, name, account_id = key
        query = self.search.text().strip() if hasattr(self, "search") else ""
        if len(query) >= 2:  # every account and the local folders, newest first
            rows = self.store.search([a.id for a in self.accounts] + [localmail.LOCAL], query)
        else:
            rows = (self.store.listing([a.id for a in self.accounts], role=name) if kind == "role"
                    else self.store.listing([account_id], folder=name))
        for row in rows:
            item = QTreeWidgetItem([row["sender"] or row["sender_address"] or "",
                                    row["subject"] or t("no_subject", self.lang), when(row["date"], self.lang)])
            item.setData(0, ROLE, row)
            self._style_row(item, row)
            self.list.addTopLevelItem(item)
            if keep and (row["account"], row["folder"], row["uid"]) == keep:
                self.list.setCurrentItem(item)
        if not rows:
            self.reader.setPlainText(t("empty_folder", self.lang))

    def _style_row(self, item: QTreeWidgetItem, row: dict) -> None:
        font = item.font(0)
        font.setBold(not row["seen"])
        states = [] if row["seen"] else [t("unread", self.lang)]
        if row["flagged"]:
            states.append(t("flagged", self.lang))
        spoken = t("row", self.lang, sender=item.text(0), subject=item.text(1), date=item.text(2))
        if states:
            spoken += ", " + ", ".join(states)
        for column in range(3):
            item.setFont(column, font)
            item.setData(column, Qt.ItemDataRole.AccessibleTextRole, spoken)
        item.setToolTip(1, item.text(1))

    def _step(self, delta: int) -> None:
        index = self.list.indexOfTopLevelItem(self.list.currentItem()) if self.list.currentItem() else -1
        target = self.list.topLevelItem(max(0, min(self.list.topLevelItemCount() - 1, index + delta)))
        if target is not None:
            self.list.setCurrentItem(target)

    def _account(self, account_id: str) -> acc.Account | None:
        return next((a for a in self.accounts if a.id == account_id), None)

    def open_current(self) -> None:
        item = self.list.currentItem()
        if item is None:
            self.current = None
            self.header.clear()
            self.reader.setPlainText(t("pick_message", self.lang))
            return
        row = item.data(0, ROLE)
        self.current = row
        account = self._account(row["account"])
        sender = f"{row['sender']} {LRI}<{row['sender_address']}>{PDI}"
        self.header.setText("\n".join([t("from_line", self.lang, sender=sender),
                                       t("to_line", self.lang, to=f"{LRI}{row['recipients'] or ''}{PDI}"),
                                       row["subject"] or t("no_subject", self.lang)]))
        self.notice.hide()
        if row["account"] == localmail.LOCAL:  # kept whole on this computer when it was imported
            raw = self.store.body(localmail.LOCAL, row["folder"], row["uid"])
            self.show_body(mail.parse_body(raw or b""))
            self.store.set_seen(localmail.LOCAL, row["folder"], row["uid"])
            row["seen"] = 1
            self._style_row(item, row)
            return
        self.reader.setPlainText(t("loading", self.lang))
        password = self.password_for(account) if account else None
        if account is None or password is None:
            return
        key = (row["account"], row["folder"], row["uid"])

        def done(body) -> None:
            if not self.current or (self.current["account"], self.current["folder"], self.current["uid"]) != key:
                return  # another message was opened meanwhile
            self.show_body(body)
            row["seen"] = 1
            self._style_row(item, row)

        self.runner.start(lambda: engine.open_message(account, password, self.db, row["folder"], row["uid"]), done,
                          lambda e: self.reader.setPlainText(error(e, self.lang)))

    def show_body(self, body: mail.Body) -> None:
        blocked = 0
        if body.html:
            safe, blocked = sanitize.clean_html(body.html, t("image", self.lang))
            self.current_text = body.text or sanitize.html_to_text(body.html)
        else:
            safe = sanitize.text_to_html(body.text)
            self.current_text = body.text
        self.reader.setHtml(safe)
        notes = []
        if blocked:
            notes.append(t("images_blocked", self.lang, count=blocked))
        if body.attachments:
            notes.append(t("attachments", self.lang, names=", ".join(n for n, _ in body.attachments[:8])))
        self.notice.setText("\n".join(notes))
        self.notice.setVisible(bool(notes))

    def import_mail(self, sources: list | None = None) -> None:
        """Copy the mail other apps keep on this computer into local folders (their files are only read)."""
        found = localmail.find_sources() if sources is None else sources
        if not found:
            self.statusBar().showMessage(t("import_mail_none", self.lang), 8000)
            return
        self.statusBar().showMessage(t("import_mail_running", self.lang, count=len(found)))

        def work():
            from .store import Store

            store = Store(self.db)
            try:
                return [localmail.import_source(store, source) for source in found]
            finally:
                store.close()

        def done(results) -> None:
            added = sum(r.added for r in results)
            self.statusBar().showMessage(t("import_mail_done", self.lang, added=added, folders=len(results)), 10000)
            self.refresh_views()

        self.runner.start(work, done, lambda e: self.statusBar().showMessage(error(e, self.lang)))

    def _open_link(self, url: QUrl) -> None:
        if url.scheme() == "mailto":
            self.new_message(mailto=url.toString())
        elif url.scheme() in ("http", "https"):
            QDesktopServices.openUrl(url)

    # Passwords and sync

    def _ask_password(self, account: acc.Account) -> str | None:
        value, ok = QInputDialog.getText(self, t("title", self.lang), t("ask_password", self.lang, address=account.address),
                                         QLineEdit.EchoMode.Password)
        return value if ok and value else None

    def password_for(self, account: acc.Account) -> str | None:
        password = self.keyring.get(account.id)
        if password is None:
            password = self.ask_password(account)
            if password is not None:
                self.keyring.memory[account.id] = password
        return password

    def sync_all(self) -> None:
        for account in self.accounts:
            self.sync(account)

    def sync(self, account: acc.Account, folder: str | None = None) -> None:
        if account.id in self.syncing:
            return
        password = self.password_for(account)
        if password is None:
            return
        self.syncing.add(account.id)
        self.statusBar().showMessage(t("checking", self.lang))

        def done(result) -> None:
            self.syncing.discard(account.id)
            acc.save(self.accounts, self.directory)  # the folder roles found on the server
            count = sum(result["arrived"].values()) if isinstance(result, dict) else 0
            self.statusBar().showMessage(t("arrived", self.lang, count=count) if count else t("up_to_date", self.lang),
                                         8000)
            self.refresh_views()

        def failed(key: str) -> None:
            self.syncing.discard(account.id)
            if key == "login":
                self.keyring.memory.pop(account.id, None)
            self.statusBar().showMessage(f"{account.address}: {error(key, self.lang)}")

        self.runner.start(lambda: engine.sync(account, password, self.db, folder), done, failed)

    # Actions

    def add_account(self) -> None:
        dialog = SetupDialog(self.lang, self.keyring, self.runner, parent=self)
        if dialog.exec() and dialog.account is not None:
            self.accounts = [a for a in self.accounts if a.id != dialog.account.id] + [dialog.account]
            acc.save(self.accounts, self.directory)
            self.refresh_views()
            self.sync(dialog.account)

    def import_accounts(self, found: list | None = None, dialog_factory=None) -> None:
        from .importers import find_all

        found = find_all() if found is None else found
        dialog = (dialog_factory or ImportDialog)(self.lang, found, self)
        if not dialog.exec():
            return
        known = {a.id for a in self.accounts}
        new = [a for a in dialog.chosen() if a.id not in known]
        self.accounts += new
        acc.save(self.accounts, self.directory)
        self.refresh_views()
        self.statusBar().showMessage(t("import_added", self.lang, count=len(new)), 10000)
        for account in new:
            self.sync(account)

    def _compose(self, draft: compose.Draft | None = None) -> None:
        if not self.accounts:
            self.add_account()
            return
        window = ComposeWindow(self.lang, self.accounts, self.password_for, self.runner, draft,
                               on_sent=lambda account: self.sync(account))
        self.windows = [w for w in self.windows if w.isVisible()] + [window]
        window.show()
        (window.body if draft and draft.to else window.to).setFocus()

    def new_message(self, mailto: str = "") -> None:
        draft = None
        if mailto.startswith("mailto:"):
            parsed = urllib.parse.urlsplit(mailto)
            query = urllib.parse.parse_qs(parsed.query)
            body = query.get("body", [""])[0]
            draft = compose.Draft("", self.accounts[0].address if self.accounts else "",
                                  to=urllib.parse.unquote(parsed.path), cc=query.get("cc", [""])[0],
                                  subject=query.get("subject", [""])[0],
                                  paragraphs=[(line, "auto") for line in body.split("\n")] if body else [])
        self._compose(draft)

    def reply(self, everyone: bool) -> None:
        if self.current is None:
            return
        draft = compose.reply(self.current, self.current_text, self.current["account"], everyone, self.lang)
        self._compose(draft)

    def forward(self) -> None:
        if self.current is None:
            return
        self._compose(compose.forward(self.current, self.current_text, self.current["account"], self.lang))

    def delete(self) -> None:
        row = self.current
        if row and row["account"] == localmail.LOCAL:
            self._step(1)
            self.store.remove(localmail.LOCAL, row["folder"], row["uid"])
            self.show_folder()
            return
        account = self._account(row["account"]) if row else None
        password = self.password_for(account) if account else None
        if row is None or password is None:
            return
        self._step(1)
        self.runner.start(lambda: engine.delete(account, password, self.db, row["folder"], row["uid"]),
                          lambda _: self.show_folder(),
                          lambda e: self.statusBar().showMessage(error(e, self.lang)))

    def snooze_menu(self) -> None:
        if self.current is None:
            return
        menu = QMenu(self)
        for choice in ("later", "tomorrow", "week"):
            action = menu.addAction(t(f"snooze_{choice}", self.lang))
            action.triggered.connect(lambda _=False, c=choice: self.snooze(c))
        menu.exec(self.mapToGlobal(self.list.geometry().center()))

    def snooze(self, choice: str) -> None:
        """Out of sight until then; back unread. Only on this computer: the server keeps the message as it is."""
        from .store import snooze_time

        row = self.current
        if row is None:
            return
        until = snooze_time(choice)
        self._step(1)
        self.store.snooze(row["account"], row["folder"], row["uid"], until)
        self.statusBar().showMessage(t("snoozed", self.lang, when=when(until, self.lang)), 8000)
        self.refresh_views()
        self._wake_later()

    def _wake_later(self) -> None:
        """Show a snoozed message again when its time comes, even if J stays open."""
        wake = self.store.next_wake()
        if wake is not None:
            QTimer.singleShot(int(max(1.0, min(wake - time.time(), 86400.0)) * 1000) + 500, self.refresh_views)

    def mark_unread(self) -> None:
        row = self.current
        item = self.list.currentItem()
        if row and item is not None and row["account"] == localmail.LOCAL:
            self.store.set_seen(localmail.LOCAL, row["folder"], row["uid"], False)
            row["seen"] = 0
            self._style_row(item, row)
            return
        account = self._account(row["account"]) if row else None
        password = self.password_for(account) if account else None
        if row is None or password is None or item is None:
            return

        def work() -> None:
            with mail.Imap(account.incoming, password) as imap:
                imap.select(row["folder"], readonly=False)
                imap.set_flag(row["uid"], "\\Seen", on=False)
            from .store import Store

            store = Store(self.db)
            store.set_seen(account.id, row["folder"], row["uid"], False)
            store.close()

        def done(_result) -> None:
            row["seen"] = 0
            self._style_row(item, row)

        self.runner.start(work, done, lambda e: self.statusBar().showMessage(error(e, self.lang)))

    def closeEvent(self, event) -> None:  # noqa: N802
        self.store.close()
        super().closeEvent(event)


def main(mailto: str = "") -> int:
    lang = ui_lang()
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("J")
    app.setApplicationVersion(__version__)
    app.setOrganizationName(__author__)
    app.setDesktopFileName("dai-j")
    app.setLayoutDirection(qt_direction(lang))
    if "Noto Sans" in QFontDatabase.families():
        app.setFont(QFont("Noto Sans", 10))
    window = MainWindow(lang)
    window.show()
    if mailto:
        window.new_message(mailto)
    elif not window.accounts:
        window.empty_button.setFocus()
    else:
        window.list.setFocus()
    return app.exec()
