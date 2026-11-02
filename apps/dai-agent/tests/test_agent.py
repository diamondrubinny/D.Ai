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

    def test_yes_approves_only_a_quiet_do_and_notify_tells_the_answer(self):
        """docs/AGENTS.md §6ב: a timer runs with --yes --notify and nobody present."""
        fake = FakeTune()
        import sys
        notified = []
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(sys.modules, {
                "dai_tune": mock.MagicMock(), "dai_tune.planner": SimpleNamespace(plan_from_text=fake.plan),
                "dai_tune.cli": SimpleNamespace(describe=lambda plan, lang: [{"summary": plan.sentence}]),
                "dai_ai.client": SimpleNamespace(where=lambda task: "local")}):
            home = Path(tmp)
            services = tools.Services(ctx=object(), lang="en", home=home, execute=fake.execute,
                                      run=lambda argv, **k: notified.append(argv) or subprocess.CompletedProcess(argv, 0, "", ""))
            out = io.StringIO()
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                chat = scripted_chat([{"thought": "", "tool": "do", "args": {"sentence": "lock the screen after 5 minutes"}, "final": ""},
                                      {"thought": "", "tool": "do", "args": {"sentence": "allow usb storage"}, "final": ""},
                                      {"thought": "", "tool": "done", "args": {}, "final": "Locked; USB left as it was."}])
                code = cli.main(["dai-agent", "run", "harden", "--yes", "--notify", "--lang", "he"], chat=chat, services=services, home=home,
                                ask_input=lambda q: (_ for _ in ()).throw(EOFError()))        # no terminal: a question is a no
                self.assertEqual(code, 0)
            self.assertEqual([e[0] for e in fake.executed], ["lock the screen after 5 minutes"])  # the weakening step never ran
            self.assertEqual(notified[-1][:2], ["notify-send", "-a"])
            self.assertIn("Locked; USB left as it was.", notified[-1][-1])
            self.assertIn("סוכן D.Ai: harden", notified[-1][-2])                          # --lang he, whatever LANG says

    def test_memory_subcommand(self):
        from dai_agent import memory
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(cli.main(["dai-agent", "memory"], home=home), 0)
                self.assertIn("remembers nothing", out.getvalue())
                memory.add(home, "likes tea")
                memory.add(home, "lives in Haifa")
                self.assertEqual(cli.main(["dai-agent", "memory"], home=home), 0)
                self.assertIn("  2. lives in Haifa", out.getvalue())
                self.assertEqual(cli.main(["dai-agent", "memory", "forget", "1"], home=home), 0)
                self.assertEqual([r["text"] for r in memory.load(home)], ["lives in Haifa"])
                self.assertEqual(cli.main(["dai-agent", "memory", "forget", "9"], home=home), 2)
                self.assertEqual(cli.main(["dai-agent", "memory", "bogus"], home=home), 2)
                self.assertEqual(cli.main(["dai-agent", "memory", "clear"], home=home), 0)
                self.assertEqual(memory.load(home), [])
            self.assertIn("no line 9", err.getvalue())


