# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-pdf: D.Ai PDF, a reader that opens every PDF in a sandbox (docs/PDF.md).

  dai-pdf [FILE]                 open the window (with FILE, if given)
  dai-pdf info FILE              pages, metadata, and what the file wants to do
  dai-pdf text FILE [--page N] [--raw]   the text (Hebrew made readable unless --raw); all pages without --page
  dai-pdf check FILE             exit 0: nothing active in the file; 1: scripts, launches, submits, attachments
                                 or an XFA form were found (listed); 2: the file could not be opened
  dai-pdf merge A B ... -o OUT   one file from several, in this order
  dai-pdf split FILE --pages 1-3,7 -o OUT      only those pages (extract); without --pages, one file per page
  dai-pdf rotate FILE --by 90 [--pages 2,4] -o OUT   turn pages (90, 180, 270); all pages without --pages
  dai-pdf delete FILE --pages 2 -o OUT         the file without those pages
  dai-pdf fields FILE            the form's fields: name, kind, value
  dai-pdf fill FILE --set name=value ... [--flatten] -o OUT   fill the form (true/false for check boxes)
  dai-pdf ocr FILE -o OUT [--lang heb,eng] [--all]   a text layer for scanned pages (every page with --all)
  dai-pdf strip FILE -o OUT        remove the metadata (author, program, dates, XMP) before sharing
  dai-pdf redact FILE --page N --box LEFT,TOP,WIDTH,HEIGHT ... -o OUT   black boxes; the page becomes a
                                   picture, so what was under a box is truly gone
  dai-pdf export FILE --dir FOLDER [--dpi 150] [--pages 1-3]   every page as a PNG picture
  dai-pdf compress FILE -o OUT [--strong] [--check]   a smaller file: pictures at most 2000 px (1200 with --strong);
                                   --check only says what the size would be, and writes nothing
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


def _editor():
    from .edit import Editor

    direct = os.environ.get("DAI_PDF_DIRECT") == "1"
    python = os.environ.get("DAI_PDF_PYTHON") or sys.executable
    return Editor(sandboxed=not direct, python=python)


def _inputs(args: list[str]) -> list[str]:
    skip, out = False, []
    for arg in args[1:]:
        if skip:
            skip = False
        elif arg in ("-o", "--pages", "--by", "--set", "--password", "--lang", "--page", "--box", "--dir", "--dpi"):
            skip = True
        elif not arg.startswith("--"):
            out.append(arg)
    return out


def _edit_error(exc, lang: str) -> int:
    from .edit import EditError

    assert isinstance(exc, EditError)
    messages = {
        "missing": ("There is no file called {detail}.", "אין קובץ בשם {detail}."),
        "password": ("The file is locked: add --password.", "הקובץ נעול: הוסיפו --password."),
        "sandbox": ("The sandbox (bubblewrap) is missing; nothing was written.", "ארגז החול (bubblewrap) חסר; שום דבר לא נכתב."),
        "bad request": ("Those pages do not exist in the file ({detail}).", "העמודים האלה לא קיימים בקובץ ({detail})."),
        "timeout": ("The edit took too long and was stopped.", "העריכה ארכה יותר מדי ונעצרה."),
    }
    en, he = messages.get(exc.kind, ("The file could not be edited ({detail}).", "לא ניתן היה לערוך את הקובץ ({detail})."))
    print(say(lang, en, he, detail=exc.detail or exc.kind), file=sys.stderr)
    return 2


def _count(path: str, password: str) -> int:
    reader = _reader(path, password)
    try:
        return reader.open().count
    finally:
        reader.close()


