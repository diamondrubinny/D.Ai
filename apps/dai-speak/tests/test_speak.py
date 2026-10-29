# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""D.Ai Speak (docs/SPEAK.md): the voice follows the letters, the text goes through stdin, the pid file is
only trusted when /proc says espeak-ng, and the CLI with a fake wl-paste and a fake reader."""
import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from dai_speak import cli, engine


class FakeChild:
    def __init__(self, argv, pid=4242, returncode=0):
        self.argv, self.pid, self.returncode = argv, pid, returncode
        self.stdin = io.BytesIO()
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
        self.assertEqual(engine.reader_argv("he", 160), ["espeak-ng", "-v", "he", "-s", "160", "--stdin"])
        self.assertEqual(engine.reader_argv("en", 999, Path("/tmp/x.wav"))[-3:], ["--stdin", "-w", "/tmp/x.wav"])
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
            proc = fake_proc(tmp, 4242, "espeak-ng")
            self.assertEqual(engine.running_reader(path, proc), 4242)
            self.assertTrue(engine.stop(path, proc, kill=lambda pid, sig: killed.append(pid)))
            self.assertEqual(killed, [4242])
            path.write_text("1")
            self.assertIsNone(engine.running_reader(path, fake_proc(tmp, 1, "espeak-ng")))

    def test_start_sends_the_text_through_stdin_and_remembers_the_pid(self):
        children = []

        def popen(argv, **kwargs):
            self.assertEqual(kwargs["stdin"], subprocess.PIPE)
            child = FakeChild(argv)
            children.append(child)
            return child
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run" / "speak.pid"
            pid = engine.start("שלום לכולם", "en", 160, path=path, popen=popen, proc=Path(tmp) / "proc")
            self.assertEqual(pid, 4242)
            self.assertEqual(children[0].argv[:3], ["espeak-ng", "-v", "he"])
            self.assertEqual(children[0].written.decode(), "שלום לכולם")
            self.assertEqual(path.read_text(), "4242")
            self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")
            long = "a" * (engine.MAX_TEXT + 10)
            engine.start(long, "en", 160, path=path, popen=popen, proc=Path(tmp) / "proc")
            self.assertEqual(len(children[-1].written), engine.MAX_TEXT)
            with self.assertRaises(engine.SpeakError):
                engine.start("   ", "he", 160, path=path, popen=popen)
            engine.start("to a file", "en", 160, wav=Path(tmp) / "x.wav", path=path, popen=popen, proc=Path(tmp) / "proc")
            self.assertIn("-w", children[-1].argv)

            def missing(argv, **kwargs):
                raise FileNotFoundError(2, "No such file", "espeak-ng")
            with self.assertRaises(engine.SpeakError) as caught:
                engine.start("x", "en", 160, path=path, popen=missing)
            self.assertIn("espeak-ng", str(caught.exception))

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
                self.assertEqual(cli.main(["dai-speak", "--text", "Hello", "--lang", "en", "--rate", "200"], run, popen, tmp, path), 0)
                self.assertEqual(children[-1].argv, ["espeak-ng", "-v", "en-us", "-s", "200", "--stdin"])
                self.assertEqual(children[-1].written, b"Hello")
                self.assertEqual(cli.main(["dai-speak", "--stdin", "--lang", "he"], run, popen, tmp, path, stdin=io.StringIO("מהקלט")), 0)
                self.assertEqual(children[-1].written.decode(), "מהקלט")
                self.assertEqual(children[-1].argv[2], "he")
                # From the shortcut: the selection is read and a notice (not the text) is shown.
                self.assertEqual(cli.main(["dai-speak", "--lang", "en"], run, popen, tmp, path), 0)
                self.assertEqual(children[-2].written, b"selected words")
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
            self.assertEqual(children[-1].argv[4], "130")


if __name__ == "__main__":
    unittest.main()
