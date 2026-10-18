# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Languages for every D.Ai app (docs/I18N.md).

The English text is the source and the gettext message ID; Hebrew is written
next to it in the code (reviewed together); every other language comes from
the catalog /usr/share/locale/<lang>/LC_MESSAGES/dai-os.mo and falls back to
English when a text is not translated yet.

A translation is only used when it has exactly the same {placeholders} as the
English text, so a broken or hostile catalog can never break formatting or
reach into the objects being formatted.
"""

from __future__ import annotations

import gettext
import os
import string
from functools import lru_cache

__version__ = "0.1.0"
__author__ = "Diamond Rubinny (d.Ai)"

DOMAIN = "dai-os"
SYSTEM_LOCALEDIR = "/usr/share/locale"
SUPPORTED = ("en", "he", "ar", "ru", "es", "fr", "de", "pt")
RTL = frozenset({"he", "ar"})
NATIVE_NAMES = {
    "en": "English", "he": "עברית", "ar": "العربية", "ru": "Русский",
    "es": "Español", "fr": "Français", "de": "Deutsch", "pt": "Português",
}
ENGLISH_NAMES = {
    "en": "English", "he": "Hebrew", "ar": "Arabic", "ru": "Russian",
    "es": "Spanish", "fr": "French", "de": "German", "pt": "Portuguese",
}
RLE, PDF = "‫", "‬"


def normalize(value: str) -> str:
    """'pt_BR.UTF-8' -> 'pt'; unknown or C/POSIX -> 'en'."""
    code = value.split(".")[0].split("@")[0].split("_")[0].split("-")[0].lower()
    return code if code in SUPPORTED else "en"


def ui_lang(environ: dict[str, str] | None = None) -> str:
    """The interface language, from the same variables the apps always used."""
    env = os.environ if environ is None else environ
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = env.get(var)
        if value:
            return normalize(value)
    return "en"


def is_rtl(lang: str) -> bool:
    return lang in RTL


def english_name(lang: str) -> str:
    """For prompts to the local AI ("answer in Arabic")."""
    return ENGLISH_NAMES.get(lang, "English")


def localedir() -> str:
    """DAI_LOCALEDIR is for tests and translators; never honoured as root."""
    override = os.environ.get("DAI_LOCALEDIR")
    if override and os.geteuid() != 0:
        return override
    return SYSTEM_LOCALEDIR


@lru_cache(maxsize=16)
def _catalog(lang: str, directory: str) -> gettext.NullTranslations:
    return gettext.translation(DOMAIN, directory, languages=[lang], fallback=True)


def _fields(template: str) -> frozenset | None:
    try:
        return frozenset((name, conversion, spec) for _, name, spec, conversion in string.Formatter().parse(template)
                         if name is not None)
    except ValueError:
        return None


def translate(lang: str, english: str) -> str:
    """English text in another language from the catalog, or the English text itself."""
    if lang in ("en", "he") or not english:
        return english
    translated = _catalog(lang, localedir()).gettext(english)
    if translated == english or not translated.strip():
        return english
    return translated if _fields(translated) == _fields(english) else english


def pick(lang: str, en: str, he: str) -> str:
    """The text for this language: Hebrew from the code, the rest from the catalog."""
    return he if lang == "he" else translate(lang, en)


def text(lang: str, en: str, he: str, **kwargs: object) -> str:
    """pick() and fill in the {placeholders}."""
    chosen = pick(lang, en, he)
    return chosen.format(**kwargs) if kwargs else chosen


def embed(caption: str, lang: str) -> str:
    """Right-to-left embedding for short labels (Qt buttons ignore RLM)."""
    return f"{RLE}{caption}{PDF}" if is_rtl(lang) else caption


def qt_direction(lang: str):
    from PyQt6.QtCore import Qt

    return Qt.LayoutDirection.RightToLeft if is_rtl(lang) else Qt.LayoutDirection.LeftToRight
