# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""D.Ai Focus (docs/BEYOND.md §5), with the system replaced by fakes."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from dai_focus import cli


class FakeControls:
    def __init__(self, dnd=False):
        self._dnd, self.calls = dnd, []

    def dnd(self):
        return self._dnd

    def set_dnd(self, on):
        self.calls.append(on)
        self._dnd = on
        return True


class FakeSystem:
    """pgrep, pkill, systemd-run, systemctl and notify-send, remembered."""

    def __init__(self, nightlight=False, tools=("wlsunset", "systemd-run", "notify-send")):
        self.nightlight, self.tools, self.calls, self.popens = nightlight, set(tools), [], []

    def run(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[:2] == ["pgrep", "-x"]:
            return subprocess.CompletedProcess(argv, 0 if self.nightlight else 1, "", "")
        if argv[:2] == ["pkill", "-x"]:
            self.nightlight = False
        return subprocess.CompletedProcess(argv, 0, "", "")

    def popen(self, argv, **kwargs):
        self.popens.append(argv)
        self.nightlight = True

    def which(self, name):
        return f"/usr/bin/{name}" if name in self.tools else None


class FocusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "dai" / "focus.json"
        self.clock = [1000.0]
        self.system = FakeSystem()
        self.controls = FakeControls()
        self.session = cli.Session(self.system.run, self.system.popen, self.system.which, self.controls,
                                   self.path, lambda: self.clock[0])

    def test_start_quiets_warms_and_arms_a_timer(self):
        code, message = self.session.start(40, "en")
        self.assertEqual(code, 0)
        self.assertIn("40 minutes", message)
        self.assertEqual(self.controls.calls, [True])
        self.assertEqual(self.system.popens, [cli.WLSUNSET])
        self.assertIn(["systemd-run", "--user", "--quiet", "--unit=dai-focus-end", "--on-active=40m",
                       "--description=D.Ai Focus: the session ends", "dai-focus", "stop", "--by-timer"], self.system.calls)
        data = json.loads(self.path.read_text())
        self.assertEqual((data["minutes"], data["dnd_before"], data["nightlight_started"], data["timer"]), (40, False, True, True))
        self.assertTrue(any(c[0] == "notify-send" for c in self.system.calls))

    def test_stop_puts_everything_back(self):
        self.session.start(25, "en")
        self.clock[0] += 7 * 60
        code, message = self.session.stop("en")
        self.assertEqual(code, 0)
        self.assertIn("stopped after 7 minutes", message)
        self.assertEqual(self.controls.calls, [True, False])
        self.assertIn(["pkill", "-x", "wlsunset"], self.system.calls)
        self.assertIn(["systemctl", "--user", "stop", "dai-focus-end.timer"], self.system.calls)
        self.assertFalse(self.path.exists())

    def test_what_was_already_on_stays_on(self):
        self.controls._dnd = True
        self.system.nightlight = True
        self.session.start(25, "en")
        self.assertEqual(self.controls.calls, [])          # do not disturb was the person's own choice
        self.assertEqual(self.system.popens, [])            # the night light too
        code, message = self.session.stop("en")
        self.assertEqual(self.controls.calls, [])
        self.assertNotIn(["pkill", "-x", "wlsunset"], self.system.calls)
        self.assertIn("Nothing had been changed", message)

    def test_the_timer_ends_it_and_no_double_session(self):
        self.session.start(25, "he")
        code, message = self.session.start(25, "he")
        self.assertEqual(code, 1)
        self.assertIn("כבר רץ", message)
        self.clock[0] += 25 * 60
        code, message = self.session.stop("he", by_timer=True)
        self.assertEqual(code, 0)
        self.assertIn("נגמר: 25 דקות", message)
        self.assertNotIn(["systemctl", "--user", "stop", "dai-focus-end.timer"], self.system.calls[-3:])

    def test_status_counts_down(self):
        self.assertIn("No focus session", self.session.status("en")[1])
        self.session.start(30, "en")
        self.clock[0] += 10 * 60 + 1
        self.assertIn("20 of 30 minutes left", self.session.status("en")[1])
        self.assertEqual(json.loads(self.session.status("en", as_json=True)[1]), {"active": True, "minutes": 30, "remaining": 20})

    def test_minutes_are_bounded_and_defaults_apply(self):
        self.assertEqual(cli.clamp_minutes(None), 25)
        self.assertEqual(cli.clamp_minutes("abc"), 25)
        self.assertEqual(cli.clamp_minutes("2"), 5)
        self.assertEqual(cli.clamp_minutes("999"), 180)
        self.assertEqual(cli.clamp_minutes("45"), 45)

    def test_without_the_tools_it_still_works_and_says_so(self):
        self.system.tools = set()
        code, message = self.session.start(25, "en")
        self.assertEqual(code, 0)
        self.assertEqual(self.system.popens, [])
        data = json.loads(self.path.read_text())
        self.assertFalse(data["timer"])
        self.assertFalse(data["nightlight_started"])
        self.assertEqual(self.controls.calls, [True])

    def test_never_a_shell(self):
        self.session.start(25, "en")
        self.session.stop("en")
        for argv in self.system.calls + self.system.popens:
            self.assertIsInstance(argv, list)
            self.assertNotIn(argv[0], ("sh", "bash"))

    def test_cli_verbs(self):
        self.assertEqual(cli.main(["dai-focus", "status"], self.session), 0)
        self.assertEqual(cli.main(["dai-focus", "start", "15"], self.session), 0)
        self.assertEqual(cli.main(["dai-focus", "start"], self.session), 1)
        self.assertEqual(cli.main(["dai-focus", "stop"], self.session), 0)
        self.assertEqual(cli.main(["dai-focus", "stop"], self.session), 1)
        self.assertEqual(cli.main(["dai-focus", "dance"], self.session), 2)
        self.assertEqual(cli.main(["dai-focus", "--version"], self.session), 0)


if __name__ == "__main__":
    unittest.main()
