# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Ready-made goals per role (docs/AGENTS.md §6ח): what the window offers when it is empty."""
from __future__ import annotations

from dai_i18n import pick

from .roles import ROLES

SUGGESTIONS: dict[str, tuple[tuple[str, str], ...]] = {
    "secretary": (
        ("Summarize my newest mail", "סכם לי את הדואר החדש"),
        ("Remind me in 20 minutes to take a break", "תזכיר לי בעוד 20 דקות לעשות הפסקה"),
        ("Focus for 25 minutes", "פוקוס ל־25 דקות"),
        ("Find the files I worked on this week", "מצא את הקבצים שעבדתי עליהם השבוע"),
    ),
    "organizer": (
        ("What is slow on this computer, and what can be fixed safely?", "מה איטי במחשב הזה, ומה אפשר לתקן בבטחה?"),
        ("What fills the disk?", "מה ממלא את הדיסק?"),
        ("Is the battery set up well?", "האם הסוללה מוגדרת טוב?"),
    ),
    "guard": (
        ("What is weak in my security, and harden the easy parts", "מה חלש באבטחה שלי, וחזק את החלקים הקלים"),
        ("Is my computer up to date?", "האם המחשב מעודכן?"),
    ),
    "tutor": (
        ("What is on my screen?", "מה על המסך שלי?"),
        ("Explain what D.Ai Command does", "הסבר מה D.Ai Command עושה"),
        ("How do I lock the screen automatically?", "איך נועלים את המסך אוטומטית?"),
    ),
}
SUGGESTIONS["all"] = tuple(dict.fromkeys(s for role in ("secretary", "organizer", "guard", "tutor") for s in SUGGESTIONS[role][:2]))


def suggestions(role: str, lang: str) -> list[str]:
    """The goals to offer for a role, in the interface language; [] for an unknown role."""
    if role not in ROLES:
        return []
    return [pick(lang, *pair) for pair in SUGGESTIONS.get(role, ())]
