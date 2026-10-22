# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The D.Ai Settings window (docs/BEYOND.md §6).

  list of settings (search, groups) ──► a change ──► the plan (what, scope, risk, effect) ──► Apply ──► done (Undo)

Every control is a D.Ai Tune action: the plan comes from dai_tune.planner, the change goes through the same
root helper (polkit) and journal as "dai-tune", and the window shows the value read back from the system,
not the one asked for. The security score at the top is dai_tune.posture's.
"""
from __future__ import annotations

import contextlib
import io
import sys
from typing import Any, Callable

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont, QFontDatabase, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QStackedWidget, QVBoxLayout, QWidget,
)

from dai_i18n import pick, qt_direction, text as i18n_text, ui_lang
from dai_style import color, controls, rgba, with_touch
from dai_style.panes import fit_width, touch_scrolling
from dai_tune.catalog import CATALOG
from dai_tune.cli import apply_plan, cmd_undo
from dai_tune.context import Context
from dai_tune.planner import Plan, build_plan
from dai_tune.posture import assess, title as check_title

from . import __author__, __version__
from .model import GROUPS, SETTINGS, Setting, Value, matches

APP_ID = "dai-settings"

BG_900, BG_800, SURFACE, BORDER = color("bg_900"), color("bg_800"), color("surface"), color("border")
TEXT, MUTED, ACCENT, ACCENT_STRONG = color("text"), color("muted"), color("accent"), color("accent_strong")
ACCENT_2, ACCENT_SOFT, DEEP, PANEL = color("accent_2"), color("accent_soft"), color("deep"), color("panel")
OK_GREEN, WARN_AMBER, DANGER, DISABLED = color("ok"), color("warn"), color("danger"), color("disabled")

STYLE = f"""
QWidget#Settings {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {BG_900}, stop:1 {DEEP}); }}
QWidget {{ color: {TEXT}; font-size: 11pt; }}
QLabel#Title {{ font-size: 20pt; font-weight: 700; }}
QLabel#Muted {{ color: {MUTED}; }}
QLabel#Section {{ color: {ACCENT_SOFT}; font-weight: 700; font-size: 10pt; letter-spacing: 1px; }}
QLabel#Score {{ font-size: 13pt; font-weight: 700; }}
QFrame#Card {{ background: {rgba('bg_800', 0.92)}; border: 1px solid {BORDER}; border-radius: 14px; }}
QFrame#Row {{ background: {BG_800}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame#Step {{ background: {BG_800}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame#Warn {{ background: {rgba('warn', 0.10)}; border: 1px solid {WARN_AMBER}; border-radius: 12px; }}
QLineEdit {{ background: {BG_900}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 10px; }}
QLineEdit:focus {{ border: 2px solid {ACCENT_2}; }}
QComboBox {{ background: {BG_900}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 10px; min-width: 160px; }}
QComboBox:focus {{ border: 2px solid {ACCENT_2}; }}
QComboBox QAbstractItemView {{ background: {BG_800}; color: {TEXT}; selection-background-color: {ACCENT_STRONG}; }}
QPushButton {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; padding: 8px 16px; }}
QPushButton:hover {{ border: 1px solid {ACCENT}; background: {rgba('accent', 0.18)}; }}
QPushButton:focus {{ border: 2px solid {ACCENT_2}; }}
QPushButton:disabled {{ color: {DISABLED}; border: 1px solid {BORDER}; background: {BG_800}; }}
QPushButton#Primary {{ color: #FFFFFF; font-weight: 700; border: none;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT_STRONG}, stop:1 {PANEL}); }}
QPushButton#Primary:hover {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT}, stop:1 {ACCENT_2}); }}
QPushButton#Primary:disabled {{ background: {SURFACE}; color: {DISABLED}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; height: 0; }}
QFrame#Actions {{ border-top: 1px solid {BORDER}; }}
""" + controls()

STRINGS = {
    "title": ("D.Ai Settings", "הגדרות D.Ai"),
    "subtitle": ("Every change shows its plan first, goes through D.Ai Tune, and can be undone.",
                 "כל שינוי מראה קודם את התוכנית, עובר דרך D.Ai Tune, ואפשר לבטל אותו."),
    "search": ("Search settings", "חיפוש בהגדרות"),
    "search_hint": ("Search: lock, theme, language…", "חיפוש: נעילה, ערכת נושא, שפה…"),
    "no_match": ("Nothing matches. Everything else is a sentence away: dai-tune help",
                 "אין התאמה. כל השאר במרחק משפט: dai-tune help"),
    "score": ("Security {score}/100", "אבטחה {score}/100"),
    "not_admin": ("Only an administrator can change the system's settings; your own account's settings still work.",
                  "רק מנהל המחשב יכול לשנות הגדרות מערכת; ההגדרות של החשבון שלכם עובדות."),
    "on": ("on", "פועל"),
    "off": ("off", "כבוי"),
    "turn_on": ("Turn on", "הפעלה"),
    "run": ("Run", "הרצה"),
    "change": ("Change", "שינוי"),
    "plan_of": ("WHAT WILL HAPPEN", "מה יקרה"),
    "apply": ("Apply", "החלה"),
    "cancel": ("Cancel", "ביטול"),
    "back": ("Back to settings", "חזרה להגדרות"),
    "undo": ("Undo", "ביטול השינוי"),
    "undo_last": ("Undo the last change", "ביטול השינוי האחרון"),
    "weakens": ("This weakens security. Type \"yes\" to continue.", "זה מחליש את האבטחה. כתבו „כן” כדי להמשיך."),
    "applying": ("Applying. Enter the administrator password when asked.", "מחיל. הזינו את סיסמת המנהל כשתתבקשו."),
    "done": ("Done", "בוצע"),
    "done_text": ("The setting is in place. D.Ai Tune recorded it; Undo puts it back.",
                  "ההגדרה במקום. D.Ai Tune רשם אותה; „ביטול השינוי” מחזיר אותה."),
    "undone": ("Undone.", "בוטל."),
    "failed": ("That did not work", "זה לא עבד"),
    "try_again": ("Back", "חזרה"),
    "nothing": ("No change: that is already the value.", "אין שינוי: זה כבר הערך."),
    "scope_user": ("your account", "החשבון שלך"),
    "scope_system": ("system", "מערכת"),
    "risk_low": ("low risk", "סיכון נמוך"),
    "risk_medium": ("medium risk", "סיכון בינוני"),
    "risk_high": ("high risk", "סיכון גבוה"),
    "effect_hardens": ("hardens security", "מחזק אבטחה"),
    "effect_weakens": ("weakens security", "מחליש אבטחה"),
    "effect_neutral": ("neutral", "ניטרלי"),
}
EFFECT_ICON = {"hardens": "🛡", "weakens": "⚠", "neutral": "•"}


class Worker(QObject):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self.fn = fn

    @pyqtSlot()
    def run(self) -> None:
        try:
            self.finished.emit(self.fn())
        except Exception as exc:  # noqa: BLE001 - shown to the person, never a crash
            self.failed.emit(str(exc))


def is_admin() -> bool:
    from dai_forge.cli import is_admin as forge_admin  # the same rule as D.Ai Forge
    return forge_admin()


class SettingsWindow(QWidget):
    def __init__(self, lang: str, ctx: Context | None = None, admin: bool | None = None) -> None:
        super().__init__(objectName="Settings")
        self.lang = lang
        self.ctx = ctx or Context(lang=lang)
        try:
            self.admin = is_admin() if admin is None else admin
        except Exception:  # noqa: BLE001 - no group database: treat as not an administrator
            self.admin = False
        self.values: dict[str, Value] = {}
        self.plan: Plan | None = None
        self.pending: tuple[Setting, Value] | None = None
        self.last_entry = ""
        self.threads: list[tuple[QThread, Worker]] = []
        self.controls: dict[str, QWidget] = {}
        self.setWindowTitle(self.t("title"))
        self.setLayoutDirection(qt_direction(lang))
        self.setMinimumSize(fit_width(560), 420)
        self.resize(fit_width(760), 640)
        self.setStyleSheet(with_touch(STYLE))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 18)
        outer.setSpacing(10)
        head = QHBoxLayout()
        logo = QLabel("◆")
        logo.setStyleSheet(f"color: {ACCENT}; font-size: 28pt;")
        head.addWidget(logo)
        titles = QVBoxLayout()
        titles.addWidget(QLabel(self.t("title"), objectName="Title"))
        sub = QLabel(self.t("subtitle"), objectName="Muted")
        sub.setWordWrap(True)
        titles.addWidget(sub)
        head.addLayout(titles, 1)
        outer.addLayout(head)
        self.pages = QStackedWidget()
        outer.addWidget(self.pages, 1)
        QShortcut(QKeySequence("Escape"), self, activated=self._escape)
        self.show_list()

    def t(self, key: str, **kwargs: object) -> str:
        return i18n_text(self.lang, *STRINGS[key], **kwargs) if kwargs else pick(self.lang, *STRINGS[key])

    # -- pages ----------------------------------------------------------------

    def _page(self) -> tuple[QVBoxLayout, QHBoxLayout]:
        while self.pages.count():
            widget = self.pages.widget(0)
            self.pages.removeWidget(widget)
            widget.deleteLater()
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 4, 6, 4)
        layout.setSpacing(10)
        scroll.setWidget(inner)
        touch_scrolling(scroll)
        outer.addWidget(scroll, 1)
        bar = QFrame(objectName="Actions")
        actions = QHBoxLayout(bar)
        actions.setContentsMargins(0, 10, 0, 0)
        actions.addStretch(1)
        outer.addWidget(bar)
        self.pages.addWidget(page)
        return layout, actions

    def _card(self, layout: QVBoxLayout, name: str = "Card") -> QVBoxLayout:
        frame = QFrame(objectName=name)
        inner = QVBoxLayout(frame)
        inner.setContentsMargins(16, 12, 16, 12)
        inner.setSpacing(6)
        layout.addWidget(frame)
        return inner

    def _wrap(self, text: str, name: str = "") -> QLabel:
        label = QLabel(text, objectName=name) if name else QLabel(text)
        label.setWordWrap(True)
        return label

    def _button(self, actions: QHBoxLayout, text: str, slot: Callable[[], None], primary: bool = False) -> QPushButton:
        button = QPushButton(text, objectName="Primary" if primary else "")
        button.setAccessibleName(text)
        button.clicked.connect(slot)
        actions.addWidget(button)
        return button

    # -- the list -------------------------------------------------------------

    def show_list(self, query: str = "") -> None:
        self.values = self._read_all()
        layout, actions = self._page()
        score, checks = self._score()
        card = self._card(layout)
        row = QHBoxLayout()
        label = QLabel(self.t("score", score=score), objectName="Score")
        label.setStyleSheet(f"color: {OK_GREEN if score >= 80 else (WARN_AMBER if score >= 50 else DANGER)};")
        row.addWidget(label, 1)
        card.addLayout(row)
        for check in checks:
            if not check.ok:
                card.addWidget(self._wrap("✗ " + check_title(check, self.lang), "Muted"))
        if not self.admin:
            card.addWidget(self._wrap(self.t("not_admin"), "Muted"))

        self.search = QLineEdit(query)
        self.search.setPlaceholderText(self.t("search_hint"))
        self.search.setAccessibleName(self.t("search"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)

        self.controls = {}
        self.rows: dict[str, QFrame] = {}
        self.sections: dict[str, QLabel] = {}
        for group, names in GROUPS.items():
            section = QLabel(pick(self.lang, *names).upper(), objectName="Section")
            self.sections[group] = section
            layout.addWidget(section)
            for setting in (s for s in SETTINGS if s.group == group):
                value = self.values.get(setting.key)
                if value is None and setting.kind != "button":
                    continue  # not on this computer
                self.rows[setting.key] = self._row(layout, setting, value)
        self.empty = self._wrap(self.t("no_match"), "Muted")
        self.empty.setVisible(False)
        layout.addWidget(self.empty)
        layout.addStretch(1)
        if self.last_entry:
            self._button(actions, self.t("undo_last"), self.undo)
        self._filter(query)
        self.search.setFocus()

    def _row(self, layout: QVBoxLayout, setting: Setting, value: Value) -> QFrame:
        frame = QFrame(objectName="Row")
        box = QVBoxLayout(frame)
        box.setContentsMargins(14, 10, 14, 10)
        line = QHBoxLayout()
        title = QLabel(f"<b>{setting.label(self.lang)}</b>")
        title.setWordWrap(True)
        line.addWidget(title, 1)
        name = setting.label(self.lang)
        enabled = self.admin or setting.scope() != "system"
        if setting.kind == "toggle":
            if setting.on_only and not value:
                control = QPushButton(self.t("turn_on"))
                control.clicked.connect(lambda _c, s=setting: self.change(s, True))
            elif setting.on_only:
                control = QLabel(self.t("on"))
            else:
                control = QCheckBox(self.t("on") if value else self.t("off"))
                control.setChecked(bool(value))
                control.clicked.connect(lambda checked, s=setting: self.change(s, bool(checked)))
            control.setAccessibleName(name)
        elif setting.kind == "choice":
            control = QComboBox()
            control.setAccessibleName(name)
            for candidate, names in setting.choices:
                control.addItem(pick(self.lang, *names), candidate)
            index = control.findData(value)
            if index < 0:
                control.addItem(str(value), value)
                index = control.count() - 1
            control.setCurrentIndex(index)
            control.activated.connect(lambda i, s=setting, c=control: self.change(s, c.itemData(i)))
        elif setting.kind == "text":
            control = QWidget()
            inner = QHBoxLayout(control)
            inner.setContentsMargins(0, 0, 0, 0)
            field = QLineEdit(str(value or ""))
            field.setPlaceholderText(setting.placeholder)
            field.setAccessibleName(name)
            change = QPushButton(self.t("change"))
            change.setAccessibleName(f"{self.t('change')}: {name}")
            change.clicked.connect(lambda _c, s=setting, f=field: self.change(s, f.text().strip()))
            field.returnPressed.connect(change.click)
            inner.addWidget(field, 1)
            inner.addWidget(change)
            field.setEnabled(enabled)
            change.setEnabled(enabled)
        else:
            control = QPushButton(self.t("run"))
            control.setAccessibleName(f"{self.t('run')}: {name}")
            control.clicked.connect(lambda _c, s=setting: self.change(s, True))
        if setting.kind != "text":
            control.setEnabled(enabled)
        line.addWidget(control)
        box.addLayout(line)
        if setting.hint[0]:
            box.addWidget(self._wrap(pick(self.lang, *setting.hint), "Muted"))
        self.controls[setting.key] = control
        layout.addWidget(frame)
        return frame

    def _filter(self, query: str) -> None:
        shown_groups: set[str] = set()
        for setting in SETTINGS:
            frame = self.rows.get(setting.key)
            if frame is None:
                continue
            visible = matches(setting, query, self.lang)
            frame.setVisible(visible)
            if visible:
                shown_groups.add(setting.group)
        for group, section in self.sections.items():
            section.setVisible(group in shown_groups)
        self.empty.setVisible(not shown_groups)

    def _read_all(self) -> dict[str, Value]:
        from .model import snapshot
        return snapshot(self.ctx)

    def _score(self):
        try:
            return assess(self.ctx, self.lang)
        except Exception:  # noqa: BLE001 - the score is information, never a reason to fail
            return 0, []

    # -- a change: plan, confirm, apply ----------------------------------------

    def change(self, setting: Setting, value: Value) -> None:
        if setting.kind != "button" and value == self.values.get(setting.key):
            self.show_message(self.t("nothing"))
            return
        requests = setting.request(value)
        if not requests:
            return
        self.pending = (setting, value)
        self.plan = build_plan(requests, self.ctx)
        layout, actions = self._page()
        card = self._card(layout)
        shown = setting.choice_label(str(value), self.lang) if setting.kind == "choice" else (
            (self.t("on") if value else self.t("off")) if setting.kind == "toggle" else str(value))
        card.addWidget(QLabel(f"<span style='font-size:15pt; font-weight:700'>{setting.label(self.lang)}"
                              + (f": {shown}" if setting.kind != "button" else "") + "</span>"))
        layout.addWidget(QLabel(self.t("plan_of"), objectName="Section"))
        for step in self.plan.steps:
            spec = CATALOG[step.action]
            step_card = self._card(layout, "Step")
            step_card.addWidget(self._wrap(f"{EFFECT_ICON[step.effect]} <b>{spec.summary(step.params, self.lang)}</b>"))
            tags = " · ".join([self.t(f"scope_{step.scope}"), self.t(f"risk_{step.risk}"), self.t(f"effect_{step.effect}")])
            step_card.addWidget(self._wrap(tags, "Muted"))
            note = spec.note(step.params, self.lang)
            if note:
                step_card.addWidget(self._wrap("↳ " + note, "Muted"))
        for problem in [*self.plan.errors, *self.plan.unknown]:
            layout.addWidget(self._wrap(f"<span style='color:{DANGER}'>✗ {problem}</span>"))
        self.confirm_field: QLineEdit | None = None
        if self.plan.weakens:
            warn = self._card(layout, "Warn")
            warn.addWidget(self._wrap("⚠ " + self.t("weakens")))
            self.confirm_field = QLineEdit()
            self.confirm_field.setAccessibleName(self.t("weakens"))
            self.confirm_field.textChanged.connect(self._update_apply)
            warn.addWidget(self.confirm_field)
        layout.addStretch(1)
        self._button(actions, self.t("cancel"), lambda: self.show_list())
        self.apply_button = self._button(actions, self.t("apply"), self.apply, primary=True)
        self._update_apply()
        (self.confirm_field or self.apply_button).setFocus()

    def _update_apply(self, *_args) -> None:
        ok = bool(self.plan and self.plan.ok)
        if any(CATALOG[s.action].scope == "system" for s in (self.plan.steps if self.plan else [])):
            ok = ok and self.admin
        if self.confirm_field is not None:
            ok = ok and self.confirm_field.text().strip().casefold() in ("yes", "כן")
        self.apply_button.setEnabled(ok)

    def apply(self) -> None:
        if not self.apply_button.isEnabled() or self.plan is None or self.pending is None:
            return
        plan, (setting, _value) = self.plan, self.pending
        label = f"Settings: {setting.key}"
        self.show_working(self.t("applying"))
        self._run(lambda: apply_plan(plan, self.ctx, label), self.applied)

    def applied(self, result) -> None:
        if not result.ok:
            self.show_error(result.error)
            return
        self.last_entry = result.entry_id
        layout, actions = self._page()
        card = self._card(layout)
        card.addWidget(QLabel(f"<span style='font-size:17pt; font-weight:700; color:{OK_GREEN}'>{self.t('done')}</span>"))
        card.addWidget(self._wrap(self.t("done_text"), "Muted"))
        layout.addStretch(1)
        self._button(actions, self.t("undo"), self.undo)
        back = self._button(actions, self.t("back"), lambda: self.show_list(), primary=True)
        back.setFocus()

    def undo(self) -> None:
        entry = self.last_entry or "last"

        def work():
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                status = cmd_undo(entry, self.ctx)
            if status != 0:
                raise RuntimeError(out.getvalue().strip() or "undo failed")
            return out.getvalue()

        self.show_working(self.t("applying"))
        self._run(work, lambda _out: (setattr(self, "last_entry", ""), self.show_message(self.t("undone"))))

    # -- status pages -------------------------------------------------------------

    def show_working(self, text: str) -> None:
        layout, _actions = self._page()
        layout.addStretch(1)
        spinner = QLabel("✦")
        spinner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        spinner.setStyleSheet(f"color: {ACCENT}; font-size: 40pt;")
        layout.addWidget(spinner)
        message = self._wrap(text)
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(message)
        layout.addStretch(2)

    def show_message(self, text: str) -> None:
        layout, actions = self._page()
        card = self._card(layout)
        card.addWidget(self._wrap(f"<span style='font-size:15pt; font-weight:700; color:{OK_GREEN}'>{text}</span>"))
        layout.addStretch(1)
        back = self._button(actions, self.t("back"), lambda: self.show_list(), primary=True)
        back.setFocus()

    @pyqtSlot(str)
    def show_error(self, text: str) -> None:
        layout, actions = self._page()
        card = self._card(layout, "Warn")
        card.addWidget(QLabel(f"<span style='font-size:15pt; font-weight:700; color:{DANGER}'>{self.t('failed')}</span>"))
        card.addWidget(self._wrap(text))
        layout.addStretch(1)
        back = self._button(actions, self.t("try_again"), lambda: self.show_list(), primary=True)
        back.setFocus()

    # -- threads -------------------------------------------------------------------

    def _run(self, fn: Callable[[], Any], done: Callable[[Any], None]) -> None:
        thread, worker = QThread(self), Worker(fn)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(done)
        worker.failed.connect(self.show_error)
        for signal in (worker.finished, worker.failed):
            signal.connect(thread.quit)
        thread.finished.connect(lambda: self._forget(thread))
        self.threads.append((thread, worker))
        thread.start()

    def _forget(self, thread: QThread) -> None:
        self.threads = [(t, w) for t, w in self.threads if t is not thread]

    def _escape(self) -> None:
        if self.pages.count() and self.plan is not None and self.pending is not None:
            self.plan, self.pending = None, None
            self.show_list()
        else:
            self.close()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--version" in argv:
        print(f"dai-settings {__version__} — {__author__}")
        return 0
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName(APP_ID)
    app.setDesktopFileName(APP_ID)
    if "Noto Sans" in QFontDatabase.families():
        app.setFont(QFont("Noto Sans", 11))
    app.setStyleSheet(with_touch(STYLE))
    window = SettingsWindow(ui_lang())
    window.show()
    return app.exec()
