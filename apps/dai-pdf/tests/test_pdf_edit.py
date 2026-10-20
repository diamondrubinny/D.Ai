# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Editing (dai_pdf/edit.py, docs/PDF.md stage 2): pages reordered, rotated, deleted, inserted from another
file, merged and split; forms listed, filled and flattened; the result written only after the sandboxed editor
finished; the same through bubblewrap where the machine allows it."""
import os
import tempfile
import unittest
from pathlib import Path

from . import fixtures

fixtures.need_libraries()

import pikepdf  # noqa: E402

from dai_pdf import edit, sandbox  # noqa: E402
from dai_pdf.edit import EditError, Editor, parse_pages  # noqa: E402


def sizes(path: Path) -> list[tuple[float, int]]:
    with pikepdf.open(path) as pdf:
        return [(float(p.MediaBox[2]), int(p.obj.get("/Rotate", 0))) for p in pdf.pages]


class DirectEditTests(unittest.TestCase):
    """The functions themselves, in this process (the sandbox is the same code with a different command line)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.editor = Editor(sandboxed=False, python=fixtures.helper_python())

    def test_pages_reordered_rotated_deleted_and_inserted(self):
        a = fixtures.plain(self.dir / "a.pdf", pages=3)
        b = fixtures.with_outline(self.dir / "b.pdf")
        out = self.dir / "out.pdf"
        answer = self.editor.save([str(a), str(b)], str(out), pages=[
            {"source": 0, "index": 2, "rotate": 90}, {"source": 1, "index": 4, "rotate": 0}, {"source": 0, "index": 0, "rotate": 270}])
        self.assertEqual(answer["pages"], 3)
        self.assertEqual([r for _, r in sizes(out)], [90, 0, 270])
        with pikepdf.open(out) as pdf:
            self.assertEqual(len(pdf.pages), 3)
            texts = [bytes(p.Contents.read_bytes()) for p in pdf.pages]
        self.assertIn(b"Hello D.Ai page 3", texts[0])
        self.assertIn(b"Chapter 5", texts[1])
        self.assertIn(b"Hello D.Ai page 1", texts[2])
        self.assertEqual(oct(out.stat().st_mode & 0o777), "0o600")

    def test_bad_pages_and_missing_files_are_refused_and_nothing_is_written(self):
        a = fixtures.plain(self.dir / "a.pdf", pages=2)
        out = self.dir / "out.pdf"
        with self.assertRaises(EditError) as caught:
            self.editor.save([str(a)], str(out), pages=[{"source": 0, "index": 7, "rotate": 0}])
        self.assertEqual(caught.exception.kind, "bad request")
        self.assertFalse(out.exists())
        with self.assertRaises(EditError) as caught:
            self.editor.save([str(self.dir / "nothing.pdf")], str(out), pages=[])
        self.assertEqual(caught.exception.kind, "missing")
        with self.assertRaises(EditError) as caught:
            self.editor.save([str(fixtures.not_a_pdf(self.dir / "x.pdf"))], str(out), pages=None)
        self.assertEqual(caught.exception.kind, "broken")
        self.assertFalse(out.exists())
        self.assertEqual(os.listdir(self.dir), ["a.pdf", "x.pdf"])  # no leftover temp files beside the inputs

    def test_a_locked_file_needs_its_password(self):
        locked = fixtures.locked(self.dir / "l.pdf", "secret")
        out = self.dir / "out.pdf"
        with self.assertRaises(EditError) as caught:
            self.editor.save([str(locked)], str(out), pages=[{"source": 0, "index": 0, "rotate": 180}])
        self.assertEqual(caught.exception.kind, "password")
        self.editor.save([str(locked)], str(out), pages=[{"source": 0, "index": 0, "rotate": 180}], passwords=["secret"])
        self.assertEqual(sizes(out), [(300.0, 180)])

    def test_fields_are_listed_filled_and_flattened(self):
        form = fixtures.form(self.dir / "f.pdf")
        fields = self.editor.fields(str(form))
        self.assertEqual([(f["name"], f["kind"], f["page"]) for f in fields],
                         [("name", "text", 0), ("agree", "checkbox", 0), ("id", "text", 0), ("colour", "radio", 1), ("size", "choice", 1)])
        self.assertEqual(fields[1]["value"], False)
        self.assertTrue(fields[2]["readonly"])
        self.assertEqual(fields[3]["options"], ["Red", "Blue"])
        self.assertEqual(fields[4]["options"], [["S", "Small"], ["M", "Medium"], ["L", "Large"]])
        self.assertEqual(fields[4]["value"], "M")
        out = self.dir / "filled.pdf"
        answer = self.editor.save([str(form)], str(out), fields={"name": "Dana שלום", "agree": True, "id": "hacked",
                                                                 "colour": "Blue", "size": "L", "nobody": "x"})
        self.assertEqual(answer["filled"], 4)  # id is read-only, nobody does not exist
        after = {f["name"]: f["value"] for f in self.editor.fields(str(out))}
        self.assertEqual(after, {"name": "Dana שלום", "agree": True, "id": "fixed", "colour": "Blue", "size": "L"})
        with pikepdf.open(out) as pdf:
            kids = pdf.Root.AcroForm.Fields[3].Kids
            self.assertEqual([str(k.AS) for k in kids], ["/Off", "/Blue"])
            self.assertEqual(str(pdf.Root.AcroForm.Fields[1].AS), "/Yes")
        flat = self.dir / "flat.pdf"
        self.editor.save([str(out)], str(flat), flatten=True)
        self.assertEqual(self.editor.fields(str(flat)), [])  # baked in: nothing left to fill
        with pikepdf.open(flat) as pdf:
            self.assertEqual(len(pdf.pages), 2)
            self.assertNotIn("/AcroForm", pdf.Root)

    def test_fill_then_reorder_in_one_save(self):
        form = fixtures.form(self.dir / "f.pdf")
        out = self.dir / "out.pdf"
        self.editor.save([str(form)], str(out), pages=[{"source": 0, "index": 1, "rotate": 0}], fields={"size": "S"})
        self.assertEqual([(f["name"], f["value"]) for f in self.editor.fields(str(out)) if f["page"] == 0], [("colour", "Off"), ("size", "S")])

    def test_page_ranges(self):
        self.assertEqual(parse_pages("", 4), [0, 1, 2, 3])
        self.assertEqual(parse_pages("1-2, 4", 4), [0, 1, 3])
        self.assertEqual(parse_pages("3-", 4), [2, 3])
        self.assertEqual(parse_pages("-2", 4), [0, 1])
        for bad in ("0", "5", "3-2", "x"):
            with self.assertRaises(ValueError):
                parse_pages(bad, 4)

    def test_the_editor_command_line_binds_only_what_it_needs(self):
        argv = sandbox.edit_argv(["/home/dana/a.pdf", "/home/dana/b.pdf"], "/tmp/outdir", "/usr/bin/python3")
        self.assertIn("--unshare-all", argv)
        self.assertEqual(argv[argv.index("--ro-bind", argv.index("--tmpfs")) + 1:][:2], [sandbox.package_dir(), sandbox.package_dir()])
        self.assertIn("/tmp/in/1.pdf", argv)
        self.assertEqual(argv[argv.index("--bind") + 1:argv.index("--bind") + 3], ["/tmp/outdir", "/tmp/out"])
        self.assertNotIn("--bind /home", " ".join(argv))
        self.assertEqual(argv[-4:], [sandbox.package_dir(), "/tmp/in", "/tmp/out", "2"])


@unittest.skipUnless(fixtures.sandbox_works(), "bubblewrap cannot make a sandbox here")
class SandboxedEditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.editor = Editor(sandboxed=True, python=fixtures.helper_python(), binds=fixtures.helper_binds())

    def test_merge_and_fill_inside_bubblewrap(self):
        a = fixtures.plain(self.dir / "a.pdf", pages=2)
        form = fixtures.form(self.dir / "f.pdf")
        out = self.dir / "merged.pdf"
        answer = self.editor.save([str(form), str(a)], str(out), pages=[
            {"source": 0, "index": 0, "rotate": 0}, {"source": 1, "index": 1, "rotate": 90}, {"source": 0, "index": 1, "rotate": 0}],
            fields={"name": "Sandboxed"})
        self.assertEqual(answer["pages"], 3)
        self.assertEqual([f["value"] for f in self.editor.fields(str(out)) if f["name"] == "name"], ["Sandboxed"])
        self.assertEqual([r for _, r in sizes(out)], [0, 90, 0])


if __name__ == "__main__":
    unittest.main()
