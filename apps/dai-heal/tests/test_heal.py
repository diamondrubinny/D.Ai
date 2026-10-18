# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from dai_heal import cli
from dai_heal import fixes as F
from dai_heal import problems as P
from dai_heal.text import describe
from dai_heal.watch import QUIET_SECONDS, Watcher, ignore, ignored


class Fake:
    """Canned command output by prefix; records every command."""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def __call__(self, argv):
        argv = list(argv)
        self.calls.append(argv)
        for prefix, (code, out) in self.responses.items():
            if tuple(argv[:len(prefix)]) == prefix:
                return subprocess.CompletedProcess(argv, code, out, "")
        return subprocess.CompletedProcess(argv, 0, "", "")


class HealCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        patch = mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.home / ".local/state"), "HOME": str(self.home),
                                             "LANG": "en_US.UTF-8"})
        patch.start()
        self.addCleanup(patch.stop)


class ProblemTests(HealCase):
    def test_failed_units_with_their_log(self):
        fake = Fake({("systemctl", "list-units"): (0, "● cups.service loaded failed failed CUPS Scheduler\n"),
                     ("systemctl", "--user", "list-units"): (0, "syncthing.service loaded failed failed Syncthing\n"),
                     ("journalctl", "-u", "cups.service"): (0, "cupsd: Unable to open /etc/cups/cupsd.conf\n")})
        system = P.failed_units(fake)
        user = P.failed_units(fake, user=True)
        self.assertEqual([(p.kind, p.name) for p in system + user], [("service", "cups.service"),
                                                                     ("user-service", "syncthing.service")])
        self.assertIn("Unable to open", system[0].detail)

    def test_crashes_are_the_users_own_and_grouped(self):
        uid = os.getuid()
        rows = [{"time": 1_800_000_000_000_000, "pid": 10, "uid": uid, "sig": 11, "exe": "/usr/bin/gimp"},
                {"time": 1_800_000_100_000_000, "pid": 11, "uid": uid, "sig": 11, "exe": "/usr/bin/gimp"},
                {"time": 1_800_000_200_000_000, "pid": 12, "uid": uid + 1, "sig": 6, "exe": "/usr/bin/other"}]
        found = P.crashes(Fake({("coredumpctl",): (0, json.dumps(rows))}))
        self.assertEqual([(p.name, p.count, p.extra["exe"]) for p in found], [("gimp", 2, "/usr/bin/gimp")])
        self.assertEqual(found[0].when, 1_800_000_100)
        self.assertEqual(P.crashes(Fake({("coredumpctl",): (1, "No coredumps found.")})), [])

    def test_forge_crash_reports(self):
        directory = P.state_dir()
        directory.mkdir(parents=True)
        (directory / "forge-prices.json").write_text(json.dumps(
            {"kind": "forge-app", "name": "prices", "when": 5, "detail": "ValueError: boom", "count": 2,
             "extra": {"title": "Prices"}}))
        (directory / "forge-bad.json").write_text("{not json")
        (directory / "forge-evil.json").write_text(json.dumps({"kind": "forge-app", "name": "../../etc"}))
        found = P.forge_crashes()
        self.assertEqual([(p.name, p.count) for p in found], [("prices", 2)])
        self.assertEqual(describe(found[0], "he"), "האפליקציה שלך „Prices” קרסה (2 פעמים).")


