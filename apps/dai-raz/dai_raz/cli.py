# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-raz: is every part of D.Ai still working? (docs/RAZ.md)

  dai-raz check [--json]   run every check now (exit 1 when one failed); the result is kept for comparing
  dai-raz last [--json]    the last result
  dai-raz forget           delete what Raz kept
  dai-raz --version
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from dai_i18n import pick, text, ui_lang

from . import __author__, __version__
from .checks import Result, run_all, to_json

TITLES = {
    "commands": ("D.Ai commands start", "פקודות D.Ai עולות"),
    "panel": ("Taskbar plugins are loaded", "התוספים של שורת המשימות נטענו"),
    "services": ("Background services are on", "שירותי הרקע פועלים"),
    "files": ("Protected settings are intact", "ההגדרות המוגנות שלמות"),
    "packages": ("D.Ai's files are as installed", "הקבצים של D.Ai כפי שהותקנו"),
    "firewall": ("The firewall is on", "חומת האש פועלת"),
    "updates": ("Security updates install by themselves", "עדכוני אבטחה מותקנים לבד"),
    "posture": ("The security score can be computed", "אפשר לחשב את ציון האבטחה"),
    "languages": ("Every language works", "כל השפות עובדות"),
}
SUMMARY = ("{ok} passed · {failed} failed · {skipped} not applicable here",
           "{ok} עברו · {failed} נכשלו · {skipped} לא רלוונטיות כאן")
MARK = {"ok": "✓", "failed": "✗", "skipped": "–"}
KEEP_DAYS = 90


def state_dir() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    return base / "dai" / "raz"


def save(results: list[Result], directory: Path | None = None) -> None:
    directory = directory or state_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    data = json.dumps({"time": time.time(), "results": json.loads(to_json(results))}, ensure_ascii=False)
    for name in ("last.json", f"run-{stamp}.json"):
        fd, tmp = tempfile.mkstemp(dir=directory)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
        os.chmod(tmp, 0o600)
        os.replace(tmp, directory / name)
    cutoff = time.time() - KEEP_DAYS * 86400
    for old in directory.glob("run-*.json"):  # kept for 90 days (docs/RAZ.md §5)
        if old.stat().st_mtime < cutoff:
            old.unlink(missing_ok=True)


def show(results: list[Result], lang: str) -> str:
    lines = ["Raz · D.Ai"]
    for r in results:
        title = pick(lang, *TITLES[r.id]) if r.id in TITLES else r.id
        lines.append(f"{MARK.get(r.status, '?')} {title} ({r.detail})" if r.detail else f"{MARK.get(r.status, '?')} {title}")
        lines += [f"    · {item}" for item in r.items]
    counts = {s: sum(r.status == s for r in results) for s in ("ok", "failed", "skipped")}
    lines.append(text(lang, *SUMMARY, **counts))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv[1:])
    lang = ui_lang()
    if "--version" in args:
        print(f"dai-raz {__version__} — {__author__}")
        return 0
    if not args or "-h" in args or "--help" in args:
        print(__doc__.strip())
        return 0 if args else 2
    command = args[0]
    if command == "check":
        results = run_all()
        try:
            save(results)
        except OSError:
            pass  # a read-only home must not hide the result
        print(to_json(results) if "--json" in args else show(results, lang))
        return 1 if any(r.status == "failed" for r in results) else 0
    if command == "last":
        try:
            data = json.loads((state_dir() / "last.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            print(pick(lang, "Raz has not checked yet: dai-raz check", "Raz עוד לא בדק: dai-raz check"))
            return 1
        if "--json" in args:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            print(time.strftime("%d.%m.%Y %H:%M", time.localtime(data.get("time", 0))))
            print(show([Result(**r) for r in data.get("results", [])], lang))
        return 0
    if command == "forget":
        shutil.rmtree(state_dir(), ignore_errors=True)
        print(pick(lang, "Deleted.", "נמחק."))
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2
