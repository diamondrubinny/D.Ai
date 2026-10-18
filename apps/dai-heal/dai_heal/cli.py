# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-heal: when something breaks, a chat explains it and offers a fix (docs/EVOLVE.md §4).

  dai-heal                       the help & repair chat (Super+F1)
  dai-heal chat [--problem KEY]  the chat, opened on one problem (from a notification)
  dai-heal status [--json]       what is broken now
  dai-heal fix KEY [--yes]       offer the fixes for one problem (asks first)
  dai-heal ignore KEY            never ask about this problem again
  dai-heal watch                 notice new problems and offer help (started at login)
"""

from __future__ import annotations

import json
import sys

from . import __author__, __version__
from . import problems as P
from . import fixes as F
from .text import describe, explain, fix_label, lang, t, when
from .watch import Watcher, ignore


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv[1:])
    if "--version" in args:
        print(f"dai-heal {__version__} — {__author__}")
        return 0
    if "-h" in args or "--help" in args:
        print(__doc__.strip())
        return 0
    language = lang()
    command = args[0] if args else "chat"
    if command == "status":
        found = P.collect()
        if "--json" in args:
            print(json.dumps([p.to_json() for p in found], ensure_ascii=False, indent=2))
            return 0
        for problem in found:
            print(f"✗ {describe(problem, language)}  {when(problem, language)}  [{problem.key}]")
            if problem.detail:
                print("    " + problem.detail.strip().splitlines()[-1][:160])
        if not found:
            print(t("status_none", language))
        return 0
    if command == "fix" and len(args) >= 2:
        return cmd_fix(args[1], "--yes" in args, language)
    if command == "ignore" and len(args) == 2:
        ignore(args[1])
        print("✓")
        return 0
    if command == "watch":
        Watcher().run_forever()
        return 0
    if command == "chat":
        focus = args[args.index("--problem") + 1] if "--problem" in args and args.index("--problem") + 1 < len(args) else None
        from .chat import main as chat_main

        return chat_main(focus)
    print(__doc__.strip(), file=sys.stderr)
    return 2


def cmd_fix(key: str, assume_yes: bool, language: str, ask=input) -> int:
    problem = next((p for p in P.collect() if p.key == key), None)
    if problem is None:
        print(t("status_none", language))
        return 1
    print(describe(problem, language))
    print(explain(problem, language))
    for fix in F.fixes_for(problem):
        prompt = f"{fix_label(fix, language)}? [{'כ/ל' if language == 'he' else 'y/N'}] "  # i18n: command (the accepted answers)
        if not assume_yes and ask(prompt).strip().lower() not in ("y", "yes", "כ", "כן"):
            continue
        outcome = F.apply(fix, problem)
        print(t(outcome.key, language, detail=outcome.detail))
        if outcome.key == "still_failing" and outcome.detail:
            print(outcome.detail)
        if outcome.ok:
            return 0
    return 1
