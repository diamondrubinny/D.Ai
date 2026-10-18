#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Writes the language switcher and the hreflang alternates into every landing page of site/.

  python3 build/scripts/site-languages.py [--check]

The switcher replaces the <!-- languages --> marker (or the block a previous run wrote), so running it
again gives the same pages; --check exits 1 when a page is out of date (the site test runs it).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parents[2] / "site"
# (code, folder, name in its own language); Hebrew is the root page.
LANGS = [("he", "", "עברית"), ("en", "en", "English"), ("ar", "ar", "العربية"), ("ru", "ru", "Русский"),
         ("es", "es", "Español"), ("fr", "fr", "Français"), ("de", "de", "Deutsch"), ("pt", "pt", "Português")]
LABEL = {"he": "שפות", "en": "Languages", "ar": "اللغات", "ru": "Языки", "es": "Idiomas", "fr": "Langues",
         "de": "Sprachen", "pt": "Idiomas"}
BLOCK = re.compile(r"<!-- languages -->(?:.*?<!-- /languages -->)?", re.S)
ALTERNATES = re.compile(r"\n *<!-- alternates -->.*?<!-- /alternates -->", re.S)


def href(current: str, folder: str) -> str:
    up = "../" if current else ""
    return f"{up}{folder + '/' if folder else ''}index.html"


def render(code: str, folder: str) -> tuple[str, str]:
    links = []
    for other, other_folder, name in LANGS:
        current = ' aria-current="page"' if other == code else ""
        links.append(f'<a href="{href(folder, other_folder)}" hreflang="{other}" lang="{other}"{current}>{name}</a>')
    switcher = (f'<!-- languages --><nav class="langs" aria-label="{LABEL[code]}">' + " ".join(links)
                + "</nav><!-- /languages -->")
    alternates = "\n  <!-- alternates -->" + "".join(
        f'\n  <link rel="alternate" hreflang="{other}" href="{href(folder, other_folder)}">'
        for other, other_folder, _ in LANGS) + "\n  <!-- /alternates -->"
    return switcher, alternates


def update(path: Path, code: str, folder: str) -> str:
    text = path.read_text(encoding="utf-8")
    switcher, alternates = render(code, folder)
    if not BLOCK.search(text):
        text = text.replace("    </div>\n  </footer>", f"      {switcher}\n    </div>\n  </footer>", 1)
    text = BLOCK.sub(lambda m: switcher, text, count=1)
    text = ALTERNATES.sub("", text)
    return text.replace('  <link rel="stylesheet"', alternates.lstrip("\n") + '\n  <link rel="stylesheet"', 1)


def main(argv: list[str]) -> int:
    stale = []
    for code, folder, _ in LANGS:
        path = SITE / folder / "index.html" if folder else SITE / "index.html"
        new = update(path, code, folder)
        if new != path.read_text(encoding="utf-8"):
            stale.append(str(path.relative_to(SITE)))
            if "--check" not in argv:
                path.write_text(new, encoding="utf-8")
    if "--check" in argv and stale:
        print("out of date (run build/scripts/site-languages.py):", ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
