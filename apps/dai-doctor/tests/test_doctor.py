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

from dai_doctor import cli
from dai_doctor.clean import clean_user
from dai_doctor.diagnose import diagnose, topic_for
from dai_doctor.facts import Battery, Facts, Proc, battery, collect, meminfo, processes

GB = 2**30
MB = 2**20


def quiet(argv):
    return subprocess.CompletedProcess(list(argv), 0, "", "")


class FakeSystem(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "root"
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        (self.root / "proc").mkdir(parents=True)
        (self.root / "proc/meminfo").write_text(
            "MemTotal:       8000000 kB\nMemAvailable:    400000 kB\nSwapTotal: 2000000 kB\nSwapFree: 500000 kB\n")
        (self.root / "proc/loadavg").write_text("6.50 3.00 1.00 2/300 1234\n")
        (self.root / "proc/uptime").write_text(f"{20 * 86400}.0 0.0\n")
        self.process(4242, "firefox-esr", rss_pages=400_000)
        self.process(1, "systemd", rss_pages=1000)

    def tearDown(self):
        self.tmp.cleanup()

    def process(self, pid, name, rss_pages):
        folder = self.root / "proc" / str(pid)
        folder.mkdir()
        (folder / "comm").write_text(name + "\n")
        (folder / "statm").write_text(f"999999 {rss_pages} 0 0 0 0 0\n")
        (folder / "stat").write_text(f"{pid} ({name}) S 1 1 1 0 -1 0 0 0 0 0 100 50 0 0 20 0 1 0 0 0\n")


class FactTests(FakeSystem):
    def test_proc_parsing(self):
        mem = meminfo(self.root)
        self.assertEqual((mem["MemTotal"], mem["MemAvailable"]), (8000000 * 1024, 400000 * 1024))
        procs = {p.name: p for p in processes(self.root, sample=0)}
        self.assertEqual(procs["firefox-esr"].rss, 400_000 * os.sysconf("SC_PAGE_SIZE"))
        facts = collect(self.root, self.home, runner=quiet, sample=0, topics=("slow",))
        self.assertEqual((facts.load1, round(facts.uptime_days)), (6.5, 20))

    def test_battery(self):
        bat = self.root / "sys/class/power_supply/BAT0"
        bat.mkdir(parents=True)
        for name, value in {"capacity": "25", "status": "Discharging", "energy_full": "30000000",
                            "energy_full_design": "50000000"}.items():
            (bat / name).write_text(value + "\n")
        self.assertEqual(battery(self.root), Battery(25, 60, "Discharging"))
        self.assertIsNone(battery(self.home))


class DiagnoseTests(FakeSystem):
    def facts(self, **overrides):
        base = dict(cores=4, load1=0.5, mem_total=8 * GB, mem_available=4 * GB, swap_total=0, swap_free=0,
                    uptime_days=1, processes=[], disks={"/": (100 * GB, 50 * GB)}, folders=[], caches={})
        base.update(overrides)
        return Facts(**base)

    def keys(self, findings, level=None):
        return [f.key for f in findings if level is None or f.level == level]

    def test_healthy_computer(self):
        findings = diagnose(self.facts(), ("slow", "disk", "battery"))
        self.assertEqual(self.keys(findings, "bad") + self.keys(findings, "warn"), [])

    def test_slow_reasons_are_explained(self):
        facts = self.facts(mem_available=int(0.5 * GB), swap_total=2 * GB, swap_free=int(0.5 * GB), load1=7,
                           uptime_days=20, failed_units=["cups.service"],
                           processes=[Proc(10, "firefox-esr", 180.0, 3 * GB), Proc(11, "labwc", 90.0, 1 * GB)])
        findings = diagnose(facts, ("slow",))
        self.assertEqual(findings[0].level, "bad")
        self.assertTrue({"memory", "cpu", "swap", "services", "uptime"} <= set(self.keys(findings)))
        memory = next(f for f in findings if f.key == "memory")
        self.assertIn("firefox-esr", memory.detail)
        cpu = next(f for f in findings if f.key == "cpu")
        self.assertNotIn("labwc", cpu.detail)  # the desktop itself is never blamed

    def test_disk_findings_and_fixes(self):
        facts = self.facts(disks={"/": (100 * GB, int(1.5 * GB))},
                           caches={"apt": 600 * MB, "journal": 900 * MB, "trash": 300 * MB, "thumbnails": 20 * MB},
                           folders=[("Videos", 40 * GB), ("Downloads", 9 * GB)])
        findings = diagnose(facts, ("disk",))
        self.assertEqual(findings[0].level, "bad")
        fixes = {fix.kind: fix.payload for f in findings for fix in f.fixes}
        self.assertEqual(fixes, {"tune": "free up disk space", "clean": "user"})
        self.assertIn("Videos", next(f for f in findings if f.key == "folders").detail)
        # A large disk with 11% free is fine.
        self.assertEqual(diagnose(self.facts(disks={"/": (252 * GB, 29 * GB)}), ("disk",))[0].level, "ok")

    def test_tune_sentences_are_understood_by_tune(self):
        try:
            from dai_tune.parser import parse
        except ImportError:
            self.skipTest("dai_tune not on the path")
        for sentence in ("free up disk space", "battery saver mode"):
            result = parse(sentence)
            self.assertTrue(result.requests and not result.unknown, sentence)

    def test_battery_advice(self):
        facts = self.facts(battery=Battery(20, 55, "Discharging"), power_profile="balanced")
        findings = diagnose(facts, ("battery",), "he")
        self.assertEqual(self.keys(findings), ["battery-health", "battery-low"])
        self.assertIn("שחוקה", findings[0].title)
        self.assertEqual(findings[1].fixes[0].payload, "battery saver mode")
        self.assertEqual(diagnose(self.facts(battery=None), ("battery",)), [])

    def test_questions(self):
        for text, topic in [("why is my computer slow", "slow"), ("למה המחשב איטי?", "slow"),
                            ("מה תופס את הדיסק", "disk"), ("what's taking my disk space", "disk"),
                            ("כמה סוללה נשארה?", "battery"), ("slow motion.mp4", None), ("firefox", None)]:
            self.assertEqual(topic_for(text), topic, text)


class CleanTests(FakeSystem):
    def test_only_trash_and_previews_and_no_symlink_following(self):
        trash = self.home / ".local/share/Trash/files"
        trash.mkdir(parents=True)
        (trash / "old.iso").write_bytes(b"x" * 100_000)
        (trash / "folder").mkdir()
        (trash / "folder" / "a.txt").write_text("a")
        precious = self.home / "Documents"
        precious.mkdir()
        (precious / "thesis.odt").write_text("keep me")
        (trash / "link-to-documents").symlink_to(precious)
        thumbs = self.home / ".cache/thumbnails/large"
        thumbs.mkdir(parents=True)
        (thumbs / "t.png").write_bytes(b"x" * 5000)
        freed = clean_user(self.home)
        self.assertGreater(freed, 100_000)
        self.assertEqual(list(trash.iterdir()), [])
        self.assertEqual(list((self.home / ".cache/thumbnails").iterdir()), [])
        self.assertEqual((precious / "thesis.odt").read_text(), "keep me")

    def test_symlinked_trash_folder_is_left_alone(self):
        elsewhere = self.home / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "keep.txt").write_text("x")
        (self.home / ".local/share/Trash").mkdir(parents=True)
        (self.home / ".local/share/Trash/files").symlink_to(elsewhere)
        clean_user(self.home)
        self.assertTrue((elsewhere / "keep.txt").exists())


