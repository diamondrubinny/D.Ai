# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-record: a video of the screen (docs/RECORD.md).

  dai-record start [SECONDS] [--area] [--file FILE]   start; with SECONDS it stops by itself
  dai-record stop                                     stop and keep the file
  dai-record toggle                                   start (no limit) or stop: Super+Shift+R
  dai-record status
  dai-record --version

The file goes to ~/Videos/Recordings (XDG_VIDEOS_DIR). No sound is recorded. Nothing leaves the computer.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from dai_i18n import pick, ui_lang

from . import __author__, __version__
from .engine import RecordError, choose_area, new_file, notify_saved, notify_started, pid_file, running, start, stop, videos_dir, wait_and_stop


def _option(args: list[str], name: str) -> str | None:
    if name in args:
        at = args.index(name)
        return args[at + 1] if at + 1 < len(args) else None
    return None


def main(argv: list[str] | None = None, run=subprocess.run, popen=subprocess.Popen, pid_path: Path | None = None,
         home: Path | None = None, guard: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)[1:]
    lang = ui_lang()
    if not args or args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if args[0] == "--version":
        print(f"dai-record {__version__} — {__author__}")
        return 0
    path = pid_file() if pid_path is None else pid_path
    command = args[0]
    if command == "_wait" and len(args) == 3 and args[1].isdigit() and args[2].isdigit():
        wait_and_stop(int(args[1]), int(args[2]), path, lang, run=run)
        return 0
    if command == "status":
        state = running(path)
        print(pick(lang, "Recording to {file}", "מקליט אל {file}").format(file=state[1]) if state else pick(lang, "Not recording.", "לא מקליט."))
        return 0
    if command == "stop" or (command == "toggle" and running(path) is not None):
        file = stop(path)
        if file is None:
            print(pick(lang, "Not recording.", "לא מקליט."))
            return 0
        notify_saved(file, lang, run)
        print(file)
        return 0
    if command in ("start", "toggle"):
        rest = args[1:]
        seconds = int(rest[0]) if rest and rest[0].isdigit() else 0
        area = None
        if "--area" in rest:
            area = choose_area(run)
            if area is None:
                print(pick(lang, "No area was chosen.", "לא נבחר אזור."))
                return 0
        file = Path(given) if (given := _option(rest, "--file")) else new_file(videos_dir(home=home))
        try:
            start(file, area, lang, path, seconds, popen, guard=guard)
        except RecordError as exc:
            print(f"✗ {exc}", file=sys.stderr)
            return 1
        notify_started(lang, seconds, run)
        print(file)
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2
