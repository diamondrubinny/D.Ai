# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""D.Ai sounds (docs/SOUNDS.md): the theme's files, the choices, Do not disturb and the udev watcher."""
import configparser
import tempfile
import unittest
from pathlib import Path

from dai_sound import cli

ROOT = Path(__file__).resolve().parents[3]
THEME = ROOT / "build/live-build/common/includes.chroot_after_packages/usr/share/sounds/dai"
NAMES = ("desktop-login", "desktop-logout", "message-new-instant", "dialog-information", "complete", "dialog-warning",
         "dialog-error", "bell", "device-added", "device-removed", "power-plug", "power-unplug", "screen-capture",
         "audio-volume-change", "trash-empty")


class ThemeTests(unittest.TestCase):
    def test_every_sound_is_there_and_small(self):
        for name in NAMES:
            path = THEME / "stereo" / f"{name}.oga"
            with self.subTest(name=name):
                self.assertTrue(path.is_file())
                self.assertEqual(path.read_bytes()[:4], b"OggS")
                self.assertLess(path.stat().st_size, 64 * 1024)

    def test_index_theme(self):
        index = configparser.ConfigParser(interpolation=None)
        index.read(THEME / "index.theme")
        self.assertEqual(index["Sound Theme"]["Directories"], "stereo")
        self.assertEqual(index["Sound Theme"]["Inherits"], "freedesktop")
        self.assertEqual(index["stereo"]["OutputProfile"], "stereo")


class PlayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = {"XDG_CONFIG_HOME": self.tmp.name}
        self.calls = []

    def run_(self, argv, **kwargs):
        self.calls.append(argv)

    def play(self, name, force=False):
        return cli.play(name, self.run_, self.env, [str(THEME / "stereo")], force)

    def set_dnd(self, on):
        path = Path(self.tmp.name) / "lxqt" / "notifications.conf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"[General]\ndoNotDisturb={'true' if on else 'false'}\n")

    def test_plays_with_pipewire(self):
        self.assertTrue(self.play("complete"))
        self.assertEqual(self.calls[0][:3], ["pw-play", "--volume", "0.7"])
        self.assertTrue(self.calls[0][3].endswith("/complete.oga"))

    def test_quiet_and_off(self):
        cli.save_mode("quiet", self.env)
        self.play("complete")
        self.assertEqual(self.calls[-1][2], "0.3")
        cli.save_mode("off", self.env)
        self.assertFalse(self.play("complete"))
        self.assertFalse(self.play("desktop-login"))  # off is off
        self.assertTrue(self.play("complete", force=True))  # a preview from Tune

    def test_do_not_disturb_silences_all_but_login(self):
        self.set_dnd(True)
        self.assertFalse(self.play("message-new-instant"))
        self.assertTrue(self.play("desktop-login"))
        self.set_dnd(False)
        self.assertTrue(self.play("message-new-instant"))

    def test_names_are_never_paths(self):
        for bad in ("../../etc/passwd", "a/b", "", "X", "complete.oga", "-v"):
            self.assertFalse(self.play(bad), bad)
        self.assertEqual(self.calls, [])

    def test_unknown_choice_means_on(self):
        path = Path(self.tmp.name) / "dai" / "sounds"
        path.parent.mkdir(parents=True)
        path.write_text("loud\n")
        self.assertEqual(cli.mode(self.env), "on")
        with self.assertRaises(ValueError):
            cli.save_mode("loud", self.env)


class WatcherTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.played = []
        self.charging = False

    def watcher(self):
        return cli.Watcher(self.played.append, lambda: self.charging, lambda: self.now)

    def test_usb_devices(self):
        watcher = self.watcher()
        watcher.line("UDEV  [512.103] add      /devices/pci0000:00/0000:00:14.0/usb1/1-2 (usb)")
        watcher.line("UDEV  [512.140] add      /devices/pci0000:00/0000:00:14.0/usb1/1-2 (usb)")  # the same plug-in
        self.now += 5
        watcher.line("UDEV  [517.000] remove   /devices/pci0000:00/0000:00:14.0/usb1/1-2 (usb)")
        self.assertEqual(self.played, ["device-added", "device-removed"])

    def test_charger(self):
        watcher = self.watcher()
        self.charging = True
        watcher.line("UDEV  [600.0] change   /devices/LNXSYSTM:00/ACPI0003:00/power_supply/AC (power_supply)")
        watcher.line("UDEV  [600.1] change   /devices/LNXSYSTM:00/PNP0C0A:00/power_supply/BAT0 (power_supply)")
        self.now += 10
        self.charging = False
        watcher.line("UDEV  [610.0] change   /devices/LNXSYSTM:00/ACPI0003:00/power_supply/AC (power_supply)")
        self.assertEqual(self.played, ["power-plug", "power-unplug"])

    def test_desktop_without_a_charger_and_noise(self):
        watcher = cli.Watcher(self.played.append, lambda: None, lambda: self.now)
        watcher.line("UDEV  [1.0] change   /devices/x/power_supply/BAT0 (power_supply)")
        watcher.line("monitor will print the received events for:")
        watcher.line("KERNEL[1.0] add      /devices/x (usb)")
        self.assertEqual(self.played, [])

    def test_mains_from_sysfs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIsNone(cli.mains_online(root))
            (root / "AC").mkdir()
            (root / "AC" / "type").write_text("Mains\n")
            (root / "AC" / "online").write_text("1\n")
            (root / "BAT0").mkdir()
            (root / "BAT0" / "type").write_text("Battery\n")
            self.assertTrue(cli.mains_online(root))
            (root / "AC" / "online").write_text("0\n")
            self.assertFalse(cli.mains_online(root))


if __name__ == "__main__":
    unittest.main()
