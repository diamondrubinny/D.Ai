# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Editing a PDF (docs/PDF.md stage 2): pages and forms, through pikepdf, inside the sandbox.

The window never parses a PDF, so editing runs in a one-shot helper under bubblewrap (dai_pdf.sandbox.edit_argv):
the inputs are bound read-only, an empty folder the window made is bound writable, one JSON request arrives on
stdin, one JSON answer leaves on stdout, and the result lands in that folder. Nothing in the files is executed.

  {"op": "fields"}                               -> the form fields of input 0 (name, kind, value, options, page)
  {"op": "save", "pages": [...], "fields": {...}, "flatten": false, "passwords": [...]}
       pages:  [{"source": 0, "index": 3, "rotate": 90}, ...]   the new order; source 0 is the document, 1.. the
               other inputs (insert, merge); rotate is added to the page's own rotation
       fields: {"name": "text" | true | false | "Choice"}         values to fill into input 0's form
       flatten: true bakes the form and the annotations into the pages (no longer editable)
       -> {"ok": true, "pages": N, "bytes": B}  and the file at OUT/result.pdf

Editor (outside the sandbox) runs the helper and moves the result where the person asked.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import sandbox

RESULT = "result.pdf"
EDIT_TIMEOUT = 180.0
MAX_PAGES = 20_000
MAX_SOURCES = 64


class EditError(Exception):
    def __init__(self, kind: str, detail: str = "") -> None:
        super().__init__(kind)
        self.kind, self.detail = kind, detail


# --- inside the sandbox ------------------------------------------------------------------------------------------

