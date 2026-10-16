# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-code: a local coding assistant for the project in the current folder.

  dai-code ask "question"            answer from the relevant project files
  dai-code explain FILE[:A-B]        explain a file or a line range
  dai-code edit FILE "change"        propose an edit as a diff; confirm; back up; undo
  dai-code review                    review uncommitted changes (git diff)
  dai-code commit-msg                suggest a commit message for staged changes
  dai-code undo [ID] [--force] | history
Options: --yes  --dry-run  --root DIR
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from . import __author__, __version__, ai, edits
from .project import MAX_EDIT, Project, ProjectError

MAX_DIFF = 14_000


def _he() -> bool:
    import os
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if value:
            return value.startswith("he")
    return False


def _l(en: str, he: str) -> str:
    return he if _he() else en


def _color(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if sys.stdout.isatty() else text


def show_diff(diff: str) -> None:
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            print(_color(line, "32"))
        elif line.startswith("-") and not line.startswith("---"):
            print(_color(line, "31"))
        elif line.startswith("@@"):
            print(_color(line, "36"))
        else:
            print(line)


def _stream(chat, prompt: str, max_tokens: int = 1200) -> int:
    got = False
    for piece in ai.stream_text(chat, prompt, max_tokens):
        got = True
        print(piece, end="", flush=True)
    print()
    return 0 if got else 1


def _git(project: Project, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(project.root), *args], capture_output=True, text=True, timeout=30,
                         check=False)
    if out.returncode != 0:
        raise ProjectError(out.stderr.strip() or "git failed (is this a git repository?)")
    return out.stdout


def _target(spec: str) -> tuple[str, tuple[int, int] | None]:
    match = re.fullmatch(r"(.+?):(\d+)-(\d+)", spec)
    if match:
        start, end = int(match.group(2)), int(match.group(3))
        if start < 1 or end < start:
            raise ProjectError("line range must be START-END with 1 <= START <= END")
        return match.group(1), (start, end)
    return spec, None


def cmd_explain(project: Project, spec: str, chat) -> int:
    name, lines = _target(spec)
    path = project.resolve(name)
    text = project.read_text(path.relative_to(project.root))
    if text is None:
        raise ProjectError(f"{name}: not a readable text file (or larger than 64 KB)")
    if lines:
        text = "\n".join(text.splitlines()[lines[0] - 1:lines[1]])
    if len(text) > 16_000:
        text = text[:16_000] + "\n… (truncated)"
    return _stream(chat, ai.explain_prompt(str(path.relative_to(project.root)), text, lines))


def cmd_edit(project: Project, name: str, instruction: str, chat, assume_yes: bool, dry_run: bool) -> int:
    path = project.resolve(name, for_edit=True)
    rel = str(path.relative_to(project.root))
    original = ""
    if path.exists():
        raw = path.read_bytes()
        if len(raw) > MAX_EDIT:
            raise ProjectError(_l(f"{rel} is larger than {MAX_EDIT // 1024} KB; edit a smaller file or a part of it",
                                  f"{rel} גדול מ־{MAX_EDIT // 1024}KB; ערכו קובץ קטן יותר"))
        try:
            original = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProjectError(f"{rel} is not UTF-8 text") from exc
    print(_l(f"Asking the local AI to edit {rel}…", f"מבקש מה־AI המקומי לערוך את {rel}…"), file=sys.stderr)

    def progress(reply: str) -> None:
        if sys.stderr.isatty():
            print(f"\r  {len(reply):,}", end="", file=sys.stderr, flush=True)

    result = ai.edit(rel, original, instruction, chat, progress)
    if sys.stderr.isatty():
        print(file=sys.stderr)
    diff = edits.unified(rel, original, result["content"])
    if not diff:
        print(_l("The AI proposed no change.", "ה־AI לא הציע שינוי."))
        return 0
    if result["summary"]:
        print(_color("✦ " + result["summary"], "1;35"))
    show_diff(diff)
    if dry_run:
        print(_l("(dry run — nothing was written)", "(הרצת ניסיון — לא נכתב דבר)"))
        return 0
    if not assume_yes:
        answer = input(_l("Apply this change? [y/N] ", "להחיל את השינוי? [כ/ל] ")).strip().casefold()
        if answer not in ("y", "yes", "כ", "כן"):
            print(_l("Cancelled. Nothing was written.", "בוטל. לא נכתב דבר."))
            return 1
    entry = edits.apply(project.root, path, result["content"], result["summary"], instruction)
    print(_color(_l(f"✓ Applied ({entry['id']}). Undo: dai-code undo", f"✓ הוחל ({entry['id']}). ביטול: dai-code undo"),
                 "32"))
    return 0


def cmd_history(project: Project) -> int:
    items = edits.entries(project.root)
    if not items:
        print(_l("No edits yet.", "עדיין אין עריכות."))
    for item in items[-20:]:
        mark = "✓" if item.get("status") == "applied" else "↶"
        print(f"{mark} {item['id']}  {item['file']}  {item.get('summary', '')[:80]}")
    return 0


def _value(args: list[str], name: str) -> str | None:
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            value = args[index + 1]
            del args[index:index + 2]
            return value
        raise ProjectError(f"{name} needs a value")
    return None


def main(argv: list[str] | None = None, chat=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv[1:])
    if "--version" in args:
        print(f"dai-code {__version__} — {__author__}")
        return 0
    try:
        root = _value(args, "--root")
        flags = {a for a in args if a in ("--yes", "--dry-run", "--force", "--help")}
        words = [a for a in args if a not in flags]
        if not words or "--help" in flags or words[0] in ("help", "עזרה"):
            print(__doc__.strip().split("\n\n", 1)[1])
            return 0
        project = Project.open(Path(root) if root else None)
        command = words[0]
        if command == "history":
            return cmd_history(project)
        if command == "undo":
            entry = edits.undo(project.root, words[1] if len(words) > 1 else "last", force="--force" in flags)
            print(_color(_l(f"✓ Restored {entry['file']}", f"✓ שוחזר {entry['file']}"), "32"))
            return 0
        chat = chat or ai.default_chat()
        if command == "ask" and len(words) >= 2:
            question = " ".join(words[1:])
            return _stream(chat, ai.ask_prompt(question, project.tree(), project.context_for(question)))
        if command == "explain" and len(words) == 2:
            return cmd_explain(project, words[1], chat)
        if command == "edit" and len(words) >= 3:
            return cmd_edit(project, words[1], " ".join(words[2:]), chat, "--yes" in flags, "--dry-run" in flags)
        if command == "review":
            diff = _git(project, "diff", "--no-color")
            if not diff.strip():
                print(_l("No uncommitted changes to review.", "אין שינויים שלא נשמרו לסקירה."))
                return 0
            return _stream(chat, ai.review_prompt(diff[:MAX_DIFF]), 1500)
        if command == "commit-msg":
            diff = _git(project, "diff", "--cached", "--no-color")
            if not diff.strip():
                print(_l("Nothing is staged (git add first).", "אין שינויים ב־stage (הריצו git add)."))
                return 1
            return _stream(chat, ai.commit_prompt(diff[:MAX_DIFF]), 300)
    except (ProjectError, ValueError, ai.AIError) as exc:
        print(_color(f"✗ {exc}", "31"), file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print()
        return 1
    print(__doc__.strip().split("\n\n", 1)[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
