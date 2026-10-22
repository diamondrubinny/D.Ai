# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-find: find files the way you remember them.

  dai-find "the pdf I downloaded last week"
  dai-find "התמונות מאתמול"
  dai-find --json "invoice from March"
  dai-find "the document about the lease"      inside the files, from the local index
  dai-find index [--status | --clear | --quiet] build the content index now (a user timer does it too)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dai_i18n import pick, ui_lang

from . import __author__, __version__
from .query import parse
from .search import _listing, human_size, search


def _lang() -> str:
    return ui_lang()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv[1:])
    if "--version" in args:
        print(f"dai-find {__version__} — {__author__}")
        return 0
    if args and args[0] == "index":
        return index_command(args[1:], ui_lang())
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
                         "kind": h.kind, "snippet": h.snippet} for h in hits],
        }, ensure_ascii=False, indent=2))
        return 0 if hits else 1
    if not hits:
        print(pick(lang, "Nothing found.", "לא נמצא כלום."))
        return 1
    home = str(Path.home())
    for hit in hits:
        shown = str(hit.path).replace(home, "~", 1)
        print(f"{hit.date:%Y-%m-%d %H:%M}  {human_size(hit.size):>9}  {shown}")
        if hit.snippet:
            print(f"{'':28}“{hit.snippet}”")
    return 0


def index_command(args: list[str], lang: str, home: Path | None = None) -> int:
    """dai-find index: the content index of the home folder (docs/BEYOND.md §11)."""
    from . import index
    home = (home or Path.home()).resolve()
    quiet = "--quiet" in args
    if "--clear" in args:
        gone = index.clear(home)
        if not quiet:
            print(pick(lang, "The content index was deleted.", "אינדקס התוכן נמחק.") if gone
                  else pick(lang, "There is no content index.", "אין אינדקס תוכן."))
        return 0
    if "--status" in args:
        count = index.status(home)
        if count is None:
            print(pick(lang, "No content index yet (dai-find index builds it).", "עדיין אין אינדקס תוכן (dai-find index בונה אותו)."))
            return 1
        print(pick(lang, "{n} documents in the content index.", "{n} מסמכים באינדקס התוכן.").format(n=count))
        return 0
    entries, _ = _listing(home, 200_000, 60.0, 0.0)
    report = index.build(home, entries)
    if not quiet:
        print(pick(lang, "Read {read}, forgot {gone}, {total} documents in the index{more}.",
                   "נקראו {read}, נשכחו {gone}, {total} מסמכים באינדקס{more}.").format(
            read=report.indexed, gone=report.removed, total=report.total,
            more="" if report.complete else pick(lang, " (more next time)", " (עוד בפעם הבאה)")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
