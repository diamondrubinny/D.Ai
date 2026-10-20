# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-tv: D.Ai inside the television (docs/TV.md stage 2b). Talks to the Kodi on this computer only.

  dai-tv ping                 is Kodi listening for D.Ai? (exit 0 yes, 1 no)
  dai-tv playing              what plays now (title, year, the plot's first lines)
  dai-tv say TEXT             show TEXT on the TV as a notification
  dai-tv ask QUESTION         ask Diamond (the local AI) about what plays, or anything; the answer goes on the TV
  dai-tv do ACTION            one of Kodi's actions: play, pause, stop, back, select, up, down, left, right, info
  dai-tv listen [--seconds 6] the remote's microphone: a spoken command ("pause", "השהה") is done, anything else
                              is asked of Diamond; the answer goes on the TV (D.Ai Voice transcribes on this computer)
  dai-tv night on|off         night mode now, in the running Kodi: dim after 5 minutes, the volume down
  dai-tv seed                 before Kodi starts: its add-on database with the channel add-ons enabled (no questions)
  dai-tv channels PLAYLIST.m3u [--epg URL] | --off   live channels from your own playlist (IPTV Simple)
  dai-tv browse URL | --close   Ruby in TV mode (Firefox, kiosk, big) on a web address; --close is "back to the TV"
  dai-tv --version | --help

Nothing here leaves the computer: Diamond runs locally and Kodi is reached on 127.0.0.1 only.
"""
from __future__ import annotations

import sys

from dai_i18n import pick, ui_lang

from . import rpc

ACTIONS = ("play", "pause", "stop", "back", "select", "up", "down", "left", "right", "info", "mute", "volumeup", "volumedown",
           "skipnext", "skipprevious", "fullscreen", "contextmenu")


# What a spoken word does on the remote (docs/TV.md §10): Hebrew and English, a fixed table, nothing else runs.
SPOKEN = {
    "pause": ("pause", "השהה", "השהייה", "עצור רגע", "הפסקה"),
    "play": ("play", "continue", "resume", "נגן", "המשך", "תמשיך", "תנגן"),
    "stop": ("stop", "עצור", "תעצור", "די"),
    "skipnext": ("next", "skip", "הבא", "דלג"),
    "skipprevious": ("previous", "back one", "הקודם", "אחורה"),
    "mute": ("mute", "quiet", "silence", "השתק", "שקט"),
    "volumeup": ("louder", "volume up", "חזק יותר", "הגבר", "תגביר"),
    "volumedown": ("quieter", "volume down", "lower", "חלש יותר", "הנמך", "תנמיך"),
    "back": ("go back", "back", "חזור", "תחזור"),
    "info": ("info", "what is this", "מידע", "מה זה"),
    "select": ("select", "ok", "okay", "בחר", "אישור"),
}
LISTEN_SECONDS = 6
NIGHT = {"on": {"screensaver.mode": "screensaver.xbmc.builtin.dim", "screensaver.time": 5},
         "off": {"screensaver.time": 10}}
NIGHT_VOLUME = {"on": 40, "off": 75}


def spoken_action(text: str) -> str | None:
    """The action a spoken sentence means, or None when it is a question for Diamond."""
    words = text.strip().strip(".!?,").casefold()
    if not words or len(words) > 40:
        return None
    for action, phrases in SPOKEN.items():
        if words in phrases:
            return action
    return None


def _voice_text(seconds: int, lang: str) -> str:
    """Record from the microphone for a few seconds and transcribe on this computer (D.Ai Voice)."""
    import time

    try:
        from dai_voice import engine
    except ImportError as exc:
        raise RuntimeError("D.Ai Voice is not installed on this TV") from exc
    engine.start()
    time.sleep(seconds)
    wav = engine.stop()
    return engine.transcribe(wav, lang=lang if lang in engine.LANGS else None, delete=True)  # i18n: ok (Whisper's language code)


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


def _answer(question: str, lang: str) -> str:
    """Diamond's answer about the question (with what plays now as context), shown on the TV too."""
    now = rpc.playing()
    if now:
        question = say(lang, "On the TV now: {what}. {q}", "בטלוויזיה עכשיו: {what}. {q}", what=describe(now, lang).replace("\n", " "), q=question)
    answer = _ask_diamond(question, lang)
    rpc.notify("Diamond", answer[:200], 10)
    return answer


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


def kodi_home() -> "Path":
    from pathlib import Path

    return Path.home() / ".kodi"


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
            print(_answer(question, lang))
            return 0
        if verb == "listen":
            try:
                seconds = max(2, min(15, int(rest[rest.index("--seconds") + 1]))) if "--seconds" in rest else LISTEN_SECONDS
            except (ValueError, IndexError):
                seconds = LISTEN_SECONDS
            rpc.notify("D.Ai", say(lang, "Listening… ({n} seconds)", "מקשיב… ({n} שניות)", n=seconds), seconds)
            try:
                text = _voice_text(seconds, lang).strip()
            except Exception as exc:  # noqa: BLE001 - no microphone, no Voice, no model: say so on the TV, never crash
                why = str(exc) or type(exc).__name__
                rpc.notify("D.Ai", say(lang, "Could not listen: {why}", "לא הצלחתי להקשיב: {why}", why=why)[:200], 6)
                print(say(lang, "Could not listen: {why}", "לא הצלחתי להקשיב: {why}", why=why), file=sys.stderr)
                return 1
            if not text:
                rpc.notify("D.Ai", say(lang, "I heard nothing.", "לא שמעתי כלום."), 4)
                print(say(lang, "I heard nothing.", "לא שמעתי כלום."))
                return 3
            action = spoken_action(text)
            if action:
                rpc.action(action)
                print(say(lang, "Heard: {text} → {action}", "שמעתי: {text} ← {action}", text=text, action=action))
                return 0
            print(say(lang, "Heard: {text}", "שמעתי: {text}", text=text))
            print(_answer(text, lang))
            return 0
        if verb == "seed":
            from . import seed

            changed = seed.seed(kodi_home())
            print(say(lang, "Add-ons ready: {ids}", "תוספים מוכנים: {ids}", ids=", ".join(changed) or say(lang, "nothing to change", "אין מה לשנות")))
            return 0
        if verb == "channels":
            from pathlib import Path

            from . import seed

            if rest[:1] == ["--off"]:
                gone = seed.channels_off(kodi_home())
                print(say(lang, "Live channels off.", "ערוצים חיים כבויים.") if gone else say(lang, "There was no playlist.", "לא הייתה רשימה."))
                return 0
            playlist = Path(rest[0]).expanduser() if rest and not rest[0].startswith("--") else None
            if playlist is None or playlist.suffix.lower() not in (".m3u", ".m3u8") or not playlist.is_file():
                print(say(lang, "Which playlist? dai-tv channels FILE.m3u (a file on this computer)",
                          "איזו רשימה? dai-tv channels FILE.m3u (קובץ במחשב הזה)"), file=sys.stderr)
                return 2
            epg = rest[rest.index("--epg") + 1] if "--epg" in rest and rest.index("--epg") + 1 < len(rest) else ""
            if epg and not epg.startswith(("http://", "https://")):
                print(say(lang, "The EPG is a web address (http:// or https://).", "לוח השידורים הוא כתובת אינטרנט (http:// או https://)."), file=sys.stderr)
                return 2
            seed.seed(kodi_home())
            seed.channels(kodi_home(), playlist.resolve(), epg=epg)
            print(say(lang, "Live channels from {file}; Kodi shows them when it starts again.",
                      "ערוצים חיים מתוך {file}; Kodi יציג אותם כשיופעל מחדש.", file=playlist.name))
            return 0
        if verb == "browse":
            from . import browse

            if rest[:1] == ["--close"]:
                print(say(lang, "Back to the TV.", "חזרה לטלוויזיה.") if browse.close() else say(lang, "The browser was not open.", "הדפדפן לא היה פתוח."))
                return 0
            url = rest[0] if rest else ""
            if not browse.allowed(url):
                print(say(lang, "A web address, please: dai-tv browse https://…", "כתובת אינטרנט, בבקשה: dai-tv browse https://…"), file=sys.stderr)
                return 2
            pid = browse.open_url(url)
            print(say(lang, "Ruby opens {url} on the TV (pid {pid}).", "Ruby פותח את {url} בטלוויזיה (pid {pid}).", url=url, pid=pid))
            return 0
        if verb == "night":
            mode = rest[0].lower() if rest else ""
            if mode not in NIGHT:
                print(say(lang, "dai-tv night on|off", "dai-tv night on|off"), file=sys.stderr)
                return 2
            for setting, value in NIGHT[mode].items():
                rpc.call("Settings.SetSettingValue", {"setting": setting, "value": value})
            rpc.call("Application.SetVolume", {"volume": NIGHT_VOLUME[mode]})
            rpc.notify("D.Ai", say(lang, "Night mode on: dim after 5 minutes, the volume down.", "מצב לילה פועל: עמעום אחרי 5 דקות, עוצמה נמוכה.")
                       if mode == "on" else say(lang, "Night mode off.", "מצב לילה כבוי."), 5)
            print(say(lang, "Night mode: {mode}", "מצב לילה: {mode}", mode=mode))
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

