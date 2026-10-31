# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""D.Ai Remind (docs/REMIND.md): the files, firing with fake notify-send/dai-sound/dai-speak, cancel and list."""
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from dai_remind import cli, engine


def write_reminder(home: Path, reminder_id: str, text: str, at: str) -> None:
    folder = home / engine.REMIND_DIR
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{reminder_id}.json").write_text(json.dumps({"text": text, "at": at, "created": "2026-10-31T10:00"}))
    units = home / engine.UNIT_DIR
    units.mkdir(parents=True, exist_ok=True)
    (units / f"dai-remind-{reminder_id}.service").write_text("[Service]\n")
    (units / f"dai-remind-{reminder_id}.timer").write_text("[Timer]\n")


class EngineTests(unittest.TestCase):
    def test_fire_shows_sounds_cleans_up_and_speaks_only_when_asked(self):
        calls, spoken = [], []

        def run(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, "", "")

        class Child:
            def __init__(self):
                self.stdin = io.BytesIO()
                real = self.stdin.close
                self.stdin.close = lambda: (spoken.append(self.stdin.getvalue()), real())

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_reminder(home, "0a1b2c3d", "call Dana", "2026-10-31T18:30")
            reminder = engine.fire("0a1b2c3d", "en", home, run, popen=lambda argv, **k: Child(), which=lambda n: "/usr/bin/" + n)
            self.assertEqual(reminder.text, "call Dana")
            notify = next(c for c in calls if c[0] == "notify-send")
            self.assertEqual(notify[-1], "call Dana")                       # the text is an argument, never a shell
            self.assertIn("-u", notify)
            self.assertIn(["dai-sound", "bell"], calls)
            self.assertIn(["systemctl", "--user", "disable", "--now", "dai-remind-0a1b2c3d.timer"], calls)
            self.assertIn(["systemctl", "--user", "disable", "dai-remind-0a1b2c3d.service"], calls)
            # fire() runs inside that service: it must never stop itself (that killed the first VM run)
            self.assertFalse(any("--now" in c and c[-1].endswith(".service") for c in calls))
            self.assertEqual(spoken, [])                                      # "read explanations aloud" is off
            self.assertFalse((home / engine.REMIND_DIR / "0a1b2c3d.json").exists())
            self.assertFalse(any(p.exists() for p in engine.unit_files("0a1b2c3d", home)))
            self.assertTrue((home / engine.REMIND_DIR / "0a1b2c3d.fired").exists())
            (home / ".config/dai").mkdir(parents=True)
            (home / ".config/dai/explain.json").write_text('{"sight": true, "voice": true}')
            write_reminder(home, "0a1b2c3e", "שתה מים", "2026-10-31T18:40")
            engine.fire("0a1b2c3e", "he", home, run, popen=lambda argv, **k: Child(), which=lambda n: "/usr/bin/" + n)
            self.assertEqual(spoken[-1].decode(), "תזכורת: שתה מים")
            with self.assertRaises(engine.RemindError):
                engine.fire("0a1b2c3e", "en", home, run, popen=lambda argv, **k: Child(), which=lambda n: None)
            with self.assertRaises(engine.RemindError):
                engine.load("../etc/x", home)

    def test_list_describes_and_sorts(self):
        from datetime import datetime
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.assertEqual(engine.upcoming(home), [])
            write_reminder(home, "bbbbbbbb", "later", "2026-10-31T20:00")
            write_reminder(home, "aaaaaaaa", "sooner", "2026-10-31T10:30")
            (home / engine.REMIND_DIR / "zzzz.json").write_text("{}")         # not an id: ignored
            (home / engine.REMIND_DIR / "cccccccc.json").write_text("broken")  # unreadable: ignored
            names = [r.text for r in engine.upcoming(home)]
            self.assertEqual(names, ["sooner", "later"])
            line = engine.describe(engine.load("aaaaaaaa", home), "en", now=datetime(2026, 10, 31, 10, 0))
            self.assertIn("in 30 min", line)
            self.assertIn("sooner", line)
            line = engine.describe(engine.load("bbbbbbbb", home), "he", now=datetime(2026, 10, 31, 10, 0))
            self.assertIn("בעוד 10 שע׳ 0 דק׳", line)


class CliTests(unittest.TestCase):
    def test_list_cancel_fire_and_bad_ids(self):
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, "", "")
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(cli.main(["dai-remind", "list"], home), 0)
                self.assertIn("No reminders", out.getvalue())
                write_reminder(home, "0a1b2c3d", "call Dana", "2026-12-31T18:30")
                self.assertEqual(cli.main(["dai-remind", "list"], home), 0)
                self.assertIn("call Dana", out.getvalue())
                self.assertEqual(cli.main(["dai-remind", "cancel", "0a1b2c3d"], home, run=run), 0)
                self.assertIn("removed 0a1b2c3d", out.getvalue())
                self.assertFalse((home / engine.REMIND_DIR / "0a1b2c3d.json").exists())
                self.assertEqual(cli.main(["dai-remind", "cancel", "0a1b2c3d"], home, run=run), 0)
                self.assertIn("nothing to remove", out.getvalue())
                self.assertEqual(cli.main(["dai-remind", "cancel", "../x"], home, run=run), 2)
                self.assertEqual(cli.main(["dai-remind", "fire", "0a1b2c3d"], home, run=run, which=lambda n: None), 1)
                write_reminder(home, "0a1b2c3f", "stretch", "2026-12-31T18:30")
                self.assertEqual(cli.main(["dai-remind", "fire", "0a1b2c3f"], home, run=run, which=lambda n: None), 0)
                self.assertIn("⏰ stretch", out.getvalue())
                self.assertEqual(cli.main(["dai-remind", "--version"], home), 0)
                self.assertEqual(cli.main(["dai-remind", "dance"], home), 2)
            self.assertIn("hexadecimal", err.getvalue())


if __name__ == "__main__":
    unittest.main()