class FixTests(HealCase):
    def test_closed_list_per_kind(self):
        (self.home / ".config/gimp").mkdir(parents=True)
        crash = P.Problem("crash", "gimp", extra={"exe": "/usr/bin/gimp"})
        self.assertEqual(F.fixes_for(crash, self.home), [F.Fix("relaunch", "/usr/bin/gimp"), F.Fix("reset-settings", "gimp")])
        self.assertEqual(F.fixes_for(P.Problem("crash", "x", extra={"exe": "/tmp/evil/x"}), self.home), [])
        self.assertEqual(F.fixes_for(P.Problem("service", "cups.service")), [F.Fix("tune", "restart service cups.service")])
        self.assertEqual(F.fixes_for(P.Problem("forge-app", "prices")), [F.Fix("forge-repair", "prices")])

    def test_service_restart_through_tune_then_verified(self):
        problem = P.Problem("service", "cups.service")
        sentences = []
        active = Fake({("systemctl", "is-active"): (0, "active\n")})
        outcome = F.apply(F.Fix("tune", "restart service cups.service"), problem, runner=active,
                          tune=lambda s: (sentences.append(s), (True, ""))[1])
        self.assertEqual((outcome.ok, outcome.key, sentences), (True, "fixed", ["restart service cups.service"]))
        failing = Fake({("systemctl", "is-active"): (3, "failed\n"), ("systemctl", "status"): (3, "cupsd: bad config")})
        outcome = F.apply(F.Fix("tune", "restart service cups.service"), problem, runner=failing, tune=lambda s: (True, ""))
        self.assertEqual((outcome.ok, outcome.key), (False, "still_failing"))
        self.assertIn("bad config", outcome.detail)
        cancelled = F.apply(F.Fix("tune", "x"), problem, runner=active, tune=lambda s: (False, "authorization cancelled"))
        self.assertEqual((cancelled.ok, cancelled.detail), (False, "authorization cancelled"))

    def test_user_service_restart(self):
        fake = Fake({("systemctl", "--user", "is-active"): (0, "active\n")})
        with mock.patch.object(F.time, "sleep"):
            outcome = F.apply(F.Fix("user-restart", "syncthing.service"), P.Problem("user-service", "syncthing.service"),
                              runner=fake)
        self.assertTrue(outcome.ok)
        self.assertIn(["systemctl", "--user", "restart", "syncthing.service"], fake.calls)
        bad = F.apply(F.Fix("user-restart", "x; rm -rf ~"), P.Problem("user-service", "x"), runner=fake)
        self.assertFalse(bad.ok)

    def test_reset_settings_keeps_them_and_can_put_them_back(self):
        settings = self.home / ".config/gimp"
        settings.mkdir(parents=True)
        (settings / "gimprc").write_text("broken")
        outcome = F.apply(F.Fix("reset-settings", "gimp"), P.Problem("crash", "gimp"), home=self.home)
        self.assertEqual(outcome.key, "settings_reset")
        self.assertFalse(settings.exists())
        self.assertEqual(Path(outcome.detail, "gimprc").read_text(), "broken")
        back = F.apply(outcome.undo, P.Problem("crash", "gimp"), home=self.home)
        self.assertTrue(back.ok)
        self.assertEqual((settings / "gimprc").read_text(), "broken")
        outside = F.apply(F.Fix("restore-settings", "/etc/passwd.dai-backup-1"), P.Problem("crash", "x"), home=self.home)
        self.assertFalse(outside.ok)

    def test_forge_repair_and_relaunch(self):
        repaired = F.apply(F.Fix("forge-repair", "prices"), P.Problem("forge-app", "prices", detail="ValueError"),
                           repair=lambda name, error: (True, "v3"))
        self.assertEqual((repaired.key, repaired.detail), ("repaired", "v3"))
        spawned = []
        outcome = F.apply(F.Fix("relaunch", "/usr/bin/env"), P.Problem("crash", "env"), spawn=spawned.append)
        self.assertEqual((outcome.ok, spawned), (True, [["/usr/bin/env"]]))
        self.assertFalse(F.apply(F.Fix("relaunch", "/tmp/x"), P.Problem("crash", "x"), spawn=spawned.append).ok)


class WatchTests(HealCase):
    def setUp(self):
        super().setUp()
        self.now = 1_800_000_000.0
        self.found = []
        self.shown = []
        self.watcher = Watcher(collect=lambda since=None: list(self.found), announce=lambda p, lang: self.shown.append(p.name),
                               clock=lambda: self.now)

    def test_once_then_quiet_then_again_when_it_repeats(self):
        self.found = [P.Problem("service", "cups.service", self.now)]
        self.watcher.check()
        self.watcher.check()
        self.assertEqual(self.shown, ["cups.service"])
        self.now += QUIET_SECONDS + 1
        self.watcher.check()
        self.assertEqual(self.shown, ["cups.service"])  # nothing new about it
        self.found = [P.Problem("service", "cups.service", self.now)]
        self.watcher.check()
        self.assertEqual(self.shown, ["cups.service", "cups.service"])

    def test_old_crashes_and_ignored_problems_are_not_announced(self):
        self.found = [P.Problem("crash", "gimp", self.now - 3600), P.Problem("crash", "vlc", self.now)]
        ignore(P.Problem("crash", "vlc").key)
        self.watcher.check()
        self.assertEqual(self.shown, [])
        self.assertEqual(len(ignored()), 1)


