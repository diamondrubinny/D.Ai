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
RECORD_MIN, RECORD_MAX = 5, 600


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
    ask_person: Callable[[str], str | None] | None = None   # the ask tool: a question to the person; None = nobody there
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


def _j_dir(services: Services) -> Path:
    """J's data folder: the test's own, or ~/.local/share/dai-j (never created here)."""
    if services.extra.get("j_dir") is not None:
        return Path(services.extra["j_dir"])
    if services.home is not None:
        return services.home / ".local/share/dai-j"
    from dai_j.accounts import data_dir
    return data_dir()


def _inbox(services: Services, limit: int) -> list[dict]:
    from dai_j.accounts import load
    from dai_j.store import Store
    folder = _j_dir(services)
    accounts = [a.id for a in load(folder)] if (folder / "accounts.json").is_file() else []
    if not accounts or not (folder / "mail.sqlite").is_file():
        return []
    store = Store(folder / "mail.sqlite")
    try:
        return store.listing(accounts, role="inbox", limit=limit)
    finally:
        store.close()


def _when(stamp: float) -> str:
    from datetime import datetime
    try:
        return datetime.fromtimestamp(float(stamp)).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError, TypeError):
        return ""


def mail(services: Services, limit: int = 5) -> str:
    """The newest inbox messages from J's own store: sender, subject, date. No network, no bodies."""
    rows = _inbox(services, max(1, min(limit, 10)))
    if not rows:
        return pick(services.lang, "J has no mail on this computer (no account, or nothing fetched yet).",
                    "אין דואר של J במחשב הזה (אין חשבון, או שעדיין לא הורד דבר).")
    lines = []
    for number, row in enumerate(rows, 1):
        mark = "" if row.get("seen") else "● "
        lines.append(f"{number}. {mark}{row.get('sender') or row.get('sender_address') or '?'}: {row.get('subject') or '(no subject)'}  [{_when(row.get('date', 0))}]")
    return "\n".join(lines)


def mail_summary(services: Services, number: int = 1) -> str:
    """Diamond's summary of the N-th newest inbox message (1 = newest), through J's own summary prompt."""
    from dai_j import diamond
    from dai_j.mail import parse_body
    from dai_j.sanitize import html_to_text
    from dai_j.store import Store
    rows = _inbox(services, max(1, min(number, 10)))
    if len(rows) < max(1, number):
        return pick(services.lang, "There is no message number {n}.", "אין הודעה מספר {n}.").format(n=number)
    row = rows[max(1, number) - 1]
    store = Store(_j_dir(services) / "mail.sqlite")
    try:
        raw = store.body(row["account"], row["folder"], int(row["uid"]))
    finally:
        store.close()
    head = f"{row.get('sender') or row.get('sender_address') or '?'}: {row.get('subject') or '(no subject)'}"
    if not raw:
        return pick(services.lang, "{head} — J has not downloaded this message yet; open it in J first.",
                    "{head} — J עדיין לא הוריד את ההודעה הזאת; פתחו אותה ב־J קודם.").format(head=head)
    body = parse_body(raw)
    text = body.text or html_to_text(body.html)
    said = diamond.answer(diamond.summary_messages(row.get("sender") or row.get("sender_address") or "", row.get("subject") or "",
                                                   text, services.lang), chat=services.extra.get("chat"))
    return f"{head}\n" + (said or pick(services.lang, "Diamond is not available.", "Diamond לא זמין."))


def explain(services: Services, text: str) -> str:
    """D.Ai Explain on a text (an error, a message): the explanation and, when Tune understands it, a sentence."""
    from dai_explain.engine import ExplainError
    from dai_explain.engine import explain as explain_text
    try:
        out = explain_text(text, services.lang, chat=services.extra.get("chat"))
    except ExplainError as exc:
        raise ToolError(str(exc)) from exc
    result = out.text
    if out.suggestion:
        result += "\n" + pick(services.lang, "Suggested D.Ai Tune sentence: {s}", "משפט D.Ai Tune מוצע: {s}").format(s=out.suggestion)
    return result


def look(services: Services, question: str = "") -> str:
    """What is on the screen now (docs/AGENTS.md §6ה): a picture in memory only, D.Ai Explain's answer. With a
    vision model installed Diamond looks at the picture on this computer; otherwise only the text read from it
    goes to Diamond (or to the provider chosen for general questions)."""
    from dai_explain.engine import ExplainError, capture_screen, explain as explain_screen, read_text, vision_model
    capture = services.extra.get("capture") or (lambda: capture_screen(services.run))
    reader = services.extra.get("read_text") or (lambda image: read_text(image, services.lang, services.run))
    sees = services.extra.get("sees") or vision_model
    try:
        image = capture()
        text = reader(image) if sees() is None else ""
        if question:
            text = f"{question}\n\n{text}".strip()
        out = explain_screen(text, services.lang, chat=services.extra.get("chat"), image=image, sees=sees)
    except ExplainError as exc:
        raise ToolError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - no OCR, no grim: one clear line, never the agent down
        raise ToolError(pick(services.lang, "Could not look at the screen: {e}", "לא הצלחתי להסתכל על המסך: {e}").format(e=exc)) from exc
    result = out.text
    if out.suggestion:
        result += "\n" + pick(services.lang, "Suggested D.Ai Tune sentence: {s}", "משפט D.Ai Tune מוצע: {s}").format(s=out.suggestion)
    return result


