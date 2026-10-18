# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
import contextlib
import io
import json
import os
import stat
import subprocess
import tempfile
import time
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from unittest import mock

from dai_evolve import cli, scan, store

NOW = 1_800_000_000.0


def no_handler(argv):
    return subprocess.CompletedProcess(argv, 0, "", "")


def handler(argv):
    return subprocess.CompletedProcess(argv, 0, "vlc.desktop\n", "")


@dataclass
class FakeFix:
    kind: str
    label: str
    payload: str = ""


@dataclass
class FakeFinding:
    key: str
    level: str
    title: str
    fixes: list = field(default_factory=list)


@dataclass
class FakeProblem:
    key: str


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.home = root / "home"
        self.home.mkdir()
        patcher = mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(root / "state"),
                                               "XDG_CONFIG_HOME": str(root / "config"), "LANG": "C.UTF-8"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def scan(self, **kwargs):
        options = dict(home=self.home, now=NOW, run=no_handler, doctor=list, heal=list, model_ready=False,
                       recipes={"ebook-reader", "video-player", "image-editor", "archives"})
        options.update(kwargs)
        return scan.scan(**options)


class StoreTests(Base):
    def test_wish_is_kept_private_and_short(self):
        store.record_wish("תוכנה לעריכת סרטונים", clock=lambda: NOW)
        path = store.state_dir() / "wishes.jsonl"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        self.assertEqual([w["text"] for w in store.wishes_list(NOW)], ["תוכנה לעריכת סרטונים"])

    def test_passwords_and_tokens_are_never_kept(self):
        for text in ("Hunter2pass!x", "my token is abc", "ghp_a1b2c3d4e5f6g7h8i9j0 please", "x", "api_key here"):
            store.record_wish(text, clock=lambda: NOW)
        store.count_command(">curl -H 'Authorization: Bearer x' api", clock=lambda: NOW)
        self.assertEqual(store.wishes_list(NOW), [])
        self.assertEqual(store.read_json("commands.json", {}), {})

    def test_old_wishes_expire(self):
        store.record_wish("open epub books", clock=lambda: NOW - 31 * 86400)
        self.assertEqual(store.wishes_list(NOW), [])

    def test_off_keeps_nothing(self):
        store.record_wish("open epub books", clock=lambda: NOW)
        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(["dai-evolve", "off"])
        self.assertFalse((store.state_dir() / "wishes.jsonl").exists())
        store.record_wish("open epub books", clock=lambda: NOW)
        store.count_command(">df -h", clock=lambda: NOW)
        self.assertEqual(store.wishes_list(NOW), [])
        self.assertEqual(self.scan(), [])
        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(["dai-evolve", "on"])
        self.assertFalse(store.is_off())


