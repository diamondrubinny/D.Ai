# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dai_raz import checks, cli


class Fake:
    """A healthy D.Ai system; tests break one thing at a time."""

    def __init__(self, root: Path):
        self.root = root
        self.missing: set[str] = set()
        self.version_exit = 0
        self.enabled = {"dai-daid.socket": "enabled", "dai-evolve.timer": "enabled"}
        self.nftables = "active"
        self.verify = ""
        self.calls: list[list[str]] = []
        (root / "proc/4242").mkdir(parents=True)
        (root / "proc/4242/maps").write_text("\n".join(f"7f /usr/lib/lxqt-panel/{p}" for p in checks.PANEL_PLUGINS))
        (root / "etc/apt/apt.conf.d").mkdir(parents=True)
        (root / "etc/apt/apt.conf.d/20auto-upgrades").write_text('APT::Periodic::Unattended-Upgrade "1";\n')

    def which(self, name):
        return None if name in self.missing else f"/usr/bin/{name}"

    def run(self, argv):
        self.calls.append(argv)
        out = ""
        code = 0
        if argv[1:] == ["--version"]:
            out, code = f"{argv[0]} 0.1.0 — Diamond Rubinny (d.Ai)", self.version_exit
        elif argv[0] == "pgrep":
            out = "4242\n"
        elif argv[:3] == ["systemctl", "--user", "is-enabled"]:
            out = self.enabled.get(argv[3], "disabled") + "\n"
        elif argv[:2] == ["systemctl", "is-active"]:
            out = self.nftables + "\n"
        elif argv[0] == "dpkg-query":
            out = "install ok installed" if argv[-1] != "dai-panel-plugin" else "unknown ok not-installed"
        elif argv[:2] == ["dpkg", "--verify"]:
            out = self.verify
        return subprocess.CompletedProcess(argv, code, out, "")

    def system(self):
        return checks.System(run=self.run, which=self.which, root=self.root)


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fake = Fake(Path(self.tmp.name))

    def by_id(self, results):
        return {r.id: r for r in results}

    def test_a_healthy_system(self):
        with mock.patch.object(checks, "protected_files",
                               lambda s: checks.Result("files", "config", "ok")):
            results = self.by_id(checks.run_all(self.fake.system()))
        for name in ("commands", "panel", "services", "packages", "firewall", "updates", "languages"):
            self.assertEqual(results[name].status, "ok", (name, results[name]))
        verify = next(c for c in self.fake.calls if c[:2] == ["dpkg", "--verify"])
        self.assertEqual(verify[2:], ["dai-apps", "dai-ruby"])  # only installed packages
        self.assertTrue(all(isinstance(c, list) for c in self.fake.calls))  # never a shell

    def test_each_kind_of_breakage_is_found(self):
        self.fake.missing.add("dai-mom")
        self.fake.enabled["dai-evolve.timer"] = "disabled"
        self.fake.nftables = "inactive"
        self.fake.verify = ("??5??????   /usr/lib/dai/dai_mom/actions.py\n"
                            "??5?????? c /etc/firefox/policies/policies.json\n")
        (self.fake.root / "proc/4242/maps").write_text("libdaicommand.so")
        (self.fake.root / "etc/apt/apt.conf.d/20auto-upgrades").write_text('APT::Periodic::Unattended-Upgrade "0";\n')
        results = self.by_id(checks.run_all(self.fake.system()))
        self.assertIn("dai-mom: missing", results["commands"].items)
        self.assertEqual(results["services"].items, ["dai-evolve.timer: disabled"])
        self.assertEqual(results["firewall"].status, "failed")
        self.assertEqual(results["updates"].status, "failed")
        self.assertEqual(results["packages"].items, ["/usr/lib/dai/dai_mom/actions.py"])  # the user's conffile is theirs
        self.assertEqual(results["panel"].items, ["libdaistatus.so", "libdaiclock.so"])

    def test_protected_files(self):
        root = self.fake.root
        for name in checks.PROTECTED_FILES:
            path = root / name.lstrip("/")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}" if name.endswith(".json") else "x")
            os.chmod(path, 0o644)
        system = self.fake.system()
        owner_ok = os.getuid() == 0
        result = checks.protected_files(system)
        if owner_ok:
            self.assertEqual(result.status, "ok", result.items)
        policies = root / "etc/firefox/policies/policies.json"
        policies.write_text("{broken")
        os.chmod(policies, 0o666)
        items = checks.protected_files(system).items
        self.assertIn("/etc/firefox/policies/policies.json: writable by others", items)
        self.assertIn("/etc/firefox/policies/policies.json: not valid JSON", items)

    def test_no_panel_is_not_a_failure(self):
        self.fake.run = lambda argv: subprocess.CompletedProcess(argv, 1, "", "")
        self.assertEqual(checks.panel(self.fake.system()).status, "skipped")

    def test_a_check_that_crashes_does_not_hide_the_rest(self):
        def boom(system):
            raise RuntimeError("bug")

        with mock.patch.object(checks, "CHECKS", (boom, checks.languages)):
            results = checks.run_all(self.fake.system())
        self.assertEqual([r.status for r in results], ["failed", "ok"])


class CliTests(unittest.TestCase):
    def test_saves_privately_and_shows_in_hebrew(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "raz"
            results = [checks.Result("firewall", "security", "ok", "nftables active"),
                       checks.Result("commands", "components", "failed", "18 commands", ["dai-mom: missing"])]
            cli.save(results, directory)
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            self.assertEqual((directory / "last.json").stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads((directory / "last.json").read_text())["results"][1]["items"], ["dai-mom: missing"])
            shown = cli.show(results, "he")
            self.assertIn("✓ חומת האש פועלת", shown)
            self.assertIn("✗ פקודות D.Ai עולות", shown)
            self.assertIn("1 עברו · 1 נכשלו", shown)

    def test_exit_code_and_version(self):
        import contextlib
        import io

        out = io.StringIO()
        failing = [checks.Result("firewall", "security", "failed")]
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(out), \
                mock.patch.dict(os.environ, {"XDG_STATE_HOME": tmp}), mock.patch.object(cli, "run_all", lambda: failing):
            self.assertEqual(cli.main(["dai-raz", "check", "--json"]), 1)
            self.assertEqual(cli.main(["dai-raz", "last"]), 0)
            self.assertEqual(cli.main(["dai-raz", "forget"]), 0)
            self.assertFalse((Path(tmp) / "dai/raz").exists())
            self.assertEqual(cli.main(["dai-raz", "--version"]), 0)
        self.assertIn("Diamond Rubinny (d.Ai)", out.getvalue())


if __name__ == "__main__":
    unittest.main()
