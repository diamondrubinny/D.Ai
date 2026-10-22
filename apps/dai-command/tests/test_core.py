# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
import os
import stat
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from dai_command import core


def write_desktop(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


class ParseExecTests(unittest.TestCase):
    def test_strips_field_codes(self):
        self.assertEqual(core.parse_exec("firefox-esr %u"), ("firefox-esr",))
        self.assertEqual(core.parse_exec("app --file=%f %F"), ("app", "--file="))

    def test_keeps_literal_percent_and_quotes(self):
        self.assertEqual(core.parse_exec('sh -c "echo 100%%"'), ("sh", "-c", "echo 100%"))

    def test_invalid_quoting(self):
        self.assertEqual(core.parse_exec('broken "quote'), ())


class DesktopEntryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_localized_name_and_keywords(self):
        path = write_desktop(self.dir, "browser.desktop", """\
            [Desktop Entry]
            Type=Application
            Name=Web Browser
            Name[he]=דפדפן
            Keywords=internet;web;
            Exec=firefox-esr %u
            Icon=firefox-esr
        """)
        app = core.parse_desktop_file(path, "browser.desktop", ["LXQt"], ["he_IL", "he"])
        self.assertIsNotNone(app)
        self.assertEqual(app.name, "דפדפן")
        self.assertIn("web browser", app.search_terms)
        self.assertIn("internet", app.search_terms)
        self.assertEqual(app.exec_args, ("firefox-esr",))

    def test_hebrew_terms_searchable_on_english_system(self):
        path = write_desktop(self.dir, "browser.desktop", """\
            [Desktop Entry]
            Type=Application
            Name=Firefox ESR
            GenericName=Web Browser
            GenericName[he]=דפדפן
            Exec=firefox-esr %u
        """)
        app = core.parse_desktop_file(path, "browser.desktop", ["LXQt"], ["en_US", "en"])
        self.assertEqual(app.name, "Firefox ESR")
        self.assertEqual(core.search_apps([app], "דפדפן"), [app])

    def test_hidden_and_desktop_filters(self):
        cases = {
            "nodisplay.desktop": "NoDisplay=true",
            "hidden.desktop": "Hidden=true",
            "gnome-only.desktop": "OnlyShowIn=GNOME;",
            "not-lxqt.desktop": "NotShowIn=LXQt;",
            "tryexec.desktop": "TryExec=/nonexistent/binary",
        }
        for filename, extra in cases.items():
            path = write_desktop(self.dir, filename, f"""\
                [Desktop Entry]
                Type=Application
                Name=X
                Exec=true
                {extra}
            """)
            with self.subTest(filename):
                self.assertIsNone(core.parse_desktop_file(path, filename, ["LXQt"], []))

    def test_load_apps_first_directory_wins(self):
        user_dir, system_dir = self.dir / "user", self.dir / "system"
        user_dir.mkdir()
        system_dir.mkdir()
        body = "[Desktop Entry]\nType=Application\nName={}\nExec=true\n"
        (user_dir / "app.desktop").write_text(body.format("User copy"))
        (system_dir / "app.desktop").write_text(body.format("System copy"))
        apps = core.load_apps([user_dir, system_dir])
        self.assertEqual([a.name for a in apps], ["User copy"])

    def test_search_ranking(self):
        apps = [
            core.AppEntry("a", "Terminal", ("qterminal",), search_terms=("terminal", "shell")),
            core.AppEntry("b", "Text Editor", ("featherpad",), search_terms=("text editor",)),
            core.AppEntry("c", "Settings", ("lxqt-config",), search_terms=("settings", "system terminal options")),
        ]
        self.assertEqual([a.name for a in core.search_apps(apps, "ter")], ["Terminal", "Settings"])
        self.assertEqual([a.name for a in core.search_apps(apps, "edit")], ["Text Editor"])
        self.assertEqual(core.search_apps(apps, "  "), [])


class CalculatorTests(unittest.TestCase):
    def test_arithmetic(self):
        self.assertEqual(core.calculate("2*(3+4)"), 14)
        self.assertEqual(core.calculate("2^10"), 1024)
        self.assertAlmostEqual(core.calculate("sqrt(16)+pi"), 4 + 3.141592653589793)
        self.assertEqual(core.calculate("15% of 80"), 12)
        self.assertEqual(core.calculate("15% מתוך 80"), 12)

    def test_rejects_non_math_and_unsafe_input(self):
        for text in [
            "firefox",
            "42",
            "__import__('os').system('id')",
            "().__class__",
            "open('/etc/passwd')",
            "2**100000",
            "10**1000*10**1000",
            "1/0",
            "x" * 300,
            "lambda: 1",
        ]:
            with self.subTest(text):
                self.assertIsNone(core.calculate(text))

    def test_format(self):
        self.assertEqual(core.format_number(1234567.0), "1,234,567")
        self.assertEqual(core.format_number(0.1 + 0.2), "0.3")


class LayoutFixTests(unittest.TestCase):
    def test_english_typed_on_hebrew_intent(self):
        self.assertEqual(core.fix_layout("akuo"), ("שלום", "he"))
        self.assertEqual(core.fix_layout("nv bang"), ("מה נשמע", "he"))

    def test_hebrew_typed_on_english_intent(self):
        self.assertEqual(core.fix_layout("יקךךם"), ("hello", "en"))

    def test_convert_whole_selection(self):
        self.assertEqual(core.convert_layout("akuo"), "שלום")
        self.assertEqual(core.convert_layout("nv bang?"), "מה נשמע?")
        self.assertEqual(core.convert_layout("יקךךם"), "hello")
        self.assertEqual(core.convert_layout("akuo 123"), "שלום 123")
        self.assertIsNone(core.convert_layout("123 !?"))

    def test_russian_and_arabic_layouts(self):
        # Tables as in xkb (symbols/ru "common", symbols/ara "basic").
        self.assertEqual(core.fix_layout("ghbdtn", layout="ru"), ("привет", "ru"))
        self.assertEqual(core.fix_layout("руддщ"), ("hello", "en"))
        self.assertEqual(core.convert_layout("vfvf vskf hfve", layout="ru"), "мама мыла раму")
        self.assertEqual(core.fix_layout("lvpfh", layout="ara"), ("مرحبا", "ar"))
        self.assertEqual(core.fix_layout("اثممخ"), ("hello", "en"))
        self.assertEqual(core.convert_layout("bh", layout="ara"), "ﻻا")  # B is the ligature key
        self.assertEqual(core.fix_layout("akuo", layout="il"), ("שלום", "he"))

    def test_the_other_layout_comes_from_the_persons_keyboards(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / "environment"
            env.write_text("XKB_DEFAULT_LAYOUT=us\nDAI_LAYOUTS=us,ru,il\n")
            self.assertEqual(core.other_layout(env), "ru")
            env.write_text("DAI_LAYOUTS=ara,us\n")
            self.assertEqual(core.other_layout(env), "ara")
            self.assertEqual(core.other_layout(Path(tmp) / "missing"), "il")  # D.Ai's default

    def test_fixlayout_print_mode(self):
        from dai_command import fixlayout

        with mock.patch.object(fixlayout, "read_selection", return_value="akuo"), \
                mock.patch("builtins.print") as printed:
            self.assertEqual(fixlayout.main(["dai-fixlayout", "--print"]), 0)
        printed.assert_called_once_with("שלום")
        with mock.patch.object(fixlayout, "read_selection", return_value=""), \
                mock.patch.object(fixlayout, "_notify"):
            self.assertEqual(fixlayout.main(["dai-fixlayout"]), 1)

    def test_not_candidates(self):
        self.assertIsNone(core.fix_layout("a"))
        self.assertIsNone(core.fix_layout("123"))
        self.assertIsNone(core.fix_layout("mixed שלום"))


class HistoryTests(unittest.TestCase):
    def test_dedupe_limit_privacy_and_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = core.History(Path(tmp) / "dai" / "history", limit=3)
            for entry in ["a", "b", "a", "c", "d", " secret", ""]:
                history.add(entry)
            self.assertEqual(history.load(), ["a", "c", "d"])
            mode = stat.S_IMODE(os.stat(history.path).st_mode)
            self.assertEqual(mode, 0o600)


class BuildActionsTests(unittest.TestCase):
    apps = [core.AppEntry("t", "Terminal", ("qterminal",), "utilities-terminal", "Shell", ("terminal",))]

    def test_prefixes(self):
        self.assertEqual(core.build_actions("?how", self.apps)[0].kind, "ai")
        self.assertEqual(core.build_actions(">ls -la", self.apps)[0].payload, "ls -la")
        self.assertEqual(core.build_actions("$sleep 1", self.apps)[0].kind, "run")

    def test_calc_app_layout_and_history(self):
        self.assertEqual(core.build_actions("1+1", self.apps)[0].payload, "2")
        self.assertEqual(core.build_actions("term", self.apps)[0].kind, "app")
        self.assertEqual(core.build_actions("akuo", self.apps)[0].payload, "שלום")
        recent = core.build_actions("", self.apps, ["one", "two"])
        self.assertEqual([a.title for a in recent], ["two", "one"])
        self.assertTrue(all(a.kind == "history" for a in recent))

    def test_tune_prefix_previews_plan(self):
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "dai-tune"))
        with mock.patch.dict(os.environ, {"LANG": "en_US.UTF-8"}):
            rows = core.build_actions("!block the camera and turn off bluetooth", [])
            self.assertEqual([a.title for a in rows], ["Block the camera", "Block Bluetooth"])
            self.assertTrue(all(a.kind == "tune" and a.payload for a in rows))
            self.assertEqual(core.build_actions("!what is this", [])[0].payload, "")

    def test_forge_prefix_previews_recipe_and_app(self):
        import sys

        apps_root = Path(__file__).resolve().parents[2]
        for name in ("dai-tune", "dai-forge"):
            sys.path.insert(0, str(apps_root / name))
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {
            "LANG": "he_IL.UTF-8",
            "DAI_FORGE_BUILTIN": str(apps_root / "dai-forge/data/recipes"),
            "XDG_DATA_HOME": tmp,
            "DAI_APPS_DIR": str(Path(tmp) / "Apps"),
        }):
            from dai_forge import paths

            with mock.patch.object(paths, "BUILTIN_RECIPES", apps_root / "dai-forge/data/recipes"):
                rows = core.build_actions("+תתקין אנטי וירוס", [])
                self.assertEqual(rows[0].title, "אנטי וירוס (ClamAV)")
                self.assertEqual(len(rows), 4)  # heading + 3 steps
                self.assertTrue(all(a.kind == "forge" and a.payload == "תתקין אנטי וירוס" for a in rows))
                build = core.build_actions("+תבנה אפליקציה לרשימת קניות", [])
                self.assertEqual(len(build), 1)
                self.assertIn("ארגז חול", build[0].subtitle)
                self.assertEqual(core.build_actions("+", [])[0].payload, "")

    def test_executable_offers_run_and_terminal(self):
        with mock.patch.object(core.shutil, "which", return_value="/usr/bin/htop"):
            kinds = [a.kind for a in core.build_actions("htop", [])]
        self.assertEqual(kinds[-2:], ["run", "terminal"])


