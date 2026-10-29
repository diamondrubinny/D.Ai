# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""D.Ai Speak (docs/SPEAK.md): the voice follows the letters, the text goes through stdin, the pid file is
only trusted when /proc says espeak-ng, and the CLI with a fake wl-paste and a fake reader."""
import io
import os
import subprocess
import tempfile
import unittest
from unittest import mock
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from dai_speak import cli, engine


class FakeChild:
    def __init__(self, argv, pid=4242, returncode=0):
        self.argv, self.pid, self.returncode = argv, pid, returncode
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO()
        self.kwargs = {}
        self.written = b""
        real_close = self.stdin.close

        def close():
            self.written = self.stdin.getvalue()
            real_close()
        self.stdin.close = close

    def wait(self):
        return self.returncode


def fake_proc(tmp: Path, pid: int, comm: str) -> Path:
    (tmp / "proc" / str(pid)).mkdir(parents=True, exist_ok=True)
    (tmp / "proc" / str(pid) / "comm").write_text(comm + "\n")
    return tmp / "proc"


class EngineTests(unittest.TestCase):
    def test_the_voice_follows_the_letters_then_the_interface(self):
        self.assertEqual(engine.language_of("שלום עולם", "en"), "he")
        self.assertEqual(engine.language_of("مرحبا", "en"), "ar")
        self.assertEqual(engine.language_of("Привет", "he"), "ru")
        self.assertEqual(engine.language_of("Hello", "fr"), "fr")
        self.assertEqual(engine.language_of("Hello", "xx"), "en")
        self.assertEqual(engine.reader_argv("he", 160, sandbox=False), ["espeak-ng", "-v", "he", "-s", "160", "--stdin", "--stdout"])
        boxed = engine.reader_argv("en", 999, sandbox=True)
        self.assertEqual(boxed[0], "bwrap")
        self.assertEqual(boxed[-7:], ["espeak-ng", "-v", "en-us", "-s", "400", "--stdin", "--stdout"])
        for flag in ("--unshare-all", "--die-with-parent", "--cap-drop", "--clearenv", "--new-session"):
            self.assertIn(flag, boxed)
        self.assertNotIn("--share-net", boxed)
        self.assertNotIn(str(Path.home()), " ".join(boxed))
        self.assertEqual(engine.clamp_rate("abc"), engine.DEFAULT_RATE)
        self.assertEqual(engine.clamp_rate(10), engine.RATE_MIN)

    def test_settings_come_from_the_user_file_and_bad_values_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.assertEqual(engine.load_settings(home).rate, engine.DEFAULT_RATE)
            (home / engine.SETTINGS_FILE).parent.mkdir(parents=True)
            (home / engine.SETTINGS_FILE).write_text('{"rate": 220}')
            self.assertEqual(engine.load_settings(home).rate, 220)
            (home / engine.SETTINGS_FILE).write_text('[1, 2]')
            self.assertEqual(engine.load_settings(home).rate, engine.DEFAULT_RATE)
            (home / engine.SETTINGS_FILE).write_text('{"rate": "fast"}')
            self.assertEqual(engine.load_settings(home).rate, engine.DEFAULT_RATE)

    def test_the_pid_file_is_only_trusted_for_a_running_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            path = tmp / "speak.pid"
            self.assertIsNone(engine.running_reader(path))
            path.write_text("4242")
            proc = fake_proc(tmp, 4242, "bash")
            self.assertIsNone(engine.running_reader(path, proc))      # a foreign process is never ours
            killed = []
            self.assertFalse(engine.stop(path, proc, kill=lambda pid, sig: killed.append(pid)))
            self.assertEqual(killed, [])
            self.assertFalse(path.exists())                             # the stale file is gone
            path.write_text("4242")
            proc = fake_proc(tmp, 4242, "bwrap")                  # the sandbox around the reader is ours too
            self.assertEqual(engine.running_reader(path, proc), 4242)
            proc = fake_proc(tmp, 4242, "espeak-ng")
            self.assertEqual(engine.running_reader(path, proc), 4242)
            self.assertTrue(engine.stop(path, proc, kill=lambda pid, sig: killed.append(pid)))
            self.assertEqual(killed, [4242])
            path.write_text("1")
            self.assertIsNone(engine.running_reader(path, fake_proc(tmp, 1, "espeak-ng")))

    def test_start_sends_the_text_through_stdin_and_remembers_the_pid(self):
        children = []

        def popen(argv, **kwargs):
            child = FakeChild(argv)
            child.kwargs = kwargs
            children.append(child)
            return child
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(engine.shutil, "which", lambda name: "/usr/bin/" + name):
            path = Path(tmp) / "run" / "speak.pid"
            pid = engine.start("שלום לכולם", "en", 160, path=path, popen=popen, proc=Path(tmp) / "proc")
            self.assertEqual(pid, 4242)
            reader, player = children[-2], children[-1]
            self.assertEqual(reader.argv[0], "bwrap")
            self.assertEqual(reader.argv[-7:-4], ["espeak-ng", "-v", "he"])
            self.assertEqual(reader.kwargs["stdin"], subprocess.PIPE)
            self.assertEqual(reader.kwargs["stdout"], subprocess.PIPE)
            self.assertEqual(player.argv, ["pw-play", "-"])
            self.assertEqual(player.kwargs["process_group"], 4242)     # one stop ends the reader and the player
            self.assertEqual(reader.written.decode(), "שלום לכולם")
            self.assertEqual(path.read_text(), "4242")
            self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")
            long = "a" * (engine.MAX_TEXT + 10)
            engine.start(long, "en", 160, path=path, popen=popen, proc=Path(tmp) / "proc")
            self.assertEqual(len(children[-2].written), engine.MAX_TEXT)
            with self.assertRaises(engine.SpeakError):
                engine.start("   ", "he", 160, path=path, popen=popen)
            wav = Path(tmp) / "x.wav"
            engine.start("to a file", "en", 160, wav=wav, path=path, popen=popen, proc=Path(tmp) / "proc")
            self.assertNotEqual(children[-1].argv[:1], ["pw-play"])           # a file: no player
            self.assertTrue(hasattr(children[-1].kwargs["stdout"], "write"))  # the reader's stdout is the file
            self.assertNotIn("-w", children[-1].argv)

            def missing(argv, **kwargs):
                raise FileNotFoundError(2, "No such file", "espeak-ng")
            with self.assertRaises(engine.SpeakError) as caught:
                engine.start("x", "en", 160, path=path, popen=missing)
            self.assertIn("espeak-ng", str(caught.exception))

            def no_player(argv, **kwargs):
                if argv[0] == "pw-play":
                    raise FileNotFoundError(2, "No such file", "pw-play")
                child = FakeChild(argv)
                child.kill = lambda: children.append("killed")
                return child
            with self.assertRaises(engine.SpeakError) as caught:
                engine.start("x", "en", 160, path=path, popen=no_player)
            self.assertIn("pw-play", str(caught.exception))
            self.assertEqual(children[-1], "killed")

    def test_selection_prefers_the_primary_selection(self):
        def run(argv, **kwargs):
            if "-p" in argv:
                return subprocess.CompletedProcess(argv, 0, b"primary text\n", b"")
            return subprocess.CompletedProcess(argv, 0, b"clipboard", b"")
        self.assertEqual(engine.selection(run), "primary text")

        def only_clipboard(argv, **kwargs):
            if "-p" in argv:
                return subprocess.CompletedProcess(argv, 1, b"", b"Nothing is selected")
            return subprocess.CompletedProcess(argv, 0, b"clipboard", b"")
        self.assertEqual(engine.selection(only_clipboard), "clipboard")

        def broken(argv, **kwargs):
            raise OSError("no wl-paste")
        self.assertEqual(engine.selection(broken), "")


class CliTests(unittest.TestCase):
    def test_text_stdin_stop_and_the_shortcut_toggle(self):
        children = []

        def popen(argv, **kwargs):
            child = FakeChild(argv, pid=777)
            children.append(child)
            return child

        def run(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, b"selected words", b"")
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            path = tmp / "speak.pid"
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                with mock.patch.object(engine.shutil, "which", lambda name: None):      # no bubblewrap here: plain
                    self.assertEqual(cli.main(["dai-speak", "--text", "Hello", "--lang", "en", "--rate", "200"], run, popen, tmp, path), 0)
                self.assertEqual(children[-2].argv, ["espeak-ng", "-v", "en-us", "-s", "200", "--stdin", "--stdout"])
                self.assertEqual(children[-2].written, b"Hello")
                self.assertEqual(children[-1].argv, ["pw-play", "-"])
                self.assertEqual(cli.main(["dai-speak", "--stdin", "--lang", "he"], run, popen, tmp, path, stdin=io.StringIO("מהקלט")), 0)
                self.assertEqual(children[-2].written.decode(), "מהקלט")
                self.assertEqual(children[-2].argv[-5], "he")
                # From the shortcut: the selection is read and a notice (not the text) is shown.
                self.assertEqual(cli.main(["dai-speak", "--lang", "en"], run, popen, tmp, path), 0)
                self.assertEqual(children[-3].written, b"selected words")
                self.assertEqual(children[-1].argv[0], "notify-send")
                self.assertNotIn("selected words", " ".join(children[-1].argv))
                # (The second press of the shortcut goes through running_reader/stop, covered above.)
                self.assertEqual(cli.main(["dai-speak", "--stop"], run, popen, tmp, path), 0)
                self.assertFalse(path.exists())
                self.assertEqual(cli.main(["dai-speak", "--text", "   ", "--lang", "en"], run, popen, tmp, path), 1)
                self.assertEqual(cli.main(["dai-speak", "--dance"], run, popen, tmp, path), 2)
                self.assertEqual(cli.main(["dai-speak", "--version"], run, popen, tmp, path), 0)
            self.assertIn("nothing to read", err.getvalue())

    def test_the_rate_comes_from_the_settings_file(self):
        children = []

        def popen(argv, **kwargs):
            child = FakeChild(argv)
            children.append(child)
            return child
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / engine.SETTINGS_FILE).parent.mkdir(parents=True)
            (home / engine.SETTINGS_FILE).write_text('{"rate": 130}')
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(["dai-speak", "--text", "x", "--lang", "en"], None, popen, home, home / "pid"), 0)
            self.assertEqual(children[-2].argv[-3], "130")
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(cli.main(["dai-speak", "--show", "--lang", "en"], None, popen, home, home / "pid"), 0)
            self.assertIn("espeak-ng -v en-us -s 130 --stdin --stdout", out.getvalue())


class ClientTests(unittest.TestCase):
    def test_other_windows_read_through_stdin_and_stop(self):
        from dai_speak import client
        children = []

        def popen(argv, **kwargs):
            child = FakeChild(argv)
            children.append(child)
            return child
        self.assertTrue(client.read("  Page one.  ", "he", popen))
        self.assertEqual(children[-1].argv, ["dai-speak", "--stdin", "--lang", "he"])
        self.assertEqual(children[-1].written, b"Page one.")
        self.assertFalse(client.read("   ", "en", popen))
        client.stop(popen)
        self.assertEqual(children[-1].argv, ["dai-speak", "--stop"])

        def missing(argv, **kwargs):
            raise FileNotFoundError(2, "no", "dai-speak")
        with redirect_stderr(io.StringIO()):
            self.assertFalse(client.read("x", "en", missing))
        client.stop(missing)


if __name__ == "__main__":
    unittest.main()
