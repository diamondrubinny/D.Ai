# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-oem: prepare an installed computer for its new owner (docs/OEM.md).

  sudo dai-oem prepare [--remove-user NAME] [--poweroff] [--yes]
  sudo dai-oem cancel        undo prepare (before the computer is handed over)
  dai-oem status
  sudo dai-oem cleanup       run by dai-oem-cleanup.service at the next boot
"""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

from dai_i18n import pick, ui_lang

from . import __author__, __version__
from .core import Machine, OemError

STRINGS = {
    "need_root": ("Run it as administrator: sudo dai-oem {cmd}", "יש להריץ כמנהל: sudo dai-oem {cmd}"),
    "plan": ("This prepares the computer for its new owner:\n"
             "  • at the next start, a short setup asks for their name, user, password, computer name{luks}\n"
             "  • the temporary user {user} and everything in its home folder are deleted after that\n"
             "  • package caches, system logs, the machine ID and SSH host keys are reset now\n",
             "המחשב יוכן לבעלים החדשים:\n"
             "  • בהפעלה הבאה ייפתח אשף קצר: שם, משתמש, סיסמה, שם מחשב{luks}\n"
             "  • המשתמש הזמני {user} וכל מה שבתיקייה שלו יימחקו אחרי זה\n"
             "  • מטמון חבילות, יומני מערכת, מזהה המחשב ומפתחות SSH מתאפסים עכשיו\n"),
    "luks_part": (" and a new disk encryption password", " וסיסמת הצפנה חדשה"),
    "confirm": ("Continue? [y/N] ", "להמשיך? [כ/ל] "),
    "luks_prompt": ("Temporary disk encryption password: ", "סיסמת ההצפנה הזמנית: "),
    "ready": ("Ready. Power off and hand it over; the owner needs the temporary encryption password once.",
              "מוכן. כבו את המחשב ומסרו אותו. הנמען צריך את סיסמת ההצפנה הזמנית פעם אחת."),
    "ready_plain": ("Ready. Power off and hand it over.", "מוכן. כבו את המחשב ומסרו אותו."),
    "cancelled": ("Cancelled: the computer starts as before.", "בוטל: המחשב יעלה כמו קודם."),
    "none": ("Not prepared.", "לא הוכן."),
    "pending": ("Prepared: the setup opens at the next start.", "הוכן: האשף ייפתח בהפעלה הבאה."),
    "cleanup": ("Finished by {owner}; the temporary users are removed at the next start.",
                "הוגדר על ידי {owner}. המשתמשים הזמניים יימחקו בהפעלה הבאה."),
}


def lang() -> str:
    return ui_lang()


def t(key: str, language: str, **kwargs: object) -> str:
    return pick(language, *STRINGS[key]).format(**kwargs)


def _option(args: list[str], name: str) -> str | None:
    if name in args:
        index = args.index(name)
        return args[index + 1] if index + 1 < len(args) else None
    return None


def main(argv: list[str] | None = None, machine: Machine | None = None, ask=input, secret=getpass.getpass) -> int:
    args = list(sys.argv[1:] if argv is None else argv[1:])
    if "--version" in args:
        print(f"dai-oem {__version__} — {__author__}")
        return 0
    language = lang()
    command = args[0] if args else "status"
    machine = machine or Machine(root=Path("/"))
    try:
        if command == "status":
            state = machine.state()
            phase = state.get("phase")
            print(t(phase, language, owner=state.get("owner", "?")) if phase in ("pending", "cleanup") else t("none", language))
            return 0
        if command not in ("prepare", "cancel", "cleanup"):
            print(__doc__.strip(), file=sys.stderr)
            return 2
        if os.geteuid() != 0 and machine.root == Path("/"):
            print(t("need_root", language, cmd=command), file=sys.stderr)
            return 1
        if command == "cleanup":
            machine.cleanup()
            return 0
        if command == "cancel":
            machine.cancel()
            print(t("cancelled", language))
            return 0

        user = _option(args, "--remove-user") or os.environ.get("SUDO_USER") or ""
        needs_luks = bool(machine.luks_devices())
        print(t("plan", language, user=user or "?", luks=t("luks_part", language) if needs_luks else ""))
        if "--yes" not in args and ask(t("confirm", language)).strip().lower() not in ("y", "yes", "כ", "כן"):
            return 1
        password = secret(t("luks_prompt", language)) if needs_luks else None
        machine.prepare(user, password, allow_live="--allow-live" in args)
        print(t("ready" if needs_luks else "ready_plain", language))
        if "--poweroff" in args:
            machine.run(["systemctl", "poweroff"], check=False)
        return 0
    except OemError as exc:
        print(f"dai-oem: {exc}", file=sys.stderr)
        return 1
