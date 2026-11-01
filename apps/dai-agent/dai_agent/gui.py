# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The agent window (docs/AGENTS.md §6): the same loop as the CLI, the steps as a list, and approval by a
button that shows the D.Ai Tune plan before anything changes. Nothing is applied without the click."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from typing import Any, Callable

from PyQt6.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from dai_i18n import embed, pick, qt_direction, ui_lang
from dai_style import app_font, color, rgba, with_touch

from . import __author__, __version__
from .agent import AgentError, Run, StepRecord, run_agent
from .plans import describe_act
from .policy import allowed_roles, refusal
from .roles import ROLES
from .tools import Services

APP_ID = "dai-agent"
BG_900, BG_800, BORDER, TEXT, MUTED = color("bg_900"), color("bg_800"), color("border"), color("text"), color("muted")
ACCENT, ACCENT_2, ACCENT_STRONG, DISABLED = color("accent"), color("accent_2"), color("accent_strong"), color("disabled")
SURFACE, DANGER, OK_GREEN = color("surface"), color("danger"), color("ok")

STYLE = f"""
QWidget#Agent {{ background: {BG_900}; }}
QWidget {{ color: {TEXT}; font-size: 11pt; }}
QLabel#Title {{ font-size: 15pt; font-weight: 700; }}
QLabel#Status {{ color: {MUTED}; font-size: 10pt; }}
QLabel#Result {{ font-family: monospace; font-size: 10pt; color: {MUTED}; }}
QLabel#Warn {{ color: {DANGER}; font-weight: 700; }}
QLabel#Ok {{ color: {OK_GREEN}; }}
QFrame#Step {{ background: {rgba('surface', 0.95)}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame#Ask {{ background: {rgba('accent', 0.14)}; border: 1px solid {ACCENT}; border-radius: 12px; }}
QFrame#Final {{ background: {rgba('accent', 0.22)}; border: 1px solid {ACCENT}; border-radius: 14px; }}
QLineEdit {{ background: {BG_800}; border: 1px solid {BORDER}; border-radius: 10px; padding: 9px 12px; font-size: 12pt; }}
QLineEdit:focus {{ border: 2px solid {ACCENT_2}; }}
QComboBox {{ background: {BG_800}; border: 1px solid {BORDER}; border-radius: 10px; padding: 6px 12px; }}
QComboBox:focus {{ border: 2px solid {ACCENT_2}; }}
QComboBox QAbstractItemView {{ background: {BG_800}; color: {TEXT}; selection-background-color: {rgba('accent', 0.35)}; }}
QPushButton {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; padding: 8px 16px; }}
QPushButton:hover {{ border: 1px solid {ACCENT}; background: {rgba('accent', 0.18)}; }}
QPushButton:focus {{ border: 2px solid {ACCENT_2}; }}
QPushButton#Primary {{ background: {ACCENT_STRONG}; color: #FFFFFF; font-weight: 700; border: 1px solid {ACCENT_STRONG}; }}
QToolButton#Mic {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 10px; padding: 8px; font-size: 14pt; }}
QToolButton#Mic:hover {{ border: 1px solid {ACCENT_STRONG}; }}
QToolButton#Mic:focus {{ border: 2px solid {ACCENT_STRONG}; }}
QToolButton#Mic[recording="true"] {{ background: #B4233A; color: #FFFFFF; border: 2px solid {DANGER}; }}
QPushButton:disabled {{ color: {DISABLED}; border: 1px solid {BORDER}; background: {BG_800}; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
"""

