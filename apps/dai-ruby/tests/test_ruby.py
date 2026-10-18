# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Ruby's settings (docs/BROWSER.md stage 1): private by default, nothing locked that is the user's choice."""

import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"


def luminance(hex_colour: str) -> float:
    channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class PolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policies = json.loads((DATA / "policies.json").read_text())["policies"]

    def test_privacy_by_default(self):
        p = self.policies
        self.assertTrue(p["DisableTelemetry"])
        self.assertTrue(p["DisableFirefoxStudies"])
        self.assertTrue(p["EnableTrackingProtection"]["Value"])
        self.assertEqual(p["Cookies"]["Behavior"], "reject-tracker-and-partition-foreign")
        self.assertEqual(p["HttpsOnlyMode"], "enabled")
        self.assertTrue(p["PopupBlocking"]["Default"])
        self.assertFalse(p["FirefoxSuggest"]["SponsoredSuggestions"])
        self.assertFalse(p["FirefoxHome"]["SponsoredTopSites"])
        self.assertFalse(p["Preferences"]["browser.ml.chat.enabled"]["Value"])  # no AI pushed on anyone

    def test_automatic_cleaning_keeps_what_people_need(self):
        clean = self.policies["SanitizeOnShutdown"]
        self.assertTrue(clean["Cookies"] and clean["Cache"])
        self.assertFalse(clean["History"] or clean["Sessions"] or clean["SiteSettings"])  # exceptions survive

    def test_the_users_choices_are_not_locked(self):
        for name in ("Cookies", "SanitizeOnShutdown", "PopupBlocking", "EnableTrackingProtection", "DNSOverHTTPS"):
            self.assertFalse(self.policies[name]["Locked"], name)

    def test_only_the_two_known_extensions_from_mozilla(self):
        extensions = self.policies["ExtensionSettings"]
        self.assertEqual(sorted(extensions), ["@testpilot-containers", "uBlock0@raymondhill.net"])
        for settings in extensions.values():
            self.assertEqual(settings["installation_mode"], "force_installed")
            self.assertTrue(settings["install_url"].startswith("https://addons.mozilla.org/firefox/downloads/"))
        lists = self.policies["3rdparty"]["Extensions"]["uBlock0@raymondhill.net"]["toOverwrite"]["filterLists"]
        for wanted in ("easylist", "easyprivacy", "fanboy-cookiemonster", "ISR-0", "user-filters"):
            self.assertIn(wanted, lists)

    def test_preferences_use_allowed_prefixes(self):
        allowed = ("browser.", "dom.", "media.", "network.", "extensions.", "ui.", "widget.")
        for name in self.policies["Preferences"]:
            self.assertTrue(name.startswith(allowed), name)


class DesktopTests(unittest.TestCase):
    def test_one_menu_entry_named_ruby_running_firefox_unmodified(self):
        text = (DATA / "firefox-esr.desktop").read_text()
        self.assertIn("\nName=Ruby\n", text)
        self.assertIn("\nName[he]=רובי\n", text)
        self.assertIn("StartupWMClass=firefox-esr", text)  # windows keep Firefox's app id
        commands = re.findall(r"^Exec=(\S+)", text, re.M)
        self.assertEqual(len(commands), 3)
        self.assertEqual(set(commands), {"/usr/lib/firefox-esr/firefox-esr"})
        self.assertIn("Firefox ESR", text)  # it says what it is


class StartPage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []
        self.ids: dict[str, dict] = {}
        self.sections = {"he": 0, "en": 0}
        self.current = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for key in ("src", "href"):
            if a.get(key):
                self.links.append(a[key])
        if tag == "div" and a.get("id") in self.sections:
            self.current = a["id"]
        if tag == "section" and self.current:
            self.sections[self.current] += 1


class StartPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (DATA / "start.html").read_text()
        cls.page = StartPage()
        cls.page.feed(cls.html)

    def test_local_only(self):
        self.assertIn("default-src 'none'", self.html)
        self.assertEqual([l for l in self.page.links if re.match(r"(?i)https?:|//", l)], [])

    def test_hebrew_first_and_both_languages_say_the_same(self):
        self.assertIn('<html lang="he" dir="rtl">', self.html)
        self.assertEqual(self.page.sections["he"], self.page.sections["en"])
        self.assertIn("© 2026 Diamond Rubinny (d.Ai)", self.html)
        self.assertIn("trademark of the Mozilla Foundation", self.html)

    def test_contrast_is_aa(self):
        colours = dict(re.findall(r"--([a-z]+):\s*(#[0-9A-Fa-f]{6})", self.html))
        for name in ("text", "muted", "ruby", "cyan"):
            for surface in ("bg", "card"):
                self.assertGreaterEqual(contrast(colours[name], colours[surface]), 4.5, f"{name} on {surface}")


if __name__ == "__main__":
    unittest.main()
