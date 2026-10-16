# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-backup: encrypted backups to an external drive, automatically.

  dai-backup setup [DRIVE] [--folders Documents,Pictures]   once
  dai-backup now | status [--json] | list
  dai-backup restore PATH [--from SNAPSHOT]                  into ~/Restored/<date>/
  dai-backup check | disable
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from . import __author__, __version__
from .config import (DEFAULT_FOLDERS, REPO_DIR, Settings, candidate_drives, key_path, load, new_key, save,
                     settings_path)
from .engine import BackupError, Restic

WEEK, DAY = 7 * 86400, 86400


def _lang() -> str:
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if value:
            return "he" if value.startswith("he") else "en"
    return "en"


def _l(en: str, he: str) -> str:
    return he if _lang() == "he" else en


def systemctl(*args: str) -> int:
    try:
        return subprocess.run(["systemctl", "--user", *args], capture_output=True, check=False).returncode
    except OSError:
        return 127


def notify(text: str) -> None:
    try:
        subprocess.Popen(["notify-send", "-a", "D.Ai", "D.Ai Backup", text],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def _when(stamp: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(stamp)) if stamp else _l("never", "אף פעם")


def _value(args: list[str], name: str) -> str | None:
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    return None


def cmd_setup(args: list[str], home: Path, restic_runner=None) -> int:
    if load(home) is not None:
        print(_l("Backup is already set up (dai-backup status). To change it: dai-backup disable, then setup.",
                 "הגיבוי כבר מוגדר (dai-backup status). כדי לשנות: dai-backup disable ואז setup."), file=sys.stderr)
        return 1
    positional = [a for a in args if not a.startswith("--") and a != _value(args, "--folders")]
    drive = Path(positional[0]).expanduser() if positional else None
    if drive is None:
        drives = candidate_drives()
        if len(drives) != 1:
            print(_l("Connect an external drive and run: dai-backup setup /media/$USER/<drive>",
                     "חברו דיסק חיצוני והריצו: dai-backup setup /media/$USER/<שם הדיסק>"), file=sys.stderr)
            for path in drives:
                print(f"  {path}", file=sys.stderr)
            return 2
        drive = drives[0]
    if not drive.is_dir() or not os.access(drive, os.W_OK):
        print(_l(f"{drive} is not a writable folder", f"{drive} אינה תיקייה שאפשר לכתוב אליה"), file=sys.stderr)
        return 2
    repo = drive / REPO_DIR
    if repo.exists() and any(repo.iterdir()):
        print(_l(f"{repo} already exists; it is not overwritten.", f"{repo} כבר קיים, ולא נדרס."), file=sys.stderr)
        return 1
    folders = (_value(args, "--folders") or ",".join(DEFAULT_FOLDERS)).split(",")
    folders = [f.strip().strip("/") for f in folders if f.strip() and ".." not in f]
    settings = Settings(repo=str(repo), folders=folders, created=time.time())
    key = new_key(home)
    try:
        restic = Restic(settings, home, restic_runner) if restic_runner else Restic(settings, home)
        restic.init()
    except BackupError as exc:
        key_path(home).unlink(missing_ok=True)
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    save(settings, home)
    timer = systemctl("enable", "--now", "dai-backup.timer") == 0
    line = "═" * 44
    print(_l("✓ Encrypted backup created on", "✓ נוצר גיבוי מוצפן ב־"), repo)
    print(f"\n{line}\n  {_l('RECOVERY KEY — write it down and keep it safe', 'מפתח שחזור — רשמו אותו ושמרו במקום בטוח')}\n\n    {key}\n{line}")
    print(_l("Without this key the backup cannot be restored on another computer — by you or anyone else.",
             "בלי המפתח הזה אי אפשר לשחזר את הגיבוי במחשב אחר — לא אתם ולא אף אחד אחר."))
    print(_l("Backed up: ", "מגובה: ") + ", ".join(f"~/{f}" for f in folders))
    print(_l("Runs every day while the drive is connected." if timer else "Run it with: dai-backup now",
             "ירוץ כל יום כשהדיסק מחובר." if timer else "הפעלה: dai-backup now"))
    return 0


def run_backup(settings: Settings, home: Path, restic: Restic, quiet: bool = False) -> int:
    try:
        summary = restic.backup()
        if time.time() - settings.last_maintenance > WEEK:
            restic.maintain(verify=True)
            settings.last_maintenance = time.time()
        settings.last_backup = time.time()
        added = summary.get("data_added", 0)
        detail = f"{summary.get('files_new', 0)} new, {summary.get('files_changed', 0)} changed, {added / 2**20:.1f} MB"
        settings.history.append({"time": settings.last_backup, "ok": True, "detail": detail})
        save(settings, home)
        if not quiet:
            print(_l("✓ Backed up: ", "✓ גובה: ") + detail)
        return 0
    except BackupError as exc:
        settings.history.append({"time": time.time(), "ok": False, "detail": str(exc)[:300]})
        save(settings, home)
        notify(_l(f"Backup failed: {exc}", f"הגיבוי נכשל: {exc}"))
        print(f"✗ {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None, restic_runner=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv[1:])
    if "--version" in args:
        print(f"dai-backup {__version__} — {__author__}")
        return 0
    if not args or args[0] in ("-h", "--help", "help", "עזרה"):
        print(__doc__.strip())
        return 0
    home = Path.home()
    command, rest = args[0], args[1:]
    if command == "setup":
        return cmd_setup(rest, home, restic_runner)
    settings = load(home)
    if settings is None:
        print(_l("Backup is not set up yet: dai-backup setup", "הגיבוי עוד לא מוגדר: dai-backup setup"), file=sys.stderr)
        return 1
    restic = Restic(settings, home, restic_runner) if restic_runner else Restic(settings, home)
    present = restic.available()

    if command == "auto":  # the daily timer
        if not present:
            if time.time() - settings.last_backup > WEEK and time.time() - settings.last_reminder > DAY:
                settings.last_reminder = time.time()
                save(settings, home)
                notify(_l("No backup for over a week — connect the backup drive.",
                          "לא היה גיבוי יותר משבוע. חברו את דיסק הגיבוי."))
            return 0
        return run_backup(settings, home, restic, quiet=True)
    if command == "status":
        info = {"repo": settings.repo, "drive_connected": present, "folders": settings.folders,
                "last_backup": settings.last_backup, "copies": len(restic.snapshots()) if present else None,
                "history": settings.history[-5:]}
        if "--json" in rest:
            print(json.dumps(info, ensure_ascii=False, indent=2))
            return 0
        print(_l("Drive: ", "דיסק: ") + settings.repo + (" ✓" if present else _l(" (not connected)", " (לא מחובר)")))
        print(_l("Last backup: ", "גיבוי אחרון: ") + _when(settings.last_backup))
        if present:
            print(_l("Copies: ", "עותקים: ") + str(info["copies"]))
        print(_l("Folders: ", "תיקיות: ") + ", ".join(f"~/{f}" for f in settings.folders))
        return 0
    if command == "disable":
        systemctl("disable", "--now", "dai-backup.timer")
        settings_path(home).unlink(missing_ok=True)
        print(_l("Automatic backups are off. The backup on the drive and the key (~/.config/dai/backup.key) are kept.",
                 "הגיבוי האוטומטי כבוי. הגיבוי שבדיסק והמפתח (~/.config/dai/backup.key) נשמרו."))
        return 0
    if not present:
        print(_l(f"Connect the backup drive first ({settings.repo}).", f"חברו קודם את דיסק הגיבוי ({settings.repo})."),
              file=sys.stderr)
        return 1
    try:
        if command == "now":
            return run_backup(settings, home, restic)
        if command == "list":
            for snap in restic.snapshots():
                print(f"{snap.get('short_id', '?')}  {snap.get('time', '')[:16].replace('T', ' ')}")
            return 0
        if command == "check":
            restic.maintain(verify=True)
            settings.last_maintenance = time.time()
            save(settings, home)
            print(_l("✓ The backup is healthy and restorable.", "✓ הגיבוי תקין וניתן לשחזור."))
            return 0
        if command == "restore" and rest:
            target = restic.restore(Path(rest[0]), _value(rest, "--from") or "latest")
            print(_l(f"✓ Restored into {target}", f"✓ שוחזר אל {target}"))
            return 0
    except BackupError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
