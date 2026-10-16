"""dai-fixlayout: fix text typed in the wrong keyboard layout, in any app.

Select the text, press Pause (or Super+Alt+L): the selection is converted
(akuo -> שלום, יקךךם -> hello) and pasted over itself. Only the selection is
read, only when the key is pressed, and nothing is stored.

Uses wl-clipboard (wl-paste/wl-copy) and wtype on Wayland.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

from .core import convert_layout, ui_language

MAX_CHARS = 4000


def _run(argv: list[str], data: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, input=data, capture_output=True, text=True, timeout=5, check=False)


def _notify(summary: str, body: str = "") -> None:
    if shutil.which("notify-send"):
        _run(["notify-send", "-a", "D.Ai", "-i", "dai-logo", "-t", "2500", summary, body])


def read_selection() -> str:
    result = _run(["wl-paste", "--primary", "--no-newline"])
    return result.stdout if result.returncode == 0 else ""


def main(argv: list[str]) -> int:
    he = ui_language() == "he"
    text = read_selection()
    if not text.strip():
        _notify("D.Ai", "סמנו טקסט ואז לחצו Pause" if he else "Select text, then press Pause")
        return 1
    if len(text) > MAX_CHARS:
        _notify("D.Ai", "הבחירה ארוכה מדי" if he else "Selection is too long")
        return 1
    fixed = convert_layout(text)
    if fixed is None:
        _notify("D.Ai", "אין מה לתקן" if he else "Nothing to fix")
        return 1
    if "--print" in argv:  # for scripts and tests: no clipboard, no typing
        print(fixed)
        return 0
    _run(["wl-copy"], fixed)
    # Replace the still-selected text by pasting over it.
    _run(["wtype", "-M", "ctrl", "v", "-m", "ctrl"])
    _notify("תוקן: " + fixed if he else "Fixed: " + fixed)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
