# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Reading aloud with the local espeak-ng (docs/SPEAK.md §2).

The text goes to espeak-ng through its standard input (never on a command line), the voice follows the text's
own letters and then the interface language, and the one running reader is remembered in a pid file that is
only ever acted on after /proc confirms the process is still espeak-ng.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from dai_i18n import pick

VOICES = {"he": "he", "en": "en-us", "ar": "ar", "ru": "ru", "es": "es", "fr": "fr", "de": "de", "pt": "pt"}
DEFAULT_RATE = 160          # words per minute; espeak-ng's own default is 175
RATE_MIN, RATE_MAX = 80, 400
RATE_STEP = 30              # "faster" / "slower" in D.Ai Tune
MAX_TEXT = 20_000           # characters; more is cut (docs/SPEAK.md §2)
SETTINGS_FILE = ".config/dai/speak.json"
READER = "espeak-ng"

HEBREW = re.compile(r"[֐-׿]")
ARABIC = re.compile(r"[؀-ۿ]")
CYRILLIC = re.compile(r"[Ѐ-ӿ]")


class SpeakError(RuntimeError):
    """A message for the person, in their language."""


@dataclass(frozen=True)
class Settings:
    rate: int = DEFAULT_RATE


def clamp_rate(value: object) -> int:
    try:
        rate = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_RATE
    return max(RATE_MIN, min(RATE_MAX, rate))


def load_settings(home: Path | None = None) -> Settings:
    path = (home or Path.home()) / SETTINGS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    if not isinstance(data, dict):
        return Settings()
    return Settings(rate=clamp_rate(data.get("rate", DEFAULT_RATE)))


def language_of(text: str, fallback: str) -> str:
    """The language the letters say, else the interface language (docs/SPEAK.md §2)."""
    if HEBREW.search(text):
        return "he"
    if ARABIC.search(text):
        return "ar"
    if CYRILLIC.search(text):
        return "ru"
    return fallback if fallback in VOICES else "en"


def voice_for(lang: str) -> str:
    return VOICES.get(lang, VOICES["en"])


PLAYER = "pw-play"


def reader_argv(lang: str, rate: int, sandbox: bool | None = None) -> list[str]:
    """espeak-ng, text in on stdin and WAV out on stdout; inside bubblewrap when it is there (docs/SPEAK.md §9).

    The reader parses untrusted text (a mail, a PDF page). In the sandbox it has no network, no home, no
    devices and nothing writable; the sound leaves it only as bytes on standard output.
    """
    inner = [READER, "-v", voice_for(lang), "-s", str(clamp_rate(rate)), "--stdin", "--stdout"]
    if sandbox is None:
        sandbox = shutil.which("bwrap") is not None
    if not sandbox:
        return inner
    return [
        "bwrap",
        "--ro-bind", "/usr", "/usr",
        "--symlink", "usr/bin", "/bin",
        "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib64", "/lib64",
        "--ro-bind-try", "/etc/ld.so.cache", "/etc/ld.so.cache",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        "--cap-drop", "ALL",
        "--clearenv",
        "--setenv", "PATH", "/usr/bin",
        "--",
        *inner,
    ]


def runtime_dir(environ: dict[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    base = env.get("XDG_RUNTIME_DIR") or f"/tmp/dai-{os.getuid()}"
    return Path(base) / "dai"


def pid_file(environ: dict[str, str] | None = None) -> Path:
    return runtime_dir(environ) / "speak.pid"


def _comm(pid: int, proc: Path = Path("/proc")) -> str:
    try:
        return (proc / str(pid) / "comm").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def running_reader(path: Path, proc: Path = Path("/proc")) -> int | None:
    """The pid in the file, only when that process is still espeak-ng; a stale or foreign pid is ignored."""
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    if pid <= 1 or _comm(pid, proc) not in (READER, "bwrap"):
        return None
    return pid


def stop(path: Path | None = None, proc: Path = Path("/proc"), kill: Callable[[int, int], None] = os.killpg) -> bool:
    """Stop the running reader and its player (one process group). True when there was one."""
    path = pid_file() if path is None else path
    pid = running_reader(path, proc)
    try:
        path.unlink()
    except OSError:
        pass
    if pid is None:
        return False
    try:
        kill(pid, signal.SIGTERM)
    except OSError:
        return False
    return True


def cut(text: str) -> str:
    text = text.strip()
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT]


def start(text: str, lang: str, rate: int, wav: Path | None = None, path: Path | None = None,
          popen=subprocess.Popen, proc: Path = Path("/proc")) -> int:
    """Start reading `text` (stopping a reader already running) and remember its pid. Returns the pid."""
    text = cut(text)
    if not text:
        raise SpeakError(pick(lang, "There is nothing to read.", "אין מה להקריא."))
    path = pid_file() if path is None else path
    stop(path, proc)
    argv = reader_argv(language_of(text, lang), rate)
    out = None
    if wav is not None:
        try:
            out = wav.open("wb")
        except OSError as exc:
            raise SpeakError(pick(lang, "The reader could not write {path}.", "הקורא לא הצליח לכתוב את {path}.").format(path=wav)) from exc
    try:
        child = popen(argv, stdin=subprocess.PIPE, stdout=out if out is not None else subprocess.PIPE,
                      stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        raise SpeakError(pick(lang, "The reader (espeak-ng) is not installed: {error}",
                              "הקורא (espeak-ng) לא מותקן: {error}").format(error=exc.strerror or exc)) from exc
    finally:
        if out is not None:
            out.close()
    if wav is None:
        # The sound goes from the reader's stdout to the player, in the reader's process group, so one stop ends both.
        try:
            popen([PLAYER, "-"], stdin=child.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                  process_group=child.pid)
        except OSError as exc:
            child.kill()
            raise SpeakError(pick(lang, "The player ({player}) is not installed: {error}",
                                  "הנגן ({player}) לא מותקן: {error}").format(player=PLAYER, error=exc.strerror or exc)) from exc
        if child.stdout is not None:
            child.stdout.close()      # only the player keeps the pipe
    assert child.stdin is not None
    try:
        child.stdin.write(text.encode("utf-8"))
        child.stdin.close()
    except OSError:
        pass
    if wav is None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(child.pid), encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
    else:
        child.wait()
        if child.returncode != 0:
            raise SpeakError(pick(lang, "The reader could not write {path}.", "הקורא לא הצליח לכתוב את {path}.").format(path=wav))
    return child.pid


def selection(run=subprocess.run) -> str:
    """The primary selection, else the clipboard, as text; empty when there is none."""
    for argv in (["wl-paste", "-p", "-n", "-t", "text"], ["wl-paste", "-n", "-t", "text"]):
        try:
            result = run(argv, capture_output=True, timeout=3, check=False)
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0 and result.stdout:
            data = result.stdout
            return (data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)).strip()
    return ""


def notify(lang: str, run=subprocess.Popen) -> None:
    """A small notice without the text itself (it may be private; notifications are kept in a log)."""
    title = pick(lang, "Diamond is reading", "Diamond מקריא")
    body = pick(lang, "Super+Shift+S stops it", "Super+Shift+S עוצר")
    try:
        run(["notify-send", "-a", "D.Ai", "-i", "audio-speakers", "-t", "4000", title, body],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass
