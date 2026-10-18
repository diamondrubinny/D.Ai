# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
import json
import os
import stat
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import dai_status


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.file = Path(self.tmp.name) / "dai" / "status.json"

    def test_private_file_in_a_private_folder(self):
        self.assertTrue(dai_status.update("heal", 2))
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.file.parent.stat().st_mode), 0o700)
        self.assertEqual(json.loads(self.file.read_text()), {"heal": 2})

    def test_sections_are_merged_and_unchanged_values_not_rewritten(self):
        dai_status.update("heal", 1)
        dai_status.update("ideas", 3)
        self.assertEqual(dai_status.read(), {"heal": 1, "ideas": 3})
        before = self.file.stat().st_mtime_ns
        self.assertFalse(dai_status.update("ideas", 3))
        self.assertEqual(self.file.stat().st_mtime_ns, before)

    def test_values_are_cleaned(self):
        dai_status.update("heal", 10_000)
        dai_status.update("ideas", -4)
        dai_status.update("privacy", ["Zoom", "Zoom", "a‮b\x07", "", "x" * 90, "B", "C"])
        data = dai_status.read()
        self.assertEqual((data["heal"], data["ideas"]), (99, 0))
        self.assertEqual(data["privacy"], ["B", "C", "Zoom"])  # unique, sorted, at most three
        dai_status.update("privacy", ["a‮b\x07"])
        self.assertEqual(dai_status.read()["privacy"], ["ab"])

    def test_unknown_sections_and_bad_values_are_refused_quietly(self):
        self.assertFalse(dai_status.update("shell", "rm -rf /"))
        self.assertFalse(dai_status.update("heal", "many"))
        self.assertFalse(dai_status.update("privacy", 5))
        self.assertEqual(dai_status.read(), {})

    def test_no_runtime_directory_is_not_an_error(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(dai_status.update("heal", 1))
            self.assertEqual(dai_status.read(), {})

    def test_a_broken_file_is_replaced(self):
        self.file.parent.mkdir(mode=0o700)
        self.file.write_text("{not json")
        self.assertEqual(dai_status.read(), {})
        self.assertTrue(dai_status.update("ideas", 1))
        self.assertEqual(dai_status.read(), {"ideas": 1})

    def test_concurrent_writers_keep_every_section(self):
        def write(section, value):
            for _ in range(30):
                dai_status.update(section, value)
        threads = [threading.Thread(target=write, args=args)
                   for args in (("heal", 4), ("ideas", 2), ("privacy", ["Zoom"]))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(dai_status.read(), {"heal": 4, "ideas": 2, "privacy": ["Zoom"]})


class WriterTests(unittest.TestCase):
    """Heal, Privacy and Evolve mirror their state (each only when installed together)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.tmp.name,
                                               "XDG_STATE_HOME": f"{self.tmp.name}/state",
                                               "XDG_CONFIG_HOME": f"{self.tmp.name}/config"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_heal_counts_current_problems(self):
        try:
            from dai_heal import problems as P
            from dai_heal.watch import Watcher
        except ImportError:
            self.skipTest("dai_heal is not on PYTHONPATH")
        found = [P.Problem("service", "a.service", 100.0), P.Problem("user-service", "b.service", 100.0)]
        watcher = Watcher(collect=lambda since=0: found, announce=lambda p, lang: None, clock=lambda: 1000.0,
                          directory=Path(self.tmp.name) / "heal")
        watcher.check()
        self.assertEqual(dai_status.read()["heal"], 2)
        found.clear()
        watcher.check()
        self.assertEqual(dai_status.read()["heal"], 0)

    def test_evolve_counts_ideas_and_clears_them_when_off(self):
        try:
            from dai_evolve import cli, scan, store
        except ImportError:
            self.skipTest("dai_evolve is not on PYTHONPATH")
        for _ in range(2):
            store.record_wish("play retro games", clock=lambda: 1_800_000_000.0)
        found = scan.scan(home=Path(self.tmp.name), now=1_800_000_000.0, doctor=list, heal=list, model_ready=False, recipes=set())
        self.assertEqual(dai_status.read()["ideas"], len(found))
        scan.dismiss(found[0].key)
        self.assertEqual(dai_status.read()["ideas"], 0)
        with mock.patch("sys.stdout"):
            cli.main(["dai-evolve", "off"])
        self.assertEqual(dai_status.read()["ideas"], 0)


if __name__ == "__main__":
    unittest.main()
