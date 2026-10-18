# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from dai_ai import models
from dai_tune import posture
from dai_tune.cli import ApplyResult
from dai_tune.context import Context

from dai_welcome import core

REPO = Path(__file__).resolve().parents[3]
CATALOG = models.load_catalog(REPO / "apps" / "dai-ai" / "data" / "models.json")


def quiet_runner(argv):
    return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


class WelcomeTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root, self.home = base / "root", base / "home"
        self.root.mkdir()
        self.home.mkdir()
        self.ctx = Context(root=self.root, home=self.home, runner=quiet_runner, lang="en")

    def tearDown(self):
        self.tmp.cleanup()


class FirstRunTests(WelcomeTestCase):
    def test_opens_once_and_never_in_the_live_session(self):
        self.assertTrue(core.first_run_needed(self.home, self.root))
        path = core.mark_done(self.home, {"skipped": True})
        self.assertFalse(core.first_run_needed(self.home, self.root))
        self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")
        self.assertTrue(json.loads(path.read_text())["skipped"])
        path.unlink()
        (self.root / "run" / "live" / "medium").mkdir(parents=True)
        self.assertFalse(core.first_run_needed(self.home, self.root))


class SecurityTests(WelcomeTestCase):
    def checks(self, lock_ok, updates_ok):
        return [posture.Check("lock", lock_ok, 10), posture.Check("updates", updates_ok, 15)]

    def test_levels_to_sentences(self):
        self.assertEqual(core.security_sentences("recommended", self.checks(False, False)), [core.LOCK, core.UPDATES])
        self.assertEqual(core.security_sentences("recommended", self.checks(True, True)), [])
        self.assertEqual(core.security_sentences("strict", self.checks(True, True)), list(core.STRICT_EXTRA))
        self.assertEqual(core.security_sentences("keep", self.checks(False, False)), [])
        with self.assertRaises(ValueError):
            core.security_sentences("off", [])

    def test_plans_are_real_tune_plans(self):
        plan = core.security_plan("strict", self.ctx)
        self.assertTrue(plan.ok)
        actions = [step.action for step in plan.steps]
        lock_ok = {c.key: c.ok for c in posture.assess(self.ctx)[1]}["lock"]
        self.assertEqual("session.lock" in actions, not lock_ok)
        self.assertEqual(actions.count("device.block"), 2)
        with mock.patch.object(posture, "assess", return_value=(0, [posture.Check("lock", False, 10)])):
            actions = [step.action for step in core.security_plan("recommended", self.ctx).steps]
        self.assertEqual(actions, ["session.lock", "updates.auto"])
        self.assertIsNone(core.security_plan("keep", self.ctx))


class ModelTests(WelcomeTestCase):
    def test_ram(self):
        meminfo = self.root / "meminfo"
        meminfo.write_text("MemTotal:       16303512 kB\nMemFree: 1 kB\n")
        self.assertEqual(core.ram_mb(meminfo), 15921)
        self.assertEqual(core.ram_mb(self.root / "missing"), 0)

    def test_options_follow_memory(self):
        low = {o.key: o for o in core.ai_options(2000)}
        self.assertFalse(low["assistant"].checked)
        self.assertEqual(low["assistant"].note, "low_ram")
        self.assertTrue(low["voice"].checked)
        mid = {o.key: o for o in core.ai_options(6000)}
        self.assertEqual((mid["assistant"].model_id, mid["assistant"].checked), (core.ASSISTANT_SMALL, True))
        self.assertFalse(mid["code"].checked)
        big = core.ai_options(16000)
        self.assertEqual(core.chosen_models(big), [core.CODER, core.VOICE])
        self.assertEqual({o.key: o.note for o in big}["code"], "included")
        installed = core.ai_options(16000, {core.VOICE})
        self.assertEqual(core.chosen_models(installed), [core.CODER])
        for option in core.ai_options(16000):
            self.assertIn(option.model_id, CATALOG)

    def test_setup_continues_after_a_failure_and_sets_defaults(self):
        applied, installed, defaults, seen = [], [], [], []

        def apply(plan, ctx, label=""):
            applied.append(label)
            return ApplyResult(True, entry_id="x")

        def install(model, progress=None):
            if model.id == core.CODER:
                raise models.ModelError("network down")
            progress(model.size, model.size)
            installed.append(model.id)

        setup = core.Setup(core.security_plan("recommended", self.ctx),
                           [core.ASSISTANT_SMALL, core.CODER, core.VOICE])
        results = core.run_setup(setup, self.ctx, seen.append, apply=apply, install=install, catalog=CATALOG,
                                 set_default=lambda model_id, key="model": defaults.append((key, model_id)))
        self.assertEqual(applied, ["D.Ai Welcome"])
        self.assertEqual([(r.label, r.ok) for r in results],
                         [("security", True), (core.ASSISTANT_SMALL, True), (core.CODER, False), (core.VOICE, True)])
        self.assertIn("network down", results[2].detail)
        self.assertEqual(installed, [core.ASSISTANT_SMALL, core.VOICE])
        self.assertEqual(defaults, [("speech_model", core.VOICE), ("model", core.ASSISTANT_SMALL)])
        self.assertIn(f"model:{core.VOICE}:100", seen)


