# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-evolve: notice what is missing and offer to build it (docs/EVOLVE.md §3).

  dai-evolve                     what D.Ai suggests now (same as: suggest)
  dai-evolve suggest [--json]    the suggestions from the last scan
  dai-evolve scan [--notify]     look at the local signals again (daily, by a user timer)
  dai-evolve open KEY            do what a suggestion offers (opens Forge, Tune or Heal for review)
  dai-evolve dismiss KEY         never suggest this again
  dai-evolve wishes              what you asked for and did not find (last 30 days)
  dai-evolve off | on            stop noticing (and delete what was kept) | start again

Nothing leaves the computer, nothing is installed or changed without your
review in D.Ai Forge, D.Ai Tune or D.Ai Heal, and no AI reads your signals.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from dataclasses import asdict

from dai_i18n import pick, ui_lang

from . import __author__, __version__, scan, store

NOTIFY_EVERY = 20 * 3600  # at most one notification a day
STRINGS = {
    "none": ("Nothing to suggest right now.", "אין הצעות כרגע."),
    "off": ("D.Ai Evolve is off: nothing is noticed or kept. Turn on again: dai-evolve on",
            "D.Ai Evolve כבוי: שום דבר לא נרשם או נשמר. להפעלה מחדש: dai-evolve on"),
    "turned_off": ("Off. What was kept has been deleted.", "כבוי. מה שנשמר נמחק."),
    "turned_on": ("On. Suggestions appear in D.Ai Command (Super+Space).", "פועל. הצעות יופיעו ב־D.Ai Command (Super+Space)."),
    "dismissed": ("It will not be suggested again.", "זה לא יוצע שוב."),
    "unknown": ("No such suggestion (run: dai-evolve suggest).", "אין הצעה כזו (הריצו: dai-evolve suggest)."),
    "no_wishes": ("No requests without a result in the last 30 days.", "אין בקשות שלא נמצאו להן תוצאות ב־30 הימים האחרונים."),
    "notify_title": ("D.Ai has an idea for you", "ל־D.Ai יש רעיון בשבילך"),
    "notify_action": ("Show me", "תראה לי"),
    "notify_more": ("and {n} more in D.Ai Command (Super+Space)", "ועוד {n} ב־D.Ai Command (Super+Space)"),
}


def lang() -> str:
    return ui_lang()


def t(key: str, language: str, **kwargs: object) -> str:
    return pick(language, *STRINGS[key]).format(**kwargs)


def open_argv(suggestion: scan.Suggestion) -> list[str]:
    """Where a suggestion is reviewed. Every path asks again before it changes anything."""
    if suggestion.action == "forge":
        return ["dai-forge-gui", suggestion.payload]
    if suggestion.action == "tune":
        return ["x-terminal-emulator", "-e", "bash", "-c", 'dai-tune "$1"; echo; read -r -p "Enter ↵" _', "dai-tune",
                suggestion.payload]
    return ["dai-heal"]


def open_suggestion(suggestion: scan.Suggestion, spawn=None) -> None:
    spawn = spawn or (lambda argv: subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL,
                                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    scan.done(suggestion)
    spawn(open_argv(suggestion))


def _print(found: list[scan.Suggestion], language: str) -> None:
    for suggestion in found:
        print(f"✦ {suggestion.title(language)}  [{suggestion.key}]")
        print(f"    {suggestion.why(language)}")
    if not found:
        print(t("none", language))


def notify_new(found: list[scan.Suggestion], language: str, clock=time.time, send=None) -> scan.Suggestion | None:
    """One notification a day at most, only for suggestions not shown before. Returns what was announced."""
    notified = store.read_json("notified.json", {}) or {}
    notified = notified if isinstance(notified, dict) else {}
    keys = set(notified.get("keys", []))
    fresh = [s for s in found if s.key not in keys]
    if not fresh or clock() - float(notified.get("last", 0)) < NOTIFY_EVERY:
        return None
    store.write_json("notified.json", {"last": clock(), "keys": sorted(keys | {s.key for s in fresh})[-300:]})
    first = fresh[0]
    body = first.why(language)
    if len(fresh) > 1:
        body += "\n" + t("notify_more", language, n=len(fresh) - 1)
    (send or _send)(first, first.title(language), body, language)
    return first


def _send(suggestion: scan.Suggestion, title: str, body: str, language: str) -> None:
    if not shutil.which("notify-send"):
        return
    base = ["notify-send", "-a", "D.Ai", "-i", "dialog-information"]
    try:
        result = subprocess.run([*base, "--wait", "-A", f"open={t('notify_action', language)}", title, body],
                                capture_output=True, text=True, timeout=3600, check=False)
    except (OSError, subprocess.SubprocessError):
        return
    if result.returncode != 0:  # notify-send without actions
        subprocess.run([*base, title, body], capture_output=True, check=False)
    elif result.stdout.strip() == "open":
        open_suggestion(suggestion)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv[1:])
    if "--version" in args:
        print(f"dai-evolve {__version__} — {__author__}")
        return 0
    if "-h" in args or "--help" in args:
        print(__doc__.strip())
        return 0
    language = lang()
    command = args[0] if args else "suggest"
    if command == "off":
        store.forget_all()
        marker = store.off_marker()
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
        print(t("turned_off", language))
        return 0
    if command == "on":
        store.off_marker().unlink(missing_ok=True)
        print(t("turned_on", language))
        return 0
    if store.is_off():
        print(t("off", language))
        return 0
    if command == "scan":
        found = scan.scan()
        if "--notify" in args:
            notify_new(found, language)
        else:
            _print(found, language)
        return 0
    if command == "suggest":
        found = scan.saved()
        if "--json" in args:
            print(json.dumps([asdict(s) for s in found], ensure_ascii=False, indent=2))
        else:
            _print(found, language)
        return 0
    if command in ("open", "dismiss") and len(args) == 2:
        suggestion = next((s for s in scan.saved() if s.key == args[1]), None)
        if suggestion is None:
            print(t("unknown", language), file=sys.stderr)
            return 1
        if command == "dismiss":
            scan.dismiss(suggestion.key)
            print(t("dismissed", language))
        else:
            open_suggestion(suggestion)
        return 0
    if command == "wishes":
        wishes = store.wishes_list()
        for wish in wishes:
            stamp = time.strftime("%Y-%m-%d", time.localtime(float(wish.get("time", 0))))
            print(f"{stamp}  {wish['text']}" + (f"  ({wish['reason']})" if wish.get("reason") else ""))
        if not wishes:
            print(t("no_wishes", language))
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2
