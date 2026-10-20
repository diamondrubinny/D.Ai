# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-pdf on the command line (dai_pdf/cli.py): --version with the credit line, info, text, check and their
exit codes."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from . import fixtures

fixtures.need_libraries()

from dai_pdf import cli  # noqa: E402


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        env = {"DAI_PDF_DIRECT": "1", "DAI_PDF_PYTHON": fixtures.helper_python(), "LANG": "en_US.UTF-8", "LC_ALL": "",
               "LANGUAGE": "", "DAI_LANG": "en"}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["dai-pdf", *args])
        return code, out.getvalue(), err.getvalue()

    def test_version_and_help(self):
        code, out, _ = self.run_cli("--version")
        self.assertEqual(code, 0)
        self.assertIn("dai-pdf 0.1.0 — Diamond Rubinny (d.Ai)", out)
        code, out, _ = self.run_cli("--help")
        self.assertEqual(code, 0)
        self.assertIn("sandbox", out)

    def test_info_lists_pages_metadata_and_wants(self):
        code, out, _ = self.run_cli("info", str(fixtures.active(self.dir / "a.pdf")))
        self.assertEqual(code, 0)
        self.assertIn("Pages: 1", out)
        self.assertIn("! This PDF contains JavaScript (2)", out)
        self.assertIn("evil.exe", out)
        self.assertIn("Links to addresses: 1", out)

    def test_check_exit_codes(self):
        self.assertEqual(self.run_cli("check", str(fixtures.plain(self.dir / "p.pdf")))[0], 0)
        code, out, _ = self.run_cli("check", str(fixtures.active(self.dir / "a.pdf")))
        self.assertEqual(code, 1)
        self.assertIn("not run", out)
        code, _, err = self.run_cli("check", str(self.dir / "none.pdf"))
        self.assertEqual(code, 2)
        self.assertIn("no file called", err)
        code, _, err = self.run_cli("check", str(fixtures.locked(self.dir / "l.pdf")))
        self.assertEqual((code, "locked" in err), (2, True))
        self.assertEqual(self.run_cli("check", str(fixtures.locked(self.dir / "l2.pdf")), "--password", "secret")[0], 0)
        code, _, err = self.run_cli("check")
        self.assertEqual((code, "Which file" in err), (2, True))

    def test_text_whole_file_and_one_page(self):
        path = fixtures.plain(self.dir / "p.pdf", pages=2)
        code, out, _ = self.run_cli("text", str(path))
        self.assertEqual(code, 0)
        self.assertIn("Hello D.Ai page 1", out)
        self.assertIn("\f", out)
        self.assertIn("Hello D.Ai page 2", out)
        code, out, _ = self.run_cli("text", str(path), "--page", "2")
        self.assertEqual((code, out.strip()), (0, "Hello D.Ai page 2"))
        code, _, err = self.run_cli("text", str(path), "--page", "9")
        self.assertEqual((code, "No page 9" in err), (2, True))


    def test_edit_commands(self):
        import pikepdf
        a = fixtures.plain(self.dir / "a.pdf", pages=3)
        b = fixtures.plain(self.dir / "b.pdf", pages=1)
        out = self.dir / "m.pdf"
        code, text, err = self.run_cli("merge", str(a), str(b), "-o", str(out))
        self.assertEqual((code, err), (0, ""), text)
        self.assertIn("4 pages", text)
        code, text, _ = self.run_cli("rotate", str(out), "--by", "90", "--pages", "2", "-o", str(self.dir / "r.pdf"))
        self.assertEqual(code, 0, text)
        with pikepdf.open(self.dir / "r.pdf") as pdf:
            self.assertEqual([int(p.obj.get("/Rotate", 0)) for p in pdf.pages], [0, 90, 0, 0])
        code, text, _ = self.run_cli("delete", str(out), "--pages", "1,4", "-o", str(self.dir / "d.pdf"))
        self.assertEqual(code, 0, text)
        self.assertIn("2 pages", text)
        code, text, _ = self.run_cli("split", str(out), "--pages", "3-4", "-o", str(self.dir / "s.pdf"))
        self.assertEqual(code, 0, text)
        code, text, _ = self.run_cli("split", str(out), "-o", str(self.dir / "each.pdf"))
        self.assertEqual(code, 0, text)
        self.assertEqual(sorted(p.name for p in self.dir.glob("each-*.pdf")), ["each-1.pdf", "each-2.pdf", "each-3.pdf", "each-4.pdf"])
        code, _, err = self.run_cli("delete", str(out), "--pages", "9", "-o", str(self.dir / "x.pdf"))
        self.assertEqual(code, 2)
        self.assertIn("No page", err)
        code, _, err = self.run_cli("rotate", str(out), "--by", "45", "-o", str(self.dir / "x.pdf"))
        self.assertEqual(code, 2)
        code, _, err = self.run_cli("merge", str(a))
        self.assertEqual(code, 2)
        self.assertIn("-o", err)
        self.assertFalse((self.dir / "x.pdf").exists())

    def test_fields_and_fill(self):
        form = fixtures.form(self.dir / "f.pdf")
        code, text, _ = self.run_cli("fields", str(form))
        self.assertEqual(code, 0, text)
        self.assertIn("name  (text, page 1): ", text)
        self.assertIn("agree  (checkbox, page 1): unchecked", text)
        self.assertIn("size  (choice, page 2): M  [S, M, L]", text)
        out = self.dir / "filled.pdf"
        code, text, _ = self.run_cli("fill", str(form), "--set", "name=Dana", "--set", "agree=true", "--flatten", "-o", str(out))
        self.assertEqual(code, 0, text)
        self.assertIn("2 fields filled.", text)
        code, text, _ = self.run_cli("fields", str(out))
        self.assertIn("No form fields", text)
        code, text, _ = self.run_cli("fields", str(fixtures.plain(self.dir / "p.pdf")))
        self.assertIn("No form fields", text)


if __name__ == "__main__":
    unittest.main()
