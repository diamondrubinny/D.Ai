# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""PDFs for the tests, written with pikepdf: plain, "active" (scripts, launches, links, a form that submits,
attachments, XFA), locked, many pages with an outline, and not a PDF at all."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

try:
    import pikepdf
except ImportError:  # pragma: no cover - the whole suite skips
    pikepdf = None


def need_libraries() -> None:
    if pikepdf is None:
        raise unittest.SkipTest("pikepdf is missing")
    try:
        from PyQt6 import QtPdf  # noqa: F401
    except ImportError as exc:
        raise unittest.SkipTest("PyQt6.QtPdf is missing") from exc


def _page(pdf, text: str, width: int = 300, height: int = 200):
    page = pikepdf.Page(pikepdf.Dictionary(Type=pikepdf.Name.Page, MediaBox=[0, 0, width, height]))
    pdf.pages.append(page)
    page = pdf.pages[-1]
    font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
                                                BaseFont=pikepdf.Name.Helvetica))
    page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
    safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    page.Contents = pdf.make_stream(f"BT /F1 24 Tf 20 100 Td ({safe}) Tj ET".encode("latin-1", "replace"))
    return page


def plain(path: Path, pages: int = 1) -> Path:
    pdf = pikepdf.new()
    for i in range(pages):
        _page(pdf, f"Hello D.Ai page {i + 1}")
    pdf.docinfo["/Title"] = "A plain file"
    pdf.docinfo["/Author"] = "Dana"
    pdf.save(path)
    return path


def with_outline(path: Path) -> Path:
    pdf = pikepdf.new()
    for i in range(5):
        _page(pdf, f"Chapter {i + 1}")
    outlines = pdf.open_outline()
    with outlines:
        first = pikepdf.OutlineItem("Part one", 0)
        first.children.append(pikepdf.OutlineItem("Chapter 2", 1))
        outlines.root.append(first)
        outlines.root.append(pikepdf.OutlineItem("Part two", 3))
    pdf.save(path)
    return path


def active(path: Path) -> Path:
    """Everything a file can "want": document JavaScript, an open action that launches, a URI link, a GoToR
    link, a form field that submits, an attachment, a file-attachment annotation, and an XFA marker."""
    pdf = pikepdf.new()
    page = _page(pdf, "Careful: this file wants things")
    link = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link, Rect=[20, 90, 200, 130],
                                                A=pikepdf.Dictionary(S=pikepdf.Name.URI, URI="https://example.com/x")))
    remote = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link, Rect=[20, 20, 100, 40],
                                                  A=pikepdf.Dictionary(S=pikepdf.Name.GoToR, F="other.pdf", D=[0])))
    js_annot = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link, Rect=[150, 20, 250, 40],
                                                    A=pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS="app.alert(2)")))
    att_annot = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.FileAttachment,
                                                     Rect=[250, 150, 280, 180], FS=pikepdf.Dictionary(F="notes.txt")))
    field = pdf.make_indirect(pikepdf.Dictionary(FT=pikepdf.Name.Btn, T="send", Rect=[10, 10, 50, 30],
                                                 A=pikepdf.Dictionary(S=pikepdf.Name.SubmitForm, F="https://example.com/collect")))
    page.Annots = pikepdf.Array([link, remote, js_annot, att_annot])
    pdf.Root.OpenAction = pikepdf.Dictionary(S=pikepdf.Name.Launch, F="calc.exe")
    pdf.Root.Names = pikepdf.Dictionary(JavaScript=pikepdf.Dictionary(Names=pikepdf.Array(["doc", pdf.make_indirect(
        pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS="app.alert(1)"))])))
    pdf.Root.AcroForm = pikepdf.Dictionary(Fields=pikepdf.Array([field]), XFA=pikepdf.Array([]))
    pdf.attachments["evil.exe"] = pikepdf.AttachedFileSpec(pdf, b"MZ not really")  # pikepdf 8 and 10 alike
    pdf.save(path)
    return path


