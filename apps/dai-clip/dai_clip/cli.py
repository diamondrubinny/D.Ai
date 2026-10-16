# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-clip: clipboard history that never keeps passwords (docs/CLIP.md).

  dai-clip                  the history window (Super+V)
  dai-clip list [--json]    what is kept now (newest first)
  dai-clip clear            forget everything
  dai-clip pause [MINUTES]  keep nothing for a while (default 10)
  dai-clip resume
  dai-clip off | on         turn the history off (and clear it) / back on
  dai-clip status
  dai-clip watch            follow the clipboard (started at login)
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from typing import Callable

from . import __author__, __version__
from .secrets import Verdict, classify, marked_sensitive
from .store import MAX_CHARS, History, is_off, runtime_dir, set_off
from .text import clock, lang, preview, t

CLEAR_AFTER_SECONDS = 90
# UTF-8 takes at most 4 bytes per character; anything longer is over MAX_CHARS.
MAX_INPUT_BYTES = MAX_CHARS * 4


def offered_types(run: Callable = subprocess.run) -> list[str] | None:
    """MIME types of the current selection, or None when they cannot be read."""
    try:
        result = run(["wl-paste", "--list-types"], capture_output=True, text=True, timeout=2, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.split() if result.returncode == 0 else None


def store(data: bytes, state: str | None, types: Callable[[], list[str] | None], history: History | None,
          env: dict | None = None) -> tuple[str, Verdict | None]:
    """Keep one clipboard change, unless it must not be kept. Returns (outcome, verdict)."""
    if state == "sensitive":
        return "sensitive", None
    if state in ("nil", "clear"):
        return "empty", None
    if history is None:
        return "no-runtime", None
    if is_off(env):
        return "off", None
    if history.paused_until() is not None:
        return "paused", None
    offered = types()
    if offered is None or marked_sensitive(state, offered):
        return "sensitive", None  # fail closed: unknown types are treated as a password manager's
    if len(data) > MAX_INPUT_BYTES:
        return "too-large", None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "binary", None
    if "\x00" in text:
        return "binary", None
    if (verdict := classify(text)) is not None:
        return "secret", verdict
    return ("stored", None) if history.add(text) else ("empty", None)


def schedule_clear(text: str, delay: float = CLEAR_AFTER_SECONDS) -> None:
    """Empty the clipboard after `delay` seconds if it still holds `text`.

    Runs in a detached child so wl-paste (which waits for us) is not held up.
    Only a digest is kept, and it is never put in argv or the environment.
    """
    digest = hashlib.sha256(text.encode()).digest()
    if os.fork():
        return
    try:
        os.setsid()
        devnull = os.open(os.devnull, os.O_RDWR)
        for fd in (0, 1, 2):
            os.dup2(devnull, fd)
        time.sleep(delay)
        current = subprocess.run(["wl-paste", "--no-newline", "--type", "text"], capture_output=True,
                                 timeout=5, check=False).stdout
        if hashlib.sha256(current).digest() == digest:
            subprocess.run(["wl-copy", "--clear"], timeout=5, check=False)
    finally:
        os._exit(0)


def _history() -> History | None:
    folder = runtime_dir()
    return History(folder) if folder else None


def cmd_store() -> int:
    data = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    outcome, verdict = store(data, os.environ.get("CLIPBOARD_STATE"), offered_types, _history())
    if verdict is not None and verdict.clear:
        schedule_clear(data.decode("utf-8"))
    if os.environ.get("DAI_CLIP_DEBUG"):
        print(outcome, verdict.kind if verdict else "", file=sys.stderr)  # never the content
    return 0


def cmd_watch(language: str) -> int:
    if not shutil.which("wl-paste") or not os.environ.get("WAYLAND_DISPLAY"):
        print(t("no_wayland", language), file=sys.stderr)
        return 1
    # Text only: without a text type, wl-paste does not run the command at all.
    os.execvp("wl-paste", ["wl-paste", "--type", "text", "--watch", "dai-clip", "_store"])
    return 1  # not reached


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv[1:])
    if "--version" in args:
        print(f"dai-clip {__version__} — {__author__}")
        return 0
    if "-h" in args or "--help" in args:
        print(__doc__.strip())
        return 0
    language = lang()
    command = args[0] if args else "show"
    if command == "_store":
        return cmd_store()
    if command == "watch":
        return cmd_watch(language)
    if command in ("on", "off"):
        set_off(command == "off")
        if command == "off" and (history := _history()):
            history.clear()
        print(t(command, language))
        return 0

    history = _history()
    if history is None:
        print(t("no_runtime", language), file=sys.stderr)
        return 1
    if command == "show":
        from .gui import main as gui_main

        return gui_main(history)
    if command == "list":
        items = history.items()
        if "--json" in args:
            print(json.dumps([item.__dict__ for item in items], ensure_ascii=False, indent=2))
        else:
            for number, item in enumerate(items, 1):
                print(f"{number:2}. {clock(item.time)}  {preview(item.text)}")
            if not items:
                print(t("empty", language))
        return 0
    if command == "clear":
        history.clear()
        print(t("cleared", language))
        return 0
    if command == "pause":
        try:
            minutes = max(1.0, min(float(args[1]), 24 * 60)) if len(args) > 1 else 10.0
        except ValueError:
            minutes = 10.0
        print(t("paused", language, time=clock(history.pause(minutes))))
        return 0
    if command == "resume":
        history.resume()
        print(t("resumed", language))
        return 0
    if command == "status":
        count = len(history.items())
        if is_off():
            print(t("status_off", language))
        elif (until := history.paused_until()) is not None:
            print(t("status_paused", language, time=clock(until), n=count))
        else:
            print(t("status_on", language, n=count))
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2
