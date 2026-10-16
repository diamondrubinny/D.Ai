# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""What does a "+ ..." request ask for? (offline, rule based)

  recipe   "install antivirus", "+ תוסיף סנכרון קבצים"
  remove   "remove antivirus", "הסר טלגרם"
  app      "build an app that ...", "תבנה אפליקציה של ..."
  edit     "change shopping: add a delete button", "שנה את shopping: ..."
  unknown  anything else (the local AI may author a recipe for it)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .recipes import Library, Recipe, find

BUILD = (
    r"(?:\b(?:build|create|make|write|generate|code|develop|program)\b|"
    r"תבנה|לבנות|בנה|תיצור|ליצור|צור|תכין|להכין|הכן|תכתוב|לכתוב|כתוב|תפתח|לפתח|פתח לי)"
)
APP_NOUN = (
    r"(?:\b(?:app|apps|application|program|tool|utility|script|website|web ?page|web ?app|game|widget|calculator|timer)\b|"
    r"אפליקציה|אפליקציית|יישום|יישומון|תוכנה|תוכנת|תוכנית|כלי|סקריפט|אתר|דף|עמוד|משחק|מחשבון|טיימר)"
)
WEB = r"(?:\b(?:website|web ?page|web ?app|html|site)\b|אתר|דף אינטרנט|דף|עמוד)"
CLI = r"(?:\b(?:script|command line|cli|terminal)\b|סקריפט|שורת פקודה|שורת הפקודה|טרמינל|מסוף)"
EDIT = (
    r"^(?:please\s+)?(?:change|update|edit|improve|fix|modify|שנה|תשנה|עדכן|תעדכן|שפר|תשפר|תקן|תתקן|ערוך|תערוך)\s+"
    r"(?:את\s+)?(?:the\s+)?(?:app\s+|האפליקציה\s+|אפליקציה\s+)?([a-z][a-z0-9-]{1,30})(?![a-z0-9-])\s*[:,-]?\s*(.*)$"
)


@dataclass(frozen=True)
class Intent:
    kind: str  # recipe | remove | app | edit | unknown | empty
    text: str
    recipe: Recipe | None = None
    app_kind: str = "gui"
    app_name: str = ""
    instruction: str = ""


def _has(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE) is not None


def app_kind(text: str) -> str:
    if _has(WEB, text):
        return "web"
    if _has(CLI, text):
        return "cli"
    return "gui"


def classify(text: str, library: Library, existing_apps: Iterable[str] = ()) -> Intent:
    text = re.sub(r"\s+", " ", text.strip().lstrip("+").strip())
    if not text:
        return Intent("empty", text)
    lowered = text.casefold()

    if (m := re.match(EDIT, lowered, re.IGNORECASE)) and m.group(1) in set(existing_apps):
        return Intent("edit", text, app_name=m.group(1), instruction=m.group(2).strip() or text)

    if _has(BUILD, lowered) and _has(APP_NOUN, lowered):
        return Intent("app", text, app_kind=app_kind(lowered))

    recipe, removing = find(text, library)
    if recipe is not None:
        return Intent("remove" if removing else "recipe", text, recipe=recipe)
    return Intent("unknown", text)
