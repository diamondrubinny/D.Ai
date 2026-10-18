# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The MOM window (docs/MOM.md §3, §6): apps in plain language, and how busy the computer is.

Everything works from the keyboard: type to filter, Delete closes, Shift+Delete
forces (after a question). Every row has an accessible name that says it all,
and every bar shows its value as text, never as colour alone.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QFontDatabase, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar,
                             QPushButton, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from dai_i18n import embed, qt_direction, ui_lang

from . import __author__, __version__
from . import actions, apps as apps_mod, procs
from .text import describe, notes, size, t

KEY = Qt.ItemDataRole.UserRole
OTHER = "__other__"

STYLE = """
QMainWindow, QWidget#Page { background: #0B1020; }
QWidget { color: #E6E9F5; font-size: 10.5pt; }
QTabWidget::pane { border: 0; }
QTabBar::tab { background: transparent; color: #9AA3C7; padding: 8px 16px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #FFFFFF; border-bottom: 2px solid #7C5CFF; }
QTabBar::tab:focus { color: #22D3EE; }
QLineEdit { background: #141B33; border: 1px solid #2A3563; border-radius: 10px; padding: 6px 10px; }
QLineEdit:focus, QTreeWidget:focus, QListWidget:focus, QPushButton:focus { border: 2px solid #22D3EE; }
QTreeWidget, QListWidget { background: #141B33; border: 1px solid #2A3563; border-radius: 12px; alternate-background-color: #18203D; }
QTreeWidget::item, QListWidget::item { padding: 4px 2px; }
QTreeWidget::item:selected, QListWidget::item:selected { background: #5B3FD6; color: #FFFFFF; }
QHeaderView::section { background: #141B33; color: #B8A6FF; border: 0; padding: 6px; font-weight: 600; }
QPushButton { background: #1C2547; border: 1px solid #2A3563; border-radius: 10px; padding: 6px 14px; }
QPushButton:hover { border: 1px solid #7C5CFF; }
QPushButton#Danger { color: #FFB4B4; }
QPushButton:disabled { color: #5A6390; }
QLabel#Muted { color: #9AA3C7; font-size: 9.5pt; }
QProgressBar { background: #141B33; border: 1px solid #2A3563; border-radius: 8px; text-align: center; min-height: 22px; }
QProgressBar::chunk { border-radius: 7px; background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7C5CFF, stop:1 #22D3EE); }
"""


@dataclass
class Perf:
    cpu: float = 0.0
    mem_total: int = 0
    mem_used: int = 0
    swap_total: int = 0
    swap_used: int = 0
    disk_total: int = 0
    disk_free: int = 0


class LiveSource:
    """Reads the real computer; each call measures CPU since the previous one."""

    def __init__(self, lang: str, root: Path = Path("/")) -> None:
        self.lang = lang
        self.root = root
        self.previous: procs.Snapshot | None = None
        self.cpu_before = procs.cpu_total(root)
        self.desktop = apps_mod.load_desktop_apps(apps_mod.desktop_dirs(), lang)
        self.loaded = time.monotonic()

    def __call__(self) -> tuple[list[apps_mod.App], Perf]:
        from .cli import recording_now

        if time.monotonic() - self.loaded > 60:  # new apps get installed
            self.desktop = apps_mod.load_desktop_apps(apps_mod.desktop_dirs(), self.lang)
            self.loaded = time.monotonic()
        snap = procs.snapshot(self.root, self.previous)
        self.previous = snap
        busy, total = procs.cpu_total(self.root)
        delta = total - self.cpu_before[1]
        cpu = (busy - self.cpu_before[0]) / delta * 100 if delta > 0 else 0.0
        self.cpu_before = (busy, total)
        mem = procs.memory_totals(self.root)
        try:
            disk = shutil.disk_usage("/")
            disk_total, disk_free = disk.total, disk.free
        except OSError:
            disk_total = disk_free = 0
        perf = Perf(cpu=round(max(0.0, min(cpu, 100.0)), 1), mem_total=mem.get("MemTotal", 0),
                    mem_used=mem.get("MemTotal", 0) - mem.get("MemAvailable", 0),
                    swap_total=mem.get("SwapTotal", 0), swap_used=mem.get("SwapTotal", 0) - mem.get("SwapFree", 0),
                    disk_total=disk_total, disk_free=disk_free)
        return apps_mod.group(snap, self.desktop, recording=recording_now()), perf


