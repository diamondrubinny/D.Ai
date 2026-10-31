# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""D.Ai Record (docs/RECORD.md): the recorder's command line, the pid file only trusted for wf-recorder,
the guard that stops in time, and the CLI with a fake recorder."""
import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from dai_record import cli, engine


class FakeChild:
    def __init__(self, argv, pid=5151):
        self.argv, self.pid = argv, pid


def fake_proc(tmp: Path, pid: int, comm: str) -> Path:
    (tmp / "proc" / str(pid)).mkdir(parents=True, exist_ok=True)
    (tmp / "proc" / str(pid) / "comm").write_text(comm + "\n")
    return tmp / "proc"


class EngineTests(unittest.TestCase):
    def test_argv_file_and_area(self):
        self.assertEqual(engine.recorder_argv(Path("/tmp/a.mp4")), ["wf-recorder", "-f", "/tmp/a.mp4"])
        self.assertEqual(engine.recorder_argv(Path("/tmp/a.mp4"), "10,20 300x200")[-2:], ["-g", "10,20 300x200"])
        self.assertNotIn("--audio", engine.recorder_argv(Path("/tmp/a.mp4")))
        with self.assertRaises(engine.RecordError):
            engine.recorder_argv(Path("/tmp/a.mp4"), "; rm -rf /")
        self.assertTrue(str(engine.new_file(Path("/v"))).startswith("/v/Recording-"))
        self.assertEqual(engine.videos_dir({"XDG_VIDEOS_DIR": "/mnt/v"}), Path("/mnt/v/Recordings"))

    def test_pid_file_start_stop_and_the_guard(self):
        children = []

        def popen(argv, **kwargs):
            child = FakeChild(argv)
            children.append(child)
            return child
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            path, proc = tmp / "run" / "record.pid", tmp / "proc"
            file = tmp / "v" / "a.mp4"
            pid = engine.start(file, None, "en", path, 0, popen, proc)
            self.assertEqual(pid, 5151)
            self.assertEqual(children[-1].argv, ["wf-recorder", "-f", str(file)])
            self.assertEqual(path.read_text().splitlines(), ["5151", str(file)])
            self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")
            self.assertIsNone(engine.running(path, proc))                     # no such process: not ours
            fake_proc(tmp, 5151, "bash")
            self.assertIsNone(engine.running(path, proc))                     # a foreign process: never ours
            fake_proc(tmp, 5151, "wf-recorder")
            self.assertEqual(engine.running(path, proc), (5151, file))
            with self.assertRaises(engine.RecordError):                      # one at a time
                engine.start(file, None, "en", path, 0, popen, proc)
            killed = []
            self.assertEqual(engine.stop(path, proc, kill=lambda p, s: killed.append((p, s))), file)
            self.assertEqual(killed, [(5151, engine.signal.SIGINT)])
            self.assertFalse(path.exists())
            self.assertIsNone(engine.stop(path, proc, kill=lambda p, s: killed.append(p)))
            # With seconds the guard is started too, and it stops only that same recording.
            engine.start(file, "0,0 10x10", "he", path, 30, popen, proc, guard=["dai-record", "_wait", "X", "30"])
            self.assertEqual(children[-1].argv, ["dai-record", "_wait", "X", "30"])
            self.assertEqual(children[-2].argv[-2:], ["-g", "0,0 10x10"])
            with self.assertRaises(engine.RecordError):
                engine.stop(path, proc, kill=lambda p, s: None)
                engine.start(file, None, "en", path, 10 ** 6, popen, proc)
            path.write_text("5151\n" + str(file) + "\n")
            slept, notified = [], []

            def run(argv, **kwargs):
                notified.append(argv)
                return subprocess.CompletedProcess(argv, 0, "", "")
            got = engine.wait_and_stop(5151, 3, path, "en", proc, sleep=slept.append, kill=lambda p, s: killed.append(p), run=run)
            self.assertEqual(got, file)
            self.assertEqual(slept[0], 3)
            self.assertEqual(notified[0][0], "notify-send")
            self.assertIn(["dai-sound", "screen-capture"], notified)
            path.write_text("5151\n" + str(file) + "\n")
            self.assertIsNone(engine.wait_and_stop(999, 1, path, "en", proc, sleep=lambda s: None, kill=lambda p, s: None, run=run))

            def missing(argv, **kwargs):
                raise FileNotFoundError(2, "no", "wf-recorder")
            path.unlink(missing_ok=True)
            with self.assertRaises(engine.RecordError) as caught:
                engine.start(file, None, "en", path, 0, missing, proc)
            self.assertIn("wf-recorder", str(caught.exception))


class CliTests(unittest.TestCase):
    def test_start_status_stop_toggle(self):
        children, calls = [], []

        def popen(argv, **kwargs):
            child = FakeChild(argv)
            children.append(child)
            return child

        def run(argv, **kwargs):
            calls.append(argv)
            if argv[0] == "slurp":
                return subprocess.CompletedProcess(argv, 0, "1,2 30x40\n", "")
            return subprocess.CompletedProcess(argv, 0, "", "")
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            path = tmp / "record.pid"
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(cli.main(["dai-record", "status"], run, popen, path, tmp), 0)
                self.assertIn("Not recording", out.getvalue())
                self.assertEqual(cli.main(["dai-record", "start", "5", "--area", "--file", str(tmp / "r.mp4")], run, popen, path, tmp, guard=["g"]), 0)
                self.assertEqual(children[0].argv, ["wf-recorder", "-f", str(tmp / "r.mp4"), "-g", "1,2 30x40"])
                self.assertEqual(children[1].argv, ["g"])
                self.assertEqual(calls[-1][0], "notify-send")
                self.assertIn("5 seconds", " ".join(calls[-1]))
                self.assertEqual(cli.main(["dai-record", "stop"], run, popen, path, tmp), 0)   # the fake pid is not wf-recorder
                self.assertIn("Not recording", out.getvalue())
                self.assertEqual(cli.main(["dai-record", "start", "--file", str(tmp / "s.mp4")], run, popen, path, tmp, guard=["g"]), 0)
                self.assertEqual(len(children), 3)                                            # no guard without seconds
                self.assertEqual(cli.main(["dai-record", "--version"], run, popen, path, tmp), 0)
                self.assertEqual(cli.main(["dai-record", "dance"], run, popen, path, tmp), 2)
                self.assertEqual(cli.main(["dai-record", "start", "--file", str(tmp / "t.mp4")], lambda a, **k: subprocess.CompletedProcess(a, 0, "", ""),
                                          lambda a, **k: (_ for _ in ()).throw(FileNotFoundError(2, "no", "wf-recorder")), path, tmp), 1)
            self.assertIn("wf-recorder", err.getvalue())
            self.assertTrue(str(children[2].argv[2]).endswith("s.mp4"))


if __name__ == "__main__":
    unittest.main()