def _open(path: str, password: str):
    import pikepdf

    try:
        return pikepdf.open(path, password=password or "")
    except pikepdf.PasswordError as exc:
        raise EditError("password", str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - anything qpdf refuses
        raise EditError("broken", type(exc).__name__) from exc


def _name(obj) -> str:
    return str(obj)[1:] if obj is not None and str(obj).startswith("/") else str(obj or "")


def _field_name(field) -> str:
    parts = []
    node = field
    seen = 0
    while node is not None and seen < 32:
        if "/T" in node:
            parts.append(str(node.T))
        node = node.get("/Parent")
        seen += 1
    return ".".join(reversed(parts))


def _inherited(field, key: str):
    node = field
    seen = 0
    while node is not None and seen < 32:
        if key in node:
            return node[key]
        node = node.get("/Parent")
        seen += 1
    return None


def _widgets(field) -> list:
    """The widget annotations of a field: the field itself, or its kids that are widgets."""
    kids = field.get("/Kids")
    if kids is None:
        return [field]
    out = []
    for kid in kids:
        if "/Kids" in kid and "/T" in kid:
            continue  # a child field, listed on its own
        out.append(kid)
    return out


def _on_state(widget) -> str:
    ap = widget.get("/AP")
    if ap is not None and "/N" in ap:
        try:
            for key in ap.N.keys():
                if key != "/Off":
                    return key[1:]
        except (AttributeError, TypeError):
            pass
    return "Yes"


def list_fields(pdf) -> list[dict]:
    """Every fillable field of the form, as the window and the command line show them."""
    import pikepdf

    acroform = pdf.Root.get("/AcroForm")
    if acroform is None or "/Fields" not in acroform:
        return []
    page_of: dict[tuple, int] = {}
    for i, page in enumerate(pdf.pages):
        for annot in page.obj.get("/Annots", []) or []:
            try:
                page_of[annot.objgen] = i
            except AttributeError:
                continue
    out: list[dict] = []

    def walk(field, depth: int) -> None:
        if depth > 32 or len(out) >= 5000:
            return
        kids = field.get("/Kids")
        if kids is not None and any("/T" in kid for kid in kids):
            for kid in kids:
                walk(kid, depth + 1)
            return
        kind_name = _name(_inherited(field, "/FT"))
        if not kind_name:
            return
        flags = int(_inherited(field, "/Ff") or 0)
        widgets = _widgets(field)
        page = next((page_of.get(w.objgen) for w in widgets if w.objgen in page_of), -1)
        value = _inherited(field, "/V")
        entry = {"name": _field_name(field), "page": page if page is not None else -1,
                 "readonly": bool(flags & 1), "required": bool(flags & 2)}
        if kind_name == "Tx":
            entry.update(kind="text", value=str(value) if value is not None else "", multiline=bool(flags & (1 << 12)))
        elif kind_name == "Btn":
            if flags & (1 << 16):
                return  # a push button: nothing to fill
            states = [_on_state(w) for w in widgets]
            if flags & (1 << 15):
                entry.update(kind="radio", value=_name(value) if value is not None else "Off", options=states)
            else:
                entry.update(kind="checkbox", value=value is not None and _name(value) != "Off", on=states[0] if states else "Yes")
        elif kind_name == "Ch":
            options = []
            for opt in _inherited(field, "/Opt") or []:
                if isinstance(opt, pikepdf.Array) and len(opt) >= 2:
                    options.append([str(opt[0]), str(opt[1])])
                else:
                    options.append([str(opt), str(opt)])
            entry.update(kind="choice", value=str(value) if value is not None else "", options=options,
                         combo=bool(flags & (1 << 17)))
        else:
            return  # signatures: stage 4
        out.append(entry)

    for field in acroform.Fields:
        walk(field, 0)
    return out


def fill_fields(pdf, values: dict) -> int:
    """Set field values; returns how many were set. Appearances are regenerated so every viewer shows them."""
    import pikepdf

    acroform = pdf.Root.get("/AcroForm")
    if acroform is None or not values:
        return 0
    by_name: dict[str, object] = {}

    def walk(field, depth: int) -> None:
        if depth > 32:
            return
        kids = field.get("/Kids")
        if kids is not None and any("/T" in kid for kid in kids):
            for kid in kids:
                walk(kid, depth + 1)
            return
        by_name[_field_name(field)] = field

    for field in acroform.Fields:
        walk(field, 0)
    done = 0
    for name, value in values.items():
        field = by_name.get(str(name))
        if field is None:
            continue
        kind = _name(_inherited(field, "/FT"))
        flags = int(_inherited(field, "/Ff") or 0)
        if flags & 1:
            continue  # read-only
        if kind == "Tx" or kind == "Ch":
            field.V = pikepdf.String(str(value))
            if "/AP" in field:
                del field["/AP"]  # the old picture of the old value
            for widget in _widgets(field):
                if widget is not field and "/AP" in widget:
                    del widget["/AP"]
        elif kind == "Btn" and not flags & (1 << 16):
            widgets = _widgets(field)
            if flags & (1 << 15):
                chosen = str(value)
            else:
                chosen = _on_state(widgets[0]) if widgets and value is True else "Off"
            field.V = pikepdf.Name("/" + chosen)
            for widget in widgets:
                states = {_on_state(widget), "Off"}
                widget.AS = pikepdf.Name("/" + (chosen if chosen in states else "Off"))
        else:
            continue
        done += 1
    if done:
        acroform.NeedAppearances = True
        try:
            pdf.generate_appearance_streams()
        except Exception as exc:  # noqa: BLE001 - a viewer regenerates them from NeedAppearances
            print(f"dai-pdf edit: appearances: {type(exc).__name__}", file=sys.stderr)
    return done


def build(inputs: list[str], spec: dict, output: str) -> dict:
    """Make the file the spec describes from the inputs and write it to output."""
    import pikepdf

    passwords = list(spec.get("passwords") or [])
    if not inputs or len(inputs) > MAX_SOURCES:
        raise EditError("bad request", "inputs")
    pdfs = [_open(path, passwords[i] if i < len(passwords) else "") for i, path in enumerate(inputs)]
    main = pdfs[0]
    done = fill_fields(main, dict(spec.get("fields") or {}))
    pages = spec.get("pages")
    if pages is not None:
        if not isinstance(pages, list) or not pages or len(pages) > MAX_PAGES:
            raise EditError("bad request", "pages")
        chosen = []
        for entry in pages:
            source, index = int(entry.get("source", 0)), int(entry.get("index", 0))
            if not 0 <= source < len(pdfs) or not 0 <= index < len(pdfs[source].pages):
                raise EditError("bad request", f"page {source}:{index}")
            chosen.append((pdfs[source].pages[index], int(entry.get("rotate", 0)) % 360))
        del main.pages[:]
        for page, rotate in chosen:
            main.pages.append(page)
            page = main.pages[-1]
            if rotate:
                page.Rotate = (int(page.obj.get("/Rotate", 0)) + rotate) % 360
    if spec.get("flatten"):
        try:
            main.flatten_annotations("all")
        except Exception as exc:  # noqa: BLE001
            raise EditError("broken", f"flatten: {type(exc).__name__}") from exc
    main.remove_unreferenced_resources()
    main.save(output)
    for pdf in pdfs:
        pdf.close()
    return {"ok": True, "pages": len(pikepdf.open(output).pages), "bytes": os.path.getsize(output), "filled": done}


def main() -> int:
    """The sandboxed entry: argv = package, IN_DIR ("" means the inputs follow), OUT_DIR, count, [inputs...]."""
    if len(sys.argv) < 5:
        print("usage: edit <package dir> <in dir> <out dir> <count> [inputs]", file=sys.stderr)
        return 2
    in_dir, out_dir, count = sys.argv[2], sys.argv[3], int(sys.argv[4])
    inputs = [f"{in_dir}/{i}.pdf" for i in range(count)] if in_dir else sys.argv[5:5 + count]
    try:
        request = json.loads(sys.stdin.buffer.readline().decode("utf-8"))
        if not isinstance(request, dict):
            raise ValueError("not an object")
    except ValueError:
        print(json.dumps({"ok": False, "error": "bad request"}))
        return 1
    try:
        op = request.get("op")
        if op == "fields":
            passwords = list(request.get("passwords") or [])
            pdf = _open(inputs[0], passwords[0] if passwords else "")
            answer = {"ok": True, "fields": list_fields(pdf)}
        elif op == "save":
            answer = build(inputs, request, os.path.join(out_dir, RESULT))
        else:
            answer = {"ok": False, "error": "unknown op"}
    except EditError as exc:
        answer = {"ok": False, "error": exc.kind, "detail": exc.detail}
    except Exception as exc:  # noqa: BLE001 - the window gets a word, never a traceback with the file's contents
        answer = {"ok": False, "error": "broken", "detail": type(exc).__name__}
    sys.stdout.write(json.dumps(answer, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0 if answer.get("ok") else 1


# --- outside the sandbox: the window's and the command line's side ------------------------------------------------

class Editor:
    """Runs one edit at a time in the sandbox (or directly, for tests) and hands back the result."""

    def __init__(self, sandboxed: bool = True, python: str = "/usr/bin/python3", binds: tuple[str, ...] = ()) -> None:
        self.sandboxed, self.python, self.binds = sandboxed, python, binds

    def _run(self, inputs: list[str], request: dict) -> tuple[dict, Path | None]:
        for path in inputs:
            if not Path(path).is_file():
                raise EditError("missing", path)
        if self.sandboxed and not sandbox.available():
            raise EditError("sandbox", "bubblewrap is missing: a PDF is never edited outside the sandbox")
        with tempfile.TemporaryDirectory(prefix="dai-pdf-") as out_dir:
            os.chmod(out_dir, 0o700)
            argv = sandbox.edit_argv([str(Path(p).resolve()) for p in inputs], out_dir, self.python, self.binds) \
                if self.sandboxed else sandbox.direct_edit_argv([str(Path(p).resolve()) for p in inputs], out_dir, self.python)
            env = None if self.sandboxed else {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
            try:
                proc = subprocess.run(argv, input=(json.dumps(request) + "\n").encode("utf-8"), capture_output=True,
                                      timeout=EDIT_TIMEOUT, env=env, check=False)
            except subprocess.TimeoutExpired as exc:
                raise EditError("timeout") from exc
            except OSError as exc:
                raise EditError("dead", str(exc)) from exc
            line = proc.stdout.decode("utf-8", "replace").strip().splitlines()
            try:
                answer = json.loads(line[-1]) if line else {}
            except ValueError:
                answer = {}
            if not answer:
                raise EditError("dead", f"rc={proc.returncode}")
            if not answer.get("ok"):
                raise EditError(str(answer.get("error", "broken")), str(answer.get("detail", "")))
            result = Path(out_dir) / RESULT
            if request.get("op") == "save":
                if not result.is_file():
                    raise EditError("dead", "no result")
                keep = Path(tempfile.mkstemp(prefix="dai-pdf-", suffix=".pdf")[1])
                shutil.move(str(result), keep)  # out of the folder that is about to go
                return answer, keep
            return answer, None

    def fields(self, path: str, password: str = "") -> list[dict]:
        answer, _ = self._run([path], {"op": "fields", "passwords": [password]})
        return [dict(f) for f in answer.get("fields", [])]

    def save(self, inputs: list[str], destination: str, pages: list[dict] | None = None, fields: dict | None = None,
             flatten: bool = False, passwords: list[str] | None = None) -> dict:
        """Write the described file to destination (replacing it only after the sandbox finished cleanly)."""
        request = {"op": "save", "pages": pages, "fields": fields or {}, "flatten": bool(flatten),
                   "passwords": passwords or []}
        answer, result = self._run(inputs, request)
        assert result is not None
        target = Path(destination)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(result), str(target))
            os.chmod(target, 0o600)
        finally:
            if result.exists():
                result.unlink()
        return answer


def parse_pages(text: str, count: int) -> list[int]:
    """"1-3,5" -> [0, 1, 2, 4] (1-based in, 0-based out), in the order written; "" means every page."""
    if not text.strip():
        return list(range(count))
    out: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a or 1), int(b or count)
        else:
            start = end = int(part)
        if start < 1 or end > count or start > end:
            raise ValueError(part)
        out.extend(range(start - 1, end))
    return out
