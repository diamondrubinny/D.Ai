# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-focus: a quiet session with a timer (docs/BEYOND.md §5).

  dai-focus start [MINUTES]   do not disturb + warm light for MINUTES (default 25, 5-180); a timer ends it
  dai-focus stop              end the session now: what was changed is put back
  dai-focus status [--json]   how much is left

Nothing here needs root or a shell: "do not disturb" is the same file D.Ai Quick writes and the notification
daemon reads, the light is wlsunset, and the timer is a systemd user timer. The session's state lives in
$XDG_RUNTIME_DIR/dai/focus.json and is gone after a reboot.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from dai_i18n import pick, ui_lang

DEFAULT_MINUTES = 25
MIN_MINUTES, MAX_MINUTES = 5, 180
TIMER_UNIT = "dai-focus-end"
# wlsunset warms the screen between "sunset" and "sunrise": a sunrise one minute after sunset makes it warm
# nearly the whole day, for as long as the session lasts (docs/BEYOND.md §5: requires verification on a session).
WLSUNSET = ["wlsunset", "-t", "4000", "-T", "6500", "-S", "23:59", "-s", "23:58"]

Run = Callable[..., subprocess.CompletedProcess]


def say(lang: str, en: str, he: str, **kwargs: object) -> str:
    return pick(lang, en, he).format(**kwargs)


def state_path() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/dai-{os.getuid()}"
    return Path(base) / "dai" / "focus.json"


def clamp_minutes(value: str | int | None) -> int:
    try:
        minutes = int(value) if value not in (None, "") else DEFAULT_MINUTES
    except (TypeError, ValueError):
        return DEFAULT_MINUTES
    return max(MIN_MINUTES, min(MAX_MINUTES, minutes))


