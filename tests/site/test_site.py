# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The website: Hebrew RTL, accessible structure, AA contrast, no trackers."""

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

SITE = Path(__file__).resolve().parents[2] / "site"
PAGES = sorted(SITE.glob("*.html"))


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
        self.assertEqual({p.name for p in PAGES}, {"index.html", "privacy.html", "accessibility.html", "terms.html"})

    def test_language_direction_and_basics(self):
        for path in PAGES:
            with self.subTest(page=path.name):
                page = parse(path)
                self.assertEqual((page.html_attrs.get("lang"), page.html_attrs.get("dir")), ("he", "rtl"))
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
            with self.subTest(page=path.name):
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
                        self.assertTrue((SITE / url).exists())

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
