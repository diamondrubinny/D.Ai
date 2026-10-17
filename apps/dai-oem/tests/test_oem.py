# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
import io
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from dai_oem import cli, helper
from dai_oem.core import (
    LUKS_KEY, SDDM_BACKUP, SDDM_CONF, SESSION_FILE, SESSION_TEMPLATE, SETUP_USER, STATE_FILE, Machine, OemError, Owner,
    suggest_username, validation_errors,
)

PASSWD = """root:x:0:0:root:/root:/bin/bash
sddm:x:108:115:Simple Desktop Display Manager:/var/lib/sddm:/bin/false
oem:x:1000:1000:Partner:/home/oem:/bin/bash
"""
GROUP = """root:x:0:
sudo:x:27:oem
audio:x:29:oem
video:x:44:oem
users:x:100:
lpadmin:x:120:oem
oem:x:1000:
"""
TEMP_LUKS = "temporary-luks-1"


class FakeSystem:
    """Records commands and simulates the few whose effects later steps read."""

    def __init__(self, root: Path, luks_password=TEMP_LUKS):
        self.root = root
        self.calls: list[tuple[list[str], str | None]] = []
        self.luks_password = luks_password
        self.fail = set()

    def __call__(self, argv, data=None):
        argv = list(argv)
        self.calls.append((argv, data))
        code = 1 if argv[0] in self.fail else 0
        passwd = self.root / "etc/passwd"
        if argv[0] == "useradd" and not code:
            uid = 999 if "--system" in argv else 1001
            passwd.write_text(passwd.read_text() + f"{argv[-1]}:x:{uid}:{uid}::/home/{argv[-1]}:/bin/sh\n")
        if argv[0] == "userdel" and not code:
            passwd.write_text("".join(l + "\n" for l in passwd.read_text().splitlines() if not l.startswith(argv[-1] + ":")))
        if argv[:3] == ["cryptsetup", "open", "--test-passphrase"]:
            code = 0 if data == self.luks_password + "\n" else 2
        if argv[:2] == ["cryptsetup", "luksChangeKey"] and not code:
            old = Path(argv[argv.index("--key-file") + 1]).read_text()
            if old != self.luks_password:
                code = 2
            else:
                self.luks_password = Path(argv[-1]).read_text()
        return subprocess.CompletedProcess(argv, code, stdout="", stderr="simulated failure" if code else "")

    def commands(self):
        return [argv[0] for argv, _ in self.calls]


class OemTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for path, content in {"etc/passwd": PASSWD, "etc/group": GROUP, "etc/machine-id": "0123456789abcdef\n",
                              "etc/hosts": "127.0.0.1\tlocalhost\n127.0.1.1\toem-bench\n", "etc/ssh/ssh_host_ed25519_key": "k",
                              "etc/sddm.conf": "[Theme]\nCurrent=dai\n",
                              SESSION_TEMPLATE.lstrip("/"): "[Desktop Entry]\nExec=labwc -C /usr/share/dai/oem/labwc\n"}.items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        self.system = FakeSystem(self.root)
        self.machine = Machine(root=self.root, runner=self.system, clock=lambda: 1_800_000_000)

    def encrypted(self):
        (self.root / "etc/crypttab").write_text("# <name> <device> <key> <options>\n"
                                                "luks-abc UUID=1234-abcd none luks,discard\n")

    def owner(self, **changes):
        fields = dict(full_name="Dana Levi", username="dana", password="correct horse 9", hostname="dana-pc",
                      luks_password=None, language="he")
        fields.update(changes)
        return Owner(**fields)

    def read(self, path):
        return (self.root / path.lstrip("/")).read_text()


