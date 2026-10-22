# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dai_quick.controls import Controls


class FakeSystem:
    """nmcli, bluetoothctl, powerprofilesctl and wpctl as a little state machine."""

    def __init__(self, bluetooth_adapter=True, tools=("nmcli", "bluetoothctl", "powerprofilesctl", "wpctl")):
        self.state = {"wifi": "enabled", "bt": "no", "profile": "balanced", "mic": False, "volume": 0.62}
        self.adapter = bluetooth_adapter
        self.tools = set(tools)
        self.calls: list[list[str]] = []

    def which(self, name):
        return f"/usr/bin/{name}" if name in self.tools else None

    def run(self, argv):
        self.calls.append(list(argv))
        out = ""
        match argv:
            case ["nmcli", "radio", "wifi"]:
                out = self.state["wifi"] + "\n"
            case ["nmcli", "radio", "wifi", value]:
                self.state["wifi"] = "enabled" if value == "on" else "disabled"
            case ["bluetoothctl", "show"]:
                out = f"Controller 00:11:22:33:44:55 (public)\n\tPowered: {self.state['bt']}\n" if self.adapter else ""
            case ["bluetoothctl", "power", value]:
                self.state["bt"] = "yes" if value == "on" else "no"
            case ["powerprofilesctl", "get"]:
                out = self.state["profile"] + "\n"
            case ["powerprofilesctl", "set", value]:
                self.state["profile"] = value
            case ["dai-focus", "status", "--json"]:
                out = '{"active": %s}\n' % ("true" if self.state.get("focus") else "false")
            case ["dai-focus", "start", minutes]:
                self.state["focus"] = True
                self.state["dnd_by_focus"] = True
            case ["dai-focus", "stop"]:
                self.state["focus"] = False
            case ["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"]:
                out = "Volume: 1.00" + (" [MUTED]" if self.state["mic"] else "") + "\n"
            case ["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", value]:
                self.state["mic"] = value == "1"
            case ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"]:
                out = f"Volume: {self.state['volume']:.2f}\n"
            case ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", value]:
                self.state["volume"] = int(value.rstrip("%")) / 100
            case _:
                return subprocess.CompletedProcess(argv, 1, "", "unknown")
        return subprocess.CompletedProcess(argv, 0, out, "")


class ControlsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.system = FakeSystem()
        self.conf = Path(self.tmp.name) / "lxqt" / "notifications.conf"
        self.controls = Controls(self.system.run, self.system.which, self.conf)

    def test_reads_and_switches_every_toggle(self):
        self.assertEqual(self.controls.state(), {"wifi": True, "bluetooth": False, "dnd": False, "saver": False,
                                                 "mic": False, "focus": None, "volume": 62})  # no dai-focus: no tile
        for key in ("wifi", "bluetooth", "dnd", "saver", "mic"):
            before = self.controls.read(key)
            self.assertTrue(self.controls.set(key, not before), key)
            self.assertEqual(self.controls.read(key), not before, key)
        self.assertEqual(self.system.state["profile"], "power-saver")
        self.controls.set_volume(140)
        self.assertEqual(self.controls.volume(), 100)  # clamped

    def test_missing_hardware_or_tools_are_hidden_not_broken(self):
        system = FakeSystem(bluetooth_adapter=False, tools=("nmcli",))
        controls = Controls(system.run, system.which, self.conf)
        state = controls.state()
        self.assertIsNone(state["bluetooth"])
        self.assertIsNone(state["saver"])
        self.assertIsNone(state["mic"])
        self.assertIsNone(state["volume"])
        self.assertTrue(state["wifi"])

    def test_never_a_shell_and_only_known_controls(self):
        self.controls.set("wifi", False)
        self.assertTrue(all(isinstance(call, list) for call in self.system.calls))
        with self.assertRaises(ValueError):
            self.controls.set("rm -rf", True)

    def test_do_not_disturb_keeps_the_rest_of_the_settings_file(self):
        self.conf.parent.mkdir(parents=True)
        self.conf.write_text("[General]\nplacement=top-right\nblackList=Spammy, Other\nserver_decides=10\n")
        self.controls.set_dnd(True)
        text = self.conf.read_text()
        self.assertIn("doNotDisturb=true", text)  # Qt's key, case kept
        self.assertIn("placement=top-right", text)
        self.assertIn("blackList=Spammy, Other", text)
        self.controls.set_dnd(False)
        self.assertFalse(self.controls.dnd())

    def test_security_and_status_come_from_d_ai(self):
        with mock.patch.dict("sys.modules", {"dai_status": mock.Mock(read=lambda: {"heal": 2})}):
            self.assertEqual(Controls.status(), {"heal": 2})


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PyQt6.QtWidgets import QApplication
        except ImportError:
            raise unittest.SkipTest("PyQt6 is missing")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.system = FakeSystem(bluetooth_adapter=False)
        self.controls = Controls(self.system.run, self.system.which, Path(self.tmp.name) / "n.conf")
        self.spawned = []

    def window(self, lang="en", status=None):
        from dai_quick import gui

        with mock.patch.object(Controls, "security", staticmethod(lambda lang="en": 85)), \
                mock.patch.object(Controls, "status", staticmethod(lambda: status or {})):
            return gui.QuickWindow(self.controls, lang, spawn=self.spawned.append, close_on_blur=False)

    def test_every_control_is_accessible(self):
        from dai_raz.a11y import assert_accessible
        for lang in ("he", "en"):
            assert_accessible(self, self.window(lang), touch=True)

    def test_tiles_mirror_the_system(self):
        window = self.window()
        self.assertEqual(sorted(window.tiles), ["dnd", "mic", "saver", "wifi"])  # no Bluetooth adapter: no tile
        self.assertTrue(window.tiles["wifi"].isChecked())
        self.assertEqual(window.tiles["wifi"].accessibleName(), "Wi-Fi: on")
        window.tiles["wifi"].click()
        self.assertEqual(self.system.state["wifi"], "disabled")
        self.assertEqual(window.tiles["wifi"].accessibleName(), "Wi-Fi: off")
        window.tiles["dnd"].click()
        self.assertFalse(window.dnd_note.isHidden())
        self.assertIn("85/100", window.security_label.text())

    def test_focus_tile_starts_a_session_and_shows_it(self):
        self.system.tools.add("dai-focus")
        self.assertIs(self.controls.focus(), False)
        window = self.window()
        self.assertIn("focus", window.tiles)
        self.assertEqual(window.tiles["focus"].accessibleName(), "Focus 25 min: off")
        window.tiles["focus"].click()
        self.assertIn(["dai-focus", "start", "25"], self.system.calls)
        self.assertTrue(window.tiles["focus"].isChecked())
        window.tiles["focus"].click()
        self.assertIn(["dai-focus", "stop"], self.system.calls)
        self.assertFalse(window.tiles["focus"].isChecked())

    def test_a_failed_switch_shows_the_truth(self):
        window = self.window()
        self.system.tools.discard("nmcli")  # the change cannot happen
        self.system.run = lambda argv: subprocess.CompletedProcess(argv, 1, "", "denied")
        self.controls.runner = self.system.run
        window.tiles["saver"].click()
        self.assertFalse(window.tiles["saver"].isChecked())

    def test_status_rows_and_links(self):
        window = self.window(status={"heal": 2, "privacy": ["<b>Zoom</b>"]})
        self.assertIn("2", window.heal_label.text())
        self.assertIn("<b>Zoom</b>", window.privacy_label.text())  # shown as text, never markup
        from PyQt6.QtWidgets import QPushButton

        buttons = [b for b in window.findChildren(QPushButton) if "help" in b.text().lower()]
        buttons[0].click()
        self.assertEqual(self.spawned[-1], ["dai-heal"])

    def test_hebrew_is_right_to_left(self):
        from PyQt6.QtCore import Qt

        window = self.window("he")
        self.assertEqual(window.layoutDirection(), Qt.LayoutDirection.RightToLeft)
        self.assertIn("לא להפריע", window.tiles["dnd"].text())

    def test_escape_closes(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest

        window = self.window()
        window.show()
        QTest.keyClick(window, Qt.Key.Key_Escape)
        self.assertFalse(window.isVisible())


if __name__ == "__main__":
    unittest.main()