def edit(args: list[str], lang: str) -> int:
    from .edit import EditError, parse_pages

    command = args[0]
    inputs = _inputs(args)
    out = _option(args, "-o")
    password = _option(args, "--password") or ""
    if not inputs:
        print(say(lang, "Which file? dai-pdf {command} FILE", "איזה קובץ? dai-pdf {command} FILE", command=command), file=sys.stderr)
        return 2
    if command not in ("fields", "export") and not out and not (command == "compress" and "--check" in args):
        print(say(lang, "Where to? add -o OUT.pdf", "לאן? הוסיפו -o OUT.pdf"), file=sys.stderr)
        return 2
    editor = _editor()
    try:
        if command == "fields":
            fields = editor.fields(inputs[0], password)
            if not fields:
                print(say(lang, "No form fields in this file.", "אין שדות טופס בקובץ הזה."))
            for f in fields:
                value = f.get("value")
                shown = (say(lang, "checked", "מסומן") if value else say(lang, "unchecked", "לא מסומן")) \
                    if f["kind"] == "checkbox" else str(value)
                extra = ""
                if f.get("options"):
                    extra = "  [" + ", ".join(o[0] if isinstance(o, list) else str(o) for o in f["options"]) + "]"
                print(f"{f['name']}  ({f['kind']}, {say(lang, 'page', 'עמוד')} {f['page'] + 1}): {shown}{extra}")
            return 0
        if command == "merge":
            pages = []
            for i, path in enumerate(inputs):
                pages += [{"source": i, "index": j, "rotate": 0} for j in range(_count(path, password if i == 0 else ""))]
            answer = editor.save(inputs, out, pages=pages, passwords=[password])
        elif command in ("split", "rotate", "delete"):
            count = _count(inputs[0], password)
            try:
                chosen = parse_pages(_option(args, "--pages") or "", count)
            except ValueError as exc:
                print(say(lang, "No page {page}: the file has {n}.", "אין עמוד {page}: בקובץ יש {n}.", page=exc, n=count), file=sys.stderr)
                return 2
            if command == "split":
                if _option(args, "--pages") is None:  # one file per page
                    stem = Path(out)
                    for index in range(count):
                        target = stem.with_name(f"{stem.stem}-{index + 1}{stem.suffix or '.pdf'}")
                        editor.save(inputs[:1], str(target), pages=[{"source": 0, "index": index, "rotate": 0}], passwords=[password])
                        print(target)
                    return 0
                pages = [{"source": 0, "index": i, "rotate": 0} for i in chosen]
            elif command == "rotate":
                try:
                    by = int(_option(args, "--by") or 90)
                except ValueError:
                    by = 0
                if by % 90 or by % 360 == 0:
                    print(say(lang, "--by takes 90, 180 or 270.", "‏--by מקבל 90, 180 או 270."), file=sys.stderr)
                    return 2
                pages = [{"source": 0, "index": i, "rotate": by if i in chosen else 0} for i in range(count)]
            else:
                if len(chosen) >= count:
                    print(say(lang, "That would leave no pages.", "זה לא ישאיר עמודים."), file=sys.stderr)
                    return 2
                pages = [{"source": 0, "index": i, "rotate": 0} for i in range(count) if i not in chosen]
            answer = editor.save(inputs[:1], out, pages=pages, passwords=[password])
        elif command == "ocr":
            from .edit import ocr_langs
            answer = editor.save(inputs[:1], out, ocr={"pages": "all" if "--all" in args else "scans",
                                                       "langs": ocr_langs(lang, _option(args, "--lang") or "")}, passwords=[password])
            print(say(lang, "{n} pages got a text layer.", "{n} עמודים קיבלו שכבת טקסט.", n=answer.get("ocr", 0)))
        elif command == "strip":
            answer = editor.save(inputs[:1], out, strip_metadata=True, passwords=[password])
            print(say(lang, "Metadata removed.", "המטא-דאטה הוסר."))
        elif command == "compress":
            from .edit import human_size
            level = "strong" if "--strong" in args else "light"
            if "--check" in args:
                answer = editor.measure(inputs[:1], compress=level, passwords=[password])
            else:
                answer = editor.save(inputs[:1], out, compress=level, passwords=[password])
            print(say(lang, "{before} → {after} ({n} pictures made smaller)", "{before} ← {after} ({n} תמונות הוקטנו)",
                      before=human_size(answer.get("before", 0)), after=human_size(answer.get("bytes", 0)), n=answer.get("compressed", 0)))
        elif command == "redact":
            boxes, page = [], None
            for i, arg in enumerate(args):
                if arg == "--page" and i + 1 < len(args):
                    try:
                        page = int(args[i + 1]) - 1
                    except ValueError:
                        page = -1
                elif arg == "--box" and i + 1 < len(args):
                    try:
                        rect = [float(v) for v in args[i + 1].split(",")]
                    except ValueError:
                        rect = []
                    if page is None or page < 0 or len(rect) != 4:
                        print(say(lang, "Say --page N before each --box LEFT,TOP,WIDTH,HEIGHT (in points).",
                                  "ציינו --page N לפני כל --box LEFT,TOP,WIDTH,HEIGHT (בנקודות)."), file=sys.stderr)
                        return 2
                    boxes.append({"page": page, "rect": rect})
            if not boxes:
                print(say(lang, "Nothing to black out: add --page N --box LEFT,TOP,WIDTH,HEIGHT.",
                          "אין מה להשחיר: הוסיפו --page N --box LEFT,TOP,WIDTH,HEIGHT."), file=sys.stderr)
                return 2
            answer = editor.save(inputs[:1], out, redactions=boxes, passwords=[password])
            print(say(lang, "{n} pages redacted; each became a picture, so nothing under a box remains.",
                      "{n} עמודים הושחרו; כל אחד הפך לתמונה, כך ששום דבר מתחת לתיבה לא נשאר.", n=answer.get("redacted", 0)))
        elif command == "export":
            folder = _option(args, "--dir")
            if not folder:
                print(say(lang, "Where to? add --dir FOLDER", "לאן? הוסיפו --dir FOLDER"), file=sys.stderr)
                return 2
            count = _count(inputs[0], password)
            try:
                chosen = parse_pages(_option(args, "--pages") or "", count)
                dpi = int(_option(args, "--dpi") or 150)
            except ValueError as exc:
                print(say(lang, "No page {page}: the file has {n}.", "אין עמוד {page}: בקובץ יש {n}.", page=exc, n=count), file=sys.stderr)
                return 2
            files = editor.export(inputs[:1], folder, pages=[{"source": 0, "index": i, "rotate": 0} for i in chosen], dpi=dpi,
                                  passwords=[password])
            for f in files:
                print(f)
            return 0
        elif command == "fill":
            values: dict[str, object] = {}
            for i, arg in enumerate(args):
                if arg == "--set" and i + 1 < len(args) and "=" in args[i + 1]:
                    name, raw = args[i + 1].split("=", 1)
                    values[name] = True if raw.lower() == "true" else False if raw.lower() == "false" else raw
            answer = editor.save(inputs[:1], out, fields=values, flatten="--flatten" in args, passwords=[password])
            print(say(lang, "{n} fields filled.", "{n} שדות מולאו.", n=answer.get("filled", 0)))
        else:
            return 2
    except EditError as exc:
        return _edit_error(exc, lang)
    if out:
        print(say(lang, "{out}: {n} pages", "{out}: {n} עמודים", out=out, n=answer.get("pages", 0)))
    return 0


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
    if args and args[0] in ("merge", "split", "rotate", "delete", "fields", "fill", "ocr", "strip", "redact", "export", "compress"):
        return edit(args, lang)
    from .gui import main as window

    path = next((a for a in args if not a.startswith("--")), None)
    return window(["dai-pdf"], path)
