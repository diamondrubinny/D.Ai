# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
import os
import signal
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dai_mom import actions, apps, procs, text

UID = 1000


class FakeProc:
    """A /proc tree on disk: enough of stat, status, comm, cmdline and smaps_rollup."""

    def __init__(self, root: Path):
        self.root = root
        (root / "proc").mkdir(parents=True)

    def add(self, pid, ppid, name, cmdline, uid=UID, start=100, ticks=0, pss_kb=1024, stat_name=None, cgroup=""):
        base = self.root / "proc" / str(pid)
        base.mkdir(exist_ok=True)
        fields = ["S", str(ppid)] + ["0"] * 9 + [str(ticks), "0"] + ["0"] * 6 + [str(start)] + ["0"] * 10
        (base / "stat").write_text(f"{pid} ({stat_name or name}) " + " ".join(fields))
        (base / "status").write_text(f"Name:\t{name}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n")
        (base / "comm").write_text(name + "\n")
        (base / "cmdline").write_text("\0".join(cmdline) + ("\0" if cmdline else ""))
        (base / "cgroup").write_text(f"0::/user.slice/{cgroup or 'session.scope'}\n")
        (base / "smaps_rollup").write_text(f"Rss:  {pss_kb * 2} kB\nPss:  {pss_kb} kB\n")

    def remove(self, pid):
        base = self.root / "proc" / str(pid)
        for f in base.iterdir():
            f.unlink()
        base.rmdir()


def desktop(directory: Path, name, body):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.desktop").write_text("[Desktop Entry]\nType=Application\n" + body)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fake = FakeProc(self.root)
        apps_dir = self.root / "share/applications"
        desktop(apps_dir, "firefox-esr", "Name=Firefox ESR\nName[he]=פיירפוקס\nComment=Browse the Web\n"
                                         "Exec=/usr/lib/firefox-esr/firefox-esr %u\nIcon=firefox-esr\n")
        desktop(apps_dir, "qterminal", "Name=QTerminal\nExec=qterminal\nIcon=utilities-terminal\n")
        desktop(apps_dir, "dai-heal", "Name=Help & repair\nName[he]=עזרה ותיקון\nExec=dai-heal\n")
        desktop(apps_dir, "org.gimp.GIMP", "Name=GIMP\nExec=/usr/bin/flatpak run --branch=stable org.gimp.GIMP @@u %U @@\n")
        self.dirs = [apps_dir]
        f = self.fake
        f.add(1, 0, "systemd", ["/sbin/init"], uid=0)
        f.add(2, 0, "kthreadd", [], uid=0)
        f.add(3, 2, "kworker/0:1", [], uid=0)
        f.add(500, 1, "systemd", ["/usr/lib/systemd/systemd", "--user"])
        f.add(600, 500, "labwc", ["labwc"])
        f.add(601, 600, "lxqt-panel", ["lxqt-panel"])
        f.add(700, 601, "firefox-esr", ["/usr/lib/firefox-esr/firefox-esr"], pss_kb=400_000)
        f.add(701, 700, "Isolated Web Co", ["/usr/lib/firefox-esr/firefox-esr", "-contentproc"], pss_kb=200_000,
              stat_name="Isolated Web Co")
        f.add(702, 700, "Web Content", ["/usr/lib/firefox-esr/firefox-esr", "-contentproc"], pss_kb=100_000)
        f.add(800, 600, "qterminal", ["qterminal"])
        f.add(801, 800, "bash", ["bash"])
        f.add(802, 801, "vim", ["vim", "notes) (x"], stat_name="vim) (x")
        f.add(900, 600, "python3", ["python3", "-I", "-c", "import sys; from dai_heal.cli import main"])
        f.add(950, 500, "pipewire", ["/usr/bin/pipewire"])
        f.add(960, 600, "sleep", ["sleep", "999"])
        scope = "app-flatpak-org.gimp.GIMP-4242.scope"
        f.add(970, 600, "bwrap", ["bwrap", "--args", "40", "gimp"], cgroup=scope)
        f.add(971, 970, "gimp", ["/app/bin/gimp"], cgroup=scope)
        f.add(1000, 1, "sshd", ["sshd"], uid=0)

    def grouped(self, lang="en", recording=None):
        snap = procs.snapshot(self.root)
        return apps.group(snap, apps.load_desktop_apps(self.dirs, lang), uid=UID, recording=recording)


