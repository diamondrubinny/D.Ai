# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The helper and the reader (dai_pdf/helper.py, reader.py): pages, text, links, search rectangles, outline,
passwords, broken files, a helper that dies, and the real sandbox with its memory limit where bubblewrap works."""
import os
import signal
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from . import fixtures

fixtures.need_libraries()

from dai_pdf import sandbox  # noqa: E402
from dai_pdf.reader import PdfError, Reader  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n"


def reader(path, password="", sandboxed=False):
    return Reader(str(path), password=password, sandboxed=sandboxed, python=fixtures.helper_python(),
                  binds=fixtures.helper_binds())


class DirectReaderTests(unittest.TestCase):
    """The helper outside the sandbox: what it answers (the sandbox only wraps the same process)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def open(self, path, **kwargs):
        r = reader(path, **kwargs)
        self.addCleanup(r.close)
        return r, r.open()

    def test_pages_text_links_and_rectangles(self):
        r, doc = self.open(fixtures.active(self.dir / "a.pdf"))
        self.assertEqual(doc.count, 1)
        self.assertEqual(doc.pages, [(300.0, 200.0)])
        png, w, h = r.render(0, 600, 400)
        self.assertEqual((png[:8], w, h), (PNG, 600, 400))
        self.assertEqual(r.text(0), "Careful: this file wants things")
        links = r.links(0)
        # the GoToR link comes out as a file: address: the window refuses those (test_pdf_gui)
        self.assertEqual([link["url"] for link in links if link["url"]], ["https://example.com/x", "file:other.pdf"])
        self.assertEqual(links[0]["rect"][0], 20.0)
        rects = r.select(0, 0, 7)  # "Careful"
        self.assertEqual(len(rects), 1)
        self.assertGreater(rects[0][2], 10)
        self.assertEqual(r.select(0, 10_000, 5), [])
        self.assertEqual(doc.findings.launch, 1)
        self.assertTrue(doc.inspected)

    def test_metadata_outline_and_labels(self):
        r, doc = self.open(fixtures.with_outline(self.dir / "o.pdf"))
        self.assertEqual(doc.count, 5)
        self.assertEqual([(e["title"], e["page"], e["level"]) for e in doc.outline],
                         [("Part one", 0, 0), ("Chapter 2", 1, 1), ("Part two", 3, 0)])
        _, plain = self.open(fixtures.plain(self.dir / "p.pdf"))
        self.assertEqual((plain.metadata["title"], plain.metadata["author"]), ("A plain file", "Dana"))
        self.assertEqual(plain.title, "A plain file")

    def test_a_bad_page_number_is_an_error_not_a_crash(self):
        r, _ = self.open(fixtures.plain(self.dir / "p.pdf"))
        with self.assertRaises(PdfError) as caught:
            r.render(7, 10, 10)
        self.assertEqual(caught.exception.kind, "page")
        self.assertEqual(r.text(0), "Hello D.Ai page 1")  # the helper is still there
        self.assertEqual(r.restarts, 0)

    def test_locked_files(self):
        path = fixtures.locked(self.dir / "l.pdf")
        with self.assertRaises(PdfError) as caught:
            reader(path).open()
        self.assertEqual(caught.exception.kind, "password")
        r, doc = self.open(path, password="secret")
        self.assertEqual((doc.count, doc.findings.encrypted), (1, True))
        self.assertEqual(r.text(0), "Locked page")

    def test_broken_and_missing(self):
        with self.assertRaises(PdfError) as caught:
            reader(fixtures.not_a_pdf(self.dir / "x.pdf")).open()
        self.assertEqual(caught.exception.kind, "broken")
        with self.assertRaises(PdfError) as caught:
            reader(self.dir / "none.pdf").open()
        self.assertEqual(caught.exception.kind, "missing")

    def test_a_helper_that_died_is_started_again(self):
        r, _ = self.open(fixtures.plain(self.dir / "p.pdf", pages=2))
        os.kill(r.proc.pid, signal.SIGKILL)
        r.proc.wait(timeout=5)
        self.assertEqual(r.text(1), "Hello D.Ai page 2")
        self.assertEqual(r.restarts, 1)
        png, _, _ = r.render(1, 30, 20)
        self.assertEqual(png[:8], PNG)

    def test_the_window_refuses_without_bubblewrap(self):
        with mock.patch("dai_pdf.sandbox.shutil.which", return_value=None):
            with self.assertRaises(PdfError) as caught:
                Reader(str(fixtures.plain(self.dir / "p.pdf")), sandboxed=True).open()
        self.assertEqual(caught.exception.kind, "sandbox")

    def test_text_is_made_readable_unless_asked_raw(self):
        r, _ = self.open(fixtures.plain(self.dir / "p.pdf"))
        r.document.texts[0] = "םולש"  # as if the file stored it mirrored
        self.assertEqual(r.text(0), "שלום")
        self.assertEqual(r.text(0, as_extracted=True), "םולש")


class SandboxArgvTests(unittest.TestCase):
    def test_the_sandbox_has_no_network_no_home_and_the_file_read_only(self):
        argv = sandbox.argv("/home/dana/secret.pdf")
        self.assertIn("--unshare-all", argv)
        self.assertIn("--clearenv", argv)
        self.assertIn("--die-with-parent", argv)
        self.assertEqual(argv[argv.index("--ro-bind", argv.index("/home/dana/secret.pdf") - 1) + 2], "/tmp/document.pdf")
        self.assertNotIn("--bind", argv)                       # nothing writable from outside
        self.assertNotIn("/home", [a for a in argv if a != "/home/dana/secret.pdf"])
        self.assertIn(f"--data={sandbox.MEMORY}", argv)
        self.assertIn(f"--cpu={sandbox.CPU_SECONDS}", argv)
        self.assertEqual(argv[-1], "/tmp/document.pdf")        # the helper sees the file only under its new name


@unittest.skipUnless(fixtures.sandbox_works(), "bubblewrap cannot make a sandbox here")
class RealSandboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_the_same_answers_from_inside_the_sandbox(self):
        r = reader(fixtures.active(self.dir / "a.pdf"), sandboxed=True)
        self.addCleanup(r.close)
        doc = r.open()
        self.assertEqual((doc.count, doc.findings.javascript, [a["name"] for a in doc.findings.attachments]),
                         (1, 2, ["evil.exe", "notes.txt"]))
        png, w, h = r.render(0, 300, 200)
        self.assertEqual((png[:8], w, h), (PNG, 300, 200))
        self.assertEqual(r.text(0), "Careful: this file wants things")
        self.assertEqual(r.links(0)[0]["url"], "https://example.com/x")

    def test_the_memory_limit_stops_a_huge_page_and_the_helper_goes_on(self):
        with mock.patch.object(sandbox, "MEMORY", 160 * 1024 * 1024):
            r = reader(fixtures.plain(self.dir / "p.pdf"), sandboxed=True)
            self.addCleanup(r.close)
            r.open()
            with self.assertRaises(PdfError) as caught:
                r.render(0, 7000, 7000)  # 196 MB of pixels: refused by PDFium, or the helper killed; either way
            self.assertEqual(caught.exception.kind, "page")
            png, _, _ = r.render(0, 300, 200)
            self.assertEqual(png[:8], PNG)
            self.assertLessEqual(r.restarts, 1)


if __name__ == "__main__":
    unittest.main()
