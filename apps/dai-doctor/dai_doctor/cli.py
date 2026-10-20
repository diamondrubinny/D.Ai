# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-doctor: why is my computer slow, what fills my disk, how is my battery.

  dai-doctor               everything
  dai-doctor slow | disk | battery | hardware   ("will my Wi-Fi/printer work?", also in the live session)
  dai-doctor machine                            why Windows (a D.Ai VM machine) is slow
  dai-doctor --json        for scripts
  Fixes are offered one by one: system changes go through D.Ai Tune (undo),
  the trash and picture previews are emptied only after you confirm.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from dai_i18n import pick, text, ui_lang

from . import __author__, __version__
from .clean import clean_user
from .diagnose import TOPICS, diagnose, size
from .facts import collect

MARK = {"ok": ("✓", "32"), "warn": ("⚠", "33"), "bad": ("✗", "31")}


def _lang() -> str:
    return ui_lang()


def _color(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if sys.stdout.isatty() else text


def _ask(question: str) -> bool:
    if not sys.stdin.isatty():
        return False
    try:
        return input(question).strip().casefold() in ("y", "yes", "כ", "כן")
    except EOFError:
        return False


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv[1:])
    if "--version" in args:
        print(f"dai-doctor {__version__} — {__author__}")
        return 0
    if args and args[0] in ("-h", "--help", "help", "עזרה"):
        print(__doc__.strip())
        return 0
    as_json = "--json" in args
    # Everything by default, except the hardware list (ask for it: dai-doctor hardware).
    topics = tuple(a for a in args if a in TOPICS) or ("slow", "disk", "battery")
    lang = _lang()
    if not as_json:
        print(pick(lang, "Checking this computer…", "בודק את המחשב…"), file=sys.stderr)
    facts = collect(home=Path.home(), topics=topics)
    findings = diagnose(facts, topics, lang)
    if as_json:
        print(json.dumps([asdict(f) for f in findings], ensure_ascii=False, indent=2))
        return 0
    for finding in findings:
        mark, code = MARK[finding.level]
        print(_color(f"{mark} {finding.title}", code))
        if finding.detail:
            print(f"    {finding.detail}")
        for fix in finding.fixes:
            if fix.kind == "advice":
                print(f"    → {fix.label}")
    fixes = [(f, fix) for f in findings for fix in f.fixes if fix.kind in ("tune", "clean", "forge")]
    for finding, fix in fixes:
        if not _ask(f"\n{fix.label}? [{'כ/ל' if lang == 'he' else 'y/N'}] "):  # i18n: command (the accepted answers)
            continue
        if fix.kind == "tune":
            # The plan is shown, authorized (polkit) and journaled for undo by D.Ai Tune.
            subprocess.run(["dai-tune", fix.payload], check=False)
        elif fix.kind == "forge":
            # Review and the administrator password happen in D.Ai Forge.
            subprocess.run(["dai-forge", fix.payload], check=False)
        elif fix.kind == "clean":
            freed = clean_user(Path.home())
            print(_color(text(lang, "✓ Freed {size}", "✓ פונו {size}", size=size(freed)), "32"))
    if not any(f.level != "ok" for f in findings):
        print(_color(pick(lang, "\nEverything looks fine.", "\nהכל נראה תקין."), "32"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
