# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The D.Ai Server edition (docs/SERVER.md §2, §4), checked without building an image.

What is checked: the desktop is removed from a copy of the shared layer (server-prune.py); the server's packages
exclude the desktop, radios and pkexec; every unit, hook and file the server enables exists; the firewall, SSH and
audit files parse; the hardening keys are present. Where a tool is missing on the machine running the tests
(nft, sshd, auditctl), that one check is skipped with a visible reason, never passed silently.
"""
from __future__ import annotations

import configparser
import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "build" / "live-build"
SERVER = LIVE / "editions" / "server"
INCLUDES = SERVER / "includes.chroot_after_packages"
sys.path.insert(0, str(ROOT / "build" / "scripts"))

import importlib  # noqa: E402

prune_module = importlib.import_module("server-prune")

# Packages a server never carries: the desktop, graphics and audio, browsers, radios, office, and the local AI.
DESKTOP_PACKAGES = {
    "labwc", "lxqt-session", "lxqt-panel", "sddm", "xwayland", "xserver-xorg-core", "pcmanfm-qt", "qterminal",
    "pipewire", "wireplumber", "firefox-esr", "libreoffice-writer", "python3-pyqt6", "cups", "orca", "blueman",
    "bluez", "wpasupplicant", "pkexec", "plymouth", "calamares", "flatpak", "grim", "slurp", "swaylock",
}


def package_names(path: Path) -> set[str]:
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        word = line.strip()
        if word and not word.startswith("#"):
            names.add(word)
    return names


class Pruning(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name) / "config"
        shutil.copytree(LIVE / "common", self.config)

    def test_the_desktop_is_removed(self):
        removed = prune_module.prune(self.config)
        self.assertIn("package-lists/desktop.list.chroot", removed)
        self.assertFalse((self.config / "package-lists" / "desktop.list.chroot").exists())
        self.assertFalse((self.config / "hooks" / "normal" / "0200-dai-theme.hook.chroot").exists())
        self.assertFalse((self.config / "hooks" / "normal" / "0300-dai-installer.hook.chroot").exists())
        self.assertFalse((self.config / "includes.chroot_after_packages" / "etc" / "sddm.conf.d").exists())
        self.assertFalse((self.config / "includes.chroot_after_packages" / "usr" / "share" / "sddm").exists())

    def test_radios_and_pkexec_leave_the_base_list(self):
        prune_module.prune(self.config)
        left = package_names(self.config / "package-lists" / "base.list.chroot")
        self.assertFalse(left & prune_module.BASE_REMOVED, left & prune_module.BASE_REMOVED)
        self.assertIn("nftables", left)  # what stays is what a server needs
        self.assertIn("apparmor", left)

    def test_the_shared_security_stays(self):
        prune_module.prune(self.config)
        self.assertTrue((self.config / "includes.chroot_after_packages" / "etc" / "sysctl.d"
                         / "90-dai-hardening.conf").exists())
        self.assertTrue((self.config / "includes.chroot_after_packages" / "etc" / "dai"
                         / "firewall-allow.nft").exists())

    def test_it_is_safe_to_run_twice(self):
        prune_module.prune(self.config)
        self.assertEqual(prune_module.prune(self.config), [])  # nothing left to remove the second time

    def test_a_tree_without_package_lists_is_refused(self):
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        with self.assertRaises(SystemExit):
            prune_module.prune(empty)

    def test_every_named_desktop_hook_exists_in_the_shared_layer(self):
        # A renamed hook must not leave the server with the desktop on a silent typo.
        shared = {p.name for p in (LIVE / "common" / "hooks" / "normal").glob("*.hook.*")}
        for name in prune_module.DESKTOP_HOOKS:
            self.assertIn(name, shared)


class ServerPackages(unittest.TestCase):
    def test_no_desktop_packages(self):
        listed = package_names(SERVER / "package-lists" / "server.list.chroot")
        base = package_names(LIVE / "common" / "package-lists" / "base.list.chroot")
        self.assertFalse(listed & DESKTOP_PACKAGES, listed & DESKTOP_PACKAGES)
        self.assertFalse((base - prune_module.BASE_REMOVED) & DESKTOP_PACKAGES)

    def test_the_server_needs_are_listed(self):
        listed = package_names(SERVER / "package-lists" / "server.list.chroot")
        for name in ("openssh-server", "fail2ban", "auditd", "aide", "chrony", "libpam-pwquality"):
            self.assertIn(name, listed)

    def test_the_build_accepts_the_server_edition(self):
        text = (ROOT / "build" / "scripts" / "build-iso.sh").read_text(encoding="utf-8")
        self.assertIn("user | dev | edu | server", text)
        self.assertIn('if [[ "$EDITION" == server ]]; then', text)
        self.assertIn("server-prune.py", text)


class ServerFiles(unittest.TestCase):
    def test_the_server_hook_is_valid_sh(self):
        hook = SERVER / "hooks" / "normal" / "0100-dai-server.hook.chroot"
        subprocess.run(["sh", "-n", str(hook)], check=True)

    def test_every_unit_the_hook_enables_exists(self):
        hook = (SERVER / "hooks" / "normal" / "0100-dai-server.hook.chroot").read_text(encoding="utf-8")
        enabled = re.findall(r"systemctl enable (.+)", hook)
        names = " ".join(enabled).split()
        ours = {n for n in names if n.startswith("dai-")}
        self.assertTrue({"dai-ssh-hostkeys.service", "dai-aide-init.service", "dai-aide-check.timer"} <= ours)
        for name in ours:
            self.assertTrue((INCLUDES / "etc" / "systemd" / "system" / name).exists(), name)

    def test_units_have_the_sections_systemd_needs(self):
        for path in sorted((INCLUDES / "etc" / "systemd" / "system").glob("dai-*")):
            parser = configparser.ConfigParser(strict=False, interpolation=None)
            parser.read(path, encoding="utf-8")
            self.assertTrue(parser.has_section("Unit"), path.name)
            if path.suffix == ".service":
                self.assertTrue(parser.has_option("Service", "ExecStart"), path.name)
            if path.suffix == ".timer":
                self.assertTrue(parser.has_option("Timer", "OnCalendar"), path.name)

    def test_ssh_is_key_only_for_admins(self):
        text = (INCLUDES / "etc" / "ssh" / "sshd_config.d" / "10-dai-server.conf").read_text(encoding="utf-8")
        settings = dict(re.findall(r"^(\w+)\s+(.+)$", text, re.M))
        self.assertEqual(settings["PermitRootLogin"], "no")
        self.assertEqual(settings["PasswordAuthentication"], "no")
        self.assertEqual(settings["AllowGroups"], "dai-admin")
        values = " ".join(line for line in text.splitlines() if line.strip() and not line.startswith("#")).lower()
        for weak in ("cbc", "sha1", "3des", "arcfour", "-md5"):
            self.assertNotIn(weak, values, weak)  # comments may name them; the settings may not

    @unittest.skipUnless(shutil.which("sshd"), "sshd is not installed here (openssh-server)")
    def test_sshd_accepts_the_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            conf = Path(tmp) / "sshd_config"
            conf.write_text("Include " + str(INCLUDES / "etc" / "ssh" / "sshd_config.d" / "10-dai-server.conf") + "\n")
            subprocess.run(["sshd", "-t", "-f", str(conf)], check=True)

    def test_the_admin_hosts_file_is_comments_only(self):
        lines = (INCLUDES / "etc" / "dai" / "admin-hosts.nft").read_text(encoding="utf-8").splitlines()
        self.assertTrue(all(line.startswith("#") or not line.strip() for line in lines),
                        "until the install fills it, nobody is listed")

    @unittest.skipUnless(shutil.which("nft"), "nft is not installed here")
    def test_the_firewall_parses(self):
        with tempfile.TemporaryDirectory() as tmp:
            etc_dai = Path(tmp) / "dai"
            etc_dai.mkdir()
            (etc_dai / "firewall-allow.nft").write_text("# none\n")
            (etc_dai / "admin-hosts.nft").write_text(
                (INCLUDES / "etc" / "dai" / "admin-hosts.nft").read_text(encoding="utf-8"))
            text = (INCLUDES / "etc" / "nftables.conf").read_text(encoding="utf-8")
            text = text.replace("/etc/dai/", str(etc_dai) + "/")
            conf = Path(tmp) / "nftables.conf"
            conf.write_text(text)
            result = subprocess.run(["nft", "-c", "-f", str(conf)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_firewall_is_default_deny_with_ssh_from_admins_only(self):
        text = (INCLUDES / "etc" / "nftables.conf").read_text(encoding="utf-8")
        self.assertIn("policy drop", text)
        self.assertRegex(text, r"ip saddr @admin_ssh tcp dport 22 ct state new limit rate \d+/minute accept")
        self.assertNotRegex(text, r"tcp dport 22 accept")  # no SSH rule without the admin list

    def test_audit_rules_are_well_formed_and_enabled(self):
        rules = [line for line in (INCLUDES / "etc" / "audit" / "rules.d" / "90-dai-server.rules")
                 .read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
        for rule in rules:
            self.assertRegex(rule, r"^-(D|b \d+|f \d|w |a |e \d)", rule)
            if rule.startswith(("-w ", "-a ")):
                self.assertIn(" -k ", rule, rule)  # every rule has a key for the review
        self.assertEqual(rules[-1], "-e 1")  # enabled, not locked until reboot (a decision of the organisation)

    def test_aide_paths_match_the_units(self):
        conf = (INCLUDES / "etc" / "aide" / "dai-server.conf").read_text(encoding="utf-8")
        self.assertIn("database_in=file:/var/lib/aide/aide.db", conf)
        self.assertIn("database_out=file:/var/lib/aide/aide.db.new", conf)
        unit = (INCLUDES / "etc" / "systemd" / "system" / "dai-aide-init.service").read_text(encoding="utf-8")
        self.assertIn("mv -f /var/lib/aide/aide.db.new /var/lib/aide/aide.db", unit)
        self.assertIn("--config=/etc/aide/dai-server.conf", unit)

    def test_fail2ban_bans_ssh(self):
        text = (INCLUDES / "etc" / "fail2ban" / "jail.d" / "dai-server.conf").read_text(encoding="utf-8")
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(text)
        self.assertEqual(parser["sshd"]["enabled"], "true")

    def test_logs_keep_a_stated_retention(self):
        text = (INCLUDES / "etc" / "systemd" / "journald.conf.d" / "dai-server.conf").read_text(encoding="utf-8")
        self.assertIn("MaxRetentionSec=90day", text)
        self.assertIn("placeholder", text)  # the number is not advice (docs/SERVER.md §7)

    def test_updates_are_security_only_and_never_reboot(self):
        text = (INCLUDES / "etc" / "apt" / "apt.conf.d" / "52dai-server-updates").read_text(encoding="utf-8")
        self.assertIn("-security", text)
        self.assertIn('Automatic-Reboot "false"', text)

    def test_sudo_is_logged(self):
        text = (INCLUDES / "etc" / "sudoers.d" / "10-dai-server").read_text(encoding="utf-8")
        self.assertIn('Defaults logfile="/var/log/sudo.log"', text)


if __name__ == "__main__":
    unittest.main()
