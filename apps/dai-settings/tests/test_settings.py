# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""D.Ai Settings (docs/BEYOND.md §6): the readers, the requests they make, and the window."""
import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from dai_tune.context import Context
from dai_tune.planner import build_plan

from dai_settings import cli, model


class FakeSystem:
    """systemctl, powerprofilesctl and timedatectl answers, remembered."""

    def __init__(self):
        self.ssh, self.profile, self.calls = "enabled", "balanced", []

    def run(self, argv):
        self.calls.append(list(argv))
        out = ""
        if argv[:2] == ["systemctl", "is-enabled"]:
            out = self.ssh + "\n"
        elif argv == ["powerprofilesctl", "get"]:
            out = self.profile + "\n"
        return subprocess.CompletedProcess(argv, 0, out, "")


class SettingsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root, self.home = base / "root", base / "home"
        self.system = FakeSystem()
        self.ctx = Context(root=self.root, home=self.home, runner=self.system.run, spawner=lambda argv: None, lang="en")
        for path in ("usr/sbin/sshd", "usr/bin/clamscan", "usr/bin/snapper", "usr/bin/powerprofilesctl",
                     "usr/share/zoneinfo/Asia/Jerusalem", "usr/share/zoneinfo/Europe/Berlin"):
            (self.root / path).parent.mkdir(parents=True, exist_ok=True)
            (self.root / path).write_text("")
        (self.root / "etc").mkdir(parents=True, exist_ok=True)
        (self.root / "etc/hostname").write_text("dai-os\n")
        (self.root / "etc/localtime").symlink_to(self.root / "usr/share/zoneinfo/Asia/Jerusalem")
        (self.home / ".config/dai").mkdir(parents=True)
        (self.home / ".config/dai/theme").write_text("day\n")
        (self.home / ".config/dai/session.env").write_text("DAI_LOCK_TIMEOUT_SECONDS=300\n")
        (self.home / ".config/labwc").mkdir(parents=True)
        (self.home / ".config/labwc/environment").write_text("DAI_LAYOUTS=us,il,ru\nXKB_DEFAULT_LAYOUT=us\n")


class ModelTests(SettingsTestCase):
    def test_reads_what_the_system_says(self):
        values = model.snapshot(self.ctx)
        self.assertEqual(values["lock"], "5")
        self.assertTrue(values["updates"])          # untouched: Debian's default is on
        self.assertFalse(values["usb"])
        self.assertTrue(values["ssh"])
        self.assertEqual(values["antivirus"], "off")
        self.assertFalse(values["snapshots"])
        self.assertEqual(values["theme"], "day")
        self.assertEqual(values["touch"], "auto")
        self.assertEqual(values["sounds"], "on")
        self.assertEqual(values["language"], "en")
        self.assertEqual(values["layouts"], "us,il,ru")
        self.assertEqual(values["hostname"], "dai-os")
        self.assertEqual(values["power"], "balanced")
        self.assertEqual(values["clean"], "")

    def test_reads_follow_the_files_tune_writes(self):
        (self.root / "etc/modprobe.d").mkdir()
        (self.root / "etc/modprobe.d/dai-tune-usb_storage.conf").write_text("blacklist usb_storage\n")
        (self.root / "etc/apt/apt.conf.d").mkdir(parents=True)
        (self.root / "etc/apt/apt.conf.d/20auto-upgrades").write_text('APT::Periodic::Unattended-Upgrade "0";\n')
        (self.root / "etc/systemd/system").mkdir(parents=True)
        (self.root / "etc/systemd/system/dai-av-scan.timer").write_text("[Timer]\nOnCalendar=weekly\n")
        (self.root / "etc/snapper/configs").mkdir(parents=True)
        (self.root / "etc/snapper/configs/root").write_text("")
        (self.home / ".config/dai/language.env").write_text("LANG=he_IL.UTF-8\nLANGUAGE=he:en\n")
        self.system.ssh, self.system.profile = "disabled", "power-saver"
        values = model.snapshot(self.ctx)
        self.assertTrue(values["usb"])
        self.assertFalse(values["updates"])
        self.assertEqual(values["antivirus"], "weekly")
        self.assertTrue(values["snapshots"])
        self.assertEqual(values["language"], "he")
        self.assertFalse(values["ssh"])
        self.assertEqual(values["power"], "power-saver")

    def test_what_is_not_on_this_computer_reads_as_none(self):
        for path in ("usr/sbin/sshd", "usr/bin/clamscan", "usr/bin/snapper", "usr/bin/powerprofilesctl"):
            (self.root / path).unlink()
        values = model.snapshot(self.ctx)
        for key in ("ssh", "antivirus", "snapshots", "power"):
            self.assertIsNone(values[key], key)
        self.assertEqual(values["theme"], "day")

    def test_every_request_is_a_valid_plan(self):
        """Each control's value becomes a plan the planner accepts, with the right scope."""
        samples = {"lock": "10", "updates": False, "usb": True, "camera": False, "ssh": True, "antivirus": "daily",
                   "snapshots": True, "theme": "contrast", "touch": "on", "sounds": "quiet", "language": "ar",
                   "layouts": "us, il", "timezone": "Europe/Berlin", "hostname": "office-pc", "power": "performance",
                   "clean": True, "saver": True}
        for setting in model.SETTINGS:
            with self.subTest(setting.key):
                plan = build_plan(setting.request(samples[setting.key]), self.ctx)
                self.assertTrue(plan.ok, (setting.key, plan.errors, plan.unknown))
                self.assertEqual(plan.steps[0].scope, setting.scope())
        self.assertEqual(model.by_key("updates").request(False)[0].params, {"enabled": False})
        self.assertEqual(model.by_key("antivirus").request("off")[0].params, {"enabled": False})
        self.assertEqual(model.by_key("layouts").request("us, il")[0].params, {"layouts": ["us", "il"]})
        self.assertEqual(model.by_key("usb").request(False)[0].action, "device.allow")
        self.assertEqual(model.by_key("snapshots").request(False), [])  # only "on" exists

    def test_weakening_changes_say_so(self):
        plan = build_plan(model.by_key("updates").request(False), self.ctx)
        self.assertTrue(plan.weakens)
        plan = build_plan(model.by_key("lock").request("0"), self.ctx)
        self.assertTrue(plan.weakens)

    def test_search(self):
        self.assertTrue(model.matches(model.by_key("lock"), "LOCK", "en"))
        self.assertTrue(model.matches(model.by_key("lock"), "נעיל", "he"))
        self.assertTrue(model.matches(model.by_key("theme"), "contrast", "en"))
        self.assertFalse(model.matches(model.by_key("theme"), "camera", "en"))
        self.assertTrue(model.matches(model.by_key("theme"), "", "en"))

    def test_cli_list(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cli.main(["dai-settings", "list"], self.ctx), 0)
        text = out.getvalue()
        self.assertIn("Lock the screen: after 5 minutes", text)
        self.assertIn("Theme: light (D.Ai Day)", text)
        self.assertIn("Computer name: dai-os", text)
        out = io.StringIO()
        with redirect_stdout(out):
            cli.main(["dai-settings", "list", "--json"], self.ctx)
        self.assertEqual(json.loads(out.getvalue())["layouts"], "us,il,ru")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["dai-settings", "--version"], self.ctx), 0)
            self.assertEqual(cli.main(["dai-settings", "dance"], self.ctx), 2)


