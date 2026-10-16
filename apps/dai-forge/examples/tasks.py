#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Example D.Ai Forge app: a small Hebrew task list.

Add it with:  dai-forge app add tasks /usr/share/dai/forge/examples/tasks.py --title "המשימות שלי"
It runs in the Forge sandbox: no network, and ~ is its own private folder.
"""

import json
import os
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

DATA = os.path.join(os.path.expanduser("~"), "tasks.json")
STYLE = """
QWidget { background: #0B1020; color: #E6E9F5; font-size: 13pt; }
QLineEdit, QListWidget { background: #141B33; border: 1px solid #2A3563; border-radius: 10px; padding: 8px; }
QLineEdit:focus, QListWidget:focus { border: 2px solid #22D3EE; }
QPushButton { background: #5B3FD6; color: white; border: none; border-radius: 10px; padding: 8px 16px; }
QPushButton:focus { outline: none; border: 2px solid #22D3EE; }
QLabel#Title { font-size: 20pt; font-weight: 600; }
QLabel#Hint { color: #9AA3C7; font-size: 11pt; }
"""


def load() -> list[dict]:
    try:
        with open(DATA, encoding="utf-8") as fh:
            data = json.load(fh)
        return [t for t in data if isinstance(t, dict) and isinstance(t.get("text"), str)]
    except (OSError, ValueError):
        return []


def save(tasks: list[dict]) -> None:
    tmp = DATA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(tasks, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, DATA)


class Tasks(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("המשימות שלי")
        self.resize(460, 520)
        layout = QVBoxLayout(self)
        title = QLabel("המשימות שלי", objectName="Title")
        layout.addWidget(title)
        layout.addWidget(QLabel("Enter להוספה · רווח לסימון · Delete למחיקה", objectName="Hint"))

        row = QHBoxLayout()
        self.entry = QLineEdit(placeholderText="משימה חדשה…")
        self.entry.setAccessibleName("משימה חדשה")
        self.entry.returnPressed.connect(self.add)
        add = QPushButton("הוספה")
        add.setAccessibleName("הוספת משימה")
        add.clicked.connect(self.add)
        row.addWidget(self.entry, 1)
        row.addWidget(add)
        layout.addLayout(row)

        self.list = QListWidget()
        self.list.setAccessibleName("רשימת המשימות")
        self.list.itemChanged.connect(self.store)
        layout.addWidget(self.list, 1)

        remove = QPushButton("מחיקת המסומנות")
        remove.setAccessibleName("מחיקת משימות שבוצעו")
        remove.clicked.connect(self.remove_done)
        layout.addWidget(remove)

        for task in load() or [{"text": "לנסות את D.Ai Forge", "done": True}, {"text": "לבנות אפליקציה משלי", "done": False}]:
            self.append(task["text"], task.get("done") is True)

    def append(self, text: str, done: bool = False) -> None:
        item = QListWidgetItem(text)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if done else Qt.CheckState.Unchecked)
        self.list.addItem(item)

    def add(self) -> None:
        text = self.entry.text().strip()
        if text:
            self.append(text)
            self.entry.clear()
            self.store()

    def remove_done(self) -> None:
        for row in reversed(range(self.list.count())):
            if self.list.item(row).checkState() == Qt.CheckState.Checked:
                self.list.takeItem(row)
        self.store()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Delete and self.list.currentItem() is not None:
            self.list.takeItem(self.list.currentRow())
            self.store()
        else:
            super().keyPressEvent(event)

    def store(self, *_args) -> None:
        save([
            {"text": self.list.item(i).text(), "done": self.list.item(i).checkState() == Qt.CheckState.Checked}
            for i in range(self.list.count())
        ])


def main() -> int:
    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    app.setFont(QFont("Noto Sans", 12))
    app.setStyleSheet(STYLE)
    window = Tasks()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
