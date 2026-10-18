# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-move: bring your files and bookmarks from Windows.

  dai-move                         look for Windows on connected drives
  dai-move SOURCE [--user NAME]    a Windows drive or a copied user folder
  Options: --dry-run (only show what would be copied), --yes (do not ask)
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

from dai_i18n import text, ui_lang

from . import __author__, __version__
from .browsers import bookmarks_html, outlook_files, wifi_names
from .core import FOLDERS, execute, find_users, mount_points, plan


def _lang() -> str:
    return ui_lang()


def _l(en: str, he: str, **kwargs: object) -> str:
    return text(_lang(), en, he, **kwargs)


def _size(n: int) -> str:
    return f"{n / 2**30:.1f} GB" if n >= 2**30 else f"{n / 2**20:.0f} MB"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv[1:])
    if "--version" in args:
        print(f"dai-move {__version__} — {__author__}")
        return 0
    if args and args[0] in ("-h", "--help", "help", "עזרה"):
        print(__doc__.strip())
        return 0
    user_name = None
    if "--user" in args:
        index = args.index("--user")
        user_name = args[index + 1] if index + 1 < len(args) else None
        del args[index:index + 2]
    flags = {a for a in args if a.startswith("--")}
    positional = [a for a in args if not a.startswith("--")]
    roots = [Path(positional[0]).expanduser()] if positional else mount_points()
    users = [u for u in find_users(roots) if user_name in (None, u.name)]
    if not users:
        print(_l("No Windows user folders found. Connect the Windows drive (or a copy of C:\\Users\\<name>) "
                 "and open it once in the file manager, then try again.\n"
                 "A BitLocker-encrypted drive cannot be read here: copy the files to a USB drive from Windows first.",
                 "לא נמצאו תיקיות משתמש של Windows. חברו את כונן ה־Windows (או העתק של C:\\Users\\<שם>), "
                 "פתחו אותו פעם אחת במנהל הקבצים, ונסו שוב.\n"
                 "כונן שמוצפן ב־BitLocker אי אפשר לקרוא כאן: העתיקו קודם את הקבצים לדיסק און קי מתוך Windows."),
              file=sys.stderr)
        return 1
    if len(users) > 1:
        print(_l("Several Windows users were found; choose one with --user:", "נמצאו כמה משתמשי Windows. בחרו אחד עם ‎--user:"))
        for user in users:
            print(f"  --user {user.name}    ({user.root})")
        return 2
    user, home = users[0], Path.home()
    work = plan(user, home)
    per_folder = Counter(dest.relative_to(home).parts[0] for _, dest in work.copies)
    links_html, links = bookmarks_html(user.home)
    networks = wifi_names(user.root)
    mail_files = outlook_files(user.home)

    print(_l("From Windows user “{name}” ({home}):", "ממשתמש ה־Windows \u200f„{name}” \u200f({home}):",
             name=user.name, home=user.home))
    for folder in FOLDERS.values():
        if per_folder.get(folder):
            print(f"  ~/{folder}: {per_folder[folder]} " + _l("files", "קבצים"))
    print(_l("  Total {copies} files, {_size}", "  סך הכל {copies} קבצים, {_size}",
             copies=len(work.copies), _size=_size(work.bytes)))
    if work.renamed:
        print(_l("  {renamed} names already exist here and get “(Windows)” — nothing is overwritten",
                 "  {renamed} שמות כבר קיימים כאן ויקבלו „(Windows)”. שום דבר לא נדרס", renamed=work.renamed))
    if links:
        print(_l("  {links} bookmarks from Chrome/Edge → ~/Bookmarks-from-Windows.html",
                 "  {links} סימניות מ־Chrome/Edge → \u200f~/Bookmarks-from-Windows.html", links=links))
    if networks:
        print(_l("  Saved Wi-Fi networks (passwords stay encrypted by Windows; enter them once): ",
                 "  רשתות Wi-Fi שמורות (הסיסמאות נשארות מוצפנות אצל Windows, צריך להזין אותן פעם אחת): ")
              + ", ".join(networks))
    if mail_files:
        print(_l("  Outlook mail: {count} files → J's local folders (read through readpst, never changed)",
                 "  דואר של Outlook: {count} קבצים → התיקיות המקומיות של J (נקראים דרך readpst, ולא משתנים)",
                 count=len(mail_files)))
    if "--dry-run" in flags:
        return 0
    if "--yes" not in flags:
        if not sys.stdin.isatty():
            print(_l("Run again with --yes to copy.", "הריצו שוב עם ‎--yes כדי להעתיק."))
            return 0
        if input(_l("Copy now? [y/N] ", "להעתיק עכשיו? [כ/ל] ")).strip().casefold() not in ("y", "yes", "כ", "כן"):
            return 1
    try:
        copied, errors = execute(work, home, lambda i, n: print(f"\r  {i}/{n}", end="", flush=True) if sys.stdout.isatty() else None)
    except OSError as exc:
        print(f"\n✗ {exc}", file=sys.stderr)
        return 1
    if links:
        target = home / "Bookmarks-from-Windows.html"
        if not target.exists():
            target.write_text(links_html, encoding="utf-8")
    print(_l("\n✓ Copied {copied} files.", "\n✓ הועתקו {copied} קבצים.", copied=copied))
    if links:
        print(_l("Firefox: Bookmarks → Manage bookmarks → Import and Backup → Import Bookmarks from HTML.",
                 "‏Firefox: סימניות → ניהול סימניות → ייבוא וגיבוי → ייבוא סימניות מ־HTML."))
    if mail_files:
        errors += import_mail(mail_files)
    for error in errors[:10]:
        print(f"  ✗ {error}", file=sys.stderr)
    return 0 if not errors else 1


def import_mail(files: list[Path], run=subprocess.run, which=shutil.which) -> list[str]:
    """Each Outlook file into J (dai-j import-mail), one at a time; what failed, for the summary."""
    if which("dai-j") is None:
        return [_l("J is not installed: the Outlook files were not imported.", "J לא מותקן: קובצי ה־Outlook לא יובאו.")]
    failed = []
    for path in files:
        print(_l("Importing {name} into J…", "מייבאים את {name} ל־J…", name=path.name))
        try:
            done = run(["dai-j", "import-mail", str(path)], capture_output=True, text=True, timeout=3600)
        except (OSError, subprocess.SubprocessError):
            failed.append(path.name)
            continue
        if done.returncode != 0:
            failed.append(f"{path.name}: {(done.stderr or '').strip()[:200]}")
    if not failed:
        print(_l("✓ Outlook mail is in J, under “On this computer”.", "✓ הדואר של Outlook נמצא ב־J, תחת „במחשב הזה”."))
    return failed


if __name__ == "__main__":
    sys.exit(main())
