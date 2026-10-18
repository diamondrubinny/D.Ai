# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-j: J, the mail client (docs/MAIL.md).

  dai-j                      open J
  dai-j mailto:ADDRESS?...   write to someone (J is the handler for mailto: links)
  dai-j discover ADDRESS     which servers J would use for an address, as JSON (nothing is signed in)
  dai-j --version
"""

from __future__ import annotations

import json
import sys

from . import __author__, __version__


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv[1:])
    if "--version" in args:
        print(f"dai-j {__version__} — {__author__}")
        return 0
    if "-h" in args or "--help" in args:
        print(__doc__.strip())
        return 0
    if args and args[0] == "discover":
        from .discover import discover

        if len(args) != 2:
            print(__doc__.strip(), file=sys.stderr)
            return 2
        settings = discover(args[1])
        if settings is None:
            print("not an e-mail address", file=sys.stderr)
            return 1
        print(json.dumps(settings.to_dict(), indent=2))
        return 0
    if len(args) > 1 or args and not args[0].startswith("mailto:"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    from .gui import main as gui_main

    return gui_main(args[0] if args else "")
