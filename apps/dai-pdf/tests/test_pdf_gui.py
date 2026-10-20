# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The D.Ai PDF window (dai_pdf/gui.py): opening, the file bar, pages and zoom, search with highlights, links
asked about (and refused), passwords, copying, printing to a file, the side panel, errors, and Raz's
accessibility audit in Hebrew and English in all three themes."""
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from . import fixtures

fixtures.need_libraries()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSize  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog, QLabel  # noqa: E402

from dai_pdf.edit import Editor  # noqa: E402
from dai_pdf.reader import Reader  # noqa: E402

RAZ = Path(__file__).resolve().parents[2] / "dai-raz"
if str(RAZ) not in sys.path:
    sys.path.insert(0, str(RAZ))


def load_gui(theme: str = "night"):
    os.environ["DAI_THEME"] = theme
    from dai_pdf import gui
    return importlib.reload(gui)


def factory(path, password="", sandboxed=True):
    return Reader(path, password=password, sandboxed=False, python=fixtures.helper_python())


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.opened_urls = []

    def window(self, path=None, lang="en", ask_password=None, confirm_discard=None):
        gui = load_gui()
        win = gui.PdfWindow(str(path) if path else None, lang=lang, reader_factory=factory,
                            open_url=self.opened_urls.append, sandboxed=False, ask_password=ask_password,
                            editor=Editor(sandboxed=False, python=fixtures.helper_python()),
                            confirm_discard=confirm_discard or (lambda: True))  # a modal box would hang offscreen
        self.addCleanup(win.close)
        win.resize(1000, 700)
        win.show()
        self.app.processEvents()
        win.render_visible()
        self.app.processEvents()
        return win

    def test_a_plain_file_pages_and_zoom(self):
        win = self.window(fixtures.plain(self.dir / "p.pdf", pages=3))
        self.assertEqual(len(win.views), 3)
        self.assertFalse(win.banner.isVisible())
        self.assertEqual(win.count_label.text(), "of 3")
        self.assertIn("A plain file", win.windowTitle())
        self.assertFalse(win.views[0].pixmap().isNull())
        self.assertAlmostEqual(win.views[0].pixmap().width() / win.views[0].pixmap().height(), 1.5, places=1)
        win.set_zoom("200")
        win.render_visible()
        self.assertEqual(win.views[0].pixmap().size(), QSize(800, 533))
        win.rotate()
        win.render_visible()
        self.assertEqual(win.views[0].pixmap().size(), QSize(533, 800))
        win.go_to(2)
        self.assertEqual(win.page_field.text(), "3")
        win.page_field.setText("2")
        win._page_typed()
        self.assertEqual(win.current_page, 1)
        self.assertIn("Hello D.Ai page 2", win.views[1].accessibleDescription())

    def test_the_file_bar_says_what_the_file_wants(self):
        win = self.window(fixtures.active(self.dir / "a.pdf"))
        self.assertTrue(win.banner.isVisible())
        text = win.banner_text.text()
        for piece in ("JavaScript (2)", "run a program", "another file", "send data", "2 attached files", "XFA"):
            self.assertIn(piece, text)
        self.assertEqual(win.attachments.count(), 2)
        self.assertIn("evil.exe", win.attachments.item(0).text())

    def test_links_are_asked_about_and_local_ones_refused(self):
        win = self.window(fixtures.active(self.dir / "a.pdf"))
        gui = sys.modules["dai_pdf.gui"]
        link = {"url": "https://example.com/x", "page": -1, "rect": [20, 70, 180, 40]}
        with mock.patch.object(gui.LinkDialog, "exec", return_value=QDialog.DialogCode.Rejected):
            win.follow_link(link)
        self.assertEqual(self.opened_urls, [])
        with mock.patch.object(gui.LinkDialog, "exec", return_value=QDialog.DialogCode.Accepted):
            win.follow_link(link)
            win.follow_link({"url": "file:///etc/passwd", "page": -1, "rect": [0, 0, 1, 1]})
            win.follow_link({"url": "javascript:alert(1)", "page": -1, "rect": [0, 0, 1, 1]})
        self.assertEqual(self.opened_urls, ["https://example.com/x"])  # only the web link, only after the dialog
        view = win.views[0]
        self.assertIsNotNone(view.link_at(view.to_pixels((30.0, 80.0, 1.0, 1.0)).topLeft()))
        self.assertIsNone(view.link_at(view.to_pixels((290.0, 190.0, 1.0, 1.0)).topLeft()))

    def test_search_highlights_and_the_results_panel(self):
        win = self.window(fixtures.plain(self.dir / "p.pdf", pages=3))
        win.search_field.setText("page")
        win.search()
        self.assertEqual(win.result_list.count(), 3)
        self.assertEqual([page for page, _, _ in win.results], [0, 1, 2])
        self.assertEqual(win.side.currentIndex(), 2)
        win.result_list.setCurrentRow(2)
        self.assertEqual(win.current_page, 2)
        self.assertEqual(len(win.views[2].highlights), 1)
        self.assertEqual(win.views[0].highlights, [])
        win.search_field.setText("nothing like this")
        win.search()
        self.assertIn("Nothing found", win.status.text())
        self.assertEqual(win.views[2].highlights, [])

    def test_locked_file_asks_for_the_password(self):
        asked = []

        def ask(name, wrong):
            asked.append((name, wrong))
            return "wrong" if len(asked) == 1 else "secret"

        win = self.window(fixtures.locked(self.dir / "l.pdf"), ask_password=ask)
        self.assertEqual(asked, [("l.pdf", False), ("l.pdf", True)])
        self.assertEqual(len(win.views), 1)
        self.assertIn("Locked page", win.views[0].accessibleDescription())
        gave_up = self.window(fixtures.locked(self.dir / "l2.pdf"), ask_password=lambda name, wrong: None)
        self.assertEqual(len(gave_up.views), 0)
        self.assertIn("stays closed", gave_up.message.text())

    def test_errors_are_sentences(self):
        win = self.window(self.dir / "missing.pdf")
        self.assertIn("no file called missing.pdf", win.message.text())
        win.open_path(str(fixtures.not_a_pdf(self.dir / "x.pdf")))
        self.assertIn("not a PDF that can be opened", win.message.text())
        empty = self.window(lang="he")
        self.assertIn("פתחו קובץ PDF", empty.message.text())

    def test_copy_and_info(self):
        win = self.window(fixtures.plain(self.dir / "p.pdf"))
        win.copy_page(False)
        self.assertEqual(QApplication.clipboard().text(), "Hello D.Ai page 1")
        self.assertIn("copied", win.status.text())
        gui = sys.modules["dai_pdf.gui"]
        dialog = gui.InfoDialog(win, "en", win.doc, False)
        texts = " ".join(label.text() for label in dialog.findChildren(gui.QLabel))
        self.assertIn("A plain file", texts)
        self.assertIn("Dana", texts)

    def test_print_to_a_pdf_file(self):
        try:
            from PyQt6.QtPrintSupport import QPrinter
        except ImportError:
            self.skipTest("QtPrintSupport is missing")
        win = self.window(fixtures.plain(self.dir / "p.pdf", pages=2))
        printer = QPrinter(QPrinter.PrinterMode.ScreenResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        out = self.dir / "printed.pdf"
        printer.setOutputFileName(str(out))
        self.assertEqual(win.print_to(printer), 2)
        self.assertTrue(out.exists() and out.stat().st_size > 1000)

    def test_outline_and_thumbnails(self):
        win = self.window(fixtures.with_outline(self.dir / "o.pdf"))
        self.assertEqual(win.outline.topLevelItemCount(), 2)
        self.assertEqual(win.outline.topLevelItem(0).childCount(), 1)
        win._outline_chosen(win.outline.topLevelItem(1))
        self.assertEqual(win.current_page, 3)
        win.side.setCurrentIndex(0)
        for _ in range(10):
            win._next_thumbnail()
        self.assertEqual(win.thumbs_done, 5)
        self.assertFalse(win.thumbs.item(4).icon().isNull())

    def test_pages_edited_undone_and_saved(self):
        import pikepdf
        win = self.window(fixtures.plain(self.dir / "p.pdf", pages=3))
        self.assertFalse(win.modified)
        win.go_to(1)
        win.rotate_page()
        self.assertTrue(win.modified)
        self.assertTrue(win.windowTitle().startswith("• "))
        self.assertEqual(win.plan[1]["rotate"], 90)
        win.render_visible()
        self.assertEqual(win.views[1].pixel_size().width(), win.views[1].pixel_size().height() * 2 // 3)  # turned
        win.move_page(-1, index=1)
        self.assertEqual([e["index"] for e in win.plan], [1, 0, 2])
        self.assertEqual(win.current_page, 0)
        win.delete_page(index=2)
        self.assertEqual(len(win.views), 2)
        self.assertEqual(win.count_label.text(), "of 2")
        self.assertTrue(win.insert_pdf(str(fixtures.with_outline(self.dir / "o.pdf")), at=1))
        self.assertEqual([(e["source"], e["index"]) for e in win.plan], [(0, 1), (1, 0), (1, 1), (1, 2), (1, 3), (1, 4), (0, 0)])
        self.assertEqual(len(win.sources), 2)
        win.undo()
        self.assertEqual(len(win.plan), 2)
        win.undo()
        self.assertEqual([e["index"] for e in win.plan], [1, 0, 2])
        win.redo()
        self.assertEqual(len(win.plan), 2)
        win.redo()
        self.assertEqual(len(win.plan), 7)
        win.go_to(0)
        for _ in range(8):
            win._next_thumbnail()
        self.assertFalse(win.thumbs.item(1).icon().isNull())
        out = self.dir / "edited.pdf"
        self.assertTrue(win.save_to(str(out)))
        self.assertFalse(win.modified)
        self.assertIn("Saved edited.pdf", win.status.text())
        self.assertEqual(win.reader.path, str(out))  # the saved file is now the one shown
        self.assertEqual(len(win.views), 7)
        with pikepdf.open(out) as pdf:
            self.assertEqual([int(p.obj.get("/Rotate", 0)) for p in pdf.pages], [90, 0, 0, 0, 0, 0, 0])
            self.assertIn(b"Hello D.Ai page 2", bytes(pdf.pages[0].Contents.read_bytes()))
            self.assertIn(b"Chapter 1", bytes(pdf.pages[1].Contents.read_bytes()))
        win.delete_page()
        for _ in range(6):
            win.delete_page()
        self.assertEqual(len(win.views), 1)  # the last page stays
        self.assertIn("at least one page", win.status.text())

    def test_the_form_is_filled_and_flattened(self):
        from PyQt6.QtWidgets import QCheckBox, QComboBox, QLineEdit
        win = self.window(fixtures.form(self.dir / "f.pdf"))
        self.assertEqual([f["name"] for f in win.fields], ["name", "agree", "id", "colour", "size"])
        self.assertIsInstance(win.field_widgets["name"], QLineEdit)
        self.assertFalse(win.field_widgets["id"].isEnabled())
        win.field_widgets["name"].setText("Dana")
        win.field_widgets["name"].textEdited.emit("Dana")
        win.field_widgets["agree"].setChecked(True)
        colour: QComboBox = win.field_widgets["colour"]
        colour.setCurrentIndex(colour.findData("Blue"))
        size: QComboBox = win.field_widgets["size"]
        size.setCurrentIndex(size.findData("L"))
        self.assertEqual(win.field_values, {"name": "Dana", "agree": True, "colour": "Blue", "size": "L"})
        self.assertTrue(win.modified)
        out = self.dir / "filled.pdf"
        self.assertTrue(win.save_to(str(out)))
        self.assertEqual({f["name"]: f["value"] for f in win.fields},
                         {"name": "Dana", "agree": True, "id": "fixed", "colour": "Blue", "size": "L"})
        win.flatten_box.setChecked(True)
        flat = self.dir / "flat.pdf"
        self.assertTrue(win.save_to(str(flat)))
        self.assertEqual(win.fields, [])
        self.assertIn("No form fields", win.form_widget.findChild(QLabel).text())

    def test_marks_drawn_listed_undone_and_saved(self):
        import pikepdf
        from PyQt6.QtCore import QRect
        win = self.window(fixtures.plain(self.dir / "p.pdf", pages=2))
        before = win.views[0].pixmap().toImage()
        win.set_tool("highlight")
        self.assertTrue(win.tool_buttons["highlight"].isChecked())
        self.assertIn("Drag", win.status.text())
        view = win.views[0]
        win.drawn(0, QRect(view.to_pixels((20.0, 80.0, 1.0, 1.0)).topLeft(), view.to_pixels((170.0, 110.0, 1.0, 1.0)).topLeft()))
        self.assertEqual(len(win.marks), 1)
        self.assertEqual((win.marks[0]["kind"], win.marks[0]["source"], win.marks[0]["index"]), ("highlight", 0, 0))
        self.assertAlmostEqual(win.marks[0]["rect"][0], 20.0, delta=1.5)
        self.assertTrue(win.modified)
        win.render_visible()
        self.assertNotEqual(win.views[0].pixmap().toImage(), before)  # the overlay is on the picture
        win.tool_color = "#1565C0"
        win.add_mark("underline", 1, (20.0, 80.0, 100.0, 30.0))
        win.add_mark("note", 1, (250.0, 10.0, 20.0, 20.0), text="שימו לב")
        win.add_mark("text", 0, (10.0, 140.0, 200.0, 40.0), text="שלום", size=14)
        logo = fixtures.picture(self.dir / "logo.png")
        win.add_mark("stamp", 1, (200.0, 120.0, 80.0, 40.0), image=win.add_picture(str(logo)))
        self.assertEqual(win.marks_list.count(), 5)
        self.assertIn("p. 2", win.marks_list.item(1).text())
        win.move_page(-1, index=1)  # the marks follow their pages
        self.assertEqual(win.marks_for(0), [m for m in win.marks if m["index"] == 1])
        self.assertIn("p. 1", win.marks_list.item(1).text())
        win.undo()
        win.marks_list.setCurrentRow(4)
        win.remove_mark()
        self.assertEqual(len(win.marks), 4)
        win.undo()
        self.assertEqual(len(win.marks), 5)
        out = self.dir / "marked.pdf"
        self.assertTrue(win.save_to(str(out)))
        self.assertEqual(win.marks, [])  # the saved file carries them now
        with pikepdf.open(out) as pdf:
            self.assertEqual([str(a.Subtype) for a in pdf.pages[0].Annots], ["/Highlight"])
            self.assertEqual([str(a.Subtype) for a in pdf.pages[1].Annots], ["/Underline", "/Text"])
            self.assertTrue(any(k.startswith("/DaiImg") for k in pdf.pages[1].Resources.XObject.keys()))
        win.set_tool("select")
        self.assertFalse(win.tool_buttons["highlight"].isChecked())

    def test_redaction_and_the_clean_tab(self):
        import pikepdf
        win = self.window(fixtures.plain(self.dir / "p.pdf", pages=2))
        win.set_tool("redact")
        self.assertIn("disappear", win.status.text())
        win.add_mark("redact", 0, (10.0, 80.0, 280.0, 40.0))
        self.assertEqual(win.marks_list.count(), 1)
        self.assertIn("Black box", win.marks_list.item(0).text())
        win.render_visible()
        picture = win.views[0].pixmap().toImage()
        self.assertLess(picture.pixelColor(picture.width() // 2, picture.height() // 2).lightness(), 40)  # the overlay is black
        win.strip_box.setChecked(True)
        self.assertTrue(win.modified)
        out = self.dir / "clean.pdf"
        self.assertTrue(win.save_to(str(out)))
        with pikepdf.open(out) as pdf:
            self.assertEqual(dict(pdf.docinfo), {})
            self.assertIn("/DaiPage", pdf.pages[0].Resources.XObject)
            self.assertNotIn("/XObject", pdf.pages[1].Resources)
        win.reader and self.assertEqual(win.reader.text(0).strip(), "")  # the words are gone in the saved file
        pics = self.dir / "pics"
        files = win.export_to(str(pics), dpi=72)
        self.assertEqual(len(files), 2)
        self.assertIn("2 pictures", win.status.text())

    def test_a_smaller_file_from_the_clean_tab(self):
        win = self.window(fixtures.photos(self.dir / "photos.pdf", width=800, height=600))
        self.assertEqual(win.compress_choice.currentData(), "")
        win.compress_choice.setCurrentIndex(2)
        self.assertTrue(win.modified)
        measured = win.check_size()
        self.assertIn("pictures made smaller", win.status.text())
        self.assertIn("MB; after saving", win.status.text())
        self.assertFalse((self.dir / "small.pdf").exists())
        out = self.dir / "small.pdf"
        self.assertTrue(win.save_to(str(out)))
        self.assertEqual(out.stat().st_size, measured)
        self.assertLess(measured, (self.dir / "photos.pdf").stat().st_size // 2)

    def test_unsaved_changes_ask_before_closing(self):
        asked = []
        win = self.window(fixtures.plain(self.dir / "p.pdf", pages=2), confirm_discard=lambda: asked.append(1) or False)
        win.rotate_page()
        win.close()
        self.assertEqual(asked, [1])
        self.assertTrue(win.isVisible())  # the close was refused
        win.undo()
        self.assertTrue(win.modified)  # an undo back to the original is still "changed": the saved file may differ
        win.confirm_discard = lambda: True
        win.close()
        self.assertFalse(win.isVisible())

    def test_accessible_in_both_languages_and_every_theme(self):
        from dai_raz.a11y import assert_accessible

        for lang in ("en", "he"):
            win = self.window(fixtures.active(self.dir / f"a-{lang}.pdf"), lang=lang)
            win.search_field.setText("wants")
            win.search()
            assert_accessible(self, win, touch=True)
            form = self.window(fixtures.form(self.dir / f"f-{lang}.pdf"), lang=lang)
            form.side.setCurrentIndex(4)
            assert_accessible(self, form, touch=True)
            form.add_mark("note", 0, (10.0, 10.0, 20.0, 20.0), text="x")
            form.side.setCurrentIndex(5)
            assert_accessible(self, form, touch=True)
            form.side.setCurrentIndex(6)
            assert_accessible(self, form, touch=True)
            gui = sys.modules["dai_pdf.gui"]
            for dialog in (gui.InfoDialog(win, lang, win.doc, False), gui.LinkDialog(win, lang, "https://x", True),
                           gui.LinkDialog(win, lang, "file:///x", False), gui.PasswordDialog(win, lang, "a.pdf", True)):
                dialog.show()
                self.app.processEvents()
                assert_accessible(self, dialog)
                dialog.close()


if __name__ == "__main__":
    unittest.main()
