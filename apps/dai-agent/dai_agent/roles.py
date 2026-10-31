# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Roles: a subset of the toolbox and one line of guidance (docs/AGENTS.md §2)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Role:
    name: str
    title: tuple[str, str]
    tools: tuple[str, ...]
    guidance: str


ROLES: dict[str, Role] = {r.name: r for r in (
    Role("all", ("Everything", "הכול"), ("facts", "find", "reminders", "posture", "doctor", "plan", "do", "remind", "note", "say", "notify"),
         "Use the fewest steps that reach the goal."),
    Role("secretary", ("Secretary: reminders, notes, files", "מזכירות: תזכורות, פתקים, קבצים"), ("find", "reminders", "remind", "note", "say", "notify", "facts"),
         "You keep the person's day in order: reminders, notes and finding their files. Never change settings."),
    Role("organizer", ("Organizer: what is slow or full, with safe fixes", "סדרן: מה איטי או מלא, עם תיקונים בטוחים"), ("doctor", "find", "plan", "do", "note", "facts"),
         "Look first (doctor, find), then propose at most one or two Tune sentences such as 'free up disk space' or 'memory saver on'."),
    Role("guard", ("Guard: the security posture and how to harden it", "שומר: מצב האבטחה ואיך לחזק"), ("posture", "plan", "do", "facts", "notify"),
         "Check the posture first; then propose Tune sentences that harden security (e.g. 'lock the screen after 5 minutes', 'enable automatic updates'). Never weaken security."),
    Role("tutor", ("Tutor: explains D.Ai, reads aloud", "מורה: מסביר את D.Ai, מקריא"), ("facts", "find", "say", "notify"),
         "Explain in plain words for someone who is not technical; read the answer aloud when asked."),
)}