class ScanTests(Base):
    def test_repeated_wish_becomes_a_forge_suggestion(self):
        store.record_wish("Video editor app", clock=lambda: NOW - 100)
        self.assertEqual(self.scan(), [])  # once is not a pattern
        store.record_wish("video editor app!", clock=lambda: NOW)
        found = self.scan()
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0].kind, found[0].action, found[0].payload), ("wish", "forge", "video editor app!"))
        self.assertIn("2", found[0].why("en"))

    def test_wish_without_a_model_is_retried_once_a_model_exists(self):
        store.record_wish("build a habit tracker", source="forge", reason="no-model", clock=lambda: NOW)
        self.assertEqual(self.scan(), [])
        found = self.scan(model_ready=True)
        self.assertEqual(found[0].payload, "build a habit tracker")
        self.assertIn("Diamond is installed", found[0].why("en"))

    def test_repeated_command_becomes_an_automation_request(self):
        for _ in range(3):
            store.count_command(">df -h /", clock=lambda: NOW)
            store.count_command(">sudo apt update", clock=lambda: NOW)
            store.count_command(">htop", clock=lambda: NOW)
        found = self.scan()
        self.assertEqual([s.kind for s in found], ["repeat"])
        self.assertIn("df -h /", found[0].payload)
        self.assertIn("every morning", found[0].payload)

    def test_file_type_without_a_program_suggests_a_recipe(self):
        books = self.home / "Downloads"
        books.mkdir()
        (books / "novel.epub").write_bytes(b"x")
        (books / "old.epub").write_bytes(b"x")
        old = time.time() - 60 * 86400
        os.utime(books / "old.epub", (old, old))
        found = self.scan(now=(books / "novel.epub").stat().st_mtime + 10)
        self.assertEqual([(s.kind, s.payload) for s in found], [("filetype", "install ebook-reader")])
        self.assertIn("1", found[0].why("en"))
        self.assertNotIn("novel", json.dumps([s.__dict__ for s in found]))  # names are never kept

    def test_no_suggestion_when_a_program_opens_it_or_no_recipe(self):
        (self.home / "Desktop").mkdir()
        (self.home / "Desktop" / "film.mkv").write_bytes(b"x")
        mtime = (self.home / "Desktop" / "film.mkv").stat().st_mtime
        self.assertEqual(self.scan(now=mtime, run=handler), [])
        self.assertEqual(self.scan(now=mtime, recipes=set()), [])

    def test_hidden_folders_are_not_looked_at(self):
        (self.home / "Documents" / ".cache").mkdir(parents=True)
        (self.home / "Documents" / ".cache" / "a.epub").write_bytes(b"x")
        self.assertEqual(self.scan(now=time.time()), [])

    def test_doctor_and_heal_findings(self):
        findings = [FakeFinding("disk.full", "bad", "The disk is almost full", [FakeFix("tune", "Free disk space", "free disk space")]),
                    FakeFinding("load", "ok", "fine", [FakeFix("tune", "x", "y")])]
        found = self.scan(doctor=lambda: findings, heal=lambda: [FakeProblem("unit:a"), FakeProblem("crash:b")])
        self.assertEqual([(s.kind, s.action, s.payload) for s in found],
                         [("doctor", "tune", "free disk space"), ("heal", "heal", "")])
        self.assertIn("2", found[1].why("he"))

    def test_dismissed_suggestions_stay_hidden(self):
        for _ in range(2):
            store.record_wish("play retro games", clock=lambda: NOW)
        key = self.scan()[0].key
        scan.dismiss(key)
        self.assertEqual(self.scan(), [])
        self.assertEqual(scan.saved(), [])

    def test_saved_is_what_command_reads(self):
        for _ in range(2):
            store.record_wish("play retro games", clock=lambda: NOW)
        self.scan()
        rows = scan.saved()
        self.assertEqual(rows[0].payload, "play retro games")
        (store.state_dir() / "suggestions.json").write_text('[{"bad": 1}, "x", {"key": "k", "kind": "wish", "title_en": "t",'
                                                              ' "title_he": "t", "why_en": "", "why_he": "", "action": "shell",'
                                                              ' "payload": "rm -rf /"}]')
        self.assertEqual(scan.saved(), [])  # unknown actions are never offered

    def test_acting_on_a_wish_forgets_it(self):
        for _ in range(2):
            store.record_wish("play retro games", clock=lambda: NOW)
        suggestion = self.scan()[0]
        opened = []
        cli.open_suggestion(suggestion, spawn=opened.append)
        self.assertEqual(opened, [["dai-forge-gui", "play retro games"]])
        self.assertEqual(store.wishes_list(NOW), [])
        self.assertEqual(scan.saved(), [])


class OpenTests(unittest.TestCase):
    def test_every_action_goes_to_a_review_screen(self):
        tune = scan.Suggestion("k", "doctor", "t", "t", "", "", "tune", "free disk space; rm -rf ~")
        argv = cli.open_argv(tune)
        self.assertEqual(argv[-1], "free disk space; rm -rf ~")  # passed as one argument, never through a shell string
        self.assertTrue(argv[4].startswith('dai-tune "$1"'))
        self.assertEqual(cli.open_argv(scan.Suggestion("k", "heal", "t", "t", "", "", "heal", "")), ["dai-heal"])


class NotifyTests(Base):
    def test_one_notification_a_day_and_only_new(self):
        for _ in range(2):
            store.record_wish("play retro games", clock=lambda: NOW)
        found = self.scan()
        sent = []
        send = lambda s, title, body, lang: sent.append((title, body))
        self.assertIsNotNone(cli.notify_new(found, "he", clock=lambda: NOW, send=send))
        self.assertIsNone(cli.notify_new(found, "he", clock=lambda: NOW + 2 * 86400, send=send))  # not new
        for _ in range(2):
            store.record_wish("learn to type faster", clock=lambda: NOW)
        found = self.scan()
        self.assertIsNone(cli.notify_new(found, "he", clock=lambda: NOW + 3600, send=send))  # too soon
        self.assertIsNotNone(cli.notify_new(found, "he", clock=lambda: NOW + 86400, send=send))
        self.assertEqual(len(sent), 2)
        self.assertIn("learn to type faster", sent[1][0])


