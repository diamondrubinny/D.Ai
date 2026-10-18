# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Hebrew and English wording for D.Ai Heal."""

from __future__ import annotations

import time

from dai_i18n import pick, ui_lang

from .fixes import Fix
from .problems import Problem

STRINGS = {
    "title": ("D.Ai Help & Repair", "D.Ai עזרה ותיקון"),
    "hello": ("Hi. Tell me what is not working, or pick a problem I noticed:",
              "היי. ספרו לי מה לא עובד, או בחרו בעיה ששמתי לב אליה:"),
    "nothing": ("I did not notice any crash or failed service. Tell me what is not working.",
                "לא שמתי לב לקריסה או לשירות שנכשל. ספרו לי מה לא עובד."),
    "placeholder": ("For example: the sound does not work", "למשל: הצליל לא עובד"),
    "send": ("Send", "שליחה"),
    "notify_title": ("Something stopped working", "משהו הפסיק לעבוד"),
    "notify_action": ("Help me fix it", "עזרה בתיקון"),
    "notify_hint": ("Super+F1 opens help", "Super+F1 פותח עזרה"),
    # problems
    "p_service": ("The system service {name} failed.", "שירות המערכת {name} נכשל."),
    "p_user-service": ("Your background service {name} failed.", "שירות הרקע שלך {name} נכשל."),
    "p_crash": ("{name} crashed{times}.", "{name} קרסה{times}."),
    "p_forge-app": ("Your app “{title}” crashed{times}.", "האפליקציה שלך „{title}” קרסה{times}."),
    "p_regression": ("The last update broke something D.Ai checks.", "העדכון האחרון שבר משהו ש־D.Ai בודקת."),
    "times": (" ({n} times)", " ({n} פעמים)"),
    "when": ("When: {when}", "מתי: {when}"),
    "error": ("What it said:", "מה היא אמרה:"),
    # explanations (rule based; the local AI may add its own, clearly marked)
    "x_service": ("A part of the system that runs in the background stopped. Restarting it usually helps; "
                  "it needs the administrator password.",
                  "רכיב של המערכת שרץ ברקע נעצר. הפעלה מחדש בדרך כלל עוזרת, ונדרשת סיסמת מנהל."),
    "x_user-service": ("Something that runs in the background for you stopped. I can start it again.",
                       "משהו שרץ ברקע בשבילך נעצר. אפשר להפעיל אותו מחדש."),
    "x_crash": ("Programs usually crash because of damaged settings or a bug. Starting it again often works; "
                "if it keeps crashing, putting its settings aside (they are kept) usually fixes it.",
                "תוכנות קורסות בדרך כלל בגלל הגדרות פגומות או באג. הפעלה מחדש עוזרת לא פעם, ואם זה חוזר, "
                "העברת ההגדרות שלה הצידה (הן נשמרות) בדרך כלל מתקנת."),
    "x_forge-app": ("This is an app you built with D.Ai Forge. I can fix it: Diamond reads the error, changes "
                    "the code, and tests it in the sandbox before you open it. The current version is kept.",
                    "זו אפליקציה שבנית עם D.Ai Forge. אפשר לתקן אותה: Diamond קורא את השגיאה, משנה את הקוד "
                    "ובודק אותה בארגז החול לפני שתפתחו אותה. הגרסה הנוכחית נשמרת."),
    "x_regression": ("Before the update this worked, and now it does not (Raz, D.Ai's quality control, checked "
                     "before and after). Undoing the update brings the system back to how it was; it needs "
                     "snapshots, which are on when D.Ai was installed on Btrfs. Fixed it another way? Check again.",
                     "לפני העדכון זה עבד, ועכשיו לא (Raz, בקרת האיכות של D.Ai, בדק לפני ואחרי). ביטול העדכון "
                     "מחזיר את המערכת למצב שהיה. זה דורש צילומי מצב, שפועלים כש־D.Ai הותקנה על Btrfs. תיקנתם "
                     "בדרך אחרת? בדקו שוב."),
    "ai_says": ("Diamond adds:", "Diamond מוסיף:"),
    # fixes
    "f_tune": ("Restart it (administrator password)", "הפעלה מחדש (סיסמת מנהל)"),
    "f_user-restart": ("Start it again", "הפעלה מחדש"),
    "f_forge-repair": ("Fix the app with Diamond", "תיקון האפליקציה עם Diamond"),
    "f_reset-settings": ("Put its settings aside", "העברת ההגדרות הצידה"),
    "f_relaunch": ("Open it again", "פתיחה מחדש"),
    "f_restore-settings": ("Put the old settings back", "החזרת ההגדרות הישנות"),
    "f_undo-update": ("Undo the update (administrator password)", "ביטול העדכון (סיסמת מנהל)"),
    "f_recheck": ("Check again", "בדיקה חוזרת"),
    "not_now": ("Not now", "לא עכשיו"),
    "never": ("Don't ask about this again", "לא לשאול על זה שוב"),
    "working": ("Working on it…", "מטפל בזה…"),
    # outcomes
    "fixed": ("✓ Fixed: it is running again.", "✓ תוקן: זה עובד שוב."),
    "repaired": ("✓ The app was fixed and passed the test in the sandbox ({detail}). Open it from the Start menu.",
                 "✓ האפליקציה תוקנה ועברה בדיקה בארגז החול ({detail}). פתחו אותה מתפריט התחל."),
    "relaunched": ("Opened again. If it crashes again, I will tell you.", "נפתחה מחדש. אם היא תקרוס שוב, אגיד לכם."),
    "settings_reset": ("✓ Its settings were moved aside to {detail}. Open it again to start fresh.",
                       "✓ ההגדרות הועברו הצידה אל {detail}. פתחו אותה שוב כדי להתחיל מחדש."),
    "settings_restored": ("✓ The old settings are back.", "✓ ההגדרות הישנות חזרו."),
    "update_undone": ("✓ The update was undone. Restart the computer to finish.",
                      "✓ העדכון בוטל. הפעילו מחדש את המחשב כדי לסיים."),
    "recheck_ok": ("✓ Everything passes again.", "✓ הכל עובר שוב."),
    "still_failing": ("✗ It is still failing. Here is what it says now:", "✗ זה עדיין נכשל. זה מה שהוא אומר עכשיו:"),
    "fix_failed": ("✗ That did not work: {detail}", "✗ זה לא הצליח: {detail}"),
    "report": ("If it keeps happening, report it (nothing is sent without you): "
               "https://github.com/diamondrubinny/D.Ai/issues",
               "אם זה ממשיך, דווחו (שום דבר לא נשלח בלעדיכם): https://github.com/diamondrubinny/D.Ai/issues"),
    "doctor_intro": ("Here is what I checked:", "זה מה שבדקתי:"),
    "unknown_question": ("I could not match that to something I can check. Try: “the sound does not work”, "
                         "“why is it slow?”, “the printer does not work”.",
                         "לא הצלחתי לקשר את זה למשהו שאני יודע לבדוק. נסו: „הצליל לא עובד”, „למה המחשב איטי?”, "
                         "„המדפסת לא עובדת”."),
    "status_none": ("No problems noticed.", "לא נמצאו בעיות."),
}


def lang() -> str:
    return ui_lang()


def t(key: str, language: str, **kwargs: object) -> str:
    return pick(language, *STRINGS[key]).format(**kwargs)


def describe(problem: Problem, language: str) -> str:
    times = t("times", language, n=problem.count) if problem.count > 1 else ""
    title = str(problem.extra.get("title") or problem.name)
    return t(f"p_{problem.kind}", language, name=problem.name, title=title, times=times)


def when(problem: Problem, language: str) -> str:
    return t("when", language, when=time.strftime("%d.%m %H:%M", time.localtime(problem.when))) if problem.when else ""


def explain(problem: Problem, language: str) -> str:
    return t(f"x_{problem.kind}", language)


def fix_label(fix: Fix, language: str) -> str:
    return t(f"f_{fix.kind}", language)
