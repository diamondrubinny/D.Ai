# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""D.Ai Store (docs/BEYOND.md §9): the catalog over Forge's recipes, Flathub's index, and the window."""
import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from dai_forge import recipes
from dai_tune.context import Context
from dai_tune.planner import build_plan

from dai_store import catalog, cli

BUILTIN = Path(__file__).resolve().parents[2] / "dai-forge" / "data" / "recipes"


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.ctx = Context(root=base / "root", home=base / "home",
                           runner=lambda argv: subprocess.CompletedProcess(argv, 0, "", ""), lang="en")
        (base / "home").mkdir()
        self.library = recipes.load_library({"admin": base / "admin", "builtin": BUILTIN, "user": base / "user"})
        self.items = catalog.recipe_items(self.library)


class CatalogTests(StoreTestCase):
    def test_every_recipe_has_a_category_and_a_plan(self):
        self.assertGreaterEqual(len(self.items), 25)
        for item in self.items:
            with self.subTest(item.id):
                self.assertIn(item.category, catalog.CATEGORIES)
                self.assertTrue(item.name("he") and item.name("en"))
                self.assertTrue(item.sets_up("en"))
                plan = build_plan(list(item.requests), self.ctx)
                self.assertTrue(plan.ok or plan.errors, item.id)  # understood by the planner (a missing tool is an error, not unknown)
                self.assertFalse(plan.unknown, item.id)
        self.assertEqual(catalog.category_of("language-ru"), "languages")
        self.assertEqual(catalog.category_of("signal"), "talk")
        self.assertEqual(catalog.category_of("something-new"), "more")

    def test_search_in_both_languages(self):
        self.assertIn("signal", [i.id for i in catalog.search(self.items, "סיגנל", "he")])
        self.assertIn("steam", [i.id for i in catalog.search(self.items, "games", "en")])
        self.assertEqual(catalog.search(self.items, "zzzz", "en"), [])
        self.assertEqual(len(catalog.search(self.items, "", "en")), len(self.items))

    def test_flathub_search_parses_flatpaks_own_output(self):
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            out = "org.videolan.VLC\tVLC\tPlays everything\norg.gimp.GIMP\tGIMP\tImage editor\nnot an id\tx\ty\n"
            return subprocess.CompletedProcess(argv, 0, out, "")

        found = catalog.flathub_search("vlc", run)
        self.assertEqual([i.id for i in found], ["org.videolan.VLC", "org.gimp.GIMP"])
        self.assertEqual(calls[0][:2], ["flatpak", "search"])
        item = found[0]
        self.assertEqual([r.action for r in item.requests], ["flatpak.remote", "flatpak.install"])
        self.assertEqual(item.requests[1].params, {"apps": ["org.videolan.VLC"], "remote": "flathub"})
        self.assertTrue(build_plan(list(item.requests), self.ctx).ok)
        self.assertEqual(catalog.flathub_search("v", run), [])  # too short to ask
        self.assertEqual(catalog.flathub_search("vlc", lambda *a, **k: (_ for _ in ()).throw(OSError())), [])

    def test_installed_flatpaks(self):
        run = lambda argv, **k: subprocess.CompletedProcess(argv, 0, "org.signal.Signal\n", "")
        self.assertEqual(catalog.installed_flatpaks(run), {"org.signal.Signal"})

    def test_cli_list_and_search(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cli.main(["dai-store", "list"], self.library), 0)
        text = out.getvalue()
        self.assertIn("Talk and meet", text)
        self.assertIn("Signal messenger", text)
        self.assertIn("Install from Flathub: org.signal.Signal", text)
        with mock.patch.object(catalog, "flathub_search", lambda term: []), \
                mock.patch.object(cli, "flathub_search", lambda term: []):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["dai-store", "search", "vlc"], self.library), 1)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["dai-store", "--version"]), 0)
            self.assertEqual(cli.main(["dai-store", "dance"]), 2)


class WindowTests(StoreTestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PyQt6.QtWidgets import QApplication
        except ImportError:
            raise unittest.SkipTest("PyQt6 is missing")
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        from dai_store import gui
        self.gui = gui
        self.window = gui.StoreWindow("en", self.ctx, admin=True, items=self.items,
                                      flathub=lambda term: [catalog.flathub_item("org.videolan.VLC", "VLC", "Plays everything")],
                                      installed=lambda: {"org.videolan.VLC"})
        self.addCleanup(self.window.deleteLater)

    def test_every_control_is_accessible(self):
        from dai_raz.a11y import assert_accessible
        self.qt.setStyleSheet(self.gui.STYLE)
        self.addCleanup(self.qt.setStyleSheet, "")
        assert_accessible(self, self.window, touch=True)

    def test_search_and_categories_filter_the_cards(self):
        self.assertIn("signal", self.window.cards)
        self.window.pick_category("games")
        self.assertIn("steam", self.window.cards)
        self.assertNotIn("signal", self.window.cards)
        self.window.pick_category("")
        self.window.search.setText("vpn")
        self.assertTrue({"openvpn", "wireguard", "cisco-vpn"} <= set(self.window.cards))
        self.window.search.setText("zzzz")
        self.assertEqual(self.window.cards, {})
        self.assertTrue(self.window.empty.isVisibleTo(self.window))

    def test_flathub_results_join_the_list_with_installed_marked(self):
        self.window.search.setText("vlc")
        self.window.search_flathub()
        self.wait(lambda: "org.videolan.VLC" in getattr(self.window, "cards", {}))
        self.assertIn("org.videolan.VLC", self.window.installed_apps)

    def test_set_up_shows_the_plan_then_applies_through_tune(self):
        from dai_tune.cli import ApplyResult
        applied = []

        def fake_apply(plan, ctx, label):
            applied.append(label)
            return ApplyResult(True, entry_id="s1")

        signal = next(i for i in self.items if i.id == "signal")
        with mock.patch.object(self.gui, "apply_plan", fake_apply):
            self.window.show_plan(signal)
            self.assertEqual([s.action for s in self.window.plan.steps], ["flatpak.remote", "flatpak.install"])
            self.assertTrue(self.window.apply_button.isEnabled())
            self.window.apply()
            self.wait(lambda: applied)
        self.assertEqual(applied, ["Store: signal"])
        self.wait(lambda: self.window.last_entry == "s1")
        self.window.admin = False
        self.window.show_plan(signal)
        self.assertFalse(self.window.apply_button.isEnabled())

    def test_hebrew_is_right_to_left(self):
        from PyQt6.QtCore import Qt
        window = self.gui.StoreWindow("he", self.ctx, admin=True, items=self.items)
        self.addCleanup(window.deleteLater)
        self.assertEqual(window.layoutDirection(), Qt.LayoutDirection.RightToLeft)
        self.assertEqual(window.windowTitle(), "חנות D.Ai")

    def wait(self, condition, timeout=5.0):
        import time
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.qt.processEvents()
            time.sleep(0.01)
        self.assertTrue(condition())


if __name__ == "__main__":
    unittest.main()
