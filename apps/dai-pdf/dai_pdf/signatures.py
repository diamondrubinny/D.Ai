# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Digital signatures in a PDF (docs/PDF.md stage 4a): listed and checked, never made.

Runs inside the viewing sandbox (the helper calls it at open). For every signature field with a value, the
signed byte ranges are read from the file and the PKCS#7/CMS signature is checked against them with OpenSSL,
on this computer. Two separate facts are reported and never blurred into one "valid":

  intact      the signature matches the bytes it covers (the signed part was not altered)
  covers_all  the signed bytes are the whole file; otherwise something was added after signing (an incremental
              update: a later signature, a filled field, or a change) and the window says so

Who the signer is comes from the certificate inside the signature (its subject) or the field's /Name. Whether
that certificate is trustworthy (a chain to a trusted authority, revocation) is NOT checked here: the window
says the name and that the file is unchanged, nothing more (requires a trust store and a legal review before
D.Ai says "valid"). Nothing leaves the computer.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

MAX_SIGNATURES = 20
MAX_CONTENTS = 1_000_000       # bytes of CMS: a signature is kilobytes; more is not a signature
OPENSSL_TIMEOUT = 20
SUBFILTERS_DETACHED = ("/adbe.pkcs7.detached", "/ETSI.CAdES.detached")


def _text(value) -> str:
    try:
        return str(value)
    except Exception:  # noqa: BLE001 - a broken string is no name
        return ""


def pdf_date(value: str) -> str:
    """D:20261020153000+02'00' → 2026-10-20 15:30 (what is there; the offset is kept when present)."""
    m = re.match(r"D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?([Zz+-])?(\d{2})?'?(\d{2})?", value or "")
    if not m:
        return value or ""
    year, month, day, hour, minute = m.group(1), m.group(2) or "01", m.group(3) or "01", m.group(4) or "00", m.group(5) or "00"
    out = f"{year}-{month}-{day} {hour}:{minute}"
    if m.group(7) in ("+", "-") and m.group(8):
        out += f" {m.group(7)}{m.group(8)}:{m.group(9) or '00'}"
    elif m.group(7) in ("Z", "z"):
        out += " UTC"
    return out


def _fields(pdf):
    """Every terminal form field, with /FT inherited from its parents (pikepdf gives the tree raw)."""
    try:
        roots = list(pdf.Root.AcroForm.Fields)
    except (AttributeError, KeyError, TypeError):
        return
    seen = 0
    stack = [(f, None) for f in roots]
    while stack and seen < 5000:
        field, inherited = stack.pop()
        seen += 1
        try:
            kind = field.get("/FT", inherited)
            kids = field.get("/Kids")
        except Exception:  # noqa: BLE001
            continue
        if kids is not None:
            stack.extend((k, kind) for k in kids)
        else:
            yield field, kind


def _subject_cn(openssl_out: str) -> str:
    """CN = Dana Test, O = … → Dana Test (the first subject line, the first certificate)."""
    for line in openssl_out.splitlines():
        if line.startswith("subject="):
            m = re.search(r"CN\s*=\s*([^,/]+)", line)
            return (m.group(1) if m else line[len("subject="):]).strip()
    return ""


def _openssl(argv: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["openssl", *argv], capture_output=True, text=True, timeout=OPENSSL_TIMEOUT, cwd=cwd, check=False,
                          env={"PATH": "/usr/bin:/bin", "LANG": "C"})


def der_trim(contents: bytes) -> bytes:
    """The DER object at the start of /Contents, without the zero padding PDF writers add after it.

    Stripping every trailing zero byte is wrong once in a while: a signature or certificate can itself end
    with 0x00, and then the DER came back one byte short and a sound signature read as broken.
    """
    if len(contents) >= 2 and contents[0] == 0x30:
        first = contents[1]
        if first < 0x80:
            length, header = first, 2
        else:
            count = first & 0x7F
            if 0 < count <= 4 and len(contents) >= 2 + count:
                length, header = int.from_bytes(contents[2:2 + count], "big"), 2 + count
            else:
                return contents.rstrip(b"\0")
        if header + length <= len(contents):
            return contents[:header + length]
    return contents.rstrip(b"\0")