try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication, QCheckBox, QLabel, QPushButton, QRadioButton

    from dai_welcome import gui
    HAVE_QT = True
except ImportError:  # PyQt6 is not installed on every developer machine
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PyQt6 not available")
class WindowTests(WelcomeTestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(gui.STYLE)

    def window(self, lang="en", admin=True, ram=16000, runner=None):
        win = gui.WelcomeWindow(lang, self.ctx, ram=ram, installed=set(), catalog=CATALOG, admin=admin, runner=runner)
        win.show()
        self.addCleanup(win.close)
        return win

    def texts(self, win, kind=None):
        kind = kind or QLabel
        return " ".join(w.text() for w in win.findChildren(kind) if w.isVisible())

    def goto(self, win, step):
        win.show_step(step)
        self.app.processEvents()

    def click(self, win, text):
        buttons = [b for b in win.findChildren(QPushButton) if b.text() == text and b.isVisible()]
        self.assertTrue(buttons, f"no button {text!r} in: {self.texts(win, QPushButton)}")
        buttons[0].click()
        self.app.processEvents()

    def test_walk_through_and_apply(self):
        calls = []

        def runner(setup, ctx, progress):
            calls.append(setup)
            progress("security")
            progress(f"model:{core.CODER}:50")
            return [core.Result("security", True), core.Result(core.CODER, True), core.Result(core.VOICE, True)]

        win = self.window(runner=runner)
        self.assertIn("Welcome to D.Ai OS", self.texts(win))
        self.click(win, "Let's start ✦")
        self.assertEqual(win.step, "security")
        self.assertIn("Security score now:", self.texts(win))
        strict = [r for r in win.findChildren(QRadioButton) if r.text() == "Strict"][0]
        strict.setChecked(True)
        self.click(win, "Next")
        self.assertEqual(win.step, "ai")
        boxes = {b.text(): b for b in win.findChildren(QCheckBox)}
        self.assertFalse(boxes[gui.STRINGS["code"][0]].isEnabled())  # included in the assistant
        self.click(win, "Next")
        self.assertIn("No telemetry", self.texts(win))
        self.click(win, "Next")
        summary = self.texts(win)
        self.assertIn("System changes", summary)
        self.assertIn("Downloads", summary)
        self.click(win, "Apply ✦")
        deadline = time.monotonic() + 10
        while win.step != "done" and time.monotonic() < deadline:
            QTest.qWait(20)
        self.assertEqual(win.step, "done")
        self.assertEqual(calls[0].models, [core.CODER, core.VOICE])
        self.assertEqual(sum(1 for s in calls[0].plan.steps if s.action == "device.block"), 2)
        self.assertIn("Super+Space", self.texts(win))
        state = json.loads(core.state_path(self.home).read_text())
        self.assertEqual((state["level"], state["failed"]), ("strict", []))

    def test_not_an_administrator(self):
        win = self.window(admin=False, ram=2000)
        self.goto(win, "security")
        radios = {r.text(): r for r in win.findChildren(QRadioButton)}
        self.assertFalse(radios["Strict"].isEnabled())
        self.assertTrue(radios["Keep as it is"].isChecked())
        self.assertIn("Only an administrator", self.texts(win))
        self.goto(win, "ai")
        for box in win.findChildren(QCheckBox):
            box.setChecked(False)
        self.goto(win, "summary")
        self.assertIn("Nothing to change", self.texts(win))
        self.click(win, "Finish")
        self.assertTrue(core.state_path(self.home).exists())

    def test_escape_means_not_now(self):
        win = self.window()
        win.activateWindow()
        QTest.qWaitForWindowActive(win, 2000)
        QTest.keyClick(win.focusWidget() or win, Qt.Key.Key_Escape)
        self.app.processEvents()
        self.assertTrue(json.loads(core.state_path(self.home).read_text())["skipped"])
        self.assertFalse(win.isVisible())

    def test_hebrew_and_accessible_names(self):
        win = self.window(lang="he")
        self.assertIn("ברוכים הבאים", self.texts(win))
        for button in win.findChildren(QPushButton):
            if button.isVisible():
                self.assertTrue(button.accessibleName())
        self.goto(win, "ai")
        for box in win.findChildren(QCheckBox):
            self.assertTrue(box.accessibleDescription())

    def test_failed_step_offers_retry(self):
        win = self.window(runner=lambda s, c, p: [core.Result(core.VOICE, False, "no network")])
        self.goto(win, "summary")
        self.click(win, "Apply ✦")
        deadline = time.monotonic() + 10
        while win.step != "done" and time.monotonic() < deadline:
            QTest.qWait(20)
        self.assertIn("no network", self.texts(win))
        self.click(win, "Try again")
        self.assertEqual(win.step, "summary")


if __name__ == "__main__":
    unittest.main()
