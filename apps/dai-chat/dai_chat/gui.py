# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The Diamond Chat window (docs/SEND.md §3, "The experience"): contacts on one side, the conversation on the
other, and the message field at the bottom. Right-to-left in Hebrew, in the person's theme, every control named
for screen readers and reachable with Tab.

It reads and writes the same store as the background service, and pokes the service after writing; it looks
at the store again every two seconds, so messages that arrived show up without a restart.
"""
from __future__ import annotations

import subprocess
import sys
import time
import unicodedata
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QGuiApplication, QIcon, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (QApplication, QDialog, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
                             QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget)

from dai_i18n import pick, qt_direction, ui_lang
from dai_style import color
from dai_style.panes import Panes, touch_scrolling

from . import invite, pictures, sas, scan
from .pairing import clean_name
from .service import Settings, settings_path
from .message import MAX_PICTURE, MAX_TEXT, Message
from .store import Contact, Store

APP_ID = "dai-chat"
PUBLIC_ROLE = Qt.ItemDataRole.UserRole + 1
PICTURE_ROLE = Qt.ItemDataRole.UserRole + 2
THUMBNAIL = 180
REFRESH_MS = 2000

BG, BG2, SURFACE, BORDER, TEXT, MUTED = (color(r) for r in ("bg_900", "bg_800", "surface", "border", "text", "muted"))
ACCENT, ACCENT_STRONG, ACCENT_2, WARN, OK = (color(r) for r in ("accent", "accent_strong", "accent_2", "warn", "ok"))
DISABLED = color("disabled")
STYLE = f"""
QWidget#Window, QDialog {{ background: {BG}; color: {TEXT}; }}
QLabel {{ color: {TEXT}; }}
#Title {{ font-size: 14pt; font-weight: 700; }}
#AppTitle {{ font-size: 12pt; font-weight: 700; color: {MUTED}; padding-bottom: 4px; }}
#Muted {{ color: {MUTED}; }}
#Banner {{ background: {SURFACE}; border: 1px solid {WARN}; border-radius: 10px; }}
#BannerText {{ color: {TEXT}; }}
#Unverified {{ color: {WARN}; font-weight: 600; }}
#Verified {{ color: {OK}; font-weight: 600; }}
#Symbols {{ font-size: 18pt; color: {TEXT}; }}
#Code {{ font-family: monospace; font-size: 13pt; color: {TEXT}; background: {SURFACE}; border: 1px solid {BORDER};
    border-radius: 8px; padding: 8px; }}
QListWidget {{ background: {BG2}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 10px; outline: none;
    font-size: 11pt; padding: 4px; }}
QListWidget::item {{ padding: 6px; border-radius: 8px; }}
QListWidget::item:selected {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {ACCENT}; }}
QListWidget:focus {{ border: 2px solid {ACCENT_2}; }}
QLineEdit {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 10px; padding: 8px 12px;
    font-size: 12pt; selection-background-color: {ACCENT_STRONG}; }}
