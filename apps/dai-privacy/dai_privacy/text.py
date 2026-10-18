# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Hebrew and English wording for privacy events."""

from __future__ import annotations


from dai_i18n import pick, ui_lang

from .sensors import Use

DEVICES = {
    # Hebrew forms follow "ב": "משתמש במיקרופון".
    "mic": ("microphone", "מיקרופון"),
    "camera": ("camera", "מצלמה"),
    "video": ("camera or screen sharing", "מצלמה או בשיתוף מסך"),
}
ICONS = {"mic": "🎙", "camera": "📷", "video": "📷"}
STRINGS = {
    "nothing": ("Nothing is using the microphone or camera.", "שום דבר לא משתמש במיקרופון או במצלמה."),
    "uses": ("{icon} {app} is using the {device}", "{icon} {app} משתמש ב{device}"),
    "stopped": ("{app} stopped using the {device}", "{app} הפסיק להשתמש ב{device}"),
    "log_empty": ("No microphone or camera use in the last {days} days.", "לא היה שימוש במיקרופון או במצלמה ב־{days} הימים האחרונים."),
    "title": ("D.Ai Privacy", "D.Ai פרטיות"),
    "show_log": ("Privacy log…", "יומן פרטיות…"),
    "block_camera": ("Block the camera (D.Ai Tune)…", "חסימת המצלמה (D.Ai Tune)…"),
    "quit": ("Hide the indicator until next login", "הסתרת המחוון עד הכניסה הבאה"),
}


def lang() -> str:
    return ui_lang()


def t(key: str, language: str, **kwargs: object) -> str:
    return pick(language, *STRINGS[key]).format(**kwargs)


def describe(use: Use, language: str, stopped: bool = False) -> str:
    device = use.device if use.device in DEVICES else "video"
    return t("stopped" if stopped else "uses", language, icon=ICONS[device], app=use.app,
             device=pick(language, *DEVICES[device]))
