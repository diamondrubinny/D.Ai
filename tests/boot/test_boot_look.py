# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The way to the desktop (docs/V2.md D2): boot menu look, Plymouth theme, GRUB settings and the SDDM theme.

The menus here are live-build's own templates (live-build 20250505, Debian 13) after its substitutions.
"""
import configparser
import importlib.machinery
import importlib.util
import re
import shutil
import struct
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LB = ROOT / "build/live-build/common"
CHROOT = LB / "includes.chroot_after_packages"
HOOK = LB / "hooks/normal/0450-dai-boot-look.hook.binary"
loader = importlib.machinery.SourceFileLoader("boot_look", str(HOOK))
spec = importlib.util.spec_from_loader("boot_look", loader)
hook = importlib.util.module_from_spec(spec)
loader.exec_module(hook)

STDMENU = """menu background splash.png
menu color title	* #FFFFFFFF *
menu color border	* #00000000 #00000000 none
menu color sel		* #ffffffff #76a1d0ff *
menu color hotsel	1;7;37;40 #ffffffff #76a1d0ff *
menu color tabmsg	* #ffffffff #00000000 *
menu color help		37;40 #ffdddd00 #00000000 none
menu vshift 12
menu rows 10
menu tabmsg Press ENTER to boot or TAB to edit a menu entry
menu width 82
"""
MENU = """menu hshift 0
menu width 82

menu title Boot menu\x07
include stdmenu.cfg
include live.cfg
"""
LIVE = """label live-amd64
	menu label ^Live system (amd64)
	menu default
	linux /live/vmlinuz
	initrd /live/initrd.img
	append boot=live components quiet splash

label live-amd64-failsafe
	menu label Live system (amd64 fail-safe mode)
	linux /live/vmlinuz
	append boot=live components memtest noapic
