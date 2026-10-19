# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Text out of a PDF, made readable (docs/PDF.md §8, "Hebrew text order").

Many PDFs store Hebrew the way it was drawn: right to left, so the extracted text comes out mirrored
("םולש" for "שלום"). There is no flag in the file that says so. This module guesses, per line:

  - a line whose Hebrew runs read backwards (against a small list of very common words, and the shape of
    final letters, which belong at the END of a word) is mirrored: each run of Hebrew letters is reversed,
    and the order of runs in the line is reversed too, so the line reads as it was written;
  - a line whose Hebrew reads forwards is left alone;
  - lines without Hebrew are never touched.

It is a heuristic, and it says so in the window's help. Copying "as extracted" is always possible.
"""
from __future__ import annotations

import re

HEBREW_RUN = re.compile(r"[֐-׿][֐-׿ְ-ׇ'\"]*")
FINAL = "ךםןףץ"
FINAL_FOR = {"כ": "ך", "מ": "ם", "נ": "ן", "פ": "ף", "צ": "ץ"}
# Very common words: if a line's Hebrew contains more of them reversed than forwards, the line is mirrored.
COMMON = ("של", "את", "על", "לא", "זה", "עם", "הוא", "היא", "גם", "כל", "אם", "או", "יש", "אני", "הם", "כי",
          "מה", "אל", "עד", "בין", "אבל", "שלום", "תודה", "יום", "שנה", "בית", "ישראל", "אין", "רק", "אחד")


def _score(words: list[str]) -> int:
    """How much a list of Hebrew words looks like real Hebrew: common words, and final letters at the end."""
    score = 0
    for word in words:
        if word in COMMON:
            score += 3
        if len(word) > 1 and word[-1] in FINAL:
            score += 2
        if any(ch in FINAL for ch in word[:-1]):
            score -= 2  # a final letter in the middle of a word: wrong way round
    return score


def is_mirrored(line: str) -> bool:
    words = HEBREW_RUN.findall(line)
    if not words:
        return False
    forwards = _score(words)
    backwards = _score([w[::-1] for w in words])
    return backwards > forwards


def unmirror_line(line: str) -> str:
    """The line as it was written: Hebrew runs reversed, and their order in the line reversed."""
    parts = HEBREW_RUN.split(line)      # the non-Hebrew pieces, in order
    runs = HEBREW_RUN.findall(line)
    if not runs:
        return line
    # Rebuild from the end: the leftmost Hebrew run was written last.
    out: list[str] = []
    pieces = []
    for i, part in enumerate(parts):
        pieces.append(("t", part))
        if i < len(runs):
            pieces.append(("h", runs[i]))
    for kind, value in reversed(pieces):
        out.append(value[::-1] if kind == "h" else value)
    # The non-Hebrew pieces were also reversed in order; characters inside them keep their order, but
    # mirrored lines usually keep punctuation attached to the wrong side. Left as is: good enough to read.
    return "".join(out)


def readable(text: str) -> str:
    """Every mirrored line put right; others untouched."""
    return "\n".join(unmirror_line(line) if is_mirrored(line) else line for line in text.split("\n"))


def find_all(haystack: str, needle: str) -> list[int]:
    """Case-insensitive positions of `needle` in `haystack` (what the search panel uses)."""
    if not needle:
        return []
    low, want = haystack.casefold(), needle.casefold()
    positions, start = [], 0
    while True:
        at = low.find(want, start)
        if at < 0:
            return positions
        positions.append(at)
        start = at + max(1, len(want))
