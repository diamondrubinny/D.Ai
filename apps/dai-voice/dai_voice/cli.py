# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-voice: push-to-talk dictation and voice commands, transcribed locally.

  dai-voice toggle [--to type|command|copy|print] [--lang he|en|auto]
  dai-voice start | stop [--to ...] | cancel | status
  dai-voice transcribe FILE.wav [--lang ...]
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from dai_ai.paths import runtime_dir

from dai_i18n import pick, ui_lang

from . import __author__, __version__
from .engine import LANGS, VoiceError, cancel, recording, start, stop, transcribe

TARGETS = ("type", "command", "copy", "print")
TEXT = {
    "recording": ("🎙 Recording… press again to finish", "🎙 מקליט… לחצו שוב לסיום"),
    "transcribing": ("Transcribing on this computer…", "מתמלל במחשב הזה…"),
    "nothing": ("No speech was recognized", "לא זוהה דיבור"),
}


def _lang_ui() -> str:
    return ui_lang()


def _t(key: str) -> str:
    return pick(_lang_ui(), *TEXT[key])


def notify(body: str, persistent: bool = False) -> None:
    """One notification that is replaced as the state changes (never silent while recording)."""
    id_file = runtime_dir() / "voice-notify-id"
    try:
        previous = id_file.read_text().strip()
    except OSError:
        previous = ""
    argv = ["notify-send", "-a", "D.Ai Voice", "-i", "audio-input-microphone", "-p",
            "-t", "0" if persistent else "4000"]
    if previous.isdigit():
        argv += ["-r", previous]
    try:
        result = subprocess.run([*argv, "D.Ai Voice", body], capture_output=True, text=True, timeout=5, check=False)
        if result.stdout.strip().isdigit():
            id_file.write_text(result.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass


def deliver(text: str, target: str) -> int:
    if not text:
        notify(_t("nothing"))
        return 3
    if target == "print":
        print(text)
        return 0
    if target == "copy":
        subprocess.run(["wl-copy", "--", text], check=False)
    elif target == "command":
        subprocess.Popen(["dai-command", "--query", text], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:  # type into the focused window (Wayland virtual keyboard)
        time.sleep(0.3)  # let the shortcut's modifier keys be released
        subprocess.run(["wtype", "--", text], check=False)
    notify("✓ " + (text if len(text) <= 120 else text[:117] + "…"))
    return 0


def _option(args: list[str], name: str, choices: tuple[str, ...], default: str) -> str:
    if name in args and args.index(name) + 1 < len(args):
        value = args[args.index(name) + 1]
        if value not in choices:
            raise VoiceError(f"{name} must be one of: {', '.join(choices)}")
        return value
    return default


def finish(target: str, lang: str | None) -> int:
    wav = stop()
    if target != "print":
        notify(_t("transcribing"), persistent=True)
    text = transcribe(wav, lang=lang, delete=True)
    return deliver(text, target)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv[1:])
    if "--version" in args:
        print(f"dai-voice {__version__} — {__author__}")
        return 0
    command = args[0] if args else "help"
    try:
        target = _option(args, "--to", TARGETS, "type")
        lang = _option(args, "--lang", LANGS, "") or None
        if command == "toggle":
            state = recording()
            if state is None:
                start()
                notify(_t("recording"), persistent=True)
                return 0
            return finish(target, lang)
        if command == "start":
            start()
            notify(_t("recording"), persistent=True)
            return 0
        if command == "stop":
            return finish(target if "--to" in args else "print", lang)
        if command == "cancel":
            cancel()
            notify("✗")
            return 0
        if command == "status":
            state = recording()
            print("recording" if state and not state.get("finished") else "idle")
            return 0
        if command == "transcribe" and len(args) >= 2:
            print(transcribe(Path(args[1]), lang=lang))
            return 0
    except VoiceError as exc:
        if command in ("toggle", "stop"):
            notify("✗ " + str(exc))
        print(f"dai-voice: {exc}", file=sys.stderr)
        return 1
    print(__doc__.strip().split("\n\n", 1)[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
