# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-captions: live captions for whatever the computer plays (docs/BEYOND.md §13).

  dai-captions                      the captions bar, from the speakers
  dai-captions --from-file X.wav    the bar, fed from a file (no sound hardware needed)
  dai-captions --print [--from-file X.wav] [--lang he]   lines to standard output instead of a window
  dai-captions --version

Everything runs on this computer: PipeWire records the output in five-second chunks, whisper.cpp reads each
one inside D.Ai Voice's sandbox (no network, no home), the chunk is deleted, the text is never saved.
"""
from __future__ import annotations

import sys
from pathlib import Path

from dai_i18n import pick, ui_lang

from . import __author__, __version__
from .engine import Captions, VoiceError, file_chunks, live_chunks, run_pipeline, transcribe_chunk


def _option(args: list[str], name: str) -> str | None:
    if name in args:
        at = args.index(name)
        return args[at + 1] if at + 1 < len(args) else None
    return None


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)[1:]
    lang = ui_lang()
    if args and args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if "--version" in args:
        print(f"dai-captions {__version__} — {__author__}")
        return 0
    source = _option(args, "--from-file")
    speech_lang = _option(args, "--lang")
    if "--from-file" in args and not source:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    if "--print" in args:
        try:
            chunks = file_chunks(Path(source)) if source else live_chunks(lambda: False)
            captions = run_pipeline(chunks, lambda p: transcribe_chunk(p, speech_lang), emit=lambda text: None,
                                    captions=Captions(max_lines=1000))
        except (VoiceError, OSError, EOFError) as exc:
            print(pick(lang, "Captions failed: {error}", "הכתוביות נכשלו: {error}").format(error=exc), file=sys.stderr)
            return 1
        print(captions.text or pick(lang, "(no speech)", "(אין דיבור)"))
        return 0 if captions.lines else 1
    unknown = [a for a in args if a.startswith("-") and a not in ("--from-file", "--lang", "--print")]
    if unknown:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    from .gui import main as window
    return window(["dai-captions", *args])
