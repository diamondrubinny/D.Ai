# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Starts a Forge app inside its sandbox under its own name (docs/TASKBAR.md §12).

  python3 -I sandbox_start.py dai-app-<name> /app/<entry>

The Wayland app_id becomes "dai-app-<name>", the name of the app's .desktop
file, so the taskbar shows the app with its 🛡 icon (built in a sandbox).
Runs inside bubblewrap, with /usr read-only: nothing here can change the sandbox.
"""

from __future__ import annotations

import re
import runpy
import sys


def main(argv: list[str]) -> int:
    if len(argv) != 3 or not re.fullmatch(r"dai-app-[a-z0-9][a-z0-9-]{0,39}", argv[1]) \
            or not re.fullmatch(r"/app/[A-Za-z0-9_.-]{1,64}\.py", argv[2]) or ".." in argv[2]:
        print("usage: sandbox_start.py dai-app-<name> /app/<entry>.py", file=sys.stderr)
        return 2
    try:
        from PyQt6.QtGui import QGuiApplication

        QGuiApplication.setDesktopFileName(argv[1])  # static: holds for the QApplication the app creates
    except ImportError:
        pass
    sys.argv = [argv[2]]
    runpy.run_path(argv[2], run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
