# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""D.Ai OCR (docs/V2.md F1), with the screen and the OCR engine replaced by fakes."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dai_ocr import cli

PNG = b"\x89PNG\r\n\x1a\nfake"


class Fake:
    """Answers like slurp, grim, tesseract, wl-copy and notify-send, and remembers what was asked."""

    def __init__(self, area="10,20 300x80", text="שלום עולם\nHello  \n\n\n\fD.Ai\n", langs="eng\nheb\nara\n"):
        self.area, self.text, self.langs, self.calls, self.copied, self.notes = area, text, langs, [], [], []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        name = argv[0]
        if name == "tesseract" and argv[1] == "--list-langs":
            return subprocess.CompletedProcess(argv, 0, f'List of available languages in "/usr/share":\n{self.langs}', "")
        if name == "slurp":
            return subprocess.CompletedProcess(argv, 0 if self.area else 1, self.area or "", "")
        if name == "grim":
            return subprocess.CompletedProcess(argv, 0, PNG, b"")
        if name == "tesseract":
            return subprocess.CompletedProcess(argv, 0, self.text.encode(), b"")
        if name == "wl-copy":
            self.copied.append(kwargs["input"].decode())
            return subprocess.CompletedProcess(argv, 0)
        if name == "notify-send":
            self.notes.append(argv[-2:])
            return subprocess.CompletedProcess(argv, 0)
        raise AssertionError(argv)

    def argv(self, name):
        return [argv for argv, _ in self.calls if argv[0] == name]


class OcrTests(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.dict(os.environ, {"LANG": "he_IL.UTF-8", "LANGUAGE": "", "LC_ALL": "", "LC_MESSAGES": ""})
        patch.start()
        self.addCleanup(patch.stop)

    def test_languages_follow_the_interface_and_what_is_installed(self):
        self.assertEqual(cli.languages(["he", "en"], {"heb", "eng"}), "heb+eng")
        self.assertEqual(cli.languages(["ru", "en"], {"eng"}), "eng")  # no Russian data: English only
        self.assertEqual(cli.languages(["en", "en"], {"eng"}), "eng")
        self.assertEqual(cli.languages([], set()), "eng")

    def test_text_is_tidied(self):
        self.assertEqual(cli.clean("a  \n\n\n\fb\r\n"), "a\n\nb")
        self.assertEqual(cli.preview("x " * 200)[-1], "…")

    def test_area_to_clipboard(self):
        fake, chimes = Fake(), []
        self.assertEqual(cli.main(["dai-ocr"], run=fake, chime=chimes.append), 0)
        self.assertEqual(chimes, ["complete"])  # the crystal "done" of docs/SOUNDS.md
        self.assertEqual(fake.copied, ["שלום עולם\nHello\n\nD.Ai"])
        self.assertEqual(fake.argv("grim")[0], ["grim", "-g", "10,20 300x80", "-"])  # to memory, not a file
        tesseract = [argv for argv in fake.argv("tesseract") if argv[1] != "--list-langs"][0]
        self.assertEqual(tesseract, ["tesseract", "stdin", "stdout", "-l", "heb+eng"])
        self.assertIn("הטקסט הועתק", fake.notes[-1][0])

    def test_escape_does_nothing(self):
        fake = Fake(area="")
        self.assertEqual(cli.main(["dai-ocr"], run=fake), 1)
        self.assertEqual((fake.argv("grim"), fake.copied, fake.notes), ([], [], []))

    def test_nothing_found_says_so(self):
        fake = Fake(text="  \n\f")
        self.assertEqual(cli.main(["dai-ocr"], run=fake), 1)
        self.assertEqual(fake.copied, [])
        self.assertIn("לא נמצא טקסט", fake.notes[-1][0])

    def test_a_file_and_print(self):
        fake = Fake()
        with tempfile.TemporaryDirectory() as tmp:
            picture = Path(tmp) / "page.png"
            picture.write_bytes(PNG)
            with mock.patch("sys.stdout") as out:
                self.assertEqual(cli.main(["dai-ocr", "--file", str(picture), "--print", "--lang", "ar,en"], run=fake), 0)
        self.assertEqual(fake.argv("slurp"), [])
        self.assertEqual(fake.copied, [])
        self.assertIn("ara+eng", [argv[-1] for argv in fake.argv("tesseract")])
        self.assertIn("D.Ai", "".join(str(c) for c in out.write.call_args_list))
        self.assertEqual(cli.main(["dai-ocr", "--file", "/no/such.png"], run=fake), 2)

    def test_engine_failure_is_reported_not_raised(self):
        def broken(argv, **kwargs):
            if argv[0] == "tesseract" and argv[1] != "--list-langs":
                return subprocess.CompletedProcess(argv, 1, b"", b"error")
            return Fake()(argv, **kwargs)
        notes = []
        with mock.patch.object(cli, "notify", lambda title, body, run: notes.append(body)):
            self.assertEqual(cli.main(["dai-ocr"], run=broken), 1)
        self.assertIn("tesseract", notes[0])

    def test_unknown_languages_are_ignored(self):
        fake = Fake()
        cli.main(["dai-ocr", "--lang", "xx,; rm -rf /", "--print", "--file", "/no/such.png"], run=fake)
        self.assertEqual(cli.languages(["xx"], {"eng"}), "eng")


class CommandBarTests(unittest.TestCase):
    def test_command_bar_offers_it(self):
        try:
            from dai_command import core
        except ImportError:
            self.skipTest("dai_command not on the path")
        with mock.patch("shutil.which", return_value="/usr/bin/dai-ocr"):
            for text in ("copy text from the screen", "ocr", "text from this picture", "העתקת טקסט מהמסך",
                         "זיהוי טקסט", "טקסט מתמונה"):
                self.assertEqual(core.build_actions(text, [])[0].kind, "ocr", text)
            for text in ("read the text file", "find the text from yesterday", "what did I copy", "copy"):
                self.assertNotIn("ocr", [row.kind for row in core.build_actions(text, [])], text)


if __name__ == "__main__":
    unittest.main()
