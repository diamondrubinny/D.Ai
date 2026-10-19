# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The Diamond Chat window (dai_chat/gui.py): writing and sending, a message that arrives while it is open,
adding someone by their code, comparing symbols, pictures only to verified contacts, a blocked contact, the
off state, and Raz's accessibility audit in Hebrew and English in all three themes."""
import importlib
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

if importlib.util.find_spec("nacl") is None or importlib.util.find_spec("PyQt6") is None:
    raise unittest.SkipTest("PyNaCl or PyQt6 is missing")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog, QLabel, QPushButton  # noqa: E402

from dai_chat import invite, keys, message, store  # noqa: E402
from dai_chat.service import Settings  # noqa: E402

RAZ = Path(__file__).resolve().parents[2] / "dai-raz"
if str(RAZ) not in sys.path:
    sys.path.insert(0, str(RAZ))


def load_gui(theme: str = "night"):
    os.environ["DAI_THEME"] = theme
    from dai_chat import gui
    return importlib.reload(gui)  # the colors are read when the module loads, as in the other windows


def scan_reason(key):
    from dai_chat import scan
    return scan.REASONS[key][0]


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = store.Store(Path(self.tmp.name) / "chat")
        self.addCleanup(self.store.close)
        self.me = keys.Identity.generate()
        self.dana = keys.Identity.generate().public
        self.store.add_contact(store.Contact(self.dana, "Dana"))
        self.pokes, self.restarts = [], []
        self.settings_file = Path(self.tmp.name) / "chat.json"
        Settings(name="Me").save(self.settings_file)
        self.code = invite.make(keys.Identity.generate().public, self.me.public)

    def window(self, lang="en", running=True, clean=None):
        gui = load_gui()
        win = gui.ChatWindow(self.store, self.me.public, self.code, poke=lambda: self.pokes.append(1),
                             running=lambda: running, lang=lang,
                             clean=clean or (lambda data: (b"\x89PNG\r\n\x1a\nCLEAN", "image/png")),
                             settings_file=self.settings_file, restart=lambda: self.restarts.append(1))
        self.addCleanup(win.close)
        win.show()
        self.app.processEvents()
        return win

    def choose(self, win, name="Dana"):
        for row in range(win.contacts.count()):
            if win.contacts.item(row).text().endswith(name):
                win.contacts.setCurrentRow(row)
        self.app.processEvents()

    def texts(self, win):
        return " ".join(w.text() for w in win.findChildren(QLabel) if w.isVisible())

    def test_write_and_send(self):
        empty = store.Store(Path(self.tmp.name) / "empty")
        self.addCleanup(empty.close)
        nobody = load_gui().ChatWindow(empty, self.me.public, self.code, lang="en", settings_file=self.settings_file,
                                       restart=lambda: None)
        self.addCleanup(nobody.close)
        self.assertFalse(nobody.field.isEnabled())  # no contact yet: nothing to write to
        self.assertIn("Choose a contact", nobody.who.text())
        win = self.window()
        self.choose(win)
        self.assertTrue(win.field.isEnabled())
        win.field.setText("  see you at six  ")
        win.field.returnPressed.emit()
        self.assertEqual(self.store.conversation(self.dana)[0]["text"], "see you at six")
        self.assertEqual(self.store.queued(self.dana), [self.store.conversation(self.dana)[0]["id"]])
        self.assertEqual((win.field.text(), len(self.pokes)), ("", 1))
        self.assertIn("see you at six", win.messages.item(0).text())
        self.assertIn("⌛", win.messages.item(0).text())  # queued

    def test_a_message_that_arrives_while_open(self):
        win = self.window()
        self.choose(win)
        self.store.add_message(self.dana, message.Message.text("שלום!"), outgoing=False, state="delivered")
        win.refresh()
        self.assertIn("שלום!", win.messages.item(0).text())
        self.assertTrue(win.messages.item(0).text().startswith("Dana"))

    def test_add_someone_by_their_code(self):
        win = self.window()
        noa = keys.Identity.generate()
        code = invite.make(keys.Identity.generate().public, noa.public)
        dialog = load_gui().AddDialog(win, "en", self.code)
        dialog.name.setText("Noa")
        dialog.code.setText(code[:-1] + ("a" if code[-1] != "a" else "b"))
        dialog.check()
        self.assertIn("typo", dialog.error.text())
        dialog.code.setText(self.code)
        dialog.check()
        self.assertIn("your own code", dialog.error.text())
        dialog.code.setText(code)
        dialog.check()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertTrue(dialog.parsed.matches(noa.public))

    def test_compare_symbols_then_pictures(self):
        win = self.window()
        self.choose(win)
        self.assertTrue(win.compare.isVisible())
        self.assertIn("not verified", self.texts(win))
        picture = Path(self.tmp.name) / "photo.png"
        picture.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(64))
        win.send_picture(str(picture))
        self.assertEqual(self.store.queued(self.dana), [])  # not before the symbols were compared
        self.assertIn("Compare the symbols", win.status.text())
        dialog = load_gui().SymbolsDialog(win, "he", "Dana", [0, 1, 2, 3, 4, 5])
        self.assertIn("יהלום", " ".join(w.text() for w in dialog.findChildren(QLabel)))
        self.store.set_verified(self.dana)
        win.refresh()
        self.assertFalse(win.compare.isVisible())
        win.send_picture(str(picture))
        self.assertEqual(len(self.store.queued(self.dana)), 1)
        self.assertIn("without its location", win.status.text())

    def test_pictures_show_and_open(self):
        from PyQt6.QtCore import QBuffer, QIODevice
        from PyQt6.QtGui import QColor, QImage
        image = QImage(400, 300, QImage.Format.Format_RGB32)
        image.fill(QColor("teal"))
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        self.store.add_message(self.dana, message.Message.picture(bytes(buffer.data()), "image/png"),
                               outgoing=False, state="delivered")
        opened = []
        gui = load_gui()
        win = gui.ChatWindow(self.store, self.me.public, self.code, lang="en", viewer=opened.append,
                             settings_file=self.settings_file, restart=lambda: None)
        self.addCleanup(win.close)
        win.show()
        self.choose(win)
        item = win.messages.item(0)
        self.assertFalse(item.icon().isNull())  # a thumbnail
        self.assertIn("[a picture]", item.text())  # and words for a screen reader
        win.open_picture(item)
        self.assertEqual(len(opened), 1)
        self.assertTrue(opened[0].name.endswith(".png") and opened[0].parent == self.store.pictures)

    def test_a_new_contact_waits_for_a_yes(self):
        self.store.add_message(self.dana, message.Message.text("hi from Dana"), outgoing=False, state="request")
        trick = message.Message.text("urgent: your password")
        self.store.add_message(self.dana, trick, outgoing=False, state="request", warning="asks")
        win = self.window()
        self.choose(win)
        self.assertEqual(win.messages.count(), 0)  # nothing shown before a decision
        self.assertTrue(win.banner.isVisible() and win.accept_button.isVisible())
        self.assertIn("checked for phishing", win.banner_text.text())
        self.assertIn("(2 ✉)", win.contacts.currentItem().text())
        win.accept_button.click()
        self.assertEqual(win.messages.count(), 1)
        self.assertIn("hi from Dana", win.messages.item(0).text())
        self.assertTrue(win.show_button.isVisible())  # the suspicious one is still held
        self.assertIn("password", win.banner_text.text().lower() + scan_reason("asks"))
        win.discard_button.click()
        self.assertFalse(win.banner.isVisible())
        self.assertEqual(self.store.conversation(self.dana, waiting=True), [])

    def test_decline_blocks(self):
        self.store.add_message(self.dana, message.Message.text("buy now"), outgoing=False, state="request")
        win = self.window()
        self.choose(win)
        win.decline_button.click()
        self.assertTrue(self.store.contact(self.dana).blocked)
        self.assertEqual(self.store.conversation(self.dana, waiting=True), [])

    def test_their_chosen_name_and_receiving(self):
        self.store.add_contact(store.Contact(self.dana, "Dana", display="Dana L", accepted=True))
        win = self.window()
        self.choose(win)
        self.assertIn("Dana L", win.display.text())
        self.assertIn("Receiving: off", win.receive_button.text())  # off until turned on
        win.receive_button.click()
        self.assertTrue(Settings.load(self.settings_file).receive)
        self.assertIn("Receiving: on", win.receive_button.text())
        self.assertEqual(len(self.restarts), 1)
        dialog = load_gui().NameDialog(win, "en", "")
        dialog.name.setText("\u202e\u200f ")
        dialog.check()
        self.assertIn("letters", dialog.error.text())
        dialog.name.setText("  Noa  K ")
        dialog.check()
        self.assertEqual(dialog.chosen, "Noa K")

    def test_a_picture_the_sandbox_refuses(self):
        from dai_chat import pictures

        def refuse(data):
            raise pictures.PictureError("no")

        self.store.set_verified(self.dana)
        win = self.window(clean=refuse)
        self.choose(win)
        picture = Path(self.tmp.name) / "fake.png"
        picture.write_bytes(b"<svg/>")
        win.send_picture(str(picture))
        self.assertEqual(self.store.queued(self.dana), [])
        self.assertIn("not a PNG", win.status.text())

    def test_blocked_and_off(self):
        self.store.set_blocked(self.dana)
        win = self.window(running=False)
        self.choose(win)
        self.assertFalse(win.field.isEnabled())
        self.assertTrue(win.on_button.isVisible())
        self.assertIn("Chat is off", win.status.text())

    def test_each_message_in_its_own_direction(self):
        gui = load_gui()
        self.assertEqual(gui.in_its_direction("שלום!"), "\u202bשלום!\u202c")
        self.assertEqual(gui.in_its_direction("123 hello"), "\u202a123 hello\u202c")  # digits are not letters
        self.assertEqual(gui.in_its_direction("مرحبا"), "\u202bمرحبا\u202c")
        self.assertEqual(gui.in_its_direction("😊 !"), "😊 !")

    def test_hebrew_is_right_to_left(self):
        from PyQt6.QtCore import Qt
        win = self.window(lang="he")
        self.assertEqual(win.layoutDirection(), Qt.LayoutDirection.RightToLeft)
        self.assertIn("אנשי קשר", win.contacts.accessibleName())
        for button in win.findChildren(QPushButton):
            if button.isVisible():
                self.assertTrue(button.accessibleName())

    def test_accessible_in_every_theme(self):
        from dai_raz.a11y import assert_accessible  # checks Night, then Day and Contrast itself
        self.store.add_message(self.dana, message.Message.text("hi"), outgoing=False, state="request")  # the banner
        for lang in ("he", "en"):
            win = self.window(lang=lang)
            self.choose(win)
            assert_accessible(self, win)
            gui = load_gui()
            for dialog in (gui.SymbolsDialog(win, lang, "Dana", [0, 1, 2, 3, 4, 5]), gui.AddDialog(win, lang, self.code),
                           gui.NameDialog(win, lang, "Me")):
                dialog.show()
                self.app.processEvents()
                assert_accessible(self, dialog)
                dialog.close()


if __name__ == "__main__":
    unittest.main()
