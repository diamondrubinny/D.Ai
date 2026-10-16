"""dai-tune command line: plan, confirm, apply, undo, status."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

from . import __version__
from .catalog import CATALOG
from .context import Context, detect_lang
from .executor import ApplyError, Journal, apply_steps, undo_entry
from .parser import EXAMPLES
from .planner import Plan, plan_from_text, plan_hash
from .posture import assess, title

HELPER = "/usr/lib/dai/dai-tune-helper"

LABELS = {
    "scope": {"user": ("user", "משתמש"), "system": ("system", "מערכת")},
    "risk": {"low": ("low risk", "סיכון נמוך"), "medium": ("medium risk", "סיכון בינוני"), "high": ("HIGH RISK", "סיכון גבוה")},
    "effect": {"hardens": ("hardens security", "מחזק אבטחה"), "weakens": ("WEAKENS security", "מחליש אבטחה"), "neutral": ("neutral", "ניטרלי")},
}
ICONS = {"hardens": "🛡 ", "weakens": "⚠ ", "neutral": "• "}


def _l(lang: str, en: str, he: str) -> str:
    return he if lang == "he" else en


def _label(kind: str, value: str, lang: str) -> str:
    en, he = LABELS[kind][value]
    return he if lang == "he" else en


def _color(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if sys.stdout.isatty() else text


def describe(plan: Plan, lang: str) -> list[dict[str, Any]]:
    rows = []
    for step in plan.steps:
        spec = CATALOG[step.action]
        rows.append({
            "action": step.action,
            "params": step.params,
            "scope": step.scope,
            "risk": step.risk,
            "effect": step.effect,
            "summary": spec.summary(step.params, lang),
            "note": spec.note(step.params, lang),
        })
    return rows


def print_plan(plan: Plan, lang: str) -> None:
    print(_color(_l(lang, f"D.Ai Tune — change plan  #{plan.hash}", f"D.Ai Tune — תוכנית שינויים  #{plan.hash}"), "1"))
    for index, row in enumerate(describe(plan, lang), 1):
        tags = " · ".join([
            _label("scope", row["scope"], lang), _label("risk", row["risk"], lang), _label("effect", row["effect"], lang)
        ])
        color = "33" if row["effect"] == "weakens" else ("32" if row["effect"] == "hardens" else "0")
        print(f"  {index}. {ICONS[row['effect']]}{row['summary']}")
        print("     " + _color(tags, color))
        if row["note"]:
            print("     ↳ " + row["note"])
    for clause in plan.unknown:
        print(_color("  ✗ " + _l(lang, f"Not understood: “{clause}”", f"לא הובן: „{clause}”"), "31"))
    for error in plan.errors:
        print(_color("  ✗ " + error, "31"))


def confirm(plan: Plan, lang: str, assume_yes: bool) -> bool:
    if plan.weakens:
        if assume_yes:
            print(_l(lang, "Refusing --yes: this plan weakens security and needs explicit confirmation.",
                     "‎--yes נדחה: התוכנית מחלישה אבטחה ודורשת אישור מפורש."))
            return False
        answer = input(_l(lang, 'This plan WEAKENS security. Type "yes" to apply: ',
                          'התוכנית מחלישה אבטחה. להחלה הקלידו "כן": ')).strip().casefold()
        return answer in ("yes", "כן")
    if assume_yes:
        return True
    answer = input(_l(lang, "Apply? [y/N] ", "להחיל? [כ/ל] ")).strip().casefold()
    return answer in ("y", "yes", "כ", "כן")


def run_helper(args: list[str], payload: dict | None = None) -> dict[str, Any]:
    """Run the root helper through polkit (or sudo when DAI_TUNE_ELEVATE=sudo)."""
    if os.geteuid() == 0:
        elevate: list[str] = []
    else:
        method = os.environ.get("DAI_TUNE_ELEVATE", "pkexec")
        elevate = ["sudo"] if method == "sudo" else ["pkexec"]
    result = subprocess.run(
        [*elevate, HELPER, *args],
        input=json.dumps(payload) if payload is not None else "",
        stdout=subprocess.PIPE,
        text=True,
        check=False,
    )
    try:
        data = json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        data = {"ok": False, "error": f"helper exited with {result.returncode} (authorization cancelled?)"}
    return data


def cmd_apply(text: str, ctx: Context, dry_run: bool, as_json: bool, assume_yes: bool) -> int:
    lang = ctx.lang
    plan = plan_from_text(text, ctx)
    if as_json:
        print(json.dumps({
            "ok": plan.ok, "hash": plan.hash, "risk": plan.risk, "weakens": plan.weakens,
            "unknown": plan.unknown, "errors": plan.errors, "steps": describe(plan, lang),
        }, ensure_ascii=False, indent=2))
        return 0 if plan.ok else 2
    print_plan(plan, lang)
    if not plan.ok:
        if not plan.steps and not plan.errors:
            print(_l(lang, 'Nothing was changed. See what you can ask: dai-tune help',
                     'לא בוצע שום שינוי. מה אפשר לבקש: dai-tune help'))
        else:
            print(_l(lang, "Nothing was changed. Please rephrase the parts above.",
                     "לא בוצע שום שינוי. נסחו מחדש את החלקים שסומנו."))
        return 2
    if dry_run:
        print(_l(lang, "(dry run — nothing was changed)", "(הרצת ניסיון — לא בוצע שינוי)"))
        return 0
    if not confirm(plan, lang, assume_yes):
        print(_l(lang, "Cancelled. Nothing was changed.", "בוטל. לא בוצע שום שינוי."))
        return 1

    system_steps = plan.scoped("system")
    system_id = None
    if system_steps:
        payload = {"version": 1, "hash": plan_hash(system_steps), "steps": [s.as_dict() for s in system_steps]}
        result = run_helper(["apply"], payload)
        if not result.get("ok"):
            print(_color("✗ " + str(result.get("error")), "31"))
            print(_l(lang, "Nothing was changed.", "לא בוצע שום שינוי."))
            return 1
        system_id = result["id"]

    journal = Journal.for_user(ctx)
    summaries = [row["summary"] for row in describe(plan, lang)]
    try:
        apply_steps(plan.scoped("user"), ctx, journal, actor=str(os.getuid()), scope="user",
                    extra={"system_entry": system_id, "summary": summaries})
    except ApplyError as exc:
        print(_color(f"✗ {exc}", "31"))
        if system_id:
            run_helper(["undo", system_id])
            print(_l(lang, "System changes were rolled back too.", "גם שינויי המערכת בוטלו."))
        return 1

    print(_color(_l(lang, "✓ Applied. To undo: dai-tune undo", "✓ בוצע. לביטול: dai-tune undo"), "32"))
    return 0


def cmd_undo(entry_id: str, ctx: Context) -> int:
    lang = ctx.lang
    journal = Journal.for_user(ctx)
    entry = journal.find(entry_id)
    if entry is None:
        print(_l(lang, "Nothing to undo.", "אין מה לבטל."))
        return 1
    if entry.get("system_entry"):
        result = run_helper(["undo", entry["system_entry"]])
        if not result.get("ok"):
            print(_color("✗ " + str(result.get("error")), "31"))
            return 1
    undo_entry(entry, ctx, journal)
    print(_color(_l(lang, "✓ Undone: ", "✓ בוטל: ") + "; ".join(entry.get("summary", [])), "32"))
    return 0


def cmd_history(ctx: Context) -> int:
    entries = Journal.for_user(ctx).entries()
    if not entries:
        print(_l(ctx.lang, "No changes yet.", "עדיין אין שינויים."))
    for entry in entries[-20:]:
        status = {"applied": "✓", "undone": "↶"}.get(entry.get("status"), "?")
        print(f"{status} {entry['id']}  {entry['time']}  " + "; ".join(entry.get("summary", [])))
    return 0


def cmd_status(ctx: Context) -> int:
    lang = ctx.lang
    score, checks = assess(ctx, lang)
    color = "32" if score >= 80 else ("33" if score >= 50 else "31")
    print(_color(_l(lang, f"Security score: {score}/100", f"ציון אבטחה: {score}/100"), "1;" + color))
    for check in checks:
        mark = _color("✓", "32") if check.ok else _color("✗", "31")
        detail = f" ({check.detail})" if check.detail else ""
        print(f"  {mark} {title(check, lang)}{detail}")
        if not check.ok and check.fix:
            print(f'      → dai-tune "{check.fix}"')
    return 0


def cmd_help(lang: str) -> int:
    print(_l(lang, "D.Ai Tune — configure the system by writing what you need.",
             "D.Ai Tune — מתאימים את המערכת פשוט ע\"י כתיבה."))
    print(_l(lang, "Examples:", "דוגמאות:"))
    for example in EXAMPLES[lang]:
        print(f'  dai-tune "{example}"')
    print()
    print("  dai-tune status   " + _l(lang, "security score and fixes", "ציון אבטחה והמלצות"))
    print("  dai-tune history  " + _l(lang, "what was changed", "מה שונה"))
    print("  dai-tune undo     " + _l(lang, "undo the last change", "ביטול השינוי האחרון"))
    print("  --dry-run --json --yes")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv[1:])
    lang = detect_lang()
    ctx = Context(lang=lang)
    flags = {a for a in args if a.startswith("--")}
    words = [a for a in args if not a.startswith("--")]
    if "--version" in flags:
        print(f"dai-tune {__version__}")
        return 0
    if not words or words[0] in ("help", "עזרה") or "--help" in flags:
        return cmd_help(lang)
    command = words[0]
    if command in ("status", "מצב"):
        return cmd_status(ctx)
    if command in ("history", "היסטוריה"):
        return cmd_history(ctx)
    if command in ("undo", "בטל"):
        return cmd_undo(words[1] if len(words) > 1 else "last", ctx)
    try:
        return cmd_apply(" ".join(words), ctx, "--dry-run" in flags, "--json" in flags, "--yes" in flags)
    except (EOFError, KeyboardInterrupt):
        print()
        return 1
