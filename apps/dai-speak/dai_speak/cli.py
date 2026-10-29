# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-speak: Diamond reads aloud, on this computer (docs/SPEAK.md).

  dai-speak                      read the selected text; if already reading, stop (Super+Shift+S)
  dai-speak --text "..."         read this text
  dai-speak --stdin              read the standard input
  dai-speak --stop               stop reading
  dai-speak --lang he            the voice's language (otherwise: the text's letters, then your language)
  dai-speak --rate 200           words per minute (80-400; the setting comes from "read faster" in D.Ai Tune)
  dai-speak --wav FILE           write a sound file instead of playing
  dai-speak --show               print the reader's command line (is it inside the sandbox?) and exit
  dai-speak --version

Nothing leaves the computer and nothing is saved. The voice is espeak-ng, the same one Orca uses, run inside
bubblewrap (no network, no home) with the sound piped to pw-play.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from dai_i18n import ui_lang

from . import __author__, __version__
from .engine import SpeakError, clamp_rate, load_settings, notify, pid_file, reader_argv, running_reader, selection, start, stop

FLAGS = ("--text", "--stdin", "--stop", "--lang", "--rate", "--wav", "--quiet", "--show")


def _option(args: list[str], name: str) -> str | None:
    if name in args:
        at = args.index(name)
        return args[at + 1] if at + 1 < len(args) else None
    return None


def main(argv: list[str] | None = None, run=subprocess.run, popen=subprocess.Popen, home: Path | None = None,
         pid_path: Path | None = None, stdin=None) -> int:
    args = list(sys.argv if argv is None else argv)[1:]
    if args and args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if "--version" in args:
        print(f"dai-speak {__version__} — {__author__}")
        return 0
    if any(a.startswith("-") and a not in FLAGS for a in args):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    lang = _option(args, "--lang") or ui_lang()
    path = pid_file() if pid_path is None else pid_path
    if "--stop" in args:
        stop(path)
        return 0
    rate = clamp_rate(_option(args, "--rate") or load_settings(home).rate)
    if "--show" in args:
        print(" ".join(reader_argv(lang, rate)))
        return 0
    wav = Path(given) if (given := _option(args, "--wav")) else None
    from_shortcut = False
    if (text := _option(args, "--text")) is not None:
        pass
    elif "--stdin" in args:
        text = (stdin or sys.stdin).read()
    else:
        from_shortcut = True
        if running_reader(path) is not None:     # the second press stops
            stop(path)
            return 0
        text = selection(run)
    try:
        start(text, lang, rate, wav, path, popen)
    except SpeakError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    if from_shortcut and "--quiet" not in args:
        notify(lang, popen)
    return 0
