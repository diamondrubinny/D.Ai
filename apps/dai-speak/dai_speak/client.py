# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Reading aloud from other D.Ai windows (docs/SPEAK.md §8): a detached dai-speak, the text through its
standard input (never on a command line), and the same stop as the shortcut."""
from __future__ import annotations

import shutil
import subprocess
import sys


def available() -> bool:
    return shutil.which("dai-speak") is not None


def read(text: str, lang: str, popen=subprocess.Popen) -> bool:
    """Start reading `text`; True when dai-speak was started."""
    words = text.strip()
    if not words:
        return False
    try:
        child = popen(["dai-speak", "--stdin", "--lang", lang], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        print(f"dai-speak: cannot start: {exc}", file=sys.stderr)
        return False
    try:
        assert child.stdin is not None
        child.stdin.write(words.encode("utf-8"))
        child.stdin.close()
    except OSError:
        pass
    return True


def stop(popen=subprocess.Popen) -> None:
    try:
        popen(["dai-speak", "--stop"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
              start_new_session=True)
    except OSError:
        pass
