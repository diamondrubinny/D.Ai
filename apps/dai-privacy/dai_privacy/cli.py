# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-privacy: who is using the microphone and camera.

  dai-privacy status [--json]          right now
  dai-privacy log [--days N] [--json]  the last 30 days (kept only on this computer)
  dai-privacy watch                    print and log changes (no window)
  dai-privacy tray                     the panel indicator (started at login)
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime

from . import __author__, __version__
from .log import append, changes, log_path, read
from .sensors import current
from .text import describe, lang, t


def _days(args: list[str]) -> float:
    if "--days" in args:
        index = args.index("--days")
        try:
            return max(0.0, min(float(args[index + 1]), 30.0))
        except (IndexError, ValueError):
            pass
    return 30.0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv[1:])
    if "--version" in args:
        print(f"dai-privacy {__version__} — {__author__}")
        return 0
    command = args[0] if args and not args[0].startswith("-") else "status"
    language = lang()
    as_json = "--json" in args
    if command == "status":
        uses = current()
        if as_json:
            print(json.dumps([u.__dict__ for u in uses], ensure_ascii=False))
        else:
            print("\n".join(describe(u, language) for u in uses) or t("nothing", language))
        return 0
    if command == "log":
        days = _days(args)
        entries = read(log_path(), days)
        if as_json:
            print(json.dumps(entries, ensure_ascii=False, indent=2))
        elif not entries:
            print(t("log_empty", language, days=f"{days:g}"))
        for entry in [] if as_json else entries:
            from .sensors import Use

            use = Use(entry.get("device", "video"), entry.get("app", "?"), entry.get("pid", 0))
            when = datetime.fromtimestamp(entry["time"]).strftime("%Y-%m-%d %H:%M")
            mark = "▶" if entry.get("event") == "start" else "■"
            print(f"{when}  {mark} {describe(use, language, stopped=entry.get('event') == 'stop')}")
        return 0
    if command == "watch":
        before: set = set()
        try:
            while True:
                now = set(current())
                events = changes(before, now)
                append(log_path(), events)
                for kind, use in events:
                    print(describe(use, language, stopped=kind == "stop"), flush=True)
                before = now
                time.sleep(2)
        except KeyboardInterrupt:
            return 0
    if command == "tray":
        from .tray import main as tray_main

        return tray_main()
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