class HealLanguageTests(unittest.TestCase):
    """"Something is not working" in the six other languages opens D.Ai Heal (docs/I18N.md §10)."""

    def test_heal_words(self):
        for text in ("что-то не работает", "Firefox вылетает", "algo no funciona", "quelque chose ne marche pas",
                     "etwas funktioniert nicht", "alguma coisa não funciona", "شيء لا يعمل"):
            with self.subTest(text):
                self.assertTrue(core.HEAL_WORDS.search(core._heal_english(text)))
        self.assertFalse(core.HEAL_WORDS.search(core._heal_english("instala vlc")))

    def test_focus_sentences(self):
        """D.Ai Focus (docs/BEYOND.md §5): the minutes come from the sentence, 25 without one; stop words end it."""
        from unittest import mock
        with mock.patch("shutil.which", lambda name: "/usr/bin/dai-focus" if name == "dai-focus" else None):
            for text, payload in (("focus for 40 minutes", "40"), ("פוקוס ל-15 דקות", "15"), ("מצב ריכוז", "25"),
                                  ("focus", "25"), ("בלי הפרעות", "25"), ("focus for 999 minutes", "180"),
                                  ("stop focus", "stop"), ("סיים את הפוקוס", "stop"),
                                  ("game mode", "game"), ("מצב משחק", "game"), ("stop game mode", "game-stop"),
                                  ("סיים מצב משחק", "game-stop")):
                with self.subTest(text):
                    actions = core.focus_actions(text)
                    self.assertIsNotNone(actions)
                    self.assertEqual((actions[0].kind, actions[0].payload), ("focus", payload))
            self.assertIsNone(core.focus_actions("find my photos"))
        with mock.patch("shutil.which", lambda name: None):
            self.assertIsNone(core.focus_actions("focus for 40 minutes"))  # not installed: no row

    def test_store_words(self):
        for text in ("store", "app store", "open store", "software", "חנות", "חנות אפליקציות", "תוכנות"):
            with self.subTest(text):
                self.assertTrue(core.STORE_WORDS.search(text.strip()))
        self.assertFalse(core.STORE_WORDS.search("grocery store list"))
        self.assertFalse(core.STORE_WORDS.search("install vlc"))

    def test_settings_words(self):
        for text in ("settings", "Settings", "open settings", "security settings", "הגדרות", "הגדרות אבטחה"):
            with self.subTest(text):
                self.assertTrue(core.SETTINGS_WORDS.search(text.strip()))
        self.assertFalse(core.SETTINGS_WORDS.search("backup settings"))
        self.assertFalse(core.SETTINGS_WORDS.search("what are the settings of firefox"))


if __name__ == "__main__":
    unittest.main()
