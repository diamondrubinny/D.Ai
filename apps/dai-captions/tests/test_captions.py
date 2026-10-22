# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""D.Ai Captions (docs/BEYOND.md §13): the chunk pipeline with a fake whisper, and the bar."""
import io
import math
import os
import struct
import subprocess
import tempfile
import unittest
import wave
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from dai_captions import cli, engine


def tone_wav(path: Path, seconds: float, rate: int = 16000, channels: int = 1, silent: bool = False) -> Path:
    frames = int(rate * seconds)
    samples = [0 if silent else int(8000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(frames)]
    with wave.open(str(path), "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(struct.pack(f"<{len(samples) * channels}h", *(s for s in samples for _ in range(channels))))
    return path


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.tmp.name})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_a_file_becomes_five_second_chunks_at_16k_mono(self):
        source = tone_wav(Path(self.tmp.name) / "stereo.wav", 12.5, rate=48000, channels=2)
        chunks = list(engine.file_chunks(source))
        self.assertEqual(len(chunks), 3)
        with wave.open(str(chunks[0]), "rb") as wav:
            self.assertEqual((wav.getnchannels(), wav.getframerate(), wav.getnframes()), (1, 16000, 80000))
        self.assertEqual(oct(chunks[0].stat().st_mode & 0o777), "0o600")
        self.assertTrue(str(chunks[0]).startswith(self.tmp.name))

    def test_silence_is_skipped_and_chunks_are_deleted(self):
        source = tone_wav(Path(self.tmp.name) / "quiet.wav", 10, silent=True)
        seen = []
        captions = engine.run_pipeline(engine.file_chunks(source), transcriber=lambda p: seen.append(p) or "x")
        self.assertEqual((seen, captions.lines), ([], []))
        self.assertFalse(list(Path(self.tmp.name).glob("dai/captions-*.wav")))

    def test_lines_join_sentences_and_keep_the_last_three(self):
        captions = engine.Captions()
        captions.add("And so my fellow")
        captions.add("Americans, ask not.")
        captions.add("What your country can do for you")
        captions.add("")
        self.assertEqual(captions.lines, ["And so my fellow Americans, ask not.", "What your country can do for you"])
        for i in range(5):
            captions.add(f"Line {i}.")
        self.assertEqual(len(captions.lines), 3)
        self.assertEqual(captions.lines[-1], "Line 4.")

    def test_pipeline_emits_after_each_spoken_chunk_and_stops(self):
        source = tone_wav(Path(self.tmp.name) / "talk.wav", 15)
        texts = iter(["hello there.", "second", "third"])
        shown = []
        stops = [False, False, True]
        captions = engine.run_pipeline(engine.file_chunks(source), transcriber=lambda p: next(texts),
                                       emit=shown.append, stop=lambda: stops.pop(0))
        self.assertEqual(shown, ["hello there.", "hello there.\nsecond"])
        self.assertEqual(captions.text, "hello there.\nsecond")

    def test_record_argv_captures_the_speakers_not_the_microphone(self):
        argv = engine.record_argv(Path("/run/user/1/dai/captions-0.wav"))
        self.assertEqual(argv[:4], ["timeout", "--signal=INT", "5", "pw-record"])
        self.assertIn("{ stream.capture.sink = true }", argv)
        self.assertIn("16000", argv)

    def test_record_chunk_handles_a_missing_recorder(self):
        self.assertIsNone(engine.record_chunk(0, run=lambda *a, **k: (_ for _ in ()).throw(OSError())))

        def fake_run(argv, **kwargs):
            tone_wav(Path(argv[-1]), 1)
            return subprocess.CompletedProcess(argv, 0, "", "")

        path = engine.record_chunk(1, run=fake_run)
        self.assertTrue(path and path.exists())

    def test_transcribe_chunk_goes_through_voice_and_deletes(self):
        chunk = tone_wav(Path(self.tmp.name) / "c.wav", 1)
        with mock.patch.object(engine, "transcribe", lambda p, lang=None, delete=False: (p.unlink(), " text ")[1]) as _:
            self.assertEqual(engine.transcribe_chunk(chunk, "he"), " text ")
        self.assertFalse(chunk.exists())

    def test_cli_print_from_file(self):
        source = tone_wav(Path(self.tmp.name) / "talk.wav", 6)
        out = io.StringIO()
        with mock.patch.object(cli, "transcribe_chunk", lambda p, lang=None: (p.unlink(), "ask not what your country")[1]), \
                redirect_stdout(out):
            code = cli.main(["dai-captions", "--print", "--from-file", str(source), "--lang", "en"])
        self.assertEqual(code, 0)
        self.assertIn("ask not what your country", out.getvalue())
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["dai-captions", "--version"]), 0)
            self.assertEqual(cli.main(["dai-captions", "--from-file"]), 2)
            self.assertEqual(cli.main(["dai-captions", "--dance"]), 2)
        with mock.patch.object(cli, "transcribe_chunk", side_effect=engine.VoiceError("no speech model installed")), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["dai-captions", "--print", "--from-file", str(source)]), 1)


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PyQt6.QtWidgets import QApplication
        except ImportError:
            raise unittest.SkipTest("PyQt6 is missing")
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.tmp.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        from dai_captions import gui
        self.gui = gui

    def test_every_control_is_accessible(self):
        from dai_raz.a11y import assert_accessible
        self.qt.setStyleSheet(self.gui.STYLE)
        self.addCleanup(self.qt.setStyleSheet, "")
        window = self.gui.CaptionsWindow("en")
        self.addCleanup(window.deleteLater)
        window.show_line("The first line.")
        window.show_error("no speech model installed")
        assert_accessible(self, window, touch=True)

    def test_a_file_runs_through_the_bar_and_hebrew_reads_right_to_left(self):
        from PyQt6.QtCore import Qt
        source = tone_wav(Path(self.tmp.name) / "talk.wav", 10)
        texts = iter(["שלום לכולם.", "second line"])
        window = self.gui.CaptionsWindow("he", source, transcriber=lambda p: (p.unlink(), next(texts))[1])
        self.addCleanup(window.deleteLater)
        self.assertEqual(window.layoutDirection(), Qt.LayoutDirection.RightToLeft)
        self.assertEqual(window.windowTitle(), "כתוביות חיות D.Ai")
        self.assertTrue(window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        window.start()
        self.wait(lambda: window.thread is None)
        self.assertEqual(window.lines.text(), "שלום לכולם.\nsecond line")
        self.assertEqual(window.status.text(), "הסתיים")
        self.assertFalse(window.pause_button.isEnabled())

    def test_no_model_shows_what_to_run(self):
        source = tone_wav(Path(self.tmp.name) / "talk.wav", 5)
        window = self.gui.CaptionsWindow("en", source,
                                         transcriber=lambda p: (_ for _ in ()).throw(engine.VoiceError("no speech model installed — run: dai-models install whisper-small")))
        self.addCleanup(window.deleteLater)
        window.start()
        self.wait(lambda: window.thread is None)
        self.assertTrue(window.error_box.isVisibleTo(window))
        self.assertIn("dai-models install whisper-small", window.error.text())

    def wait(self, condition, timeout=10.0):
        import time
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.qt.processEvents()
            time.sleep(0.01)
        self.assertTrue(condition())


if __name__ == "__main__":
    unittest.main()