STRINGS = {
    "title": ("D.Ai Agent", "סוכן D.Ai"),
    "goal": ("What should the agent do?", "מה הסוכן צריך לעשות?"),
    "role": ("Role", "תפקיד"),
    "dry_run": ("Only show changes", "רק להראות שינויים"),
    "start": ("Start", "התחלה"),
    "stop": ("Stop", "עצירה"),
    "working": ("Diamond is planning…", "Diamond מתכנן…"),
    "idle": ("Every change asks you first. You can undo: dai-tune undo", "כל שינוי שואל קודם. אפשר לבטל: dai-tune undo"),
    "asks": ("Diamond wants to: {tool} {args}", "Diamond רוצה: {tool} {args}"),
    "plan": ("This would change:", "זה ישנה:"),
    "weakens": ("⚠ This step WEAKENS security.", "⚠ הצעד הזה מחליש אבטחה."),
    "system": ("Needs the administrator password (asked by the system).", "דורש סיסמת מנהל (המערכת תשאל)."),
    "not_understood": ("D.Ai Tune did not understand this step: {error}", "D.Ai Tune לא הבין את הצעד: {error}"),
    "allow": ("Allow", "לאשר"),
    "skip": ("Skip", "לדלג"),
    "allowed": ("✓ allowed", "✓ אושר"),
    "skipped": ("✗ skipped", "✗ דולג"),
    "answer": ("Diamond's answer", "התשובה של Diamond"),
    "run_id": ("run {id} · dai-agent history", "ריצה {id} · dai-agent history"),
    "copy": ("Copy", "העתקה"),
    "question": ("Diamond asks: {q}", "Diamond שואל: {q}"),
    "answer_field": ("Your answer", "התשובה שלכם"),
    "send_answer": ("Answer", "לענות"),
    "no_answer": ("No answer", "בלי תשובה"),
    "answered": ("✓ answered", "✓ נענה"),
    "undo": ("Undo all changes", "לבטל את כל השינויים"),
    "undone": ("✓ Undone: every change of this run was taken back.", "✓ בוטל: כל השינויים של הריצה הזאת הוחזרו."),
    "undo_failed": ("Could not undo: {lines}", "לא ניתן לבטל: {lines}"),
    "read": ("Read aloud", "הקראה"),
    "close": ("Close", "סגירה"),
    "local": ("On this computer: the goal and the tools' results stay here.", "במחשב הזה: המטרה ותוצאות הכלים נשארות כאן."),
    "remote": ("The goal and the tools' results go to {p} (your own key).", "המטרה ותוצאות הכלים נשלחות ל־{p} (במפתח שלך)."),
    "failed": ("The agent could not run: {error}", "הסוכן לא הצליח לרוץ: {error}"),
    "status": {"done": ("Done", "הסתיים"), "stopped": ("Stopped", "נעצר"), "failed": ("Failed", "נכשל"),
               "no-plan": ("Diamond could not plan", "Diamond לא הצליח לתכנן")},
}


def ltr(text: str) -> str:
    """Paths and tool output stay left-to-right inside Hebrew."""
    return "\n".join(f"‪{line}‬" for line in text.splitlines())


def execute_in_window(plan: Any, ctx: Any, dry_run: bool = False, assume_yes: bool = False, label: str = "") -> int:
    """The window's executor for the `do` tool: the person already saw the plan on the card and clicked, so
    there is no prompt here; apply_plan keeps the journal, the undo and the polkit helper for system steps."""
    if dry_run:
        return 0
    from dai_tune.cli import apply_plan
    result = apply_plan(plan, ctx, label)
    if not result.ok:
        raise RuntimeError(result.error)
    return 0


class Runner(QObject):
    """Runs the agent loop in a thread and talks to the window only through signals."""

    line = pyqtSignal(str)
    ask = pyqtSignal(object)
    question = pyqtSignal(str)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, goal: str, services: Services, role: str, chat: Callable | None, script: list | None, home) -> None:
        super().__init__()
        self.goal, self.services, self.role, self.chat, self.script, self.home = goal, services, role, chat, script, home
        self.event = threading.Event()
        self.answer = False
        self.said: str | None = None
        self.closing = False
        services.ask_person = self.ask_person

    def approve(self, record: StepRecord) -> bool:
        if self.closing:
            return False
        self.event.clear()
        self.answer = False
        self.ask.emit(describe_act(record, self.services))
        self.event.wait()
        return self.answer and not self.closing

    def reply(self, allowed: bool) -> None:
        self.answer = allowed
        self.event.set()

    def ask_person(self, question: str) -> str | None:
        """The ask tool: a card with a field; the worker waits for the answer (or a skip, or the window closing)."""
        if self.closing:
            return None
        self.event.clear()
        self.said = None
        self.question.emit(question)
        self.event.wait()
        return None if self.closing else self.said

    def reply_text(self, said: str | None) -> None:
        self.said = said
        self.event.set()

    def release(self) -> None:
        self.closing = True
        self.event.set()

    @pyqtSlot()
    def run(self) -> None:
        try:
            run = run_agent(self.goal, self.services, chat=self.chat, role=ROLES[self.role], approve=self.approve,
                            script=self.script, say=self.line.emit, home=self.home)
        except AgentError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - shown in the window, never a silent thread death
            self.failed.emit(str(exc) or exc.__class__.__name__)
            return
        self.finished.emit(run)