QLineEdit:focus {{ border: 2px solid {ACCENT_2}; }}
QPushButton {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 14px; }}
QPushButton:hover {{ border: 1px solid {ACCENT}; }}
QPushButton:focus {{ border: 2px solid {ACCENT_2}; }}
QPushButton#Primary {{ background: {ACCENT_STRONG}; color: #FFFFFF; border: 1px solid {ACCENT_STRONG}; }}
QPushButton#Primary:focus {{ border: 2px solid {ACCENT_2}; }}
QPushButton:disabled, QPushButton#Primary:disabled {{ background: {SURFACE}; color: {DISABLED}; border: 1px solid {BORDER}; }}
QLineEdit:disabled {{ color: {DISABLED}; }}
"""


def in_its_direction(text: str) -> str:
    """A message laid out in its own direction, whatever the window's: Hebrew or Arabic right to left, the rest
    left to right (from its first letter, as the Unicode bidi algorithm does for a paragraph)."""
    for char in text:
        kind = unicodedata.bidirectional(char)
        if kind in ("R", "AL"):
            return f"\u202b{text}\u202c"  # RLE ... PDF
        if kind == "L":
            return f"\u202a{text}\u202c"  # LRE ... PDF
    return text


def say(lang: str, en: str, he: str, **kwargs: object) -> str:
    return pick(lang, en, he).format(**kwargs)


def turn_on(run: Callable = subprocess.Popen) -> None:
    run(["dai-chat", "on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class NameDialog(QDialog):
    """The display name contacts see: chosen here, never taken from the computer's user name."""

    def __init__(self, parent: QWidget, lang: str, current: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(say(lang, "Your display name", "שם התצוגה שלכם"))
        self.setLayoutDirection(qt_direction(lang))
        layout = QVBoxLayout(self)
        intro = QLabel(say(lang, "The name your contacts will see. Choose any name: it is not your user name on "
                           "this computer, and you can change it later.",
                           "השם שאנשי הקשר יראו. בחרו כל שם: זה לא שם המשתמש שלכם במחשב, ואפשר לשנות אותו אחר כך."))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.name = QLineEdit(current)
        self.name.setMaxLength(40)
        self.name.setAccessibleName(say(lang, "Your display name", "שם התצוגה שלכם"))
        intro.setBuddy(self.name)
        layout.addWidget(self.name)
        self.error = QLabel("")
        self.error.setObjectName("Unverified")
        layout.addWidget(self.error)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(say(lang, "Cancel", "ביטול"))
        cancel.setAccessibleName(cancel.text())
        cancel.clicked.connect(self.reject)
        self.ok = QPushButton(say(lang, "Save", "שמירה"))
        self.ok.setObjectName("Primary")
        self.ok.setAccessibleName(self.ok.text())
        self.ok.setDefault(True)
        self.ok.clicked.connect(self.check)
        buttons.addWidget(cancel)
        buttons.addWidget(self.ok)
        layout.addLayout(buttons)
        self.lang, self.chosen = lang, ""

    def check(self) -> None:
        self.chosen = clean_name(self.name.text())
        if not self.chosen:
            self.error.setText(say(self.lang, "Write a name with letters in it.", "כתבו שם שיש בו אותיות."))
            return
        self.accept()


class AddDialog(QDialog):
    """Their name and the code they gave you; your code to give them."""

    def __init__(self, parent: QWidget, lang: str, my_code: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(say(lang, "Add a contact", "הוספת איש קשר"))
        self.setLayoutDirection(qt_direction(lang))
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setAccessibleName(say(lang, "Their name", "השם שלהם"))
        self.code = QLineEdit()
        self.code.setAccessibleName(say(lang, "The code they gave you", "הקוד שקיבלתם מהם"))
        self.code.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        name_label, code_label = QLabel(say(lang, "Their name", "השם שלהם")), QLabel(
            say(lang, "The code they gave you", "הקוד שקיבלתם מהם"))
        name_label.setBuddy(self.name)
        code_label.setBuddy(self.code)
        form.addRow(name_label, self.name)
        form.addRow(code_label, self.code)
        layout.addLayout(form)
        mine = QLabel(say(lang, "Give them your code too:", "תנו להם גם את הקוד שלכם:"))
        layout.addWidget(mine)
        code = QLabel(my_code)
        code.setObjectName("Code")
        code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        code.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        code.setAccessibleName(say(lang, "Your code", "הקוד שלכם"))
        layout.addWidget(code)
        self.error = QLabel("")
        self.error.setObjectName("Unverified")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QHBoxLayout()
        self.copy = QPushButton(say(lang, "Copy my code", "העתקת הקוד שלי"))
        self.copy.setAccessibleName(self.copy.text())
        self.copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(my_code))
        self.ok = QPushButton(say(lang, "Add", "הוספה"))
        self.ok.setObjectName("Primary")
        self.ok.setAccessibleName(self.ok.text())
        self.ok.setDefault(True)
        self.ok.clicked.connect(self.check)
        cancel = QPushButton(say(lang, "Cancel", "ביטול"))
        cancel.setAccessibleName(cancel.text())
        cancel.clicked.connect(self.reject)
        buttons.addWidget(self.copy)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self.ok)
        layout.addLayout(buttons)
        self.lang, self.my_code, self.parsed = lang, my_code, None

    def check(self) -> None:
        try:
            parsed = invite.parse(self.code.text())
        except invite.InviteError:
            self.error.setText(say(self.lang, "That code has a typo. Check it with them and try again.",
                                   "בקוד יש שגיאת הקלדה. בדקו אותו מולם ונסו שוב."))
            self.code.setFocus()
            return
        if not self.name.text().strip():
            self.error.setText(say(self.lang, "Write their name.", "כתבו את השם שלהם."))
            self.name.setFocus()
            return
        if "".join(self.code.text().split()).lower() == "".join(self.my_code.split()).lower():
            self.error.setText(say(self.lang, "That is your own code.", "זה הקוד שלכם."))
            return
        self.parsed = parsed
        self.accept()


