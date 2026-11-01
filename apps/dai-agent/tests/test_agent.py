# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""D.Ai Agents (docs/AGENTS.md): the closed toolbox, approval before every act, --yes never covering a
weakening step, bounded steps, the journal, roles, and the CLI with a scripted Diamond."""
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from dai_agent import agent, cli, roles, tools


def scripted_chat(steps):
    """A fake Diamond: one JSON step per call."""
    queue = list(steps)

    def chat(messages, schema=None, max_tokens=0, task="general"):
        assert [b["properties"]["tool"]["const"] for b in schema["anyOf"]][-1] == "done"
        yield json.dumps(queue.pop(0))
    return chat


class FakeTune:
    """plan_from_text / execute_plan stand-ins with a weakening sentence and a system one."""
    def __init__(self):
        self.executed = []

    def plan(self, sentence, ctx):
        unknown = [] if sentence.startswith(("note: ", "remind me", "lock", "allow usb", "block usb")) else [sentence]
        scope = "system" if "usb" in sentence else "user"
        step = SimpleNamespace(scope=scope, effect="weakens" if sentence.startswith("allow") else "hardens")
        return SimpleNamespace(ok=not unknown, unknown=unknown, errors=[], weakens=step.effect == "weakens",
                               scoped=lambda s: [step] if step.scope == s else [], steps=[step], sentence=sentence)

    def execute(self, plan, ctx, dry_run=False, assume_yes=False, label=""):
        self.executed.append((plan.sentence, dry_run, assume_yes, label))
        return 0


class ToolTests(unittest.TestCase):
    def test_step_schema_has_one_branch_per_tool_with_its_own_args(self):
        schema = agent.step_schema(["remind", "posture"])
        names = [b["properties"]["tool"]["const"] for b in schema["anyOf"]]
        self.assertEqual(names, ["remind", "posture", "done"])
        remind = schema["anyOf"][0]["properties"]["args"]
        self.assertEqual(remind["properties"]["in_minutes"]["type"], "integer")
        self.assertEqual(remind["properties"]["text"]["maxLength"], 500)
        self.assertIn("text", remind["required"])
        self.assertFalse(remind["additionalProperties"])                  # an invented "answer" cannot be generated
        self.assertEqual(schema["anyOf"][1]["properties"]["args"]["properties"], {})
        self.assertEqual(schema["anyOf"][-1]["properties"]["final"]["maxLength"], agent.MAX_ANSWER)
        for branch in schema["anyOf"]:
            self.assertFalse(branch["additionalProperties"])

    def test_args_are_checked_and_unknown_tools_refused(self):
        tool = tools.TOOLS["remind"]
        self.assertEqual(tools.check_args(tool, {"text": " call Dana ", "in_minutes": 20}), {"text": "call Dana", "in_minutes": 20})
        for bad in ({"text": "x", "shell": "rm"}, {"in_minutes": 5}, {"text": "a\nb"}, {"text": "x", "in_minutes": "20"}, {"text": "x" * 501}, "text"):
            with self.subTest(bad=bad), self.assertRaises(tools.ToolError):
                tools.check_args(tool, bad)
        with self.assertRaises(tools.ToolError):
            tools.run_tool("shell", {"cmd": "id"}, tools.Services())

    def test_do_goes_through_tune_and_yes_never_covers_weakening_or_system(self):
        fake = FakeTune()
        services = tools.Services(ctx=object(), lang="en", execute=fake.execute, assume_yes=True)
        import sys
        with mock.patch.dict(sys.modules, {"dai_tune": mock.MagicMock(), "dai_tune.planner": SimpleNamespace(plan_from_text=fake.plan)}):
            if True:
                self.assertEqual(tools.run_tool("do", {"sentence": "lock the screen after 5 minutes"}, services), "Applied: lock the screen after 5 minutes")
                self.assertEqual(fake.executed[-1][2], True)                      # user + hardens: --yes applies
                tools.run_tool("do", {"sentence": "allow usb storage"}, services)
                self.assertEqual(fake.executed[-1][2], False)                     # weakens: still asks
                tools.run_tool("do", {"sentence": "block usb storage"}, services)
                self.assertEqual(fake.executed[-1][2], False)                     # system: still asks
                self.assertIn("remind me in 20 minutes to call Dana", tools.run_tool("remind", {"text": "call Dana", "in_minutes": 20}, services))
                self.assertIn("remind me at 18:30 to rest", tools.run_tool("remind", {"text": "rest", "at": "18:30"}, services))
                self.assertIn("note: buy milk", tools.run_tool("note", {"text": "buy milk"}, services))
                with self.assertRaises(tools.ToolError):
                    tools.run_tool("do", {"sentence": "dance wildly"}, services)
                services.dry_run = True
                self.assertTrue(tools.run_tool("do", {"sentence": "lock the screen"}, services).startswith("Dry run"))
                self.assertEqual(fake.executed[-1][1], True)

    def test_light_tools(self):
        spoken = []
        services = tools.Services(lang="he", speak=lambda text, lang: spoken.append((text, lang)) or True,
                                  run=lambda argv, **k: spoken.append(argv) or subprocess.CompletedProcess(argv, 0, "", ""))
        self.assertEqual(tools.run_tool("say", {"text": "שלום"}, services), "נאמר בקול.")
        self.assertEqual(spoken[0], ("שלום", "he"))
        self.assertEqual(tools.run_tool("notify", {"text": "hi"}, services), "הוצג.")
        self.assertEqual(spoken[-1][-1], "hi")


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.fake = FakeTune()
        self.services = tools.Services(ctx=object(), lang="en", home=self.home, execute=self.fake.execute)
        self.said = []
        import sys
        self.patch = mock.patch.dict(sys.modules, {"dai_tune": mock.MagicMock(), "dai_tune.planner": SimpleNamespace(plan_from_text=self.fake.plan)})
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_a_run_asks_before_acting_and_journals(self):
        chat = scripted_chat([
            {"thought": "note it", "tool": "note", "args": {"text": "buy milk"}, "final": ""},
            {"thought": "and remind", "tool": "remind", "args": {"text": "call Dana", "in_minutes": 20}, "final": ""},
            {"thought": "finish", "tool": "done", "args": {}, "final": "Noted and reminded."},
        ])
        approvals = []

        def approve(step):
            approvals.append(step.tool)
            return step.tool == "note"
        run = agent.run_agent("note buy milk and remind me", self.services, chat=chat, approve=approve, say=self.said.append, home=self.home)
        self.assertEqual(run.status, "done")
        self.assertEqual(run.final, "Noted and reminded.")
        self.assertEqual(approvals, ["note", "remind"])
        self.assertEqual([(s.tool, s.approved, bool(s.error)) for s in run.steps], [("note", True, False), ("remind", False, True)])
        self.assertEqual([e[0] for e in self.fake.executed], ["note: buy milk"])
        saved = json.loads(agent.journal_path(self.home, run.id).read_text())
        self.assertEqual((saved["goal"], saved["status"], saved["steps"][1]["error"]), ("note buy milk and remind me", "done", "not approved"))
        self.assertEqual(oct(agent.journal_path(self.home, run.id).stat().st_mode & 0o777), "0o600")
        self.assertEqual(agent.history(self.home)[0]["id"], run.id)

    def test_unknown_tools_repeats_and_limits(self):
        chat = scripted_chat([{"thought": "", "tool": "shell", "args": {"cmd": "id"}, "final": ""},
                              {"thought": "", "tool": "reminders", "args": {}, "final": ""},
                              {"thought": "", "tool": "reminders", "args": {}, "final": ""}])
        with mock.patch.object(tools, "reminders", lambda services: "No reminders."):
            tools.TOOLS["reminders"].__dict__  # frozen dataclass: patch the registry entry's run through run_tool
            with mock.patch.object(tools, "run_tool", lambda name, args, services: "No reminders." if name == "reminders" else tools.run_tool(name, args, services)), \
                    mock.patch.object(agent, "run_tool", lambda name, args, services: "No reminders."):
                run = agent.run_agent("list", self.services, chat=chat, say=self.said.append, home=self.home)
        self.assertEqual(run.status, "stopped")
        self.assertIn("repeated", run.final)
        self.assertIn("not a tool", run.steps[0].error)
        # A role without the tool refuses it even though the toolbox has it.
        chat = scripted_chat([{"thought": "", "tool": "do", "args": {"sentence": "lock the screen"}, "final": ""},
                              {"thought": "", "tool": "done", "args": {}, "final": "ok"}])
        run = agent.run_agent("lock", self.services, chat=chat, role=roles.ROLES["tutor"], approve=lambda s: True, say=self.said.append, home=self.home)
        self.assertIn("not a tool of this role", run.steps[0].error)
        self.assertEqual(self.fake.executed, [])
        # Eight steps and no "done": stopped.
        chat = scripted_chat([{"thought": "", "tool": "facts", "args": {"question": f"q{i}"}, "final": ""} for i in range(9)])
        with mock.patch.object(agent, "run_tool", lambda name, args, services: "fact"):
            run = agent.run_agent("ask a lot", self.services, chat=chat, say=self.said.append, home=self.home)
        self.assertEqual((run.status, len(run.steps)), ("stopped", agent.MAX_STEPS))

    def test_no_plan_and_a_script(self):
        def broken(messages, schema=None, max_tokens=0, task="general"):
            raise RuntimeError("D.Ai AI service is not running")
            yield  # noqa
        run = agent.run_agent("anything", self.services, chat=broken, say=self.said.append, home=self.home)
        self.assertEqual(run.status, "no-plan")
        self.assertIn("not running", run.final)
        script = [{"tool": "note", "args": {"text": "from a script"}}, {"tool": "done", "args": {}, "final": "scripted"}]
        run = agent.run_agent("script", self.services, script=script, approve=lambda s: True, say=self.said.append, home=self.home)
        self.assertEqual((run.status, run.final), ("done", "scripted"))
        self.assertEqual(self.fake.executed[-1][0], "note: from a script")
        prompt = agent.system_prompt(roles.ROLES["guard"], "he")
        self.assertIn("posture", prompt)
        self.assertNotIn("- remind", prompt)
        self.assertIn("Hebrew", prompt)


class CliTests(unittest.TestCase):
    def test_tools_roles_history_run_and_flags(self):
        fake = FakeTune()
        import sys
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(sys.modules, {"dai_tune": mock.MagicMock(), "dai_tune.planner": SimpleNamespace(plan_from_text=fake.plan), "dai_ai.client": SimpleNamespace(where=lambda task: "local")}):
            home = Path(tmp)
            services = tools.Services(ctx=object(), lang="en", home=home, execute=fake.execute)
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(cli.main(["dai-agent", "tools"]), 0)
                self.assertIn("do         act", out.getvalue())
                self.assertEqual(cli.main(["dai-agent", "roles"]), 0)
                self.assertIn("secretary", out.getvalue())
                self.assertEqual(cli.main(["dai-agent", "history"], home=home), 0)
                self.assertIn("No runs yet", out.getvalue())
                chat = scripted_chat([{"thought": "", "tool": "note", "args": {"text": "milk"}, "final": ""},
                                      {"thought": "", "tool": "done", "args": {}, "final": "Noted."}])
                self.assertEqual(cli.main(["dai-agent", "run", "note milk", "--yes"], chat=chat, services=services, home=home), 0)
                self.assertEqual(fake.executed[-1][0], "note: milk")
                self.assertIn("Noted.", out.getvalue())
                answers = iter(["n"])
                chat = scripted_chat([{"thought": "", "tool": "note", "args": {"text": "eggs"}, "final": ""},
                                      {"thought": "", "tool": "done", "args": {}, "final": "ok"}])
                self.assertEqual(cli.main(["dai-agent", "note eggs"], chat=chat, services=services, home=home, ask_input=lambda q: next(answers)), 0)
                self.assertNotIn("note: eggs", [e[0] for e in fake.executed])
                script = home / "s.json"
                script.write_text(json.dumps([{"tool": "note", "args": {"text": "scripted"}}, {"tool": "done", "args": {}, "final": "fin"}]))
                self.assertEqual(cli.main(["dai-agent", "run", "x", "--script", str(script), "--yes", "--role", "secretary"], services=services, home=home), 0)
                self.assertEqual(fake.executed[-1][0], "note: scripted")
                self.assertEqual(cli.main(["dai-agent", "history"], home=home), 0)
                self.assertIn("[secretary]", out.getvalue())
                self.assertEqual(cli.main(["dai-agent", "run", "x", "--role", "wizard"], services=services, home=home), 2)
                self.assertEqual(cli.main(["dai-agent", "run", "x", "--script", "/no/such.json"], services=services, home=home), 2)
                self.assertEqual(cli.main(["dai-agent", "--version"]), 0)
                self.assertEqual(cli.main(["dai-agent", "run", "--bogus"]), 2)
            self.assertIn("unknown role", err.getvalue())


if __name__ == "__main__":
    unittest.main()
