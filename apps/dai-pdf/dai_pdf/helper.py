# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The part of D.Ai PDF that touches the file. It runs inside the sandbox (dai_pdf.sandbox), one process per
open document, and answers the window over stdin and stdout:

  request:   one JSON object per line
  answer:    one JSON line; when it has "bytes", that many raw bytes follow (a PNG)

  {"op": "open", "password": ""}          -> pages, metadata, outline, findings
  {"op": "render", "page": 0, "width": W, "height": H}   -> PNG
  {"op": "text", "page": 0}               -> the page's text, as extracted (the window makes Hebrew readable)
  {"op": "select", "page": 0, "start": 10, "length": 5}  -> rectangles of those characters (points, top-left)
  {"op": "links", "page": 0}              -> links on the page: where they go (URL or page) and their rectangle
  {"op": "close"}

Rendering: Qt PDF (PDFium). Inspection: pikepdf (qpdf). Nothing here follows a link, runs a script, opens an
attachment or writes a file. Stdout carries only answers; everything else goes to stderr.
"""
from __future__ import annotations

import json
import sys

MAX_SIDE = 8_000      # pixels: more than this is not a zoom level anyone uses (800% of A4 is about 6600)
MAX_TEXT = 2_000_000  # characters per page sent back
MAX_OUTLINE = 5_000


def _json_line(obj: dict) -> None:
    sys.stdout.buffer.write(json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


def _answer(obj: dict, body: bytes = b"") -> None:
    if body:
        obj = {**obj, "bytes": len(body)}
    _json_line(obj)
    if body:
        sys.stdout.buffer.write(body)
        sys.stdout.buffer.flush()


def _outline(model, parent, level: int, out: list[dict]) -> None:
    from PyQt6.QtPdf import QPdfBookmarkModel

    rows = model.rowCount(parent)
    for row in range(rows):
        if len(out) >= MAX_OUTLINE:
            return
        index = model.index(row, 0, parent)
        title = model.data(index, QPdfBookmarkModel.Role.Title.value) or ""
        page = model.data(index, QPdfBookmarkModel.Role.Page.value)
        out.append({"title": str(title)[:300], "page": int(page) if page is not None else -1, "level": level})
        _outline(model, index, level + 1, out)


def _metadata(doc) -> dict:
    from PyQt6.QtCore import QDateTime
    from PyQt6.QtPdf import QPdfDocument

    fields = {
        "title": QPdfDocument.MetaDataField.Title, "author": QPdfDocument.MetaDataField.Author,
        "subject": QPdfDocument.MetaDataField.Subject, "keywords": QPdfDocument.MetaDataField.Keywords,
        "producer": QPdfDocument.MetaDataField.Producer, "creator": QPdfDocument.MetaDataField.Creator,
        "created": QPdfDocument.MetaDataField.CreationDate, "modified": QPdfDocument.MetaDataField.ModificationDate,
    }
    out = {}
    for key, which in fields.items():
        value = doc.metaData(which)
        if isinstance(value, QDateTime):
            out[key] = value.toString("yyyy-MM-dd HH:mm") if value.isValid() else ""
        else:
            out[key] = str(value or "")[:500]
    return out


def _open_pikepdf(path: str, password: str):
    """pikepdf's view of the file, for the findings and the links; None when it cannot be had."""
    try:
        import pikepdf
    except ImportError:
        return None
    try:
        return pikepdf.open(path, password=password or "")
    except Exception as exc:  # noqa: BLE001 - the viewer still works; the bar says the file could not be inspected
        print(f"dai-pdf helper: could not inspect: {type(exc).__name__}", file=sys.stderr)
        return None


def _findings(pdf) -> dict:
    if pdf is None:
        return {"unknown": True}
    try:
        from .findings import scan

        return scan(pdf).to_dict()
    except Exception as exc:  # noqa: BLE001
        print(f"dai-pdf helper: could not inspect: {type(exc).__name__}", file=sys.stderr)
        return {"unknown": True}


def _page_index(pdf, target) -> int:
    """The index of a page object in the file, or -1."""
    try:
        wanted = target.objgen
    except AttributeError:
        return -1
    for i, page in enumerate(pdf.pages):
        if page.obj.objgen == wanted:
            return i
    return -1


def _signatures(pdf, path: str) -> list[dict]:
    """Digital signatures, checked with OpenSSL inside the sandbox (signatures.py); [] when pikepdf could not look."""
    if pdf is None:
        return []
    try:
        from . import signatures

        return signatures.scan(pdf, path)
    except Exception:  # noqa: BLE001 - the file still opens; the window says nothing about signatures
        return []


