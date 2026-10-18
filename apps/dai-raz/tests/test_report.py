# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Raz stage 4 (docs/RAZ.md §14): trends, the week in plain words, improvement items and the problem report."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dai_raz import cli, report

DAY = report.DAY
NOW = 1_800_000_000.0


def run(at, failed=(), boot=None, crashes=None):
    ids = ("commands", "firewall", "languages", "updates")
    return {"time": at, "results": [{"id": i, "area": "x", "status": "failed" if i in failed else "ok", "detail": "",
                                     "items": []} for i in ids],
            "metrics": {"boot_seconds": boot, "crashes_week": crashes}}


class MetricTests(unittest.TestCase):
    def test_boot_time_from_systemd(self):
        out = "Startup finished in 2.1s (kernel) + 9.034s (userspace) = 11.134s\ngraphical.target reached\n"
        self.assertEqual(report.boot_seconds(lambda argv, **k: subprocess.CompletedProcess(argv, 0, out, "")), 11.1)
        out = "Startup finished in 3.2s (kernel) + 1min 2.5s (userspace) = 1min 5.701s\n"
        self.assertEqual(report.boot_seconds(lambda argv, **k: subprocess.CompletedProcess(argv, 0, out, "")), 65.7)
        busy = "Bootup is not yet finished.\n"
        self.assertIsNone(report.boot_seconds(lambda argv, **k: subprocess.CompletedProcess(argv, 1, busy, "")))

    def test_crashes_this_week(self):
        out = "Mon 2026-10-12 10:00:00 IDT 1234 1000 1000 SIGSEGV present /usr/bin/x\n" * 3
        self.assertEqual(report.crashes_this_week(lambda argv, **k: subprocess.CompletedProcess(argv, 0, out, "")), 3)
        self.assertEqual(report.crashes_this_week(lambda argv, **k: subprocess.CompletedProcess(argv, 1, "", "")), 0)

        def missing(argv, **kwargs):
            raise FileNotFoundError(argv[0])
        self.assertIsNone(report.crashes_this_week(missing))


class WeekTests(unittest.TestCase):
    def test_a_good_week_in_plain_words(self):
        runs = [run(NOW - 10 * DAY, boot=14.0), run(NOW - 9 * DAY, boot=14.2),
                run(NOW - 3 * DAY, boot=12.0), run(NOW - DAY, boot=12.0)]
        week = report.week(runs, NOW)
        self.assertEqual((week.runs, week.failures, week.boot, week.boot_before), (2, {}, 12.0, 14.1))
        self.assertEqual(report.week_text(week, "en", cli.TITLES),
                         "This week everything worked. Starting is 2.1 seconds faster than last week.")
        self.assertEqual(report.week_text(week, "he", cli.TITLES),
                         "השבוע הכל עבד. האתחול מהיר ב־2.1 שניות מאשר בשבוע שעבר.")

    def test_a_week_with_problems(self):
        runs = [run(NOW - 2 * DAY, failed=("firewall",), crashes=4), run(NOW - DAY, failed=("firewall",), crashes=5)]
        said = report.week_text(report.week(runs, NOW), "en", cli.TITLES)
        self.assertIn("Not working 2 of 2 times: The firewall is on.", said)
        self.assertIn("crashed 5 times", said)
        self.assertEqual(report.week_text(report.week([], NOW), "en", cli.TITLES), "Raz did not check this week yet.")


