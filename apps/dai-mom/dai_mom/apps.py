# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Processes grouped into the apps people know (docs/MOM.md §3).

An app is found from its .desktop file (name, icon and description in the
user's language). A process belongs to the highest ancestor that is an app,
so a terminal owns the programs started in it and Firefox owns its content
processes. Whatever is not part of an app is listed under its own name.
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path

from .procs import Process, Snapshot

# The parts of the session itself. Closing one ends or breaks the session, so it needs a clear "yes",
# and forcing it is refused (docs/MOM.md §5).
PROTECTED = frozenset({
    "labwc", "lxqt-panel", "lxqt-session", "lxqt-notificationd", "lxqt-policykit-agent", "lxqt-runner",
    "pipewire", "pipewire-pulse", "wireplumber", "dbus-daemon", "dbus-broker", "daid", "systemd",
    "startlxqtwayland", "Xwayland", "sddm", "sddm-helper",
})

# Ancestors that are the session, never an app: the search for an app stops here.
SESSION = PROTECTED | {"init", "sh", "dash", "bash-session", "lxqt-wayland-session", "kthreadd"}

# The D.Ai launchers run `python3 -c '... from dai_<name>.cli import main ...'`.
DAI_MODULE = re.compile(r"\bdai_([a-z]+)\b")
# Interpreters are never the app themselves: the script they run is.
INTERPRETERS = frozenset({"python", "python3", "perl", "ruby", "node", "sh", "bash", "dash", "java"})
SHELLS = frozenset({"sh", "bash", "dash"})
FLATPAK_SCOPE = re.compile(r"^app-flatpak-(.+)-\d+\.scope$")
FIELD_CODE = re.compile(r"%[fFuUdDnNickvm]")


@dataclass
class DesktopApp:
    id: str                    # firefox-esr (the .desktop file name without the suffix)
    name: str
    comment: str = ""
    icon: str = ""
    keys: set[str] = field(default_factory=set)   # program names that mean this app


@dataclass
class App:
    key: str                   # stable across refreshes: the desktop id, or "proc:<name>"
    name: str
    comment: str = ""
    icon: str = ""
    processes: list[Process] = field(default_factory=list)
    is_app: bool = True        # False: a process with no .desktop file
    sandboxed: bool = False    # runs inside bwrap (D.Ai Forge)
    recording: bool = False    # uses the microphone or camera now (D.Ai Privacy)
    protected: bool = False    # a part of the session (PROTECTED)

    @property
    def memory(self) -> int:
        return sum(p.memory for p in self.processes)

    @property
    def cpu(self) -> float:
        return round(sum(p.cpu for p in self.processes), 1)

    @property
    def roots(self) -> list[Process]:
        """The processes whose parent is not in this app: closing them closes the app."""
        pids = {p.pid for p in self.processes}
        return [p for p in self.processes if p.ppid not in pids]


def _localized(entry: dict[str, str], key: str, lang: str) -> str:
    return entry.get(f"{key}[{lang}]") or entry.get(key, "")


def parse_desktop(text: str) -> dict[str, str]:
    """The [Desktop Entry] group of a .desktop file."""
    entry: dict[str, str] = {}
    group = ""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            group = line[1:-1]
        elif group == "Desktop Entry" and "=" in line and not line.startswith("#"):
            name, value = line.split("=", 1)
            entry.setdefault(name.strip(), value.strip())
    return entry


def exec_keys(command: str) -> set[str]:
    """The program names an Exec= line can show up as: 'env X=1 /usr/bin/foo %u' -> {'foo'}."""
    try:
        words = [w for w in shlex.split(FIELD_CODE.sub("", command)) if w]
    except ValueError:
        return set()
    while words and (words[0] == "env" or "=" in words[0] and not words[0].startswith("/")):
        words.pop(0)
    if not words:
        return set()
    keys = {os.path.basename(words[0])}
    if keys == {"flatpak"} and "run" in words:
        rest = [w for w in words[words.index("run") + 1:] if not w.startswith("-")]
        keys = {rest[0]} if rest else set()
    return {k for k in keys if k}


def desktop_dirs(home: Path | None = None) -> list[Path]:
    home = home or Path.home()
    data = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    dirs = [home / ".local/share/applications", home / ".local/share/flatpak/exports/share/applications",
            Path("/var/lib/flatpak/exports/share/applications")]
    return dirs + [Path(d) / "applications" for d in data.split(":") if d]


def load_desktop_apps(dirs: list[Path], lang: str) -> dict[str, DesktopApp]:
    """Program name -> the app it belongs to. The first directory wins (the user's own files first)."""
    by_key: dict[str, DesktopApp] = {}
    seen: set[str] = set()
    for directory in dirs:
        try:
            files = sorted(directory.glob("*.desktop"))
        except OSError:
            continue
        for path in files:
            if path.name in seen:
                continue
            seen.add(path.name)
            try:
                entry = parse_desktop(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if entry.get("Type", "Application") != "Application" or not entry.get("Name"):
                continue
            app = DesktopApp(id=path.stem, name=_localized(entry, "Name", lang),
                             comment=_localized(entry, "Comment", lang) or _localized(entry, "GenericName", lang),
                             icon=entry.get("Icon", ""))
            app.keys = exec_keys(entry.get("Exec", "")) | exec_keys(entry.get("TryExec", ""))
            if entry.get("StartupWMClass"):
                app.keys.add(entry["StartupWMClass"].lower())
            if path.stem.startswith("dai-"):
                app.keys.add(path.stem)  # matched through DAI_MODULE
            for key in app.keys:
                by_key.setdefault(key, app)
    return by_key


def _interpreter(name: str) -> bool:
    return name in INTERPRETERS or re.fullmatch(r"python3\.\d+", name) is not None


def program_keys(process: Process) -> list[str]:
    """The names to look a process up by, most specific first."""
    keys = []
    scope = FLATPAK_SCOPE.match(process.cgroup)
    if scope:
        keys.append(scope.group(1))
    if _interpreter(process.name) or process.cmdline and _interpreter(os.path.basename(process.cmdline[0])):
        found = DAI_MODULE.search(" ".join(process.cmdline[:4]))
        if found:
            keys.append(f"dai-{found.group(1)}")
        script = next((a for a in process.cmdline[1:] if not a.startswith("-")), "")
        if script and "/" in script:
            keys.append(os.path.basename(script))
        return keys  # never "python3.13": that would be the interpreter's own menu entry
    if process.exe:
        keys.append(os.path.basename(process.exe))
    if process.cmdline:
        keys.append(os.path.basename(process.cmdline[0]))
    keys += [process.name, process.name.lower()]
    return keys


def _dai_service(process: Process) -> DesktopApp | None:
    """A D.Ai background service without a menu entry: "dai_privacy" -> "D.Ai Privacy"."""
    if not _interpreter(process.name) or process.name in SHELLS:
        return None  # a shell's command text is not the program it runs
    found = DAI_MODULE.search(" ".join(process.cmdline[:4]))  # D.Ai's launchers: python3 -I -c "from dai_x…"
    if not found:
        return None
    module = found.group(1)
    name = "Diamond" if module == "ai" else f"D.Ai {module.capitalize()}"  # daid is Diamond, the local AI
    return DesktopApp(id=f"dai-{module}", name=name, icon="dai-logo")


def group(snapshot: Snapshot, desktop: dict[str, DesktopApp], uid: int | None = None,
          recording: list[str] | None = None) -> list[App]:
    """This user's processes as apps (biggest first). Other users' processes are not included."""
    uid = os.getuid() if uid is None else uid
    procs = snapshot.processes
    mine = {pid: p for pid, p in procs.items() if p.uid == uid}

    def match(process: Process) -> DesktopApp | None:
        if process.name in SESSION:
            return None
        return next((desktop[k] for k in program_keys(process) if k in desktop), None) or _dai_service(process)

    owner: dict[int, str] = {}
    apps: dict[str, App] = {}
    for pid, process in mine.items():
        found: DesktopApp | None = None
        current: Process | None = process
        hops = 0
        sandbox: Process | None = None
        while current is not None and hops < 64:  # the highest ancestor that is an app wins
            if current.name in SESSION or current.uid != uid:
                break
            if sandbox is not None and current.name != "bwrap":
                break  # a sandbox is its own app, not part of whatever started it
            candidate = match(current)
            if candidate is not None:
                found = candidate
            if current.name == "bwrap":
                sandbox = current
            current = procs.get(current.ppid)
            hops += 1
        if found is None and sandbox is not None:
            found = DesktopApp(id=f"sandbox:{sandbox.pid}", name="", icon="security-high")
        if found is not None:
            key = found.id
            app = apps.setdefault(key, App(key=key, name=found.name, comment=found.comment, icon=found.icon))
        else:
            key = f"proc:{process.name}"
            app = apps.setdefault(key, App(key=key, name=process.name, is_app=False,
                                           protected=process.name in PROTECTED))
        app.processes.append(process)
        owner[pid] = key

    lowered = [r.lower() for r in recording or []]
    for app in apps.values():
        app.sandboxed = any(p.name == "bwrap" for p in app.processes)
        app.protected = app.protected or any(p.name in PROTECTED for p in app.processes)
        names = {app.name.lower(), *(p.name.lower() for p in app.processes)}
        app.recording = any(r and any(r in n or n in r for n in names if len(n) > 2) for r in lowered)
        app.processes.sort(key=lambda p: p.pid)
        if not app.name:  # a sandbox without a menu entry: named after what runs inside
            app.name = next((p.name for p in app.processes if p.name != "bwrap"), "sandbox")
    return sorted(apps.values(), key=lambda a: (not a.is_app, -a.memory, a.name.lower()))


def find(apps: list[App], wanted: str) -> App | None:
    """An app by its key, its name or a pid (for the command line)."""
    if wanted.isdigit():
        return next((a for a in apps if any(p.pid == int(wanted) for p in a.processes)), None)
    folded = wanted.casefold()
    for test in (lambda a: a.key.casefold() in (folded, f"proc:{folded}"), lambda a: a.name.casefold() == folded):
        hit = next((a for a in apps if test(a)), None)
        if hit is not None:
            return hit
    return None
