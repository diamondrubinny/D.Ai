# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The D.Ai VM window: the hardware check shown, the wizard that creates a machine, the buttons that follow its
state, the viewer spawned, deleting, the drivers download, and Raz's accessibility audit in Hebrew and English
in all three themes."""
import hashlib
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import PyQt6  # noqa: F401
except ImportError:
    raise unittest.SkipTest("PyQt6 is missing")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog, QLabel  # noqa: E402

from dai_vm import drivers, hardware  # noqa: E402

from . import fakes  # noqa: E402

RAZ = Path(__file__).resolve().parents[2] / "dai-raz"
if str(RAZ) not in sys.path:
    sys.path.insert(0, str(RAZ))


def load_gui(theme: str = "night"):
    os.environ["DAI_THEME"] = theme
    from dai_vm import gui
    return importlib.reload(gui)


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.root = fakes.fake_root(self.home / "root")
        self.run = fakes.FakeRun()
        self.virsh = fakes.virsh_with(self.run)
        self.spawned, self.urls = [], []
        self.iso = fakes.fake_iso(self.home / "win.iso")

    def report(self, lang="en", **kwargs):
        root = fakes.fake_root(self.root, **kwargs)
        return fakes.check(lang, root=root, home=self.home)

    def window(self, lang="en", report=None, fetch=None):
        gui = load_gui()
        win = gui.VmWindow(lang=lang, home=self.home, virsh=self.virsh, report=report or self.report(lang), run=self.run,
                           spawn=self.spawned.append, open_url=self.urls.append, fetch=fetch)
        self.addCleanup(win.close)
        win.show()
        self.app.processEvents()
        return win

    def texts(self, widget):
        return " ".join(w.text() for w in widget.findChildren(QLabel))

    def create(self, win, name="win11"):
        gui = sys.modules["dai_vm.gui"]
        dialog = gui.NewMachineDialog(win, win.lang, win.report, False, win.open_url)
        dialog.name.setText(name)
        dialog.iso_field.setText(str(self.iso))
        self.assertTrue(dialog.create_button.isEnabled(), dialog.problem.text())
        self.assertTrue(win.create_from(dialog))
        return dialog

    def test_the_check_and_the_wizard(self):
        win = self.window()
        self.assertIn("Hardware virtualization is on (VT-x)", self.texts(win))
        self.assertTrue(win.new_button.isEnabled())
        gui = sys.modules["dai_vm.gui"]
        dialog = gui.NewMachineDialog(win, "en", win.report, False, win.open_url)
        self.assertFalse(dialog.create_button.isEnabled())
        self.assertIn("Choose the installation ISO", dialog.problem.text())
        dialog.name.setText("win 11")
        dialog.iso_field.setText(str(self.home / "none.iso"))
        self.assertIn("A name:", dialog.problem.text())
        self.assertIn("does not exist", dialog.problem.text())
        dialog.name.setText("win11")
        dialog.iso_field.setText(str(self.iso))
        self.assertTrue(dialog.create_button.isEnabled())
        self.assertIn("CCCOMA_X64FRE", dialog.iso_note.text())
        self.assertEqual(dialog.memory.value(), 7812)
        self.assertFalse(dialog.attach_drivers.isEnabled())
        dialog.findChildren(gui.QPushButton)[0].click()  # "Open Microsoft's download page"
        self.assertEqual(self.urls, [gui.WINDOWS_DOWNLOAD_PAGE])
        self.assertTrue(win.create_from(dialog))
        self.assertEqual([m.name for m in win.loaded], ["win11"])
        self.assertIn("win11 is ready", win.status.text())
        self.assertIn("win11 · off", win.machines.item(0).text())

    def test_buttons_follow_the_state_and_the_viewer_opens(self):
        win = self.window()
        self.create(win)
        self.assertTrue(win.start_button.isEnabled())
        self.assertFalse(win.stop_button.isEnabled())
        win.act("start")
        self.assertEqual(self.virsh.state("win11"), "running")
        self.assertEqual(self.spawned[-1][0], "remote-viewer")
        self.assertTrue(win.stop_button.isEnabled() and win.pause_button.isEnabled())
        self.assertFalse(win.start_button.isEnabled())
        win.act("pause")
        self.assertTrue(win.resume_button.isEnabled())
        win.act("resume")
        win.act("show")
        self.assertEqual(len(self.spawned), 2)
        win.act("stop")
        self.assertEqual(self.virsh.state("win11"), "shut off")
        self.assertIn("asked to shut down", win.status.text())
        self.run.fail.add("start")
        win.act("start")
        self.assertIn("did not work", win.status.text())

    def test_delete(self):
        win = self.window()
        self.create(win)
        win.act("start")
        win.really_delete(win.loaded[0])
        self.assertEqual(win.loaded, [])
        self.assertEqual(self.virsh.state("win11"), "missing")
        self.assertFalse((self.home / ".local/share/dai/vm/machines/win11").exists())

    def test_a_weak_computer_cannot_create(self):
        win = self.window(report=self.report(flags="fpu"))
        self.assertFalse(win.new_button.isEnabled())
        self.assertIn("VT-x or AMD-V", self.texts(win))

    def test_drivers_download_in_the_window(self):
        data = b"ISO" * 100
        entry = drivers.Driver("virtio-win", "t", "https://example.org/v.iso", "v.iso", hashlib.sha256(data).hexdigest(), len(data), "")
        fetch = fakes.FakeFetch(data)
        win = self.window(fetch=fetch)
        win.entry = entry
        win.refresh_drivers()
        self.assertTrue(win.download_button.isEnabled())
        win.download_drivers()
        self.assertIsNotNone(win.thread)
        win.thread.wait(10000)
        for _ in range(20):
            self.app.processEvents()
        self.assertIsNone(win.thread)
        self.assertTrue(drivers.present(entry, self.home))
        self.assertIn("ready", win.drivers_label.text())
        self.assertIn("verified", win.status.text())

    def test_accessible_in_both_languages_and_every_theme(self):
        from dai_raz.a11y import assert_accessible

        for lang in ("en", "he"):
            win = self.window(lang=lang)
            self.create(win, name=f"m-{lang}")
            assert_accessible(self, win)
            gui = sys.modules["dai_vm.gui"]
            for dialog in (gui.NewMachineDialog(win, lang, win.report, False, win.open_url),
                           gui.ConfirmDialog(win, lang, "t", "text", "yes")):
                dialog.show()
                self.app.processEvents()
                assert_accessible(self, dialog)
                dialog.close()
        weak = self.window(lang="he", report=self.report("he", flags="fpu", mem_kb=4_000_000))
        assert_accessible(self, weak)


if __name__ == "__main__":
    unittest.main()
