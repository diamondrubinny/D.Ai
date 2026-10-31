# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Recording the screen with wf-recorder (docs/RECORD.md §2): start, stop, a pid file that is only ever
acted on after /proc confirms the process, and a small detached guard that stops it after N seconds."""
from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from dai_i18n import pick

RECORDER = "wf-recorder"
MAX_SECONDS = 3600
AREA_RE = re.compile(r"^-?\d+,-?\d+ \d+x\d+$")


class RecordError(RuntimeError):
    pass


def videos_dir(environ: dict[str, str] | None = None, home: Path | None = None) -> Path:
    env = os.environ if environ is None else environ
    base = env.get("XDG_VIDEOS_DIR") or str((home or Path.home()) / "Videos")
    return Path(base) / "Recordings"


def new_file(folder: Path, now: datetime | None = None) -> Path:
    return folder / f"Recording-{(now or datetime.now()).strftime('%Y-%m-%d-%H%M%S')}.mp4"


def runtime_dir(environ: dict[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    return Path(env.get("XDG_RUNTIME_DIR") or f"/tmp/dai-{os.getuid()}") / "dai"


def pid_file(environ: dict[str, str] | None = None) -> Path:
    return runtime_dir(environ) / "record.pid"


def recorder_argv(file: Path, area: str | None = None) -> list[str]:
    """No audio by default: the microphone is a separate decision (docs/RECORD.md §2)."""
    argv = [RECORDER, "-f", str(file)]
    if area:
        if not AREA_RE.match(area):
            raise RecordError("area: X,Y WxH")
        argv += ["-g", area]
    return argv


def choose_area(run=subprocess.run) -> str | None:
    try:
        result = run(["slurp"], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    area = (result.stdout or "").strip()
    return area if result.returncode == 0 and AREA_RE.match(area) else None


def _comm(pid: int, proc: Path) -> str:
    try:
        return (proc / str(pid) / "comm").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def running(path: Path, proc: Path = Path("/proc")) -> tuple[int, Path] | None:
    """(pid, file) from the pid file, only while that process is still wf-recorder."""
    try:
        first, second = path.read_text(encoding="utf-8").splitlines()[:2]
        pid = int(first)
    except (OSError, ValueError):
        return None
    if pid <= 1 or _comm(pid, proc) != RECORDER:
        return None
    return pid, Path(second)


def stop(path: Path, proc: Path = Path("/proc"), kill: Callable[[int, int], None] = os.kill) -> Path | None:
    """SIGINT: wf-recorder closes the file properly. Returns the file, or None when nothing was recording."""
    state = running(path, proc)
    try:
        path.unlink()
    except OSError:
        pass
    if state is None:
        return None
    pid, file = state
    try:
        kill(pid, signal.SIGINT)
    except OSError:
        return None
    return file


def start(file: Path, area: str | None, lang: str, path: Path, seconds: int = 0,
          popen=subprocess.Popen, proc: Path = Path("/proc"), guard: list[str] | None = None) -> int:
    """Start wf-recorder detached, remember it, and (with seconds) start the guard that stops it in time."""
    if running(path, proc) is not None:
        raise RecordError(pick(lang, "Already recording; stop it first (Super+Shift+R).", "כבר מקליט; עצרו קודם (Super+Shift+R)."))
    if seconds and not 1 <= seconds <= MAX_SECONDS:
        raise RecordError(pick(lang, "Seconds: 1 to {max}.", "שניות: 1 עד {max}.").format(max=MAX_SECONDS))
    file.parent.mkdir(parents=True, exist_ok=True)
    argv = recorder_argv(file, area)
    try:
        child = popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        raise RecordError(pick(lang, "The recorder (wf-recorder) is not installed: {error}",
                              "המקליט (wf-recorder) לא מותקן: {error}").format(error=exc.strerror or exc)) from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{child.pid}\n{file}\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    if seconds:
        try:
            popen(guard or ["dai-record", "_wait", str(child.pid), str(seconds)],
                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            pass
    return child.pid


def wait_and_stop(pid: int, seconds: int, path: Path, lang: str, proc: Path = Path("/proc"),
                  sleep: Callable[[float], None] = time.sleep, kill: Callable[[int, int], None] = os.kill,
                  run=subprocess.run) -> Path | None:
    """The guard: after `seconds`, stop that same recording if it still runs, then tell the person."""
    sleep(seconds)
    state = running(path, proc)
    if state is None or state[0] != pid:
        return None
    file = stop(path, proc, kill)
    if file is not None:
        for _ in range(20):          # wf-recorder finishes writing after SIGINT
            if file.exists() and _comm(pid, proc) != RECORDER:
                break
            sleep(0.25)
        notify_saved(file, lang, run)
    return file


def notify(title: str, body: str, run=subprocess.run, icon: str = "camera-video") -> None:
    try:
        run(["notify-send", "-a", "D.Ai", "-i", icon, title, body], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def notify_started(lang: str, seconds: int, run=subprocess.run) -> None:
    body = (pick(lang, "{n} seconds · Super+Shift+R stops earlier", "{n} שניות · Super+Shift+R עוצר קודם").format(n=seconds) if seconds
            else pick(lang, "Super+Shift+R stops", "Super+Shift+R עוצר"))
    notify(pick(lang, "⏺ Recording the screen", "⏺ מקליט את המסך"), body, run)


def notify_saved(file: Path, lang: str, run=subprocess.run) -> None:
    notify(pick(lang, "Recording saved", "ההקלטה נשמרה"), str(file), run)
    try:
        run(["dai-sound", "screen-capture"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        pass