def form(path: Path) -> Path:
    """A two-page form: a text field and a check box on page 1, a radio group and a drop-down on page 2."""
    pdf = pikepdf.new()
    first = _page(pdf, "Please fill in")
    second = _page(pdf, "And choose")
    font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica))
    da = pikepdf.String("/Helv 12 Tf 0 g")
    name = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget, FT=pikepdf.Name.Tx,
                                                T=pikepdf.String("name"), V=pikepdf.String(""), Rect=[20, 20, 200, 50], F=4, DA=da))
    on = pdf.make_stream(b"0 0 1 rg 0 0 20 20 re f")
    agree = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget, FT=pikepdf.Name.Btn,
                                                 T=pikepdf.String("agree"), V=pikepdf.Name.Off, AS=pikepdf.Name.Off,
                                                 Rect=[20, 60, 40, 80], F=4,
                                                 AP=pikepdf.Dictionary(N=pikepdf.Dictionary(Yes=on, Off=pdf.make_stream(b"")))))
    locked_field = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget, FT=pikepdf.Name.Tx,
                                                        T=pikepdf.String("id"), V=pikepdf.String("fixed"), Ff=1,
                                                        Rect=[20, 90, 200, 110], F=4, DA=da))
    first.Annots = pikepdf.Array([name, agree, locked_field])
    kids = []
    for i, state in enumerate(("Red", "Blue")):
        kid = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget, AS=pikepdf.Name.Off,
                                                   Rect=[20 + 40 * i, 20, 40 + 40 * i, 40], F=4,
                                                   AP=pikepdf.Dictionary(N=pikepdf.Dictionary({"/" + state: on, "/Off": pdf.make_stream(b"")}))))
        kids.append(kid)
    colour = pdf.make_indirect(pikepdf.Dictionary(FT=pikepdf.Name.Btn, T=pikepdf.String("colour"), Ff=1 << 15, V=pikepdf.Name.Off,
                                                  Kids=pikepdf.Array(kids)))
    for kid in kids:
        kid.Parent = colour
    size = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget, FT=pikepdf.Name.Ch,
                                                T=pikepdf.String("size"), Ff=1 << 17, V=pikepdf.String("M"),
                                                Opt=pikepdf.Array([pikepdf.Array(["S", "Small"]), pikepdf.Array(["M", "Medium"]),
                                                                   pikepdf.Array(["L", "Large"])]),
                                                Rect=[20, 60, 120, 80], F=4, DA=da))
    second.Annots = pikepdf.Array([*kids, size])
    pdf.Root.AcroForm = pikepdf.Dictionary(Fields=pikepdf.Array([name, agree, locked_field, colour, size]), DA=da,
                                           DR=pikepdf.Dictionary(Font=pikepdf.Dictionary(Helv=font)))
    pdf.save(path)
    return path


def rotated(path: Path, degrees: int = 90) -> Path:
    """A landscape page stored with /Rotate, as scanners and phones make them."""
    pdf = pikepdf.new()
    page = _page(pdf, "Turned page", width=300, height=200)
    page.Rotate = degrees
    pdf.save(path)
    return path