class CliTests(HealCase):
    def test_status_and_version(self):
        out = io.StringIO()
        with redirect_stdout(out):
            cli.main(["dai-heal", "--version"])
        self.assertIn("Diamond Rubinny (d.Ai)", out.getvalue())
        out = io.StringIO()
        with mock.patch.object(P, "collect", return_value=[P.Problem("service", "cups.service", 0, "cupsd: bad")]), \
                redirect_stdout(out):
            cli.main(["dai-heal", "status"])
        self.assertIn("The system service cups.service failed.", out.getvalue())
        self.assertIn("cupsd: bad", out.getvalue())


class CommandTests(unittest.TestCase):
    def test_command_bar(self):
        try:
            from dai_command import core
        except ImportError:
            self.skipTest("dai_command not on the path")
        with mock.patch("shutil.which", return_value="/usr/bin/dai-heal"):
            for text in ("משהו לא עובד", "something is broken", "firefox crashed", "יש לי תקלה", "תתקן את המחשב"):
                self.assertEqual(core.build_actions(text, [])[0].kind, "heal", text)
            for text in ("firefox", "work", "עובד"):
                self.assertNotIn("heal", [row.kind for row in core.build_actions(text, [])], text)


try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # PyQt6 is in the image; CI installs it for these tests
    QApplication = None


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class ChatTests(HealCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def window(self, found, **kwargs):
        from dai_heal.chat import HealWindow
        window = HealWindow(found, **kwargs)
        self.addCleanup(window.close)
        return window

    def wait(self, window):
        from PyQt6.QtTest import QTest
        for _ in range(100):
            QTest.qWait(20)
            if not window.threads:
                break
        QTest.qWait(30)

    def test_problem_fix_and_verify_in_hebrew(self):
        from PyQt6.QtCore import Qt
        problem = P.Problem("forge-app", "prices", 1_800_000_000, "Traceback (most recent call last):\nValueError: boom",
                            extra={"title": "מחירים"})
        applied = []

        def apply(fix, p):
            applied.append(fix)
            return F.Outcome(True, "repaired", "v2")
        with mock.patch.dict(os.environ, {"LANG": "he_IL.UTF-8"}):
            window = self.window([problem], focus=problem.key, apply=apply)
        self.assertEqual(window.layoutDirection(), Qt.LayoutDirection.RightToLeft)
        text = window.texts()
        self.assertIn("„מחירים” קרסה", text)
        self.assertIn("ValueError: boom", text)
        self.assertIn("תיקון האפליקציה עם ה־AI", text)
        button = next(b for b in window.findChildren(__import__("PyQt6.QtWidgets", fromlist=["QPushButton"]).QPushButton)
                      if b.text() == "\u202bתיקון האפליקציה עם ה־AI\u202c")
        button.click()
        self.wait(window)
        self.assertEqual(applied, [F.Fix("forge-repair", "prices")])
        self.assertIn("האפליקציה תוקנה ועברה בדיקה", window.texts())

    def test_free_text_goes_to_doctor(self):
        from types import SimpleNamespace
        finding = SimpleNamespace(level="warn", title="Disk almost full", detail="2 GB free", key="disk",
                                  fixes=[SimpleNamespace(kind="tune", label="Free disk space", payload="free up disk space")])
        window = self.window([], doctor=lambda text, lang: [finding])
        self.assertIn("I did not notice", window.texts())
        window.say.setText("why is my disk full?")
        window.send()
        self.wait(window)
        self.assertIn("Disk almost full — 2 GB free", window.texts())
        self.assertIn("Free disk space", window.texts())
        window.say.setText("blah")
        window.doctor = lambda text, lang: []
        window.send()
        self.wait(window)
        self.assertIn("could not match", window.texts())


if __name__ == "__main__":
    unittest.main()