class CliTests(FakeSystem):
    def test_json_and_text(self):
        fake = Facts(cores=2, load1=0.1, mem_total=8 * GB, mem_available=6 * GB, disks={"/": (100 * GB, 60 * GB)})
        with mock.patch.object(cli, "collect", return_value=fake), mock.patch.dict(os.environ, {"LANG": "en_US.UTF-8"}):
            out = io.StringIO()
            with redirect_stdout(out), mock.patch("sys.stderr", io.StringIO()):
                self.assertEqual(cli.main(["dai-doctor", "--json", "slow"]), 0)
            self.assertEqual({f["key"] for f in json.loads(out.getvalue())}, {"memory", "cpu"})
            out = io.StringIO()
            with redirect_stdout(out), mock.patch("sys.stderr", io.StringIO()):
                cli.main(["dai-doctor"])
            self.assertIn("Everything looks fine", out.getvalue())


class CommandTests(unittest.TestCase):
    def test_command_bar_rows(self):
        try:
            from dai_command import core
        except ImportError:
            self.skipTest("dai_command not on the path")
        facts = Facts(cores=2, load1=5, mem_total=8 * GB, mem_available=int(0.3 * GB),
                      processes=[Proc(5, "chromium", 150.0, 4 * GB)], disks={"/": (100 * GB, 60 * GB)})
        core._DOCTOR_CACHE.clear()
        with mock.patch("dai_doctor.facts.collect", return_value=facts) as collect_mock, \
                mock.patch.dict(os.environ, {"LANG": "en_US.UTF-8"}):
            rows = core.doctor_actions("why is my computer so slow")
            self.assertEqual(rows[0].kind, "doctor")
            self.assertEqual(rows[0].payload, "slow")
            self.assertIn("Memory is almost full", [r.title for r in rows])
            core.doctor_actions("why is my computer so slow?")  # cached while typing
            self.assertEqual(collect_mock.call_count, 1)
            self.assertIsNone(core.doctor_actions("slow motion.mp4"))
        core._DOCTOR_CACHE.clear()


if __name__ == "__main__":
    unittest.main()
