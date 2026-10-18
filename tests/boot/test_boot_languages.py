# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The boot menu languages hook (docs/I18N.md §9), on menus shaped like the ones live-build writes."""
import importlib.machinery
import importlib.util
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parents[2] / "build/live-build/common/hooks/normal/0400-dai-boot-languages.hook.binary"
loader = importlib.machinery.SourceFileLoader("boot_languages", str(HOOK))
spec = importlib.util.spec_from_loader("boot_languages", loader)
hook = importlib.util.module_from_spec(spec)
loader.exec_module(hook)

APPEND = ("boot=live components quiet hostname=dai-os username=dai locales=en_US.UTF-8,he_IL.UTF-8 "
          "keyboard-layouts=us,il keyboard-options=grp:alt_shift_toggle timezone=Asia/Jerusalem")
GRUB = f"""source /boot/grub/config.cfg

# Live boot
menuentry "Live system (amd64)" --hotkey=l {{
	linux	/live/vmlinuz-6.12.0-amd64 {APPEND}
	initrd	/live/initrd.img-6.12.0-amd64
}}
menuentry "Live system (amd64 fail-safe mode)" {{
	linux	/live/vmlinuz-6.12.0-amd64 boot=live components memtest noapic noapm nodma nomce nolapic nosmp nosplash vga=788
	initrd	/live/initrd.img-6.12.0-amd64
}}
"""
SYSLINUX = f"""label live-amd64
	menu label ^Live system (amd64)
	menu default
	linux /live/vmlinuz-6.12.0-amd64
	initrd /live/initrd.img-6.12.0-amd64
	append {APPEND}

label live-amd64-failsafe
	menu label ^Live system (amd64 fail-safe mode)
	linux /live/vmlinuz-6.12.0-amd64
	initrd /live/initrd.img-6.12.0-amd64
	append boot=live components memtest noapic
"""


class BootLanguagesTests(unittest.TestCase):
    def test_grub_submenu_after_the_default_entry(self):
        out = hook.patch_grub(GRUB)
        self.assertTrue(out.startswith(GRUB[:GRUB.index("menuentry \"Live system (amd64 fail-safe")].rstrip("\n")))
        self.assertLess(out.index("submenu"), out.index("fail-safe"))  # the default entry stays first
        self.assertEqual(out.count("{"), out.count("}"))
        entries = re.findall(r'menuentry "([^"]+)" --id dai-languages-(\w+) \{\n(.*?)\n\t\}', out, re.S)
        self.assertEqual([code for _, code, _ in entries], ["en", "he", "ar", "ru", "es", "fr", "de", "pt"])
        russian = dict((code, body) for _, code, body in entries)["ru"]
        self.assertIn("locales=ru_RU.UTF-8,en_US.UTF-8 keyboard-layouts=ru,us,il keyboard-options=grp:alt_shift_toggle",
                      russian)
        self.assertIn("initrd\t/live/initrd.img-6.12.0-amd64", russian)
        self.assertEqual(russian.count("locales="), 1)
        self.assertTrue(all(ord(ch) < 128 for ch in out))  # boot fonts: ASCII only
        self.assertIsNone(hook.patch_grub(out))  # once
        if shutil.which("grub-script-check"):  # GRUB's own parser accepts it
            check = subprocess.run(["grub-script-check"], input=out, text=True, capture_output=True)
            self.assertEqual(check.returncode, 0, check.stderr)

    def test_syslinux_submenu(self):
        out = hook.patch_syslinux(SYSLINUX)
        self.assertLess(out.index("menu begin dai-languages"), out.index("live-amd64-failsafe"))
        self.assertEqual(out.count("menu default"), 1)  # still the plain live entry
        block = out[out.index("label dai-languages-ar"):out.index("label dai-languages-ru")]
        self.assertIn("menu label Arabic - al-Arabiya", block)
        self.assertIn("append boot=live components quiet hostname=dai-os username=dai locales=ar_EG.UTF-8,en_US.UTF-8 "
                      "keyboard-layouts=ara,us,il", block)
        self.assertIn("linux /live/vmlinuz-6.12.0-amd64", block)
        self.assertIn("menu exit", out)
        self.assertIsNone(hook.patch_syslinux(out))

    def test_a_menu_without_a_live_entry_is_left_alone(self):
        self.assertIsNone(hook.patch_grub('menuentry "Memtest" {\n\tlinux16 /memtest\n}\n'))
        self.assertIsNone(hook.patch_syslinux("label hdt\n\tcom32 hdt.c32\n"))
        self.assertEqual(hook.with_language("boot=live quiet", "de_DE.UTF-8", "de,us"),
                         "boot=live quiet locales=de_DE.UTF-8 keyboard-layouts=de,us")

    def test_runs_in_the_binary_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "boot/grub").mkdir(parents=True)
            (root / "isolinux").mkdir()
            (root / "boot/grub/grub.cfg").write_text(GRUB)
            (root / "boot/grub/config.cfg").write_text("set timeout=5\n")
            (root / "isolinux/live.cfg").write_text(SYSLINUX)
            self.assertEqual(hook.main(root), 0)
            self.assertIn("dai-languages", (root / "boot/grub/grub.cfg").read_text())
            self.assertEqual((root / "boot/grub/config.cfg").read_text(), "set timeout=5\n")
            self.assertIn("dai-languages", (root / "isolinux/live.cfg").read_text())


if __name__ == "__main__":
    unittest.main()
