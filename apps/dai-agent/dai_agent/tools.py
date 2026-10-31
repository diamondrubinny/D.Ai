# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The closed toolbox (docs/AGENTS.md §2). A tool is a name, a risk, a description for Diamond, an argument
schema and a function. "read" tools run at once; "act" tools only after the person approves; "light" tools
(sound, a notice) run at once but are shown. Text is always an argument, never a shell."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from dai_i18n import pick

MAX_TEXT = 500
MAX_RESULT = 1500


class ToolError(RuntimeError):
    pass


@dataclass(frozen=True)
class Tool:
    name: str
    risk: str                      # read | act | light
    describe: str                  # one line for Diamond, in English
    args: dict[str, str]           # name -> "str" | "int"
    run: Callable[..., str]
    required: tuple[str, ...] = ()


@dataclass
class Services:
    """What the tools reach; tests pass fakes. ctx is a dai_tune Context (lang, home, runner)."""
    ctx: Any = None
    lang: str = "en"
    home: Path | None = None
    assume_yes: bool = False
    dry_run: bool = False
    execute: Callable[..., int] | None = None     # dai_tune.cli.execute_plan(plan, ctx, dry_run=, assume_yes=, label=)
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run
    speak: Callable[[str, str], bool] | None = None
    label: str = "D.Ai Agent"
    extra: dict[str, Any] = field(default_factory=dict)


def _clip(text: str, limit: int = MAX_RESULT) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + " …"


def check_args(tool: Tool, args: Any) -> dict[str, Any]:
    """Only known names, the right types, bounded text. Unknown or missing: a ToolError (never a guess)."""
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ToolError(f"{tool.name}: args must be an object")
    clean: dict[str, Any] = {}
    for key, value in args.items():
        if key not in tool.args:
            raise ToolError(f"{tool.name}: unknown argument {key!r}")
        kind = tool.args[key]
        if kind == "int":
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10 ** 6:
                raise ToolError(f"{tool.name}: {key} must be a whole number")
        else:
            if not isinstance(value, str) or "\n" in value or len(value) > MAX_TEXT:
                raise ToolError(f"{tool.name}: {key} must be one line of up to {MAX_TEXT} characters")
            value = value.strip()
        clean[key] = value
    for key in tool.required:
        if key not in clean or clean[key] in ("", None):
            raise ToolError(f"{tool.name}: {key} is required")
    return clean


# ---------------------------------------------------------------- read tools

def facts(services: Services, question: str) -> str:
    from dai_ai.knowledge import relevant
    found = relevant(question, services.lang, limit=4)
    return "\n".join(found) if found else pick(services.lang, "Nothing in D.Ai's own facts about that.", "אין עובדה של D.Ai על זה.")


def find(services: Services, query: str) -> str:
    from dai_find.query import parse
    from dai_find.search import search
    hits = search(parse(query, lang=services.lang), home=services.home, limit=10)
    if not hits:
        return pick(services.lang, "No files match.", "אין קבצים מתאימים.")
    return "\n".join(str(hit.path) for hit in hits)


def reminders(services: Services) -> str:
    from dai_remind.engine import describe, upcoming
    rows = upcoming(services.home)
    return "\n".join(describe(r, services.lang) for r in rows) if rows else pick(services.lang, "No reminders.", "אין תזכורות.")


def posture(services: Services) -> str:
    from dai_tune.posture import assess, title
    score, checks = assess(services.ctx, services.lang)
    lines = [pick(services.lang, "Security {score}/100", "אבטחה {score}/100").format(score=score)]
    lines += [("✓ " if check.ok else "✗ ") + title(check, services.lang) for check in checks]
    return "\n".join(lines)


def doctor(services: Services, topic: str = "slow") -> str:
    from dai_doctor.diagnose import TOPICS, diagnose
    from dai_doctor.facts import collect
    if topic not in TOPICS:
        raise ToolError("doctor: topic must be one of " + ", ".join(TOPICS))
    found = diagnose(collect(home=services.home, topics=(topic,)), (topic,), services.lang)
    return "\n".join(f"[{f.level}] {f.title}" + (f": {f.detail}" if f.detail else "") for f in found) or pick(services.lang, "Nothing to report.", "אין מה לדווח.")


def plan(services: Services, sentence: str) -> str:
    from dai_tune.cli import describe
    from dai_tune.planner import plan_from_text
    made = plan_from_text(sentence, services.ctx)
    if not made.ok:
        return pick(services.lang, "Not understood: {parts}", "לא מובן: {parts}").format(parts="; ".join(made.unknown + made.errors) or sentence)
    return "\n".join(f"{row['summary']} ({row.get('scope', '')}, {row.get('effect', '')})" for row in describe(made, services.lang))


