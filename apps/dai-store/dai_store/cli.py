# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-store: find and set up software, with the plan first (docs/BEYOND.md §9).

  dai-store                 open the window
  dai-store list            the recipes by category, with what each one sets up
  dai-store search TEXT     Flathub's apps matching TEXT (flatpak's own index)
  dai-store --version

Setting something up goes through D.Ai Tune's plan, root helper and journal, like D.Ai Forge; "list" and
"search" change nothing.
"""
from __future__ import annotations

import sys

from dai_i18n import pick, ui_lang

from .catalog import CATEGORIES, flathub_search, recipe_items, search


def main(argv: list[str] | None = None, library=None) -> int:
    args = list(sys.argv if argv is None else argv)[1:]
    lang = ui_lang()
    if args and args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if "--version" in args:
        from . import __author__, __version__
        print(f"dai-store {__version__} — {__author__}")
        return 0
    if args and args[0] == "list":
        items = recipe_items(library)
        for key, names in CATEGORIES.items():
            group = [i for i in items if i.category == key]
            if not group:
                continue
            print(pick(lang, *names))
            for item in group:
                print(f"  {item.name(lang)}: {item.about(lang)}")
                for line in item.sets_up(lang):
                    print(f"      • {line}")
        return 0
    if args and args[0] == "search":
        found = search(flathub_search(" ".join(args[1:])), "", lang)
        if not found:
            print(pick(lang, "Nothing found (is Flathub set up? dai-store list).", "לא נמצא (האם Flathub מוגדר? dai-store list)."))
            return 1
        for item in found:
            print(f"{item.id}  {item.name(lang)}: {item.about(lang)}")
        return 0
    if args:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    from .gui import main as window
    return window(["dai-store"])
