# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""MOM's guard (docs/MOM.md §12): notices an app that runs away, tells once, never closes it."""
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from dai_mom import background as bg, guard
from dai_mom.apps import App
from dai_mom.procs import Process


def app(key="game", name="Game", cpu=0.0, memory=200 * 2**20, protected=False):
    proc = Process(pid=10, ppid=1, uid=1000, name=key, cmdline=[key], exe="", start=1, ticks=0, memory=memory,
                   cpu=cpu)
    return App(key, name, processes=[proc], protected=protected)


class CpuTests(unittest.TestCase):
    def test_two_minutes_of_a_whole_core_tells_once(self):
        g = guard.Guard("en", cores=4)
        busy = app(cpu=25.0)  # 25% of 4 cores = one whole core
        names, alerts = g.observe([busy], 0)
        self.assertEqual((names, alerts), ([], []))
        names, alerts = g.observe([busy], 119)
        self.assertEqual(alerts, [])
        names, alerts = g.observe([busy], 121)
        self.assertEqual(names, ["Game"])
        self.assertEqual([(a.key, a.reason) for a in alerts], [("game", "cpu")])
        self.assertIn("2 minutes", alerts[0].detail)
        names, alerts = g.observe([busy], 200)
        self.assertEqual((names, alerts), (["Game"], []))  # still shown, never told twice

    def test_calming_down_clears_and_a_new_run_tells_again(self):
        g = guard.Guard("en", cores=1)
        g.observe([app(cpu=100.0)], 0)
        self.assertEqual(len(g.observe([app(cpu=100.0)], 130)[1]), 1)
        self.assertEqual(g.observe([app(cpu=5.0)], 145), ([], []))
        g.observe([app(cpu=100.0)], 160)
        self.assertEqual(len(g.observe([app(cpu=100.0)], 290)[1]), 1)

    def test_short_bursts_and_half_a_core_are_normal(self):
        g = guard.Guard("en", cores=2)
        for second in range(0, 600, 15):
            busy = 50.0 if (second // 60) % 2 == 0 else 0.0  # a minute on, a minute off
            self.assertEqual(g.observe([app(cpu=busy)], second), ([], []))
        g = guard.Guard("en", cores=2)
        for second in range(0, 600, 15):
            self.assertEqual(g.observe([app(cpu=40.0)], second)[1], [])  # 0.8 of a core

    def test_mom_itself_is_never_reported(self):
        g = guard.Guard("en", cores=1)
        g.observe([app("dai-mom", "MOM", cpu=100.0)], 0)
        self.assertEqual(g.observe([app("dai-mom", "MOM", cpu=100.0)], 300), ([], []))


class MemoryTests(unittest.TestCase):
    def test_growing_for_ten_minutes_tells_once(self):
        g = guard.Guard("en", cores=1)
        start = 600 * 2**20
        alerts = []
        for step in range(0, 41):
            names, found = g.observe([app(memory=start + step * 20 * 2**20)], step * 15)
            alerts += found
        self.assertEqual([a.reason for a in alerts], ["memory"])
        self.assertIn("800 MB", alerts[0].detail)
        self.assertEqual(names, ["Game"])

    def test_memory_given_back_is_not_a_leak(self):
        g = guard.Guard("en", cores=1)
        for step in range(0, 41):
            memory = (600 + step * 20) * 2**20 if step % 10 else 600 * 2**20  # drops back every 150 s
            self.assertEqual(g.observe([app(memory=memory)], step * 15)[1], [])

    def test_small_apps_growing_a_little_are_fine(self):
        g = guard.Guard("en", cores=1)
        for step in range(0, 80):
            self.assertEqual(g.observe([app(memory=(50 + step) * 2**20)], step * 15)[1], [])  # +80 MB


class ReportTests(unittest.TestCase):
    def test_the_notification_is_quiet_and_never_closes_anything(self):
        calls = []
        alert = guard.Alert("game", "Game", "cpu", "Game has kept a whole processor core busy for 2 minutes.")
        with mock.patch("shutil.which", return_value="/usr/bin/notify-send"):
            guard.notify(alert, "he", run=lambda argv, **kw: calls.append(argv))
        self.assertEqual(calls[0][:6], ["notify-send", "-a", "D.Ai", "-i", "dai-mom", "-u"])
        self.assertIn("low", calls[0])
        self.assertIn("Ctrl+Shift+Esc", calls[0][-1])
        self.assertIn("שום דבר לא נסגר", calls[0][-1])

    def test_the_diamond_shows_names_only(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": tmp}):
            import dai_status

            guard.mirror(["Game‮", "Firefox"])
            self.assertEqual(dai_status.read()["busy"], ["Firefox", "Game"])
            guard.mirror([])
            self.assertEqual(dai_status.read()["busy"], [])

    def test_a_round_reads_proc_and_writes_the_status(self):
        seen = []
        with mock.patch.object(guard, "mirror", seen.append), mock.patch("os.nice"):
            guard.run_forever("en", sleep=lambda s: None, rounds=2)
        self.assertEqual(seen[-1], [])  # stopping clears the diamond
        self.assertEqual(len(seen), 3)


class BootCostTests(unittest.TestCase):
    def test_login_apps_measured_by_systemd(self):
        out = ("  3.214s app-dai\\x2dclip@autostart.service\n"
               "   412ms app-nm\\x2dapplet@autostart.service\n"
               "1min 2.500s app-slow@autostart.service\n"
               "   120ms pipewire.service\n")

        def runner(argv):
            self.assertEqual(argv[:3], ["systemd-analyze", "--user", "blame"])
            return subprocess.CompletedProcess(argv, 0, out, "")
        self.assertEqual(bg.boot_costs(runner), {"dai-clip.desktop": 3.2, "nm-applet.desktop": 0.4,
                                                 "slow.desktop": 62.5})

    def test_nothing_is_guessed_when_it_cannot_be_measured(self):
        self.assertEqual(bg.boot_costs(lambda argv: subprocess.CompletedProcess(argv, 1, "", "no bus")), {})

        def missing(argv):
            raise FileNotFoundError("systemd-analyze")
        self.assertEqual(bg.boot_costs(missing), {})


if __name__ == "__main__":
    unittest.main()
