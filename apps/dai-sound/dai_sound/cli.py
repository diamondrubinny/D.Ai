# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-sound: the D.Ai sound theme, "the diamond family" (docs/SOUNDS.md).

  dai-sound NAME            play a sound from the theme (complete, dialog-error, device-added, ...)
  dai-sound watch           play device-added/-removed and power-plug/-unplug as they happen (autostart)
  dai-sound status          on, quiet or off, and whether "Do not disturb" silences them now
  dai-sound on|quiet|off    the same choice D.Ai Tune makes ("quiet sounds")

Respects ~/.config/dai/sounds (on, quiet or off) and "Do not disturb" (lxqt-notificationd's setting),
except for login and logout. Plays with pw-play (PipeWire). Needs no special permissions.
"""
from __future__ import annotations

import configparser
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Iterable

THEME_DIRS = ("/usr/share/sounds/dai/stereo", "/usr/share/sounds/freedesktop/stereo")
NAME = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
MODES = ("on", "quiet", "off")
VOLUME = {"on": "0.7", "quiet": "0.3"}
ALWAYS = {"desktop-login", "desktop-logout"}  # rare, and a change of state: not silenced by Do not disturb
GAP = 1.5  # seconds: the same sound twice within this is one sound (a device sends several events)

Run = Callable[..., object]


def config_home(environ: dict | None = None) -> Path:
    env = os.environ if environ is None else environ
    return Path(env.get("XDG_CONFIG_HOME") or Path(env.get("HOME", str(Path.home()))) / ".config")


def mode(environ: dict | None = None) -> str:
    try:
        value = (config_home(environ) / "dai" / "sounds").read_text(encoding="ascii").strip().lower()
    except (OSError, UnicodeError):
        return "on"
    return value if value in MODES else "on"


def save_mode(value: str, environ: dict | None = None) -> Path:
    if value not in MODES:
        raise ValueError(value)
    path = config_home(environ) / "dai" / "sounds"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value + "\n", encoding="ascii")
    return path


def do_not_disturb(environ: dict | None = None) -> bool:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(config_home(environ) / "lxqt" / "notifications.conf", encoding="utf-8")
    except (OSError, configparser.Error):
        return False
    return parser.get("General", "doNotDisturb", fallback="false").strip().lower() == "true"


def find(name: str, dirs: Iterable[str] = THEME_DIRS) -> Path | None:
    if not NAME.match(name):
        return None
    for directory in dirs:
        for ext in (".oga", ".ogg", ".wav"):
            path = Path(directory) / f"{name}{ext}"
            if path.is_file():
                return path
    return None


def should_play(name: str, environ: dict | None = None) -> str | None:
    """The volume to play `name` at, or None when it should stay silent."""
    chosen = mode(environ)
    if chosen == "off":
        return None
    if name not in ALWAYS and do_not_disturb(environ):
        return None
    return VOLUME[chosen]


def play(name: str, run: Run = subprocess.Popen, environ: dict | None = None,
         dirs: Iterable[str] = THEME_DIRS, force: bool = False) -> bool:
    volume = VOLUME["on"] if force else should_play(name, environ)
    path = find(name, dirs)
    if volume is None or path is None:
        return False
    try:
        run(["pw-play", "--volume", volume, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return False
    return True


# --------------------------------------------------------------------------
# watch: USB devices and the charger, from udev (no special permissions)
# --------------------------------------------------------------------------

EVENT = re.compile(r"^UDEV\s+\[[\d.]+\]\s+(add|remove|change)\s+(\S+)\s+\((usb|power_supply)\)")


def mains_online(sysfs: Path = Path("/sys/class/power_supply")) -> bool | None:
    """True when a charger is plugged in, False when not, None on a computer with no mains supply (a desktop)."""
    found = None
    for supply in sysfs.glob("*"):
        try:
            if (supply / "type").read_text().strip() != "Mains":
                continue
            found = bool(found) or (supply / "online").read_text().strip() == "1"
        except OSError:
            continue
    return found


class Watcher:
    """Turns udev lines into sounds: one per real change, never a burst."""

    def __init__(self, play_sound: Callable[[str], object], online: Callable[[], bool | None] = mains_online,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.play_sound, self.online, self.clock = play_sound, online, clock
        self.charging = online()
        self.last: dict[str, float] = {}

    def _sound(self, name: str) -> None:
        now = self.clock()
        if now - self.last.get(name, -GAP) >= GAP:
            self.last[name] = now
            self.play_sound(name)

    def line(self, text: str) -> None:
        match = EVENT.match(text.strip())
        if not match:
            return
        action, _path, subsystem = match.groups()
        if subsystem == "usb" and action in ("add", "remove"):
            self._sound("device-added" if action == "add" else "device-removed")
        elif subsystem == "power_supply":
            charging = self.online()
            if charging is not None and self.charging is not None and charging != self.charging:
                self._sound("power-plug" if charging else "power-unplug")
            self.charging = charging


def watch(play_sound: Callable[[str], object] = play) -> int:
    argv = ["udevadm", "monitor", "--udev", "--subsystem-match=usb/usb_device", "--subsystem-match=power_supply"]
    try:
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    except OSError:
        print("dai-sound: udevadm is missing", file=sys.stderr)
        return 1
    watcher = Watcher(play_sound)
    assert process.stdout is not None
    for text in process.stdout:
        watcher.line(text)
    return process.wait()


def main(argv: list[str] | None = None, run: Run = subprocess.Popen) -> int:
    args = list(sys.argv if argv is None else argv)[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if args else 2
    command = args[0]
    if command == "--version":
        from . import __author__, __version__
        print(f"dai-sound {__version__} — {__author__}")
        return 0
    if command == "watch":
        return watch()
    if command == "status":
        print(f"sounds: {mode()}" + (" (silenced now: Do not disturb)" if do_not_disturb() else ""))
        return 0
    if command in MODES:
        save_mode(command)
        if command != "off":
            play("complete", run, force=True)
        return 0
    if not NAME.match(command):
        print(f"dai-sound: not a sound name: {command!r}", file=sys.stderr)
        return 2
    return 0 if play(command, run, force="--force" in args) else 1