class NewToolTests(unittest.TestCase):
    """docs/AGENTS.md §6ב: mail from J's own store, a summary through J's prompt, explain, record, remember."""

    def j_store(self, home):
        from dai_j import accounts
        from dai_j.discover import Server
        from dai_j.mail import Header
        from dai_j.store import Store
        folder = home / ".local/share/dai-j"
        folder.mkdir(parents=True)
        server = Server("mail.example.org", 993, "ssl", "dana")
        accounts.save([accounts.Account("dana@example.org", "Dana", server, server)], folder)
        store = Store(folder / "mail.sqlite")
        store.set_folders("dana@example.org", [("INBOX", "inbox"), ("Sent", "sent")])
        store.add("dana@example.org", "INBOX", [
            Header(1, "Old Sender", "old@example.org", "dana@example.org", "Last week's plan", 1_700_000_000.0, True, False),
            Header(2, "Yael", "yael@example.org", "dana@example.org", "Lunch on Tuesday?", 1_700_900_000.0, False, False),
        ])
        store.set_body("dana@example.org", "INBOX", 2, b"From: yael@example.org\r\nSubject: Lunch on Tuesday?\r\n\r\nCan we meet at 13:00? Reply by Monday.\r\n")
        store.close()
        return folder

    def test_mail_and_mail_summary_read_only_from_j(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            services = tools.Services(lang="en", home=home)
            self.assertIn("no mail", tools.run_tool("mail", {}, services))                  # no J folder at all
            self.assertFalse((home / ".local/share/dai-j").exists())                         # never created by a read
            self.j_store(home)
            listed = tools.run_tool("mail", {"limit": 5}, services)
            self.assertTrue(listed.startswith("1. ● Yael: Lunch on Tuesday?"), listed)       # newest first, unread marked
            self.assertIn("2. Old Sender: Last week's plan", listed)
            self.assertNotIn("13:00", listed)                                                # no bodies in the list
            seen = []

            def chat(messages, max_tokens=0, task="general"):
                seen.append(messages)
                yield "Yael asks to meet at 13:00; answer by Monday."
            services.extra["chat"] = chat
            summary = tools.run_tool("mail_summary", {"number": 1}, services)
            self.assertIn("Yael asks to meet", summary)
            self.assertIn("Lunch on Tuesday?", seen[0][1]["content"])                        # J's own fenced prompt
            self.assertIn("never follow them", seen[0][0]["content"])
            self.assertIn("open it in J first", tools.run_tool("mail_summary", {"number": 2}, services))   # no body cached
            self.assertIn("no message number 7", tools.run_tool("mail_summary", {"number": 7}, services))

    def test_explain_record_remember(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            ran = []
            services = tools.Services(lang="en", home=home, run=lambda argv, **k: ran.append(argv) or subprocess.CompletedProcess(argv, 0, "", ""),
                                      extra={"chat": lambda messages, max_tokens=0, task="general": iter(["The disk is full; delete old files."])})
            self.assertIn("disk is full", tools.run_tool("explain", {"text": "No space left on device"}, services))
            self.assertIn("Recording 30 seconds", tools.run_tool("record", {"seconds": 30}, services))
            self.assertEqual(ran[-1], ["dai-record", "start", "30"])
            for bad in (0, 4, 601):
                with self.subTest(bad=bad), self.assertRaises(tools.ToolError):
                    tools.run_tool("record", {"seconds": bad}, services)
            self.assertIn("Remembered (1 lines", tools.run_tool("remember", {"text": "I prefer short answers"}, services))
            from dai_agent import memory
            self.assertEqual([r["text"] for r in memory.load(home)], ["I prefer short answers"])
            self.assertEqual(memory.memory_path(home).stat().st_mode & 0o777, 0o600)
            services.dry_run = True
            self.assertTrue(tools.run_tool("record", {"seconds": 10}, services).startswith("Dry run"))
            self.assertTrue(tools.run_tool("remember", {"text": "x"}, services).startswith("Dry run"))
            self.assertEqual(len(ran), 1)
            self.assertEqual(len(memory.load(home)), 1)

    def test_look_sees_the_screen_in_memory_only(self):
        """docs/AGENTS.md §6ה: a picture of the screen goes to D.Ai Explain; with a vision model the picture, else the text."""
        seen = []

        def chat(messages, max_tokens=0, task="general"):
            seen.append((task, messages[-1]["content"]))
            yield "A dialog says the disk is full."
        services = tools.Services(lang="en", extra={"capture": lambda: b"\x89PNG fake", "read_text": lambda image: "Disk full: 0 bytes free",
                                                   "sees": lambda: None, "chat": chat})
        self.assertIn("disk is full", tools.run_tool("look", {"question": "what does the dialog say?"}, services))
        self.assertEqual(seen[-1][0], "general")                                      # no vision model: the text only
        self.assertIn("Disk full: 0 bytes free", str(seen[-1][1]))
        self.assertIn("what does the dialog say?", str(seen[-1][1]))
        services.extra["sees"] = lambda: "smolvlm-256m"
        services.extra["read_text"] = lambda image: (_ for _ in ()).throw(AssertionError("OCR must not run when Diamond sees"))
        with mock.patch("dai_explain.engine.shrink", lambda image, width=0: image):
            tools.run_tool("look", {}, services)
        self.assertEqual(seen[-1][0], "vision")                                       # the picture, on this computer
        services.extra["capture"] = lambda: (_ for _ in ()).throw(OSError("no grim"))
        with self.assertRaises(tools.ToolError) as caught:
            tools.run_tool("look", {}, services)
        self.assertIn("no grim", str(caught.exception))

    def test_open_uses_commands_app_index_and_focus_goes_through_dai_focus(self):
        """docs/AGENTS.md §6ז: open = Command's best match, never a free command; focus = dai-focus start N."""
        from dai_command.core import AppEntry
        apps = [AppEntry("dai-command.desktop", "D.Ai Command", ("dai-command",), search_terms=("d.ai command", "calculator", "launcher", "command")),
                AppEntry("galculator.desktop", "Galculator", ("galculator",), search_terms=("galculator",)),   # Debian's entry: no keywords
                AppEntry("htop.desktop", "htop", ("htop",), search_terms=("htop", "processes"), terminal=True)]
        spawned, ran = [], []
        services = tools.Services(lang="he", extra={"apps": apps, "spawn": spawned.append},
                                  run=lambda argv, **k: ran.append(argv) or subprocess.CompletedProcess(argv, 0, "Pop-ups are hidden for 5 minutes.", ""))
        self.assertEqual(tools.run_tool("open", {"app": "calculator"}, services), "נפתח: Galculator.")   # run 41368294749: not Command
        self.assertEqual(spawned[-1], ["galculator"])
        self.assertEqual(tools.run_tool("open", {"app": "command"}, services), "נפתח: D.Ai Command.")
        tools.run_tool("open", {"app": "processes"}, services)
        self.assertEqual(spawned[-1], ["x-terminal-emulator", "-e", "htop"])
        self.assertIn("אין כאן אפליקציה בשם rm -rf", tools.run_tool("open", {"app": "rm -rf"}, services))
        self.assertEqual(len(spawned), 3)
        self.assertEqual(tools.run_tool("focus", {"minutes": 5}, services), "Pop-ups are hidden for 5 minutes.")
        self.assertEqual(ran[-1], ["dai-focus", "start", "5"])
        for bad in (4, 181):
            with self.subTest(bad=bad), self.assertRaises(tools.ToolError):
                tools.run_tool("focus", {"minutes": bad}, services)
        services.dry_run = True
        self.assertTrue(tools.run_tool("focus", {}, services).startswith("הרצת ניסיון"))
        self.assertEqual(len(ran), 1)
        from dai_agent import plans
        card = plans.describe_act(agent.StepRecord("focus", {"minutes": 25}), services)
        self.assertEqual(card["rows"], ["פוקוס ל־25 דקות: בלי הודעות קופצות, אור חם יותר; הטיימר מסיים."])
        self.assertTrue(plans.quiet_ok(agent.StepRecord("focus", {"minutes": 25}), services))

    def test_roles_know_the_new_tools(self):
        self.assertTrue({"mail", "mail_summary", "remember"} <= set(roles.ROLES["secretary"].tools))
        self.assertIn("explain", roles.ROLES["tutor"].tools)
        self.assertIn("look", roles.ROLES["tutor"].tools)
        self.assertIn("open", roles.ROLES["tutor"].tools)
        self.assertNotIn("focus", roles.ROLES["tutor"].tools)
        self.assertNotIn("record", roles.ROLES["secretary"].tools)
        self.assertEqual(set(tools.TOOLS), set(roles.ROLES["all"].tools))


class MemoryTests(unittest.TestCase):
    def test_memory_is_bounded_listed_in_the_prompt_and_forgettable(self):
        from dai_agent import memory
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.assertEqual(memory.load(home), [])
            memory.add(home, "  likes   tea ")
            memory.add(home, "works at night")
            memory.add(home, "likes tea")                                     # a repeat moves, it does not double
            self.assertEqual([r["text"] for r in memory.load(home)], ["works at night", "likes tea"])
            for n in range(memory.MAX_LINES + 5):
                memory.add(home, f"line {n}")
            self.assertEqual(len(memory.load(home)), memory.MAX_LINES)
            self.assertNotIn("works at night", [r["text"] for r in memory.load(home)])
            self.assertTrue(memory.forget(home, 1))
            self.assertFalse(memory.forget(home, 999))
            self.assertEqual(len(memory.load(home)), memory.MAX_LINES - 1)
            with self.assertRaises(ValueError):
                memory.add(home, "   ")
            prompt = agent.system_prompt(roles.ROLES["secretary"], "en", memory.load(home))
            self.assertIn("asked you to remember", prompt)
            self.assertIn("- line 6", prompt)
            self.assertNotIn("remember", agent.system_prompt(roles.ROLES["tutor"], "en", []).split("Rules")[1].split("\n")[0])
            memory.memory_path(home).write_text("not json")
            self.assertEqual(memory.load(home), [])
            memory.clear(home)
            memory.clear(home)
            self.assertFalse(memory.memory_path(home).exists())

    def test_run_agent_puts_the_memory_in_the_system_prompt(self):
        from dai_agent import memory
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            memory.add(home, "Dana is my sister")
            prompts = []

            def chat(messages, schema=None, max_tokens=0, task="general"):
                prompts.append(messages[0]["content"])
                yield json.dumps({"thought": "", "tool": "done", "args": {}, "final": "ok"})
            run = agent.run_agent("hello", tools.Services(lang="en", home=home), chat=chat, say=lambda line: None, home=home)
            self.assertEqual(run.status, "done")
            self.assertIn("- Dana is my sister", prompts[0])


class PlanTests(unittest.TestCase):
    """plans.py: what the card shows and what --yes may approve alone."""
    def test_describe_and_quiet_ok(self):
        import sys
        from dai_agent import plans
        fake = FakeTune()
        services = tools.Services(ctx=object(), lang="he", execute=fake.execute)
        with mock.patch.dict(sys.modules, {"dai_tune": mock.MagicMock(), "dai_tune.planner": SimpleNamespace(plan_from_text=fake.plan),
                                           "dai_tune.cli": SimpleNamespace(describe=lambda plan, lang: [{"summary": f"Step: {plan.sentence}"}])}):
            record = plans.describe_act(agent.StepRecord("record", {"seconds": 20}), services)
            self.assertEqual(record["rows"], ["הקלטת המסך למשך 20 שניות (בלי קול), אל ~/Videos/Recordings."])
            remember = plans.describe_act(agent.StepRecord("remember", {"text": "tea"}), services)
            self.assertEqual(remember["rows"], ["לזכור לריצות הבאות: tea"])
            lock = plans.describe_act(agent.StepRecord("do", {"sentence": "lock the screen after 5 minutes"}), services)
            self.assertEqual((lock["rows"], lock["weakens"], lock["system"]), (["Step: lock the screen after 5 minutes"], False, False))
            self.assertTrue(plans.quiet_ok(agent.StepRecord("do", {"sentence": "lock the screen after 5 minutes"}), services))
            self.assertFalse(plans.quiet_ok(agent.StepRecord("do", {"sentence": "allow usb storage"}), services))     # weakens
            self.assertFalse(plans.quiet_ok(agent.StepRecord("do", {"sentence": "block usb storage"}), services))     # system
            self.assertFalse(plans.quiet_ok(agent.StepRecord("do", {"sentence": "dance"}), services))                 # not understood
            self.assertTrue(plans.quiet_ok(agent.StepRecord("remember", {"text": "x"}), services))
            self.assertTrue(plans.quiet_ok(agent.StepRecord("record", {"seconds": 9}), services))
            self.assertFalse(plans.quiet_ok(agent.StepRecord("say", {"text": "x"}), services))


class PolicyTests(unittest.TestCase):
    """docs/AGENTS.md §6ג: /etc/dai/policy-agent.env decides which roles a person may use here."""
    def test_roles_from_the_policy_file(self):
        from dai_agent import policy
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(policy.allowed_roles(root), tuple(roles.ROLES))             # no file: everything
            env = root / "etc/dai/policy-agent.env"
            env.parent.mkdir(parents=True)
            env.write_text("DAI_AGENT_ROLES=none\n")
            self.assertEqual(policy.allowed_roles(root), ())
            self.assertIn("turned off", policy.refusal("tutor", "en", root))
            env.write_text("# school\nDAI_AGENT_ROLES=\"secretary, tutor\"\n")
            self.assertEqual(policy.allowed_roles(root), ("secretary", "tutor"))
            self.assertEqual(policy.refusal("tutor", "he", root), "")
            self.assertIn("secretary, tutor", policy.refusal("guard", "he", root))
            env.write_text("DAI_AGENT_ROLES=all\n")
            self.assertEqual(policy.allowed_roles(root), tuple(roles.ROLES))
            env.write_text("DAI_AGENT_ROLES=secretary\n")
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(cli.main(["dai-agent", "run", "x", "--role", "guard"], home=root, root=root), 2)
                self.assertEqual(cli.main(["dai-agent", "roles"], root=root), 0)
            self.assertIn("only these roles here: secretary", err.getvalue())
            self.assertIn("guard", out.getvalue())
            self.assertEqual(out.getvalue().count("not allowed here"), len(roles.ROLES) - 1)


class DirectWayTests(unittest.TestCase):
    """docs/AGENTS.md §6ט: a goal that is a D.Ai Tune sentence runs as one do step without the model."""
    def setUp(self):
        import sys
        self.fake = FakeTune()
        patch = mock.patch.dict(sys.modules, {"dai_tune": mock.MagicMock(), "dai_tune.planner": SimpleNamespace(plan_from_text=self.fake.plan),
                                              "dai_tune.cli": SimpleNamespace(describe=lambda plan, lang: [{"summary": plan.sentence}])})
        patch.start()
        self.addCleanup(patch.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.services = tools.Services(ctx=object(), lang="en", home=self.home, execute=self.fake.execute)

    def test_an_understood_sentence_needs_no_model(self):
        def no_chat(messages, schema=None, max_tokens=0, task="general"):
            raise AssertionError("the model must not be asked")
        run = agent.run_agent("lock the screen after 5 minutes", self.services, chat=no_chat, approve=lambda step: True, say=lambda line: None, home=self.home)
        self.assertEqual((run.planner, run.status, run.final), ("tune", "done", "Done: lock the screen after 5 minutes"))
        self.assertEqual([(s.tool, s.args) for s in run.steps], [("do", {"sentence": "lock the screen after 5 minutes"})])
        self.assertEqual(self.fake.executed[-1][0], "lock the screen after 5 minutes")
        self.assertEqual(json.loads(agent.journal_path(self.home, run.id).read_text())["planner"], "tune")
        self.services.dry_run = True
        run = agent.run_agent("note: buy milk", self.services, chat=no_chat, approve=lambda step: True, say=lambda line: None, home=self.home)
        self.assertEqual(run.final, "Dry run: note: buy milk")

    def test_a_refused_direct_step_changes_nothing_and_an_unknown_goal_goes_to_the_model(self):
        run = agent.run_agent("allow usb storage", self.services, chat=None, approve=lambda step: False, say=lambda line: None, home=self.home)
        self.assertEqual((run.planner, run.status, run.final), ("tune", "stopped", "Nothing was changed."))
        self.assertEqual(self.fake.executed, [])
        asked = []

        def chat(messages, schema=None, max_tokens=0, task="general"):
            asked.append(messages[-1]["content"])
            yield json.dumps({"thought": "", "tool": "done", "args": {}, "final": "Diamond answered."})
        run = agent.run_agent("organise my day", self.services, chat=chat, approve=lambda step: True, say=lambda line: None, home=self.home)
        self.assertEqual((run.planner, run.final), ("diamond", "Diamond answered."))
        self.assertEqual(asked, ["organise my day"])
        run = agent.run_agent("lock the screen after 5 minutes", self.services, chat=chat, approve=lambda step: True, say=lambda line: None, home=self.home, direct=False)
        self.assertEqual(run.planner, "diamond")                                      # --model: Diamond anyway
        tutor = agent.run_agent("lock the screen after 5 minutes", self.services, chat=chat, role=roles.ROLES["tutor"], say=lambda line: None, home=self.home)
        self.assertEqual(tutor.planner, "diamond")                                    # a role without do cannot take the direct way

    def test_cli_model_flag_and_history_mark(self):
        import sys
        out = io.StringIO()
        with mock.patch.dict(sys.modules, {"dai_ai.client": SimpleNamespace(where=lambda task: "local")}), redirect_stdout(out), redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["dai-agent", "run", "lock the screen after 5 minutes", "--yes"], services=self.services, home=self.home), 0)
            self.assertIn("Done: lock the screen after 5 minutes", out.getvalue())
            self.assertEqual(cli.main(["dai-agent", "history"], home=self.home), 0)
            self.assertIn("(Tune)", out.getvalue())
            chat = scripted_chat([{"thought": "", "tool": "done", "args": {}, "final": "by Diamond"}])
            self.assertEqual(cli.main(["dai-agent", "run", "lock the screen after 5 minutes", "--yes", "--model"], chat=chat, services=self.services, home=self.home), 0)
            self.assertIn("by Diamond", out.getvalue())


class AskAndUndoTests(unittest.TestCase):
    """docs/AGENTS.md §6ו: the ask tool, the Tune entry a step makes, and undoing a whole run."""
    def test_ask_tool_with_and_without_a_person(self):
        services = tools.Services(lang="en")
        self.assertIn("Nobody can answer", tools.run_tool("ask", {"question": "which folder?"}, services))   # a timer
        services.ask_person = lambda q: "  the  Lease folder "
        self.assertEqual(tools.run_tool("ask", {"question": "which folder?"}, services), "The person answered: the Lease folder")
        services.ask_person = lambda q: None
        self.assertEqual(tools.run_tool("ask", {"question": "which?"}, services), "The person did not answer.")
        self.assertIsNone(cli.ask_person("x", "en", lambda prompt: (_ for _ in ()).throw(EOFError())))
        self.assertEqual(cli.ask_person("x", "he", lambda prompt: "כן" if "Diamond שואל: x" in prompt else "?"), "כן")

    def test_a_do_step_keeps_its_tune_entry_and_a_run_can_be_undone(self):
        fake = FakeTune()
        import sys
        ids = iter(["e1", "e2"])
        journal = SimpleNamespace(find=lambda which="last": {"id": getattr(journal, "last", "")})

        def execute(plan, ctx, dry_run=False, assume_yes=False, label=""):
            journal.last = next(ids)                                                  # Tune journaled one entry
            return fake.execute(plan, ctx, dry_run, assume_yes, label)
        journal.last = ""
        executor = SimpleNamespace(Journal=SimpleNamespace(for_user=lambda ctx: journal))
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(sys.modules, {
                "dai_tune": mock.MagicMock(), "dai_tune.planner": SimpleNamespace(plan_from_text=fake.plan), "dai_tune.executor": executor}):
            home = Path(tmp)
            services = tools.Services(ctx=object(), lang="en", home=home, execute=execute)
            steps = [{"thought": "", "tool": "note", "args": {"text": "milk"}, "final": ""},
                     {"thought": "", "tool": "reminders", "args": {}, "final": ""},
                     {"thought": "", "tool": "remind", "args": {"text": "call Dana", "in_minutes": 5}, "final": ""},
                     {"thought": "", "tool": "done", "args": {}, "final": "ok"}]
            with mock.patch.object(agent, "run_tool", side_effect=lambda name, args, svc: "No reminders." if name == "reminders" else tools.run_tool(name, args, svc)):
                run = agent.run_agent("organise", services, chat=scripted_chat(steps), approve=lambda step: True, say=lambda line: None, home=home)
            self.assertEqual([s.entry for s in run.steps], ["e1", "", "e2"])
            saved = json.loads(agent.journal_path(home, run.id).read_text())
            self.assertEqual([s["entry"] for s in saved["steps"]], ["e1", "", "e2"])
            self.assertFalse(saved["undone"])
            calls = []

            def run_command(argv, **kwargs):
                calls.append(argv)
                return subprocess.CompletedProcess(argv, 0, "✓ Undone: " + argv[-1], "")
            ok, lines = agent.undo_run(home, run.id, run_command, "en")
            self.assertTrue(ok, lines)
            self.assertEqual(calls, [["dai-tune", "undo", "e2"], ["dai-tune", "undo", "e1"]])       # last change first
            self.assertTrue(json.loads(agent.journal_path(home, run.id).read_text())["undone"])
            self.assertEqual(agent.undo_run(home, run.id, run_command, "en")[1], [f"Run {run.id} was already undone."])
            self.assertIn("No run called", agent.undo_run(home, "nope", run_command, "en")[1][0])
            self.assertIn("No run called", agent.undo_run(home, "../x", run_command, "en")[1][0])
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(cli.main(["dai-agent", "history"], home=home), 0)
                self.assertEqual(cli.main(["dai-agent", "undo", run.id], home=home, services=services), 1)   # already undone
                self.assertEqual(cli.main(["dai-agent", "undo"], home=home), 2)
            self.assertIn("done ↶", out.getvalue())
            self.assertIn("already undone", err.getvalue())
            failing = lambda argv, **k: subprocess.CompletedProcess(argv, 1, "", "✗ nothing to undo")  # noqa: E731
            saved["undone"] = False
            agent.journal_path(home, run.id).write_text(json.dumps(saved))
            ok, lines = agent.undo_run(home, run.id, failing, "en")
            self.assertFalse(ok)
            self.assertTrue(lines[0].startswith("✗"))
            self.assertFalse(json.loads(agent.journal_path(home, run.id).read_text())["undone"])


class SuggestTests(unittest.TestCase):
    """docs/AGENTS.md §6ח: ready-made goals per role."""
    def test_suggestions_per_role_and_cli(self):
        from dai_agent.suggest import suggestions
        self.assertIn("Focus for 25 minutes", suggestions("secretary", "en"))
        self.assertIn("פוקוס ל־25 דקות", suggestions("secretary", "he"))
        self.assertEqual(suggestions("wizard", "en"), [])
        for role in roles.ROLES:
            self.assertGreaterEqual(len(suggestions(role, "en")), 2, role)
            self.assertEqual(len(set(suggestions(role, "en"))), len(suggestions(role, "en")))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(cli.main(["dai-agent", "suggest", "guard"]), 0)
            self.assertEqual(cli.main(["dai-agent", "suggest"]), 0)
            self.assertEqual(cli.main(["dai-agent", "suggest", "wizard"]), 2)
        self.assertIn("harden the easy parts", out.getvalue())
        self.assertIn("unknown role", err.getvalue())


class WindowTests(unittest.TestCase):
    """The agent window (docs/AGENTS.md §6): Raz audits it, approval is a button that shows the Tune plan,
    a skip applies nothing, a weakening plan is said in words, closing while a card waits frees the thread."""

    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PyQt6.QtWidgets import QApplication
        except ImportError:
            raise unittest.SkipTest("PyQt6 is missing")
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        import sys
        from dai_agent import gui
        self.gui = gui
        self.fake = FakeTune()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        patch = mock.patch.dict(sys.modules, {"dai_tune": mock.MagicMock(), "dai_tune.planner": SimpleNamespace(plan_from_text=self.fake.plan),
                                              "dai_tune.cli": SimpleNamespace(describe=lambda plan, lang: [{"summary": f"Step: {plan.sentence}"}])})
        patch.start()
        self.addCleanup(patch.stop)

    def window(self, steps, lang="en", goal="organise my day", spawn=None):
        services = tools.Services(ctx=object(), lang=lang, home=self.home, execute=self.fake.execute)
        window = self.gui.AgentWindow(lang, services, goal=goal, chat=scripted_chat(steps), home=self.home,
                                      spawn=spawn or (lambda argv, text=None: None))
        self.addCleanup(window.close)
        self.addCleanup(window.deleteLater)
        return window

    def wait(self, window, until, tries=200):
        from PyQt6.QtTest import QTest
        for _ in range(tries):
            QTest.qWait(20)
            if until():
                return True
        return until()

    def card_buttons(self, window):
        from PyQt6.QtWidgets import QPushButton
        self.assertIsNotNone(window.pending)
        allow, skip = window.pending.findChildren(QPushButton)[:2]
        return allow, skip

    def test_every_control_is_accessible_with_a_card_open_and_an_answer(self):
        from dai_raz.a11y import assert_accessible
        self.qt.setStyleSheet(self.gui.STYLE)
        self.addCleanup(self.qt.setStyleSheet, "")
        for lang in ("he", "en"):
            window = self.window([{"tool": "find", "args": {"query": "lease"}, "thought": "look"},
                                  {"tool": "do", "args": {"sentence": "allow usb storage"}, "thought": "weaken"},
                                  {"tool": "done", "args": {}, "final": "All set."}], lang=lang)
            with mock.patch.dict(sys_modules_find()):
                window.start()
                self.assertTrue(self.wait(window, lambda: window.pending is not None))
                assert_accessible(self, window, touch=True)            # a step card and an approval card are open
                allow, skip = self.card_buttons(window)
                skip.click()
                self.assertTrue(self.wait(window, lambda: window.run is not None))
            assert_accessible(self, window, touch=True)                # the answer is shown
            self.assertIn("All set.", window.texts())

    def test_allow_runs_the_plan_shown_on_the_card_and_skip_does_not(self):
        steps = [{"tool": "note", "args": {"text": "call Dana"}, "thought": ""},
                 {"tool": "remind", "args": {"text": "water", "in_minutes": 5}, "thought": ""},
                 {"tool": "done", "args": {}, "final": "Noted and set."}]
        window = self.window(steps)
        window.start()
        self.assertTrue(self.wait(window, lambda: window.pending is not None))
        self.assertIn("Step: note: call Dana", window.texts())                   # the Tune plan is on the card
        allow, skip = self.card_buttons(window)
        self.assertIs(window.focusWidget(), allow)
        allow.click()
        self.assertTrue(self.wait(window, lambda: window.pending is not None and len(window.findChildren(type(window.pending))) >= 2))
        self.assertIn("Step: remind me in 5 minutes to water", window.texts())
        _, skip = self.card_buttons(window)
        skip.click()
        self.assertTrue(self.wait(window, lambda: window.run is not None))
        self.assertEqual([e[0] for e in self.fake.executed], ["note: call Dana"])   # allowed once, skipped once
        self.assertEqual(self.fake.executed[0][2], False)                           # never assume_yes from the window
        self.assertEqual(window.run.status, "done")
        self.assertEqual([s.approved for s in window.run.steps], [True, False])
        self.assertIn("✓ allowed", window.texts())
        self.assertIn("✗ skipped", window.texts())
        self.assertTrue((self.home / ".local/share/dai/agents" / f"{window.run.id}.json").exists())
        self.assertTrue(window.copy.isEnabled())

    def test_chips_offer_goals_per_role_and_start_a_run(self):
        """docs/AGENTS.md §6ח: an empty window shows ready-made goals; a click fills the goal and starts."""
        from PyQt6.QtWidgets import QPushButton
        from dai_raz.a11y import assert_accessible
        steps = [{"thought": "", "tool": "done", "args": {}, "final": "Focused."}]
        window = self.window(steps, lang="he", goal="")
        self.assertFalse(window.ideas.isHidden())
        chips = [b for b in window.ideas.findChildren(QPushButton)]
        self.assertGreaterEqual(len(chips), 4)                                       # "all": two per role
        assert_accessible(self, window, touch=True)
        window.role.setCurrentIndex(window.role.findData("guard"))
        chips = [b for b in window.ideas.findChildren(QPushButton) if b.isVisible() or not window.isVisible()]
        self.assertTrue(any("חזק" in c.accessibleName() for c in chips))
        chip = next(c for c in chips if "חזק" in c.accessibleName())
        chip.click()
        self.assertEqual(window.goal.text(), chip.accessibleName())
        self.assertTrue(window.ideas.isHidden())                                      # gone while the run is on the screen
        self.assertTrue(self.wait(window, lambda: window.run is not None))
        self.assertIn("Focused.", window.texts())
        self.assertTrue(window.ideas.isHidden())

    def test_enter_presses_the_focused_card_button(self):
        """Run 41336886735: Enter on the Allow button did nothing (a QPushButton outside a dialog answers Space only)."""
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        steps = [{"thought": "", "tool": "note", "args": {"text": "call Dana"}, "final": ""},
                 {"thought": "", "tool": "done", "args": {}, "final": "Noted."}]
        window = self.window(steps)
        window.start()
        self.assertTrue(self.wait(window, lambda: window.pending is not None))
        QTest.qWait(50)
        allow, _skip = self.card_buttons(window)
        self.assertIs(window.focusWidget(), allow)                     # not the microphone, the next tab stop after Start
        QTest.keyClick(allow, Qt.Key.Key_Return)
        self.assertTrue(self.wait(window, lambda: window.run is not None))
        self.assertEqual([e[0] for e in self.fake.executed], ["note: call Dana"])

    def test_a_weakening_plan_is_said_in_words_and_skip_gets_the_focus(self):
        window = self.window([{"tool": "do", "args": {"sentence": "allow usb storage"}, "thought": ""},
                              {"tool": "done", "args": {}, "final": "ok"}], lang="he")
        window.show()
        window.start()
        self.assertTrue(self.wait(window, lambda: window.pending is not None))
        self.assertIn("מחליש אבטחה", window.texts())
        self.assertIn("סיסמת מנהל", window.texts())                                 # a system step says so
        allow, skip = self.card_buttons(window)
        self.assertIs(window.focusWidget(), skip)
        skip.click()
        self.assertTrue(self.wait(window, lambda: window.run is not None))
        self.assertEqual(self.fake.executed, [])

    def test_dry_run_applies_nothing_and_a_misunderstood_step_cannot_be_allowed(self):
        window = self.window([{"tool": "do", "args": {"sentence": "lock the screen after 5 minutes"}, "thought": ""},
                              {"tool": "do", "args": {"sentence": "make coffee"}, "thought": ""},
                              {"tool": "done", "args": {}, "final": "ok"}])
        window.dry_run.setChecked(True)
        window.start()
        self.assertTrue(self.wait(window, lambda: window.pending is not None))
        allow, _ = self.card_buttons(window)
        allow.click()
        self.assertTrue(self.wait(window, lambda: window.pending is not None and "make coffee" in window.texts() and "did not understand" in window.texts()))
        allow, skip = self.card_buttons(window)
        self.assertFalse(allow.isEnabled())
        skip.click()
        self.assertTrue(self.wait(window, lambda: window.run is not None))
        self.assertEqual(self.fake.executed[0][1], True)                            # dry_run reached the executor
        self.assertEqual(window.run.steps[0].result[:8], "Dry run:")

    def test_closing_while_a_card_waits_frees_the_thread_and_applies_nothing(self):
        window = self.window([{"tool": "note", "args": {"text": "x"}, "thought": ""}, {"tool": "done", "args": {}, "final": "ok"}])
        window.start()
        self.assertTrue(self.wait(window, lambda: window.pending is not None))
        window.close()
        self.assertIsNone(window.thread)
        self.assertEqual(self.fake.executed, [])

    def test_read_aloud_goes_through_dai_speak_stdin_and_window_main_parses(self):
        spawned = []
        window = self.window([{"tool": "done", "args": {}, "final": "The answer."}], spawn=lambda argv, text=None: spawned.append((argv, text)))
        window.start()
        self.assertTrue(self.wait(window, lambda: window.run is not None))
        window.read.click()
        self.assertEqual(spawned, [(["dai-speak", "--stdin", "--lang", "en"], "The answer.")])
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(cli.main(["dai-agent", "window", "--version"]), 0)
            self.assertEqual(self.gui.main(["dai-agent", "--role", "nobody"]), 2)
            self.assertEqual(self.gui.main(["dai-agent", "--dance"]), 2)
        self.assertIn("dai-agent 0.", out.getvalue())
        self.assertIn("unknown role", err.getvalue())

    def test_microphone_fills_the_goal_and_the_answer_is_read_aloud(self):
        """docs/AGENTS.md §6ג: a goal from the microphone is answered aloud; --speak does it every time."""
        from PyQt6.QtCore import pyqtSignal
        from PyQt6.QtWidgets import QToolButton
        from dai_raz.a11y import assert_accessible

        class MicButton(QToolButton):
            transcribed = pyqtSignal(str)

            def __init__(self):
                super().__init__()
                self.setObjectName("Mic")
                self.setAccessibleName("Microphone")
                self.setText("🎙")
        spoken = []
        steps = [{"thought": "", "tool": "done", "args": {}, "final": "Two reminders today."}]
        services = tools.Services(ctx=object(), lang="en", home=self.home, execute=self.fake.execute)
        window = self.gui.AgentWindow("en", services, chat=scripted_chat(steps), home=self.home, mic=MicButton,
                                      spawn=lambda argv, text=None: spoken.append((argv, text)))
        self.addCleanup(window.close)
        self.addCleanup(window.deleteLater)
        assert_accessible(self, window, touch=True)                              # with the microphone button
        window.mic.transcribed.emit("  what is   on today ")
        self.assertEqual(window.goal.text(), "what is on today")
        self.assertTrue(self.wait(window, lambda: window.run is not None))
        self.assertEqual(spoken[-1][0], ["dai-speak", "--stdin", "--lang", "en"])
        self.assertEqual(spoken[-1][1], "Two reminders today.")
        self.assertFalse(window.spoken_goal)
        typed = self.gui.AgentWindow("en", services, goal="again", chat=scripted_chat(list(steps)), home=self.home, mic=MicButton,
                                     spawn=lambda argv, text=None: spoken.append((argv, text)))
        self.addCleanup(typed.close)
        typed.start()
        self.assertTrue(self.wait(typed, lambda: typed.run is not None))
        self.assertEqual(len(spoken), 1)                                          # typed: not aloud unless asked
        loud = self.gui.AgentWindow("en", services, goal="again", chat=scripted_chat(list(steps)), home=self.home, mic=MicButton,
                                    speak=True, spawn=lambda argv, text=None: spoken.append((argv, text)))
        self.addCleanup(loud.close)
        loud.start()
        self.assertTrue(self.wait(loud, lambda: loud.run is not None))
        self.assertEqual(len(spoken), 2)

    def test_policy_limits_the_roles_in_the_window(self):
        from dai_raz.a11y import assert_accessible
        env = self.home / "etc/dai/policy-agent.env"
        env.parent.mkdir(parents=True)
        env.write_text("DAI_AGENT_ROLES=secretary,tutor\n")
        services = tools.Services(ctx=object(), lang="he", home=self.home, execute=self.fake.execute)
        window = self.gui.AgentWindow("he", services, role="guard", home=self.home, root=self.home, mic=None)
        self.addCleanup(window.close)
        self.assertEqual([window.role.itemData(i) for i in range(window.role.count())], ["secretary", "tutor"])
        self.assertEqual(window.role.currentData(), "secretary")                   # guard is not allowed: the first allowed one
        assert_accessible(self, window, touch=True)
        env.write_text("DAI_AGENT_ROLES=none\n")
        off = self.gui.AgentWindow("he", services, goal="x", home=self.home, root=self.home, mic=None)
        self.addCleanup(off.close)
        off.start()
        self.assertIsNone(off.thread)
        self.assertIn("מדיניות הארגון", off.status.text())
        with mock.patch.object(self.gui, "refusal", lambda role, lang, root=None: "Agents are turned off on this computer by the organization's policy."):
            err = io.StringIO()
            with redirect_stderr(err):
                self.assertEqual(self.gui.main(["dai-agent", "x"]), 2)
            self.assertIn("turned off", err.getvalue())

    def test_window_main_takes_a_script(self):
        script = self.home / "steps.json"
        script.write_text(json.dumps([{"tool": "done", "args": {}, "final": "scripted"}]))
        import sys
        err = io.StringIO()
        started = []
        with mock.patch.object(self.gui.AgentWindow, "show", lambda self: None), \
                mock.patch.object(self.gui.AgentWindow, "start", lambda self: started.append(self.script)), \
                mock.patch.object(self.gui.QApplication, "exec", lambda self: 0), \
                mock.patch.dict(sys.modules, {"dai_tune.context": SimpleNamespace(Context=lambda lang: object()),
                                              "dai_ai.client": SimpleNamespace(where=lambda task: "local")}), \
                redirect_stderr(err):
            self.assertEqual(self.gui.main(["dai-agent", "scripted", "--script", str(script)]), 0)
            self.assertEqual(started, [[{"tool": "done", "args": {}, "final": "scripted"}]])          # the steps reach the window
            self.assertEqual(self.gui.main(["dai-agent", "x", "--script", "/no/such.json"]), 2)
            script.write_text('{"not": "a list"}')
            self.assertEqual(self.gui.main(["dai-agent", "x", "--script", str(script)]), 2)
        self.assertIn("--script", err.getvalue())

    def test_a_question_card_takes_the_answer_and_undo_takes_the_changes_back(self):
        """docs/AGENTS.md §6ו: the ask tool in the window, and the Undo button after a run that changed things."""
        from PyQt6.QtWidgets import QLineEdit, QPushButton
        from dai_raz.a11y import assert_accessible
        steps = [{"thought": "", "tool": "ask", "args": {"question": "Which folder?"}, "final": ""},
                 {"thought": "", "tool": "note", "args": {"text": "call Dana"}, "final": ""},
                 {"thought": "", "tool": "done", "args": {}, "final": "All set."}]
        undone = []
        services = tools.Services(ctx=object(), lang="he", home=self.home, execute=self.fake.execute,
                                  run=lambda argv, **k: undone.append(argv) or subprocess.CompletedProcess(argv, 0, "✓ בוטל", ""))
        window = self.gui.AgentWindow("he", services, goal="organise", chat=scripted_chat(steps), home=self.home, mic=None)
        self.addCleanup(window.close)
        self.addCleanup(window.deleteLater)
        window.start()
        self.assertTrue(self.wait(window, lambda: window.pending is not None))
        self.assertIn("Diamond שואל: Which folder?", window.texts())
        assert_accessible(self, window, touch=True)                                   # the question card is open
        field = window.pending.findChildren(QLineEdit)[0]
        self.assertIs(window.focusWidget(), field)
        field.setText("Lease")
        window.pending.findChildren(QPushButton)[0].click()
        self.assertTrue(self.wait(window, lambda: window.pending is not None and "Diamond רוצה" in window.texts()))
        allow, _skip = self.card_buttons(window)
        allow.click()
        self.assertTrue(self.wait(window, lambda: window.run is not None))
        self.assertIn("האדם ענה: Lease", window.texts())
        self.assertEqual(window.run.steps[0].result, "האדם ענה: Lease")
        self.assertFalse(window.undo.isEnabled())                                     # FakeTune journals nothing
        window.run.steps[1].entry = "e9"
        window.undo.setEnabled(True)
        from dai_agent import agent as agent_module
        saved = agent_module.load_run(self.home, window.run.id)
        saved["steps"][1]["entry"] = "e9"
        agent_module.journal_path(self.home, window.run.id).write_text(json.dumps(saved))
        window.undo.click()
        self.assertEqual(undone, [["dai-tune", "undo", "e9"]])
        self.assertIn("בוטל", window.status.text())
        self.assertFalse(window.undo.isEnabled())
        assert_accessible(self, window, touch=True)

    def test_closing_while_a_question_waits_frees_the_thread(self):
        steps = [{"thought": "", "tool": "ask", "args": {"question": "Sure?"}, "final": ""},
                 {"thought": "", "tool": "done", "args": {}, "final": "ok"}]
        services = tools.Services(ctx=object(), lang="en", home=self.home, execute=self.fake.execute)
        window = self.gui.AgentWindow("en", services, goal="x", chat=scripted_chat(steps), home=self.home, mic=None)
        self.addCleanup(window.deleteLater)
        window.start()
        self.assertTrue(self.wait(window, lambda: window.pending is not None))
        window.close()
        self.assertIsNone(window.thread)


def sys_modules_find():
    """A find tool that needs no index: dai_find stand-ins."""
    return {"dai_find": mock.MagicMock(), "dai_find.query": SimpleNamespace(parse=lambda q, lang="en": q),
            "dai_find.search": SimpleNamespace(search=lambda q, home=None, limit=10: [SimpleNamespace(path=Path("/home/me/lease.pdf"))])}

if __name__ == "__main__":
    unittest.main()
