# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""D.Ai Rotate (docs/MOBILE.md A3): monitor-sensor's lines become wlr-randr transforms under the person's choice."""
import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dai_rotate import cli, rotate

WLR = ('eDP-1 "Built-in"\n  Enabled: yes\n  Modes:\n    1920x1200 px, 60.000000 Hz (preferred, current)\n'
       '  Position: 0,0\n  Transform: normal\n  Scale: 1.000000\nHDMI-A-1 "Monitor"\n  Enabled: yes\n  Transform: 90\n')


class Runner:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def __call__(self, argv):
        self.calls.append(list(argv))
        if argv == ["wlr-randr"]:
            return subprocess.CompletedProcess(argv, 0, WLR, "")
        return subprocess.CompletedProcess(argv, 1 if self.fail else 0, "", "")


class RotateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.runner = Runner()
        patcher = mock.patch.dict(os.environ, {"LANG": "en_US.UTF-8", "LC_ALL": "", "LANGUAGE": "", "DAI_LANG": "en"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_lines_and_mapping(self):
        self.assertEqual(rotate.parse_line("=== Has accelerometer (orientation: left-up, tilt: vertical)"), "left-up")
        self.assertEqual(rotate.parse_line("    Accelerometer orientation changed: bottom-up"), "bottom-up")
        self.assertIsNone(rotate.parse_line("=== No accelerometer"))
        self.assertIsNone(rotate.parse_line("    Accelerometer orientation changed: sideways"))
        self.assertEqual([rotate.wanted(o, "auto") for o in ("normal", "left-up", "right-up", "bottom-up", "undefined")],
                         ["normal", "90", "270", "180", None])
        self.assertEqual(rotate.wanted("left-up", "off"), None)
        self.assertEqual(rotate.wanted("left-up", "180"), "180")

    def test_follow_turns_every_screen_once_per_change(self):
        lines = ["+++ iio-sensor-proxy appeared", "=== Has accelerometer (orientation: normal, tilt: vertical)",
                 "    Accelerometer orientation changed: left-up", "    Light changed: 3.0 (lux)",
                 "    Accelerometer orientation changed: left-up", "    Accelerometer orientation changed: normal"]
        applied = rotate.follow(lines, self.runner, self.home)
        self.assertEqual(applied, ["normal", "90", "normal"])
        turns = [c for c in self.runner.calls if c[:2] == ["wlr-randr", "--output"]]
        self.assertEqual(turns[:2], [["wlr-randr", "--output", "eDP-1", "--transform", "normal"],
                                     ["wlr-randr", "--output", "HDMI-A-1", "--transform", "normal"]])
        self.assertEqual(len(turns), 6)  # three changes, two screens; the repeated reading did nothing

    def test_the_choice_is_read_as_it_changes(self):
        rotate.set_mode("off", self.home)
        self.assertEqual(rotate.follow(["    Accelerometer orientation changed: left-up"], self.runner, self.home), [])
        rotate.set_mode("180", self.home)
        self.assertEqual(rotate.follow(["    Accelerometer orientation changed: left-up"], self.runner, self.home), ["180"])
        (self.home / rotate.MODE_FILE).write_text("sideways\n")
        self.assertEqual(rotate.mode(self.home), "auto")  # nonsense in the file means the default
        self.assertEqual(oct((self.home / rotate.MODE_FILE).stat().st_mode & 0o777), "0o600")
        with self.assertRaises(ValueError):
            rotate.set_mode("diagonal", self.home)
        with self.assertRaises(ValueError):
            rotate.apply("45", self.runner)

    def test_outputs_and_a_failing_wlr_randr(self):
        self.assertEqual(rotate.outputs(self.runner), ["eDP-1", "HDMI-A-1"])
        self.assertEqual(rotate.current_transform(self.runner, "HDMI-A-1"), "90")
        self.assertEqual(rotate.current_transform(self.runner, "eDP-1"), "normal")
        self.assertFalse(rotate.apply("90", Runner(fail=True)))
        self.assertEqual(rotate.follow(["    Accelerometer orientation changed: left-up"], Runner(fail=True), self.home), [])

    def run_cli(self, *args, which=lambda name: "/usr/bin/" + name):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["dai-rotate", *args], home=self.home, runner=self.runner, which=which)
        return code, out.getvalue(), err.getvalue()

    def test_command_line(self):
        code, out, _ = self.run_cli("status")
        self.assertEqual(code, 0)
        self.assertIn("Choice: auto", out)
        self.assertIn("Screen HDMI-A-1: transform 90", out)
        code, out, _ = self.run_cli("set", "90")
        self.assertEqual((code, "turned to 90" in out), (0, True), out)
        self.assertEqual(rotate.mode(self.home), "90")
        self.assertIn(["wlr-randr", "--output", "eDP-1", "--transform", "90"], self.runner.calls)
        self.assertEqual(self.run_cli("apply")[0], 0)
        code, out, _ = self.run_cli("set", "off")
        self.assertIn("Rotation lock", out)
        code, out, _ = self.run_cli("set", "auto")
        self.assertIn("follows the tablet", out)
        self.assertEqual(self.run_cli("set", "upside")[0], 2)
        code, out, _ = self.run_cli("run", which=lambda name: None)
        self.assertEqual((code, "nothing to follow" in out), (0, True))
        code, out, _ = self.run_cli("status", which=lambda name: None)
        self.assertIn("no iio-sensor-proxy", out)
        self.assertEqual(self.run_cli("dance")[0], 2)
        self.assertIn("dai-rotate 0.1.0", self.run_cli("--version")[1])


if __name__ == "__main__":
    unittest.main()