def _spawn(argv: list[str]) -> None:
    subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)


def _ask(parent: QWidget, title: str, body: str, action: str, lang: str) -> bool:
    box = QMessageBox(QMessageBox.Icon.Warning, title, body, parent=parent)
    yes = box.addButton(action, QMessageBox.ButtonRole.DestructiveRole)
    cancel = box.addButton(t("cancel", lang), QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel)  # Enter never destroys anything
    box.setEscapeButton(cancel)
    box.exec()
    return box.clickedButton() is yes


class MomWindow(QMainWindow):
    def __init__(self, lang: str | None = None, source: Callable[[], tuple[list, Perf]] | None = None,
                 closer=actions.close, ask=_ask, spawn=_spawn, interval: int = 2000, services_runner=None,
                 autostart: tuple[Path | None, list[Path] | None] = (None, None), ai=None,
                 ai_inline: bool = False, doctor=None) -> None:
        super().__init__()
        self.lang = lang or ui_lang()
        self.source = source or LiveSource(self.lang)
        self.closer = closer
        self.ask = ask
        self.spawn = spawn
        self.ai = ai              # Diamond (diamond.answer by default); tests pass their own
        self.ai_inline = ai_inline
        self.doctor = doctor      # → D.Ai Doctor's findings for "why is it slow?"
        self.perf = Perf()
        self.dialog = None
        self.apps: dict[str, apps_mod.App] = {}
        self.items: dict[str, QTreeWidgetItem] = {}
        self.setWindowTitle(t("title", self.lang))
        self.setLayoutDirection(qt_direction(self.lang))
        self.setStyleSheet(STYLE)
        self.resize(820, 560)

        self.tabs = QTabWidget()
        from .background import _run
        from .pages import BackgroundPage, StartupPage

        self.background = BackgroundPage(self.lang, services_runner or _run)
        from . import background as bg

        runner = services_runner or _run
        self.startup = StartupPage(self.lang, *autostart, costs=lambda: bg.boot_costs(runner))
        self.tabs.addTab(self._apps_page(), t("apps", self.lang))
        self.tabs.addTab(self.background, t("background", self.lang))
        self.tabs.addTab(self.startup, t("startup", self.lang))
        self.tabs.addTab(self._performance_page(), t("performance", self.lang))
        self.tabs.currentChanged.connect(self._tab_shown)
        self.setCentralWidget(self.tabs)

        self.timer = QTimer(self, interval=interval)
        self.timer.timeout.connect(self.refresh)
        self.refresh()
        if interval > 0:
            self.timer.start()

    # Pages

    def _apps_page(self) -> QWidget:
        page = QWidget(objectName="Page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)
        self.search = QLineEdit(placeholderText=t("search", self.lang))
        self.search.setAccessibleName(t("search", self.lang))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels([t(k, self.lang) for k in ("col_name", "col_memory", "col_cpu", "col_notes")])
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setAccessibleName(t("apps", self.lang))
        self.tree.setColumnWidth(0, 300)
        self.tree.setColumnWidth(1, 100)
        self.tree.setColumnWidth(2, 80)
        self.tree.currentItemChanged.connect(lambda *_: self._update_buttons())
        layout.addWidget(self.tree, 1)

        row = QHBoxLayout()
        self.summary = QLabel(objectName="Muted")
        row.addWidget(self.summary, 1)
        hint = QLabel(t("hint", self.lang), objectName="Muted")
        row.addWidget(hint)
        self.close_button = QPushButton(embed(t("close", self.lang), self.lang))
        self.close_button.clicked.connect(lambda: self.close_selected(False))
        self.force_button = QPushButton(embed(t("force", self.lang), self.lang), objectName="Danger")
        self.force_button.clicked.connect(lambda: self.close_selected(True))
        self.ask_button = QPushButton(embed("✦ " + t("ask_diamond", self.lang), self.lang))
        self.ask_button.setToolTip(t("ask_diamond", self.lang) + " · ?")
        self.ask_button.clicked.connect(self.ask_diamond)
        row.addWidget(self.ask_button)
        row.addWidget(self.close_button)
        row.addWidget(self.force_button)
        layout.addLayout(row)

        QShortcut(QKeySequence(Qt.Key.Key_Delete), self.tree, lambda: self.close_selected(False))
        QShortcut(QKeySequence("Shift+Delete"), self.tree, lambda: self.close_selected(True))
        QShortcut(QKeySequence("?"), self.tree, self.ask_diamond)
        QShortcut(QKeySequence.StandardKey.Find, self, self.search.setFocus)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self._escape)
        self.search.returnPressed.connect(self.tree.setFocus)
        return page

    def _performance_page(self) -> QWidget:
        page = QWidget(objectName="Page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        self.bars: dict[str, tuple[QLabel, QProgressBar]] = {}
        for key in ("cpu", "memory", "swap", "disk"):
            label = QLabel()
            bar = QProgressBar()
            bar.setRange(0, 100)
            label.setBuddy(bar)
            layout.addWidget(label)
            layout.addWidget(bar)
            self.bars[key] = (label, bar)
        layout.addStretch(1)
        self.slow_button = QPushButton(embed("✦ " + t("slow", self.lang), self.lang))
        self.slow_button.clicked.connect(self.why_slow)
        layout.addWidget(self.slow_button, 0, Qt.AlignmentFlag.AlignLeading)
        return page

    def _tab_shown(self, index: int) -> None:
        page = self.tabs.widget(index)
        if page in (self.background, self.startup):
            page.refresh()  # services and login apps change rarely: read them when the tab is opened

    # Data

    def refresh(self) -> None:
        found, perf = self.source()
        self.apps = {a.key: a for a in found}
        self._fill_tree(found)
        self._fill_performance(perf)
        self.perf = perf
        shown = [a for a in found if a.is_app]
        self.summary.setText(t("summary", self.lang, apps=len(shown), procs=sum(len(a.processes) for a in found)))
        self._filter(self.search.text())
        self._update_buttons()

    def _set_row(self, item: QTreeWidgetItem, app: apps_mod.App) -> None:
        item.setText(0, app.name)
        item.setText(1, size(app.memory, self.lang))
        item.setText(2, f"{app.cpu:g}%")
        item.setText(3, notes(app, self.lang))
        item.setData(0, KEY, app.key)
        item.setToolTip(0, describe(app, self.lang))
        spoken = t("row", self.lang, name=app.name, memory=size(app.memory, self.lang), cpu=f"{app.cpu:g}")
        spoken += ". " + notes(app, self.lang)
        for column in range(4):
            item.setData(column, Qt.ItemDataRole.AccessibleTextRole, spoken)
        for column in (1, 2):
            item.setTextAlignment(column, Qt.AlignmentFlag.AlignTrailing | Qt.AlignmentFlag.AlignVCenter)

    def _fill_tree(self, found: list[apps_mod.App]) -> None:
        current = self.tree.currentItem()
        selected = current.data(0, KEY) if current is not None else None
        wanted = {a.key for a in found if a.is_app} | {OTHER}
        for key in [k for k in self.items if k not in wanted and not k.startswith("proc:")]:
            item = self.items.pop(key)
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
        other = self.items.get(OTHER)
        if other is None:
            other = QTreeWidgetItem([t("other", self.lang)])
            other.setData(0, KEY, OTHER)
            self.items[OTHER] = other
        for index, app in enumerate(a for a in found if a.is_app):
            item = self.items.get(app.key)
            if item is None:
                item = QTreeWidgetItem()
                icon = QIcon.fromTheme(app.icon) if app.icon else QIcon()
                if not icon.isNull():
                    item.setIcon(0, icon)
                self.items[app.key] = item
            if self.tree.indexOfTopLevelItem(item) != index:
                was_open = item.isExpanded()
                if self.tree.indexOfTopLevelItem(item) >= 0:
                    self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
                self.tree.insertTopLevelItem(index, item)
                item.setExpanded(was_open)
            self._set_row(item, app)
            self._fill_children(item, [(f"{p.name} ({p.pid})", p.memory, p.cpu) for p in app.processes])
        if self.tree.indexOfTopLevelItem(other) < 0:
            self.tree.addTopLevelItem(other)
        elif self.tree.indexOfTopLevelItem(other) != self.tree.topLevelItemCount() - 1:
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(other))
            self.tree.addTopLevelItem(other)
        rest = [a for a in found if not a.is_app]
        other.takeChildren()
        for app in rest:
            child = QTreeWidgetItem()
            self._set_row(child, app)
            other.addChild(child)
        other.setText(1, size(sum(a.memory for a in rest), self.lang))
        other.setText(2, f"{round(sum(a.cpu for a in rest), 1):g}%")
        total = sum(len(a.processes) for a in rest)
        other.setText(3, t("one_process", self.lang) if total == 1 else t("processes", self.lang, count=total))
        if selected is not None:
            match = self._item_for(selected)
            if match is not None:
                self.tree.setCurrentItem(match)
        if self.tree.currentItem() is None and self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))

    @staticmethod
    def _fill_children(item: QTreeWidgetItem, rows: list[tuple[str, int, float]]) -> None:
        while item.childCount() > len(rows):
            item.removeChild(item.child(item.childCount() - 1))
        for index, (name, memory, cpu) in enumerate(rows):
            child = item.child(index) if index < item.childCount() else QTreeWidgetItem(item)
            child.setText(0, name)
            child.setText(1, size(memory))
            child.setText(2, f"{cpu:g}%")

    def _item_for(self, key: str) -> QTreeWidgetItem | None:
        if key in self.items:
            return self.items[key]
        other = self.items.get(OTHER)
        for index in range(other.childCount() if other else 0):
            if other.child(index).data(0, KEY) == key:
                return other.child(index)
        return None

    def _fill_performance(self, perf: Perf) -> None:
        def percent(part: int, whole: int) -> int:
            return round(part / whole * 100) if whole > 0 else 0

        values = {
            "cpu": (t("cpu_now", self.lang, value=f"{perf.cpu:g}"), round(perf.cpu)),
            "memory": (t("memory_now", self.lang, used=size(perf.mem_used), total=size(perf.mem_total)),
                       percent(perf.mem_used, perf.mem_total)),
            "swap": (t("swap_now", self.lang, used=size(perf.swap_used), total=size(perf.swap_total)),
                     percent(perf.swap_used, perf.swap_total)),
            "disk": (t("disk_now", self.lang, free=size(perf.disk_free), total=size(perf.disk_total)),
                     percent(perf.disk_total - perf.disk_free, perf.disk_total)),
        }
        for key, (caption, value) in values.items():
            label, bar = self.bars[key]
            label.setText(caption)
            bar.setValue(value)
            bar.setFormat(f"{value}%")
            bar.setAccessibleName(caption)  # the words, not only the bar
            label.setVisible(key != "swap" or perf.swap_total > 0)
            bar.setVisible(key != "swap" or perf.swap_total > 0)

    # Actions

    def selected_app(self) -> apps_mod.App | None:
        item = self.tree.currentItem()
        while item is not None and item.data(0, KEY) is None:
            item = item.parent()  # a process row acts on its app
        key = item.data(0, KEY) if item is not None else None
        return self.apps.get(key) if key and key != OTHER else None

    def _update_buttons(self) -> None:
        app = self.selected_app()
        self.close_button.setEnabled(app is not None)
        self.ask_button.setEnabled(app is not None)
        self.force_button.setEnabled(app is not None and not app.protected)

    def close_selected(self, force: bool) -> None:
        app = self.selected_app()
        if app is None:
            return
        if app.protected and force:
            QMessageBox.information(self, t("title", self.lang), t("protected_force", self.lang, name=app.name))
            return
        confirmed = False
        if app.protected:
            confirmed = self.ask(self, t("confirm_protected_title", self.lang, name=app.name),
                                 t("confirm_protected", self.lang, name=app.name), t("close", self.lang), self.lang)
            if not confirmed:
                return
        if force:
            confirmed = self.ask(self, t("confirm_force_title", self.lang, name=app.name),
                                 t("confirm_force", self.lang, name=app.name), t("force", self.lang), self.lang)
            if not confirmed:
                return
        try:
            self.closer(app, force=force, confirmed=confirmed)
        except actions.Refused as refused:
            QMessageBox.information(self, t("title", self.lang), t(str(refused), self.lang, name=app.name))
            return
        self.statusBar().showMessage(t("forced" if force else "closed", self.lang, name=app.name), 5000)
        if not force:
            QTimer.singleShot(3000, lambda: self._offer_force(app))
        QTimer.singleShot(300, self.refresh)

    # Diamond (docs/MOM.md §11)

    def _open_diamond(self, title: str, prepare, suggestions: list) -> None:
        from .ask import DiamondDialog

        self.dialog = DiamondDialog(self.lang, title, prepare, suggestions, self._suggested, ai=self.ai,
                                    inline=self.ai_inline, parent=self)
        self.dialog.setStyleSheet(STYLE + DIALOG_STYLE)
        self.dialog.open()

    def ask_diamond(self) -> None:
        app = self.selected_app()
        if app is None:
            return
        from . import diamond

        def prepare():
            facts = diamond.facts_for(app)
            return diamond.what_messages(facts, self.lang), diamond.local_what(facts, self.lang)
        self._open_diamond(t("diamond_title", self.lang, name=app.name), prepare, [])

    def why_slow(self) -> None:
        from . import diamond

        found, perf = list(self.apps.values()), self.perf

        def prepare():
            data = diamond.slow_facts(found, perf, (self.doctor or diamond.doctor_findings)(self.lang))
            return diamond.slow_messages(data, self.lang), diamond.local_why(data, self.lang)
        self._open_diamond(t("diamond_slow_title", self.lang), prepare, diamond.suggestions(found, perf, self.lang))

    def _suggested(self, suggestion) -> None:
        """A button from MOM's own list: it does what the same button elsewhere in MOM does."""
        if suggestion.kind == "startup":
            self.tabs.setCurrentWidget(self.startup)
        elif suggestion.kind == "close":
            item = self._item_for(suggestion.key)
            if item is not None:
                self.tabs.setCurrentIndex(0)
                self.tree.setCurrentItem(item)
                self.close_selected(False)

    def _offer_force(self, app: apps_mod.App) -> None:
        if app.protected or not actions.still_running(app):
            return
        if self.ask(self, t("confirm_force_title", self.lang, name=app.name), t("still", self.lang, name=app.name),
                    t("force", self.lang), self.lang):
            try:
                self.closer(app, force=True, confirmed=True)
            except actions.Refused:
                pass
            self.refresh()

    def _filter(self, query: str) -> None:
        folded = query.strip().casefold()
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item.data(0, KEY) == OTHER:
                visible = 0
                for c in range(item.childCount()):
                    child = item.child(c)
                    child.setHidden(bool(folded) and folded not in child.text(0).casefold())
                    visible += not child.isHidden()
                item.setHidden(bool(folded) and visible == 0)
                if folded and visible:
                    item.setExpanded(True)
            else:
                item.setHidden(bool(folded) and folded not in (item.text(0) + " " + item.toolTip(0)).casefold())

    def _escape(self) -> None:
        if self.search.text():
            self.search.clear()
        else:
            self.close()


DIALOG_STYLE = """
QDialog { background: #0B1020; }
QLabel#Big { font-size: 13pt; font-weight: 600; }
QPlainTextEdit { background: #141B33; border: 1px solid #2A3563; border-radius: 10px; font-family: monospace; }
QLabel:focus { border: 1px dashed #22D3EE; }
"""


def main(server=None) -> int:
    lang = ui_lang()
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("MOM")
    app.setApplicationVersion(__version__)
    app.setOrganizationName(__author__)
    app.setDesktopFileName("dai-mom")
    app.setLayoutDirection(qt_direction(lang))
    if "Noto Sans" in QFontDatabase.families():
        app.setFont(QFont("Noto Sans", 10))
    window = MomWindow(lang)
    if server is not None:
        def bring_forward() -> None:
            connection = server.nextPendingConnection()
            if connection is not None:
                connection.close()
            window.showNormal()
            window.raise_()
            window.activateWindow()

        server.newConnection.connect(bring_forward)
    window.show()
    window.tree.setFocus()
    return app.exec()
