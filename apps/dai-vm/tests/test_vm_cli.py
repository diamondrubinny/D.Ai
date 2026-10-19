# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-vm on the command line: check, create, the lifecycle verbs, drivers, iso, and the exit codes."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dai_vm import cli, drivers, hardware

from . import fakes


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.root = fakes.fake_root(self.home / "root")
        self.run = fakes.FakeRun()
        self.virsh = fakes.virsh_with(self.run)
        self.spawned = []
        self.iso = fakes.fake_iso(self.home / "win.iso")
        patches = [mock.patch.dict(os.environ, {"LANG": "en_US.UTF-8", "LC_ALL": "", "LANGUAGE": "", "DAI_LANG": "en"}),
                   mock.patch.object(hardware, "check", lambda lang, root=None, home=None, **k: fakes.check(
                       lang, root=self.root, home=self.home))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["dai-vm", *args], home=self.home, virsh=self.virsh, run=self.run, spawn=self.spawned.append)
        return code, out.getvalue(), err.getvalue()

    def test_version_help_check(self):
        self.assertIn("dai-vm 0.1.0 — Diamond Rubinny (d.Ai)", self.cli("--version")[1])
        self.assertIn("never downloads Windows", self.cli("--help")[1])
        code, out, _ = self.cli("check")
        self.assertEqual(code, 0)
        self.assertIn("✓", out)
        self.assertIn("A machine can run here.", out)

    def test_create_and_lifecycle(self):
        code, out, err = self.cli("create", "win11", "--iso", str(self.iso), "--memory", "4096", "--cpus", "2", "--disk", "64")
        self.assertEqual((code, "win11 is ready" in out), (0, True), err)
        self.assertIn("drivers are not downloaded", err)
        self.assertEqual(self.virsh.state("win11"), "shut off")
        code, out, _ = self.cli("list")
        self.assertIn("win11\tshut off\t4096 MB · 2 CPU · 64 GB · Windows 11", out)
        self.assertEqual(self.cli("start", "win11")[0], 0)
        self.assertEqual(self.virsh.state("win11"), "running")
        self.assertEqual(self.cli("show", "win11")[0], 0)
        self.assertEqual(self.spawned[-1][:2], ["remote-viewer", "--title"])
        self.assertEqual(self.cli("pause", "win11")[0], 0)
        self.assertEqual(self.virsh.state("win11"), "paused")
        self.assertEqual(self.cli("resume", "win11")[0], 0)
        self.assertEqual(self.cli("stop", "win11")[0], 0)
        self.assertEqual(self.virsh.state("win11"), "shut off")
        code, _, err = self.cli("delete", "win11")
        self.assertEqual((code, "Add --yes" in err), (1, True))
        self.assertEqual(self.cli("delete", "win11", "--yes")[0], 0)
        self.assertEqual(self.virsh.state("win11"), "missing")
        self.assertEqual(self.cli("list")[1].strip(), "No machines yet. dai-vm create NAME --iso FILE")
        code, _, err = self.cli("start", "win11")
        self.assertEqual((code, "No machine called win11" in err), (2, True))

    def test_create_refuses_on_a_weak_computer_and_bad_media(self):
        fakes.fake_root(self.root, flags="fpu")
        code, _, err = self.cli("create", "win11", "--iso", str(self.iso))
        self.assertEqual((code, "VT-x or AMD-V" in err), (1, True))
        fakes.fake_root(self.root)
        code, _, err = self.cli("create", "win11", "--iso", str(self.home / "none.iso"))
        self.assertEqual((code, "could not be used" in err), (2, True))
        code, _, err = self.cli("create", "bad name", "--iso", str(self.iso))
        self.assertEqual((code, "Not created" in err), (1, True))

    def test_drivers_and_iso(self):
        code, out, _ = self.cli("drivers")
        self.assertEqual((code, "not downloaded" in out), (1, True))
        entry = drivers.catalog()["virtio-win"]
        path = drivers.iso_path(entry, self.home)
        path.parent.mkdir(parents=True)
        with open(path, "wb") as handle:
            handle.truncate(entry.size)
        path.with_suffix(".iso.sha256").write_text(entry.sha256 + "\n")
        code, out, _ = self.cli("drivers")
        self.assertEqual((code, "are present" in out), (0, True))
        code, out, err = self.cli("create", "win11", "--iso", str(self.iso))
        self.assertEqual(code, 0, err)
        self.assertNotIn("not downloaded", err)
        code, out, _ = self.cli("iso", str(self.iso))
        self.assertEqual(code, 0)
        self.assertIn("Label: CCCOMA_X64FRE_EN-US_DV9", out)
        self.assertIn("SHA-256: ", out)
        self.assertEqual(self.cli("iso", str(self.home / "none.iso"))[0], 2)
        self.assertEqual(self.cli("bogus")[0], 2)


if __name__ == "__main__":
    unittest.main()
