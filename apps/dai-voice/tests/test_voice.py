# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dai_voice import cli, engine

CATALOG = Path(__file__).resolve().parents[2] / "dai-ai" / "data" / "models.json"


class VoiceTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {
            "XDG_RUNTIME_DIR": str(base / "run"),
            "XDG_DATA_HOME": str(base / "data"),
            "XDG_CONFIG_HOME": str(base / "config"),
            "DAI_MODELS_CATALOG": str(CATALOG),
            "LANG": "en_US.UTF-8",
        })
        self.env.start()
        (base / "run").mkdir()
        self.whisper = base / "whisper"
        self.whisper.mkdir()
        (self.whisper / "whisper-cli").write_text("")
        patcher = mock.patch.object(engine, "WHISPER_DIR", self.whisper)
        patcher.start()
        self.addCleanup(patcher.stop)
        from dai_ai import models
        catalog = mock.patch.object(engine, "load_catalog", lambda: models.load_catalog(CATALOG))
        catalog.start()
        self.addCleanup(catalog.stop)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def install_model(self, model_id="whisper-small"):
        from dai_ai import models
        model = models.load_catalog(CATALOG)[model_id]
        model.path.parent.mkdir(parents=True, exist_ok=True)
        model.path.write_bytes(b"model")
        return model.path


def completed(stdout="", code=0, stderr=""):
    return subprocess.CompletedProcess([], code, stdout, stderr)


class SandboxTests(VoiceTestCase):
    def test_whisper_runs_without_network_or_home(self):
        with mock.patch.object(engine.shutil, "which", return_value="/usr/bin/bwrap"):
            argv = engine.whisper_argv(Path("/run/user/1/dai/voice.wav"), Path("/m/model.bin"), "he")
        joined = " ".join(argv)
        for expected in ("--unshare-all", "--cap-drop ALL", "--clearenv", "--die-with-parent",
                         "--ro-bind /m/model.bin /model.bin", "--ro-bind /run/user/1/dai/voice.wav /audio.wav"):
            self.assertIn(expected, joined)
        self.assertNotIn("--share-net", argv)
        self.assertNotIn(str(Path.home()), joined)
        # tmpfs mounts come before the binds so nothing gets hidden.
        self.assertLess(argv.index("/tmp"), argv.index("--ro-bind"))
        self.assertEqual(argv[argv.index("-l") + 1], "he")

    def test_refuses_without_sandbox_and_bad_language(self):
        with mock.patch.object(engine.shutil, "which", return_value=None), self.assertRaises(engine.VoiceError):
            engine.whisper_argv(Path("a.wav"), Path("m.bin"), "en")
        with mock.patch.object(engine.shutil, "which", return_value="/usr/bin/bwrap"), \
                self.assertRaises(engine.VoiceError):
            engine.whisper_argv(Path("a.wav"), Path("m.bin"), "en; rm -rf ~")


class TranscribeTests(VoiceTestCase):
    def test_transcribe_cleans_text_and_deletes_audio(self):
        self.install_model()
        audio = Path(self.tmp.name) / "run" / "voice.wav"
        audio.write_bytes(b"RIFF" + b"\0" * 100)
        runner = mock.Mock(return_value=completed(" שלום עולם\n [BLANK_AUDIO]\n מה נשמע?\n"))
        with mock.patch.object(engine.shutil, "which", return_value="/usr/bin/bwrap"):
            text = engine.transcribe(audio, runner=runner, delete=True)
        self.assertEqual(text, "שלום עולם מה נשמע?")
        self.assertFalse(audio.exists())
        argv = runner.call_args[0][0]
        self.assertEqual(argv[argv.index("-l") + 1], "auto")

    def test_language_and_model_from_settings(self):
        self.install_model("whisper-base")
        small = self.install_model("whisper-small")
        config = Path(self.tmp.name) / "config" / "dai" / "voice.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"lang": "he", "model": "whisper-small"}))
        runner = mock.Mock(return_value=completed("x"))
        with mock.patch.object(engine.shutil, "which", return_value="/usr/bin/bwrap"):
            engine.transcribe(Path(self.tmp.name) / "a.wav", runner=runner)
        argv = runner.call_args[0][0]
        self.assertEqual(argv[argv.index("-l") + 1], "he")
        self.assertIn(f"{small}", argv)

    def test_no_model_and_failures(self):
        with mock.patch.object(engine.shutil, "which", return_value="/usr/bin/bwrap"), \
                self.assertRaisesRegex(engine.VoiceError, "dai-models install"):
            engine.transcribe(Path("a.wav"), runner=mock.Mock())
        self.install_model()
        with mock.patch.object(engine.shutil, "which", return_value="/usr/bin/bwrap"), \
                self.assertRaisesRegex(engine.VoiceError, "failed"):
            engine.transcribe(Path("a.wav"), runner=mock.Mock(return_value=completed(code=3, stderr="bad")))


