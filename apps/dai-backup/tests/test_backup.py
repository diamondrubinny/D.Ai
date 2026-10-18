# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
import io
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from dai_backup import cli, config
from dai_backup.config import Settings, key_path, load, new_key
from dai_backup.engine import BackupError, Restic

HAVE_RESTIC = shutil.which("restic") is not None


class BackupTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.home, self.drive = base / "home", base / "drive"
        (self.home / "Documents").mkdir(parents=True)
        (self.home / "Documents" / "report.odt").write_text("version 1")
        (self.home / "Pictures").mkdir()
        (self.home / "Pictures" / "beach.jpg").write_bytes(os.urandom(2048))
        (self.home / "Documents" / "node_modules").mkdir()
        (self.home / "Documents" / "node_modules" / "junk.js").write_text("x")
        self.drive.mkdir()
        self.patches = [mock.patch.object(Path, "home", return_value=self.home),
                        mock.patch.dict(os.environ, {"LANG": "en_US.UTF-8", "XDG_CONFIG_HOME": ""}),
                        mock.patch.object(cli, "systemctl", return_value=0),
                        mock.patch.object(cli, "notify")]
        for patch in self.patches:
            patch.start()
        os.environ.pop("XDG_CONFIG_HOME", None)

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.tmp.cleanup()

    def cli(self, *args, runner=None):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["dai-backup", *args], restic_runner=runner)
        return code, out.getvalue() + err.getvalue()


class KeyAndSettingsTests(BackupTestCase):
    def test_key_and_settings_are_private(self):
        key = new_key(self.home)
        self.assertRegex(key, r"^([0-9A-F]{4}-){7}[0-9A-F]{4}$")
        self.assertEqual(oct(key_path(self.home).stat().st_mode & 0o777), "0o600")
        config.save(Settings(repo="/x", folders=["Documents"]), self.home)
        self.assertEqual(oct(config.settings_path(self.home).stat().st_mode & 0o777), "0o600")
        self.assertEqual(oct(config.config_dir(self.home).stat().st_mode & 0o777), "0o700")

    def test_password_never_on_the_command_line(self):
        calls = []

        def runner(argv):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, "", "")

        key = new_key(self.home)
        Restic(Settings(repo=str(self.drive / "r"), folders=["Documents"]), self.home, runner).backup()
        flat = " ".join(calls[0])
        self.assertNotIn(key, flat)
        self.assertIn("--password-file", calls[0])
        self.assertIn("--exclude-caches", calls[0])

    def test_errors_are_reported(self):
        failing = lambda argv: subprocess.CompletedProcess(argv, 1, "", "Fatal: wrong password or no key found")
        with self.assertRaisesRegex(BackupError, "wrong password"):
            Restic(Settings(repo="/r", folders=["Documents"]), self.home, failing).backup()


class SetupTests(BackupTestCase):
    def test_refuses_bad_targets_and_existing_backups(self):
        code, out = self.cli("setup", str(self.drive / "missing"))
        self.assertEqual(code, 2)
        (self.drive / "D.Ai-Backup").mkdir()
        (self.drive / "D.Ai-Backup" / "someone-else").write_text("x")
        code, out = self.cli("setup", str(self.drive), runner=lambda a: subprocess.CompletedProcess(a, 0, "", ""))
        self.assertEqual(code, 1)
        self.assertIn("not overwritten", out)
        self.assertFalse(key_path(self.home).exists())

    def test_failed_init_leaves_nothing_behind(self):
        code, _ = self.cli("setup", str(self.drive), runner=lambda a: subprocess.CompletedProcess(a, 1, "", "boom"))
        self.assertEqual(code, 1)
        self.assertIsNone(load(self.home))
        self.assertFalse(key_path(self.home).exists())

    def test_not_set_up(self):
        self.assertEqual(self.cli("now")[0], 1)

    def test_auto_without_the_drive_reminds_once_a_day(self):
        config.save(Settings(repo=str(self.drive / "gone"), folders=["Documents"], last_backup=time.time() - 8 * 86400),
                    self.home)
        self.assertEqual(self.cli("auto")[0], 0)
        self.assertEqual(self.cli("auto")[0], 0)
        self.assertEqual(cli.notify.call_count, 1)


@unittest.skipUnless(HAVE_RESTIC, "restic is not installed")
class RealResticTests(BackupTestCase):
    """The whole cycle against the real restic binary."""

    def test_setup_backup_change_restore_check(self):
        code, out = self.cli("setup", str(self.drive), "--folders", "Documents,Pictures")
        self.assertEqual(code, 0, out)
        key = key_path(self.home).read_text().strip()
        self.assertIn(key, out)  # shown once, to write down
        self.assertTrue((self.drive / "D.Ai-Backup" / "config").is_file())
        self.assertNotIn(b"version 1", b"".join(p.read_bytes() for p in (self.drive / "D.Ai-Backup").rglob("*")
                                                if p.is_file()))  # encrypted on the drive

        self.assertEqual(self.cli("now")[0], 0)
        (self.home / "Documents" / "report.odt").write_text("version 2 — broken")
        code, out = self.cli("now")
        self.assertEqual(code, 0, out)
        self.assertIn("1 changed", out)

        code, out = self.cli("list")
        snapshots = [line.split()[0] for line in out.splitlines() if line.strip()]
        self.assertEqual(len(snapshots), 2)
        code, out = self.cli("restore", str(self.home / "Documents" / "report.odt"), "--from", snapshots[0])
        self.assertEqual(code, 0, out)
        restored = list((self.home / "Restored").rglob("report.odt"))
        self.assertEqual([p.read_text() for p in restored], ["version 1"])
        self.assertEqual((self.home / "Documents" / "report.odt").read_text(), "version 2 — broken")  # untouched
        self.assertFalse(list((self.home / "Restored").rglob("junk.js")))  # node_modules excluded

        code, out = self.cli("check")
        self.assertEqual(code, 0, out)
        status = json.loads(self.cli("status", "--json")[1])
        self.assertEqual((status["drive_connected"], status["copies"]), (True, 2))

        key_path(self.home).write_text("0000-0000-0000-0000-0000-0000-0000-0000\n")
        self.assertEqual(self.cli("now")[0], 1)  # a wrong key cannot read or write the backup


class CommandTests(BackupTestCase):
    def test_command_bar(self):
        try:
            from dai_command import core
        except ImportError:
            self.skipTest("dai_command not on the path")
        rows = core.backup_actions("גבה את הקבצים שלי")
        self.assertEqual((rows[0].kind, rows[0].payload), ("backup", "setup"))
        config.save(Settings(repo=str(self.drive / "D.Ai-Backup"), folders=["Documents"], last_backup=time.time()),
                    self.home)
        rows = core.backup_actions("when was my last backup?")
        self.assertEqual([r.payload for r in rows], ["now", "status"])
        self.assertIsNone(core.backup_actions("backpack"))


if __name__ == "__main__":
    unittest.main()