class ProcTests(Base):
    def test_reads_names_with_spaces_and_parentheses(self):
        snap = procs.snapshot(self.root)
        self.assertEqual(snap.processes[802].ppid, 801)
        self.assertEqual(snap.processes[701].name, "Isolated Web Co")
        self.assertNotIn(2, snap.processes)  # kernel threads are not shown
        self.assertNotIn(3, snap.processes)
        self.assertEqual(snap.processes[700].memory, 400_000 * 1024)  # PSS, not RSS

    def test_cpu_counts_only_the_same_process(self):
        first = procs.snapshot(self.root, now=10.0)
        self.fake.add(700, 601, "firefox-esr", ["/usr/lib/firefox-esr/firefox-esr"], ticks=100)
        self.fake.add(960, 600, "sleep", ["sleep", "999"], ticks=500, start=999)  # pid reused
        with mock.patch("os.cpu_count", return_value=1), mock.patch("os.sysconf", return_value=100):
            second = procs.snapshot(self.root, first, now=11.0)
        self.assertEqual(second.processes[700].cpu, 100.0)
        self.assertEqual(second.processes[960].cpu, 0.0)

    def test_identity_check_catches_reused_pids(self):
        seen = procs.snapshot(self.root).processes[960]
        self.assertIsNotNone(procs.is_same(self.root, seen.key))
        self.fake.add(960, 600, "evil", ["evil"], start=5000)
        self.assertIsNone(procs.is_same(self.root, seen.key))


class GroupTests(Base):
    def test_processes_become_the_apps_people_know(self):
        found = {a.key: a for a in self.grouped()}
        firefox = found["firefox-esr"]
        self.assertEqual(sorted(p.pid for p in firefox.processes), [700, 701, 702])
        self.assertEqual(firefox.memory, 700_000 * 1024)
        self.assertEqual([p.pid for p in firefox.roots], [700])
        self.assertEqual(sorted(p.pid for p in found["qterminal"].processes), [800, 801, 802])  # vim too
        self.assertEqual([p.pid for p in found["dai-heal"].processes], [900])
        self.assertEqual(found["dai-heal"].name, "Help & repair")
        self.assertTrue(found["org.gimp.GIMP"].sandboxed)
        self.assertEqual(sorted(p.pid for p in found["org.gimp.GIMP"].processes), [970, 971])
        self.assertFalse(found["proc:sleep"].is_app)
        self.assertTrue(found["proc:pipewire"].protected)
        self.assertTrue(found["proc:labwc"].protected)
        self.assertNotIn("proc:sshd", found)  # other users' processes are not ours to manage
        self.assertTrue(list(found.values())[0].is_app)  # apps first, the biggest at the top

    def test_hebrew_names_and_recording_badge(self):
        found = {a.key: a for a in self.grouped("he", recording=["Firefox"])}
        self.assertEqual(found["firefox-esr"].name, "פיירפוקס")
        self.assertTrue(found["firefox-esr"].recording)
        self.assertFalse(found["qterminal"].recording)
        self.assertIn("מקליט", text.notes(found["firefox-esr"], "he"))

    def test_exec_lines(self):
        self.assertEqual(apps.exec_keys("env GDK_BACKEND=x11 /usr/bin/foo --bar %U"), {"foo"})
        self.assertEqual(apps.exec_keys("flatpak run --branch=stable org.gimp.GIMP"), {"org.gimp.GIMP"})
        self.assertEqual(apps.exec_keys('broken "quote'), set())

    def test_find(self):
        found = self.grouped()
        self.assertEqual(apps.find(found, "701").key, "firefox-esr")
        self.assertEqual(apps.find(found, "sleep").key, "proc:sleep")
        self.assertEqual(apps.find(found, "QTERMINAL").key, "qterminal")
        self.assertIsNone(apps.find(found, "nothing"))

    def test_plain_language(self):
        found = {a.key: a for a in self.grouped()}
        line = text.describe(found["firefox-esr"], "en")
        self.assertIn("Firefox ESR · Browse the Web · 684 MB", line)
        self.assertIn("3 processes", line)
        self.assertEqual(text.size(int(1.25 * 1024 ** 3)), "1.2 GB")


class ActionTests(Base):
    def setUp(self):
        super().setUp()
        self.sent = []
        self.kill = lambda pid, sig: self.sent.append((pid, sig))

    def close(self, key, **kwargs):
        app = {a.key: a for a in self.grouped()}[key]
        return actions.close(app, root=self.root, kill=self.kill, uid=UID, **kwargs)

    def test_close_asks_the_top_process_and_force_hits_all(self):
        self.close("firefox-esr")
        self.assertEqual(self.sent, [(700, signal.SIGTERM)])
        self.sent.clear()
        self.close("firefox-esr", force=True, confirmed=True)
        self.assertEqual(sorted(self.sent), [(700, signal.SIGKILL), (701, signal.SIGKILL), (702, signal.SIGKILL)])

    def test_force_needs_a_yes(self):
        with self.assertRaisesRegex(actions.Refused, "force_confirm"):
            self.close("firefox-esr", force=True)
        self.assertEqual(self.sent, [])

    def test_the_session_is_protected(self):
        with self.assertRaisesRegex(actions.Refused, "protected_confirm"):
            self.close("proc:pipewire")
        with self.assertRaisesRegex(actions.Refused, "protected_force"):
            self.close("proc:labwc", force=True, confirmed=True)
        self.close("proc:pipewire", confirmed=True)
        self.assertEqual(self.sent, [(950, signal.SIGTERM)])

    def test_a_reused_pid_is_never_hit(self):
        app = {a.key: a for a in self.grouped()}["proc:sleep"]
        self.fake.remove(960)
        self.fake.add(960, 1, "sshd", ["sshd"], uid=0, start=7777)  # someone else got the number
        result = actions.close(app, root=self.root, kill=self.kill, uid=UID)
        self.assertEqual(self.sent, [])
        self.assertEqual(result.gone, [960])

    def test_never_as_root(self):
        app = {a.key: a for a in self.grouped()}["proc:sleep"]
        with self.assertRaisesRegex(actions.Refused, "root"):
            actions.close(app, root=self.root, kill=self.kill, uid=0)

    def test_a_real_process(self):
        import subprocess

        if os.getuid() == 0:
            self.skipTest("MOM never acts as root")
        child = subprocess.Popen(["sleep", "30"])
        self.addCleanup(child.kill)
        snap = procs.snapshot()
        app = apps.App(key="proc:sleep", name="sleep", processes=[snap.processes[child.pid]], is_app=False)
        actions.close(app)
        self.assertEqual(child.wait(5), -signal.SIGTERM)


