# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Hebrew and English wording for D.Ai Clip."""

from __future__ import annotations

import time
from dai_i18n import pick, ui_lang

STRINGS = {
    "title": ("Clipboard history", "היסטוריית העתקות"),
    "search": ("Search what you copied…", "חיפוש במה שהעתקתם…"),
    "empty": ("Nothing here yet. What you copy will show up here (never passwords).",
              "עדיין אין כאן כלום. מה שתעתיקו יופיע כאן (אף פעם לא סיסמאות)."),
    "no_match": ("Nothing matches.", "אין תוצאות."),
    "hint": ("Enter paste · Shift+Enter copy only · Delete remove · Esc close",
             "Enter הדבקה · Shift+Enter העתקה בלבד · Delete מחיקה · Esc סגירה"),
    "clear_all": ("Clear all", "ניקוי הכל"),
    "lines": ("{n} lines", "{n} שורות"),
    "just_now": ("just now", "עכשיו"),
    "minutes": ("{n} min ago", "לפני {n} דק׳"),
    "hours": ("{n} h ago", "לפני {n} שע׳"),
    "cleared": ("The clipboard history was cleared.", "היסטוריית ההעתקות נוקתה."),
    "paused": ("Not keeping anything until {time}.", "לא נשמר כלום עד {time}."),
    "resumed": ("Keeping the clipboard history again.", "היסטוריית ההעתקות נשמרת שוב."),
    "off": ("D.Ai Clip is off; the history was cleared. `dai-clip on` turns it back on.",
            "D.Ai Clip כבוי וההיסטוריה נמחקה. `dai-clip on` מפעיל אותו שוב."),
    "on": ("D.Ai Clip is on.", "D.Ai Clip פועל."),
    "status_on": ("On · {n} items · in memory only, never passwords", "פועל · {n} פריטים · בזיכרון בלבד, אף פעם לא סיסמאות"),
    "status_off": ("Off (dai-clip on)", "כבוי (dai-clip on)"),
    "status_paused": ("Paused until {time} · {n} items", "מושהה עד {time} · {n} פריטים"),
    "no_runtime": ("No private memory folder (XDG_RUNTIME_DIR); nothing is kept.",
                   "אין תיקיית זיכרון פרטית (XDG_RUNTIME_DIR), ולכן שום דבר לא נשמר."),
    "no_wayland": ("D.Ai Clip needs a Wayland session with wl-clipboard.", "D.Ai Clip צריך סשן Wayland עם wl-clipboard."),
}


def lang() -> str:
    return ui_lang()


def t(key: str, language: str, **kwargs: object) -> str:
    return pick(language, *STRINGS[key]).format(**kwargs)


def age(then: float, now: float, language: str) -> str:
    seconds = max(0.0, now - then)
    if seconds < 60:
        return t("just_now", language)
    if seconds < 3600:
        return t("minutes", language, n=int(seconds // 60))
    return t("hours", language, n=int(seconds // 3600))


def clock(when: float) -> str:
    return time.strftime("%H:%M", time.localtime(when))


def preview(text: str, width: int = 90) -> str:
    """One line for the list: the first non-empty line, shortened."""
    line = next((part.strip() for part in text.splitlines() if part.strip()), "")
    return line if len(line) <= width else line[: width - 1] + "…"