class AgentWindow(QWidget):
    def __init__(self, lang: str, services: Services, goal: str = "", role: str = "all", chat: Callable | None = None,
                 script: list | None = None, home=None, spawn: Callable[..., None] | None = None,
                 provider: str = "local", speak: bool = False, root=None, mic: type | None = None) -> None:
        super().__init__(objectName="Agent")
        self.lang, self.services, self.chat, self.script, self.home = lang, services, chat, script, home
        self.spawn = spawn or _spawn
        self.speak = speak                 # --speak: every answer aloud (docs/AGENTS.md §6ג)
        self.spoken_goal = False           # the goal came from the microphone: answer aloud this time
        self.root = root
        self.allowed = allowed_roles(root)
        self.thread: QThread | None = None
        self.runner: Runner | None = None
        self.run: Run | None = None
        self.current: QFrame | None = None
        self.current_result: QLabel | None = None
        self.pending: QFrame | None = None
        if self.services.execute is None:
            self.services.execute = execute_in_window
        self.setWindowTitle(self.t("title"))
        self.setLayoutDirection(qt_direction(lang))
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumSize(560, 420)
        self.resize(760, 720)
        self.setStyleSheet(with_touch(STYLE))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 14)
        outer.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(QLabel(f"✦ {self.t('title')}", objectName="Title"), 1)
        self.status = QLabel(self.t("idle"), objectName="Status")
        self.status.setWordWrap(True)
        head.addWidget(self.status, 2)
        outer.addLayout(head)

        row = QHBoxLayout()
        self.goal = QLineEdit(goal)
        self.goal.setPlaceholderText(self.t("goal"))
        self.goal.setAccessibleName(self.t("goal"))
        self.goal.returnPressed.connect(self.start)
        row.addWidget(self.goal, 1)
        self.mic = None
        if mic is None:
            try:
                from dai_voice.qt import VoiceButton as mic
            except ImportError:            # no D.Ai Voice here: no microphone button
                mic = None
        if mic is not None:
            self.mic = mic()
            self.mic.transcribed.connect(self.from_voice)
            row.addWidget(self.mic)
        self.role = QComboBox()
        self.role.setAccessibleName(self.t("role"))
        for name, spec in ROLES.items():
            if name in self.allowed:
                self.role.addItem(pick(lang, *spec.title), name)
        self.role.setCurrentIndex(max(0, self.role.findData(role)))
        row.addWidget(self.role)
        outer.addLayout(row)
        row2 = QHBoxLayout()
        self.dry_run = QCheckBox(self.t("dry_run"))
        self.dry_run.setAccessibleName(self.t("dry_run"))
        self.dry_run.setChecked(services.dry_run)
        row2.addWidget(self.dry_run, 1)
        self.start_button = QPushButton(self.t("start"), objectName="Primary")
        self.start_button.setAccessibleName(self.t("start"))
        self.start_button.clicked.connect(self.start)
        row2.addWidget(self.start_button)
        outer.addLayout(row2)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        self.steps = QVBoxLayout(body)
        self.steps.setSpacing(8)
        self.steps.addStretch(1)
        self.scroll.setWidget(body)
        outer.addWidget(self.scroll, 1)

        self.final_box = QFrame(objectName="Final")
        fbox = QVBoxLayout(self.final_box)
        fbox.setContentsMargins(12, 10, 12, 10)
        self.final = QLabel("")
        self.final.setWordWrap(True)
        self.final.setAccessibleName(self.t("answer"))
        self.final.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        fbox.addWidget(self.final)
        self.run_line = QLabel("", objectName="Status")
        fbox.addWidget(self.run_line)
        self.final_box.hide()
        outer.addWidget(self.final_box)

        bottom = QHBoxLayout()
        self.privacy = QLabel(self.t("local") if provider == "local" else self.t("remote", p=provider), objectName="Status")
        self.privacy.setWordWrap(True)
        bottom.addWidget(self.privacy, 1)
        self.undo = QPushButton(self.t("undo"))
        self.undo.setAccessibleName(self.t("undo"))
        self.undo.setEnabled(False)
        self.undo.clicked.connect(self.undo_changes)
        bottom.addWidget(self.undo)
        self.copy = QPushButton(self.t("copy"))
        self.copy.setAccessibleName(self.t("copy"))
        self.copy.setEnabled(False)
        self.copy.clicked.connect(self.copy_answer)
        bottom.addWidget(self.copy)
        self.read = QPushButton(self.t("read"))
        self.read.setAccessibleName(self.t("read"))
        self.read.setEnabled(False)
        self.read.clicked.connect(self.read_aloud)
        bottom.addWidget(self.read)
        close = QPushButton(self.t("close"))
        close.setAccessibleName(self.t("close"))
        close.clicked.connect(self.close)
        bottom.addWidget(close)
        outer.addLayout(bottom)
        QShortcut(QKeySequence("Escape"), self, activated=self.close)
        (self.start_button if goal else self.goal).setFocus()

    def t(self, key: str, **kwargs: object) -> str:
        value = STRINGS[key]
        return pick(self.lang, *value).format(**kwargs)

    # -- the run ----------------------------------------------------------------

    @pyqtSlot(str)
    def from_voice(self, text: str) -> None:
        """The microphone filled the goal: start, and answer aloud when done."""
        text = " ".join(text.split())
        if not text or self.thread is not None:
            return
        self.goal.setText(text)
        self.spoken_goal = True
        self.start()

    def start(self) -> None:
        goal = self.goal.text().strip()
        if self.thread is not None or not goal:
            return
        if self.role.currentData() is None:
            self.status.setText(refusal("all", self.lang, self.root))
            return
        self.clear_steps()
        self.final_box.hide()
        self.copy.setEnabled(False)
        self.read.setEnabled(False)
        self.undo.setEnabled(False)
        self.run = None
        self.services.dry_run = self.dry_run.isChecked()
        self.services.assume_yes = False
        self.services.label = f"D.Ai Agent: {goal[:60]}"
        self.status.setText(self.t("working"))
        self.start_button.setEnabled(False)
        self.goal.setEnabled(False)
        self.role.setEnabled(False)
        self.dry_run.setEnabled(False)
        self.runner = Runner(goal, self.services, str(self.role.currentData()), self.chat, self.script, self.home)
        self.thread = QThread()
        self.runner.moveToThread(self.thread)
        self.runner.line.connect(self.add_line)
        self.runner.ask.connect(self.show_ask)
        self.runner.question.connect(self.show_question)
        self.runner.finished.connect(self.show_run)
        self.runner.failed.connect(self.show_failed)
        self.thread.started.connect(self.runner.run)
        self.thread.start()

    def clear_steps(self) -> None:
        while self.steps.count() > 1:
            item = self.steps.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.current = self.current_result = self.pending = None

    def _add(self, frame: QFrame) -> None:
        self.steps.insertWidget(self.steps.count() - 1, frame)
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()))

    @pyqtSlot(str)
    def add_line(self, text: str) -> None:
        """The loop's say(): a step line starts a card, indented lines are its result."""
        if text.startswith(("→ ", "⚠ ", "✗ ")):
            frame = QFrame(objectName="Step")
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(12, 8, 12, 8)
            head = QLabel(text.strip())
            head.setWordWrap(True)
            head.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(head)
            result = QLabel("", objectName="Result")
            result.setWordWrap(True)
            result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            result.hide()
            layout.addWidget(result)
            self.current, self.current_result = frame, result
            self._add(frame)
        elif self.current_result is not None:
            body = text.strip("\n")
            if body.startswith("  "):
                body = "\n".join(line[2:] if line.startswith("  ") else line for line in body.splitlines())
            self.current_result.setText((self.current_result.text() + "\n" if self.current_result.text() else "") + ltr(body))
            self.current_result.show()

    @pyqtSlot(object)
    def show_ask(self, info: dict[str, Any]) -> None:
        frame = QFrame(objectName="Ask")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        title = QLabel(self.t("asks", tool=info["tool"], args=json.dumps(info["args"], ensure_ascii=False)))
        title.setWordWrap(True)
        layout.addWidget(title)
        if info["error"]:
            err = QLabel(self.t("not_understood", error=info["error"]), objectName="Warn")
            err.setWordWrap(True)
            layout.addWidget(err)
        elif info["rows"]:
            rows = QLabel(self.t("plan") + "\n" + "\n".join(f"• {row}" for row in info["rows"]))
            rows.setWordWrap(True)
            layout.addWidget(rows)
        if info["weakens"]:
            layout.addWidget(QLabel(self.t("weakens"), objectName="Warn"))
        if info["system"]:
            note = QLabel(self.t("system"), objectName="Status")
            note.setWordWrap(True)
            layout.addWidget(note)
        buttons = QHBoxLayout()
        allow = QPushButton(embed(self.t("allow"), self.lang), objectName="Primary")
        allow.setAccessibleName(self.t("allow"))
        allow.setEnabled(not info["error"])
        skip = QPushButton(embed(self.t("skip"), self.lang))
        skip.setAccessibleName(self.t("skip"))
        verdict = QLabel("", objectName="Status")
        allow.clicked.connect(lambda: self.answer(True, allow, skip, verdict))
        skip.clicked.connect(lambda: self.answer(False, allow, skip, verdict))
        buttons.addWidget(allow)
        buttons.addWidget(skip)
        buttons.addWidget(verdict, 1)
        layout.addLayout(buttons)
        self.pending = frame
        self._add(frame)
        skip.setFocus() if info["weakens"] else allow.setFocus()

    @pyqtSlot(str)
    def show_question(self, question: str) -> None:
        frame = QFrame(objectName="Ask")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        title = QLabel(self.t("question", q=question))
        title.setWordWrap(True)
        layout.addWidget(title)
        field = QLineEdit()
        field.setPlaceholderText(self.t("answer_field"))
        field.setAccessibleName(self.t("answer_field"))
        layout.addWidget(field)
        buttons = QHBoxLayout()
        send = QPushButton(embed(self.t("send_answer"), self.lang), objectName="Primary")
        send.setAccessibleName(self.t("send_answer"))
        skip = QPushButton(embed(self.t("no_answer"), self.lang))
        skip.setAccessibleName(self.t("no_answer"))
        verdict = QLabel("", objectName="Status")

        def done(said: str | None) -> None:
            if self.runner is None or self.pending is None:
                return
            send.setEnabled(False)
            skip.setEnabled(False)
            field.setEnabled(False)
            verdict.setText(self.t("answered") if said else self.t("skipped"))
            self.pending = None
            self.runner.reply_text(said)
        send.clicked.connect(lambda: done(field.text().strip() or None))
        field.returnPressed.connect(lambda: done(field.text().strip() or None))
        skip.clicked.connect(lambda: done(None))
        buttons.addWidget(send)
        buttons.addWidget(skip)
        buttons.addWidget(verdict, 1)
        layout.addLayout(buttons)
        self.pending = frame
        self._add(frame)
        field.setFocus()

    def undo_changes(self) -> None:
        from .agent import undo_run
        if self.run is None or self.thread is not None:
            return
        ok, lines = undo_run(self.home, self.run.id, self.services.run, self.lang)
        self.undo.setEnabled(False)
        self.status.setText(self.t("undone") if ok else self.t("undo_failed", lines="; ".join(lines)))

    def answer(self, allowed: bool, allow: QPushButton, skip: QPushButton, verdict: QLabel) -> None:
        if self.runner is None or self.pending is None:
            return
        allow.setEnabled(False)
        skip.setEnabled(False)
        verdict.setText(self.t("allowed") if allowed else self.t("skipped"))
        verdict.setObjectName("Ok" if allowed else "Status")
        self.pending = None
        self.runner.reply(allowed)

    @pyqtSlot(object)
    def show_run(self, run: Run) -> None:
        self.run = run
        self.final.setText(run.final)
        self.run_line.setText(self.t("run_id", id=run.id))
        self.final_box.show()
        self.copy.setEnabled(True)
        self.read.setEnabled(bool(run.final))
        self.undo.setEnabled(any(step.entry for step in run.steps))
        self.status.setText(pick(self.lang, *STRINGS["status"].get(run.status, STRINGS["status"]["done"])))
        self._ended()
        if run.final and (self.speak or self.spoken_goal):
            self.read_aloud()
        self.spoken_goal = False

    @pyqtSlot(str)
    def show_failed(self, error: str) -> None:
        self.final.setText(self.t("failed", error=error))
        self.run_line.setText("")
        self.final_box.show()
        self.status.setText(pick(self.lang, *STRINGS["status"]["failed"]))
        self._ended()

    def _ended(self) -> None:
        self.start_button.setEnabled(True)
        self.goal.setEnabled(True)
        self.role.setEnabled(True)
        self.dry_run.setEnabled(True)
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait(8000)
            self.thread = None
        self.runner = None
        self.pending = None

    # -- the answer -------------------------------------------------------------

    def copy_answer(self) -> None:
        QApplication.clipboard().setText(self.final.text())

    def read_aloud(self) -> None:
        if self.final.text():
            self.spawn(["dai-speak", "--stdin", "--lang", self.lang], self.final.text())

    def texts(self) -> str:
        """Everything on the cards (tests)."""
        out = []
        for i in range(self.steps.count()):
            widget = self.steps.itemAt(i).widget()
            if widget is not None:
                out += [label.text() for label in widget.findChildren(QLabel)]
        if not self.final_box.isHidden():
            out.append(self.final.text())
        return "\n".join(out)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt
        if self.runner is not None:
            self.runner.release()
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait(8000)
            self.thread = None
        event.accept()


