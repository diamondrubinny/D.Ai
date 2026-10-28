# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-explain: what is on the screen, explained (docs/EXPLAIN.md).

  dai-explain                     a picture of the whole screen -> the explanation in a window (Super+Shift+E)
  dai-explain --area              choose an area with the mouse first
  dai-explain --file IMAGE        a picture from a file
  dai-explain --text "..."        this text, no picture
  dai-explain --print             the explanation to standard output instead of a window
  dai-explain --version

The picture and its text stay in memory and are not saved. Diamond answers on this computer unless you chose
an AI provider for general questions; then the screen text goes to that provider, and the window says so.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from dai_i18n import pick, ui_lang

from . import __author__, __version__
from .engine import ExplainError, capture_screen, choose_area, explain, read_text, where_label

FLAGS = ("--area", "--file", "--text", "--print", "--lang")


def _option(args: list[str], name: str) -> str | None:
    if name in args:
        at = args.index(name)
        return args[at + 1] if at + 1 < len(args) else None
    return None


def gather_text(args: list[str], lang: str, run=subprocess.run) -> str:
    """The text to explain, from --text, --file, --area or the whole screen."""
    if (given := _option(args, "--text")) is not None:
        return given
    if (path := _option(args, "--file")) is not None:
        image = Path(path).read_bytes()
    elif "--area" in args:
        area = choose_area(run)
        if area is None:
            raise ExplainError(pick(lang, "No area was chosen.", "לא נבחר אזור."))
        image = capture_screen(run, area)
    else:
        image = capture_screen(run)
    return read_text(image, lang, run)


def main(argv: list[str] | None = None, run=subprocess.run, chat=None) -> int:
    args = list(sys.argv if argv is None else argv)[1:]
    lang = _option(args, "--lang") or ui_lang()
    if args and args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if "--version" in args:
        print(f"dai-explain {__version__} — {__author__}")
        return 0
    if any(a.startswith("-") and a not in FLAGS for a in args):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    if "--print" not in args:
        from .gui import main as window
        return window(["dai-explain", *args])
    try:
        text = gather_text(args, lang, run)
        result = explain(text, lang, chat=chat, on_piece=lambda piece: (sys.stdout.write(piece), sys.stdout.flush()))
    except (ExplainError, OSError) as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    print()
    if result.suggestion:
        print(pick(lang, "Suggested: dai-tune \"{sentence}\"", "הצעה: dai-tune \"{sentence}\"").format(sentence=result.suggestion))
    print(where_label(lang), file=sys.stderr)
    return 0
