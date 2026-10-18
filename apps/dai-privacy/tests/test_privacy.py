# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
import io
import json
import os
import subprocess
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from dai_privacy import cli
from dai_privacy.log import KEEP_DAYS, append, changes, read
from dai_privacy.sensors import Use, camera_uses, current, parse_pw_dump
from dai_privacy.text import describe


def node(media, state="running", **props):
    return {"id": 50, "type": "PipeWire:Interface:Node",
            "info": {"state": state, "props": {"media.class": media, **props}}}


PW_DUMP = [
    {"id": 0, "type": "PipeWire:Interface:Core", "info": {}},
    node("Audio/Source", **{"node.name": "alsa_input.pci"}),                                # the device itself
    node("Stream/Input/Audio", **{"application.name": "Firefox", "application.process.id": 4321}),
    node("Stream/Input/Audio", **{"application.name": "pavucontrol", "stream.monitor": "true"}),  # level meter
    node("Stream/Input/Audio", state="suspended", **{"application.name": "Zoom"}),          # not recording
    node("Stream/Input/Video", **{"application.process.binary": "obs"}),
    node("Stream/Output/Audio", **{"application.name": "mpv"}),                             # playback
]


class SensorTests(unittest.TestCase):
    def test_pipewire_capture_streams_only(self):
        self.assertEqual(parse_pw_dump(PW_DUMP), [Use("mic", "Firefox", 4321), Use("video", "obs", 0)])
        self.assertEqual(parse_pw_dump({"not": "a list"}), [])

    def test_camera_opened_directly(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp)
            for pid, name, target in ((100, "cheese", "/dev/video0"), (200, "bash", "/dev/pts/1")):
                (proc / str(pid) / "fd").mkdir(parents=True)
                (proc / str(pid) / "comm").write_text(name + "\n")
                (proc / str(pid) / "fd" / "3").symlink_to(target)
            (proc / "self").mkdir()
            self.assertEqual(camera_uses(proc), [Use("camera", "cheese", 100)])
            self.assertEqual(camera_uses(proc / "missing"), [])

    def test_current_merges_and_survives_missing_pipewire(self):
        dump = subprocess.CompletedProcess([], 0, json.dumps(PW_DUMP * 2), "")
        uses = current(runner=lambda argv: dump, proc=Path("/nonexistent"))
        self.assertEqual(len(uses), 2)  # duplicates removed
        broken = subprocess.CompletedProcess([], 127, "", "pw-dump: not found")
        self.assertEqual(current(runner=lambda argv: broken, proc=Path("/nonexistent")), [])


class LogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state" / "dai" / "privacy.log"

    def tearDown(self):
        self.tmp.cleanup()

    def test_changes(self):
        mic, cam = Use("mic", "Firefox", 1), Use("camera", "cheese", 2)
        self.assertEqual(changes(set(), {mic}), [("start", mic)])
        self.assertEqual(changes({mic}, {cam}), [("start", cam), ("stop", mic)])
        self.assertEqual(changes({mic}, {mic}), [])

    def test_private_and_pruned_after_30_days(self):
        now = time.time()
        append(self.path, [("start", Use("mic", "Old", 1))], now=now - (KEEP_DAYS + 1) * 86400)
        append(self.path, [("start", Use("mic", "Firefox", 2))], now=now)
        self.assertEqual(oct(self.path.stat().st_mode & 0o777), "0o600")
        self.assertEqual(oct(self.path.parent.stat().st_mode & 0o777), "0o700")
        self.assertEqual([e["app"] for e in read(self.path, now=now)], ["Firefox"])
        self.assertNotIn("Old", self.path.read_text())  # really removed from disk

    def test_cli(self):
        append(self.path, [("start", Use("camera", "cheese", 7)), ("stop", Use("camera", "cheese", 7))])
        env = {"XDG_STATE_HOME": str(Path(self.tmp.name) / "state"), "LANG": "he_IL.UTF-8"}
        out = io.StringIO()
        with mock.patch.dict(os.environ, env), redirect_stdout(out):
            self.assertEqual(cli.main(["dai-privacy", "log"]), 0)
        self.assertIn("cheese משתמש במצלמה", out.getvalue())
        self.assertIn("cheese הפסיק להשתמש במצלמה", out.getvalue())
        out = io.StringIO()
        with mock.patch.dict(os.environ, env), redirect_stdout(out), \
                mock.patch("dai_privacy.cli.current", return_value=[Use("mic", "Firefox", 9)]):
            cli.main(["dai-privacy", "status", "--json"])
        self.assertEqual(json.loads(out.getvalue()), [{"device": "mic", "app": "Firefox", "pid": 9}])

    def test_wording(self):
        self.assertEqual(describe(Use("mic", "Zoom"), "he"), "🎙 Zoom משתמש במיקרופון")
        self.assertEqual(describe(Use("video", "obs"), "en"), "📷 obs is using the camera or screen sharing")


try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from dai_privacy.tray import Indicator
    HAVE_QT = True
except ImportError:
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PyQt6 not available")
class IndicatorTests(unittest.TestCase):
    def test_dot_only_while_in_use_and_notifies_on_start(self):
        app = QApplication.instance() or QApplication([])
        sensed = [[], [Use("mic", "Firefox", 1)], [Use("mic", "Firefox", 1)], []]
        notified = []
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"XDG_STATE_HOME": tmp, "LANG": "en_US.UTF-8"}):
            indicator = Indicator(app, sense=lambda: sensed.pop(0), notify=notified.append)
            indicator.check()
            self.assertFalse(indicator.tray.isVisible())
            indicator.check()
            self.assertTrue(indicator.tray.isVisible())
            self.assertIn("Firefox is using the microphone", indicator.tray.toolTip())
            indicator.check()
            indicator.check()
            self.assertFalse(indicator.tray.isVisible())
            self.assertEqual(notified, ["🎙 Firefox is using the microphone"])  # once, at the start
            events = [e["event"] for e in read(Path(tmp) / "dai" / "privacy.log")]
            self.assertEqual(events, ["start", "stop"])


class CommandTests(unittest.TestCase):
    def test_command_bar(self):
        try:
            from dai_command import core
        except ImportError:
            self.skipTest("dai_command not on the path")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"XDG_STATE_HOME": tmp, "LANG": "en_US.UTF-8"}), \
                mock.patch("dai_privacy.sensors.current", return_value=[Use("mic", "Firefox", 1)]):
            rows = core.privacy_actions("who is using my microphone?")
            self.assertEqual((rows[0].kind, rows[0].title), ("privacy", "🎙 Firefox is using the microphone"))
            self.assertIsNotNone(core.privacy_actions("מי משתמש במצלמה"))
            self.assertIsNone(core.privacy_actions("microphone settings"))


if __name__ == "__main__":
    unittest.main()
