# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from dai_clip import cli
from dai_clip.secrets import classify, israeli_id_ok, luhn_ok, marked_sensitive
from dai_clip.store import KEEP_SECONDS, MAX_ITEMS, History, is_off, runtime_dir, set_off
from dai_clip.text import preview


class Clock:
    def __init__(self, now=1_800_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


class SecretTests(unittest.TestCase):
    def kind(self, text):
        verdict = classify(text)
        return verdict.kind if verdict else None

    def test_ordinary_text_is_kept(self):
        for text in ("שלום, מה שלומך?", "Hello world", "https://www.debian.org/releases/trixie/",
                     "/home/dana/Documents/report.pdf", "dana@example.com", "Report_2024-Final.pdf",
                     "def add(a, b):\n    return a + b\n", "sudo apt install restic", "0521234567",
                     "12,345.67", "D.Ai OS", "os.path.join", "password", "פגישה מחר ב־10:30 בתל אביב",
                     "github.com/diamondrubinny/D.Ai"):
            self.assertIsNone(classify(text), text)

    def test_keys_and_tokens(self):
        self.assertEqual(self.kind("-----BEGIN OPENSSH PRIVATE KEY-----\nb3Blbn\n-----END OPENSSH PRIVATE KEY-----"),
                         "private-key")
        self.assertEqual(self.kind("-----BEGIN PGP PRIVATE KEY BLOCK-----"), "private-key")
        for token in ("sk-proj-" + "a1B2" * 8, "ghp_" + "A1b2C3d4" * 5, "github_pat_" + "x1Y2_" * 10,
                      "glpat-" + "abcDEF123456" * 2, "xoxb-1234567890-abcdef", "AKIA" + "ABCDEFGHIJ123456",
                      "AIza" + "Sy" + "A1b2C3d4E5" * 3 + "abc",
                      "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"):
            verdict = classify(f"export KEY={token}")
            self.assertIsNotNone(verdict, token)
            self.assertTrue(verdict.clear, token)
        self.assertEqual(self.kind("DB_PASSWORD=hunter2hunter2"), "password-assignment")
        self.assertEqual(self.kind('"api_key": "abcd1234"'), "password-assignment")
        self.assertEqual(self.kind("הסיסמה: Tel-Aviv-2026"), "password-assignment")

    def test_numbers(self):
        self.assertTrue(luhn_ok("4111111111111111"))
        self.assertFalse(luhn_ok("4111111111111112"))
        self.assertEqual(self.kind("4111 1111 1111 1111"), "card")
        self.assertEqual(self.kind("4111-1111-1111-1111"), "card")
        self.assertIsNone(classify("4111 1111 1111 1112"))  # not a card number
        self.assertTrue(israeli_id_ok("000000018"))
        self.assertEqual(self.kind("000000018"), "id-number")
        self.assertEqual(self.kind("00000001-8"), "id-number")
        self.assertIsNone(classify("000000019"))
        code = classify("482913")
        self.assertEqual((code.kind, code.clear), ("one-time-code", False))

    def test_password_like_is_a_guess_without_clearing(self):
        verdict = classify("Tr0ub4dor&3")
        self.assertEqual((verdict.kind, verdict.clear), ("password-like", False))
        self.assertEqual(self.kind("correct-Horse-7"), "password-like")
        self.assertIsNone(classify("correct horse battery staple"))  # spaces: prose, not a password
        self.assertIsNone(classify("שלום-עולם-2026"))

    def test_password_manager_marker(self):
        self.assertTrue(marked_sensitive(None, ["text/plain", "x-kde-passwordManagerHint"]))
        self.assertTrue(marked_sensitive("sensitive", ["text/plain"]))
        self.assertFalse(marked_sensitive("data", ["text/plain;charset=utf-8", "TEXT"]))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = {"XDG_RUNTIME_DIR": self.tmp.name, "HOME": self.tmp.name}
        self.folder = runtime_dir(self.env)
        self.clock = Clock()
        self.history = History(self.folder, clock=self.clock)

    def test_private_folder_and_file(self):
        self.assertEqual(stat.S_IMODE(os.stat(self.folder).st_mode), 0o700)
        self.history.add("hello")
        self.assertEqual(stat.S_IMODE(os.stat(self.folder / "history.json").st_mode), 0o600)

    def test_no_runtime_dir_means_nothing_is_kept(self):
        self.assertIsNone(runtime_dir({}))

    def test_symlinked_folder_is_refused(self):
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        base = Path(self.tmp.name) / "run"
        base.mkdir()
        (base / "dai-clip").symlink_to(other.name)
        self.assertIsNone(runtime_dir({"XDG_RUNTIME_DIR": str(base)}))

    def test_newest_first_without_duplicates(self):
        for text in ("one", "two", "one"):
            self.clock.now += 1
            self.history.add(text)
        self.assertEqual([i.text for i in self.history.items()], ["one", "two"])

    def test_limits(self):
        for n in range(MAX_ITEMS + 5):
            self.history.add(f"item {n}")
        items = self.history.items()
        self.assertEqual(len(items), MAX_ITEMS)
        self.assertEqual(items[0].text, f"item {MAX_ITEMS + 4}")
        self.assertFalse(self.history.add("   \n"))
        self.assertFalse(self.history.add("x" * 100_001))

    def test_old_items_expire(self):
        self.history.add("old")
        self.clock.now += KEEP_SECONDS + 1
        self.history.add("new")
        self.assertEqual([i.text for i in self.history.items()], ["new"])

    def test_remove_and_clear(self):
        self.history.add("a")
        self.history.add("b")
        self.history.remove("a")
        self.assertEqual([i.text for i in self.history.items()], ["b"])
        self.history.clear()
        self.assertEqual(self.history.items(), [])

    def test_damaged_file_starts_again(self):
        (self.folder / "history.json").write_text("{not json")
        self.assertEqual(self.history.items(), [])
        (self.folder / "history.json").write_text(json.dumps([{"text": 5, "time": "x"}, "junk",
                                                              {"text": "ok", "time": self.clock.now}]))
        self.assertEqual([i.text for i in self.history.items()], ["ok"])

    def test_history_symlink_is_not_followed(self):
        target = Path(self.tmp.name) / "elsewhere.json"
        target.write_text(json.dumps([{"text": "planted", "time": self.clock.now}]))
        (self.folder / "history.json").symlink_to(target)
        self.assertEqual(self.history.items(), [])

    def test_pause_and_off(self):
        self.history.pause(10)
        self.assertIsNotNone(self.history.paused_until())
        self.clock.now += 601
        self.assertIsNone(self.history.paused_until())
        self.history.pause(1)
        self.history.resume()
        self.assertIsNone(self.history.paused_until())
        self.assertFalse(is_off(self.env))
        set_off(True, self.env)
        self.assertTrue(is_off(self.env))
        set_off(False, self.env)
        self.assertFalse(is_off(self.env))


class StoreCommandTests(StoreTests):
    """What `wl-paste --watch dai-clip _store` does with each clipboard change."""

    TEXT_TYPES = ["text/plain;charset=utf-8", "text/plain", "UTF8_STRING"]

    def run_store(self, data, state="data", types=None):
        return cli.store(data, state, lambda: self.TEXT_TYPES if types is None else types, self.history, self.env)

    def texts(self):
        return [i.text for i in self.history.items()]

    def test_text_is_kept(self):
        self.assertEqual(self.run_store("שלום עולם".encode()), ("stored", None))
        self.assertEqual(self.texts(), ["שלום עולם"])

    def test_password_manager_copy_is_not_kept(self):
        self.assertEqual(self.run_store(b"s3cr3t-Pass", types=self.TEXT_TYPES + ["x-kde-passwordManagerHint"])[0],
                         "sensitive")
        self.assertEqual(self.run_store(b"anything", state="sensitive")[0], "sensitive")
        self.assertEqual(self.run_store(b"anything", types=[])[0], "stored")
        self.assertEqual(self.texts(), ["anything"])

    def test_unknown_types_fail_closed(self):
        outcome, _ = cli.store(b"hello", "data", lambda: None, self.history, self.env)
        self.assertEqual(outcome, "sensitive")
        self.assertEqual(self.texts(), [])

    def test_secrets_binary_and_empty(self):
        outcome, verdict = self.run_store(b"ghp_" + b"A1b2C3d4" * 5)
        self.assertEqual((outcome, verdict.kind, verdict.clear), ("secret", "token", True))
        self.assertEqual(self.run_store(b"\xff\xfe\x00")[0], "binary")
        self.assertEqual(self.run_store(b"a\x00b")[0], "binary")
        self.assertEqual(self.run_store(b"", state="nil")[0], "empty")
        self.assertEqual(self.run_store(b"", state="clear")[0], "empty")
        self.assertEqual(self.run_store(b"x" * (cli.MAX_INPUT_BYTES + 1))[0], "too-large")
        self.assertEqual(self.texts(), [])

    def test_paused_off_and_no_runtime(self):
        self.history.pause(5)
        self.assertEqual(self.run_store(b"hello")[0], "paused")
        self.history.resume()
        set_off(True, self.env)
        self.assertEqual(self.run_store(b"hello")[0], "off")
        set_off(False, self.env)
        self.assertEqual(cli.store(b"hello", "data", lambda: self.TEXT_TYPES, None, self.env)[0], "no-runtime")
        self.assertEqual(self.texts(), [])

    def test_offered_types(self):
        result = mock.Mock(returncode=0, stdout="text/plain\nx-kde-passwordManagerHint\n")
        self.assertEqual(cli.offered_types(lambda *a, **k: result), ["text/plain", "x-kde-passwordManagerHint"])
        self.assertIsNone(cli.offered_types(lambda *a, **k: mock.Mock(returncode=1, stdout="")))

        def missing(*_a, **_k):
            raise FileNotFoundError("wl-paste")
        self.assertIsNone(cli.offered_types(missing))


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.tmp.name, "XDG_CONFIG_HOME": self.tmp.name,
                                               "LANG": "en_US.UTF-8"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_cli(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.main(["dai-clip", *args])
        return code, out.getvalue()

    def test_version_and_credit(self):
        self.assertIn("Diamond Rubinny (d.Ai)", self.run_cli("--version")[1])

    def test_list_clear_pause_off(self):
        History(runtime_dir()).add("hello from the clipboard")
        code, out = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("hello from the clipboard", out)
        self.assertEqual(json.loads(self.run_cli("list", "--json")[1])[0]["text"], "hello from the clipboard")
        self.assertIn("1 items", self.run_cli("status")[1])
        self.assertIn("until", self.run_cli("pause", "5")[1])
        self.assertIn("Paused", self.run_cli("status")[1])
        self.run_cli("resume")
        self.assertIn("cleared", self.run_cli("clear")[1])
        self.assertIn("Nothing here yet", self.run_cli("list")[1])
        History(runtime_dir()).add("again")
        self.run_cli("off")
        self.assertIn("Off", self.run_cli("status")[1])
        self.assertEqual(History(runtime_dir()).items(), [])
        self.run_cli("on")
        self.assertIn("On", self.run_cli("status")[1])

    def test_watch_needs_wayland(self):
        with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": ""}), mock.patch("os.execvp") as execvp:
            self.assertEqual(cli.main(["dai-clip", "watch"]), 1)
        execvp.assert_not_called()
        with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0"}), \
                mock.patch("shutil.which", return_value="/usr/bin/wl-paste"), mock.patch("os.execvp") as execvp:
            cli.main(["dai-clip", "watch"])
        execvp.assert_called_once_with("wl-paste", ["wl-paste", "--type", "text", "--watch", "dai-clip", "_store"])

    def test_watch_reopens_closed_std_fds(self):
        code = ("import os, sys; sys.path.insert(0, %r); from dai_clip.cli import ensure_std_fds; "
                "ensure_std_fds(); os.execvp('sh', ['sh', '-c', 'test -e /proc/self/fd/0 && echo OPEN'])") % str(Path(cli.__file__).parent.parent)
        result = subprocess.run([sys.executable, "-c", code], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                preexec_fn=lambda: os.close(0))
        self.assertEqual(result.stdout.strip(), "OPEN", result.stderr)

    def test_store_never_prints_the_content(self):
        stdin = mock.Mock()
        stdin.buffer = io.BytesIO(b"ghp_" + b"A1b2C3d4" * 5)
        err = io.StringIO()
        with mock.patch("sys.stdin", stdin), mock.patch("sys.stderr", err), \
                mock.patch.dict(os.environ, {"CLIPBOARD_STATE": "data", "DAI_CLIP_DEBUG": "1"}), \
                mock.patch.object(cli, "offered_types", return_value=["text/plain"]), \
                mock.patch.object(cli, "schedule_clear") as clear:
            self.assertEqual(cli.main(["dai-clip", "_store"]), 0)
        clear.assert_called_once()
        self.assertIn("secret token", err.getvalue())
        self.assertNotIn("ghp_", err.getvalue())
        self.assertEqual(History(runtime_dir()).items(), [])

    def test_preview(self):
        self.assertEqual(preview("\n\n  first line  \nsecond"), "first line")
        self.assertTrue(preview("x" * 200).endswith("…"))


class CommandTests(unittest.TestCase):
    def test_command_bar(self):
        try:
            from dai_command import core
        except ImportError:
            self.skipTest("dai_command not on the path")
        with mock.patch("shutil.which", return_value="/usr/bin/dai-clip"):
            for text in ("clipboard history", "what did I copy", "היסטוריית העתקות", "מה העתקתי היום?", "לוח העתקות"):
                rows = core.build_actions(text, [])
                self.assertEqual(rows[0].kind, "clip", text)
            for text in ("copy", "העתק", "היסטוריה", "firefox"):
                self.assertNotIn("clip", [row.kind for row in core.build_actions(text, [])], text)


try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtWidgets import QApplication
except ImportError:  # PyQt6 is in the image; CI installs it for these tests
    QApplication = None


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from dai_clip.gui import ClipWindow

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = Clock()
        self.history = History(runtime_dir({"XDG_RUNTIME_DIR": self.tmp.name}), clock=self.clock)
        for text in ("first copied", "def add(a, b):\n    return a + b", "שלום עולם"):
            self.clock.now += 120
            self.history.add(text)
        self.copied, self.pasted = [], []
        with mock.patch.dict(os.environ, {"LANG": "he_IL.UTF-8"}):
            self.window = ClipWindow(self.history, copier=self.copied.append,
                                     paster=lambda: self.pasted.append(True), clock=self.clock)
        self.window.keep_running = True
        self.addCleanup(self.window.close)

    def key(self, key, modifiers=Qt.KeyboardModifier.NoModifier):
        self.window.handle_key(QKeyEvent(QKeyEvent.Type.KeyPress, key, modifiers))

    def test_rtl_newest_first(self):
        self.assertEqual(self.window.layoutDirection(), Qt.LayoutDirection.RightToLeft)
        self.assertEqual(self.window.list.count(), 3)
        self.assertEqual(self.window.current_text(), "שלום עולם")
        from dai_clip.gui import META_ROLE
        self.assertIn("2 שורות", self.window.list.item(1).data(META_ROLE))
        self.assertEqual(self.window.list.item(1).text(), "\u202adef add(a, b):\u202c")

    def test_search_and_empty_state(self):
        self.window.search.setText("ADD(")
        self.assertEqual(self.window.list.count(), 1)
        self.window.search.setText("nothing like this")
        self.assertEqual(self.window.list.count(), 0)
        self.assertEqual(self.window.empty.text(), "אין תוצאות.")

    def test_enter_pastes_shift_enter_copies_only(self):
        self.key(Qt.Key.Key_Down)
        self.key(Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(self.copied, ["def add(a, b):\n    return a + b"])
        self.app.processEvents()
        self.assertEqual(self.pasted, [])
        self.key(Qt.Key.Key_Return)
        from PyQt6.QtTest import QTest

        QTest.qWait(400)
        self.assertEqual(len(self.copied), 2)
        self.assertEqual(self.pasted, [True])

    def test_delete_and_clear_all(self):
        self.window.list.setFocus()
        self.key(Qt.Key.Key_Delete)
        self.assertEqual([i.text for i in self.history.items()], ["def add(a, b):\n    return a + b", "first copied"])
        self.window.clear_all()
        self.assertEqual(self.window.list.count(), 0)
        self.assertIn("אף פעם לא סיסמאות", self.window.empty.text())
        self.assertFalse(self.window.clear_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
