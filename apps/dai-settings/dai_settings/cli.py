# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-settings: one window for the settings D.Ai Tune knows (docs/BEYOND.md §6).

  dai-settings                open the window
  dai-settings list [--json]  print every setting with its current value (what the window would show)
  dai-settings --version

Every setting is a D.Ai Tune action: the window builds the plan, shows it, applies it through the same root
helper and journal as "dai-tune", and can undo it. "list" changes nothing.
"""
from __future__ import annotations

import json
import sys

from dai_i18n import pick, ui_lang

from .model import GROUPS, SETTINGS, snapshot


def main(argv: list[str] | None = None, ctx=None) -> int:
    args = list(sys.argv if argv is None else argv)[1:]
    lang = ui_lang()
    if args and args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if "--version" in args:
        from . import __author__, __version__
        print(f"dai-settings {__version__} — {__author__}")
        return 0
    if args and args[0] == "list":
        from dai_tune.context import Context
        values = snapshot(ctx or Context(lang=lang))
        if "--json" in args:
            print(json.dumps(values, ensure_ascii=False))
            return 0
        group = None
        for setting in SETTINGS:
            value = values.get(setting.key)
            if value is None and setting.kind != "button":
                continue
            if setting.group != group:
                group = setting.group
                print(pick(lang, *GROUPS[group]))
            if setting.kind == "button":
                shown = pick(lang, "(action)", "(פעולה)")
            elif setting.kind == "toggle":
                shown = pick(lang, "on", "פועל") if value else pick(lang, "off", "כבוי")
            elif setting.kind == "choice":
                shown = setting.choice_label(str(value), lang)
            else:
                shown = str(value)
            print(f"  {setting.label(lang)}: {shown}")
        return 0
    if args:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    from .gui import main as window
    return window(["dai-settings"])
