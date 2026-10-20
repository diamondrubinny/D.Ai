# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The sentence that lets this user run virtual machines (vm.kvm_access, docs/VM.md): parsed in Hebrew and
English, validated, applied with usermod, and undone with gpasswd only when the user was not in kvm before."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dai_tune import parser
from dai_tune.catalog import CATALOG, ValidationError
from dai_tune.context import Context


class Runner:
    def __init__(self, groups="dana cdrom"):
        self.groups, self.calls = groups, []

    def __call__(self, argv):
        self.calls.append(list(argv))
        if argv[:2] == ["id", "-nG"]:
            return subprocess.CompletedProcess(argv, 0, self.groups + "\n", "")
        return subprocess.CompletedProcess(argv, 0, "", "")


class KvmAccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.runner = Runner()
        self.ctx = Context(root=Path(self.tmp.name), home=Path(self.tmp.name), runner=self.runner)
        self.spec = CATALOG["vm.kvm_access"]

    def test_sentences_in_both_languages(self):
        with mock.patch("getpass.getuser", return_value="dana"):
            for text in ("allow virtual machines", "enable virtualization", "turn on kvm", "אפשר מכונות וירטואליות",
                         "הפעל וירטואליזציה"):
                result = parser.parse(text)
                self.assertEqual([(r.action, r.params) for r in result.requests],
                                 [("vm.kvm_access", {"user": "dana", "enabled": True})], text)
                self.assertEqual(result.unknown, [])
            off = parser.parse("turn off virtual machines").requests[0]
            self.assertEqual(off.params, {"user": "dana", "enabled": False})

    def test_validation(self):
        self.assertEqual(self.spec.validate({"user": "dana", "enabled": True}, self.ctx), {"user": "dana", "enabled": True})
        for bad in ({"user": "root", "enabled": True}, {"user": "Dana; rm", "enabled": True}, {"user": "", "enabled": True},
                    {"user": "dana", "enabled": True, "extra": 1}):
            with self.assertRaises(ValidationError):
                self.spec.validate(bad, self.ctx)

    def test_apply_and_undo(self):
        params = self.spec.validate({"user": "dana", "enabled": True}, self.ctx)
        extra = self.spec.capture(params, self.ctx)
        self.assertEqual(extra, {"was_in_kvm": False})
        self.spec.apply(params, self.ctx)
        self.assertIn(["usermod", "-aG", "kvm", "dana"], self.runner.calls)
        self.spec.restore(params, self.ctx, extra)
        self.assertIn(["gpasswd", "-d", "dana", "kvm"], self.runner.calls)
        self.assertEqual(self.spec.risk(params), "medium")
        self.assertEqual(self.spec.effect(params), "weakens")
        self.assertIn("dana", self.spec.summary(params, "he"))

    def test_undo_keeps_a_user_who_was_in_kvm_already(self):
        self.runner.groups = "dana kvm"
        params = self.spec.validate({"user": "dana", "enabled": False}, self.ctx)
        extra = self.spec.capture(params, self.ctx)
        self.assertEqual(extra, {"was_in_kvm": True})
        self.spec.apply(params, self.ctx)
        self.assertIn(["gpasswd", "-d", "dana", "kvm"], self.runner.calls)
        self.runner.calls.clear()
        self.spec.restore(params, self.ctx, extra)
        self.assertEqual(self.runner.calls, [["usermod", "-aG", "kvm", "dana"]])



class MachineSentenceTests(unittest.TestCase):
    """docs/VM.md stage 3: "start Windows" and "snapshot Windows before the update" go through dai-vm as the person."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.runner = Runner()
        self.ctx = Context(root=self.home / "root", home=self.home, runner=self.runner)

    def machine(self, name):
        folder = self.home / ".local/share/dai/vm/machines" / name
        folder.mkdir(parents=True)
        (folder / "machine.json").write_text("{}")

    def test_sentences(self):
        cases = {"start windows": ("vm.power", {"name": "", "action": "start"}),
                 "הפעל את ווינדוס": ("vm.power", {"name": "", "action": "start"}),
                 "shut down windows": ("vm.power", {"name": "", "action": "stop"}),
                 "כבה את המכונה בשם office": ("vm.power", {"name": "office", "action": "stop"}),
                 "start the machine called office": ("vm.power", {"name": "office", "action": "start"}),
                 "snapshot windows before the update": ("vm.snapshot", {"name": "", "label": "before-update"}),
                 "צילום מצב של ווינדוס לפני העדכון": ("vm.snapshot", {"name": "", "label": "before-update"}),
                 "תמונת מצב של ווינדוס": ("vm.snapshot", {"name": "", "label": ""})}
        for text, expected in cases.items():
            result = parser.parse(text)
            self.assertEqual([(r.action, r.params) for r in result.requests], [expected], text)
            self.assertEqual(result.unknown, [], text)
        self.assertEqual(parser.parse("allow virtual machines").requests[0].action, "vm.kvm_access")

    def test_the_machine_is_resolved_and_the_commands_run(self):
        power, snap = CATALOG["vm.power"], CATALOG["vm.snapshot"]
        with self.assertRaises(ValidationError):  # no machine yet
            power.validate({"name": "", "action": "start"}, self.ctx)
        self.machine("win11")
        params = power.validate({"name": "", "action": "start"}, self.ctx)
        self.assertEqual(params, {"name": "win11", "action": "start"})
        power.apply(params, self.ctx)
        self.assertEqual(self.runner.calls[-1], ["dai-vm", "start", "win11"])
        power.restore(params, self.ctx, {})
        self.assertEqual(self.runner.calls[-1], ["dai-vm", "stop", "win11"])
        self.machine("office")
        with self.assertRaises(ValidationError) as caught:  # two machines: say which
            power.validate({"name": "", "action": "start"}, self.ctx)
        self.assertIn("office", str(caught.exception))
        with self.assertRaises(ValidationError):
            power.validate({"name": "nope", "action": "start"}, self.ctx)
        with self.assertRaises(ValidationError):
            power.validate({"name": "office", "action": "dance"}, self.ctx)
        params = snap.validate({"name": "office", "label": "before-update"}, self.ctx)
        snap.apply(params, self.ctx)
        self.assertEqual(self.runner.calls[-1], ["dai-vm", "snapshot", "office", "take", "before-update", "--note", "D.Ai Tune"])
        snap.restore(params, self.ctx, {})
        self.assertEqual(self.runner.calls[-1], ["dai-vm", "snapshot", "office", "delete", "before-update"])
        dated = snap.validate({"name": "office", "label": ""}, self.ctx)["label"]
        self.assertRegex(dated, r"^\d{4}-\d{2}-\d{2}-\d{4}$")
        with self.assertRaises(ValidationError):
            snap.validate({"name": "office", "label": "bad name"}, self.ctx)


if __name__ == "__main__":
    unittest.main()
