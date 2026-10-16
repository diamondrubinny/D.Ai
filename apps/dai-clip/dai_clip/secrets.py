# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Decide whether copied text must stay out of the history (docs/CLIP.md §2).

A false positive (ordinary text left out) is acceptable; a password kept in
the history is not. `clear` asks for the clipboard itself to be emptied
after a while, and is set only for strong signals, never for guesses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# The type a password manager adds to mark its copies (KDE convention, used by KeePassXC).
PASSWORD_MANAGER_HINT = "x-kde-passwordManagerHint"

PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----")
TOKEN = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"sk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}"       # OpenAI / Anthropic style API keys
    r"|gh[pousr]_[A-Za-z0-9]{30,}"                # GitHub tokens
    r"|github_pat_[A-Za-z0-9_]{40,}"
    r"|glpat-[A-Za-z0-9_-]{20,}"                  # GitLab
    r"|xox[abprs]-[A-Za-z0-9-]{10,}"              # Slack
    r"|AKIA[0-9A-Z]{16}"                          # AWS access key id
    r"|AIza[0-9A-Za-z_-]{35}"                     # Google API key
    r"|eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"  # JWT
    r")"
)
ASSIGNMENT = re.compile(
    r"(?i)(?:(?<![a-z])(?:pass(?:word|wd|phrase)?|pwd|secret|token|api[_-]?key|access[_-]?key)|סיסמ[הא])"
    r"[\"']?\s*[:=]\s*[\"']?[^\s\"']{4,}"
)
CARD = re.compile(r"^\d(?:[ -]?\d){12,18}$")
ISRAELI_ID = re.compile(r"^\d{8}-?\d$")
ONE_TIME_CODE = re.compile(r"^\d{4,8}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
FILE_NAME = re.compile(r"^[\w.-]+\.[A-Za-z0-9]{1,5}$")
HOST_PATH = re.compile(r"^[\w-]+(?:\.[\w-]+)+(?::\d+)?/")  # example.com/path
HEBREW = re.compile(r"[\u0590-\u05ff]")


@dataclass(frozen=True)
class Verdict:
    kind: str  # private-key | token | password-assignment | card | id-number | one-time-code | password-like
    clear: bool  # empty the clipboard after a while if it still holds this


def luhn_ok(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def israeli_id_ok(digits: str) -> bool:
    digits = digits.zfill(9)
    total = 0
    for index, char in enumerate(digits):
        value = int(char) * (1 + index % 2)
        total += value - 9 if value > 9 else value
    return total % 10 == 0 and digits != "000000000"


def _password_like(text: str) -> bool:
    if not 8 <= len(text) <= 64 or any(c.isspace() for c in text) or HEBREW.search(text):
        return False
    if ("://" in text or text.startswith(("/", "~/", "./", "../", "www.")) or EMAIL.match(text) or FILE_NAME.match(text)
            or HOST_PATH.match(text)):
        return False
    classes = (
        any(c.islower() for c in text),
        any(c.isupper() for c in text),
        any(c.isdigit() for c in text),
        any(not c.isalnum() for c in text),
    )
    return sum(classes) >= 3


def classify(text: str) -> Verdict | None:
    """None: fine to keep. Otherwise why it must not be kept."""
    if PRIVATE_KEY.search(text):
        return Verdict("private-key", True)
    if TOKEN.search(text):
        return Verdict("token", True)
    if ASSIGNMENT.search(text):
        return Verdict("password-assignment", True)
    compact = text.strip()
    if CARD.match(compact):
        digits = re.sub(r"\D", "", compact)
        if luhn_ok(digits):
            return Verdict("card", True)
    if ISRAELI_ID.match(compact) and israeli_id_ok(compact.replace("-", "")):
        return Verdict("id-number", True)
    if ONE_TIME_CODE.match(compact):
        return Verdict("one-time-code", False)
    if _password_like(compact):
        return Verdict("password-like", False)
    return None


def marked_sensitive(state: str | None, offered_types: list[str]) -> bool:
    """Copied by a password manager. wl-clipboard 2.2.1 never sets "sensitive" itself."""
    return state == "sensitive" or PASSWORD_MANAGER_HINT in offered_types
