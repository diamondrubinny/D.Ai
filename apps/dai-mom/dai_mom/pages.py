# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""MOM's "Background" and "At login" tabs (docs/MOM.md stage 2).

They refresh when shown, not on a timer: services and login apps change
rarely, and a list that keeps moving is hard to use with a screen reader.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QTreeWidget,
                             QTreeWidgetItem, QVBoxLayout, QWidget)

from dai_i18n import embed

from . import background as bg
from .text import t

DATA = Qt.ItemDataRole.UserRole


def _state(service: bg.Service, lang: str) -> str:
    key = f"state_{service.active}"
    return t(key, lang) if key in ("state_active", "state_failed", "state_inactive", "state_activating") \
        else service.active


class BackgroundPage(QWidget):
    def __init__(self, lang: str, runner: bg.Runner = bg._run) -> None:
        super().__init__(objectName="Page")
        self.lang = lang
        self.runner = runner
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels([t("col_service", lang), t("col_state", lang), ""])
        self.tree.setAccessibleName(t("background", lang))
        self.tree.setColumnWidth(0, 420)
        self.tree.currentItemChanged.connect(lambda *_: self._update_buttons())
        layout.addWidget(self.tree, 1)
        row = QHBoxLayout()
        self.status = QLabel(objectName="Muted", wordWrap=True)
        row.addWidget(self.status, 1)
        self.buttons = {}
        for action in ("refresh", "start", "stop", "restart"):
            button = QPushButton(embed(t(action, lang), lang))
            button.clicked.connect(lambda _=False, a=action: self.refresh() if a == "refresh" else self.act(a))
            row.addWidget(button)
            self.buttons[action] = button
        layout.addLayout(row)

    def refresh(self) -> None:
        self.tree.clear()
        for user, title in ((True, t("yours", self.lang)), (False, t("system_services", self.lang))):
            top = QTreeWidgetItem([title])
            top.setFirstColumnSpanned(True)
            self.tree.addTopLevelItem(top)
            for service in bg.services(self.runner, user=user):
                name = service.description or service.unit
                item = QTreeWidgetItem([name, _state(service, self.lang), service.unit])
                item.setData(0, DATA, service)
                item.setToolTip(0, service.unit)
                spoken = t("service_row", self.lang, name=name, state=_state(service, self.lang))
                for column in range(3):
                    item.setData(column, Qt.ItemDataRole.AccessibleTextRole, spoken)
                top.addChild(item)
            top.setExpanded(True)
        self._update_buttons()

    def selected(self) -> bg.Service | None:
        item = self.tree.currentItem()
        return item.data(0, DATA) if item is not None else None

    def _update_buttons(self) -> None:
        service = self.selected()
        mine = service is not None and service.user
        self.buttons["start"].setEnabled(mine and service.active != "active")
        self.buttons["stop"].setEnabled(mine and service.active == "active" and not service.protected)
        self.buttons["restart"].setEnabled(mine)

    def act(self, action: str) -> None:
        service = self.selected()
        if service is None:
            return
        name = service.description or service.unit
        try:
            ok = bg.control(service, action, self.runner)
        except bg.Refused as refused:
            self.status.setText(t(f"refused_{refused}", self.lang, name=name)
                                if str(refused) in ("protected", "system") else str(refused))
            return
        self.status.setText(t("done_ok" if ok else "done_failed", self.lang, name=name))
        self.refresh()


class StartupPage(QWidget):
    def __init__(self, lang: str, user_dir: Path | None = None, system_dirs: list[Path] | None = None) -> None:
        super().__init__(objectName="Page")
        self.lang = lang
        self.user_dir = user_dir
        self.system_dirs = system_dirs
        self.loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        hint = QLabel(t("startup_hint", lang), objectName="Muted", wordWrap=True)
        layout.addWidget(hint)
        self.list = QListWidget()
        self.list.setAccessibleName(t("startup", lang))
        self.list.itemChanged.connect(self._changed)
        layout.addWidget(self.list, 1)
        self.status = QLabel(objectName="Muted", wordWrap=True)
        layout.addWidget(self.status)

    def refresh(self) -> None:
        self.loading = True
        self.list.clear()
        for entry in bg.login_items(self.lang, self.user_dir, self.system_dirs):
            item = QListWidgetItem(f"{entry.name}" + (f" — {entry.comment}" if entry.comment else ""))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if entry.enabled else Qt.CheckState.Unchecked)
            item.setData(DATA, entry)
            self.list.addItem(item)
        self.loading = False

    def _changed(self, item: QListWidgetItem) -> None:
        if self.loading:
            return
        entry: bg.LoginItem = item.data(DATA)
        wanted = item.checkState() == Qt.CheckState.Checked
        try:
            bg.set_login_item(entry.id, wanted, self.user_dir, self.system_dirs)
        except (bg.Refused, OSError) as exc:
            self.status.setText(str(exc))
            return
        self.status.setText(t("startup_saved", self.lang, name=entry.name,
                              state=t("will_start" if wanted else "will_not_start", self.lang)))