class ValidationTests(unittest.TestCase):
    def test_fields(self):
        good = Owner("דנה לוי", "dana", "12345678", "dana-pc")
        self.assertEqual(validation_errors(good, set(), needs_luks=False), [])
        self.assertEqual(validation_errors(good, set(), needs_luks=True), ["luks_password"])
        for owner, key in ((Owner("Dana:x", "dana", "12345678", "pc"), "full_name"),
                           (Owner("Dana\n", "dana", "12345678", "pc"), "full_name"),
                           (Owner("Dana", "Dana", "12345678", "pc"), "username"),
                           (Owner("Dana", "root", "12345678", "pc"), "username"),
                           (Owner("Dana", "9lives", "12345678", "pc"), "username"),
                           (Owner("Dana", "dana", "short", "pc"), "password"),
                           (Owner("Dana", "dana", "line\nbreak", "pc"), "password"),
                           (Owner("Dana", "dana", "12345678", "-pc"), "hostname"),
                           (Owner("Dana", "dana", "12345678", "pc_1"), "hostname"),
                           (Owner("Dana", "dana", "12345678", "pc", language="fr"), "language")):
            with self.subTest(owner=owner):
                self.assertIn(key, validation_errors(owner, set(), needs_luks=False))
        self.assertIn("username", validation_errors(good, {"dana"}, needs_luks=False))

    def test_suggest_username(self):
        self.assertEqual(suggest_username("Dana Levi"), "dana")
        self.assertEqual(suggest_username("דנה לוי"), "")
        self.assertEqual(suggest_username("Root"), "")


class PrepareTests(OemTestCase):
    def test_plain_disk(self):
        state = self.machine.prepare("oem")
        self.assertEqual(state, {"phase": "pending", "remove_users": ["oem"], "luks": None, "prepared": 1_800_000_000})
        self.assertIn(f"User={SETUP_USER}", self.read(SDDM_CONF))
        self.assertIn("Session=dai-oem.desktop", self.read(SDDM_CONF))
        self.assertEqual(self.read(SDDM_BACKUP), "[Theme]\nCurrent=dai\n")
        self.assertIn("labwc -C", self.read(SESSION_FILE))
        self.assertEqual(self.read("/etc/machine-id"), "")
        self.assertFalse((self.root / "etc/ssh/ssh_host_ed25519_key").exists())
        self.assertIn(SETUP_USER, self.machine.users())
        self.assertIn("apt-get", self.system.commands())
        self.assertFalse((self.root / LUKS_KEY.lstrip("/")).exists())
        self.assertEqual(stat.S_IMODE((self.root / STATE_FILE.lstrip("/")).stat().st_mode), 0o644)

    def test_encrypted_disk_checks_and_keeps_the_temporary_password(self):
        self.encrypted()
        with self.assertRaisesRegex(OemError, "temporary disk encryption password"):
            self.machine.prepare("oem")
        with self.assertRaisesRegex(OemError, "cryptsetup failed"):
            self.machine.prepare("oem", "wrong password")
        state = self.machine.prepare("oem", TEMP_LUKS)
        self.assertEqual(state["luks"], "/dev/disk/by-uuid/1234-abcd")
        key = self.root / LUKS_KEY.lstrip("/")
        self.assertEqual(key.read_text(), TEMP_LUKS)  # no newline: a key file is read as is
        self.assertEqual(stat.S_IMODE(key.stat().st_mode), 0o600)
        self.assertNotIn(TEMP_LUKS, " ".join(self.machine.log))  # never on a command line

    def test_refusals(self):
        (self.root / "run/live").mkdir(parents=True)
        with self.assertRaisesRegex(OemError, "live session"):
            self.machine.prepare("oem")
        for user in ("root", "sddm", "nobody-here", SETUP_USER):
            with self.subTest(user=user), self.assertRaisesRegex(OemError, "not a regular user"):
                self.machine.prepare(user, allow_live=True)
        self.machine.prepare("oem", allow_live=True)
        with self.assertRaisesRegex(OemError, "already prepared"):
            self.machine.prepare("oem", allow_live=True)
        (self.root / "etc/crypttab").write_text("a UUID=1 none luks\nb UUID=2 none luks\n")
        self.machine.cancel()
        with self.assertRaisesRegex(OemError, "more than one encrypted disk"):
            self.machine.prepare("oem", "x", allow_live=True)

    def test_cancel_restores_everything(self):
        self.encrypted()
        self.machine.prepare("oem", TEMP_LUKS)
        self.machine.cancel()
        self.assertEqual(self.read(SDDM_CONF), "[Theme]\nCurrent=dai\n")
        self.assertFalse((self.root / SESSION_FILE.lstrip("/")).exists())
        self.assertFalse((self.root / LUKS_KEY.lstrip("/")).exists())
        self.assertNotIn(SETUP_USER, self.machine.users())
        self.assertEqual(self.machine.state(), {})
        with self.assertRaisesRegex(OemError, "nothing to cancel"):
            self.machine.cancel()


