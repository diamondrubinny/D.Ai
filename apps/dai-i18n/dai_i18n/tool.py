# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Translation upkeep for D.Ai OS (docs/I18N.md).

  python3 -m dai_i18n.tool extract [--check]   apps/*/dai_* -> i18n/dai-os.pot (--check: fail if stale)
  python3 -m dai_i18n.tool check               every i18n/po/<lang>.po is usable
  python3 -m dai_i18n.tool compile OUT         i18n/po/<lang>.po -> OUT/<lang>/LC_MESSAGES/dai-os.mo
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import DOMAIN, SUPPORTED
from .catalog import extract, parse_po, problems, render_pot, write_mo

REPO = Path(__file__).resolve().parents[3]
I18N = REPO / "i18n"


def app_roots(repo: Path = REPO) -> list[Path]:
    return sorted(p for p in (repo / "apps").glob("*/dai_*") if p.is_dir() and p.name != "dai_i18n")


def po_files(directory: Path = I18N / "po") -> dict[str, Path]:
    return {p.stem: p for p in sorted(directory.glob("*.po"))}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv[1:])
    command = args[0] if args else ""
    if command == "extract":
        pot = render_pot(extract(app_roots(), REPO)) + "\n"
        target = I18N / f"{DOMAIN}.pot"
        if "--check" in args:
            if not target.exists() or target.read_text(encoding="utf-8") != pot:
                print(f"{target.relative_to(REPO)} is out of date: run python3 -m dai_i18n.tool extract", file=sys.stderr)
                return 1
            print(f"{target.relative_to(REPO)} is up to date ({pot.count(chr(10) + 'msgid ') - 1} texts)")
            return 0
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(pot, encoding="utf-8")
        print(f"wrote {target.relative_to(REPO)}")
        return 0
    if command == "check":
        known = {e.msgid for e in extract(app_roots(), REPO)}
        failed = 0
        for lang, path in po_files().items():
            if lang not in SUPPORTED or lang in ("en", "he"):
                print(f"{path.name}: not a supported language (Hebrew lives in the code)", file=sys.stderr)
                failed += 1
                continue
            messages = parse_po(path.read_text(encoding="utf-8"))
            found = problems(messages, known)
            for problem in found:
                print(f"{path.name}: {problem}", file=sys.stderr)
            failed += bool(found)
            print(f"{path.name}: {len(messages)}/{len(known)} translated")
        return 1 if failed else 0
    if command == "compile" and len(args) == 2:
        out = Path(args[1])
        known = {e.msgid for e in extract(app_roots(), REPO)}
        for lang, path in po_files().items():
            messages = {k: v for k, v in parse_po(path.read_text(encoding="utf-8")).items()
                        if k in known and not problems({k: v}, known)}
            target = out / lang / "LC_MESSAGES" / f"{DOMAIN}.mo"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(write_mo(messages, lang))
            print(f"{lang}: {len(messages)} texts")
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
