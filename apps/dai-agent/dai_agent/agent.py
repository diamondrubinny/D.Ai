# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The loop (docs/AGENTS.md §2): one strict-JSON step at a time from Diamond, the closed toolbox, approval
before every act, a bounded number of steps, and a journal of the run."""
from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from dai_i18n import english_name, pick

from .roles import ROLES, Role
from .tools import MAX_TEXT, TOOLS, Services, Tool, ToolError, run_tool

MAX_STEPS = 8
MAX_ANSWER = 2000
MAX_TOKENS = 400
JOURNAL_DIR = ".local/share/dai/agents"
TOOL_TIMEOUT = 120


class AgentError(RuntimeError):
    pass


@dataclass
class StepRecord:
    tool: str
    args: dict[str, Any]
    thought: str = ""
    approved: bool | None = None     # None: a read tool (no question asked)
    result: str = ""
    error: str = ""


@dataclass
class Run:
    id: str
    goal: str
    role: str
    started: str
    steps: list[StepRecord] = field(default_factory=list)
    final: str = ""
    status: str = "running"          # done | stopped | failed | no-plan

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "goal": self.goal, "role": self.role, "started": self.started, "status": self.status,
                "final": self.final, "steps": [s.__dict__ for s in self.steps]}


def _args_schema(tool: Tool) -> dict[str, Any]:
    """The args object of one tool: only its names, its types, its bounds. Unknown names cannot be generated."""
    properties: dict[str, Any] = {}
    for key, kind in tool.args.items():
        if kind == "int":
            properties[key] = {"type": "integer", "minimum": 0, "maximum": 10 ** 6}
        else:
            properties[key] = {"type": "string", "maxLength": MAX_TEXT}
    return {"type": "object", "properties": properties, "required": list(tool.required), "additionalProperties": False}


def step_schema(tool_names: list[str]) -> dict[str, Any]:
    """One step: a thought, a tool (or "done"), its args, and the final answer when done.

    One branch per tool (anyOf + const), each with that tool's own args schema: with the grammar enforced
    (docs/AI.md §5) the model cannot name a tool outside the role nor invent an argument. The first VM run
    with a real schema showed a 0.5B model adding an "answer" argument to facts, three times in a row.
    """
    branches = []
    for name in tool_names:
        branches.append({
            "type": "object",
            "properties": {
                "thought": {"type": "string", "maxLength": 300},
                "tool": {"const": name},
                "args": _args_schema(TOOLS[name]),
                "final": {"type": "string", "maxLength": 0},
            },
            "required": ["thought", "tool", "args", "final"],
            "additionalProperties": False,
        })
    branches.append({
        "type": "object",
        "properties": {
            "thought": {"type": "string", "maxLength": 300},
            "tool": {"const": "done"},
            "args": {"type": "object", "properties": {}, "additionalProperties": False},
            "final": {"type": "string", "maxLength": MAX_ANSWER},
        },
        "required": ["thought", "tool", "args", "final"],
        "additionalProperties": False,
    })
    return {"anyOf": branches}


def system_prompt(role: Role, lang: str) -> str:
    lines = [
        "You are Diamond, the assistant built into D.Ai OS, working as an agent. You reach the person's goal with the",
        "tools below, one step at a time. Reply with ONE JSON object per step: {\"thought\", \"tool\", \"args\", \"final\"}.",
        "Use only these tools (name, what it does, args):",
    ]
    for name in role.tools:
        tool = TOOLS[name]
        lines.append(f"- {name} ({tool.risk}): {tool.describe}")
    lines += [
        "- done: finish; put the answer for the person in \"final\" (in " + english_name(lang) + ").",
        "Rules: tool results come back as messages; never invent results; a tool marked act asks the person first, so",
        "do not repeat it if it was refused; when a tool returned nothing useful, do not call it again: finish with",
        "what you know; Tune sentences are in English; at most " + str(MAX_STEPS) + " steps.",
        role.guidance,
    ]
    return "\n".join(lines)


def _collect(chat: Callable, messages: list[dict[str, Any]], schema: dict[str, Any]) -> dict[str, Any]:
    reply = "".join(chat(messages, schema=schema, max_tokens=MAX_TOKENS, task="general"))
    try:
        data = json.loads(reply)
    except json.JSONDecodeError as exc:
        raise AgentError("Diamond's step was not valid JSON") from exc
    if not isinstance(data, dict):
        raise AgentError("Diamond's step was not an object")
    return data


def journal_path(home: Path | None, run_id: str) -> Path:
    return (home or Path.home()) / JOURNAL_DIR / f"{run_id}.json"


def save(run: Run, home: Path | None) -> Path:
    path = journal_path(home, run.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(run.to_json(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)
    return path


def history(home: Path | None, limit: int = 20) -> list[dict[str, Any]]:
    folder = (home or Path.home()) / JOURNAL_DIR
    rows = []
    for path in sorted(folder.glob("*.json"), reverse=True)[:limit]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("goal"), str):
            rows.append(data)
    return rows


def run_agent(goal: str, services: Services, chat: Callable | None = None, role: Role | None = None,
              approve: Callable[[StepRecord], bool] | None = None, script: list[dict[str, Any]] | None = None,
              say: Callable[[str], None] = print, home: Path | None = None) -> Run:
    """Reach `goal`. With `script`, the steps are given (no model). approve(step) decides every act tool."""
    role = role or ROLES["all"]
    lang = services.lang
    run = Run(secrets.token_hex(4), goal.strip(), role.name, datetime.now().strftime("%Y-%m-%dT%H:%M"))
    if not run.goal:
        raise AgentError(pick(lang, "Say what the agent should do.", "תגידו מה הסוכן צריך לעשות."))
    if chat is None and script is None:
        from dai_ai.client import chat as client_chat
        chat = client_chat
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt(role, lang)},
                                      {"role": "user", "content": run.goal}]
    schema = step_schema(list(role.tools))
    seen: set[str] = set()
    for index in range(MAX_STEPS):
        if script is not None:
            if index >= len(script):
                run.status, run.final = "done", run.final or pick(lang, "Script finished.", "התסריט הסתיים.")
                break
            data = script[index]
        else:
            try:
                data = _collect(chat, messages, schema)
            except Exception as exc:  # noqa: BLE001 - daid down, a provider error, bad JSON: one clear line
                run.status = "no-plan"
                run.final = pick(lang, "Diamond could not plan this step: {error}", "Diamond לא הצליח לתכנן את הצעד: {error}").format(error=exc)
                break
        name = str(data.get("tool", ""))
        args = data.get("args") if isinstance(data.get("args"), dict) else {}
        thought = str(data.get("thought", ""))[:300]
        if name == "done":
            run.final = str(data.get("final", ""))[:MAX_ANSWER].strip() or pick(lang, "Done.", "בוצע.")
            run.status = "done"
            break
        record = StepRecord(name, args, thought)
        run.steps.append(record)
        if name not in role.tools or name not in TOOLS:
            record.error = pick(lang, "not a tool of this role: {name}", "לא כלי של התפקיד הזה: {name}").format(name=name)
            messages.append({"role": "assistant", "content": json.dumps(data, ensure_ascii=False)})
            messages.append({"role": "user", "content": f"Error: {record.error}. Use only the listed tools."})
            say(f"✗ {record.error}")
            continue
        key = json.dumps([name, args], sort_keys=True, ensure_ascii=False)
        if key in seen and TOOLS[name].risk == "read":
            run.status = "stopped"
            run.final = pick(lang, "Stopped: the same step was repeated.", "נעצר: אותו צעד חזר על עצמו.")
            break
        seen.add(key)
        say(("→ " if TOOLS[name].risk == "read" else "⚠ ") + f"{name} {json.dumps(args, ensure_ascii=False)}" + (f"  — {thought}" if thought else ""))
        if TOOLS[name].risk == "act":
            record.approved = bool(approve(record)) if approve is not None else False
            if not record.approved:
                record.error = pick(lang, "not approved", "לא אושר")
                messages.append({"role": "assistant", "content": json.dumps(data, ensure_ascii=False)})
                messages.append({"role": "user", "content": f"The person did not approve {name}. Do not try it again; finish or choose another way."})
                say(pick(lang, "  skipped (not approved)", "  דולג (לא אושר)"))
                continue
        try:
            record.result = run_tool(name, args, services)
        except ToolError as exc:
            record.error = str(exc)
        except Exception as exc:  # noqa: BLE001 - a tool must never take the agent down
            record.error = f"{name} failed: {exc}"
        messages.append({"role": "assistant", "content": json.dumps(data, ensure_ascii=False)})
        messages.append({"role": "user", "content": (f"Result of {name}:\n{record.result}" if not record.error else f"Error from {name}: {record.error}")})
        say(("  " + record.result.replace("\n", "\n  ")) if record.result else f"  ✗ {record.error}")
    else:
        run.status = "stopped"
        run.final = pick(lang, "Stopped after {n} steps.", "נעצר אחרי {n} צעדים.").format(n=MAX_STEPS)
    if run.status == "running":
        run.status = "done"
    save(run, home)
    return run