# ---------------------------------------------------------------- act tools

def do(services: Services, sentence: str) -> str:
    """A D.Ai Tune sentence through the same execute_plan as dai-tune: printed plan, confirmation, journal."""
    from dai_tune.planner import plan_from_text
    made = plan_from_text(sentence, services.ctx)
    if not made.ok:
        raise ToolError(pick(services.lang, "Tune did not understand: {parts}", "Tune לא הבין: {parts}").format(parts="; ".join(made.unknown + made.errors) or sentence))
    if services.execute is None:
        from dai_tune.cli import execute_plan
        execute = execute_plan
    else:
        execute = services.execute
    # --yes never covers a weakening or a system step: those always ask the person (docs/AGENTS.md §3).
    quiet = services.assume_yes and not made.weakens and not made.scoped("system")
    code = execute(made, services.ctx, dry_run=services.dry_run, assume_yes=quiet, label=services.label)
    if code != 0:
        raise ToolError(pick(services.lang, "Not applied (dai-tune said no, or you cancelled).", "לא בוצע (Tune סירב, או שביטלתם)."))
    return pick(services.lang, "Applied: {sentence}", "בוצע: {sentence}").format(sentence=sentence) if not services.dry_run else \
        pick(services.lang, "Dry run: {sentence}", "הרצת ניסיון: {sentence}").format(sentence=sentence)


def remind(services: Services, text: str, in_minutes: int = 0, at: str = "") -> str:
    if in_minutes:
        sentence = f"remind me in {in_minutes} minutes to {text}"
    elif at:
        sentence = f"remind me at {at} to {text}"
    else:
        sentence = f"remind me to {text}"
    return do(services, sentence)


def note(services: Services, text: str) -> str:
    return do(services, f"note: {text}")


def say(services: Services, text: str) -> str:
    if services.speak is not None:
        ok = services.speak(text, services.lang)
    else:
        try:
            from dai_speak import client
            ok = client.read(text, services.lang)
        except ImportError:
            ok = False
    return pick(services.lang, "Said aloud.", "נאמר בקול.") if ok else pick(services.lang, "D.Ai Speak is not available.", "D.Ai Speak לא זמין.")


def notify(services: Services, text: str) -> str:
    try:
        services.run(["notify-send", "-a", "D.Ai Agent", "-i", "dialog-information", "D.Ai Agent", text],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return pick(services.lang, "No notification service.", "אין שירות הודעות.")
    return pick(services.lang, "Shown.", "הוצג.")


TOOLS: dict[str, Tool] = {t.name: t for t in (
    Tool("facts", "read", "What D.Ai itself knows (shortcuts, apps, how things work). args: question", {"question": "str"}, facts, ("question",)),
    Tool("find", "read", "Find the person's files by meaning, time or content, e.g. 'photos from last week', 'the file about the lease'. args: query", {"query": "str"}, find, ("query",)),
    Tool("reminders", "read", "List the person's upcoming reminders.", {}, reminders),
    Tool("posture", "read", "The security score and which checks fail.", {}, posture),
    Tool("doctor", "read", "D.Ai Doctor findings. args: topic = slow | disk | battery | hardware | update", {"topic": "str"}, doctor),
    Tool("plan", "read", "What a D.Ai Tune sentence would change, without changing it. args: sentence (English, e.g. 'block usb storage')", {"sentence": "str"}, plan, ("sentence",)),
    Tool("do", "act", "Apply a D.Ai Tune sentence (settings, security, apps, reminders, notes), e.g. 'lock the screen after 5 minutes'. The person approves first. args: sentence", {"sentence": "str"}, do, ("sentence",)),
    Tool("remind", "act", "Set a reminder. args: text, and in_minutes (number) or at ('18:30')", {"text": "str", "in_minutes": "int", "at": "str"}, remind, ("text",)),
    Tool("note", "act", "Write one line into the person's notes. args: text", {"text": "str"}, note, ("text",)),
    Tool("say", "light", "Read a short text aloud. args: text", {"text": "str"}, say, ("text",)),
    Tool("notify", "light", "Show a short notification. args: text", {"text": "str"}, notify, ("text",)),
)}


def run_tool(name: str, args: Any, services: Services) -> str:
    tool = TOOLS.get(name)
    if tool is None:
        raise ToolError(f"unknown tool: {name}")
    clean = check_args(tool, args)
    return _clip(tool.run(services, **clean))
