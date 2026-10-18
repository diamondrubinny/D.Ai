# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from dai_code import ai, cli, edits
from dai_code.project import Project, ProjectError, redact

AUTH = '''def login(user, password):
    if user.check(password):
        return True
    return False
'''


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


class CodeTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(base / "state"), "LANG": "en_US.UTF-8",
                                                "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_AUTHOR_NAME": "t",
                                                "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
                                                "GIT_COMMITTER_EMAIL": "t@example.invalid"})
        self.env.start()
        self.root = (base / "app").resolve()
        (self.root / "src").mkdir(parents=True)
        (self.root / "src" / "auth.py").write_text(AUTH)
        (self.root / "src" / "util.py").write_text("def add(a, b):\n    return a + b\n")
        (self.root / "README.md").write_text("# demo app\n")
        (self.root / ".env").write_text("API_KEY=supersecretvalue123\n")
        (self.root / "node_modules" / "x").mkdir(parents=True)
        (self.root / "node_modules" / "x" / "index.js").write_text("login login login")
        git(self.root, "init", "-q")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "init")
        self.project = Project.open(self.root)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()


class ProjectTests(CodeTestCase):
    def test_root_from_subdirectory(self):
        self.assertEqual(Project.open(self.root / "src").root, self.root)

    def test_refuses_home_as_project(self):
        with mock.patch.object(Path, "home", return_value=self.root / "src"), \
                mock.patch("dai_code.project.find_root", return_value=self.root / "src"), \
                self.assertRaises(ProjectError):
            Project.open(self.root / "src")

    def test_paths_stay_inside_and_avoid_secrets(self):
        self.assertEqual(self.project.resolve("src/auth.py"), self.root / "src" / "auth.py")
        for bad in ["../outside.py", "/etc/passwd", ".env", ".git/config", "keys/id_rsa", "server.pem"]:
            with self.subTest(bad=bad), self.assertRaises(ProjectError):
                self.project.resolve(bad)
        outside = Path(self.tmp.name) / "outside.txt"
        outside.write_text("secret")
        (self.root / "link.txt").symlink_to(outside)
        with self.assertRaises(ProjectError):
            self.project.resolve("link.txt")

    def test_listing_skips_vendor_and_secrets(self):
        files = {str(f) for f in self.project.files()}
        self.assertIn("src/auth.py", files)
        self.assertNotIn(".env", files)
        self.assertFalse(any(f.startswith("node_modules") for f in files))

    def test_redaction(self):
        text = ('aws = "AKIAABCDEFGHIJKLMNOP"\npassword = "hunter2hunter2"\n'
                "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----\n"
                "token: ghp_" + "a" * 36 + "\n")
        clean = redact(text)
        for secret in ("AKIAABCDEFGHIJKLMNOP", "hunter2hunter2", "BEGIN RSA", "ghp_aaaa"):
            self.assertNotIn(secret, clean)
        self.assertIn("password", clean)

    def test_context_prefers_relevant_files_within_budget(self):
        context = self.project.context_for("where is login handled?")
        self.assertTrue(context.startswith("=== src/auth.py ==="))
        self.assertNotIn("supersecretvalue123", context)
        self.assertNotIn("node_modules", context)
        (self.root / "big.py").write_text("login\n" * 10_000)
        self.assertLessEqual(len(self.project.context_for("login", budget=2000)), 2100)

    def test_binary_files_are_not_read(self):
        (self.root / "logo.png").write_bytes(b"\x89PNG\0\0\0")
        self.assertIsNone(self.project.read_text(Path("logo.png")))


def fake_chat(reply, calls=None):
    def chat(messages, schema=None, max_tokens=512, task="general"):
        if calls is not None:
            calls.append({"messages": messages, "schema": schema, "task": task})
        yield reply if isinstance(reply, str) else json.dumps(reply)
    return chat


class CliTestCase(CodeTestCase):
    NEW = AUTH.replace("def login(user, password):\n", "def login(user, password):\n    if not password:\n        return False\n")

    def run_cli(self, *args, chat=None):
        out = io.StringIO()
        with redirect_stdout(out), mock.patch("sys.stderr", io.StringIO()):
            code = cli.main(["dai-code", "--root", str(self.root), *args], chat=chat)
        return code, out.getvalue()


