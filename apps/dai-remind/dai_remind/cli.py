# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-remind: reminders by sentence (docs/REMIND.md).

  dai-remind list              the reminders still to come
  dai-remind fire ID           what the timer runs: a notification, a sound, then the reminder is gone
  dai-remind cancel ID         remove one reminder (dai-tune undo also works right after adding one)
  dai-remind --version

To add one, say it: dai-tune "remind me in 20 minutes to call Dana", or type it in the command bar.
"""
from __future__ import annotations

import sys
from pathlib import Path

from dai_i18n import pick, ui_lang

from . import __author__, __version__
from .engine import ID_RE, RemindError, describe, fire, load, remove, upcoming


def main(argv: list[str] | None = None, home: Path | None = None, run=None, popen=None, which=None) -> int:
    args = list(sys.argv if argv is None else argv)[1:]
    lang = ui_lang()
    if not args or args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if args[0] == "--version":
        print(f"dai-remind {__version__} — {__author__}")
        return 0
    extra = {k: v for k, v in (("run", run), ("popen", popen), ("which", which)) if v is not None}
    if args[0] == "list" and len(args) == 1:
        reminders = upcoming(home)
        if not reminders:
            print(pick(lang, "No reminders. Say one: dai-tune \"remind me in 20 minutes to call Dana\"",
                       "אין תזכורות. תגידו אחת: dai-tune \"תזכיר לי בעוד 20 דקות לצלצל לדנה\""))
            return 0
        for reminder in reminders:
            print(describe(reminder, lang))
        return 0
    if args[0] in ("fire", "cancel") and len(args) == 2:
        reminder_id = args[1]
        if not ID_RE.match(reminder_id):
            print(pick(lang, "✗ a reminder id is 8 hexadecimal characters", "✗ מזהה תזכורת הוא 8 תווים הקסדצימליים"), file=sys.stderr)
            return 2
        try:
            if args[0] == "fire":
                reminder = fire(reminder_id, lang, home, **extra)
                print(pick(lang, "⏰ {text}", "⏰ {text}").format(text=reminder.text))
            else:
                known = load(reminder_id, home) is not None
                remove(reminder_id, home, **({"run": run} if run is not None else {}))
                print(pick(lang, "✓ removed {id}", "✓ הוסרה {id}").format(id=reminder_id) if known
                      else pick(lang, "No reminder {id}; nothing to remove.", "אין תזכורת {id}; אין מה להסיר.").format(id=reminder_id))
        except RemindError as exc:
            print(f"✗ {exc}", file=sys.stderr)
            return 1
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2