class ImproveTests(unittest.TestCase):
    def test_plan_check_act(self):
        runs = [run(NOW - 5 * DAY, failed=("updates",)), run(NOW - 4 * DAY, failed=("updates",)),
                run(NOW - 3 * DAY, failed=("updates", "languages"))]
        items = report.improve(runs, [], NOW - 3 * DAY)
        self.assertEqual([(i.check, i.state, i.fix_kind, i.fix) for i in items],
                         [("updates", "open", "tune", "enable automatic updates")])
        self.assertIn("!enable automatic updates", report.items_text(items, "en", cli.TITLES))
        runs += [run(NOW - 2 * DAY), run(NOW - DAY), run(NOW - 0.5 * DAY)]
        items = report.improve(runs, items, NOW)
        self.assertEqual((items[0].state, items[0].passes), ("worked", 3))
        self.assertIn("✓ Worked", report.items_text(items, "en", cli.TITLES))
        self.assertEqual(len(report.improve(runs, items, NOW)), 1)  # never the same item twice

    def test_old_failures_do_not_count(self):
        runs = [run(NOW - 30 * DAY - i, failed=("updates",)) for i in range(5)]
        self.assertEqual(report.improve(runs, [], NOW), [])

    def test_items_are_kept_privately(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "raz"
            report.save_items(directory, [report.Item("firewall", NOW, 3, "heal", "")])
            self.assertEqual(oct((directory / "improve.json").stat().st_mode & 0o777), "0o600")
            self.assertEqual(report.load_items(directory)[0].check, "firewall")
            (directory / "improve.json").write_text("not json")
            self.assertEqual(report.load_items(directory), [])

    def test_every_suggested_sentence_is_real_tune(self):
        try:
            from dai_tune.parser import parse
        except ImportError:
            self.skipTest("dai_tune is not on the path")
        for check, (kind, sentence) in report.FIXES.items():
            if kind == "tune":
                self.assertTrue(parse(sentence).requests, f"{check}: Tune does not understand {sentence!r}")


class ProblemReportTests(unittest.TestCase):
    def test_a_user_called_dai_keeps_the_command_names(self):
        results = [{"id": "commands", "status": "failed", "detail": "1 command", "items": ["dai-raz: missing",
                                                                                          "run by dai at 10:00:00"]}]
        with mock.patch.dict(os.environ, {"USER": "dai", "LOGNAME": "dai"}), \
                mock.patch("socket.gethostname", return_value="debian"), \
                mock.patch("pathlib.Path.home", return_value=Path("/home/dai")):
            text = report.problem_report(results, "0.1.0", cli.TITLES)
        self.assertIn("dai-raz: missing", text)
        self.assertIn("run by <user> at 10:00:00", text)  # a time is not an IPv6 address

    def test_names_places_and_secrets_never_reach_the_report(self):
        results = [{"id": "files", "status": "failed", "detail": "2 changed",
                    "items": ["/home/dana/.config/x changed by dana@laptop-77 from 192.168.1.20",
                              "token ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ab", "write to fe80::1:2:3:4 failed",
                              "mail dana@example.org",
                              "/usr/share/polkit-1/actions/io.github.diamondrubinny.dai.tune.policy: missing"]},
                   {"id": "firewall", "status": "ok", "detail": "", "items": []}]
        with mock.patch.dict(os.environ, {"USER": "dana", "LOGNAME": "dana"}), \
                mock.patch("socket.gethostname", return_value="laptop-77"), \
                mock.patch("pathlib.Path.home", return_value=Path("/home/dana")):
            text = report.problem_report(results, "0.1.0", cli.TITLES)
        for secret in ("dana", "laptop-77", "192.168.1.20", "ghp_", "fe80::1", "example.org"):
            self.assertNotIn(secret, text)
        self.assertIn("~/.config/x", text)
        self.assertIn("/usr/share/polkit-1/actions/io.github.diamondrubinny.dai.tune.policy", text)  # kept
        self.assertIn("<ip>", text)
        self.assertIn("nothing was sent", text)
        self.assertIn("Protected settings are intact [files]", text)
        self.assertNotIn("[firewall]", text)  # only what failed


class CliTests(unittest.TestCase):
    def test_week_is_told_once_a_week(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"XDG_STATE_HOME": tmp}), \
                mock.patch("shutil.which", return_value=None):
            directory = cli.state_dir()
            directory.mkdir(parents=True)
            (directory / "run-1.json").write_text(json.dumps(run(__import__("time").time() - 100)))
            with mock.patch("builtins.print") as printed:
                self.assertEqual(cli.main(["dai-raz", "week", "--weekly"]), 0)
                self.assertEqual(printed.call_count, 1)
                self.assertEqual(cli.main(["dai-raz", "week", "--weekly"]), 0)
                self.assertEqual(printed.call_count, 1)  # told already this week
            self.assertEqual(oct((directory / "week-told").stat().st_mode & 0o777), "0o600")


if __name__ == "__main__":
    unittest.main()