class SymbolsDialog(QDialog):
    """The six symbols, large, to compare by phone or face to face."""

    def __init__(self, parent: QWidget, lang: str, name: str, indexes: list[int]) -> None:
        super().__init__(parent)
        self.setWindowTitle(say(lang, "Compare with {name}", "השוואה עם {name}", name=name))
        self.setLayoutDirection(qt_direction(lang))
        layout = QVBoxLayout(self)
        intro = QLabel(say(lang, "Call {name} or meet. You should both see these six, in this order:",
                           "התקשרו ל־{name} או היפגשו. שניכם אמורים לראות את ששת אלה, בסדר הזה:", name=name))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        symbols = QLabel(sas.describe(indexes, lang))
        symbols.setObjectName("Symbols")
        symbols.setWordWrap(True)
        symbols.setAccessibleName(sas.describe(indexes, lang))
        layout.addWidget(symbols)
        buttons = QHBoxLayout()
        self.differ = QPushButton(say(lang, "They are different", "הם שונים"))
        self.differ.setAccessibleName(self.differ.text())
        self.differ.clicked.connect(self.reject)
        self.match = QPushButton(say(lang, "They match", "הם זהים"))
        self.match.setObjectName("Primary")
        self.match.setAccessibleName(self.match.text())
        self.match.clicked.connect(self.accept)
        buttons.addStretch(1)
        buttons.addWidget(self.differ)
        buttons.addWidget(self.match)
        layout.addLayout(buttons)
        warning = QLabel(say(lang, "If they are different, someone may be in the middle: do not verify.",
                             "אם הם שונים, ייתכן שמישהו באמצע: אל תאמתו."))
        warning.setObjectName("Muted")
        warning.setWordWrap(True)
        layout.addWidget(warning)