def _spawn(argv: list[str], stdin_text: str | None = None) -> None:
    """Start a program detached; text goes through its standard input, never on a command line."""
    try:
        child = subprocess.Popen(argv, stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        if stdin_text is not None and child.stdin is not None:
            try:
                child.stdin.write(stdin_text.encode("utf-8"))
                child.stdin.close()
            except OSError:
                pass
    except OSError as exc:
        print(f"dai-agent: cannot start {argv[0]}: {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """dai-agent window ["goal"] [--role ROLE] [--lang LANG] [--speak]"""
    argv = list(sys.argv if argv is None else argv)
    args = argv[1:]
    if "--version" in args:
        print(f"dai-agent {__version__} — {__author__}")
        return 0
    lang = ui_lang()
    role = "all"
    words = []
    skip = False
    for i, a in enumerate(args):
        if skip:
            skip = False
            continue
        if a in ("--role", "--lang") and i + 1 < len(args):
            if a == "--role":
                role = args[i + 1]
            else:
                lang = args[i + 1]
            skip = True
            continue
        if a == "--speak":
            continue
        if a.startswith("--"):
            print(__doc__.strip(), file=sys.stderr)
            return 2
        words.append(a)
    if role not in ROLES:
        print(pick(lang, "✗ unknown role; see: dai-agent roles", "✗ תפקיד לא מוכר; ראו: dai-agent roles"), file=sys.stderr)
        return 2
    if (why := refusal(role, lang)):
        print(f"✗ {why}", file=sys.stderr)
        return 2
    app = QApplication.instance() or QApplication(argv[:1])
    app.setApplicationName(APP_ID)
    app.setDesktopFileName(APP_ID)
    if (font := app_font()) is not None:
        app.setFont(font)
    app.setStyleSheet(with_touch(STYLE))
    from dai_tune.context import Context
    services = Services(ctx=Context(lang=lang), lang=lang)
    provider = "local"
    try:
        from dai_ai.client import where
        provider = where("general")
    except Exception:  # noqa: BLE001 - no dai_ai: local
        pass
    window = AgentWindow(lang, services, goal=" ".join(words).strip(), role=role, provider=provider, speak="--speak" in args)
    window.show()
    if window.goal.text().strip():
        window.start()
    return app.exec()