def _last_entry(services: Services) -> str:
    """The id of the newest applied D.Ai Tune journal entry, "" when there is none or no Tune."""
    try:
        from dai_tune.executor import Journal
        entry = Journal.for_user(services.ctx).find("last")
    except Exception:  # noqa: BLE001 - tests without a Tune journal
        return ""
    return str(entry.get("id", "")) if entry else ""


def ask(services: Services, question: str) -> str:
    """One question to the person (docs/AGENTS.md §6ו). Nobody there (a timer): a clear line, never a wait."""
    if services.ask_person is None:
        return pick(services.lang, "Nobody can answer now (no person at this run); decide with what you know.",
                    "אין מי שיענה עכשיו (אין אדם בריצה הזאת); החליטו לפי מה שידוע.")
    answer = services.ask_person(question)
    if answer is None or not answer.strip():
        return pick(services.lang, "The person did not answer.", "האדם לא ענה.")
    return pick(services.lang, "The person answered: {a}", "האדם ענה: {a}").format(a=" ".join(answer.split())[:MAX_TEXT])


# ---------------------------------------------------------------- act tools

def record(services: Services, seconds: int) -> str:
    """A screen recording that stops by itself (dai-record start N). The person approved the seconds."""
    if not RECORD_MIN <= seconds <= RECORD_MAX:
        raise ToolError(f"record: seconds must be {RECORD_MIN} to {RECORD_MAX}")
    if services.dry_run:
        return pick(services.lang, "Dry run: would record {n} seconds.", "הרצת ניסיון: היה מקליט {n} שניות.").format(n=seconds)
    try:
        done = services.run(["dai-record", "start", str(seconds)], capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ToolError(pick(services.lang, "D.Ai Record did not start: {e}", "D.Ai Record לא התחיל: {e}").format(e=exc)) from exc
    if done.returncode != 0:
        raise ToolError(pick(services.lang, "D.Ai Record did not start: {e}", "D.Ai Record לא התחיל: {e}").format(e=(done.stderr or done.stdout or "").strip()[-200:]))
    return pick(services.lang, "Recording {n} seconds; the file goes to ~/Videos/Recordings.",
                "מקליט {n} שניות; הקובץ יישמר ב־~/Videos/Recordings.").format(n=seconds)


def remember(services: Services, text: str) -> str:
    """One approved line into the agent's memory (docs/AGENTS.md §6ב)."""
    from . import memory
    if services.dry_run:
        return pick(services.lang, "Dry run: would remember: {t}", "הרצת ניסיון: היה זוכר: {t}").format(t=text)
    try:
        rows = memory.add(services.home, text)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    return pick(services.lang, "Remembered ({n} lines; dai-agent memory).", "נזכר ({n} שורות; dai-agent memory).").format(n=len(rows))


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
    before = _last_entry(services)
    code = execute(made, services.ctx, dry_run=services.dry_run, assume_yes=quiet, label=services.label)
    after = _last_entry(services)
    if after and after != before:
        services.extra.setdefault("entries", []).append(after)       # the run's journal keeps it (docs/AGENTS.md §6ו)
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
    Tool("mail", "read", "The newest messages in the person's inbox (J): sender, subject, date; ● = unread. args: limit (1-10)", {"limit": "int"}, mail),
    Tool("mail_summary", "read", "A short summary of one inbox message by its number in the mail list (1 = newest). args: number", {"number": "int"}, mail_summary, ("number",)),
    Tool("explain", "read", "Explain a text the person saw (an error, a message, a setting) in plain words, with a D.Ai Tune sentence when one fixes it. args: text", {"text": "str"}, explain, ("text",)),
    Tool("look", "read", "Look at the screen now and say what is on it (an error, a page, a dialog). args: question (optional, what to look for)", {"question": "str"}, look),
    Tool("do", "act", "Apply a D.Ai Tune sentence (settings, security, apps, reminders, notes), e.g. 'lock the screen after 5 minutes'. The person approves first. args: sentence", {"sentence": "str"}, do, ("sentence",)),
    Tool("remind", "act", "Set a reminder. args: text, and in_minutes (number) or at ('18:30')", {"text": "str", "in_minutes": "int", "at": "str"}, remind, ("text",)),
    Tool("note", "act", "Write one line into the person's notes. args: text", {"text": "str"}, note, ("text",)),
    Tool("record", "act", "Record the screen for a number of seconds (no sound); it stops by itself. args: seconds (5-600)", {"seconds": "int"}, record, ("seconds",)),
    Tool("remember", "act", "Keep one line for later runs (a fact about the person, a preference). The person approves first. args: text", {"text": "str"}, remember, ("text",)),
    Tool("ask", "light", "Ask the person one short question when the goal is unclear (which file, which time, yes or no). args: question", {"question": "str"}, ask, ("question",)),
    Tool("say", "light", "Read a short text aloud. args: text", {"text": "str"}, say, ("text",)),
    Tool("notify", "light", "Show a short notification. args: text", {"text": "str"}, notify, ("text",)),
)}


def run_tool(name: str, args: Any, services: Services) -> str:
    tool = TOOLS.get(name)
    if tool is None:
        raise ToolError(f"unknown tool: {name}")
    clean = check_args(tool, args)
    return _clip(tool.run(services, **clean))
