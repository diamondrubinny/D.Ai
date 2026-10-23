# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Pictures in Diamond Chat (docs/SEND.md §3, "Pictures"): re-drawn, in a sandbox, before they go anywhere.

Every picture, the one you send and the one you receive, is decoded and encoded again as new pixels:

  - what a photo says about you goes: the place (GPS), the camera, the date, the thumbnail, any comment;
  - what a malicious file could carry goes too: only pixels come out, in a fresh PNG or JPEG;
  - the decoder (Qt's, from Debian) runs in bubblewrap with no network, no home folder, no device, read-only
    /usr, and limits on memory and time: a bug in a decoder stays inside;
  - it reads only the type the first bytes say (PNG, JPEG or WebP): never SVG or PDF, whatever the name;
  - large pictures are made at most 4096 pixels on their long side, and EXIF rotation is applied first.

When the ClamAV daemon is installed (a D.Ai Forge recipe), a received picture is scanned before all this.
"""
from __future__ import annotations

import shutil
import subprocess
from typing import Callable

from .message import MAX_PICTURE, sniff

MAX_SIDE = 4096
TIMEOUT = 30
MEMORY = 1024 * 1024 * 1024  # bytes of address space for the decoder

Run = Callable[..., subprocess.CompletedProcess]

# Runs inside the sandbox: the picture on stdin, "PNG\n" or "JPEG\n" and the new picture on stdout.
DECODER = r"""
import sys
from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PyQt6.QtGui import QGuiApplication, QImage, QImageReader

app = QGuiApplication(["dai-chat-picture"])
kind, side = sys.argv[1].encode(), int(sys.argv[2])
source = QBuffer()
source.setData(QByteArray(sys.stdin.buffer.read()))
source.open(QIODevice.OpenModeFlag.ReadOnly)
reader = QImageReader(source, kind)
reader.setDecideFormatFromContent(False)
reader.setAutoTransform(True)
QImageReader.setAllocationLimit(512)
image = reader.read()
if image.isNull():
    sys.exit(3)
# Only pixels come out: a QImage read from a file carries its text chunks (PNG tEXt/iTXt, JPEG comments) and
# would write them back; an image built from the raw bits carries none.
bits = image.constBits()
bits.setsize(image.sizeInBytes())
image = QImage(bytes(bits), image.width(), image.height(), image.bytesPerLine(), image.format()).copy()
if max(image.width(), image.height()) > side:
    image = image.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
out_kind = "PNG" if image.hasAlphaChannel() else "JPEG"
target = QBuffer()
target.open(QIODevice.OpenModeFlag.WriteOnly)
if not image.save(target, out_kind, -1 if out_kind == "PNG" else 88):
    sys.exit(4)
sys.stdout.buffer.write(out_kind.encode() + b"\n" + bytes(target.data()))
"""

READERS = {"image/png": "png", "image/jpeg": "jpeg", "image/webp": "webp"}


class PictureError(ValueError):
    """Not a picture we take, too large, infected, or the decoder failed."""


def sandbox_argv(kind: str, python: str = "/usr/bin/python3", binds: tuple[str, ...] = ()) -> list[str]:
    """`python` and `binds` (read-only) are for tests with another Python; D.Ai uses Debian's."""
    extra = [arg for path in binds for arg in ("--ro-bind", path, path)]
    return [
        "bwrap",
        "--ro-bind", "/usr", "/usr",
        "--symlink", "usr/bin", "/bin",
        "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib64", "/lib64",
        "--ro-bind-try", "/etc/fonts", "/etc/fonts",
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        *extra,
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        "--cap-drop", "ALL",
        "--clearenv",
        "--setenv", "HOME", "/tmp",
        "--setenv", "QT_QPA_PLATFORM", "offscreen",
        "--setenv", "XDG_RUNTIME_DIR", "/tmp",
        "--",
        "prlimit", f"--as={MEMORY}", f"--cpu={TIMEOUT}", "--nofile=64", "--",
        python, "-I", "-c", DECODER, kind, str(MAX_SIDE),
    ]


def scan(data: bytes, run: Run = subprocess.run) -> None:
    """ClamAV, when its daemon is installed: an infected picture is refused (nothing of it is kept)."""
    if not shutil.which("clamdscan"):
        return
    try:
        result = run(["clamdscan", "--no-summary", "--stdout", "-"], input=data, capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return  # the daemon is not running: the sandboxed re-drawing still protects
    if result.returncode == 1:
        raise PictureError("ClamAV found something in this picture")


def clean(data: bytes, run: Run = subprocess.run, scan_first: bool = False,
          sandbox: Callable[[str], list[str]] = sandbox_argv) -> tuple[bytes, str]:
    """The picture re-drawn: (new bytes, "image/png" or "image/jpeg")."""
    if not data or len(data) > MAX_PICTURE:
        raise PictureError("the picture is empty or larger than 25 MB")
    mime = sniff(data)
    if mime not in READERS:
        raise PictureError("not a PNG, JPEG or WebP picture")
    if scan_first:
        scan(data, run)
    if not shutil.which("bwrap"):
        raise PictureError("bubblewrap is missing: pictures are never opened outside the sandbox")
    try:
        result = run(sandbox(READERS[mime]), input=data, capture_output=True, timeout=TIMEOUT + 10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PictureError("the picture could not be read") from exc
    head, _, body = result.stdout.partition(b"\n")
    if result.returncode != 0 or head not in (b"PNG", b"JPEG") or not body:
        raise PictureError("the picture could not be read")
    new_mime = "image/png" if head == b"PNG" else "image/jpeg"
    if sniff(body) != new_mime or len(body) > MAX_PICTURE:
        raise PictureError("the picture could not be read")
    return body, new_mime