class Session:
    """The session's moving parts, each one replaceable in tests."""

    def __init__(self, run: Run = subprocess.run, popen=subprocess.Popen, which=None, controls=None,
                 path: Path | None = None, now: Callable[[], float] = time.time) -> None:
        import shutil
        self.run = run
        self.popen = popen
        self.which = which or shutil.which
        self.path = path or state_path()
        self.now = now
        self._controls = controls

    # -- the pieces -----------------------------------------------------------

    def controls(self):
        """D.Ai Quick's controls own "do not disturb"; without them (not installed) the session skips it."""
        if self._controls is None:
            try:
                from dai_quick.controls import Controls
            except ImportError:
                return None
            self._controls = Controls()
        return self._controls

    def _quiet(self, argv: list[str]) -> subprocess.CompletedProcess:
        try:
            return self.run(argv, capture_output=True, text=True, timeout=15, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            return subprocess.CompletedProcess(argv, 127, "", str(exc))

    def nightlight_running(self) -> bool:
        return self._quiet(["pgrep", "-x", "wlsunset"]).returncode == 0

    def start_nightlight(self) -> bool:
        if not self.which("wlsunset") or self.nightlight_running():
            return False
        try:
            self.popen(WLSUNSET, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       start_new_session=True)
        except OSError:
            return False
        return True

    def stop_nightlight(self) -> None:
        self._quiet(["pkill", "-x", "wlsunset"])

    def arm_timer(self, minutes: int) -> bool:
        if not self.which("systemd-run"):
            return False
        self._quiet(["systemctl", "--user", "stop", f"{TIMER_UNIT}.timer"])
        result = self._quiet(["systemd-run", "--user", "--quiet", f"--unit={TIMER_UNIT}", f"--on-active={minutes}m",
                              "--description=D.Ai Focus: the session ends", "dai-focus", "stop", "--by-timer"])
        return result.returncode == 0

    def disarm_timer(self) -> None:
        self._quiet(["systemctl", "--user", "stop", f"{TIMER_UNIT}.timer"])

    def notify(self, title: str, body: str) -> None:
        if self.which("notify-send"):
            self._quiet(["notify-send", "-a", "D.Ai", title, body])

    # -- the state -----------------------------------------------------------

    def load(self) -> dict | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) and "started" in data else None

    def save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self.path.with_name(f".{self.path.name}.tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def clear(self) -> None:
        try:
            self.path.unlink()
        except OSError:
            pass

    def remaining(self, data: dict) -> int:
        """Whole minutes left, never below zero."""
        end = float(data.get("started", 0)) + 60 * int(data.get("minutes", 0))
        return max(0, int((end - self.now() + 59) // 60))

    # -- the verbs ------------------------------------------------------------

    def start(self, minutes: int, lang: str) -> tuple[int, str]:
        if self.load() is not None:
            return 1, say(lang, "A focus session is already running (dai-focus status).",
                          "סשן פוקוס כבר רץ (dai-focus status).")
        controls = self.controls()
        dnd_before = bool(controls.dnd()) if controls is not None else None
        if controls is not None and not dnd_before:
            controls.set_dnd(True)
        data = {"started": self.now(), "minutes": minutes, "dnd_before": dnd_before,
                "nightlight_started": self.start_nightlight()}
        data["timer"] = self.arm_timer(minutes)
        self.save(data)
        body = say(lang, "Pop-ups are hidden and the light is warmer for {n} minutes.",
                   "ההתראות מוסתרות והתאורה חמה למשך {n} דקות.", n=minutes)
        if not data["timer"]:
            body += " " + say(lang, "No timer here: end it with dai-focus stop.", "אין טיימר כאן: לסיים עם dai-focus stop.")
        self.notify(say(lang, "Focus: {n} minutes", "פוקוס: {n} דקות", n=minutes), body)
        return 0, say(lang, "Focus for {n} minutes. To end early: dai-focus stop", "פוקוס ל־{n} דקות. לסיים מוקדם: dai-focus stop", n=minutes)

    def stop(self, lang: str, by_timer: bool = False) -> tuple[int, str]:
        data = self.load()
        if data is None:
            return 1, say(lang, "No focus session is running.", "אין סשן פוקוס פעיל.")
        controls = self.controls()
        if controls is not None and data.get("dnd_before") is False:
            controls.set_dnd(False)
        if data.get("nightlight_started"):
            self.stop_nightlight()
        if not by_timer:
            self.disarm_timer()
        self.clear()
        elapsed = max(1, int((self.now() - float(data.get("started", self.now()))) // 60))
        restored = []
        if data.get("dnd_before") is False:
            restored.append(say(lang, "pop-ups are back", "ההתראות חזרו"))
        if data.get("nightlight_started"):
            restored.append(say(lang, "the light is normal again", "התאורה חזרה לרגיל"))
        body = (", ".join(restored) + ".") if restored else say(lang, "Nothing had been changed.", "שום דבר לא השתנה.")
        title = say(lang, "Focus ended: {n} minutes", "הפוקוס נגמר: {n} דקות", n=elapsed) if by_timer else \
            say(lang, "Focus stopped after {n} minutes", "הפוקוס נעצר אחרי {n} דקות", n=elapsed)
        self.notify(title, body[0].upper() + body[1:])
        return 0, title + ". " + body[0].upper() + body[1:]

    def status(self, lang: str, as_json: bool = False) -> tuple[int, str]:
        data = self.load()
        if as_json:
            payload = {"active": data is not None}
            if data is not None:
                payload.update({"minutes": data.get("minutes"), "remaining": self.remaining(data)})
            return 0, json.dumps(payload)
        if data is None:
            return 0, say(lang, "No focus session. Start one: dai-focus start 25", "אין סשן פוקוס. להתחיל: dai-focus start 25")
        return 0, say(lang, "Focus: {left} of {n} minutes left.", "פוקוס: נשארו {left} מתוך {n} דקות.",
                      left=self.remaining(data), n=data.get("minutes"))


def main(argv: list[str] | None = None, session: Session | None = None) -> int:
    args = list(sys.argv if argv is None else argv)[1:]
    lang = ui_lang()
    if not args or args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if args else 2
    if args[0] == "--version":
        from . import __author__, __version__
        print(f"dai-focus {__version__} — {__author__}")
        return 0
    session = session or Session()
    verb, rest = args[0], args[1:]
    if verb == "start":
        code, message = session.start(clamp_minutes(rest[0] if rest else None), lang)
    elif verb == "stop":
        code, message = session.stop(lang, by_timer="--by-timer" in rest)
    elif verb == "status":
        code, message = session.status(lang, as_json="--json" in rest)
    else:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    print(message, file=sys.stdout if code == 0 else sys.stderr)
    return code