def verify(path: str, byte_range: list[int], contents: bytes, subfilter: str) -> dict:
    """{"status": "intact" | "broken" | "unchecked", "why": "", "signer": "", "covers_all": bool}."""
    out: dict = {"status": "unchecked", "why": "", "signer": "", "covers_all": False}
    size = os.path.getsize(path)
    if len(byte_range) != 4 or any(v < 0 for v in byte_range) or byte_range[0] + byte_range[1] > byte_range[2] \
            or byte_range[2] + byte_range[3] > size:
        out["why"] = "the signed byte ranges do not fit the file"
        return out
    out["covers_all"] = byte_range[0] == 0 and byte_range[2] + byte_range[3] == size
    if subfilter not in SUBFILTERS_DETACHED:
        out["why"] = f"the signature kind {subfilter.lstrip('/') or '?'} is not checked here"
    with tempfile.TemporaryDirectory(prefix="dai-pdf-sig-") as tmp:
        sig = Path(tmp) / "sig.der"
        sig.write_bytes(der_trim(contents))
        certs = _openssl(["pkcs7", "-inform", "DER", "-in", str(sig), "-print_certs", "-noout"], tmp)
        out["signer"] = _subject_cn(certs.stdout) if certs.returncode == 0 else ""
        if out["why"]:
            return out
        data = Path(tmp) / "signed.bin"
        with open(path, "rb") as source, open(data, "wb") as target:
            for start, length in ((byte_range[0], byte_range[1]), (byte_range[2], byte_range[3])):
                source.seek(start)
                target.write(source.read(length))
        check = _openssl(["cms", "-verify", "-binary", "-inform", "DER", "-in", str(sig), "-content", str(data),
                          "-noverify", "-out", os.devnull], tmp)
        if check.returncode == 0:
            out["status"] = "intact"
        else:
            out["status"] = "broken"
            out["why"] = (check.stderr.strip().splitlines() or ["the signature does not match the signed bytes"])[-1][:200]
    return out


def scan(pdf, path: str) -> list[dict]:
    """The file's signatures, oldest first as the fields come, each checked. An empty list for an unsigned file."""
    found: list[dict] = []
    for field, kind in _fields(pdf):
        if _text(kind) != "/Sig":
            continue
        try:
            value = field.get("/V")
            if value is None or not hasattr(value, "get"):
                continue
            contents = bytes(value.get("/Contents", b""))
            byte_range = [int(v) for v in (value.get("/ByteRange") or [])]
            entry = {"field": _text(field.get("/T", "")), "name": _text(value.get("/Name", "")),
                     "date": pdf_date(_text(value.get("/M", ""))), "reason": _text(value.get("/Reason", "")),
                     "location": _text(value.get("/Location", "")), "kind": _text(value.get("/SubFilter", ""))}
        except Exception:  # noqa: BLE001 - a broken field is reported, not fatal
            found.append({"field": "?", "name": "", "date": "", "reason": "", "location": "", "kind": "",
                          "status": "unchecked", "why": "the signature could not be read", "signer": "", "covers_all": False})
            continue
        if not contents or len(contents) > MAX_CONTENTS:
            entry.update(status="unchecked", why="no signature data", signer="", covers_all=False)
        else:
            try:
                entry.update(verify(path, byte_range, contents, entry["kind"]))
            except (OSError, subprocess.TimeoutExpired) as exc:
                entry.update(status="unchecked", why=f"OpenSSL could not run ({type(exc).__name__})", signer="", covers_all=False)
        entry["signer"] = entry["signer"] or entry["name"]
        found.append(entry)
        if len(found) >= MAX_SIGNATURES:
            break
    return found
