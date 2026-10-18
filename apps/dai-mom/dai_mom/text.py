# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""MOM's words, in plain language (docs/MOM.md §6)."""

from __future__ import annotations

from dai_i18n import pick, text, ui_lang

from .apps import App

STRINGS = {
    "title": ("MOM – Task manager", "MOM – מנהל המשימות"),
    "apps": ("Apps", "אפליקציות"),
    "performance": ("Performance", "ביצועים"),
    "search": ("Type to find an app…", "הקלידו כדי למצוא אפליקציה…"),
    "col_name": ("Name", "שם"),
    "col_memory": ("Memory", "זיכרון"),
    "col_cpu": ("CPU", "מעבד"),
    "col_notes": ("Notes", "הערות"),
    "other": ("Other processes", "תהליכים נוספים"),
    "close": ("Close", "סגירה"),
    "force": ("Force close", "סגירה בכוח"),
    "slow": ("Why is it slow?", "למה המחשב איטי?"),
    "processes": ("{count} processes", "{count} תהליכים"),
    "one_process": ("1 process", "תהליך אחד"),
    "sandbox": ("🛡 sandbox", "🛡 ארגז חול"),
    "recording": ("🔴 recording", "🔴 מקליט"),
    "session": ("part of the session", "חלק מההפעלה"),
    "row": ("{name}, {memory} memory, {cpu} percent CPU", "{name}, {memory} זיכרון, {cpu} אחוז מעבד"),
    "confirm_force_title": ("Force close {name}?", "לסגור בכוח את {name}?"),
    "confirm_force": ("Unsaved work in {name} will be lost.", "עבודה שלא נשמרה ב־{name} תאבד."),
    "confirm_protected_title": ("Close {name}?", "לסגור את {name}?"),
    "confirm_protected": ("{name} is part of the session. Closing it can end the session or stop the sound "
                          "and the taskbar until you log in again.",
                          "{name} הוא חלק מההפעלה. סגירה שלו יכולה לסיים את ההפעלה, או לעצור את הצליל ואת שורת "
                          "המשימות עד הכניסה הבאה."),
    "protected_force": ("{name} is part of the session and cannot be forced closed.",
                        "{name} הוא חלק מההפעלה, ואי אפשר לסגור אותו בכוח."),
    "protected_confirm": ("{name} is part of the session. Add --yes to close it anyway.",
                          "{name} הוא חלק מההפעלה. הוסיפו ‎--yes‎ כדי לסגור בכל זאת."),
    "force_confirm": ("Forcing loses unsaved work. Add --yes to force {name} closed.",
                      "סגירה בכוח מאבדת עבודה שלא נשמרה. הוסיפו ‎--yes‎ כדי לסגור בכוח את {name}."),
    "permission": ("{name} belongs to the system; MOM only closes your own apps.",
                   "{name} שייך למערכת; MOM סוגרת רק את האפליקציות שלכם."),
    "root": ("MOM does not run as root.", "MOM לא רצה כ־root."),
    "not_found": ("Nothing called {name} is running.", "שום דבר בשם {name} לא רץ."),
    "closed": ("Asked {name} to close.", "ביקשנו מ־{name} להיסגר."),
    "forced": ("{name} was forced closed.", "{name} נסגר בכוח."),
    "still": ("{name} has not closed yet. Force close?", "{name} עדיין לא נסגר. לסגור בכוח?"),
    "cpu_now": ("Processor: {value}%", "מעבד: {value}%"),
    "memory_now": ("Memory: {used} of {total} in use", "זיכרון: {used} מתוך {total} בשימוש"),
    "swap_now": ("Swap: {used} of {total} in use", "זיכרון החלפה: {used} מתוך {total} בשימוש"),
    "disk_now": ("Disk: {free} free of {total}", "דיסק: {free} פנויים מתוך {total}"),
    "summary": ("{apps} apps · {procs} processes", "{apps} אפליקציות · {procs} תהליכים"),
    "hint": ("Delete: close · Shift+Delete: force close", "Delete: סגירה · Shift+Delete: סגירה בכוח"),
    "cancel": ("Cancel", "ביטול"),
    "cpu_short": ("{value}% CPU", "{value}% מעבד"),
}


def t(key: str, lang: str | None = None, **kwargs: object) -> str:
    lang = lang or ui_lang()
    return text(lang, *STRINGS[key], **kwargs) if kwargs else pick(lang, *STRINGS[key])


def size(value: int, lang: str | None = None) -> str:
    """1.2 GB / 350 MB, the way people read it."""
    if value >= 1024 ** 3:
        return f"{value / 1024 ** 3:.1f} GB"
    if value >= 1024 ** 2:
        return f"{value / 1024 ** 2:.0f} MB"
    return f"{max(value, 0) // 1024} KB"


def count(app: App, lang: str | None = None) -> str:
    n = len(app.processes)
    return t("one_process", lang) if n == 1 else t("processes", lang, count=n)


def notes(app: App, lang: str | None = None) -> str:
    parts = []
    if app.recording:
        parts.append(t("recording", lang))
    if app.sandboxed:
        parts.append(t("sandbox", lang))
    if app.protected:
        parts.append(t("session", lang))
    parts.append(count(app, lang))
    return " · ".join(parts)


def describe(app: App, lang: str | None = None) -> str:
    """One plain line: 'Firefox ESR · Browse the Web · 1.2 GB · 4% CPU · 12 processes'."""
    parts = [app.name] + ([app.comment] if app.comment else [])
    parts += [size(app.memory, lang), t("cpu_short", lang, value=f"{app.cpu:g}"), notes(app, lang)]
    return " · ".join(parts)
