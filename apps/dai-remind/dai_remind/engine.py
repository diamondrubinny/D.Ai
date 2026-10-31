# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Reminders on disk, firing one, cancelling one (docs/REMIND.md §2).

A reminder is ~/.local/share/dai/reminders/<id>.json plus two user units that D.Ai Tune wrote
(reminder.add). Firing shows a notification with the text (an argument, never a shell), plays the
diamond family's bell, reads the text aloud when "read explanations aloud" is on, then removes the units
and the file and leaves <id>.fired behind with the moment only.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from dai_i18n import pick

REMIND_DIR = ".local/share/dai/reminders"
UNIT_DIR = ".config/systemd/user"
ID_RE = re.compile(r"^[0-9a-f]{8}$")
Run = Callable[..., subprocess.CompletedProcess]


class RemindError(RuntimeError):
    pass


@dataclass(frozen=True)
class Reminder:
    id: str
    text: str
    at: str          # "YYYY-MM-DDTHH:MM", local time
    created: str = ""

    @property
    def when(self) -> datetime:
        return datetime.strptime(self.at, "%Y-%m-%dT%H:%M")


def folder(home: Path | None = None) -> Path:
    return (home or Path.home()) / REMIND_DIR


def unit_files(reminder_id: str, home: Path | None = None) -> list[Path]:
    base = (home or Path.home()) / UNIT_DIR
    return [base / f"dai-remind-{reminder_id}.service", base / f"dai-remind-{reminder_id}.timer"]


def load(reminder_id: str, home: Path | None = None) -> Reminder | None:
    if not ID_RE.match(reminder_id):
        raise RemindError("a reminder id is 8 hexadecimal characters")
    path = folder(home) / f"{reminder_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("text"), str) or not isinstance(data.get("at"), str):
        return None
    try:
        datetime.strptime(data["at"], "%Y-%m-%dT%H:%M")
    except ValueError:
        return None
    return Reminder(reminder_id, data["text"], data["at"], str(data.get("created", "")))


def upcoming(home: Path | None = None) -> list[Reminder]:
    out = []
    for path in sorted(folder(home).glob("*.json")):
        if ID_RE.match(path.stem) and (reminder := load(path.stem, home)) is not None:
            out.append(reminder)
    return sorted(out, key=lambda r: r.at)


def remove(reminder_id: str, home: Path | None = None, run: Run = subprocess.run) -> None:
    """Stop the timer and delete the units and the file; quiet when they are already gone."""
    for suffix in ("timer", "service"):
        _quiet(run, ["systemctl", "--user", "disable", "--now", f"dai-remind-{reminder_id}.{suffix}"])
    for path in unit_files(reminder_id, home) + [folder(home) / f"{reminder_id}.json"]:
        try:
            path.unlink()
        except OSError:
            pass
    _quiet(run, ["systemctl", "--user", "daemon-reload"])
    for suffix in ("timer", "service"):
        _quiet(run, ["systemctl", "--user", "reset-failed", f"dai-remind-{reminder_id}.{suffix}"])


def _quiet(run: Run, argv: list[str]) -> None:
    try:
        run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def read_aloud_wanted(home: Path | None = None) -> bool:
    """The same choice D.Ai Explain uses: "read explanations aloud" (docs/EXPLAIN.md §9)."""
    try:
        data = json.loads(((home or Path.home()) / ".config/dai/explain.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("voice") is True


def fire(reminder_id: str, lang: str, home: Path | None = None, run: Run = subprocess.run,
         popen=subprocess.Popen, which=shutil.which) -> Reminder:
    """Show, sound, (speak), then clean up. Returns the reminder."""
    reminder = load(reminder_id, home)
    if reminder is None:
        remove(reminder_id, home, run)
        raise RemindError(pick(lang, "No reminder {id}.", "אין תזכורת {id}.").format(id=reminder_id))
    title = pick(lang, "⏰ Reminder", "⏰ תזכורת")
    if which("notify-send"):
        _quiet(run, ["notify-send", "-a", "D.Ai", "-i", "alarm-clock", "-u", "critical", title, reminder.text])
    if which("dai-sound"):
        _quiet(run, ["dai-sound", "bell"])
    if read_aloud_wanted(home) and which("dai-speak"):
        try:
            child = popen(["dai-speak", "--stdin", "--lang", lang], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, start_new_session=True)
            if child.stdin is not None:
                child.stdin.write((title[2:].strip() + ": " + reminder.text).encode("utf-8"))
                child.stdin.close()
        except OSError:
            pass
    remove(reminder_id, home, run)
    try:
        folder(home).mkdir(parents=True, exist_ok=True)
        (folder(home) / f"{reminder_id}.fired").write_text(datetime.now().strftime("%Y-%m-%dT%H:%M") + "\n", encoding="utf-8")
    except OSError:
        pass
    return reminder


def describe(reminder: Reminder, lang: str, now: datetime | None = None) -> str:
    now = now or datetime.now()
    left = int((reminder.when - now).total_seconds() // 60)
    if left < 0:
        when = pick(lang, "overdue", "עבר הזמן")
    elif left < 60:
        when = pick(lang, "in {n} min", "בעוד {n} דק׳").format(n=left)
    elif left < 24 * 60:
        when = pick(lang, "in {h} h {m} min", "בעוד {h} שע׳ {m} דק׳").format(h=left // 60, m=left % 60)
    else:
        when = pick(lang, "in {d} days", "בעוד {d} ימים").format(d=left // (24 * 60))
    return f"{reminder.id}  {reminder.at.replace('T', ' ')}  ({when})  {reminder.text}"