class CompleteTests(OemTestCase):
    def test_new_owner_plain_disk(self):
        self.machine.prepare("oem")
        self.machine.complete(self.owner())
        useradd = next(argv for argv, _ in self.system.calls if argv[0] == "useradd" and argv[-1] == "dana")
        groups = useradd[useradd.index("--groups") + 1].split(",")
        self.assertIn("sudo", groups)
        self.assertIn("lpadmin", groups)  # what the partner's user had
        self.assertNotIn("oem", groups)
        self.assertIn(("chpasswd", "dana:correct horse 9\n"), [(a[0], d) for a, d in self.system.calls])
        self.assertNotIn("correct horse 9", " ".join(self.machine.log))
        self.assertEqual(self.read("/etc/hostname"), "dana-pc\n")
        self.assertIn("127.0.1.1\tdana-pc", self.read("/etc/hosts"))
        self.assertNotIn("oem-bench", self.read("/etc/hosts"))
        self.assertEqual(self.read(SDDM_CONF), "[Theme]\nCurrent=dai\n")
        self.assertFalse((self.root / SESSION_FILE.lstrip("/")).exists())
        self.assertEqual(self.machine.state()["phase"], "cleanup")
        with self.assertRaisesRegex(OemError, "no setup waiting"):
            self.machine.complete(self.owner(username="dana2"))

    def test_encrypted_disk_gets_the_new_password_first(self):
        self.encrypted()
        self.machine.prepare("oem", TEMP_LUKS)
        with self.assertRaisesRegex(OemError, "luks_password"):
            self.machine.complete(self.owner())
        self.machine.complete(self.owner(luks_password="my own disk key"))
        self.assertEqual(self.system.luks_password, "my own disk key")
        order = self.system.commands()
        self.assertLess(order.index("cryptsetup"), order.index("chpasswd"))
        self.assertFalse((self.root / LUKS_KEY.lstrip("/")).exists())
        self.assertFalse(any((self.root / "run/dai-oem").iterdir()))  # the new key file is gone too
        self.assertNotIn("my own disk key", " ".join(self.machine.log))

    def test_failure_after_the_encryption_step_can_be_retried(self):
        self.encrypted()
        self.machine.prepare("oem", TEMP_LUKS)
        self.system.fail.add("chpasswd")
        with self.assertRaises(OemError):
            self.machine.complete(self.owner(luks_password="my own disk key"))
        self.assertTrue(self.machine.state()["luks_done"])
        self.system.fail.clear()
        (self.root / "etc/passwd").write_text(PASSWD + f"{SETUP_USER}:x:999:999::/x:/bin/sh\n")  # useradd rolled back
        self.machine.complete(self.owner(luks_password=None))  # not asked again
        self.assertEqual(self.system.luks_password, "my own disk key")
        self.assertEqual(self.machine.state()["phase"], "cleanup")

    def test_invalid_owner_changes_nothing(self):
        self.machine.prepare("oem")
        before = len(self.system.calls)
        for owner in (self.owner(username="oem"), self.owner(username="root"), self.owner(hostname="bad host")):
            with self.subTest(owner=owner), self.assertRaisesRegex(OemError, "invalid"):
                self.machine.complete(owner)
        self.assertEqual(len(self.system.calls), before)

    def test_missing_command_is_a_failure_not_a_crash(self):
        def runner(argv, data=None):
            if argv[0] == "ssh-keygen":
                raise FileNotFoundError(argv[0])
            return self.system(argv, data)
        self.machine.runner = runner
        self.machine.prepare("oem")
        self.machine.complete(self.owner())
        self.assertTrue(self.machine.cleanup())
        with self.assertRaisesRegex(OemError, "not installed"):
            self.machine.run(["ssh-keygen", "-A"])

    def test_cleanup_at_next_boot(self):
        self.assertFalse(self.machine.cleanup())  # nothing pending: the service does nothing
        self.machine.prepare("oem")
        self.machine.complete(self.owner())
        self.assertTrue(self.machine.cleanup())
        users = self.machine.users()
        self.assertNotIn("oem", users)
        self.assertNotIn(SETUP_USER, users)
        self.assertIn("dana", users)
        self.assertIn(["ssh-keygen", "-A"], [argv for argv, _ in self.system.calls])
        self.assertEqual(self.machine.state(), {})


