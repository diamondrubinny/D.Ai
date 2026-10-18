# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Automations: scripts the local AI wrote, run on a schedule in the sandbox (docs/EVOLVE.md §2).

Each one is a user-level systemd timer + service (never root):

  ~/.config/systemd/user/dai-auto-<name>.service   ExecStart=dai-forge app run <name> --background
  ~/.config/systemd/user/dai-auto-<name>.timer     from the rule-parsed schedule

In the background the script's stdout is read: "NOTIFY: text" becomes a
desktop notification (3 per run at most), everything else goes to a short
log. A crash is recorded for D.Ai Heal like for any Forge app.
"""

from __future__ import annotations

import collections
import os
import subprocess
import time
from pathlib import Path
from typing import Callable

from . import apps
from .schedule import Schedule

MAX_NOTIFY = 3
MAX_SECONDS = 300
LOG_LINES = 60

Runner = Callable[[list[str]], subprocess.CompletedProcess]


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(argv, 1, "", str(exc))


def unit_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "systemd" / "user"


def unit_name(name: str, suffix: str) -> str:
    return f"dai-auto-{apps.validate_name(name)}.{suffix}"


def log_path(name: str) -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local/state")
    return Path(base) / "dai" / "auto" / f"{apps.validate_name(name)}.log"


def unit_files(app: apps.App) -> dict[str, str]:
    schedule = Schedule.from_json(app.schedule)
    if schedule is None:
        raise apps.AppError(f"{app.name} has no schedule")
    service = "\n".join([
        "# Written by D.Ai Forge (docs/EVOLVE.md): an automation you asked for. dai-forge auto remove " + app.name,
        "[Unit]",
        f"Description=D.Ai automation: {app.title}",
        "",
        "[Service]",
        "Type=oneshot",
        f"ExecStart=/usr/bin/dai-forge app run {app.name} --background",
        f"TimeoutStartSec={MAX_SECONDS + 30}",
        "Nice=10",
        "IOSchedulingClass=idle",
        *(["", "[Install]", "WantedBy=default.target"] if schedule.kind == "login" else []),
        "",
    ])
    files = {unit_name(app.name, "service"): service}
    if schedule.kind != "login":
        files[unit_name(app.name, "timer")] = "\n".join([
            "[Unit]",
            f"Description=D.Ai automation: {app.title} ({schedule.describe('en')})",
            "",
            "[Timer]",
            *schedule.timer_lines(),
            "",
            "[Install]",
            "WantedBy=timers.target",
            "",
        ])
    return files


def _target(app: apps.App) -> str:
    schedule = Schedule.from_json(app.schedule)
    return unit_name(app.name, "service" if schedule and schedule.kind == "login" else "timer")


def install(app: apps.App, runner: Runner = _run) -> str:
    """Write and enable the units; returns the unit that was enabled."""
    if app.pending_permissions:
        raise apps.AppError(f"{app.name} asks for permissions you have not approved: {', '.join(app.pending_permissions)}")
    directory = unit_dir()
    directory.mkdir(parents=True, exist_ok=True)
    for filename, text in unit_files(app).items():
        (directory / filename).write_text(text, encoding="utf-8")
    runner(["systemctl", "--user", "daemon-reload"])
    target = _target(app)
    result = runner(["systemctl", "--user", "enable", *([] if target.endswith(".service") else ["--now"]), target])
    if result.returncode != 0:
        raise apps.AppError(f"could not enable {target}: {(result.stderr or result.stdout).strip()[-200:]}")
    return target


def pause(name: str, runner: Runner = _run) -> None:
    app = apps.load(name)
    runner(["systemctl", "--user", "disable", "--now", _target(app)])


def resume(name: str, runner: Runner = _run) -> str:
    return install(apps.load(name), runner)


def uninstall(name: str, runner: Runner = _run) -> None:
    """Stop and delete the units (the script itself is removed with dai-forge app remove)."""
    for suffix in ("timer", "service"):
        runner(["systemctl", "--user", "disable", "--now", unit_name(name, suffix)])
        (unit_dir() / unit_name(name, suffix)).unlink(missing_ok=True)
    runner(["systemctl", "--user", "daemon-reload"])


def listing(runner: Runner = _run) -> list[tuple[apps.App, str]]:
    """Automations and their state (active / paused / not installed)."""
    rows = []
    for app in apps.list_apps():
        if not app.is_automation:
            continue
        target = _target(app)
        if not (unit_dir() / target).exists():
            state = "not installed"
        else:
            state = runner(["systemctl", "--user", "is-enabled", target]).stdout.strip() or "unknown"
        rows.append((app, state))
    return rows


def run_background(app: apps.App, argv: list[str], notify: Callable[[str, str], None] | None = None,
                   clock: Callable[[], float] = time.time) -> int:
    """Run unattended: NOTIFY lines → notifications, the rest → log, a crash → D.Ai Heal."""
    notify = notify or _notify
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, errors="replace")
    lines: collections.deque[str] = collections.deque(maxlen=LOG_LINES)
    sent = 0
    started = clock()
    assert process.stdout is not None
    for line in process.stdout:
        lines.append(line)
        if line.startswith("NOTIFY:") and sent < MAX_NOTIFY:
            message = line[len("NOTIFY:"):].strip()[:200]
            if message:
                notify(app.title, message)
                sent += 1
        if clock() - started > MAX_SECONDS:
            process.kill()
            lines.append(f"[D.Ai] stopped after {MAX_SECONDS} s\n")
            break
    code = process.wait()
    process.stdout.close()
    log = log_path(app.name)
    log.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started))
    previous = log.read_text(encoding="utf-8").splitlines(keepends=True)[-LOG_LINES * 4:] if log.exists() else []
    log.write_text("".join(previous) + f"--- {stamp} exit {code}\n" + "".join(lines), encoding="utf-8")
    log.chmod(0o600)
    if code != 0 and any("Traceback" in line for line in lines):
        apps.record_crash(app, "".join(lines))
    return code


def _notify(title: str, message: str) -> None:
    subprocess.run(["notify-send", "-a", "D.Ai", "-i", "appointment-soon", title, message],
                   capture_output=True, check=False)
