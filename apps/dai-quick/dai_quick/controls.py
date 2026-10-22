# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""What D.Ai Quick switches, and how (docs/TASKBAR.md §2.4).

Every control uses a tool the session user may already use without a
password - NetworkManager, BlueZ, power-profiles-daemon, PipeWire, the LXQt
notification settings - with a fixed argument list, never a shell. Nothing
here runs as root. A control the computer does not have (no Bluetooth
adapter, no power-profiles-daemon) reads as None and is not shown.
After a change the state is read again, so the panel shows what is true,
not what was asked for.
"""

from __future__ import annotations

import configparser
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

Runner = Callable[[list[str]], subprocess.CompletedProcess]
SINK = "@DEFAULT_AUDIO_SINK@"
SOURCE = "@DEFAULT_AUDIO_SOURCE@"


def run(argv: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(argv, 127, "", str(exc))


def notifications_conf() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "lxqt" / "notifications.conf"


@dataclass(frozen=True)
class Toggle:
    key: str
    icon: str       # from the icon theme (Breeze in D.Ai OS); "a|b" = first one the theme has
    fallback: str   # when the theme does not have it


TOGGLES = (Toggle("wifi", "network-wireless", "📶"), Toggle("bluetooth", "preferences-system-bluetooth", "ᛒ"),
           Toggle("dnd", "notifications-disabled", "🌙"), Toggle("saver", "battery-profile-powersave|battery-060|battery", "🔋"),
           Toggle("mic", "microphone-sensitivity-muted", "🎙"),
           Toggle("focus", "appointment-new|alarm-symbolic|alarm", "🎯"))


class Controls:
    def __init__(self, runner: Runner = run, which: Callable[[str], str | None] = shutil.which,
                 conf: Path | None = None) -> None:
        self.runner = runner
        self.which = which
        self.conf = conf

    def _ok(self, argv: list[str]) -> bool:
        return self.runner(argv).returncode == 0

    def _out(self, argv: list[str]) -> str | None:
        if not self.which(argv[0]):
            return None
        result = self.runner(argv)
        return result.stdout if result.returncode == 0 else None

    # -- toggles: read() -> True / False / None (not available) -------------

    def wifi(self) -> bool | None:
        out = self._out(["nmcli", "radio", "wifi"])
        return None if out is None else out.strip() == "enabled"

    def set_wifi(self, on: bool) -> bool:
        return self._ok(["nmcli", "radio", "wifi", "on" if on else "off"])

    def bluetooth(self) -> bool | None:
        out = self._out(["bluetoothctl", "show"])
        if out is None or "Controller" not in out:
            return None  # no adapter
        return re.search(r"^\s*Powered:\s*yes", out, re.M) is not None

    def set_bluetooth(self, on: bool) -> bool:
        return self._ok(["bluetoothctl", "power", "on" if on else "off"])

    def saver(self) -> bool | None:
        out = self._out(["powerprofilesctl", "get"])
        return None if out is None else out.strip() == "power-saver"

    def set_saver(self, on: bool) -> bool:
        return self._ok(["powerprofilesctl", "set", "power-saver" if on else "balanced"])

    def mic(self) -> bool | None:
        """True when the microphone is muted."""
        out = self._out(["wpctl", "get-volume", SOURCE])
        return None if out is None else "[MUTED]" in out

    def set_mic(self, muted: bool) -> bool:
        return self._ok(["wpctl", "set-mute", SOURCE, "1" if muted else "0"])

    def focus(self) -> bool | None:
        """A D.Ai Focus session is running (docs/BEYOND.md §5); None when dai-focus is not installed."""
        out = self._out(["dai-focus", "status", "--json"])
        if out is None:
            return None
        try:
            return bool(json.loads(out).get("active"))
        except ValueError:
            return None

    def set_focus(self, on: bool) -> bool:
        return self._ok(["dai-focus", "start", "25"] if on else ["dai-focus", "stop"])

    def dnd(self) -> bool | None:
        parser = self._notifications()
        return parser.get("General", "doNotDisturb", fallback="false").strip().lower() == "true"

    def set_dnd(self, on: bool) -> bool:
        """lxqt-notificationd reloads its settings file when it changes."""
        parser = self._notifications()
        if not parser.has_section("General"):
            parser.add_section("General")
        parser.set("General", "doNotDisturb", "true" if on else "false")
        path = self.conf or notifications_conf()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f".{path.name}.tmp")
            with open(tmp, "w", encoding="utf-8") as handle:
                parser.write(handle, space_around_delimiters=False)
            os.replace(tmp, path)
        except OSError:
            return False
        return True

    def _notifications(self) -> configparser.RawConfigParser:
        # Raw and case-preserving: the file is Qt's (QSettings), its other keys are written back untouched.
        parser = configparser.RawConfigParser(strict=False, interpolation=None)
        parser.optionxform = str  # type: ignore[assignment,method-assign]
        try:
            parser.read(self.conf or notifications_conf(), encoding="utf-8")
        except (OSError, configparser.Error):
            pass
        return parser

    def read(self, key: str) -> bool | None:
        return getattr(self, key)()

    def set(self, key: str, value: bool) -> bool:
        if key not in {t.key for t in TOGGLES}:
            raise ValueError(f"unknown control: {key}")
        return getattr(self, f"set_{key}")(value)

    # -- volume ---------------------------------------------------------------

    def volume(self) -> int | None:
        out = self._out(["wpctl", "get-volume", SINK])
        match = re.search(r"Volume:\s*([0-9.]+)", out or "")
        return round(float(match.group(1)) * 100) if match else None

    def set_volume(self, percent: int) -> bool:
        percent = max(0, min(100, int(percent)))
        return self._ok(["wpctl", "set-volume", SINK, f"{percent}%"])

    # -- what the rest of D.Ai knows --------------------------------------------

    @staticmethod
    def security(lang: str = "en") -> int | None:
        try:
            from dai_tune.context import Context
            from dai_tune.posture import assess
        except ImportError:
            return None
        try:
            return assess(Context(lang=lang), lang)[0]
        except Exception:  # a failing check must not keep the panel from opening
            return None

    @staticmethod
    def status() -> dict:
        try:
            from dai_status import read
        except ImportError:
            return {}
        return read()

    def state(self) -> dict:
        data: dict = {t.key: self.read(t.key) for t in TOGGLES}
        data["volume"] = self.volume()
        return data
