# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""D.Ai TV by sentence (docs/TV.md §10): night mode and the children's profile, the files Kodi reads, the running
Kodi told through dai-tv, undo."""
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from dai_tune import executor, parser, planner
from dai_tune.catalog import CATALOG, ValidationError
from dai_tune.context import Context


class Runner:
    def __init__(self):
        self.calls = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")


class TvSentenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        self.runner = Runner()
        self.ctx = Context(root=Path(self.tmp.name) / "root", home=self.home, runner=self.runner)

    def plan(self, text):
        return planner.plan_from_text(text, self.ctx)

    def test_sentences(self):
        cases = {"night mode": ("tv.night_mode", {"enabled": True}),
                 "מצב לילה": ("tv.night_mode", {"enabled": True}),
                 "turn off night mode": ("tv.night_mode", {"enabled": False}),
                 "כבה מצב לילה בטלוויזיה": ("tv.night_mode", {"enabled": False}),
                 "children's profile with pin 2468": ("tv.children_profile", {"enabled": True, "pin": "2468"}),
                 "פרופיל ילדים עם קוד 2468": ("tv.children_profile", {"enabled": True, "pin": "2468"}),
                 "kids mode": ("tv.children_profile", {"enabled": True, "pin": ""}),
                 "כבה פרופיל ילדים": ("tv.children_profile", {"enabled": False, "pin": ""})}
        for text, expected in cases.items():
            result = parser.parse(text)
            self.assertEqual([(r.action, r.params) for r in result.requests], [expected], text)
        self.assertNotIn("tv.night_mode", [r.action for r in parser.parse("good night").requests])

    def test_night_mode_writes_the_file_and_tells_kodi(self):
        settings = self.home / ".kodi/userdata/guisettings.xml"
        settings.parent.mkdir(parents=True)
        settings.write_text('<settings version="2">\n  <setting id="locale.language">resource.language.he_il</setting>\n</settings>\n')
        plan = self.plan("מצב לילה")
        self.assertTrue(plan.ok, plan.errors + plan.unknown)
        self.assertFalse(plan.weakens)
        journal = executor.Journal.for_user(self.ctx)
        entry = executor.apply_steps(plan.scoped("user"), self.ctx, journal, actor="1000", scope="user")
        text = settings.read_text()
        self.assertIn('<setting id="screensaver.mode">screensaver.xbmc.builtin.dim</setting>', text)
        self.assertIn('<setting id="screensaver.time">5</setting>', text)
        self.assertIn("resource.language.he_il", text)
        self.assertEqual(self.runner.calls[-1], ["dai-tv", "night", "on"])
        executor.undo_entry(entry, self.ctx, journal)
        self.assertNotIn("screensaver", settings.read_text())  # the file as it was
        self.assertEqual(self.runner.calls[-1], ["dai-tv", "night", "off"])
        off = self.plan("turn off night mode")
        executor.apply_steps(off.scoped("user"), self.ctx, journal, actor="1000", scope="user")
        self.assertIn('<setting id="screensaver.time">10</setting>', settings.read_text())

    def test_childrens_profile_locks_the_parents_behind_the_pin(self):
        profiles = self.home / ".kodi/userdata/profiles.xml"
        plan = self.plan("פרופיל ילדים עם קוד 2468")
        self.assertTrue(plan.ok, plan.errors + plan.unknown)
        self.assertEqual(plan.steps[0].params, {"enabled": True, "pin": "2468"})
        self.assertIn("2468", CATALOG["tv.children_profile"].summary(plan.steps[0].params, "he"))
        self.assertIn("PIN", CATALOG["tv.children_profile"].note(plan.steps[0].params, "en"))
        journal = executor.Journal.for_user(self.ctx)
        entry = executor.apply_steps(plan.scoped("user"), self.ctx, journal, actor="1000", scope="user")
        text = profiles.read_text()
        self.assertIn("<lockcode>" + hashlib.md5(b"2468").hexdigest() + "</lockcode>", text)  # Kodi's own scheme
        self.assertIn("<name>Children</name>", text)
        self.assertIn("<directory>profiles/Children/</directory>", text)
        self.assertIn("<canwritesources>false</canwritesources>", text)
        self.assertIn("<lockaddonmanager>true</lockaddonmanager>", text)
        self.assertIn("<autologin>1</autologin>", text)
        self.assertIn("<useloginscreen>true</useloginscreen>", text)
        self.assertIn("<nextIdProfile>2</nextIdProfile>", text)
        self.assertEqual(oct(profiles.stat().st_mode & 0o777), "0o600")
        executor.undo_entry(entry, self.ctx, journal)
        self.assertFalse(profiles.exists())  # there was none before
        # A PIN is made when none is said, and shown; a bad one is refused.
        made = self.plan("children's profile")
        self.assertRegex(made.steps[0].params["pin"], r"^[0-9]{4}$")
        with self.assertRaises(ValidationError):
            CATALOG["tv.children_profile"].validate({"enabled": True, "pin": "12"}, self.ctx)
        # Other profiles in an existing file are kept; "off" keeps the children's profile and drops the lock.
        profiles.parent.mkdir(parents=True, exist_ok=True)
        profiles.write_text("<profiles>\n  <lastloaded>0</lastloaded>\n  <profile>\n    <id>0</id>\n    <name>Master user</name>\n"
                            "    <directory pathversion=\"1\">special://masterprofile/</directory>\n  </profile>\n  <profile>\n"
                            "    <id>1</id>\n    <name>Dana</name>\n    <directory>profiles/Dana/</directory>\n  </profile>\n</profiles>\n")
        CATALOG["tv.children_profile"].apply({"enabled": True, "pin": "1357"}, self.ctx)
        text = profiles.read_text()
        self.assertIn("<name>Dana</name>", text)
        self.assertIn("<autologin>2</autologin>", text)  # the children got the next free id
        self.assertIn("<nextIdProfile>3</nextIdProfile>", text)
        CATALOG["tv.children_profile"].apply({"enabled": False, "pin": ""}, self.ctx)
        text = profiles.read_text()
        self.assertIn("<name>Children</name>", text)
        self.assertIn("<lockmode>0</lockmode>", text)
        self.assertIn("<lockcode>-</lockcode>", text)
        self.assertIn("<autologin>-1</autologin>", text)
        self.assertNotIn(hashlib.md5(b"1357").hexdigest(), text)


if __name__ == "__main__":
    unittest.main()
