# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The six symbols two people compare when they pair (docs/SEND.md §3), like Signal's safety number.

Both computers compute the same six symbols from both identity keys (in a fixed order), so an impostor in
the middle would show different ones. 64 symbols, 6 of them: 36 bits, enough for a comparison by eye or
over the phone. Each symbol has a name, in the person's language where we have one.
"""
from __future__ import annotations

from nacl.encoding import RawEncoder
from nacl.hash import blake2b

# (emoji, English, Hebrew): easy to say aloud, no two alike.
SYMBOLS = [
    ("💎", "diamond", "יהלום"), ("⭐", "star", "כוכב"), ("🌙", "moon", "ירח"), ("☀️", "sun", "שמש"),
    ("🌈", "rainbow", "קשת"), ("🔥", "fire", "אש"), ("💧", "drop", "טיפה"), ("❄️", "snow", "שלג"),
    ("🌳", "tree", "עץ"), ("🌸", "flower", "פרח"), ("🍀", "clover", "תלתן"), ("🍎", "apple", "תפוח"),
    ("🍋", "lemon", "לימון"), ("🍇", "grapes", "ענבים"), ("🍉", "melon", "אבטיח"), ("🍓", "strawberry", "תות"),
    ("🐶", "dog", "כלב"), ("🐱", "cat", "חתול"), ("🐭", "mouse", "עכבר"), ("🐰", "rabbit", "ארנב"),
    ("🦊", "fox", "שועל"), ("🐻", "bear", "דוב"), ("🐼", "panda", "פנדה"), ("🦁", "lion", "אריה"),
    ("🐮", "cow", "פרה"), ("🐷", "pig", "חזיר"), ("🐸", "frog", "צפרדע"), ("🐵", "monkey", "קוף"),
    ("🐔", "chicken", "תרנגולת"), ("🐧", "penguin", "פינגווין"), ("🐦", "bird", "ציפור"), ("🦋", "butterfly", "פרפר"),
    ("🐢", "turtle", "צב"), ("🐍", "snake", "נחש"), ("🐙", "octopus", "תמנון"), ("🐟", "fish", "דג"),
    ("🐬", "dolphin", "דולפין"), ("🐳", "whale", "לווייתן"), ("🦀", "crab", "סרטן"), ("🐝", "bee", "דבורה"),
    ("🚗", "car", "מכונית"), ("🚲", "bicycle", "אופניים"), ("🚀", "rocket", "רקטה"), ("✈️", "plane", "מטוס"),
    ("⛵", "boat", "סירה"), ("🏠", "house", "בית"), ("🏰", "castle", "טירה"), ("⏰", "clock", "שעון"),
    ("🔑", "key", "מפתח"), ("🔔", "bell", "פעמון"), ("🎈", "balloon", "בלון"), ("🎁", "gift", "מתנה"),
    ("🎵", "music", "מוזיקה"), ("🎸", "guitar", "גיטרה"), ("🥁", "drum", "תוף"), ("📚", "books", "ספרים"),
    ("✏️", "pencil", "עיפרון"), ("📷", "camera", "מצלמה"), ("☂️", "umbrella", "מטרייה"), ("👑", "crown", "כתר"),
    ("⚓", "anchor", "עוגן"), ("🧩", "puzzle", "פאזל"), ("🎯", "target", "מטרה"), ("🪁", "kite", "עפיפון"),
]
COUNT = 6


def symbols(a: bytes, b: bytes) -> list[int]:
    """Six indexes into SYMBOLS; the same on both computers, whichever pairs first."""
    first, second = sorted((a, b))
    digest = blake2b(first + second, digest_size=8, person=b"dai-chat-sas", encoder=RawEncoder)
    value = int.from_bytes(digest, "big")
    return [(value >> (6 * index)) & 63 for index in range(COUNT)]


def describe(indexes: list[int], lang: str) -> str:
    """"💎 diamond · 🐢 turtle · ..." in the person's language (English when we have no names in it)."""
    column = 2 if lang == "he" else 1
    return " · ".join(f"{SYMBOLS[i][0]} {SYMBOLS[i][column]}" for i in indexes)
