# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-pdf: D.Ai PDF, a reader that opens every PDF in a sandbox (docs/PDF.md).

  dai-pdf [FILE]                 open the window (with FILE, if given)
  dai-pdf info FILE              pages, metadata, and what the file wants to do
  dai-pdf text FILE [--page N] [--raw]   the text (Hebrew made readable unless --raw); all pages without --page
  dai-pdf check FILE             exit 0: nothing active in the file; 1: scripts, launches, submits, attachments
                                 or an XFA form were found (listed); 2: the file could not be opened
  dai-pdf --version | --help

Everything runs on this computer, inside bubblewrap. Nothing in the file is executed, followed or opened.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dai_i18n import pick, ui_lang

from .reader import PdfError, Reader


def say(lang: str, en: str, he: str, **kwargs: object) -> str:
    return pick(lang, en, he).format(**kwargs)


def _reader(path: str, password: str = "") -> Reader:
    # DAI_PDF_DIRECT=1 skips the sandbox: for the test suite on machines without user namespaces, never the window.
    direct = os.environ.get("DAI_PDF_DIRECT") == "1"
    python = os.environ.get("DAI_PDF_PYTHON") or sys.executable
    return Reader(path, password=password, sandboxed=not direct, python=python)


def _option(args: list[str], name: str) -> str | None:
    if name in args and args.index(name) + 1 < len(args):
        return args[args.index(name) + 1]
    return None


def _open(args: list[str], lang: str) -> tuple[Reader, object] | None:
    paths, skip = [], False
    for arg in args[1:]:
        if skip:
            skip = False
        elif arg in ("--page", "--password"):
            skip = True
        elif not arg.startswith("--"):
            paths.append(arg)
    if not paths:
        print(say(lang, "Which file? dai-pdf {command} FILE", "איזה קובץ? dai-pdf {command} FILE", command=args[0]), file=sys.stderr)
        return None
    path = paths[0]
    reader = _reader(path, _option(args, "--password") or "")
    try:
        doc = reader.open()
    except PdfError as exc:
        reader.close()
        if exc.kind == "password":
            print(say(lang, "{name} is locked: add --password", "{name} נעול: הוסיפו --password", name=Path(path).name),
                  file=sys.stderr)
        elif exc.kind == "missing":
            print(say(lang, "There is no file called {name}.", "אין קובץ בשם {name}.", name=path), file=sys.stderr)
        elif exc.kind == "sandbox":
            print(say(lang, "The sandbox (bubblewrap) is missing; nothing was opened.",
                      "ארגז החול (bubblewrap) חסר; שום דבר לא נפתח."), file=sys.stderr)
        else:
            print(say(lang, "{name} is not a PDF that can be opened.", "{name} אינו קובץ PDF שניתן לפתוח.",
                      name=Path(path).name), file=sys.stderr)
        return None
    return reader, doc


def info(args: list[str], lang: str) -> int:
    from .gui import findings_sentences  # the same sentences as the window's file bar

    opened = _open(args, lang)
    if opened is None:
        return 2
    reader, doc = opened
    try:
        print(say(lang, "File: {name}", "קובץ: {name}", name=doc.path))
        print(say(lang, "Pages: {n}", "עמודים: {n}", n=doc.count))
        for key, en, he in (("title", "Title", "כותרת"), ("author", "Author", "מחבר"), ("subject", "Subject", "נושא"),
                            ("creator", "Created with", "נוצר באמצעות"), ("producer", "Producer", "מפיק"),
                            ("created", "Created", "נוצר"), ("modified", "Modified", "שונה")):
            if doc.metadata.get(key):
                print(f"{say(lang, en, he)}: {doc.metadata[key]}")
        for line in findings_sentences(doc, lang):
            print("! " + line)
        if doc.findings.links:
            print(say(lang, "Links to addresses: {n} (opened only when you click and confirm)",
                      "קישורים לכתובות: {n} (נפתחים רק אחרי לחיצה ואישור)", n=doc.findings.links))
        for att in doc.findings.attachments:
            print(f"  - {att.get('name')} ({att.get('size')} B)")
        return 0
    finally:
        reader.close()


def text(args: list[str], lang: str) -> int:
    opened = _open(args, lang)
    if opened is None:
        return 2
    reader, doc = opened
    try:
        raw = "--raw" in args
        page = _option(args, "--page")
        pages = range(doc.count)
        if page is not None:
            try:
                index = int(page) - 1
            except ValueError:
                index = -1
            if not 0 <= index < doc.count:
                print(say(lang, "No page {page}: the file has {n}.", "אין עמוד {page}: בקובץ יש {n}.", page=page, n=doc.count),
                      file=sys.stderr)
                return 2
            pages = range(index, index + 1)
        for index in pages:
            try:
                print(reader.text(index, as_extracted=raw))
            except PdfError:
                print(say(lang, "[page {n} could not be read]", "[לא ניתן היה לקרוא את עמוד {n}]", n=index + 1))
            if len(pages) > 1:
                print("\f", end="")
        return 0
    finally:
        reader.close()


def check(args: list[str], lang: str) -> int:
    from .gui import findings_sentences

    opened = _open(args, lang)
    if opened is None:
        return 2
    reader, doc = opened
    try:
        lines = findings_sentences(doc, lang)
        for line in lines:
            print(line)
        if doc.findings.active():
            return 1
        print(say(lang, "Nothing in this file acts on its own.", "שום דבר בקובץ הזה לא פועל מעצמו."))
        return 0
    finally:
        reader.close()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)[1:]
    lang = ui_lang()
    if "--help" in args or "-h" in args:
        print(__doc__.strip())
        return 0
    if "--version" in args:
        from . import __author__, __version__
        print(f"dai-pdf {__version__} — {__author__}")
        return 0
    if args and args[0] in ("info", "text", "check"):
        return {"info": info, "text": text, "check": check}[args[0]](args, lang)
    from .gui import main as window

    path = next((a for a in args if not a.startswith("--")), None)
    return window(["dai-pdf"], path)