class EditTests(CliTestCase):
    def test_edit_shows_diff_applies_and_undoes(self):
        calls = []
        chat = fake_chat({"summary": "Reject empty passwords", "content": "```python\n" + self.NEW + "```"}, calls)
        code, out = self.run_cli("edit", "src/auth.py", "reject empty passwords", "--yes", chat=chat)
        self.assertEqual(code, 0)
        self.assertIn("+    if not password:", out)
        self.assertEqual((self.root / "src/auth.py").read_text(), self.NEW)
        self.assertEqual(calls[0]["task"], "code")
        self.assertEqual(calls[0]["schema"], ai.EDIT_SCHEMA)
        code, out = self.run_cli("undo")
        self.assertEqual(code, 0)
        self.assertEqual((self.root / "src/auth.py").read_text(), AUTH)

    def test_dry_run_and_refusal_write_nothing(self):
        chat = fake_chat({"summary": "x", "content": self.NEW})
        self.run_cli("edit", "src/auth.py", "x", "--dry-run", chat=chat)
        self.assertEqual((self.root / "src/auth.py").read_text(), AUTH)
        with mock.patch("builtins.input", return_value="n"):
            code, _ = self.run_cli("edit", "src/auth.py", "x", chat=chat)
        self.assertEqual(code, 1)
        self.assertEqual((self.root / "src/auth.py").read_text(), AUTH)

    def test_cannot_edit_secrets_or_outside(self):
        chat = fake_chat({"summary": "x", "content": "pwned"})
        for target in (".env", "../escape.py", ".git/config"):
            with self.subTest(target=target):
                code, _ = self.run_cli("edit", target, "x", "--yes", chat=chat)
                self.assertEqual(code, 1)
        self.assertFalse((Path(self.tmp.name) / "escape.py").exists())

    def test_undo_refuses_if_file_changed_since(self):
        self.run_cli("edit", "src/auth.py", "x", "--yes", chat=fake_chat({"summary": "x", "content": self.NEW}))
        (self.root / "src/auth.py").write_text("changed by hand\n")
        code, _ = self.run_cli("undo")
        self.assertEqual(code, 1)
        self.assertEqual((self.root / "src/auth.py").read_text(), "changed by hand\n")
        code, _ = self.run_cli("undo", "--force")
        self.assertEqual(code, 0)
        self.assertEqual((self.root / "src/auth.py").read_text(), AUTH)

    def test_new_file_undo_removes_it(self):
        self.run_cli("edit", "src/new.py", "create", "--yes", chat=fake_chat({"summary": "new", "content": "x = 1\n"}))
        self.assertTrue((self.root / "src/new.py").exists())
        self.run_cli("undo")
        self.assertFalse((self.root / "src/new.py").exists())

    def test_backups_are_private(self):
        self.run_cli("edit", "src/auth.py", "x", "--yes", chat=fake_chat({"summary": "x", "content": self.NEW}))
        state = edits.state_dir(self.root)
        self.assertEqual(oct(state.stat().st_mode & 0o777), "0o700")
        self.assertEqual(oct((state / "journal.json").stat().st_mode & 0o777), "0o600")

    def test_truncated_reply(self):
        code, _ = self.run_cli("edit", "src/auth.py", "x", "--yes", chat=fake_chat('{"summary": "x", "content": "def'))
        self.assertEqual(code, 1)
        self.assertEqual((self.root / "src/auth.py").read_text(), AUTH)


class AskTests(CliTestCase):
    def test_ask_sends_relevant_redacted_context(self):
        calls = []
        code, out = self.run_cli("ask", "where", "is", "login", "handled?", chat=fake_chat("In src/auth.py", calls))
        self.assertEqual(code, 0)
        prompt = calls[0]["messages"][1]["content"]
        self.assertIn("src/auth.py", prompt)
        self.assertNotIn("supersecretvalue123", prompt)
        self.assertIn("In src/auth.py", out)

    def test_explain_line_range(self):
        calls = []
        self.run_cli("explain", "src/auth.py:2-3", chat=fake_chat("ok", calls))
        prompt = calls[0]["messages"][1]["content"]
        self.assertIn("lines 2-3", prompt)
        self.assertNotIn("def login", prompt)

    def test_review_and_commit_message(self):
        (self.root / "src/util.py").write_text("def add(a, b):\n    return a - b\n")
        calls = []
        self.run_cli("review", chat=fake_chat("bug: subtraction", calls))
        self.assertIn("-    return a + b", calls[0]["messages"][1]["content"])
        code, _ = self.run_cli("commit-msg", chat=fake_chat("fix"))
        self.assertEqual(code, 1)  # nothing staged
        git(self.root, "add", "src/util.py")
        code, out = self.run_cli("commit-msg", chat=fake_chat("fix(util): subtract"))
        self.assertEqual((code, out.strip()), (0, "fix(util): subtract"))


if __name__ == "__main__":
    unittest.main()
