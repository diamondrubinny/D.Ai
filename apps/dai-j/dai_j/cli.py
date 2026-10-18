# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-j: J, the mail client (docs/MAIL.md).

  dai-j                      open J
  dai-j mailto:ADDRESS?...   write to someone (J is the handler for mailto: links)
  dai-j discover ADDRESS     which servers J would use for an address, as JSON (nothing is signed in)
  dai-j import [--add]       accounts found in Thunderbird, Betterbird, Evolution, Claws Mail and Mutt
                             (read-only; --add adds them to J; passwords are asked at the first sign-in)
  dai-j import-mail [PATH]    copy the mail Thunderbird, Betterbird, Evolution or KMail keep on this computer (or one
                             mbox file / Maildir folder / Outlook .pst file) into J's local folders; the other app's
                             files are only read
  dai-j --version
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

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
    if args and args[0] == "import":
        from dataclasses import asdict

        from . import accounts as acc
        from .importers import find_all

        found = find_all()
        if "--add" in args:
            current = acc.load()
            known = {a.id for a in current}
            new = [acc.Account(f.address, f.name, f.incoming, f.outgoing) for f in found
                   if f.usable and f.address.lower() not in known]
            acc.save(current + new)
            print(json.dumps({"added": [a.address for a in new]}, indent=2))
            return 0
        print(json.dumps([{**asdict(f), "usable": f.usable} for f in found], indent=2, ensure_ascii=False))
        return 0
    if args and args[0] == "import-mail":
        from . import accounts as acc, localmail
        from .store import Store

        if len(args) == 2 and localmail.is_pst(Path(args[1]).expanduser()):  # Outlook (docs/MAIL.md §11)
            directory = acc.data_dir()
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            store = Store(directory / "mail.sqlite")
            try:
                results = localmail.import_pst(store, Path(args[1]).expanduser())
            except localmail.PstError as exc:
                print({"no_readpst": "readpst is not installed (sudo apt install pst-utils)",
                       "pst_failed": f"could not read the Outlook file: {args[1]}"}[str(exc)], file=sys.stderr)
                return 1
            finally:
                store.close()
            print(json.dumps([{"folder": r.folders[0], "from": "outlook", "added": r.added, "skipped": r.skipped}
                              for r in results], indent=2, ensure_ascii=False))
            return 0
        if len(args) == 2:
            source = localmail.source_for_path(Path(args[1]))
            if source is None:
                print(f"not an mbox file, a Maildir folder or an Outlook .pst file: {args[1]}", file=sys.stderr)
                return 1
            sources = [source]
        else:
            sources = localmail.find_sources()
        directory = acc.data_dir()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        store = Store(directory / "mail.sqlite")
        report = []
        for source in sources:
            result = localmail.import_source(store, source)
            report.append({"folder": source.name, "from": source.app, "added": result.added, "skipped": result.skipped})
        store.close()
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    if len(args) > 1 or args and not args[0].startswith("mailto:"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    from .gui import main as gui_main

    return gui_main(args[0] if args else "")
