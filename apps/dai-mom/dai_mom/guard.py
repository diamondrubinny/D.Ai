# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""MOM's guard (docs/MOM.md §4, §12): notices an app that runs away, never closes it.

  - CPU: an app keeps at least one whole core busy for 2 minutes.
  - Memory: an app keeps growing for 10 minutes, by at least 512 MB and half its size.

What it does: the app's name goes on the Living Diamond (status "busy") while
it lasts, and one quiet notification is sent per run of that app (not again
until it calms down and runs away again). Do not disturb hides the pop-up,
never the diamond. It reads /proc as the user, every 15 seconds, at low
priority; nothing is written except the status file.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import apps as apps_mod, procs
from .text import t

INTERVAL = 15.0
CPU_SECONDS = 120.0
CPU_CORES = 0.9            # "a whole core": 90% of one core, as a share of the computer × cores
MEMORY_SECONDS = 600.0
MEMORY_GROWTH = 512 * 2**20
MEMORY_RATIO = 0.5
SLACK = 16 * 2**20         # memory may dip this much and still count as growing
IGNORED = {"dai-mom"}      # MOM itself


@dataclass
class Track:
    busy_since: float | None = None
    memory: list[tuple[float, int]] = field(default_factory=list)   # (time, bytes), while growing
    warned: str = ""       # "" or "cpu" / "memory": already told for this run


@dataclass
class Alert:
    key: str
    name: str
    reason: str            # "cpu" or "memory"
    detail: str


class Guard:
    def __init__(self, lang: str, cores: int | None = None, cpu_seconds: float = CPU_SECONDS) -> None:
        self.lang = lang
        self.cores = cores or os.cpu_count() or 1
        self.cpu_seconds = cpu_seconds
        self.tracks: dict[str, Track] = {}

    def observe(self, found: list[apps_mod.App], now: float) -> tuple[list[str], list[Alert]]:
        """The names to show on the diamond now, and the alerts to send now (once per run)."""
        shown: list[str] = []
        alerts: list[Alert] = []
        seen = set()
        for app in found:
            if app.key in IGNORED or not app.processes:
                continue
            seen.add(app.key)
            track = self.tracks.setdefault(app.key, Track())
            reason = self._cpu(app, track, now) or self._memory(app, track, now)
            if reason is None:
                track.warned = ""
                continue
            shown.append(app.name)
            if track.warned != reason:
                track.warned = reason
                alerts.append(Alert(app.key, app.name, reason, self._detail(app, reason, track)))
        for gone in set(self.tracks) - seen:
            del self.tracks[gone]
        return shown, alerts

    def _cpu(self, app: apps_mod.App, track: Track, now: float) -> str | None:
        cores_busy = app.cpu * self.cores / 100
        if cores_busy < CPU_CORES:
            track.busy_since = None
            return None
        if track.busy_since is None:
            track.busy_since = now
        return "cpu" if now - track.busy_since >= self.cpu_seconds else None

    def _memory(self, app: apps_mod.App, track: Track, now: float) -> str | None:
        memory = app.memory
        if track.memory and memory < track.memory[-1][1] - SLACK:
            track.memory = []  # it gave memory back: not a leak
        track.memory = [track.memory[0], (now, memory)] if track.memory else [(now, memory)]  # first and last
        start_time, start = track.memory[0]
        if now - start_time < MEMORY_SECONDS:
            return None
        grown = memory - start
        return "memory" if grown >= MEMORY_GROWTH and grown >= start * MEMORY_RATIO else None

    def _detail(self, app: apps_mod.App, reason: str, track: Track) -> str:
        from .text import size

        if reason == "cpu":
            return t("guard_cpu", self.lang, name=app.name, minutes=max(1, int(self.cpu_seconds // 60)))
        grown = app.memory - track.memory[0][1]
        return t("guard_memory", self.lang, name=app.name, grown=size(grown),
                 minutes=int((track.memory[-1][0] - track.memory[0][0]) // 60))


def notify(alert: Alert, lang: str, run: Callable = subprocess.run) -> None:
    """One quiet notification; Do not disturb (lxqt-notificationd) hides it, the diamond still shows."""
    if not shutil.which("notify-send"):
        return
    run(["notify-send", "-a", "D.Ai", "-i", "dai-mom", "-u", "low", t("guard_title", lang, name=alert.name),
         alert.detail + "\n" + t("guard_hint", lang)], capture_output=True, check=False, timeout=10)


def mirror(names: list[str]) -> None:
    try:
        import dai_status
    except ImportError:
        return
    dai_status.update("busy", names)


def run_forever(lang: str, root: Path = Path("/"), interval: float = INTERVAL,
                sleep: Callable[[float], None] = time.sleep, rounds: int | None = None,
                cpu_seconds: float = CPU_SECONDS) -> None:
    from .cli import recording_now

    try:
        os.nice(10)  # the guard must never be the thing that slows the computer down
    except OSError:
        pass
    guard = Guard(lang, cpu_seconds=cpu_seconds)
    desktop = apps_mod.load_desktop_apps(apps_mod.desktop_dirs(), lang)
    previous = procs.snapshot(root)
    done = 0
    while rounds is None or done < rounds:
        sleep(interval)
        snap = procs.snapshot(root, previous)
        previous = snap
        found = apps_mod.group(snap, desktop, recording=recording_now())
        names, alerts = guard.observe(found, time.monotonic())
        mirror(names)
        for alert in alerts:
            print(f"{alert.reason} {alert.key}: {alert.detail}", flush=True)  # the journal keeps names only
            notify(alert, lang)
        done += 1
    mirror([])  # stopping: nothing is shown as busy any more
