# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""When an automation runs, read from the request by rules - never by the AI (docs/EVOLVE.md §2).

  "every day at 18:00" / "כל יום ב־18:00"      daily
  "every morning" / "כל בוקר"                  daily 08:00 (evening 20:00, night 23:00)
  "every monday at 9" / "כל יום שני ב־9"        weekly
  "every hour" / "כל שעה"                       hourly
  "every 30 minutes" / "כל 30 דקות"             every N minutes, at least 15
  "at login" / "בכל כניסה"                      when the user logs in

The result is a systemd OnCalendar expression (or "login"), built here from
validated numbers only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from dai_i18n import pick, text

MIN_MINUTES = 15
DAY_NAMES = {"Mon": ("Mon", "שני"), "Tue": ("Tue", "שלישי"), "Wed": ("Wed", "רביעי"), "Thu": ("Thu", "חמישי"),
             "Fri": ("Fri", "שישי"), "Sat": ("Sat", "שבת"), "Sun": ("Sun", "ראשון")}
WEEKDAYS = {
    "Mon": (r"monday|mon\b", r"(?:יום )?שני"), "Tue": (r"tuesday|tue\b", r"(?:יום )?שלישי"),
    "Wed": (r"wednesday|wed\b", r"(?:יום )?רביעי"), "Thu": (r"thursday|thu\b", r"(?:יום )?חמישי"),
    "Fri": (r"friday|fri\b", r"(?:יום )?שישי"), "Sat": (r"saturday|sat\b", r"(?:יום )?שבת"),
    "Sun": (r"sunday|sun\b", r"(?:יום )?ראשון"),
}
PARTS_OF_DAY = {"morning": 8, "בוקר": 8, "noon": 12, "צהריים": 12, "evening": 20, "ערב": 20, "night": 23, "לילה": 23}
TIME = r"(?:at|ב|בשעה|ב־|ב-)?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm|בבוקר|בערב|בלילה|אחה\"צ)?"
EVERY = r"(?:every|each|כל|בכל)"


class ScheduleError(ValueError):
    pass


@dataclass(frozen=True)
class Schedule:
    kind: str           # daily | weekly | hourly | minutes | login
    hour: int = 9
    minute: int = 0
    weekday: str = ""   # Mon..Sun for weekly
    every: int = 0      # minutes, for kind "minutes"

    @property
    def calendar(self) -> str:
        """systemd OnCalendar=; "" for login."""
        if self.kind == "daily":
            return f"*-*-* {self.hour:02d}:{self.minute:02d}:00"
        if self.kind == "weekly":
            return f"{self.weekday} *-*-* {self.hour:02d}:{self.minute:02d}:00"
        if self.kind == "hourly":
            return "hourly"
        return ""  # minutes: an interval (timer_lines), login: no timer

    def timer_lines(self) -> list[str]:
        """The [Timer] section for systemd; [] for login (the service starts with the session)."""
        if self.kind == "login":
            return []
        if self.kind == "minutes":
            return [f"OnStartupSec={self.every}min", f"OnUnitActiveSec={self.every}min"]
        return [f"OnCalendar={self.calendar}", "Persistent=true"]

    def describe(self, lang: str) -> str:
        at = f"{self.hour:02d}:{self.minute:02d}"
        if self.kind == "daily":
            return text(lang, "every day at {at}", "כל יום ב־{at}", at=at)
        if self.kind == "weekly":
            return text(lang, "every {day} at {at}", "כל יום {day} ב־{at}", day=pick(lang, *DAY_NAMES[self.weekday]), at=at)
        if self.kind == "hourly":
            return pick(lang, "every hour", "כל שעה")
        if self.kind == "minutes":
            return text(lang, "every {every} minutes", "כל {every} דקות", every=self.every)
        return pick(lang, "every time you log in", "בכל כניסה למחשב")

    def to_json(self) -> dict:
        return {"kind": self.kind, "hour": self.hour, "minute": self.minute, "weekday": self.weekday, "every": self.every}

    @staticmethod
    def from_json(data: object) -> "Schedule | None":
        if not isinstance(data, dict) or data.get("kind") not in ("daily", "weekly", "hourly", "minutes", "login"):
            return None
        try:
            return _checked(Schedule(data["kind"], int(data.get("hour", 9)), int(data.get("minute", 0)),
                                     str(data.get("weekday", "")), int(data.get("every", 0))))
        except (ScheduleError, ValueError, TypeError):
            return None


def _checked(schedule: Schedule) -> Schedule:
    if not (0 <= schedule.hour <= 23 and 0 <= schedule.minute <= 59):
        raise ScheduleError("time out of range")
    if schedule.kind == "weekly" and schedule.weekday not in WEEKDAYS:
        raise ScheduleError("unknown weekday")
    if schedule.kind == "minutes" and not MIN_MINUTES <= schedule.every <= 720:
        raise ScheduleError(f"automations run at most every {MIN_MINUTES} minutes")
    return schedule


def _time(text: str, default: tuple[int, int]) -> tuple[int, int]:
    for part, hour in PARTS_OF_DAY.items():
        if re.search(rf"\b{part}\b" if part.isascii() else part, text) and not re.search(r"\d{1,2}(?::\d{2})", text):
            default = (hour, 0)
    match = re.search(r"(?:\bat\b|בשעה|(?<![\w])ב[־-]?)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm|בבוקר|בערב|בלילה|אחה\"צ)?", text)
    if not match:
        return default
    hour, minute, suffix = int(match.group(1)), int(match.group(2) or 0), match.group(3) or ""
    if suffix in ("pm", "בערב", "אחה\"צ") and hour < 12:
        hour += 12
    if suffix in ("am",) and hour == 12:
        hour = 0
    if suffix == "בלילה" and hour < 5:
        pass
    elif suffix == "בלילה" and hour < 12:
        hour += 12
    return hour, minute


def parse(text: str) -> Schedule | None:
    """The schedule a request asks for, or None when it asks for none."""
    lowered = text.casefold()
    if re.search(r"\bat (?:log ?in|login|startup|start ?up|boot)\b|(?:בכל|ב) ?כניסה|כשאני נכנס|בהפעלת המחשב|בכל הפעלה", lowered):
        return Schedule("login")
    if m := re.search(rf"{EVERY}\s+(\d{{1,3}})\s*(?:minutes?|mins?|דקות)", lowered):
        return _checked(Schedule("minutes", every=int(m.group(1))))
    if re.search(rf"{EVERY}\s+(?:hour|שעה)\b|\bhourly\b", lowered):
        return Schedule("hourly")
    for day, (en, he) in WEEKDAYS.items():
        if re.search(rf"{EVERY}\s+(?:{en})|{EVERY}\s+{he}|\bon (?:{en})s\b", lowered):
            hour, minute = _time(lowered, (9, 0))
            return _checked(Schedule("weekly", hour, minute, day))
    if re.search(rf"{EVERY}\s+(?:week|שבוע)\b|\bweekly\b", lowered):
        hour, minute = _time(lowered, (9, 0))
        return _checked(Schedule("weekly", hour, minute, "Sun"))
    if re.search(rf"{EVERY}\s+(?:day|morning|evening|night|noon|יום|בוקר|ערב|לילה|צהריים)|\bdaily\b|\bevery ?day\b|\bכל יום\b", lowered):
        hour, minute = _time(lowered, (9, 0))
        return _checked(Schedule("daily", hour, minute))
    return None