"""
GRUB = """menuentry "Live system (amd64)" --hotkey=l {
	linux	/live/vmlinuz boot=live components quiet splash
}
menuentry "Live system (amd64 fail-safe mode)" {
	linux	/live/vmlinuz boot=live components memtest
}
"""
THEME = """desktop-image: "../splash.png"
title-color: "#ffffff"
title-font: "Unifont Regular 16"
title-text: "Live Boot Menu with GRUB"
+ label {
        color = "#ffffff"
}
+ boot_menu {
        item_color = "#a8a8a8"
        selected_item_color= "#ffffff"
}
+ progress_bar {
        text_color = "#000000"
        fg_color = "#ffffff"
        bg_color = "#a8a8a8"
        border_color = "#ffffff"
}
"""


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path
    return struct.unpack(">II", data[16:24])


class BootMenuLookTests(unittest.TestCase):
    def test_syslinux_colours_replace_debians(self):
        out = hook.patch_stdmenu(STDMENU)
        self.assertNotIn("#76a1d0ff", out)
        self.assertIn("#ff5b3fd6", out)  # the selection in D.Ai's accent
        self.assertTrue(out.startswith("menu background splash.png\nmenu color"))
        self.assertIn("menu vshift 12", out)  # the layout stays
        self.assertEqual(hook.patch_stdmenu(out), out)  # running again changes nothing

    def test_entries_are_named_for_d_ai(self):
        self.assertIn("menu title D.Ai OS", hook.patch_menu(MENU))
        live = hook.rename(LIVE)
        self.assertIn("menu label ^Start D.Ai OS\n", live)
        self.assertIn("menu label Start D.Ai OS (safe graphics)", live)
        self.assertIn("append boot=live components quiet splash", live)  # the command line stays
        self.assertIn("menu title D.Ai OS", hook.rename("menu title Boot menu\ninclude live.cfg\n"))  # any file
        # live-build's own line ends with a BEL (the beep for blind users), which must survive
        self.assertEqual(hook.rename("menu title Boot menu\x07\n"), "menu title D.Ai OS\x07\n")
        grub = hook.rename(GRUB)
        self.assertIn('menuentry "Start D.Ai OS" --hotkey=l {', grub)
        self.assertIn('menuentry "Start D.Ai OS (safe graphics)" {', grub)

    def test_grub_theme(self):
        out = hook.patch_grub_theme(THEME)
        self.assertIn('desktop-image-scale-method: "crop"', out)
        self.assertIn('title-text: ""', out)
        self.assertIn('item_color = "#a9b1d3"', out)
        self.assertIn('fg_color = "#7c5cff"', out)
        self.assertIn('text_color = "#e6e9f5"', out)
        self.assertNotIn("#a8a8a8", out)
        self.assertEqual(hook.patch_grub_theme(out), out)

    def test_the_hook_on_a_binary_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            build = Path(tmp)
            binary, chroot = build / "binary", build / "chroot"
            for relative, text in (("isolinux/stdmenu.cfg", STDMENU), ("isolinux/menu.cfg", MENU),
                                   ("isolinux/live.cfg", LIVE), ("boot/grub/grub.cfg", GRUB),
                                   ("boot/grub/live-theme/theme.txt", THEME)):
                (binary / relative).parent.mkdir(parents=True, exist_ok=True)
                (binary / relative).write_text(text)
            (binary / "isolinux/splash.png").write_bytes(b"debian")
            (binary / "boot/grub/splash.png").write_bytes(b"debian")
            art = chroot / hook.ART
            art.parent.mkdir(parents=True)
            shutil.copytree(CHROOT / hook.ART, art)
            self.assertEqual(hook.main(binary, chroot), 0)
            self.assertEqual(png_size(binary / "isolinux/splash.png"), (640, 480))
            self.assertEqual(png_size(binary / "boot/grub/splash.png"), (1920, 1080))
            self.assertIn("Start D.Ai OS", (binary / "isolinux/live.cfg").read_text())
            self.assertIn("Start D.Ai OS", (binary / "boot/grub/grub.cfg").read_text())

    def test_missing_pieces_never_break_the_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(hook.main(Path(tmp) / "binary", Path(tmp) / "chroot"), 0)


class PicturesAndThemesTests(unittest.TestCase):
    def test_pictures(self):
        self.assertEqual(png_size(CHROOT / hook.ART / "syslinux-splash.png"), (640, 480))  # vesamenu's size
        self.assertEqual(png_size(CHROOT / hook.ART / "grub-splash.png"), (1920, 1080))
        theme = CHROOT / "usr/share/plymouth/themes/dai"
        self.assertTrue((theme / "watermark.png").is_file())
        self.assertGreaterEqual(len(list(theme.glob("throbber-*.png"))), 12)

    def test_plymouth_theme(self):
        config = configparser.ConfigParser(interpolation=None)
        config.read(CHROOT / "usr/share/plymouth/themes/dai/dai.plymouth")
        self.assertEqual(config["Plymouth Theme"]["ModuleName"], "two-step")
        self.assertEqual(config["two-step"]["ImageDir"], "/usr/share/plymouth/themes/dai")
        self.assertEqual(config["two-step"]["BackgroundStartColor"], "0x0b1020")
        hook_text = (LB / "hooks/normal/0250-dai-boot-look.hook.chroot").read_text()
        self.assertIn("plymouth-set-default-theme -R dai", hook_text)
        packages = (LB / "package-lists/desktop.list.chroot").read_text().split()
        self.assertTrue({"plymouth", "plymouth-themes"} <= set(packages))  # two-step is in plymouth-themes
        self.assertRegex((ROOT / "build/scripts/build-iso.sh").read_text(), r"--bootappend-live \"[^\"]*\bsplash\b")

    def test_installed_grub(self):
        text = (CHROOT / "etc/default/grub.d/50-dai.cfg").read_text()
        self.assertIn('GRUB_DISTRIBUTOR="D.Ai OS"', text)
        background = re.search(r'GRUB_BACKGROUND="([^"]+)"', text).group(1)
        self.assertTrue((CHROOT / background.lstrip("/")).is_file(), background)

    def test_sddm_theme(self):
        theme = CHROOT / "usr/share/sddm/themes/dai"
        meta = configparser.ConfigParser(interpolation=None)
        meta.read(theme / "metadata.desktop")
        info = meta["SddmGreeterTheme"]
        self.assertEqual(info["QtVersion"], "6")  # Debian 13's greeter is sddm-greeter-qt6
        self.assertTrue((theme / info["MainScript"]).is_file())
        qml = (theme / info["MainScript"]).read_text()
        self.assertIn("sddm.login(", qml)
        self.assertIn("LayoutMirroring.enabled", qml)  # right to left
        self.assertGreaterEqual(qml.count("Accessible.name"), 6)
        imports = set(re.findall(r"^import (\S+)", qml, re.M))
        self.assertLessEqual(imports, {"QtQuick", "SddmComponents"})  # nothing beyond what sddm depends on
        conf = (CHROOT / "etc/sddm.conf.d/10-dai-theme.conf").read_text()
        self.assertIn("Current=dai", conf)


if __name__ == "__main__":
    unittest.main()
