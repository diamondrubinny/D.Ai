# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-tv: D.Ai inside the television (docs/TV.md stage 2b). Talks to the Kodi on this computer only.

  dai-tv ping                 is Kodi listening for D.Ai? (exit 0 yes, 1 no)
  dai-tv playing              what plays now (title, year, the plot's first lines)
  dai-tv say TEXT             show TEXT on the TV as a notification
  dai-tv ask QUESTION         ask Diamond (the local AI) about what plays, or anything; the answer goes on the TV
  dai-tv do ACTION            one of Kodi's actions: play, pause, stop, back, select, up, down, left, right, info
  dai-tv --version | --help

Nothing here leaves the computer: Diamond runs locally and Kodi is reached on 127.0.0.1 only.
"""
from __future__ import annotations

import sys

from dai_i18n import pick, ui_lang

from . import rpc

ACTIONS = ("play", "pause", "stop", "back", "select", "up", "down", "left", "right", "info", "mute", "volumeup", "volumedown",
           "skipnext", "skipprevious", "fullscreen", "contextmenu")


def say(lang: str, en: str, he: str, **kwargs: object) -> str:
    return pick(lang, en, he).format(**kwargs)


def _ask_diamond(question: str, lang: str) -> str:
    """Diamond's answer, short, or a sentence that says it is not here (the TV never sends anything out)."""
    try:
        from dai_ai import client
    except ImportError:
        return say(lang, "Diamond is not installed on this TV.", "Diamond לא מותקן בטלוויזיה הזאת.")
    try:
        return "".join(client.ask(question, max_tokens=120)).strip() or say(lang, "Diamond had no answer.", "ל-Diamond לא הייתה תשובה.")
    except Exception as exc:  # noqa: BLE001 - daid is not running, or no model: say so, never crash the TV
        return say(lang, "Diamond is not available now ({why}).", "Diamond לא זמין עכשיו ({why}).", why=type(exc).__name__)


def describe(now: dict | None, lang: str) -> str:
    if not now:
        return say(lang, "Nothing is playing.", "שום דבר לא מתנגן.")
    title = now["title"] + (f" ({now['year']})" if now.get("year") else "")
    if now.get("show"):
        title = f"{now['show']} · {title}"
    if now.get("artist"):
        title = f"{now['artist']} · {title}"
    plot = now.get("plot", "")
    return title + (f"\n{plot[:300]}" if plot else "")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)[1:]
    lang = ui_lang()
    if not args or "--help" in args or "-h" in args:
        print(__doc__.strip())
        return 0
    if "--version" in args:
        from . import __author__, __version__
        print(f"dai-tv {__version__} — {__author__}")
        return 0
    verb, rest = args[0], args[1:]
    try:
        if verb == "ping":
            ok = rpc.ping()
            print("pong" if ok else say(lang, "Kodi did not answer.", "Kodi לא ענה."))
            return 0 if ok else 1
        if verb == "playing":
            print(describe(rpc.playing(), lang))
            return 0
        if verb == "say":
            text = " ".join(rest).strip()
            if not text:
                print(say(lang, "What to say? dai-tv say TEXT", "מה להגיד? dai-tv say TEXT"), file=sys.stderr)
                return 2
            rpc.notify("D.Ai", text)
            print(say(lang, "Shown on the TV.", "מוצג על הטלוויזיה."))
            return 0
        if verb == "ask":
            question = " ".join(rest).strip()
            if not question:
                print(say(lang, "Ask what? dai-tv ask QUESTION", "לשאול מה? dai-tv ask QUESTION"), file=sys.stderr)
                return 2
            now = rpc.playing()
            if now:
                question = say(lang, "On the TV now: {what}. {q}", "בטלוויזיה עכשיו: {what}. {q}", what=describe(now, lang).replace("\n", " "), q=question)
            answer = _ask_diamond(question, lang)
            print(answer)
            rpc.notify("Diamond", answer[:200], 10)
            return 0
        if verb == "do":
            name = rest[0].lower() if rest else ""
            if name not in ACTIONS:
                print(say(lang, "Actions: {list}", "פעולות: {list}", list=", ".join(ACTIONS)), file=sys.stderr)
                return 2
            rpc.action(name)
            print(say(lang, "Done: {name}", "בוצע: {name}", name=name))
            return 0
    except rpc.KodiError as exc:
        print(say(lang, "Kodi could not be reached: {why}", "לא ניתן להגיע ל-Kodi: {why}", why=exc), file=sys.stderr)
        return 1
    print(say(lang, "Unknown command: {verb}. dai-tv --help", "פקודה לא מוכרת: {verb}. dai-tv --help", verb=verb), file=sys.stderr)
    return 2

