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


if __name__ == "__main__":
    unittest.main()