def _links_from_pikepdf(pdf, index: int) -> list[dict]:
    """Link annotations on a page: where they go and their rectangle in points, top-left origin, on the page
    as Qt draws it (the crop box, with /Rotate applied). Qt's own link model is not in every PyQt6 build."""
    import pikepdf

    page = pdf.pages[index]
    try:
        box = [float(v) for v in page.cropbox]
    except Exception:  # noqa: BLE001 - no usable crop box: the media box
        box = [float(v) for v in page.mediabox]
    x0, y0, x1, y1 = min(box[0], box[2]), min(box[1], box[3]), max(box[0], box[2]), max(box[1], box[3])
    width, height = x1 - x0, y1 - y0
    rotate = int(page.obj.get("/Rotate", 0) or 0) % 360
    annots = page.obj.get("/Annots")
    out: list[dict] = []
    if not isinstance(annots, pikepdf.Array):
        return out
    for annot in annots:
        if not isinstance(annot, pikepdf.Dictionary) or str(annot.get("/Subtype")) != "/Link":
            continue
        try:
            rect = [float(v) for v in annot.get("/Rect")]
        except Exception:  # noqa: BLE001 - a link without a usable rectangle cannot be clicked
            continue
        rx0, ry0, rx1, ry1 = min(rect[0], rect[2]) - x0, min(rect[1], rect[3]) - y0, max(rect[0], rect[2]) - x0, max(rect[1], rect[3]) - y0
        # PDF's origin is bottom-left; Qt's is top-left.
        left, top, w, h = rx0, height - ry1, rx1 - rx0, ry1 - ry0
        if rotate == 90:
            left, top, w, h = height - top - h, left, h, w
        elif rotate == 180:
            left, top = width - left - w, height - top - h
        elif rotate == 270:
            left, top, w, h = top, width - left - w, h, w
        url, target = "", -1
        action = annot.get("/A")
        dest = annot.get("/Dest")
        if isinstance(action, pikepdf.Dictionary):
            kind = str(action.get("/S"))
            if kind == "/URI":
                url = str(action.get("/URI") or "")
            elif kind == "/GoToR":
                url = "file:" + str(action.get("/F") or "")
            elif kind == "/Launch":
                url = "launch:" + str(action.get("/F") or "")
            elif kind == "/GoTo":
                dest = action.get("/D")
        if isinstance(dest, pikepdf.Array) and len(dest) and not url:
            target = _page_index(pdf, dest[0])
        out.append({"url": url[:4000], "page": target,
                    "rect": [round(left, 2), round(top, 2), round(w, 2), round(h, 2)]})
        if len(out) >= 2000:
            break
    return out


