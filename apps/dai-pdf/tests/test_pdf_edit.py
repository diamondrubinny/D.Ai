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
        self.assertEqual(sorted(os.listdir(self.dir)), ["a.pdf", "x.pdf"])  # no leftover temp files beside the inputs

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

    def test_marks_become_annotations_and_pictures(self):
        """docs/PDF.md stage 2b: markup as real annotations, text and stamps drawn into the page, a page's own
        /Rotate honoured, bad requests refused."""
        import os as _os
        _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        a = fixtures.plain(self.dir / "a.pdf", pages=2)
        logo = fixtures.picture(self.dir / "logo.png")
        out = self.dir / "marked.pdf"
        answer = self.editor.save([str(a)], str(out), annotations=[
            {"page": 0, "kind": "highlight", "rect": [20, 80, 150, 30], "color": "#FFEB3B"},
            {"page": 0, "kind": "underline", "rect": [20, 80, 150, 30], "color": "#1565C0"},
            {"page": 1, "kind": "strikeout", "rect": [20, 80, 100, 30], "color": "#C62828", "text": "wrong"},
            {"page": 1, "kind": "note", "rect": [250, 10, 20, 20], "color": "#FFEB3B", "text": "שימו לב"},
            {"page": 0, "kind": "text", "rect": [10, 140, 200, 40], "color": "#111111", "text": "שלום עולם, hello", "size": 14},
            {"page": 1, "kind": "stamp", "rect": [200, 120, 80, 40], "image": 0}], pictures=[str(logo)])
        self.assertEqual(answer["marked"], 6)
        with pikepdf.open(out) as pdf:
            first, second = pdf.pages[0], pdf.pages[1]
            kinds = [str(x.Subtype) for x in first.Annots]
            self.assertEqual(kinds, ["/Highlight", "/Underline"])
            rect = [float(v) for v in first.Annots[0].Rect]
            self.assertEqual(rect, [20.0, 90.0, 170.0, 120.0])  # top 80 on a 200 pt page: PDF y from 90 to 120
            self.assertEqual([float(v) for v in first.Annots[0].C], [1.0, 0.9216, 0.2314])
            self.assertEqual([str(x.Subtype) for x in second.Annots], ["/StrikeOut", "/Text"])
            self.assertEqual(str(second.Annots[1].Contents), "שימו לב")
            self.assertIn("DaiImg", str(first.Resources.XObject.keys()))
            self.assertIn(b"/DaiImg", b"".join(c.read_bytes() for c in (first.Contents if isinstance(first.Contents, pikepdf.Array) else [first.Contents])))
            stamp = second.Resources.XObject[[k for k in second.Resources.XObject.keys() if k.startswith("/DaiImg")][0]]
            self.assertEqual((int(stamp.Width), int(stamp.Height)), (120, 60))
            self.assertIn("/SMask", stamp)
        # the saved file still renders in the sandboxed reader, with the marks on it (the Annotations flag)
        from dai_pdf.reader import Reader
        reader = Reader(str(out), sandboxed=False, python=fixtures.helper_python())
        reader.open()
        png, _, _ = reader.render(0, 300, 200)
        reader.close()
        self.assertTrue(png.startswith(b"\x89PNG"))
        for bad in ({"page": 5, "kind": "note", "rect": [0, 0, 10, 10]}, {"page": 0, "kind": "glitter", "rect": [0, 0, 10, 10]},
                    {"page": 0, "kind": "highlight", "rect": [0, 0, 0, 10]}, {"page": 0, "kind": "stamp", "rect": [0, 0, 10, 10], "image": 3}):
            with self.assertRaises(EditError):
                self.editor.save([str(a)], str(self.dir / "x.pdf"), annotations=[bad], pictures=[str(logo)])
        self.assertFalse((self.dir / "x.pdf").exists())

    def test_marks_follow_a_turned_page(self):
        import os as _os
        _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        turned = fixtures.rotated(self.dir / "r.pdf", 90)  # 300x200 stored, shown as 200 wide x 300 tall
        out = self.dir / "out.pdf"
        # the top-left corner of the page as displayed is the bottom-left corner of the stored page
        self.editor.save([str(turned)], str(out), annotations=[{"page": 0, "kind": "highlight", "rect": [0, 0, 50, 20]}])
        with pikepdf.open(out) as pdf:
            rect = [float(v) for v in pdf.pages[0].Annots[0].Rect]
        self.assertEqual(rect, [0.0, 0.0, 20.0, 50.0])
        # and a new turn on top (the plan's rotate) is applied after the mark was placed
        self.editor.save([str(turned)], str(out), pages=[{"source": 0, "index": 0, "rotate": 90}],
                         annotations=[{"page": 0, "kind": "highlight", "rect": [0, 0, 50, 20]}])
        with pikepdf.open(out) as pdf:
            self.assertEqual(int(pdf.pages[0].Rotate), 180)
            self.assertEqual([float(v) for v in pdf.pages[0].Annots[0].Rect], [0.0, 0.0, 20.0, 50.0])

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
        logo = fixtures.picture(self.dir / "logo.png")
        stamped = self.dir / "stamped.pdf"
        answer = self.editor.save([str(a)], str(stamped), annotations=[{"page": 0, "kind": "stamp", "rect": [10, 10, 60, 30], "image": 0},
                                                                       {"page": 0, "kind": "text", "rect": [10, 50, 200, 30], "text": "בארגז"}],
                                  pictures=[str(logo)])
        self.assertEqual(answer["marked"], 2)  # the picture was readable inside bubblewrap, read-only


if __name__ == "__main__":
    unittest.main()