class WindowTests(Base):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PyQt6.QtWidgets import QApplication
        except ImportError:
            raise unittest.SkipTest("PyQt6 is missing")
        cls.app = QApplication.instance() or QApplication([])

    def window(self, lang="en", asked=True):
        from dai_mom import gui

        self.closed = []
        self.questions = []

        def ask(parent, title, body, action, lang):
            self.questions.append(title)
            return asked

        def source():
            return self.grouped(lang), gui.Perf(cpu=12.5, mem_total=8 * 1024 ** 3, mem_used=3 * 1024 ** 3,
                                                disk_total=100 * 1024 ** 3, disk_free=40 * 1024 ** 3)

        def closer(app, force=False, confirmed=False):
            self.closed.append((app.key, force, confirmed))

        return gui.MomWindow(lang, source=source, closer=closer, ask=ask, spawn=lambda argv: None, interval=0)

    def test_apps_rows_speak_plainly(self):
        from PyQt6.QtCore import Qt

        window = self.window()
        first = window.tree.topLevelItem(0)
        self.assertEqual(first.text(0), "Firefox ESR")
        spoken = first.data(0, Qt.ItemDataRole.AccessibleTextRole)
        self.assertIn("Firefox ESR, 684 MB memory, 0 percent CPU", spoken)
        last = window.tree.topLevelItem(window.tree.topLevelItemCount() - 1)
        self.assertEqual(last.text(0), "Other processes")
        self.assertIn("Memory: 3.0 GB of 8.0 GB in use", window.bars["memory"][0].text())
        self.assertTrue(window.bars["swap"][1].isHidden())  # no swap, no empty bar

    def test_close_and_force_with_questions(self):
        window = self.window()
        window.tree.setCurrentItem(window.items["firefox-esr"])
        window.close_selected(False)
        self.assertEqual(self.closed[-1], ("firefox-esr", False, False))
        self.assertEqual(self.questions, [])
        window.close_selected(True)
        self.assertEqual(self.closed[-1], ("firefox-esr", True, True))
        self.assertEqual(len(self.questions), 1)

    def test_protected_cannot_be_forced_and_needs_a_yes(self):
        window = self.window(asked=False)
        window.tree.setCurrentItem(window._item_for("proc:pipewire"))
        self.assertFalse(window.force_button.isEnabled())
        window.close_selected(False)
        self.assertEqual(self.closed, [])  # the question was answered "no"
        self.assertEqual(len(self.questions), 1)

    def test_refresh_keeps_the_selection_and_filter_works(self):
        window = self.window()
        window.tree.setCurrentItem(window.items["qterminal"])
        window.refresh()
        self.assertEqual(window.selected_app().key, "qterminal")
        window.search.setText("gimp")
        visible = [window.tree.topLevelItem(i).text(0) for i in range(window.tree.topLevelItemCount())
                   if not window.tree.topLevelItem(i).isHidden()]
        self.assertEqual(visible, ["GIMP"])
        window.search.setText("sleep")
        other = window.items["__other__"]
        self.assertFalse(other.isHidden())
        self.assertEqual([other.child(i).text(0) for i in range(other.childCount()) if not other.child(i).isHidden()],
                         ["sleep"])

    def test_hebrew_is_right_to_left(self):
        from PyQt6.QtCore import Qt

        window = self.window("he")
        self.assertEqual(window.layoutDirection(), Qt.LayoutDirection.RightToLeft)
        self.assertEqual(window.windowTitle(), "MOM – מנהל המשימות")
        self.assertEqual(window.items["firefox-esr"].text(0), "פיירפוקס")


class CliTests(unittest.TestCase):
    def test_version_and_help(self):
        import contextlib
        import io

        from dai_mom import cli

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["dai-mom", "--version"]), 0)
            self.assertEqual(cli.main(["dai-mom", "--help"]), 0)
        self.assertIn("Diamond Rubinny (d.Ai)", out.getvalue())
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["dai-mom", "close"]), 2)


if __name__ == "__main__":
    unittest.main()
