# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Notice new problems and offer help, without nagging (docs/EVOLVE.md §4).

Runs in the user's session (autostart), read-only. One notification per
problem per 10 minutes; "don't ask again" is remembered. Old crashes from
before the session started are not announced (they are in the chat).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from . import problems as P
from .text import describe, lang, t

INTERVAL = 30
QUIET_SECONDS = 600


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)


def ignored(directory: Path | None = None) -> set[str]:
    data = _load((directory or P.state_dir()) / "ignored.json", [])
    return {k for k in data if isinstance(k, str)} if isinstance(data, list) else set()


def ignore(key: str, directory: Path | None = None) -> None:
    keys = ignored(directory) | {key}
    _save((directory or P.state_dir()) / "ignored.json", sorted(keys))


def notify(problem: P.Problem, language: str) -> None:
    """A notification with a button; clicking it opens the chat on this problem."""
    body = describe(problem, language)
    base = ["notify-send", "-a", "D.Ai", "-i", "dialog-warning", t("notify_title", language)]

    def wait_for_click() -> None:
        try:
            result = subprocess.run([*base[:-1], "--wait", "-A", f"open={t('notify_action', language)}", base[-1], body],
                                    capture_output=True, text=True, timeout=3600, check=False)
        except (OSError, subprocess.SubprocessError):
            return
        if result.returncode != 0:  # an older notify-send without actions
            subprocess.run([*base, f"{body}\n{t('notify_hint', language)}"], capture_output=True, check=False)
            return
        if result.stdout.strip() == "open" and shutil.which("dai-heal"):
            subprocess.Popen(["dai-heal", "chat", "--problem", problem.key], start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    threading.Thread(target=wait_for_click, daemon=True).start()


def _mirror(section: str, value: object) -> None:
    """Show it on the Start diamond (docs/TASKBAR.md §2.1); optional, never fatal."""
    try:
        from dai_status import update
    except ImportError:
        return
    update(section, value)


class Watcher:
    def __init__(self, collect: Callable[..., list[P.Problem]] = P.collect, announce: Callable[[P.Problem, str], None] = notify,
                 clock: Callable[[], float] = time.time, directory: Path | None = None) -> None:
        self.collect = collect
        self.announce = announce
        self.clock = clock
        self.directory = directory or P.state_dir()
        self.started = clock()
        self.language = lang()

    def check(self) -> list[P.Problem]:
        """Announce what is new; return what was announced."""
        now = self.clock()
        seen = _load(self.directory / "seen.json", {})
        seen = seen if isinstance(seen, dict) else {}
        skip = ignored(self.directory)
        announced = []
        current = [p for p in self.collect(since=self.started - 300) if p.key not in skip]
        _mirror("heal", len(current))
        for problem in current:
            if problem.kind in ("crash", "forge-app") and problem.when and problem.when < self.started - 300:
                continue  # from before this session: shown in the chat, not announced
            last = seen.get(problem.key, {}) if isinstance(seen.get(problem.key), dict) else {}
            newer = problem.when > float(last.get("when", 0)) or problem.count > int(last.get("count", 0))
            if not newer or now - float(last.get("notified", 0)) < QUIET_SECONDS:
                continue
            self.announce(problem, self.language)
            seen[problem.key] = {"when": problem.when, "count": problem.count, "notified": now}
            announced.append(problem)
        if announced:
            _save(self.directory / "seen.json", seen)
        return announced

    def run_forever(self) -> None:
        while True:
            try:
                self.check()
            except Exception:  # never stop watching because one check failed
                pass
            time.sleep(INTERVAL)
