# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Diamond's Way (docs/WAY.md): the language, one plan for a whole file, export, and the CLI."""
import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from dai_forge import recipes
from dai_tune.context import Context

from dai_way import cli, export, language, planner

BUILTIN = Path(__file__).resolve().parents[2] / "dai-forge" / "data" / "recipes"
EXAMPLES = Path(__file__).resolve().parents[1] / "data" / "examples"


class WayTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        (self.base / "home").mkdir()
        (self.base / "root/usr/share/applications").mkdir(parents=True)
        (self.base / "root/usr/share/applications/firefox-esr.desktop").write_text("[Desktop Entry]\nName=Firefox\nExec=firefox %u\n")
        self.calls = []

        def run(argv, **kwargs):
            self.calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, "", "")

        self.ctx = Context(root=self.base / "root", home=self.base / "home", runner=run, lang="en")
        self.library = recipes.load_library({"admin": self.base / "admin", "builtin": BUILTIN, "user": self.base / "user"})

    def write(self, name, text):
        path = self.base / name
        path.write_text(text, encoding="utf-8")
        return path


class LanguageTests(WayTestCase):
    def test_both_languages_values_and_sections(self):
        program = language.parse_text("""# a comment
diamond: my computer
let minutes = 10
setup:
  lock the screen after $minutes minutes   # trailing comment
  block usb storage
apps:
  antivirus
  org.videolan.VLC
exact:
  @ firewall.open_port port=8080 proto=tcp source=lan
""", "a.dway")
        self.assertEqual(program.name, "my computer")
        self.assertEqual([l.text for l in program.setup], ["lock the screen after 10 minutes", "block usb storage"])
        self.assertEqual([(l.text, l.number) for l in program.apps], [("antivirus", 8), ("org.videolan.VLC", 9)])
        self.assertEqual(program.exact[0].text, "@ firewall.open_port port=8080 proto=tcp source=lan")
        hebrew = language.parse_text("יהלום: מחשב כיתה\nיהי minutes = 5\nהגדרות:\n  נעל מסך אחרי $minutes דקות\nאפליקציות:\n  antivirus\nמדויק:\n  @ appearance.theme theme=day\n", "b.dway")
        self.assertEqual((hebrew.name, hebrew.setup[0].text, hebrew.apps[0].text, hebrew.exact[0].text),
                         ("מחשב כיתה", "נעל מסך אחרי 5 דקות", "antivirus", "@ appearance.theme theme=day"))

    def test_errors_carry_the_line_number(self):
        for text, line, words in (
            ("lock the screen\n", 1, "heading first"),
            ("setup:\n  lock after $x minutes\n", 2, "unknown value $x"),
            ("let = 3\n", 1, "let NAME = VALUE"),
            ("setup:\n  @ foo.bar\n", 2, "belongs under exact"),
            ("x" * (language.MAX_BYTES + 1), 0, "larger"),
        ):
            with self.subTest(words), self.assertRaises(language.WayError) as caught:
                language.parse_text(text, "t.dway")
            self.assertEqual(caught.exception.line, line)
            self.assertIn(words, caught.exception.message)
            self.assertIn("t.dway", str(caught.exception))

    def test_use_includes_from_the_same_folder_only(self):
        self.write("shared.dway", "diamond: shared\nlet minutes = 7\nsetup:\n  block usb storage\n")
        main = self.write("main.dway", "use: shared.dway\nsetup:\n  lock the screen after $minutes minutes\n")
        program = language.parse(main)
        self.assertEqual([l.text for l in program.setup], ["lock the screen after 7 minutes", "block usb storage"])
        self.assertEqual(program.files, ["main.dway", "shared.dway"])
        self.assertEqual(program.name, "shared")
        for bad in ("use: ../x.dway", "use: /etc/passwd", "use: notes.txt"):
            with self.assertRaises(language.WayError):
                language.parse(self.write("bad.dway", bad + "\n"))
        self.write("loop.dway", "use: loop.dway\n")
        with self.assertRaises(language.WayError) as caught:
            language.parse(self.base / "loop.dway")
        self.assertIn("deep", caught.exception.message)

    def test_exact_lines_round_trip(self):
        action, params = language.parse_exact("@ firewall.open_port port=8080 proto=tcp source=lan")
        self.assertEqual((action, params), ("firewall.open_port", {"port": 8080, "proto": "tcp", "source": "lan"}))
        self.assertEqual(language.parse_exact("@ keyboard.layouts layouts=us,il")[1], {"layouts": ["us", "il"]})
        self.assertEqual(language.parse_exact("@ updates.auto enabled=true")[1], {"enabled": True})
        self.assertEqual(language.format_exact("keyboard.layouts", {"layouts": ["us", "il"], "x": False}), "@ keyboard.layouts layouts=us,il x=false")
        with self.assertRaises(language.WayError):
            language.parse_exact("@ rm -rf")