class HelperTests(OemTestCase):
    def call(self, argv, stdin="", env=None):
        out = io.StringIO()
        with mock.patch("os.geteuid", return_value=0), mock.patch.dict(os.environ, env or {}, clear=False), \
                mock.patch("sys.stdin", io.StringIO(stdin)), redirect_stdout(out), mock.patch("syslog.syslog"):
            if env is None:
                os.environ.pop("PKEXEC_UID", None)
            with mock.patch("os.getuid", return_value=0):
                code = helper.main(argv, machine=self.machine)
        return code, json.loads(out.getvalue())

    def test_caller_must_be_the_setup_user(self):
        self.machine.prepare("oem")
        with mock.patch("pwd.getpwuid", return_value=mock.Mock(pw_name="mallory")):
            code, reply = self.call(["h", "complete"], json.dumps(self.owner().__dict__), env={"PKEXEC_UID": "1002"})
        self.assertEqual((code, reply["ok"]), (1, False))
        self.assertIn("only the first-boot setup", reply["error"])
        with mock.patch("pwd.getpwuid", return_value=mock.Mock(pw_name=SETUP_USER)):
            code, reply = self.call(["h", "complete"], json.dumps(self.owner().__dict__), env={"PKEXEC_UID": "999"})
        self.assertEqual(reply, {"ok": True})

    def test_input_is_checked(self):
        self.machine.prepare("oem")
        for stdin in ("not json", "[]", json.dumps({**self.owner().__dict__, "extra": 1}),
                      json.dumps({**self.owner().__dict__, "password": 5}), "x" * 9000):
            with self.subTest(stdin=stdin[:30]):
                code, reply = self.call(["h", "complete"], stdin)
                self.assertFalse(reply["ok"])
        self.assertEqual(self.machine.state()["phase"], "pending")

    def test_reboot_only_after_finishing(self):
        self.machine.prepare("oem")
        self.assertFalse(self.call(["h", "reboot"])[1]["ok"])
        self.call(["h", "complete"], json.dumps(self.owner().__dict__))
        self.assertTrue(self.call(["h", "reboot"])[1]["ok"])
        self.assertIn(["systemctl", "reboot"], [argv for argv, _ in self.system.calls])


class CliTests(OemTestCase):
    def run_cli(self, *args, answer="y", password=TEMP_LUKS):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), mock.patch.dict(os.environ, {"LANG": "en_US.UTF-8"}):
            code = cli.main(["dai-oem", *args], machine=self.machine, ask=lambda _p: answer, secret=lambda _p: password)
        return code, out.getvalue() + err.getvalue()

    def test_prepare_status_cancel(self):
        self.assertIn("Diamond Rubinny (d.Ai)", self.run_cli("--version")[1])
        self.assertIn("Not prepared", self.run_cli("status")[1])
        code, out = self.run_cli("prepare", "--remove-user", "oem", answer="n")
        self.assertEqual(code, 1)
        self.assertIn("temporary user oem", out)
        code, out = self.run_cli("prepare", "--remove-user", "oem")
        self.assertEqual(code, 0, out)
        self.assertIn("Power off", out)
        self.assertIn("Prepared", self.run_cli("status")[1])
        self.assertIn("Cancelled", self.run_cli("cancel")[1])

    def test_encrypted_prepare_asks_for_the_password(self):
        self.encrypted()
        code, out = self.run_cli("prepare", "--remove-user", "oem", "--yes", password="nope")
        self.assertEqual(code, 1)
        self.assertIn("cryptsetup failed", out)
        code, out = self.run_cli("prepare", "--remove-user", "oem", "--yes")
        self.assertEqual(code, 0, out)
        self.assertIn("temporary encryption password once", out)


