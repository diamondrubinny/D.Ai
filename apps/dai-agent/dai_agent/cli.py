# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-agent: Diamond with a closed toolbox (docs/AGENTS.md).

  dai-agent run "goal" [--role ROLE] [--yes] [--dry-run] [--notify] [--script FILE]
  dai-agent "goal"                 the same as run
  dai-agent tools                  the toolbox, with what each tool may do
  dai-agent roles                  secretary, organizer, guard, tutor, all
  dai-agent history                the last runs (~/.local/share/dai/agents)
  dai-agent memory                 what the agent remembers (only lines you approved with the remember tool)
  dai-agent memory forget N        drop line N;  dai-agent memory clear   forgets everything
  dai-agent window ["goal"] [--role ROLE]   the same, in a window: steps as a list, approval by a button
  dai-agent --version

Every tool that changes something asks you first (a D.Ai Tune plan you can undo). --yes approves only user-scope
steps that keep or harden security; the rest still ask. --dry-run shows every change without making it.
--notify shows the answer as a notification too (a timer has no terminal: "every day at 8 agent: …" in
D.Ai Tune makes one through Diamond's Way). --script FILE runs the JSON steps in FILE without the model.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dai_i18n import pick, ui_lang

from . import __author__, __version__
from . import memory
from .agent import AgentError, StepRecord, history, run_agent
from .plans import quiet_ok
from .roles import ROLES
from .tools import TOOLS, Services


def _option(args: list[str], name: str) -> str | None:
    if name in args:
        at = args.index(name)
        return args[at + 1] if at + 1 < len(args) else None
    return None


def ask(step: StepRecord, lang: str, ask_input=input) -> bool:
    question = pick(lang, "  Allow {tool} {args}? [y/N] ", "  לאשר {tool} {args}? [כ/ל] ").format(tool=step.tool, args=json.dumps(step.args, ensure_ascii=False))
    try:
        return ask_input(question).strip().casefold() in ("y", "yes", "כ", "כן")
    except (EOFError, KeyboardInterrupt):
        return False


def notify_final(run, lang: str, run_command=subprocess.run) -> None:
    """The answer on the screen: what a scheduled agent has instead of a terminal."""
    title = pick(lang, "D.Ai Agent: {goal}", "סוכן D.Ai: {goal}").format(goal=run.goal[:60])
    body = (run.final or "").strip()[:400] or pick(lang, "Finished.", "הסתיים.")
    if run.status in ("stopped", "no-plan", "failed"):
        body = pick(lang, "Did not finish ({status}). ", "לא הסתיים ({status}). ").format(status=run.status) + body
    try:
        run_command(["notify-send", "-a", "D.Ai Agent", "-i", "system-run", title, body],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def cmd_memory(rest: list[str], lang: str, home: Path | None) -> int:
    if rest[:1] == ["clear"] and len(rest) == 1:
        memory.clear(home)
        print(pick(lang, "The agent remembers nothing now.", "הסוכן לא זוכר כלום עכשיו."))
        return 0
    if rest[:1] == ["forget"] and len(rest) == 2 and rest[1].isdigit():
        if not memory.forget(home, int(rest[1])):
            print(pick(lang, "✗ no line {n}; see: dai-agent memory", "✗ אין שורה {n}; ראו: dai-agent memory").format(n=rest[1]), file=sys.stderr)
            return 2
        print(pick(lang, "Forgotten.", "נשכח."))
        return 0
    if rest:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    rows = memory.load(home)
    if not rows:
        print(pick(lang, "The agent remembers nothing yet (the remember tool, with your approval, adds a line).",
                   "הסוכן עדיין לא זוכר כלום (הכלי remember, באישורכם, מוסיף שורה)."))
        return 0
    for number, row in enumerate(rows, 1):
        print(f"{number:3}. {row['text']}  ({row['added']})")
    return 0


def main(argv: list[str] | None = None, chat=None, services: Services | None = None, home: Path | None = None,
         ask_input=input) -> int:
    args = list(sys.argv if argv is None else argv)[1:]
    lang = ui_lang()
    if not args or args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if args[0] == "--version":
        print(f"dai-agent {__version__} — {__author__}")
        return 0
    if args[0] == "tools":
        for tool in TOOLS.values():
            print(f"{tool.name:10} {tool.risk:5} {tool.describe}")
        return 0
    if args[0] == "roles":
        for role in ROLES.values():
            print(f"{role.name:10} {pick(lang, *role.title)}  [{', '.join(role.tools)}]")
        return 0
    if args[0] == "window":
        from .gui import main as window_main
        return window_main(["dai-agent", *args[1:]])
    if args[0] == "history":
        rows = history(home)
        if not rows:
            print(pick(lang, "No runs yet.", "אין ריצות עדיין."))
            return 0
        for row in rows:
            print(f"{row['id']}  {row.get('started', '')}  {row.get('status', '')}  [{row.get('role', '')}]  {row['goal'][:60]}")
            if row.get("final"):
                print("    " + str(row["final"])[:200].replace("\n", " "))
        return 0
    if args[0] == "memory":
        return cmd_memory(args[1:], lang, home)
    if args[0] == "run":
        args = args[1:]
    role_name = _option(args, "--role") or "all"
    if role_name not in ROLES:
        print(pick(lang, "✗ unknown role; see: dai-agent roles", "✗ תפקיד לא מוכר; ראו: dai-agent roles"), file=sys.stderr)
        return 2
    script = None
    if (script_path := _option(args, "--script")) is not None:
        try:
            script = json.loads(Path(script_path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"✗ --script: {exc}", file=sys.stderr)
            return 2
        if not isinstance(script, list) or not all(isinstance(s, dict) for s in script):
            print(pick(lang, "✗ --script: a JSON list of steps", "✗ --script: רשימת JSON של צעדים"), file=sys.stderr)
            return 2
    flags = {"--yes", "--dry-run", "--notify"}
    words = []
    skip = False
    for i, a in enumerate(args):
        if skip:
            skip = False
            continue
        if a in ("--role", "--script"):
            skip = True
            continue
        if a in flags:
            continue
        if a.startswith("--"):
            print(__doc__.strip(), file=sys.stderr)
            return 2
        words.append(a)
    goal = " ".join(words).strip()
    if services is None:
        from dai_tune.context import Context
        services = Services(ctx=Context(lang=lang), lang=lang, home=home)
    services.assume_yes = "--yes" in args
    services.dry_run = "--dry-run" in args
    services.label = f"D.Ai Agent: {goal[:60]}"
    try:
        from dai_ai.client import where
        if where("general") != "local" and script is None:
            print(pick(lang, "Note: the goal and the tools' results go to {p} (your own key).", "שימו לב: המטרה ותוצאות הכלים נשלחות ל־{p} (במפתח שלך).").format(p=where("general")))
    except Exception:  # noqa: BLE001 - no dai_ai: local
        pass
    print(pick(lang, "Goal: {goal}  [{role}]", "מטרה: {goal}  [{role}]").format(goal=goal, role=role_name))
    try:
        run = run_agent(goal, services, chat=chat, role=ROLES[role_name], script=script, home=home,
                        approve=lambda step: (services.assume_yes and quiet_ok(step, services)) or ask(step, lang, ask_input))
    except AgentError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    print()
    print(run.final)
    if "--notify" in args:
        notify_final(run, lang, services.run)
    print(pick(lang, "(run {id}: dai-agent history)", "(ריצה {id}: dai-agent history)").format(id=run.id))
    return {"done": 0, "stopped": 1, "failed": 1, "no-plan": 3}.get(run.status, 1)