class PlanTests(WayTestCase):
    def test_sentences_apps_and_exact_lines_become_one_plan(self):
        program = language.parse_text("diamond: t\nsetup:\n  lock the screen after 10 minutes\n  firefox does not go online\n"
                                      "apps:\n  antivirus\n  org.videolan.VLC\nexact:\n  @ firewall.open_port port=8080 proto=tcp source=lan\n", "t.dway")
        compiled = planner.compile_program(program, self.ctx, self.library)
        self.assertEqual(compiled.problems, [])
        self.assertTrue(compiled.ok)
        actions = [s.action for s in compiled.plan.steps]
        self.assertEqual(actions[:2], ["session.lock", "app.offline"])
        self.assertIn("packages.install", actions)
        self.assertIn("flatpak.install", actions)
        self.assertEqual(actions[-1], "firewall.open_port")
        self.assertEqual({s.scope for s in compiled.plan.steps}, {"user", "system"})
        self.assertTrue(compiled.requests[0].source.startswith("t.dway:3:"))

    def test_one_unknown_line_rejects_the_whole_file(self):
        program = language.parse_text("setup:\n  lock the screen after 10 minutes\n  dance\napps:\n  nosuchrecipe\nexact:\n  @ nope.nope a=1\n  @ firewall.open_port port=99999\n", "t.dway")
        compiled = planner.compile_program(program, self.ctx, self.library)
        self.assertIsNone(compiled.plan)
        self.assertEqual(len(compiled.problems), 3)
        self.assertIn("t.dway:3: not understood: dance", compiled.problems[0])
        self.assertIn("t.dway:5: no recipe called nosuchrecipe", compiled.problems[1])
        self.assertIn("t.dway:7: no such action: nope.nope", compiled.problems[2])
        program = language.parse_text("exact:\n  @ firewall.open_port port=99999\n", "t.dway")
        compiled = planner.compile_program(program, self.ctx, self.library)
        self.assertIsNone(compiled.plan) if compiled.plan is None else self.assertFalse(compiled.ok)
        self.assertTrue(any("port" in p for p in compiled.problems))

    def test_every_example_checks(self):
        for path in sorted(EXAMPLES.glob("*.dway")):
            with self.subTest(path.name):
                compiled = planner.compile_program(language.parse(path), self.ctx, self.library)
                self.assertEqual(compiled.problems, [])
                self.assertTrue(compiled.ok)
                self.assertGreaterEqual(len(compiled.plan.steps), 3)


class ExportTests(WayTestCase):
    def test_export_lists_what_is_installed_and_checks_back(self):
        def run(argv, **kwargs):
            if argv[0] == "dpkg-query":
                return subprocess.CompletedProcess(argv, 0, "clamav installed\nclamav-freshclam installed\nvlc deinstall\n", "")
            if argv[0] == "flatpak":
                return subprocess.CompletedProcess(argv, 0, "org.signal.Signal\n", "")
            return subprocess.CompletedProcess(argv, 0, "", "")

        text = export.export_text(self.ctx, "en", self.library, run=run, hostname="desk", today=__import__("datetime").date(2026, 10, 22))
        self.assertIn("diamond: desk", text)
        self.assertIn("  antivirus\n", text)
        self.assertIn("  signal\n", text)
        self.assertNotIn("  video-player\n", text)
        self.assertIn("@ session.lock minutes=", text)
        self.assertIn("@ updates.auto enabled=true", text)
        self.assertNotIn("psk", text.lower())
        self.assertNotIn("timezone=\n", text)   # an empty value is not exported
        path = self.write("desk.dway", text)
        compiled = planner.compile_program(language.parse(path), self.ctx, self.library)
        self.assertEqual(compiled.problems, [])
        self.assertTrue(compiled.ok)
        hebrew = export.export_text(self.ctx, "he", self.library, run=run, hostname="desk")
        self.assertIn("מדויק:", hebrew)
        self.assertIn("# נעילת המסך", hebrew)


class CliTests(WayTestCase):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), mock.patch.object(planner, "load_library", lambda: self.library), \
                mock.patch.object(cli, "EXAMPLES", EXAMPLES), mock.patch.dict(os.environ, {"LANG": "en_US.UTF-8"}):
            code = cli.main(["dai-way", *args], self.ctx)
        return code, out.getvalue(), err.getvalue()

    def test_check_plan_examples_and_errors(self):
        good = self.write("g.dway", "diamond: g\nsetup:\n  lock the screen after 10 minutes\n  block the camera\n")
        code, out, err = self.run_cli("check", str(good))
        self.assertEqual((code, err), (0, ""))
        self.assertIn("✓ g: 2 steps", out)
        code, out, _ = self.run_cli("plan", str(good))
        self.assertEqual(code, 0)
        self.assertIn("Diamond's Way — g", out)
        self.assertIn("dry run", out)
        bad = self.write("b.dway", "setup:\n  dance\n")
        code, _, err = self.run_cli("check", str(bad))
        self.assertEqual(code, 2)
        self.assertIn("b.dway:2: not understood: dance", err)
        code, _, err = self.run_cli("check", str(self.base / "missing.dway"))
        self.assertEqual(code, 2)
        self.assertIn("cannot read", err)
        code, out, _ = self.run_cli("examples")
        self.assertEqual(code, 0)
        self.assertIn("home.dway", out)
        self.assertEqual(self.run_cli("--version")[0], 0)
        self.assertEqual(self.run_cli("dance")[0], 2)

    def test_apply_goes_through_tune_with_a_journal_label(self):
        good = self.write("g.dway", "diamond: quiet desk\nsetup:\n  lock the screen after 10 minutes\n")
        labels = []

        def fake_apply(plan, ctx, label):
            from dai_tune.cli import ApplyResult
            labels.append(label)
            return ApplyResult(True, entry_id="w1")

        with mock.patch("dai_tune.cli.apply_plan", fake_apply):
            code, out, _ = self.run_cli("apply", str(good), "--yes")
        self.assertEqual(code, 0)
        self.assertEqual(labels, ["Way: quiet desk"])
        self.assertIn("✓ Applied", out)


if __name__ == "__main__":
    unittest.main()