class WindowTests(SettingsTestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PyQt6.QtWidgets import QApplication
        except ImportError:
            raise unittest.SkipTest("PyQt6 is missing")
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        from dai_settings import gui
        self.gui = gui
        self.window = gui.SettingsWindow("en", self.ctx, admin=True)
        self.addCleanup(self.window.deleteLater)

    def test_every_control_is_accessible(self):
        from dai_raz.a11y import assert_accessible
        self.qt.setStyleSheet(self.gui.STYLE)
        self.addCleanup(self.qt.setStyleSheet, "")
        assert_accessible(self, self.window, touch=True)

    def test_rows_show_the_system_and_search_filters(self):
        self.assertIn("lock", self.window.controls)
        self.assertEqual(self.window.controls["lock"].currentData(), "5")
        self.assertEqual(self.window.controls["theme"].currentData(), "day")
        self.assertTrue(self.window.controls["ssh"].isChecked())
        self.window.search.setText("theme")
        self.assertTrue(self.window.rows["theme"].isVisibleTo(self.window))
        self.assertFalse(self.window.rows["lock"].isVisibleTo(self.window))
        self.window.search.setText("zzz")
        self.assertTrue(self.window.empty.isVisibleTo(self.window))

    def test_a_change_shows_the_plan_then_applies_through_tune(self):
        from dai_tune.cli import ApplyResult
        applied = []

        def fake_apply(plan, ctx, label):
            applied.append((plan, label))
            return ApplyResult(True, entry_id="abc123")

        with mock.patch.object(self.gui, "apply_plan", fake_apply):
            self.window.change(model.by_key("theme"), "contrast")
            self.assertIsNotNone(self.window.plan)
            self.assertEqual(self.window.plan.steps[0].action, "appearance.theme")
            self.assertTrue(self.window.apply_button.isEnabled())
            self.window.apply()
            self.wait(lambda: applied)
        self.assertEqual(applied[0][1], "Settings: theme")
        self.wait(lambda: self.window.last_entry == "abc123")

    def test_weakening_needs_the_word_and_system_changes_need_an_admin(self):
        self.window.change(model.by_key("updates"), False)
        self.assertFalse(self.window.apply_button.isEnabled())
        self.window.confirm_field.setText("yes")
        self.assertTrue(self.window.apply_button.isEnabled())
        self.window.admin = False
        self.window._update_apply()
        self.assertFalse(self.window.apply_button.isEnabled())
        self.window.change(model.by_key("theme"), "night")  # the person's own account: no admin needed
        self.assertTrue(self.window.apply_button.isEnabled())

    def test_the_same_value_is_not_a_change(self):
        self.window.change(model.by_key("theme"), "day")
        self.assertIsNone(self.window.plan)

    def test_hebrew_is_right_to_left(self):
        from PyQt6.QtCore import Qt
        window = self.gui.SettingsWindow("he", self.ctx, admin=True)
        self.addCleanup(window.deleteLater)
        self.assertEqual(window.layoutDirection(), Qt.LayoutDirection.RightToLeft)
        self.assertEqual(window.windowTitle(), "הגדרות D.Ai")

    def wait(self, condition, timeout=5.0):
        import time
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.qt.processEvents()
            time.sleep(0.01)
        self.assertTrue(condition())


if __name__ == "__main__":
    unittest.main()
