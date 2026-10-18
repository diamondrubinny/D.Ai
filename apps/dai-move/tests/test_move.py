# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from dai_move import cli
from dai_move.browsers import bookmarks_html, wifi_names
from dai_move.core import execute, find_users, plan

BOOKMARKS = {"roots": {
    "bookmark_bar": {"type": "folder", "name": "Bookmarks bar", "children": [
        {"type": "url", "name": "Bank <Leumi>", "url": "https://www.leumi.co.il/"},
        {"type": "url", "name": "evil", "url": "javascript:alert(document.cookie)"},
        {"type": "folder", "name": "Work", "children": [
            {"type": "url", "name": "Docs", "url": "https://docs.example.com/?a=1&b=2"}]},
    ]},
    "other": {"type": "folder", "name": "Other", "children": []},
}}
WLAN = """<?xml version="1.0"?>
<WLANProfile><name>Home &amp; Office</name><MSM><security><sharedKey>
<keyMaterial>01000000D08C9DDF0115D1118C7A00C04FC297EB</keyMaterial></sharedKey></security></MSM></WLANProfile>
"""


class MoveTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.drive, self.home = base / "Windows", base / "home"
        user = self.drive / "Users" / "Dana"
        for rel, content in {
            "Documents/thesis.docx": "thesis", "Documents/taxes/2025.pdf": "pdf", "Pictures/beach.jpg": "jpg",
            "Desktop/notes.txt": "windows notes", "Documents/desktop.ini": "junk", "Pictures/Thumbs.db": "junk",
            "Downloads/setup.exe": "exe",
        }.items():
            (user / rel).parent.mkdir(parents=True, exist_ok=True)
            (user / rel).write_text(content)
        (self.drive / "Users" / "Public" / "Documents").mkdir(parents=True)
        (self.drive / "Users" / "Default").mkdir()
        outside = base / "secret"
        outside.mkdir()
        (outside / "password.txt").write_text("x")
        (user / "Documents" / "link").symlink_to(outside)
        chrome = user / "AppData/Local/Google/Chrome/User Data/Default/Bookmarks"
        chrome.parent.mkdir(parents=True)
        chrome.write_text(json.dumps(BOOKMARKS))
        profile = self.drive / "ProgramData/Microsoft/Wlansvc/Profiles/Interfaces/{GUID}/1.xml"
        profile.parent.mkdir(parents=True)
        profile.write_text(WLAN)
        (self.home / "Desktop").mkdir(parents=True)
        (self.home / "Desktop" / "notes.txt").write_text("linux notes")

    def tearDown(self):
        self.tmp.cleanup()


class CoreTests(MoveTestCase):
    def test_finds_real_users_only(self):
        self.assertEqual([u.name for u in find_users([self.drive])], ["Dana"])
        copied_folder = self.drive / "Users" / "Dana"
        self.assertEqual([u.home for u in find_users([copied_folder])], [copied_folder])

    def test_plan_and_copy_never_overwrite(self):
        user = find_users([self.drive])[0]
        work = plan(user, self.home)
        destinations = {str(d.relative_to(self.home)) for _, d in work.copies}
        self.assertEqual(destinations, {"Documents/thesis.docx", "Documents/taxes/2025.pdf", "Pictures/beach.jpg",
                                        "Desktop/notes (Windows).txt", "Downloads/setup.exe"})
        self.assertEqual((work.renamed, work.skipped), (1, 2))
        copied, errors = execute(work, self.home)
        self.assertEqual((copied, errors), (5, []))
        self.assertEqual((self.home / "Desktop/notes.txt").read_text(), "linux notes")
        self.assertEqual((self.home / "Desktop/notes (Windows).txt").read_text(), "windows notes")
        self.assertFalse(any("password" in str(p) for p in self.home.rglob("*")))  # symlink not followed
        self.assertTrue((self.drive / "Users/Dana/Documents/thesis.docx").exists())  # source untouched

    def test_not_enough_space(self):
        work = plan(find_users([self.drive])[0], self.home)
        work.bytes = 10**18
        with self.assertRaisesRegex(OSError, "not enough space"):
            execute(work, self.home)


class BrowserTests(MoveTestCase):
    def test_bookmarks_are_safe_html(self):
        content, count = bookmarks_html(self.drive / "Users" / "Dana")
        self.assertEqual(count, 2)
        self.assertIn("NETSCAPE-Bookmark-file-1", content)
        self.assertIn("Bank &lt;Leumi&gt;", content)
        self.assertIn("https://docs.example.com/?a=1&amp;b=2", content)
        self.assertNotIn("javascript:", content)

    def test_wifi_names_only(self):
        self.assertEqual(wifi_names(self.drive), ["Home & Office"])


class CliTests(MoveTestCase):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(Path, "home", return_value=self.home), \
                mock.patch.dict(os.environ, {"LANG": "en_US.UTF-8"}), redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["dai-move", *args])
        return code, out.getvalue() + err.getvalue()

    def test_dry_run_then_copy(self):
        code, out = self.run_cli(str(self.drive), "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("Total 5 files", out)
        self.assertIn("Home & Office", out)
        self.assertFalse((self.home / "Documents").exists())
        code, out = self.run_cli(str(self.drive), "--yes")
        self.assertEqual(code, 0, out)
        self.assertIn("Copied 5 files", out)
        self.assertIn("NETSCAPE", (self.home / "Bookmarks-from-Windows.html").read_text())

    def test_nothing_found(self):
        code, out = self.run_cli(str(self.home / "nothing"))
        self.assertEqual(code, 1)
        self.assertIn("BitLocker", out)


class CommandTests(unittest.TestCase):
    def test_command_bar(self):
        try:
            from dai_command import core
        except ImportError:
            self.skipTest("dai_command not on the path")
        with mock.patch("shutil.which", return_value="/usr/bin/dai-move"):
            for text in ("import my files from windows", "תעביר את הקבצים מווינדוס", "להעתיק מהמחשב הישן"):
                rows = core.build_actions(text, [])
                self.assertEqual(rows[0].kind, "move", text)
            self.assertNotEqual(core.build_actions("windows 11 wallpaper", [])[:1] and
                                core.build_actions("windows 11 wallpaper", [])[0].kind, "move")


if __name__ == "__main__":
    unittest.main()
