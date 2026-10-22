# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Quality gate for every text people read (docs/POLISH.md §2).

Code: every (English, Hebrew) pair the apps show. Site: the eight string files. Menu: the .desktop files.
Mechanical mistakes only; wording is for the language reviewers (docs/NEXT.md).
"""
import configparser
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "dai-i18n"))
from dai_i18n.catalog import pairs_in_source  # noqa: E402

HEBREW = re.compile(r"[֐-׿]")
LATIN = re.compile(r"[A-Za-z]")
PLACEHOLDER = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*(?::[^}]*)?\}")
BAD_BRAND = re.compile(r"\bD\.AI\b|\bDAi\b|\bD\.ai\b|(?<!\()\bd\.Ai\b|\bDAI\b")   # "(d.Ai)" is the author's mark
# Hebrew texts that are rightly the same as, or mostly, English: names, codes, commands.
SAME_OK = re.compile(r"^[\w\s./:+\-—–·•,()\[\]'\"?!@#%&*=<>|{}~…]*$")
PAIRS = {"(": ")", "[": "]", "{": "}", "“": "”", "„": "”", "«": "»"}


def balanced(text: str, hebrew: bool = False) -> bool:
    for open_, close in PAIRS.items():
        if text.count(open_) != text.count(close) and not (open_ == "„" or open_ == "“"):
            return False
    quotes = re.sub(r"(?<=[\u0590-\u05FF])\"(?=[\u0590-\u05FF])", "", text) if hebrew else text   # ע"י: gershayim, not a quote
    return quotes.count('"') % 2 == 0


def spacing_problems(text: str, french: bool = False) -> list[str]:
    """Indentation and column alignment are deliberate; a space before a comma or a full stop is not."""
    found = []
    if not french and re.search(r"[^\s.]\s[,.;](?=\s|$)", text):
        found.append("space before punctuation")
    if "..." in text:
        found.append("three dots instead of …")
    if text.rstrip() != text.rstrip(" ") and text.endswith("  "):
        found.append("trailing spaces")
    return found


class CodeTexts(unittest.TestCase):
    """Every (en, he) pair in apps/*: the same placeholders, each in its own language, tidy."""

    @classmethod
    def setUpClass(cls):
        cls.pairs = []
        for path in sorted((ROOT / "apps").glob("*/*/*.py")):
            if "/tests/" in path.as_posix():
                continue
            try:
                found = pairs_in_source(path.read_text(encoding="utf-8"), path.as_posix())
            except (SyntaxError, UnicodeDecodeError):
                continue
            cls.pairs += [(path.relative_to(ROOT).as_posix(), line, en, he) for en, he, line in found]
        assert len(cls.pairs) > 1000, len(cls.pairs)

    def test_placeholders_match(self):
        """A placeholder on one side only is a forgotten one (different names on both sides are fed by the caller)."""
        bad = [(f, l, en) for f, l, en, he in self.pairs
               if bool(PLACEHOLDER.search(en)) != bool(PLACEHOLDER.search(he))]
        self.assertEqual(bad, [])

    def test_each_side_is_in_its_own_language(self):
        hebrew_in_english = [(f, l, en) for f, l, en, he in self.pairs if HEBREW.search(en)]
        self.assertEqual(hebrew_in_english, [])
        english_only_hebrew = [(f, l, he) for f, l, en, he in self.pairs
                               if not HEBREW.search(he) and LATIN.search(he) and he != en and not SAME_OK.match(he.replace(en, ""))]
        self.assertEqual(english_only_hebrew, [])

    def test_brand_spelling_and_spacing(self):
        brand = [(f, l, t) for f, l, en, he in self.pairs for t in (en, he) if BAD_BRAND.search(t)]
        self.assertEqual(brand, [])
        spacing = [(f, l, t, p) for f, l, en, he in self.pairs for t in (en, he) for p in spacing_problems(t)]
        self.assertEqual(spacing, [])

    def test_brackets_and_quotes_are_balanced(self):
        bad = [(f, l, t) for f, l, en, he in self.pairs for t, hebrew in ((en, False), (he, True)) if not balanced(t, hebrew)]
        self.assertEqual(bad, [])


def _shape(value, path=""):
    """Every key path of a JSON document, with list lengths, so eight languages can be compared."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            out.update(_shape(item, f"{path}.{key}"))
        return out
    if isinstance(value, list):
        out = {path: f"list[{len(value)}]"}
        for i, item in enumerate(value):
            out.update(_shape(item, f"{path}[{i}]"))
        return out
    return {path: type(value).__name__}


def _strings(value, path=""):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(item, f"{path}.{key}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from _strings(item, f"{path}[{i}]")
    elif isinstance(value, str):
        yield path, value


class SiteTexts(unittest.TestCase):
    """site/src/strings/*.json: the same shape in every language, nothing empty, placeholders kept."""

    @classmethod
    def setUpClass(cls):
        cls.data = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "site/src/strings").glob("*.json"))}
        assert set(cls.data) == {"ar", "de", "en", "es", "fr", "he", "pt", "ru"}, set(cls.data)

    def test_same_shape_in_every_language(self):
        reference = _shape(self.data["en"])
        for lang, data in self.data.items():
            with self.subTest(lang):
                shape = _shape(data)
                self.assertEqual(sorted(set(reference) - set(shape)), [], "missing in " + lang)
                self.assertEqual(sorted(set(shape) - set(reference)), [], "extra in " + lang)
                self.assertEqual({k: v for k, v in shape.items() if v != reference.get(k)}, {}, "different in " + lang)

    def test_nothing_empty_and_placeholders_kept(self):
        english = dict(_strings(self.data["en"]))
        for lang, data in self.data.items():
            with self.subTest(lang):
                texts = dict(_strings(data))
                empty = [k for k, v in texts.items() if not v.strip() and english.get(k, "x").strip()]
                self.assertEqual(empty, [])
                placeholders = [k for k, v in texts.items() if k in english
                                and set(PLACEHOLDER.findall(v)) != set(PLACEHOLDER.findall(english[k]))]
                self.assertEqual(placeholders, [])
                spacing = [(k, p) for k, v in texts.items() for p in spacing_problems(v, french=lang == "fr") if p != "three dots instead of …"]
                self.assertEqual(spacing, [])
                brand = [k for k, v in texts.items() if BAD_BRAND.search(v)]
                self.assertEqual(brand, [])

    def test_hebrew_and_english_are_in_their_languages(self):
        he = dict(_strings(self.data["he"]))
        en = dict(_strings(self.data["en"]))
        self.assertEqual([k for k, v in en.items() if HEBREW.search(v)], [])
        latin_only = [k for k, v in he.items() if LATIN.search(v) and not HEBREW.search(v)
                      and v.replace("\u200f", "") != en.get(k) and len(v.split()) > 3]   # names stay names
        self.assertEqual(latin_only, [])


class DesktopFiles(unittest.TestCase):
    """Every D.Ai menu entry has a Hebrew name and comment next to the English one, and runs what it names."""

    def test_names_in_both_languages(self):
        files = sorted((ROOT / "apps").glob("*/data/*.desktop"))
        self.assertGreater(len(files), 15)
        for path in files:
            with self.subTest(path.name):
                parser = configparser.RawConfigParser(strict=False, interpolation=None)
                parser.optionxform = str  # type: ignore[assignment,method-assign]
                parser.read(path, encoding="utf-8")
                entry = parser["Desktop Entry"]
                if entry.get("NoDisplay", "false") == "true" or entry.get("Type") != "Application":
                    continue
                self.assertTrue(entry.get("Name"), "Name")
                self.assertTrue(entry.get("Name[he]", "").strip(), "Name[he]")   # a product name may stay as it is
                if entry.get("Comment"):
                    self.assertTrue(HEBREW.search(entry.get("Comment[he]", "")), "Comment[he]")
                    self.assertEqual(spacing_problems(entry["Comment"]), [])
                self.assertTrue(entry.get("Exec"), "Exec")


if __name__ == "__main__":
    unittest.main()
