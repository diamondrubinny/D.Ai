# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The D.Ai Store window (docs/BEYOND.md §9).

  search + categories ──► cards (what it does, what it sets up) ──► Set up ──► the plan ──► polkit ──► done (Undo)

No account, no ratings, no telemetry: the recipes are D.Ai Forge's, the apps are Flathub's own index, and
setting something up is the same plan, root helper and journal as "dai-tune".
"""
from __future__ import annotations

import contextlib
import io
import sys
from typing import Any, Callable

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont, QFontDatabase, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout,
    QWidget,
)

from dai_i18n import pick, qt_direction, text as i18n_text, ui_lang
from dai_style import color, rgba, with_touch
from dai_style.panes import WrapRow, fit_width, touch_scrolling
from dai_tune.catalog import CATALOG
from dai_tune.cli import apply_plan, cmd_undo
from dai_tune.context import Context
from dai_tune.planner import Plan, build_plan

from . import __author__, __version__
from .catalog import CATEGORIES, Item, flathub_search, installed_flatpaks, recipe_items, search

APP_ID = "dai-store"

BG_900, BG_800, SURFACE, BORDER = color("bg_900"), color("bg_800"), color("surface"), color("border")
TEXT, MUTED, ACCENT, ACCENT_STRONG = color("text"), color("muted"), color("accent"), color("accent_strong")
ACCENT_2, ACCENT_SOFT, DEEP, PANEL = color("accent_2"), color("accent_soft"), color("deep"), color("panel")
OK_GREEN, WARN_AMBER, DANGER, DISABLED = color("ok"), color("warn"), color("danger"), color("disabled")

STYLE = f"""
QWidget#Store {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {BG_900}, stop:1 {DEEP}); }}
QWidget {{ color: {TEXT}; font-size: 11pt; }}
QLabel#Title {{ font-size: 20pt; font-weight: 700; }}
QLabel#Muted {{ color: {MUTED}; }}
QLabel#Section {{ color: {ACCENT_SOFT}; font-weight: 700; font-size: 10pt; letter-spacing: 1px; }}
QLabel#Badge {{ background: {SURFACE}; border-radius: 9px; padding: 3px 11px; color: {ACCENT_SOFT}; }}
QFrame#Card {{ background: {rgba('bg_800', 0.92)}; border: 1px solid {BORDER}; border-radius: 14px; }}
QFrame#Step {{ background: {BG_800}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame#Warn {{ background: {rgba('warn', 0.10)}; border: 1px solid {WARN_AMBER}; border-radius: 12px; }}
QLineEdit {{ background: {BG_900}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 10px; }}
QLineEdit:focus {{ border: 2px solid {ACCENT_2}; }}
QPushButton {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; padding: 8px 16px; }}
QPushButton:hover {{ border: 1px solid {ACCENT}; background: {rgba('accent', 0.18)}; }}
QPushButton:focus {{ border: 2px solid {ACCENT_2}; }}
QPushButton:disabled {{ color: {DISABLED}; border: 1px solid {BORDER}; background: {BG_800}; }}
QPushButton#Primary {{ color: #FFFFFF; font-weight: 700; border: none;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT_STRONG}, stop:1 {PANEL}); }}
QPushButton#Primary:hover {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT}, stop:1 {ACCENT_2}); }}
QPushButton#Primary:disabled {{ background: {SURFACE}; color: {DISABLED}; }}
QPushButton#Chip {{ border-radius: 15px; padding: 6px 14px; background: {rgba('surface', 0.85)}; }}
QPushButton#Chip:checked {{ background: {BG_900}; border: 2px solid {ACCENT_2}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; height: 0; }}
QFrame#Actions {{ border-top: 1px solid {BORDER}; }}
"""

STRINGS = {
    "title": ("D.Ai Store", "חנות D.Ai"),
    "subtitle": ("What it does and what it sets up, shown before anything changes. No account, nothing sent.",
                 "מה זה עושה ומה זה מקים, מוצג לפני שמשהו משתנה. בלי חשבון, שום דבר לא נשלח."),
    "search": ("Search", "חיפוש"),
    "search_hint": ("Search: messenger, office, vpn…", "חיפוש: מסנג'ר, אופיס, vpn…"),
    "all": ("All", "הכול"),
    "flathub": ("Search Flathub", "חיפוש ב־Flathub"),
    "flathub_note": ("Flathub's own index, as flatpak keeps it on this computer; flatpak refreshes it from Flathub when it is a day old.",
                     "המפתח של Flathub כפי ש־flatpak שומר אותו במחשב; flatpak מרענן אותו מ־Flathub כשהוא בן יום."),
    "flathub_none": ("Nothing on Flathub for that, or Flathub is not set up yet (it is in \"More\").",
                     "אין כלום ב־Flathub בשביל זה, או ש־Flathub עדיין לא מוגדר (הוא ב„עוד”)."),
    "no_match": ("Nothing matches. Ask D.Ai Forge for anything else: Super+B.", "אין התאמה. כל דבר אחר מ־D.Ai Forge: ‏Super+B."),
    "sets_up": ("Sets up:", "מקים:"),
    "installed": ("installed", "מותקן"),
    "setup": ("Set up", "להקים"),
    "not_admin": ("Only an administrator can set software up; you can look.", "רק מנהל המחשב יכול להקים תוכנות. אפשר לעיין."),
    "plan_of": ("WHAT WILL HAPPEN", "מה יקרה"),
    "apply": ("Set up", "להקים"),
    "cancel": ("Cancel", "ביטול"),
    "back": ("Back to the store", "חזרה לחנות"),
    "undo": ("Undo", "ביטול ההקמה"),
    "weakens": ("This weakens security. Type \"yes\" to continue.", "זה מחליש את האבטחה. כתבו „כן” כדי להמשיך."),
    "applying": ("Setting it up. Enter the administrator password when asked.", "מקים. הזינו את סיסמת המנהל כשתתבקשו."),
    "done": ("Done", "בוצע"),
    "done_text": ("It is set up and in the menu. D.Ai Tune recorded every step; Undo removes them.",
                  "הוקם ונמצא בתפריט. D.Ai Tune רשם כל צעד; „ביטול ההקמה” מסיר אותם."),
    "undone": ("Undone.", "בוטל."),
    "failed": ("That did not work", "זה לא עבד"),
    "try_again": ("Back", "חזרה"),
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
    from dai_forge.cli import is_admin as forge_admin
    return forge_admin()


class StoreWindow(QWidget):
    def __init__(self, lang: str, ctx: Context | None = None, admin: bool | None = None, items: list[Item] | None = None,
                 flathub: Callable[[str], list[Item]] = flathub_search, installed: Callable[[], set[str]] = installed_flatpaks) -> None:
        super().__init__(objectName="Store")
        self.lang = lang
        self.ctx = ctx or Context(lang=lang)
        try:
            self.admin = is_admin() if admin is None else admin
        except Exception:  # noqa: BLE001
            self.admin = False
        self.items = items if items is not None else recipe_items()
        self.flathub = flathub
        self.installed = installed
        self.category = ""
        self.plan: Plan | None = None
        self.pending: Item | None = None
        self.last_entry = ""
        self.threads: list[tuple[QThread, Worker]] = []
        self.setWindowTitle(self.t("title"))
        self.setLayoutDirection(qt_direction(lang))
        self.setMinimumSize(fit_width(560), 420)
        self.resize(fit_width(820), 660)
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
        self.show_store()

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
        label.setTextFormat(Qt.TextFormat.RichText if "<" in text else Qt.TextFormat.PlainText)
        return label

    def _button(self, actions: QHBoxLayout, text: str, slot: Callable[[], None], primary: bool = False) -> QPushButton:
        button = QPushButton(text, objectName="Primary" if primary else "")
        button.setAccessibleName(text)
        button.clicked.connect(slot)
        actions.addWidget(button)
        return button

    # -- the store ------------------------------------------------------------

    def show_store(self, query: str = "", flathub_items: list[Item] | None = None) -> None:
        layout, actions = self._page()
        if not self.admin:
            layout.addWidget(self._wrap("ℹ " + self.t("not_admin"), "Muted"))
        row = QHBoxLayout()
        self.search = QLineEdit(query)
        self.search.setPlaceholderText(self.t("search_hint"))
        self.search.setAccessibleName(self.t("search"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self._render())
        row.addWidget(self.search, 1)
        flathub = QPushButton(self.t("flathub"))
        flathub.setAccessibleName(self.t("flathub"))
        flathub.setToolTip(self.t("flathub_note"))
        flathub.clicked.connect(self.search_flathub)
        row.addWidget(flathub)
        layout.addLayout(row)

        chips = QWidget()
        flow = WrapRow(chips)
        self.chips: dict[str, QPushButton] = {}
        for key, names in (("", (STRINGS["all"])), *CATEGORIES.items()):
            chip = QPushButton(pick(self.lang, *names), objectName="Chip")
            chip.setCheckable(True)
            chip.setChecked(key == self.category)
            chip.setAccessibleName(pick(self.lang, *names))
            chip.clicked.connect(lambda _c, k=key: self.pick_category(k))
            flow.addWidget(chip)
            self.chips[key] = chip
        layout.addWidget(chips)

        self.list_layout = QVBoxLayout()
        self.list_layout.setSpacing(10)
        layout.addLayout(self.list_layout)
        self.empty = self._wrap(self.t("no_match"), "Muted")
        layout.addWidget(self.empty)
        layout.addStretch(1)
        self.flathub_items = flathub_items or []
        self.installed_apps = self.installed() if self.flathub_items else set()
        if self.last_entry:
            self._button(actions, self.t("undo"), self.undo)
        self._render()
        self.search.setFocus()

    def pick_category(self, key: str) -> None:
        self.category = key
        for k, chip in self.chips.items():
            chip.setChecked(k == key)
        self._render()

    def _render(self) -> None:
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        query = self.search.text()
        shown = [i for i in search(self.items, query, self.lang) if not self.category or i.category == self.category]
        if self.flathub_items and not self.category:
            shown += search(self.flathub_items, query, self.lang)
        self.cards: dict[str, QFrame] = {}
        for item in shown:
            self.cards[item.id] = self._item_card(item)
        self.empty.setVisible(not shown)

    def _item_card(self, item: Item) -> QFrame:
        frame = QFrame(objectName="Card")
        box = QVBoxLayout(frame)
        box.setContentsMargins(16, 12, 16, 12)
        head = QHBoxLayout()
        head.addWidget(self._wrap(f"<b style='font-size:13pt'>{item.name(self.lang)}</b>"), 1)
        if item.source == "flathub":
            head.addWidget(QLabel("Flathub", objectName="Badge"))
        else:
            head.addWidget(QLabel(item.category_name(self.lang), objectName="Badge"))
        box.addLayout(head)
        if item.about(self.lang):
            box.addWidget(self._wrap(item.about(self.lang), "Muted"))
        box.addWidget(self._wrap(self.t("sets_up") + " " + " · ".join(item.sets_up(self.lang)), "Muted"))
        row = QHBoxLayout()
        row.addStretch(1)
        if item.source == "flathub" and item.id in self.installed_apps:
            row.addWidget(QLabel(self.t("installed"), objectName="Badge"))
        setup = QPushButton(self.t("setup"))
        setup.setAccessibleName(f"{self.t('setup')}: {item.name(self.lang)}")
        setup.setEnabled(self.admin)
        setup.clicked.connect(lambda _c, i=item: self.show_plan(i))
        row.addWidget(setup)
        box.addLayout(row)
        self.list_layout.addWidget(frame)
        return frame

    def search_flathub(self) -> None:
        term = self.search.text().strip()
        if len(term) < 2:
            return
        query = term
        self.show_working(self.t("flathub"))
        self._run(lambda: self.flathub(query), lambda found: self._flathub_done(query, found))

    def _flathub_done(self, query: str, found: list[Item]) -> None:
        if not found:
            self.show_message(self.t("flathub_none"), query)
            return
        self.show_store(query, found)

    # -- the plan -----------------------------------------------------------------

    def show_plan(self, item: Item) -> None:
        self.pending = item
        self.plan = build_plan(list(item.requests), self.ctx)
        layout, actions = self._page()
        card = self._card(layout)
        card.addWidget(QLabel(f"<span style='font-size:15pt; font-weight:700'>{self.t('setup')}: {item.name(self.lang)}</span>"))
        if item.about(self.lang):
            card.addWidget(self._wrap(item.about(self.lang), "Muted"))
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
        self._button(actions, self.t("cancel"), lambda: self.show_store())
        self.apply_button = self._button(actions, self.t("apply"), self.apply, primary=True)
        self._update_apply()
        (self.confirm_field or self.apply_button).setFocus()

    def _update_apply(self, *_args) -> None:
        ok = bool(self.plan and self.plan.ok and self.admin)
        if self.confirm_field is not None:
            ok = ok and self.confirm_field.text().strip().casefold() in ("yes", "כן")
        self.apply_button.setEnabled(ok)

    def apply(self) -> None:
        if not self.apply_button.isEnabled() or self.plan is None or self.pending is None:
            return
        plan, item = self.plan, self.pending
        self.show_working(self.t("applying"))
        self._run(lambda: apply_plan(plan, self.ctx, f"Store: {item.id}"), self.applied)

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
        back = self._button(actions, self.t("back"), lambda: self.show_store(), primary=True)
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

    # -- status pages -----------------------------------------------------------------

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

    def show_message(self, text: str, query: str = "") -> None:
        layout, actions = self._page()
        card = self._card(layout)
        card.addWidget(self._wrap(f"<span style='font-size:15pt; font-weight:700; color:{OK_GREEN}'>{text}</span>"))
        layout.addStretch(1)
        back = self._button(actions, self.t("back"), lambda: self.show_store(query), primary=True)
        back.setFocus()

    @pyqtSlot(str)
    def show_error(self, text: str) -> None:
        layout, actions = self._page()
        card = self._card(layout, "Warn")
        card.addWidget(QLabel(f"<span style='font-size:15pt; font-weight:700; color:{DANGER}'>{self.t('failed')}</span>"))
        card.addWidget(self._wrap(text))
        layout.addStretch(1)
        back = self._button(actions, self.t("try_again"), lambda: self.show_store(), primary=True)
        back.setFocus()

    # -- threads --------------------------------------------------------------------------

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
        if self.pending is not None:
            self.plan, self.pending = None, None
            self.show_store()
        else:
            self.close()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--version" in argv:
        print(f"dai-store {__version__} — {__author__}")
        return 0
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName(APP_ID)
    app.setDesktopFileName(APP_ID)
    if "Noto Sans" in QFontDatabase.families():
        app.setFont(QFont("Noto Sans", 11))
    app.setStyleSheet(with_touch(STYLE))
    window = StoreWindow(ui_lang())
    window.show()
    return app.exec()