class CliTests(Base):
    def test_suggest_json_and_dismiss(self):
        for _ in range(2):
            store.record_wish("play retro games", clock=lambda: NOW)
        self.scan()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["dai-evolve", "suggest", "--json"]), 0)
        rows = json.loads(out.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["dai-evolve", "dismiss", rows[0]["key"]]), 0)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["dai-evolve", "dismiss", "nope"]), 1)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["dai-evolve"])
        self.assertIn("Nothing to suggest", out.getvalue())

    def test_wishes_listing(self):
        store.record_wish("play retro games", reason="no-model", clock=lambda: NOW)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["dai-evolve", "wishes"])
        self.assertIn("play retro games  (no-model)", out.getvalue())


class CommandTests(Base):
    """D.Ai Command shows the last scan on an empty query and feeds the signals."""

    def setUp(self):
        super().setUp()
        try:
            from dai_command import core
        except ImportError:
            self.skipTest("dai_command is not on PYTHONPATH")
        self.core = core

    def test_empty_query_shows_suggestions_then_history(self):
        for _ in range(2):
            store.record_wish("play retro games", clock=lambda: NOW)
        self.scan()
        rows = self.core.build_actions("", [], ["firefox"])
        self.assertEqual([r.kind for r in rows], ["evolve", "history"])
        self.assertIn("play retro games", rows[0].title)
        self.assertEqual(rows[0].payload.action, "forge")

    def test_not_found_offers_to_build_it(self):
        with mock.patch.object(self.core.shutil, "which", side_effect=lambda name: "/usr/bin/x" if name == "dai-forge-gui" else None):
            rows = self.core.build_actions("an app for my recipes", [])
            self.assertEqual((rows[-1].kind, rows[-1].payload), ("forge", "an app for my recipes"))
            self.assertEqual(self.core.build_actions("2+2", [])[-1].kind, "calc")  # found something: no offer
        with mock.patch.object(self.core.shutil, "which", side_effect=lambda name: "/usr/bin/x"):
            self.assertNotIn("forge", [r.kind for r in self.core.build_actions("ls -la", [])])  # a command

    def test_forge_records_what_it_could_not_do(self):
        try:
            from dai_forge import apps
        except ImportError:
            self.skipTest("dai_forge is not on PYTHONPATH")
        apps.record_wish("build a habit tracker", "no-model")
        self.assertEqual([(w["source"], w["reason"]) for w in store.wishes_list()], [("forge", "no-model")])

    def test_window_counts_commands_and_dismisses(self):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        try:
            from PyQt6.QtWidgets import QApplication
            from dai_command import ui
        except ImportError:
            self.skipTest("PyQt6 is missing")
        app = QApplication.instance() or QApplication([])
        with mock.patch.object(ui, "load_apps", return_value=[]):
            window = ui.CommandWindow()
        window.history = self.core.History(Path(self.tmp.name) / "history")
        spawned = []
        window._spawn = spawned.append
        for text in (">df -h /", ">df -h /", " >df -h /", ">df -h /"):
            window.query.setText(text)
            window.activate_current()
        self.assertEqual(store.read_json("commands.json", {})[">df -h /"]["count"], 3)  # the private one is not counted
        self.scan()
        window.query.setText("x")
        window.query.setText("")
        self.assertEqual(window.results.item(0).data(ui.ACTION_ROLE).kind, "evolve")
        window.results.setCurrentRow(0)
        self.assertTrue(window.dismiss_current())
        self.assertEqual(scan.saved(), [])
        for _ in range(2):
            store.record_wish("play retro games", clock=lambda: NOW)
        self.scan()
        window.query.setText("x")
        window.query.setText("")
        window.results.setCurrentRow(0)
        window.activate_current()
        self.assertEqual(spawned[-1], ["dai-forge-gui", "play retro games"])
        window.close()
        app.processEvents()

if __name__ == "__main__":
    unittest.main()
