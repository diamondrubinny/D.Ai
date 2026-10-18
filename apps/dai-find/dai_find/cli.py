# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-find: find files the way you remember them.

  dai-find "the pdf I downloaded last week"
  dai-find "התמונות מאתמול"
  dai-find --json "invoice from March"
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dai_i18n import pick, ui_lang

from . import __author__, __version__
from .query import parse
from .search import human_size, search


def _lang() -> str:
    return ui_lang()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv[1:])
    if "--version" in args:
        print(f"dai-find {__version__} — {__author__}")
        return 0
    as_json = "--json" in args
    words = [a for a in args if a not in ("--json",)]
    if not words or words[0] in ("-h", "--help", "help", "עזרה"):
        print(__doc__.strip())
        return 0
    lang = _lang()
    query = parse(" ".join(words), lang=lang)
    if not query.specific:
        print(pick(lang, "Say what to look for: a type, a time, a folder or part of the name.",
                   "כתבו מה לחפש: סוג, זמן, תיקייה או חלק מהשם."), file=sys.stderr)
        return 2
    hits = search(query, Path.home())
    if as_json:
        print(json.dumps({
            "query": {"kinds": sorted(query.kinds), "since": query.since.isoformat() if query.since else None,
                      "until": query.until.isoformat() if query.until else None, "folders": query.folders,
                      "words": query.words},
            "results": [{"path": str(h.path), "date": h.date.isoformat(timespec="minutes"), "size": h.size,
                         "kind": h.kind} for h in hits],
        }, ensure_ascii=False, indent=2))
        return 0 if hits else 1
    if not hits:
        print(pick(lang, "Nothing found.", "לא נמצא כלום."))
        return 1
    home = str(Path.home())
    for hit in hits:
        shown = str(hit.path).replace(home, "~", 1)
        print(f"{hit.date:%Y-%m-%d %H:%M}  {human_size(hit.size):>9}  {shown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
