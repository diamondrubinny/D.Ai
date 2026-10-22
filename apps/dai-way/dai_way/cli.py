# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-way: a whole computer in one readable file (docs/WAY.md).

  dai-way check FILE.dway        every line understood? the plan valid? (nothing changes)
  dai-way plan FILE.dway         show the whole plan
  dai-way apply FILE.dway        show, confirm, apply through D.Ai Tune (undo: dai-way undo)
  dai-way undo                   undo the last change
  dai-way export [FILE.dway]     this computer as a file (to the screen without FILE)
  dai-way examples               the built-in examples
  dai-way --version

Sentences are D.Ai Tune's, apps are D.Ai Forge's recipes or Flathub ids, exact lines are the catalog's own
form. One plan for the whole file: one line not understood and nothing is applied.
"""
from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

from dai_i18n import pick, ui_lang
from dai_tune.cli import cmd_undo, execute_plan
from dai_tune.context import Context

from . import __author__, __version__
from .language import WayError, parse
from .planner import compile_program

EXAMPLES = Path(os.environ.get("DAI_WAY_EXAMPLES", "/usr/share/dai/way"))


def _say(lang: str, en: str, he: str, **kwargs: object) -> str:
    return pick(lang, en, he).format(**kwargs)


def load(path: str, ctx: Context):
    lang = ctx.lang
    try:
        program = parse(Path(path))
    except WayError as exc:
        print(_say(lang, "✗ {error}", "✗ {error}", error=exc), file=sys.stderr)
        return None, None
    compiled = compile_program(program, ctx)
    if compiled.problems:
        print(_say(lang, "✗ {name}: {n} problem(s); nothing was changed.", "✗ {name}: {n} בעיות; לא בוצע שום שינוי.",
                   name=program.name or path, n=len(compiled.problems)), file=sys.stderr)
        for problem in compiled.problems:
            print("  " + problem, file=sys.stderr)
        return program, None
    return program, compiled


def main(argv: list[str] | None = None, ctx: Context | None = None) -> int:
    args = list(sys.argv if argv is None else argv)[1:]
    lang = ui_lang()
    ctx = ctx or Context(lang=lang)
    if not args or args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if "--version" in args:
        print(f"dai-way {__version__} — {__author__}")
        return 0
    command, rest = args[0], args[1:]
    if command == "examples":
        found = sorted(EXAMPLES.glob("*.dway")) if EXAMPLES.is_dir() else []
        if not found:
            print(_say(lang, "No examples in {dir}.", "אין דוגמאות ב־{dir}.", dir=EXAMPLES))
            return 1
        for path in found:
            first = next((l.strip("# ").strip() for l in path.read_text(encoding="utf-8").splitlines() if l.startswith("#")), "")
            print(f"{path}  {first}")
        return 0
    if command == "undo":
        return cmd_undo(rest[0] if rest else "last", ctx)
    if command == "export":
        from .export import export_text
        text = export_text(ctx, lang, hostname=socket.gethostname() or "this computer")
        if rest:
            Path(rest[0]).write_text(text, encoding="utf-8")
            print(_say(lang, "✓ Written: {path}. Check it: dai-way check {path}", "✓ נכתב: {path}. לבדיקה: dai-way check {path}", path=rest[0]))
        else:
            print(text, end="")
        return 0
    if command in ("check", "plan", "apply") and rest:
        program, compiled = load(rest[0], ctx)
        if compiled is None:
            return 2
        heading = _say(lang, "Diamond's Way — {name}", "דרך היהלום — {name}", name=program.name or Path(rest[0]).name)
        if command == "check":
            print(_say(lang, "✓ {name}: {n} steps, every line understood ({files}).",
                       "✓ {name}: {n} צעדים, כל השורות הובנו ({files}).",
                       name=program.name or Path(rest[0]).name, n=len(compiled.plan.steps), files=", ".join(program.files)))
            return 0
        return execute_plan(compiled.plan, ctx, dry_run=command == "plan", assume_yes="--yes" in rest,
                            heading=heading, label=f"Way: {program.name or Path(rest[0]).name}")
    print(__doc__.strip(), file=sys.stderr)
    return 2
