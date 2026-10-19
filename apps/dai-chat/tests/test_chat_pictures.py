# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Pictures are re-drawn in a sandbox (dai_chat/pictures.py): what is refused before anything runs, what the
sandbox may not reach, ClamAV, and with bubblewrap and PyQt6 present, the real thing: a hidden location
removed, a large photo made smaller, something hidden after the picture dropped, a decompression bomb, SVG.

DAI_TEST_PYTHON may name a Python with PyQt6 (a venv) when the system one has none."""
import importlib.util
import os
import struct
import subprocess
import unittest
import zlib
from unittest import mock

if importlib.util.find_spec("nacl") is None:  # python3-nacl, in Debian
    raise unittest.SkipTest("PyNaCl is missing")

from dai_chat import message, pictures

PYTHON = os.environ.get("DAI_TEST_PYTHON", "/usr/bin/python3")
BINDS = (os.path.dirname(os.path.dirname(PYTHON)),) if "DAI_TEST_PYTHON" in os.environ else ()


def _png(width, height, color=2, depth=8, rows=None):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    channels = {0: 1, 2: 3, 6: 4}[color] if depth == 8 else 1
    row = b"\x00" + b"\x80" * (width * channels if depth == 8 else (width + 7) // 8)
    raw = zlib.compress(rows if rows is not None else row * height, 9)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, color, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def _works() -> bool:
    try:
        sandboxed = subprocess.run(["bwrap", "--unshare-all", "--ro-bind", "/usr", "/usr", "--symlink", "usr/lib",
                                    "/lib", "--symlink", "usr/lib64", "/lib64", "/usr/bin/true"], timeout=20)
        qt = subprocess.run([PYTHON, "-c", "import PyQt6.QtGui"], timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return sandboxed.returncode == 0 and qt.returncode == 0


def sandbox(kind):
    return pictures.sandbox_argv(kind, PYTHON, BINDS)


class BeforeAnythingRunsTests(unittest.TestCase):
    def test_refused_without_running_the_decoder(self):
        never = mock.Mock(side_effect=AssertionError("the decoder must not run"))
        for bad in (b"", b"<svg onload='x'/>", b"%PDF-1.7", b"GIF89a", b"\x89PNG\r\n\x1a\n" * 4_000_000):
            with self.assertRaises(pictures.PictureError):
                pictures.clean(bad, run=never)

    def test_the_sandbox_reaches_nothing(self):
        argv = pictures.sandbox_argv("png")
        self.assertEqual(argv[0], "bwrap")
        for flag in ("--unshare-all", "--die-with-parent", "--clearenv", "--new-session"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--cap-drop") + 1], "ALL")
        binds = [argv[i + 1] for i, a in enumerate(argv) if a in ("--bind", "--ro-bind", "--ro-bind-try")]
        self.assertEqual(binds, ["/usr", "/etc/fonts"])  # no home folder, nothing writable
        self.assertIn("prlimit", argv)
        self.assertIn("png", argv[argv.index("-c") + 2:])  # the reader is the sniffed type, never guessed

    def test_what_comes_out_is_checked_too(self):
        lies = subprocess.CompletedProcess([], 0, b"PNG\n<script>", b"")
        with mock.patch("shutil.which", return_value="/usr/bin/bwrap"), self.assertRaises(pictures.PictureError):
            pictures.clean(_png(4, 4), run=lambda *a, **k: lies)

    def test_clamav_when_installed(self):
        infected = subprocess.CompletedProcess([], 1, b"stream: Eicar FOUND", b"")
        with mock.patch("shutil.which", return_value="/usr/bin/clamdscan"), self.assertRaises(pictures.PictureError):
            pictures.scan(_png(4, 4), run=lambda *a, **k: infected)
        with mock.patch("shutil.which", return_value=None):
            pictures.scan(_png(4, 4), run=mock.Mock(side_effect=AssertionError))  # not installed: skipped


@unittest.skipUnless(_works(), "bubblewrap or PyQt6 is not usable here")
class RealSandboxTests(unittest.TestCase):
    def jpeg_with_location(self, width=600, height=400):
        out, mime = pictures.clean(_png(width, height, color=2), sandbox=sandbox)
        self.assertEqual(mime, "image/jpeg")
        payload = b"Exif\x00\x00GPSLatitude=32.0853 SECRET-PLACE"
        return out[:2] + b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload + out[2:]

    def test_the_location_goes(self):
        photo = self.jpeg_with_location()
        self.assertIn(b"SECRET-PLACE", photo)
        out, mime = pictures.clean(photo, sandbox=sandbox)
        self.assertEqual(mime, "image/jpeg")
        self.assertNotIn(b"SECRET-PLACE", out)
        self.assertNotIn(b"Exif", out)

    def test_large_photos_are_made_smaller(self):
        out, _ = pictures.clean(_png(5000, 200, color=2), sandbox=sandbox)
        width, height = struct.unpack(">HH", out[out.index(b"\xff\xc0") + 5:out.index(b"\xff\xc0") + 9])[::-1]
        self.assertEqual(width, 4096)
        self.assertIn(height, (163, 164))  # 200 * 4096 / 5000 = 163.84

    def test_something_hidden_after_the_picture_is_dropped(self):
        out, mime = pictures.clean(_png(32, 32, color=6) + b"#!/bin/sh\nrm -rf ~\n", sandbox=sandbox)
        self.assertEqual(mime, "image/png")  # transparency kept: still a PNG
        self.assertNotIn(b"rm -rf", out)
        self.assertEqual(message.sniff(out), "image/png")

    def test_a_decompression_bomb(self):
        width = height = 20000  # 50 KB on disk, 1.6 GB of pixels
        row = b"\x00" + b"\x00" * ((width + 7) // 8)
        bomb = _png(width, height, color=0, depth=1, rows=row * height)
        self.assertLess(len(bomb), 200_000)
        with self.assertRaises(pictures.PictureError):
            pictures.clean(bomb, sandbox=sandbox)


if __name__ == "__main__":
    unittest.main()
