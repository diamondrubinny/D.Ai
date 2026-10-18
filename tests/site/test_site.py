# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The website: Hebrew RTL and seven more languages, accessible structure, AA contrast, no trackers."""

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

SITE = Path(__file__).resolve().parents[2] / "site"
LANGS = ("en", "ar", "ru", "es", "fr", "de", "pt")
PAGES = sorted([*SITE.glob("*.html"), *(SITE / lang / "index.html" for lang in LANGS)])
RTL = {"he", "ar"}
SECTION_IDS = {"main", "hero-title", "why", "why-title", "see-title", "windows", "windows-title", "honest",
               "honest-title", "download", "download-title", "faq-title"}


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.headings, self.html_attrs = [], [], {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "html":
            self.html_attrs = attrs
        if re.fullmatch(r"h[1-6]", tag):
            self.headings.append(int(tag[1]))
        self.tags.append((tag, attrs))


def parse(path):
    page = Page()
    page.feed(path.read_text(encoding="utf-8"))
    return page


def luminance(hex_color):
    channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class SiteTests(unittest.TestCase):
    def test_pages_exist(self):
        self.assertEqual({p.name for p in SITE.glob("*.html")}, {"index.html", "privacy.html", "accessibility.html",
                                                                "terms.html"})
        for lang in LANGS:
            self.assertTrue((SITE / lang / "index.html").is_file(), lang)

    def test_every_language_has_the_same_page(self):
        for lang in LANGS:
            with self.subTest(lang=lang):
                page = parse(SITE / lang / "index.html")
                ids = {a.get("id") for _, a in page.tags if a.get("id")}
                self.assertTrue(SECTION_IDS <= ids, SECTION_IDS - ids)
                self.assertIn("draft", (SITE / lang / "index.html").read_text(encoding="utf-8"))  # until reviewed

    def test_the_switcher_is_generated(self):
        import subprocess
        import sys
        script = SITE.parent / "build/scripts/site-languages.py"
        result = subprocess.run([sys.executable, str(script), "--check"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_the_language_switcher(self):
        for path in PAGES:
            if path.name != "index.html":
                continue
            with self.subTest(page=str(path.relative_to(SITE))):
                page = parse(path)
                switch = [a for t, a in page.tags if t == "a" and a.get("hreflang")]
                self.assertEqual(sorted(a["hreflang"] for a in switch), sorted(("he", *LANGS)))
                self.assertEqual(len([a for a in switch if a.get("aria-current") == "page"]), 1)
                for link in switch:
                    self.assertTrue((path.parent / link["href"]).resolve().is_file(), link["href"])
                alternates = [a for t, a in page.tags if t == "link" and a.get("rel") == "alternate"]
                self.assertEqual(len(alternates), 8)

    def test_language_direction_and_basics(self):
        for path in PAGES:
            with self.subTest(page=str(path.relative_to(SITE))):
                page = parse(path)
                lang = page.html_attrs.get("lang", "")
                expected = path.parent.name if path.parent != SITE else "he"
                self.assertEqual(lang.split("-")[0], expected)
                self.assertEqual(page.html_attrs.get("dir"), "rtl" if expected in RTL else "ltr")
                tags = [t for t, _ in page.tags]
                for required in ("title", "main", "header", "footer"):
                    self.assertIn(required, tags)
                self.assertTrue(any(a.get("class") == "skip" and a.get("href") == "#main" for t, a in page.tags if t == "a"))
                self.assertEqual(page.headings.count(1), 1)
                for previous, current in zip(page.headings, page.headings[1:]):
                    self.assertLessEqual(current, previous + 1, "heading levels must not skip")

    def test_images_have_alt_and_size(self):
        for path in PAGES:
            for tag, attrs in parse(path).tags:
                if tag == "img":
                    with self.subTest(page=path.name, src=attrs.get("src")):
                        self.assertIn("alt", attrs)  # "" for decorative images
                        self.assertTrue(attrs.get("width") and attrs.get("height"))  # no layout shift

    def test_no_scripts_trackers_or_third_party_resources(self):
        for path in PAGES:
            text = path.read_text(encoding="utf-8")
            with self.subTest(page=str(path.relative_to(SITE))):
                page = parse(path)
                self.assertNotIn("script", [t for t, _ in page.tags])
                self.assertNotRegex(text, r"(?i)google-analytics|googletagmanager|facebook\.net|hotjar|fonts\.googleapis")
                self.assertNotRegex(text, r'\sstyle="')  # the CSP forbids inline styles
                self.assertIn("Content-Security-Policy", text)
                for tag, attrs in page.tags:
                    if tag in ("img", "link"):
                        url = attrs.get("src") or attrs.get("href") or ""
                        self.assertFalse(url.startswith(("http:", "https:", "//")), url)

    def test_internal_links_and_files_exist(self):
        for path in PAGES:
            ids = {a.get("id") for _, a in parse(path).tags if a.get("id")}
            for tag, attrs in parse(path).tags:
                url = attrs.get("href") if tag in ("a", "link") else attrs.get("src") if tag == "img" else None
                if not url or url.startswith(("http", "mailto:")):
                    continue
                with self.subTest(page=path.name, url=url):
                    if url.startswith("#"):
                        self.assertIn(url[1:], ids)
                    else:
                        target = (path.parent / url).resolve()
                        self.assertTrue(target.exists())
                        self.assertTrue(target.is_relative_to(SITE), url)  # never outside the site

    def test_contrast_meets_wcag_aa(self):
        css = (SITE / "style.css").read_text(encoding="utf-8")
        tokens = dict(re.findall(r"--([\w-]+):\s*(#[0-9A-Fa-f]{6})", css))
        pairs = [("text", "bg-900"), ("text", "surface"), ("muted", "bg-800"), ("muted", "bg-900"),
                 ("accent-2", "bg-900"), ("accent-2", "bg-800"), ("soft", "bg-800"),
                 ("ok", "bg-800"), ("warn", "bg-800"), ("bad", "bg-800")]
        for fg, bg in pairs:
            with self.subTest(fg=fg, bg=bg):
                self.assertGreaterEqual(contrast(tokens[fg], tokens[bg]), 4.5)

    def test_credit(self):
        for path in PAGES:
            self.assertIn("Diamond Rubinny (d.Ai)", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
