# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""What runs in the background and what starts at login (docs/MOM.md §3, stage 2).

- The user's own services (systemd --user): start, stop and restart them.
- The system's services: shown, never changed here (that is D.Ai Tune's job,
  with polkit, a journal and undo).
- Login apps (XDG autostart): turned off and on with a file in the user's own
  ~/.config/autostart (Hidden=true), never by touching the system's files.

No shell: systemctl with fixed arguments, and unit names checked first.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .apps import _localized, parse_desktop

UNIT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9@._:-]{0,200}\.(service|timer|socket)$")
ENTRY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}\.desktop$")
DESKTOP_NAMES = ("LXQt", "labwc", "wlroots")
# Parts of the session; stopping them from here is refused (as in §5).
PROTECTED_UNITS = frozenset({"pipewire.service", "pipewire.socket", "pipewire-pulse.service", "pipewire-pulse.socket",
                             "wireplumber.service", "dbus.service", "dbus.socket", "xdg-desktop-portal.service",
                             "dai-daid.socket"})

Runner = Callable[[list[str]], subprocess.CompletedProcess]


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=20, check=False,
                              env={**os.environ, "SYSTEMD_COLORS": "0", "LANG": "C.UTF-8"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(argv, 127, "", str(exc))


@dataclass
class Service:
    unit: str
    description: str
    active: str           # active, inactive, failed, activating
    sub: str              # running, exited, dead, waiting...
    user: bool            # the user's own (can be changed here) or the system's (read-only)
    protected: bool = False

    @property
    def dai(self) -> bool:
        return self.unit.startswith("dai-")


@dataclass
class LoginItem:
    id: str               # file name, e.g. dai-clip.desktop
    name: str
    comment: str
    enabled: bool
    system: bool          # comes from /etc/xdg/autostart (turning it off writes a user override)


def services(runner: Runner = _run, user: bool = True) -> list[Service]:
    argv = ["systemctl", *(["--user"] if user else []), "list-units", "--type=service,timer,socket", "--all",
            "--plain", "--no-legend", "--no-pager"]
    result = runner(argv)
    found = []
    for line in result.stdout.splitlines():
        parts = line.lstrip("●*× \t").split(None, 4)
        if len(parts) < 4 or not UNIT.match(parts[0]):
            continue
        unit, _load, active, sub = parts[:4]
        if _load == "not-found" or active == "inactive" and not (user and unit.startswith("dai-")):
            continue  # what runs or failed, and D.Ai's own units even when stopped
        found.append(Service(unit, parts[4].strip() if len(parts) > 4 else "", active, sub, user,
                             unit in PROTECTED_UNITS))
    return sorted(found, key=lambda s: (not s.dai, s.active != "active", s.unit))


class Refused(Exception):
    pass


def control(service: Service, action: str, runner: Runner = _run) -> bool:
    """start, stop or restart one of the user's own units. True when it is in the wanted state afterwards."""
    if not service.user:
        raise Refused("system")       # D.Ai Tune's job (polkit, journal, undo)
    if action not in ("start", "stop", "restart"):
        raise Refused("action")
    if not UNIT.match(service.unit):
        raise Refused("name")
    if action == "stop" and service.protected:
        raise Refused("protected")
    runner(["systemctl", "--user", action, service.unit])
    state = runner(["systemctl", "--user", "is-active", service.unit]).stdout.strip()
    return state != "active" if action == "stop" else state in ("active", "activating")


def _shown_here(entry: dict[str, str]) -> bool:
    only = [x for x in entry.get("OnlyShowIn", "").split(";") if x]
    never = [x for x in entry.get("NotShowIn", "").split(";") if x]
    if only and not any(name in only for name in DESKTOP_NAMES):
        return False
    return not any(name in never for name in DESKTOP_NAMES)


def autostart_dirs(home: Path | None = None) -> tuple[Path, list[Path]]:
    home = home or Path.home()
    config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    system = [Path(d) / "autostart" for d in (os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg").split(":") if d]
    return config / "autostart", system


def login_items(lang: str, user_dir: Path | None = None, system_dirs: list[Path] | None = None) -> list[LoginItem]:
    default_user, default_system = autostart_dirs()
    user_dir = user_dir or default_user
    system_dirs = system_dirs if system_dirs is not None else default_system
    files: dict[str, tuple[Path, bool]] = {}
    for directory in reversed(system_dirs):  # the first directory wins
        for path in sorted(directory.glob("*.desktop")) if directory.is_dir() else []:
            files[path.name] = (path, True)
    for path in sorted(user_dir.glob("*.desktop")) if user_dir.is_dir() else []:
        files[path.name] = (path, files.get(path.name, (path, False))[1])
    items = []
    for name, (path, system) in files.items():
        try:
            entry = parse_desktop(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if not entry.get("Name") or not _shown_here(entry):
            continue
        enabled = entry.get("Hidden", "false").lower() != "true" and \
            entry.get("X-GNOME-Autostart-enabled", "true").lower() != "false"
        items.append(LoginItem(name, _localized(entry, "Name", lang), _localized(entry, "Comment", lang), enabled, system))
    return sorted(items, key=lambda i: (not i.id.startswith("dai-"), i.name.lower()))


BLAME = re.compile(r"^\s*(?:(\d+)min\s*)?(?:([\d.]+)(ms|s))?\s+app-(\S+)@autostart\.service\s*$")


def boot_costs(runner: Runner = _run) -> dict[str, float]:
    """Seconds each login app adds, by its .desktop id, when the session starts them as systemd units
    (app-<id>@autostart.service, from systemd-xdg-autostart-generator). Empty when it cannot be measured:
    then MOM shows nothing rather than a guess."""
    try:
        result = runner(["systemd-analyze", "--user", "blame", "--no-pager"])
    except (OSError, subprocess.SubprocessError):
        return {}
    if result.returncode != 0:
        return {}
    costs: dict[str, float] = {}
    for line in result.stdout.splitlines():
        match = BLAME.match(line)
        if not match or not (match.group(1) or match.group(2)):
            continue
        minutes, value, unit, escaped = match.groups()
        seconds = int(minutes or 0) * 60 + (float(value) / (1000 if unit == "ms" else 1) if value else 0.0)
        item = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), escaped)
        costs[item + ".desktop"] = round(seconds, 1)
    return costs


def set_login_item(item_id: str, enabled: bool, user_dir: Path | None = None,
                   system_dirs: list[Path] | None = None) -> None:
    """Turn a login app on or off by writing (or removing) the user's own copy of its file."""
    if not ENTRY.match(item_id):
        raise Refused("name")
    default_user, default_system = autostart_dirs()
    user_dir = user_dir or default_user
    system_dirs = system_dirs if system_dirs is not None else default_system
    source = next((d / item_id for d in system_dirs if (d / item_id).is_file()), None)
    target = user_dir / item_id
    if source is None and not target.is_file():
        raise Refused("missing")
    if source is not None and enabled:
        target.unlink(missing_ok=True)  # back to the system's own file
        return
    text = (target if target.is_file() else source).read_text(encoding="utf-8", errors="replace")
    lines = [line for line in text.splitlines() if not line.startswith(("Hidden=", "X-GNOME-Autostart-enabled="))]
    out, placed = [], False
    for line in lines:
        out.append(line)
        if line.strip() == "[Desktop Entry]" and not placed:
            out.append(f"Hidden={'false' if enabled else 'true'}")
            placed = True
    user_dir.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(out) + "\n", encoding="utf-8")