@unittest.skipUnless(os.geteuid() == 0 and shutil.which("cryptsetup"), "needs root and cryptsetup (CI runs it with sudo)")
class RealCryptsetupTests(unittest.TestCase):
    """The exact cryptsetup commands, against a real LUKS2 header in an image file."""

    def test_temporary_password_is_replaced(self):
        from dai_oem.core import run_command

        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "disk.img"
            with open(image, "wb") as handle:
                handle.truncate(32 * 1024 * 1024)
            subprocess.run(["cryptsetup", "luksFormat", "--batch-mode", "--type", "luks2", "--pbkdf", "argon2id",
                            "--pbkdf-memory", "32768", "--pbkdf-force-iterations", "4", "--key-file=-", str(image)],
                           input=TEMP_LUKS.encode(), check=True, capture_output=True)
            root = Path(tmp) / "root"
            (root / "etc").mkdir(parents=True)
            (root / "etc/passwd").write_text(PASSWD)
            (root / "etc/crypttab").write_text(f"luks-x {image} none luks\n")
            template = root / SESSION_TEMPLATE.lstrip("/")
            template.parent.mkdir(parents=True)
            template.write_text("[Desktop Entry]\n")
            fake = FakeSystem(root)

            def runner(argv, data=None):  # only cryptsetup is real here
                return run_command(argv, data) if argv[0] == "cryptsetup" else fake(argv, data)

            machine = Machine(root=root, runner=runner)
            with self.assertRaisesRegex(OemError, "No key available"):
                machine.prepare("oem", "wrong password")
            machine.prepare("oem", TEMP_LUKS)
            machine.complete(Owner("Dana", "dana", "correct horse 9", "dana-pc", "סיסמה חדשה לדיסק 2026"))
            test = ["cryptsetup", "open", "--test-passphrase", str(image)]
            # Read like the boot prompt reads it: up to the newline.
            self.assertEqual(run_command(test, "סיסמה חדשה לדיסק 2026\n").returncode, 0)
            self.assertNotEqual(run_command(test, TEMP_LUKS + "\n").returncode, 0)
            self.assertFalse((root / LUKS_KEY.lstrip("/")).exists())


try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # PyQt6 is in the image; CI installs it for these tests
    QApplication = None


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class WizardTests(OemTestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def make(self, encrypted=False):
        from dai_oem.wizard import SetupWindow

        if encrypted:
            self.encrypted()
        self.machine.prepare("oem", TEMP_LUKS if encrypted else None)
        self.sent, self.restarted = [], []

        def finisher(owner):
            self.sent.append(owner)
            self.machine.complete(owner)
            return {"ok": True}
        window = SetupWindow(self.machine, finisher=finisher, restarter=lambda: self.restarted.append(True))
        self.addCleanup(window.close)
        return window

    def fill(self, window):
        window.choose_language("he")
        window.full_name.setText("Dana Levi")
        window._suggest("Dana Levi")
        window.password.setText("correct horse 9")
        window.password2.setText("correct horse 9")

    def test_hebrew_flow(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest

        window = self.make()
        self.fill(window)
        self.assertEqual(window.layoutDirection(), Qt.LayoutDirection.RightToLeft)
        self.assertEqual((window.username.text(), window.hostname.text()), ("dana", "dana-pc"))
        window.password2.setText("different")
        window.next()
        self.assertEqual(window.pages.currentIndex(), 1)
        self.assertIn("לא זהות", window.error.text())
        window.password2.setText("correct horse 9")
        window.next()  # → computer
        window.next()  # → summary (no encryption page)
        self.assertEqual(window.pages.currentIndex(), window.summary_page)
        self.assertIn("dana-pc", window.summary_label.text())
        window.next()  # finish
        QTest.qWait(300)
        self.assertEqual(self.sent[0].username, "dana")
        self.assertEqual(self.machine.state()["phase"], "cleanup")
        QTest.qWait(3200)
        self.assertEqual(self.restarted, [True])

    def test_encryption_page_needs_matching_passwords_and_acknowledgement(self):
        window = self.make(encrypted=True)
        self.fill(window)
        window.next()
        window.next()
        self.assertEqual(window.pages.currentIndex(), window.luks_page)
        window.luks1.setText("my own disk key")
        window.luks2.setText("my own disk key")
        window.next()
        self.assertEqual(window.pages.currentIndex(), window.luks_page)  # not acknowledged
        window.luks_ack.setChecked(True)
        window.next()
        self.assertEqual(window.pages.currentIndex(), window.summary_page)

    def test_failure_returns_to_the_summary(self):
        from PyQt6.QtTest import QTest

        window = self.make()
        window.finisher = lambda owner: {"ok": False, "error": "useradd failed"}
        self.fill(window)
        window.next()
        window.next()
        window.next()
        QTest.qWait(300)
        self.assertEqual(window.pages.currentIndex(), window.summary_page)
        self.assertIn("useradd failed", window.error.text())


if __name__ == "__main__":
    unittest.main()