class RecordingTests(VoiceTestCase):
    def test_start_stop_cycle(self):
        spawned = []
        recorder = subprocess.Popen(["sleep", "30"], start_new_session=True)
        self.addCleanup(recorder.kill)

        def spawn(argv):
            spawned.append(argv)
            return recorder.pid

        with mock.patch.object(engine.shutil, "which", return_value="/usr/bin/pw-record"), \
                mock.patch.object(engine, "_alive_recorder", side_effect=lambda pid: recorder.poll() is None):
            state = engine.start(spawn)
            self.assertEqual(spawned[0][:3], ["timeout", "--signal=INT", str(engine.MAX_SECONDS)])
            self.assertIn("16000", spawned[0])
            self.assertEqual(oct(engine._state_file().stat().st_mode & 0o777), "0o600")
            self.assertEqual(engine.recording()["pid"], state["pid"])
            with self.assertRaises(engine.VoiceError):
                engine.start(spawn)  # one recording at a time
            Path(state["wav"]).write_bytes(b"RIFF" + b"\0" * 1000)
            wav = engine.stop()
        recorder.wait(5)
        self.assertEqual(wav, engine.wav_path())
        self.assertIsNone(engine.recording())

    def test_stop_without_audio(self):
        engine._state_file().write_text(json.dumps({"pid": 999999, "wav": str(engine.wav_path())}))
        with self.assertRaisesRegex(engine.VoiceError, "nothing was recorded"):
            engine.stop()
        with self.assertRaisesRegex(engine.VoiceError, "not recording"):
            engine.stop()

    def test_pid_reuse_is_not_mistaken_for_the_recorder(self):
        self.assertFalse(engine._alive_recorder(os.getpid()))  # python, not pw-record


class CliTests(VoiceTestCase):
    def test_deliver_targets(self):
        with mock.patch.object(cli.subprocess, "run") as run, mock.patch.object(cli.subprocess, "Popen") as popen, \
                mock.patch.object(cli, "notify"), mock.patch.object(cli.time, "sleep"):
            self.assertEqual(cli.deliver("שלום", "type"), 0)
            self.assertEqual(run.call_args[0][0], ["wtype", "--", "שלום"])
            cli.deliver("open firefox", "command")
            self.assertEqual(popen.call_args[0][0], ["dai-command", "--query", "open firefox"])
            cli.deliver("x", "copy")
            self.assertEqual(run.call_args[0][0], ["wl-copy", "--", "x"])
            self.assertEqual(cli.deliver("", "type"), 3)

    def test_text_starting_with_dash_is_not_an_option(self):
        with mock.patch.object(cli.subprocess, "run") as run, mock.patch.object(cli, "notify"), \
                mock.patch.object(cli.time, "sleep"):
            cli.deliver("--help", "type")
        self.assertEqual(run.call_args[0][0], ["wtype", "--", "--help"])

    def test_toggle_starts_then_finishes(self):
        with mock.patch.object(cli, "recording", side_effect=[None, {"pid": 1}]), \
                mock.patch.object(cli, "start") as start, mock.patch.object(cli, "notify") as notify, \
                mock.patch.object(cli, "stop", return_value=Path("a.wav")), \
                mock.patch.object(cli, "transcribe", return_value="hello") as transcribe, \
                mock.patch.object(cli, "deliver", return_value=0) as deliver:
            self.assertEqual(cli.main(["dai-voice", "toggle", "--to", "command"]), 0)
            start.assert_called_once()
            self.assertIn("Recording", notify.call_args[0][0])  # never record silently
            self.assertEqual(cli.main(["dai-voice", "toggle", "--to", "command", "--lang", "he"]), 0)
        transcribe.assert_called_with(Path("a.wav"), lang="he", delete=True)
        deliver.assert_called_with("hello", "command")

    def test_bad_options(self):
        with mock.patch.object(cli, "notify"):
            self.assertEqual(cli.main(["dai-voice", "toggle", "--to", "shell"]), 1)
            self.assertEqual(cli.main(["dai-voice"]), 2)


try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from dai_voice.qt import VoiceButton
except ImportError:  # pragma: no cover
    VoiceButton = None


@unittest.skipIf(VoiceButton is None, "PyQt6 is not installed")
class ButtonTests(VoiceTestCase):
    def test_the_button_is_accessible(self):
        from dai_raz.a11y import assert_accessible
        app = QApplication.instance() or QApplication([])
        assert_accessible(self, VoiceButton(program="true"))

    def test_click_to_record_click_to_transcribe(self):
        import time
        app = QApplication.instance() or QApplication([])
        fake = Path(self.tmp.name) / "fake-voice"
        fake.write_text('#!/bin/sh\nif [ "$1" = stop ]; then echo "שלום מהמיקרופון"; fi\nexit 0\n')
        fake.chmod(0o755)
        button = VoiceButton(program=str(fake))
        texts, states = [], []
        button.transcribed.connect(texts.append)
        button.state_changed.connect(states.append)

        def wait_for(condition):
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and not condition():
                app.processEvents()
                time.sleep(0.01)

        button.click()
        wait_for(lambda: button.state == "recording")
        self.assertEqual(button.state, "recording")
        self.assertTrue(button.property("recording"))
        button.click()
        wait_for(lambda: texts)
        self.assertEqual(texts, ["שלום מהמיקרופון"])
        self.assertEqual(states[-1], "idle")


if __name__ == "__main__":
    unittest.main()
