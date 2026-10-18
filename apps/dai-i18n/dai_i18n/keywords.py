# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Keyword packs (docs/I18N.md §10): words in another language → the English a rule-based parser understands.

A pack is data only, one JSON file per language in an app's `lang/` folder:

  {"format": 1, "lang": "ru", "phrases": {"заблокируй": "block", "флешки": "usb"}}

The longest phrase wins, and only whole words are replaced. The English side is
limited to lowercase letters, digits and `.:'-`, so a pack can never inject
anything a parser would treat as structure. A broken file is skipped.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

ENGLISH = re.compile(r"[a-z0-9 .:'-]+")


def normalize(text: str) -> str:
    text = text.replace("״", '"').replace("׳", "'").replace("’", "'").replace("–", "-")
    return re.sub(r"\s+", " ", text.strip().casefold())


@lru_cache(maxsize=16)
def load(directory: str) -> tuple[tuple[re.Pattern, str], ...]:
    """Every pack in a folder, as (pattern, english) with the longest phrase first."""
    phrases: dict[str, str] = {}
    for path in sorted(Path(directory).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or data.get("format") != 1 or not isinstance(data.get("phrases"), dict):
            continue
        for foreign, english in data["phrases"].items():
            if isinstance(foreign, str) and foreign.strip() and isinstance(english, str) and ENGLISH.fullmatch(english):
                phrases.setdefault(normalize(foreign), english)
    ordered = sorted(phrases.items(), key=lambda item: -len(item[0]))
    return tuple((re.compile(rf"(?<![\w-]){re.escape(foreign)}(?![\w-])"), english) for foreign, english in ordered)


def translate(text: str, directory: str | Path) -> str:
    """The text with every known phrase replaced by its English; other words stay as they are."""
    for pattern, english in load(str(directory)):
        text = pattern.sub(english, text)
    return text