class ChatWindow(QWidget):
    def __init__(self, store: Store, me: bytes, my_code: str, poke: Callable[[], object] = lambda: None,
                 running: Callable[[], bool] = lambda: True, clean: Callable = pictures.clean,
                 lang: str | None = None, clock: Callable[[], float] = time.time,
                 viewer: Callable[[Path], None] | None = None, settings_file: Path | None = None,
                 restart: Callable[[], None] | None = None) -> None:
        super().__init__()
        from .cli import restart as restart_service

        self.store, self.me, self.my_code = store, me, my_code
        self.settings_file = settings_file or settings_path()
        self.restart = restart or restart_service
        self.viewer = viewer or (lambda path: subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL,
                                                                stderr=subprocess.DEVNULL))
        self.poke, self.running, self.clean, self.clock = poke, running, clean, clock
        self.lang = lang or ui_lang()
        self.current: bytes | None = None
        self.setObjectName("Window")
        self.setWindowTitle("Diamond Chat")
        self.setLayoutDirection(qt_direction(self.lang))
        self.setStyleSheet(STYLE)
        self.resize(900, 600)
        outer = QVBoxLayout(self)
        title = QLabel("💎 Diamond Chat")
        title.setObjectName("AppTitle")
        outer.addWidget(title)

        # the person's own side: contacts, waiting codes, and adding someone
        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        self.contacts = QListWidget()
        self.contacts.setAccessibleName(say(self.lang, "Contacts", "אנשי קשר"))
        self.contacts.currentItemChanged.connect(lambda item, _old: self.open(item))
        side_layout.addWidget(self.contacts, 1)
        self.add_button = QPushButton(say(self.lang, "＋ Add a contact", "＋ הוספת איש קשר"))
        self.add_button.setAccessibleName(say(self.lang, "Add a contact", "הוספת איש קשר"))
        self.add_button.clicked.connect(self.add_contact)
        side_layout.addWidget(self.add_button)

        # the conversation
        talk = QWidget()
        talk_layout = QVBoxLayout(talk)
        talk_layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        self.who = QLabel(say(self.lang, "Choose a contact, or add one.", "בחרו איש קשר, או הוסיפו אחד."))
        self.who.setObjectName("Title")
        header.addWidget(self.who)
        self.state = QLabel("")
        header.addWidget(self.state)
        header.addStretch(1)
        self.compare = QPushButton(say(self.lang, "Compare symbols", "השוואת סמלים"))
        self.compare.setAccessibleName(self.compare.text())
        self.compare.clicked.connect(self.compare_symbols)
        header.addWidget(self.compare)
        talk_layout.addLayout(header)
        self.display = QLabel("")
        self.display.setObjectName("Muted")
        talk_layout.addWidget(self.display)
        # what waits for a decision: a new contact's messages, or one the checks held
        self.banner = QFrame()
        self.banner.setObjectName("Banner")
        banner_layout = QVBoxLayout(self.banner)
        self.banner_text = QLabel("")
        self.banner_text.setObjectName("BannerText")
        self.banner_text.setWordWrap(True)
        banner_layout.addWidget(self.banner_text)
        banner_buttons = QHBoxLayout()
        banner_buttons.addStretch(1)
        self.decline_button = QPushButton(say(self.lang, "Decline and block", "דחייה וחסימה"))
        self.discard_button = QPushButton(say(self.lang, "Delete it", "מחיקה"))
        self.show_button = QPushButton(say(self.lang, "Show it anyway", "להציג בכל זאת"))
        self.accept_button = QPushButton(say(self.lang, "Accept", "אישור"))
        self.accept_button.setObjectName("Primary")
        for button, action in ((self.decline_button, self.decline), (self.discard_button, self.discard_held),
                               (self.show_button, self.show_held), (self.accept_button, self.accept_contact)):
            button.setAccessibleName(button.text())
            button.clicked.connect(action)
            banner_buttons.addWidget(button)
        banner_layout.addLayout(banner_buttons)
        self.banner.hide()
        talk_layout.addWidget(self.banner)
        self.held_id = ""
        self.messages = QListWidget()
        self.messages.setAccessibleName(say(self.lang, "Conversation", "שיחה"))
        self.messages.setWordWrap(True)
        self.messages.setSpacing(2)
        self.messages.setIconSize(QSize(THUMBNAIL, THUMBNAIL))
        self.messages.itemActivated.connect(self.open_picture)  # Enter or a double click on a picture
        talk_layout.addWidget(self.messages, 1)
        bottom = QHBoxLayout()
        self.field = QLineEdit()
        self.field.setMaxLength(MAX_TEXT // 4)
        self.field.setAccessibleName(say(self.lang, "Message", "הודעה"))
        self.field.setPlaceholderText(say(self.lang, "Write a message…", "כתבו הודעה…"))
        self.field.returnPressed.connect(self.send)
        bottom.addWidget(self.field, 1)
        self.picture_button = QPushButton(say(self.lang, "Picture…", "תמונה…"))
        self.picture_button.setAccessibleName(say(self.lang, "Send a picture", "שליחת תמונה"))
        self.picture_button.clicked.connect(self.send_picture)
        bottom.addWidget(self.picture_button)
        self.send_button = QPushButton(say(self.lang, "Send", "שליחה"))
        self.send_button.setObjectName("Primary")
        self.send_button.setAccessibleName(self.send_button.text())
        self.send_button.clicked.connect(self.send)
        bottom.addWidget(self.send_button)
        talk_layout.addLayout(bottom)

        split = Panes()  # people beside the talk; one above the other when narrow (docs/MOBILE.md A2)
        split.addWidget(side)
        split.addWidget(talk)
        split.setSizes([280, 620])
        split.setChildrenCollapsible(False)
        outer.addWidget(split, 1)
        touch_scrolling(self)

        # the service: a line that says whether messages can go out now
        status = QHBoxLayout()
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        status.addWidget(self.status, 1)
        self.name_button = QPushButton("")
        self.name_button.clicked.connect(self.choose_name)
        status.addWidget(self.name_button)
        self.receive_button = QPushButton("")
        self.receive_button.setCheckable(True)
        self.receive_button.clicked.connect(self.toggle_receive)
        status.addWidget(self.receive_button)
        self.on_button = QPushButton(say(self.lang, "Turn Chat on", "הפעלת Chat"))
        self.on_button.setAccessibleName(self.on_button.text())
        self.on_button.clicked.connect(self.turn_on)
        status.addWidget(self.on_button)
        outer.addLayout(status)

        QShortcut(QKeySequence("Ctrl+N"), self, activated=self.add_contact)
        self.timer = QTimer(self, interval=REFRESH_MS, timeout=self.refresh)
        self.timer.start()
        self.refresh()
        self.show_conversation()

    # the lists
    def refresh(self) -> None:
        selected = self.current
        self.contacts.blockSignals(True)
        self.contacts.clear()
        for contact in self.store.contacts():
            mark = "🚫" if contact.blocked else ("✓" if contact.verified else "•")
            waiting = len(self.store.conversation(contact.public, waiting=True))
            label = f"{mark}  {contact.name}" + (f"  ({waiting} ✉)" if waiting else "")
            item = QListWidgetItem(label)
            item.setData(PUBLIC_ROLE, contact.public)
            item.setToolTip(self._state_text(contact))
            self.contacts.addItem(item)
            if contact.public == selected:
                self.contacts.setCurrentItem(item)
        for _theirs, name in self.store.waiting():
            item = QListWidgetItem(say(self.lang, "⌛  {name} (waiting for them)", "⌛  {name} (ממתינים להם)", name=name))
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.contacts.addItem(item)
        self.contacts.blockSignals(False)
        settings = self.settings()
        self.name_button.setText(say(self.lang, "Your name: {name}", "השם שלכם: {name}", name=settings.name)
                                 if settings.name else say(self.lang, "Choose your name", "בחירת שם"))
        self.name_button.setAccessibleName(self.name_button.text())
        self.receive_button.setChecked(settings.receive)
        self.receive_button.setText(say(self.lang, "Receiving: on", "קבלת הודעות: פועלת") if settings.receive else
                                    say(self.lang, "Receiving: off", "קבלת הודעות: כבויה"))
        self.receive_button.setAccessibleName(self.receive_button.text())
        on = self.running()
        self.on_button.setVisible(not on)
        self.status.setText(say(self.lang, "On: messages go out as soon as your contacts are online.",
                                "פועל: הודעות יוצאות ברגע שאנשי הקשר מחוברים.") if on else
                            say(self.lang, "Chat is off. Messages you write wait on this computer.",
                                "Chat כבוי. הודעות שתכתבו ימתינו במחשב הזה."))
        if self.current is not None:
            self.show_conversation(keep_position=True)

    def _state_text(self, contact: Contact) -> str:
        if contact.blocked:
            return say(self.lang, "blocked", "חסום")
        if contact.verified:
            return say(self.lang, "verified", "מאומת")
        return say(self.lang, "not verified: compare the symbols", "לא מאומת: השוו את הסמלים")

    def open(self, item: QListWidgetItem | None) -> None:
        public = item.data(PUBLIC_ROLE) if item is not None else None
        self.current = public if isinstance(public, bytes) else None
        self.show_conversation()
        if self.current is not None:
            self.field.setFocus()

    def show_conversation(self, keep_position: bool = False) -> None:
        contact = self.store.contact(self.current) if self.current else None
        for widget in (self.field, self.send_button, self.picture_button, self.compare):
            widget.setEnabled(contact is not None and not contact.blocked)
        self.compare.setVisible(contact is not None and not contact.verified)
        if contact is None:
            self.messages.clear()
            self.state.setText("")
            self.display.setText("")
            self.banner.hide()
            return
        self.who.setText(contact.name)
        self.display.setText(say(self.lang, "Calls themselves: {name}", "השם שבחרו לעצמם: {name}",
                                 name=contact.display) if contact.display and contact.display != contact.name else "")
        self.show_banner(contact)
        self.state.setText(self._state_text(contact))
        self.state.setObjectName("Verified" if contact.verified else "Unverified")
        self.state.setStyleSheet("")  # re-apply the object-name rule
        rows = self.store.conversation(contact.public)
        if keep_position and self.messages.count() == len(rows):
            return
        self.messages.clear()
        for row in rows:
            when = time.strftime("%H:%M", time.localtime(row["time"]))
            who = say(self.lang, "Me", "אני") if row["outgoing"] else contact.name
            body = in_its_direction(row["text"]) or say(self.lang, "[a picture]", "[תמונה]")
            mark = {"queued": "⌛", "delivered": "✓", "seen": "✓✓",
                    "refused": say(self.lang, "refused", "נדחתה")}.get(row["state"], "") if row["outgoing"] else ""
            item = QListWidgetItem(f"{who} · {when}  {mark}\n{body}")
            # theirs at the start of the line, mine at the end (the right and the left in Hebrew, as in other apps)
            side = Qt.AlignmentFlag.AlignTrailing if row["outgoing"] else Qt.AlignmentFlag.AlignLeading
            item.setTextAlignment(int(side | Qt.AlignmentFlag.AlignVCenter))
            if row["picture"]:
                # Already re-drawn in the sandbox when it arrived (or before it was sent): only fresh pixels here.
                path = self.store.pictures / row["picture"]
                thumbnail = QPixmap(str(path))
                if not thumbnail.isNull():
                    item.setIcon(QIcon(thumbnail.scaled(THUMBNAIL, THUMBNAIL, Qt.AspectRatioMode.KeepAspectRatio,
                                                        Qt.TransformationMode.SmoothTransformation)))
                    item.setData(PICTURE_ROLE, str(path))
                    item.setToolTip(say(self.lang, "Enter or double-click to open", "Enter או לחיצה כפולה לפתיחה"))

            self.messages.addItem(item)
        self.messages.scrollToBottom()

    # decisions
    def show_banner(self, contact: Contact) -> None:
        waiting = self.store.conversation(contact.public, waiting=True)
        requests = [m for m in waiting if m["state"] == "request"]
        held = [m for m in waiting if m["state"] == "held"]
        self.held_id = held[0]["id"] if held and not requests else ""
        if requests:
            text = say(self.lang, "{name} sent {count} messages. They are shown only if you accept {name}; every "
                       "message is checked for phishing and malware first.",
                       "‏{name} שלחו {count} הודעות. הן יוצגו רק אם תאשרו את {name}; כל הודעה נבדקת קודם לפישינג "
                       "ולנוזקה.", name=contact.name, count=len(requests))
        elif held:
            text = say(self.lang, "A message from {name} was held because {why}. These are warning signs, not proof.",
                       "הודעה מאת {name} עוכבה כי {why}. אלה סימני אזהרה, לא הוכחה.", name=contact.name,
                       why=scan.describe(held[0]["warning"].split(","), self.lang))
        else:
            self.banner.hide()
            return
        self.banner_text.setText(text)
        self.accept_button.setVisible(bool(requests))
        self.decline_button.setVisible(bool(requests))
        self.show_button.setVisible(bool(self.held_id))
        self.discard_button.setVisible(bool(self.held_id))
        self.banner.show()

    def accept_contact(self) -> None:
        if self.current:
            self.store.accept(self.current)
            self.refresh()
            self.show_conversation()

    def decline(self) -> None:
        if self.current:
            self.store.decline(self.current)
            self.refresh()
            self.show_conversation()

    def show_held(self) -> None:
        if self.current and self.held_id:
            self.store.show(self.current, self.held_id)
            self.show_conversation()

    def discard_held(self) -> None:
        if self.current and self.held_id:
            self.store.delete_waiting(self.current, self.held_id)
            self.show_conversation()

    def settings(self) -> Settings:
        return Settings.load(self.settings_file)

    def choose_name(self) -> bool:
        dialog = NameDialog(self, self.lang, self.settings().name)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        settings = self.settings()
        settings.name = dialog.chosen
        settings.save(self.settings_file)
        self.restart()
        self.refresh()
        return True

    def toggle_receive(self) -> None:
        settings = self.settings()
        if not settings.name and not self.choose_name():
            self.refresh()
            return
        settings = self.settings()
        settings.receive = not settings.receive
        settings.save(self.settings_file)
        self.restart()
        self.refresh()

    # actions
    def open_picture(self, item: QListWidgetItem) -> None:
        path = item.data(PICTURE_ROLE)
        if path:
            self.viewer(Path(path))

    def send(self) -> None:
        words = self.field.text().strip()
        if not words or self.current is None:
            return
        self.store.add_message(self.current, Message.text(words), outgoing=True, state="queued")
        self.field.clear()
        self.poke()
        self.show_conversation()

    def send_picture(self, path: str | None = None) -> None:
        contact = self.store.contact(self.current) if self.current else None
        if contact is None:
            return
        if not contact.verified:
            self.status.setText(say(self.lang, "Compare the symbols with {name} first: pictures are only accepted "
                                    "from verified contacts.", "השוו קודם את הסמלים עם {name}: תמונות מתקבלות רק "
                                    "מאנשי קשר מאומתים.", name=contact.name))
            return
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, say(self.lang, "Send a picture", "שליחת תמונה"),
                                                  str(Path.home() / "Pictures"), "Pictures (*.png *.jpg *.jpeg *.webp)")
        if not path:
            return
        try:
            if Path(path).stat().st_size > MAX_PICTURE:
                raise pictures.PictureError("too large")
            body, mime = self.clean(Path(path).read_bytes())
        except (OSError, pictures.PictureError):
            self.status.setText(say(self.lang, "That file is not a PNG, JPEG or WebP picture up to 25 MB.",
                                    "הקובץ אינו תמונת PNG, JPEG או WebP של עד 25MB."))
            return
        self.store.add_message(contact.public, Message.picture(body, mime), outgoing=True, state="queued")
        self.poke()
        self.status.setText(say(self.lang, "Queued, without its location and camera details.",
                                "בתור, בלי המיקום ופרטי המצלמה."))
        self.show_conversation()

    def add_contact(self) -> None:
        dialog = AddDialog(self, self.lang, self.my_code)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.parsed is not None:
            self.store.wait_for(dialog.parsed, dialog.name.text())
            self.poke()
            self.refresh()

    def compare_symbols(self) -> None:
        contact = self.store.contact(self.current) if self.current else None
        if contact is None:
            return
        dialog = SymbolsDialog(self, self.lang, contact.name, sas.symbols(self.me, contact.public))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.store.set_verified(contact.public)
            self.refresh()

    def turn_on(self) -> None:
        turn_on()
        QTimer.singleShot(1500, self.refresh)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        return QSize(900, 600)


def main(argv: list[str] | None = None) -> int:
    from . import keys
    from .cli import control_path, default_stores
    from .service import invite_code, poke
    from .store import default_dir

    app = QApplication(list(sys.argv if argv is None else argv))
    app.setDesktopFileName(APP_ID)
    folder = default_dir()
    store = Store(folder)
    identity_stores, onion_stores = default_stores(folder)
    me, _ = keys.load_or_create(identity_stores)
    onion, _ = keys.load_or_create(onion_stores)
    window = ChatWindow(store, me.public, invite_code(onion.seed(), me),
                        poke=lambda: poke(control_path()),
                        running=lambda: poke(control_path(), "status") is not None)
    window.show()
    if not window.settings().name:  # first time: the name contacts will see, chosen, never the user name
        QTimer.singleShot(300, window.choose_name)
    try:
        return app.exec()
    finally:
        store.close()