def picture(path: Path, width: int = 120, height: int = 60) -> Path:
    """A small PNG with a transparent corner, for stamps."""
    from PyQt6.QtGui import QColor, QImage, QPainter

    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    painter.fillRect(0, 0, width // 2, height, QColor("#1565C0"))
    painter.fillRect(width // 2, 0, width // 2, height // 2, QColor("#C62828"))
    painter.end()
    image.save(str(path), "PNG")
    return path


def photos(path: Path, width: int = 1600, height: int = 1200) -> Path:
    """A PDF whose pages carry pictures: a colour one with a soft mask (noise, so Flate cannot shrink it), a grey
    one, and a small one that compression must leave alone; the same colour picture is used on both pages."""
    import random
    import zlib

    import pikepdf

    rng = random.Random(7)
    pdf = pikepdf.new()
    big = pdf.make_stream(zlib.compress(rng.randbytes(width * height * 3)), Type=pikepdf.Name.XObject, Subtype=pikepdf.Name.Image,
                          Width=width, Height=height, ColorSpace=pikepdf.Name.DeviceRGB, BitsPerComponent=8, Filter=pikepdf.Name.FlateDecode)
    mask = pdf.make_stream(zlib.compress(bytes((x * 255 // width) for _y in range(height) for x in range(width))),
                           Type=pikepdf.Name.XObject, Subtype=pikepdf.Name.Image, Width=width, Height=height,
                           ColorSpace=pikepdf.Name.DeviceGray, BitsPerComponent=8, Filter=pikepdf.Name.FlateDecode)
    big.SMask = mask
    grey = pdf.make_stream(zlib.compress(rng.randbytes(width * height)), Type=pikepdf.Name.XObject, Subtype=pikepdf.Name.Image,
                           Width=width, Height=height, ColorSpace=pikepdf.Name.DeviceGray, BitsPerComponent=8, Filter=pikepdf.Name.FlateDecode)
    tiny = pdf.make_stream(zlib.compress(rng.randbytes(40 * 30 * 3)), Type=pikepdf.Name.XObject, Subtype=pikepdf.Name.Image,
                           Width=40, Height=30, ColorSpace=pikepdf.Name.DeviceRGB, BitsPerComponent=8, Filter=pikepdf.Name.FlateDecode)
    for pictures in (("/Big", "/Tiny"), ("/Big", "/Grey")):
        content = b"".join(b"q 280 0 0 180 10 %d cm %s Do Q\n" % (y, name.encode()) for y, name in zip((400, 100), pictures))
        page = pikepdf.Dictionary(Type=pikepdf.Name.Page, MediaBox=[0, 0, 300, 600],
                                  Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Big=big, Tiny=tiny, Grey=grey)),
                                  Contents=pdf.make_stream(content))
        pdf.pages.append(pikepdf.Page(page))
    pdf.docinfo["/Title"] = "Photos"
    pdf.save(path)
    return path


def _raw_pdf(objects: list[bytes]) -> bytes:
    """A PDF written by hand: objects 1..n in order, a correct xref, the catalog is object 1."""
    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def openssl_available() -> bool:
    import shutil

    return shutil.which("openssl") is not None


def signed(path: Path, signer: str = "Dana Test", tamper: bool = False, kind: str = "adbe.pkcs7.detached") -> Path:
    """A PDF with one digital signature made by OpenSSL (a self-signed certificate for the tests): the field's
    /ByteRange covers everything but the /Contents hex, which holds the detached CMS signature over those
    bytes. tamper=True appends bytes after signing (what an incremental update does), so the signature still
    matches its ranges but no longer covers the whole file."""
    import subprocess

    work = path.parent / (path.stem + "-keys")
    work.mkdir(exist_ok=True)
    key, cert = work / "key.pem", work / "cert.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(cert),
                    "-days", "2", "-subj", f"/CN={signer}/O=D.Ai tests"], check=True, capture_output=True)
    hole = 8192  # hex characters reserved for the signature
    content = b"BT /F1 18 Tf 20 150 Td (Signed by hand) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R /AcroForm << /Fields [5 0 R] /SigFlags 3 >> >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Contents 4 0 R /Annots [5 0 R] "
        b"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Annot /Subtype /Widget /FT /Sig /T (Signature1) /Rect [20 20 200 60] /P 3 0 R /F 4 /V 6 0 R >>",
        (b"<< /Type /Sig /Filter /Adobe.PPKLite /SubFilter /" + kind.encode() + b" /Name (" + signer.encode() + b") "
         b"/M (D:20261020153000+02'00') /Reason (Approved) /Location (Tel Aviv) "
         b"/ByteRange [0000000000 0000000000 0000000000 0000000000] /Contents <" + b"0" * hole + b"> >>"),
    ]
    data = bytearray(_raw_pdf(objects))
    start = data.index(b"/Contents <") + len("/Contents ")   # the "<"
    end = data.index(b">", start) + 1                          # just after ">"
    ranges = [0, start, end, len(data) - end]
    placeholder = b"/ByteRange [0000000000 0000000000 0000000000 0000000000]"
    replacement = b"/ByteRange [" + b" ".join(b"%010d" % v for v in ranges) + b"]"
    assert len(placeholder) == len(replacement)
    data[data.index(placeholder):data.index(placeholder) + len(placeholder)] = replacement
    signed_bytes = bytes(data[:start]) + bytes(data[end:])
    (work / "signed.bin").write_bytes(signed_bytes)
    subprocess.run(["openssl", "cms", "-sign", "-binary", "-inkey", str(key), "-signer", str(cert), "-in", str(work / "signed.bin"),
                    "-outform", "DER", "-out", str(work / "sig.der"), "-md", "sha256"], check=True, capture_output=True)
    hexsig = (work / "sig.der").read_bytes().hex().encode()
    assert len(hexsig) <= hole, "the signature does not fit the hole"
    data[start + 1:start + 1 + len(hexsig)] = hexsig
    if tamper:
        data += b"\n% a later change\n"
    path.write_bytes(bytes(data))
    return path


def locked(path: Path, password: str = "secret") -> Path:
    pdf = pikepdf.new()
    _page(pdf, "Locked page")
    pdf.save(path, encryption=pikepdf.Encryption(user=password, owner="owner-" + password))
    return path


def not_a_pdf(path: Path) -> Path:
    path.write_bytes(b"%PDF-1.7 looks like one but is not\n" + b"x" * 100)
    return path


def sandbox_works() -> bool:
    """Can bubblewrap make a sandbox here? (CI runners and containers often say no.)"""
    if not shutil.which("bwrap"):
        return False
    try:
        result = subprocess.run(["bwrap", "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin",
                                 "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64", "--proc", "/proc",
                                 "--dev", "/dev", "--unshare-all", "--die-with-parent", "--", "/bin/true"],
                                capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def helper_python() -> str:
    """The Python that runs the helper in tests: this one, with its site-packages (the venv on a developer's
    machine; Debian's on the image and in CI)."""
    return os.environ.get("DAI_PDF_PYTHON") or sys.executable


def helper_binds() -> tuple[str, ...]:
    """Paths the sandboxed helper needs read-only when the test Python is not under /usr (a venv)."""
    prefix = Path(sys.prefix).resolve()
    binds = []
    if not str(prefix).startswith("/usr"):
        binds.append(str(prefix))
    base = Path(sys.base_prefix).resolve()
    if not str(base).startswith("/usr") and base != prefix:
        binds.append(str(base))
    return tuple(binds)
