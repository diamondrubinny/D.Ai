# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""What an act step would do, before it is approved (docs/AGENTS.md §6, §6ב): the D.Ai Tune plan of a
do/note/remind step, or one sentence for record/remember. No widgets here: the window, the CLI's --yes and a
timer all use it."""
from __future__ import annotations

from typing import Any

from dai_i18n import pick

from .agent import StepRecord
from .tools import Services


def tune_sentence(record: StepRecord) -> str:
    """The D.Ai Tune sentence a do/note/remind step applies; "" for other tools."""
    if record.tool == "do":
        return str(record.args.get("sentence", ""))
    if record.tool == "note":
        return f"note: {record.args.get('text', '')}"
    if record.tool == "remind":
        text, minutes, at = record.args.get("text", ""), record.args.get("in_minutes", 0), record.args.get("at", "")
        return f"remind me in {minutes} minutes to {text}" if minutes else (f"remind me at {at} to {text}" if at else f"remind me to {text}")
    return ""


def describe_act(record: StepRecord, services: Services) -> dict[str, Any]:
    """{"tool", "args", "rows", "weakens", "system", "error"}: the Tune plan rows of the step, whether it weakens
    security or needs the administrator; for record/remember one row in words. A sentence Tune does not
    understand is said so in "error"."""
    info: dict[str, Any] = {"tool": record.tool, "args": record.args, "rows": [], "weakens": False, "system": False, "error": ""}
    lang = services.lang
    if record.tool == "record":
        seconds = record.args.get("seconds", 0)
        info["rows"] = [pick(lang, "Record the screen for {n} seconds (no sound), to ~/Videos/Recordings.",
                             "הקלטת המסך למשך {n} שניות (בלי קול), אל ~/Videos/Recordings.").format(n=seconds)]
        return info
    if record.tool == "focus":
        info["rows"] = [pick(lang, "Focus for {n} minutes: no pop-ups, warmer light; the timer ends it.",
                             "פוקוס ל־{n} דקות: בלי הודעות קופצות, אור חם יותר; הטיימר מסיים.").format(n=record.args.get("minutes", 25))]
        return info
    if record.tool == "remember":
        info["rows"] = [pick(lang, "Remember for later runs: {text}", "לזכור לריצות הבאות: {text}").format(text=record.args.get("text", ""))]
        return info
    sentence = tune_sentence(record)
    if not sentence:
        return info
    try:
        from dai_tune.cli import describe
        from dai_tune.planner import plan_from_text
    except ImportError:
        return info
    try:
        made = plan_from_text(sentence, services.ctx)
    except Exception as exc:  # noqa: BLE001 - shown on the card, never swallowed
        info["error"] = str(exc)
        return info
    if not made.ok:
        info["error"] = "; ".join(list(made.unknown) + list(made.errors)) or sentence
        return info
    info["rows"] = [str(row.get("summary", "")) for row in describe(made, lang)]
    info["weakens"] = bool(made.weakens)
    info["system"] = bool(made.scoped("system"))
    return info


def quiet_ok(record: StepRecord, services: Services) -> bool:
    """What --yes may approve without a person: a user-scope step that keeps or hardens security. A do step
    is checked against its Tune plan; record and remember are user-scope by nature; anything else is not."""
    if record.tool in ("remember", "record", "focus", "note", "remind"):
        return True
    if record.tool != "do":
        return False
    info = describe_act(record, services)
    return not info["error"] and bool(info["rows"]) and not info["weakens"] and not info["system"]
