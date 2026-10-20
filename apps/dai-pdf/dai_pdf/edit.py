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
       annotations: [{"page": P, "kind": "highlight"|"underline"|"strikeout"|"note"|"text"|"stamp",
                      "rect": [left, top, width, height], "color": "#RRGGBB", "text": "...", "size": 12,
                      "image": I}]   P is a position in the new order; rect is in points, top-left origin, on
               the page as it is displayed (crop box, /Rotate applied), like the links the helper reports;
               image is an index into the extra inputs (pictures bound read-only after the PDFs)
       pdf_inputs: how many of the inputs are PDFs (the rest are pictures for stamps)
       redactions: [{"page": P, "rect": [...]}]   black boxes; the page becomes a picture, so what was under
               the box is truly gone (text, vectors, hidden layers: all of it, on that page)
       ocr: {"pages": "scans"|"all", "langs": "heb+eng"}   a text layer from Tesseract for pages without text
               ("scans") or every page; such a page becomes Tesseract's picture page with invisible text
       strip_metadata: true removes the Info dictionary, XMP and PieceInfo
       -> {"ok": true, "pages": N, "bytes": B}  and the file at OUT/result.pdf
  {"op": "export", "pages": [...], "dpi": 150}  -> every page as OUT/page-N.png (the plan's order and turns)

Markup (highlight, underline, strikeout, note) becomes a real annotation that any viewer draws. Free text and
stamps are drawn into the page as a picture (text is rendered by Qt, so Hebrew and right-to-left come out right
in every viewer; the price is that the text is not selectable). A page's own /Rotate is honoured, so what was
drawn on the screen lands where it was drawn.

Editor (outside the sandbox) runs the helper and moves the result where the person asked.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import sandbox

RESULT = "result.pdf"
EDIT_TIMEOUT = 180.0
OCR_TIMEOUT = 1800.0
MAX_PAGES = 20_000
MAX_SOURCES = 64
MAX_ANNOTATIONS = 5_000
MARKUP = {"highlight": "/Highlight", "underline": "/Underline", "strikeout": "/StrikeOut"}
TEXT_SCALE = 4  # pixels per point when text is drawn as a picture (288 dpi)
RASTER_DPI = 300          # redacted and OCR'd pages are pictures at this resolution
MAX_RASTER_SIDE = 10_000  # pixels: a page bigger than this is refused rather than eating the memory
OCR_LANGS = {"he": "heb", "en": "eng", "ar": "ara", "ru": "rus", "es": "spa", "fr": "fra", "de": "deu", "pt": "por"}


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


# --- annotations --------------------------------------------------------------------------------------------------

def _display_box(page) -> tuple[float, float, float, float, int]:
    """x0, y0 (PDF coordinates of the box's bottom-left), width, height of the page as displayed, and /Rotate."""
    try:
        box = [float(v) for v in page.cropbox]
    except Exception:  # noqa: BLE001 - no usable crop box: the media box
        box = [float(v) for v in page.mediabox]
    x0, y0, x1, y1 = min(box[0], box[2]), min(box[1], box[3]), max(box[0], box[2]), max(box[1], box[3])
    return x0, y0, x1 - x0, y1 - y0, int(page.obj.get("/Rotate", 0) or 0) % 360


def unrotated_rect(page, rect: list[float]) -> tuple[float, float, float, float]:
    """A rectangle on the displayed page (top-left origin) as (x, y, w, h) in PDF coordinates (bottom-left origin)
    of the unrotated page: the inverse of what the helper does for links."""
    x0, y0, width, height, rotate = _display_box(page)
    left, top, w, h = (float(v) for v in rect)
    if rotate == 90:
        left, top, w, h = top, height - left - w, h, w
    elif rotate == 180:
        left, top = width - left - w, height - top - h
    elif rotate == 270:
        left, top, w, h = width - top - h, left, h, w
    return x0 + left, y0 + height - top - h, w, h


def _colour(value: str) -> list[float]:
    value = (value or "#FFEB3B").lstrip("#")
    if len(value) != 6:
        value = "FFEB3B"
    return [round(int(value[i:i + 2], 16) / 255, 4) for i in (0, 2, 4)]


_APP = None


def _gui():
    """Qt's application object for drawing text and reading pictures, kept alive for the helper's lifetime."""
    global _APP
    from PyQt6.QtGui import QGuiApplication

    if QGuiApplication.instance() is None:
        _APP = QGuiApplication(["dai-pdf-edit"])
    return QGuiApplication.instance()


def _render_text(text: str, w_pt: float, h_pt: float, size_pt: float, colour: str) -> tuple[bytes, bytes, int, int]:
    """Text drawn by Qt into a picture: RGB bytes, alpha bytes, width, height. Hebrew is shaped and placed
    right to left; nothing here reaches the file's own content."""
    from PyQt6.QtCore import QRectF, Qt
    from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QTextOption

    _gui()
    w, h = max(1, round(w_pt * TEXT_SCALE)), max(1, round(h_pt * TEXT_SCALE))
    image = QImage(w, h, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    font = QFont("Noto Sans")
    font.setPixelSize(max(4, round(size_pt * TEXT_SCALE)))
    painter.setFont(font)
    painter.setPen(QColor("#" + (colour or "#111111").lstrip("#")))
    rtl = any("\u0590" <= ch <= "\u08ff" for ch in text)
    option = QTextOption(Qt.AlignmentFlag.AlignTop | (Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft))
    option.setWrapMode(QTextOption.WrapMode.WordWrap)
    option.setTextDirection(Qt.LayoutDirection.RightToLeft if rtl else Qt.LayoutDirection.LeftToRight)
    painter.drawText(QRectF(0, 0, w, h), text, option)
    painter.end()
    return _split_rgba(image)


def _split_rgba(image) -> tuple[bytes, bytes, int, int]:
    from PyQt6.QtGui import QImage

    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = image.width(), image.height()
    pointer = image.constBits()
    pointer.setsize(image.sizeInBytes())
    whole = bytes(pointer)
    stride = image.bytesPerLine()
    raw = whole if stride == w * 4 else b"".join(whole[y * stride:y * stride + w * 4] for y in range(h))
    rgb = bytearray(w * h * 3)
    alpha = bytearray(w * h)
    rgb[0::3], rgb[1::3], rgb[2::3], alpha[:] = raw[0::4], raw[1::4], raw[2::4], raw[3::4]
    return bytes(rgb), bytes(alpha), w, h


def _load_picture(path: str) -> tuple[bytes, bytes, int, int]:
    """A PNG or JPEG from the person, decoded by Qt (never by the PDF side), at most 4000 px a side."""
    from PyQt6.QtGui import QImageReader

    _gui()
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    if reader.format().data() not in (b"png", b"jpeg", b"jpg"):
        raise EditError("bad request", "a stamp is a PNG or JPEG picture")
    size = reader.size()
    if size.width() > 4000 or size.height() > 4000:
        reader.setScaledSize(size.scaled(4000, 4000, 1))  # Qt.AspectRatioMode.KeepAspectRatio
    image = reader.read()
    if image.isNull():
        raise EditError("bad request", "the picture could not be read")
    return _split_rgba(image)


def _image_xobject(pdf, rgb: bytes, alpha: bytes, w: int, h: int):
    import zlib
    import pikepdf

    smask = pdf.make_stream(zlib.compress(alpha), Type=pikepdf.Name.XObject, Subtype=pikepdf.Name.Image, Width=w, Height=h,
                            ColorSpace=pikepdf.Name.DeviceGray, BitsPerComponent=8, Filter=pikepdf.Name.FlateDecode)
    return pdf.make_stream(zlib.compress(rgb), Type=pikepdf.Name.XObject, Subtype=pikepdf.Name.Image, Width=w, Height=h,
                           ColorSpace=pikepdf.Name.DeviceRGB, BitsPerComponent=8, Filter=pikepdf.Name.FlateDecode, SMask=smask)


def _place(page, rect: list[float]) -> str:
    """The cm operator that puts a unit-square picture on the displayed rectangle, upright on screen, whatever
    the page's own /Rotate."""
    x, y, w, h = unrotated_rect(page, rect)
    rotate = _display_box(page)[4]
    dw, dh = float(rect[2]), float(rect[3])  # the picture's size as displayed
    if rotate == 90:
        a, b, c, d, e, f = 0, dw, -dh, 0, x + w, y
    elif rotate == 180:
        a, b, c, d, e, f = -dw, 0, 0, -dh, x + w, y + h
    elif rotate == 270:
        a, b, c, d, e, f = 0, -dw, dh, 0, x, y + h
    else:
        a, b, c, d, e, f = dw, 0, 0, dh, x, y
    return " ".join(f"{v:.4f}" for v in (a, b, c, d, e, f)) + " cm"


def add_annotations(pdf, annotations: list[dict], pictures: list[str]) -> int:
    """Markup as annotations; text and stamps drawn into the page. Returns how many were added."""
    import pikepdf

    if len(annotations) > MAX_ANNOTATIONS:
        raise EditError("bad request", "annotations")
    done = 0
    for entry in annotations:
        index = int(entry.get("page", -1))
        if not 0 <= index < len(pdf.pages):
            raise EditError("bad request", f"annotation page {index}")
        page = pdf.pages[index]
        kind = str(entry.get("kind", ""))
        rect = [float(v) for v in entry.get("rect", [0, 0, 0, 0])]
        if len(rect) != 4 or rect[2] <= 0 or rect[3] <= 0:
            raise EditError("bad request", "annotation rect")
        x, y, w, h = unrotated_rect(page, rect)
        colour = _colour(str(entry.get("color", "")))
        if kind in MARKUP:
            annot = pdf.make_indirect(pikepdf.Dictionary(
                Type=pikepdf.Name.Annot, Subtype=pikepdf.Name(MARKUP[kind]), Rect=[x, y, x + w, y + h],
                QuadPoints=[x, y + h, x + w, y + h, x, y, x + w, y], C=colour, CA=1, F=4,
                Contents=pikepdf.String(str(entry.get("text", ""))[:2000]), T=pikepdf.String("D.Ai PDF")))
        elif kind == "note":
            annot = pdf.make_indirect(pikepdf.Dictionary(
                Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Text, Rect=[x, y, x + 20, y + 20], Name=pikepdf.Name.Note,
                C=colour, F=28, Contents=pikepdf.String(str(entry.get("text", ""))[:4000]), T=pikepdf.String("D.Ai PDF"),
                Open=False))
        elif kind in ("text", "stamp"):
            if kind == "text":
                rgb, alpha, iw, ih = _render_text(str(entry.get("text", ""))[:4000], rect[2], rect[3],
                                                  float(entry.get("size", 12) or 12), str(entry.get("color", "#111111")))
            else:
                picture = int(entry.get("image", -1))
                if not 0 <= picture < len(pictures):
                    raise EditError("bad request", "stamp picture")
                rgb, alpha, iw, ih = _load_picture(pictures[picture])
            xobj = _image_xobject(pdf, rgb, alpha, iw, ih)
            name = page.add_resource(xobj, pikepdf.Name.XObject, prefix="DaiImg")
            page.contents_add(pdf.make_stream(f"q {_place(page, rect)} {name} Do Q".encode("ascii")), prepend=False)
            done += 1
            continue
        else:
            raise EditError("bad request", f"annotation kind {kind}")
        annots = page.obj.get("/Annots")
        if not isinstance(annots, pikepdf.Array):
            page.obj.Annots = pikepdf.Array([annot])
        else:
            annots.append(annot)
        done += 1
    return done


# --- pages as pictures: redaction, OCR, export -------------------------------------------------------------------

class _Renderer:
    """Qt PDF on the input files, inside the editor: pages drawn as pictures (with their own /Rotate applied)."""

    def __init__(self, inputs: list[str], passwords: list[str]) -> None:
        self.inputs, self.passwords, self.docs = inputs, passwords, {}
        _gui()

    def doc(self, source: int):
        from PyQt6.QtPdf import QPdfDocument

        if source not in self.docs:
            doc = QPdfDocument(None)
            doc.setPassword(self.passwords[source] if source < len(self.passwords) else "")
            if doc.load(self.inputs[source]) != QPdfDocument.Error.None_:
                raise EditError("broken", "Qt could not open the file to draw it")
            self.docs[source] = doc
        return self.docs[source]

    def render(self, source: int, index: int, dpi: int):
        from PyQt6.QtCore import QSize
        from PyQt6.QtPdf import QPdfDocumentRenderOptions

        doc = self.doc(source)
        size = doc.pagePointSize(index)
        w, h = round(size.width() * dpi / 72), round(size.height() * dpi / 72)
        if w > MAX_RASTER_SIDE or h > MAX_RASTER_SIDE or w < 1 or h < 1:
            raise EditError("bad request", f"page {index + 1} is too big to draw at {dpi} dpi")
        options = QPdfDocumentRenderOptions()
        options.setRenderFlags(QPdfDocumentRenderOptions.RenderFlag.Annotations)
        image = doc.render(index, QSize(w, h), options)
        if image.isNull():
            raise EditError("broken", f"page {index + 1} could not be drawn")
        # Qt draws the page over nothing (transparent); paper is white, and so is a picture of the page.
        from PyQt6.QtGui import QColor, QImage, QPainter

        paper = QImage(image.size(), QImage.Format.Format_RGB32)
        paper.fill(QColor("#FFFFFF"))
        painter = QPainter(paper)
        painter.drawImage(0, 0, image)
        painter.end()
        return paper

    def has_text(self, source: int, index: int) -> bool:
        return bool(self.doc(source).getAllText(index).text().strip())


def _black_out(image, rects: list[list[float]], dpi: int):
    from PyQt6.QtCore import QRectF
    from PyQt6.QtGui import QColor, QPainter

    painter = QPainter(image)
    painter.setPen(QColor("#000000"))
    painter.setBrush(QColor("#000000"))
    scale = dpi / 72
    for rect in rects:
        left, top, w, h = (float(v) for v in rect)
        painter.drawRect(QRectF(left * scale, top * scale, w * scale, h * scale))
    painter.end()
    return image


def _turned(image, rotate: int):
    from PyQt6.QtGui import QTransform

    return image.transformed(QTransform().rotate(rotate)) if rotate else image


def _picture_page(pdf, image, dpi: int):
    """A new page that is only this picture, sized so it prints at the same size as the page it replaces."""
    import pikepdf

    rgb, alpha, w, h = _split_rgba(image)
    import zlib
    xobj = pdf.make_stream(zlib.compress(rgb), Type=pikepdf.Name.XObject, Subtype=pikepdf.Name.Image, Width=w, Height=h,
                           ColorSpace=pikepdf.Name.DeviceRGB, BitsPerComponent=8, Filter=pikepdf.Name.FlateDecode)
    width_pt, height_pt = w * 72 / dpi, h * 72 / dpi
    page = pikepdf.Dictionary(Type=pikepdf.Name.Page, MediaBox=[0, 0, width_pt, height_pt],
                              Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(DaiPage=xobj)),
                              Contents=pdf.make_stream(f"q {width_pt:.4f} 0 0 {height_pt:.4f} 0 0 cm /DaiPage Do Q".encode("ascii")))
    return pikepdf.Page(page)


def _ocr_page(image, langs: str, dpi: int, work: Path):
    """Tesseract's PDF page for this picture: the picture plus an invisible text layer in any language."""
    import shutil
    import subprocess
    import pikepdf

    if shutil.which("tesseract") is None:
        raise EditError("missing tool", "tesseract")
    if not re.fullmatch(r"[a-z]{3}(?:\+[a-z]{3}){0,7}", langs):
        raise EditError("bad request", "ocr languages")
    png = work / "ocr.png"
    image.save(str(png), "PNG")
    result = subprocess.run(["tesseract", str(png), str(work / "ocr"), "-l", langs, "--dpi", str(dpi), "pdf"],
                            capture_output=True, text=True, timeout=600, check=False)
    out = work / "ocr.pdf"
    if result.returncode != 0 or not out.is_file():
        raise EditError("broken", "tesseract: " + (result.stderr or "").strip().splitlines()[-1:][0] if (result.stderr or "").strip() else "tesseract failed")
    import io
    produced = pikepdf.open(io.BytesIO(out.read_bytes()))  # in memory: the folder goes away before the save
    return produced, produced.pages[0]


def rasterize_pages(pdf, order: list[tuple[int, int, int]], inputs: list[str], passwords: list[str], spec: dict) -> tuple[int, int]:
    """Replace pages by pictures where the spec asks: redactions (black boxes, the content under them gone) and
    OCR (a text layer for scans). Returns (redacted, ocr'd)."""
    import tempfile

    redactions: dict[int, list[list[float]]] = {}
    for entry in spec.get("redactions") or []:
        index = int(entry.get("page", -1))
        rect = [float(v) for v in entry.get("rect", [])]
        if not 0 <= index < len(order) or len(rect) != 4 or rect[2] <= 0 or rect[3] <= 0:
            raise EditError("bad request", "redaction")
        redactions.setdefault(index, []).append(rect)
    ocr = spec.get("ocr") or {}
    which = str(ocr.get("pages", "scans")) if ocr else ""
    langs = str(ocr.get("langs") or "eng")
    if not redactions and not ocr:
        return 0, 0
    renderer = _Renderer(inputs, passwords)
    redacted = recognised = 0
    keep_alive = []
    with tempfile.TemporaryDirectory(prefix="dai-pdf-ocr-") as tmp:
        for position, (source, index, rotate) in enumerate(order):
            boxes = redactions.get(position, [])
            wants_ocr = bool(ocr) and (which == "all" or not renderer.has_text(source, index))
            if not boxes and not wants_ocr:
                continue
            image = renderer.render(source, index, RASTER_DPI)
            if boxes:
                image = _black_out(image, boxes, RASTER_DPI)
                redacted += 1
            image = _turned(image, rotate)
            if wants_ocr:
                produced, page = _ocr_page(image, langs, RASTER_DPI, Path(tmp))
                keep_alive.append(produced)
                pdf.pages[position] = page
                recognised += 1
            else:
                pdf.pages[position] = _picture_page(pdf, image, RASTER_DPI)
            if "/Rotate" in pdf.pages[position].obj:
                del pdf.pages[position].obj["/Rotate"]
    return redacted, recognised


def strip_metadata(pdf) -> None:
    """Nothing about the author, the program or the dates stays: Info, XMP, PieceInfo."""
    for key in list(pdf.docinfo.keys()):
        del pdf.docinfo[key]
    for key in ("/Metadata", "/PieceInfo"):
        if key in pdf.Root:
            del pdf.Root[key]
    for page in pdf.pages:
        for key in ("/Metadata", "/PieceInfo"):
            if key in page.obj:
                del page.obj[key]


def export_pages(inputs: list[str], spec: dict, out_dir: str) -> dict:
    """Every page of the plan as a PNG in out_dir."""
    passwords = list(spec.get("passwords") or [])
    count = int(spec.get("pdf_inputs") or len(inputs))
    pdfs = [_open(path, passwords[i] if i < len(passwords) else "") for i, path in enumerate(inputs[:count])]
    pages = spec.get("pages") or [{"source": 0, "index": i, "rotate": 0} for i in range(len(pdfs[0].pages))]
    dpi = max(36, min(600, int(spec.get("dpi") or 150)))
    renderer = _Renderer(inputs[:count], passwords)
    files = []
    for position, entry in enumerate(pages):
        source, index = int(entry.get("source", 0)), int(entry.get("index", 0))
        if not 0 <= source < len(pdfs) or not 0 <= index < len(pdfs[source].pages):
            raise EditError("bad request", f"page {source}:{index}")
        image = _turned(renderer.render(source, index, dpi), int(entry.get("rotate", 0)) % 360)
        name = f"page-{position + 1}.png"
        if not image.save(os.path.join(out_dir, name), "PNG"):
            raise EditError("broken", "could not write a picture")
        files.append(name)
    for pdf in pdfs:
        pdf.close()
    return {"ok": True, "files": files, "dpi": dpi}


def build(inputs: list[str], spec: dict, output: str) -> dict:
    """Make the file the spec describes from the inputs and write it to output."""
    import pikepdf

    passwords = list(spec.get("passwords") or [])
    count = int(spec.get("pdf_inputs") or len(inputs))
    pictures = inputs[count:]
    inputs = inputs[:count]
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
        turns = []
        for page, rotate in chosen:
            main.pages.append(page)
            turns.append(rotate)
        order = [(int(e.get("source", 0)), int(e.get("index", 0)), int(e.get("rotate", 0)) % 360) for e in pages]
        # Annotations are placed on the pages as they were drawn on screen, before any new turn is applied.
        marked = add_annotations(main, list(spec.get("annotations") or []), pictures)
        for page, rotate in zip(main.pages, turns):
            if rotate:
                page.Rotate = (int(page.obj.get("/Rotate", 0)) + rotate) % 360
    else:
        order = [(0, i, 0) for i in range(len(main.pages))]
        marked = add_annotations(main, list(spec.get("annotations") or []), pictures)
    redacted, recognised = rasterize_pages(main, order, inputs, passwords, spec)
    if spec.get("strip_metadata"):
        strip_metadata(main)
    if spec.get("flatten"):
        try:
            main.flatten_annotations("all")
        except Exception as exc:  # noqa: BLE001
            raise EditError("broken", f"flatten: {type(exc).__name__}") from exc
    main.remove_unreferenced_resources()
    main.save(output)
    for pdf in pdfs:
        pdf.close()
    return {"ok": True, "pages": len(pikepdf.open(output).pages), "bytes": os.path.getsize(output), "filled": done,
            "marked": marked, "redacted": redacted, "ocr": recognised}


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
        elif op == "export":
            answer = export_pages(inputs, request, out_dir)
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

    def _run(self, inputs: list[str], request: dict, keep_dir: str | None = None) -> tuple[dict, Path | None]:
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
                                      timeout=OCR_TIMEOUT if request.get("ocr") else EDIT_TIMEOUT, env=env, check=False)
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
            if request.get("op") == "export":
                moved = []
                for name in answer.get("files", []):
                    target = Path(keep_dir or ".") / name
                    shutil.move(str(Path(out_dir) / name), str(target))
                    os.chmod(target, 0o600)
                    moved.append(str(target))
                answer["files"] = moved
                return answer, None
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
             flatten: bool = False, passwords: list[str] | None = None, annotations: list[dict] | None = None,
             pictures: list[str] | None = None, redactions: list[dict] | None = None, ocr: dict | None = None,
             strip_metadata: bool = False) -> dict:
        """Write the described file to destination (replacing it only after the sandbox finished cleanly).
        `pictures` are stamp images, bound read-only after the PDFs."""
        request = {"op": "save", "pages": pages, "fields": fields or {}, "flatten": bool(flatten),
                   "passwords": passwords or [], "annotations": annotations or [], "pdf_inputs": len(inputs),
                   "redactions": redactions or [], "ocr": ocr or {}, "strip_metadata": bool(strip_metadata)}
        answer, result = self._run([*inputs, *(pictures or [])], request)
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

    def export(self, inputs: list[str], folder: str, pages: list[dict] | None = None, dpi: int = 150,
               passwords: list[str] | None = None) -> list[str]:
        """Every page as a PNG in folder (made if missing); returns the files written."""
        Path(folder).mkdir(parents=True, exist_ok=True)
        request = {"op": "export", "pages": pages, "dpi": int(dpi), "passwords": passwords or [], "pdf_inputs": len(inputs)}
        answer, _ = self._run(inputs, request, keep_dir=folder)
        return list(answer.get("files", []))


def ocr_langs(ui: str, extra: str = "") -> str:
    """Tesseract's language list for the person's language (first) and English, or what was asked for."""
    if extra:
        return extra.replace(",", "+")
    first = OCR_LANGS.get(ui[:2], "eng")
    return first if first == "eng" else first + "+eng"


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