class Server:
    def __init__(self, path: str) -> None:
        from PyQt6.QtGui import QGuiApplication, QImageReader
        from PyQt6.QtPdf import QPdfDocument

        self.app = QGuiApplication(["dai-pdf-helper"])
        QImageReader.setAllocationLimit(1024)
        self.path = path
        self.doc = QPdfDocument(None)
        self.password = ""
        self.pdf = None  # pikepdf's view, once opened

    def open(self, password: str) -> dict:
        from PyQt6.QtPdf import QPdfBookmarkModel, QPdfDocument

        self.password = password or ""
        self.doc.setPassword(self.password)
        err = self.doc.load(self.path)
        if err == QPdfDocument.Error.IncorrectPassword:
            return {"ok": False, "error": "password"}
        if err != QPdfDocument.Error.None_:
            return {"ok": False, "error": "broken", "detail": str(err)}
        count = self.doc.pageCount()
        pages = []
        for i in range(count):
            size = self.doc.pagePointSize(i)
            pages.append([round(size.width(), 2), round(size.height(), 2)])
        bookmarks = QPdfBookmarkModel(None)
        bookmarks.setDocument(self.doc)
        from PyQt6.QtCore import QModelIndex

        outline: list[dict] = []
        _outline(bookmarks, QModelIndex(), 0, outline)
        labels = []
        for i in range(min(count, MAX_OUTLINE)):
            label = self.doc.pageLabel(i)
            labels.append(label if label and label != str(i + 1) else "")
        self.pdf = _open_pikepdf(self.path, self.password)
        return {"ok": True, "pages": pages, "labels": labels, "metadata": _metadata(self.doc), "outline": outline,
                "findings": _findings(self.pdf), "signatures": _signatures(self.pdf, self.path)}

    def render(self, page: int, width: int, height: int) -> tuple[dict, bytes]:
        from PyQt6.QtCore import QBuffer, QIODevice, QSize

        if not 0 <= page < self.doc.pageCount():
            return {"ok": False, "error": "no such page"}, b""
        width, height = max(1, min(int(width), MAX_SIDE)), max(1, min(int(height), MAX_SIDE))
        from PyQt6.QtPdf import QPdfDocumentRenderOptions

        options = QPdfDocumentRenderOptions()
        options.setRenderFlags(QPdfDocumentRenderOptions.RenderFlag.Annotations)  # marks made in D.Ai PDF show
        image = self.doc.render(page, QSize(width, height), options)
        if image.isNull():
            return {"ok": False, "error": "could not draw"}, b""
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            return {"ok": False, "error": "could not encode"}, b""
        return {"ok": True, "width": image.width(), "height": image.height()}, bytes(buffer.data())

    def text(self, page: int) -> dict:
        if not 0 <= page < self.doc.pageCount():
            return {"ok": False, "error": "no such page"}
        return {"ok": True, "text": self.doc.getAllText(page).text()[:MAX_TEXT]}

    def select(self, page: int, start: int, length: int) -> dict:
        if not 0 <= page < self.doc.pageCount():
            return {"ok": False, "error": "no such page"}
        selection = self.doc.getSelectionAtIndex(page, max(0, int(start)), max(0, int(length)))
        rects = []
        for poly in selection.bounds():
            rect = poly.boundingRect()
            rects.append([round(rect.x(), 2), round(rect.y(), 2), round(rect.width(), 2), round(rect.height(), 2)])
        return {"ok": True, "rects": rects, "text": selection.text()[:MAX_TEXT]}

    def links(self, page: int) -> dict:
        if not 0 <= page < self.doc.pageCount():
            return {"ok": False, "error": "no such page"}
        if self.pdf is not None and page < len(self.pdf.pages):
            try:
                return {"ok": True, "links": _links_from_pikepdf(self.pdf, page)}
            except Exception as exc:  # noqa: BLE001 - fall back to Qt's model where it exists
                print(f"dai-pdf helper: links: {type(exc).__name__}", file=sys.stderr)
        try:
            from PyQt6.QtCore import QModelIndex
            from PyQt6.QtPdf import QPdfLinkModel
        except ImportError:
            return {"ok": True, "links": []}
        model = QPdfLinkModel(None)
        model.setDocument(self.doc)
        model.setPage(page)
        out = []
        for row in range(min(model.rowCount(QModelIndex()), 2000)):
            index = model.index(row, 0)
            url = model.data(index, QPdfLinkModel.Role.Url.value)
            target = model.data(index, QPdfLinkModel.Role.Page.value)
            rect = model.data(index, QPdfLinkModel.Role.Rectangle.value)
            out.append({
                "url": url.toString() if url is not None and not url.isEmpty() else "",
                "page": int(target) if target is not None else -1,
                "rect": [round(rect.x(), 2), round(rect.y(), 2), round(rect.width(), 2), round(rect.height(), 2)]
                if rect is not None else [0, 0, 0, 0],
            })
        return {"ok": True, "links": out}

    def serve(self) -> int:
        for raw in sys.stdin.buffer:
            try:
                request = json.loads(raw.decode("utf-8"))
                op = request.get("op")
            except (ValueError, AttributeError):
                _answer({"ok": False, "error": "bad request"})
                continue
            try:
                if op == "open":
                    _answer(self.open(str(request.get("password") or "")))
                elif op == "render":
                    head, body = self.render(int(request.get("page", 0)), request.get("width", 1), request.get("height", 1))
                    _answer(head, body)
                elif op == "text":
                    _answer(self.text(int(request.get("page", 0))))
                elif op == "select":
                    _answer(self.select(int(request.get("page", 0)), request.get("start", 0), request.get("length", 0)))
                elif op == "links":
                    _answer(self.links(int(request.get("page", 0))))
                elif op == "close":
                    _answer({"ok": True})
                    return 0
                else:
                    _answer({"ok": False, "error": "unknown op"})
            except Exception as exc:  # noqa: BLE001 - one bad page must not kill the helper
                _answer({"ok": False, "error": f"{type(exc).__name__}"})
        return 0


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: helper <package dir> <pdf>", file=sys.stderr)
        return 2
    return Server(sys.argv[2]).serve()


if __name__ == "__main__":
    sys.exit(main())
