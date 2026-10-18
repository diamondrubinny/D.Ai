# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""J's local folders (docs/MAIL.md §11): mbox and Maildir imported, the other app's files only read."""
import hashlib
import mailbox
import os
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path

from dai_j import localmail
from dai_j.mail import parse_body
from dai_j.store import Store


def message(subject, sender="Dana <dana@example.org>", mid=None, body="שלום"):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = sender, "avi@example.org", subject
    m["Date"] = "Mon, 12 Oct 2026 10:00:00 +0300"
    m["Message-ID"] = mid or f"<{abs(hash(subject))}@example.org>"
    m.set_content(body)
    return m


def digest(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        h.update(str(path.relative_to(root)).encode() + path.read_bytes())
    return h.hexdigest()


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        profile = self.home / ".thunderbird/abc.default"
        local = profile / "Mail/Local Folders"
        (local / "Inbox.sbd").mkdir(parents=True)
        (profile / "prefs.js").write_text('user_pref("mail.server.server1.type", "none");\n')
        box = mailbox.mbox(local / "Inbox")
        for subject, status in (("Read one", "0001"), ("Flagged unread", "0004"), ("Deleted", "0009")):
            m = mailbox.mboxMessage(message(subject))
            m["X-Mozilla-Status"] = status
            box.add(m)
        box.flush()
        box.close()
        work = mailbox.mbox(local / "Inbox.sbd/Work")
        work.add(mailbox.mboxMessage(message("Work report")))
        work.flush()
        work.close()
        (local / "Inbox.msf").write_text("// an index, not mail")
        evolution = self.home / ".local/share/evolution/mail/local"
        evolution.parent.mkdir(parents=True)
        maildir = mailbox.Maildir(evolution, create=True)
        seen = mailbox.MaildirMessage(message("Evolution seen"))
        seen.set_flags("S")
        maildir.add(seen)
        sub = maildir.add_folder("Projects")
        sub.add(mailbox.MaildirMessage(message("Project plan")))
        self.store = Store(Path(self.tmp.name) / "mail.sqlite")
        self.addCleanup(self.store.close)

    def test_finds_thunderbird_and_evolution_folders(self):
        names = {s.name: s.kind for s in localmail.find_sources(self.home)}
        self.assertEqual(names, {"Thunderbird/Local Folders/Inbox": "mbox",
                                 "Thunderbird/Local Folders/Inbox/Work": "mbox",
                                 "Evolution/Inbox": "maildir", "Evolution/Projects": "maildir"})

    def test_copies_once_with_flags_and_never_touches_the_source(self):
        before = digest(self.home)
        sources = localmail.find_sources(self.home)
        inbox = next(s for s in sources if s.name.endswith("Local Folders/Inbox"))
        result = localmail.import_source(self.store, inbox)
        self.assertEqual((result.added, result.skipped), (2, 1))  # the deleted one is not copied
        rows = {r["subject"]: r for r in self.store.listing([localmail.LOCAL], folder=inbox.name)}
        self.assertEqual(set(rows), {"Read one", "Flagged unread"})
        self.assertEqual((rows["Read one"]["seen"], rows["Flagged unread"]["seen"], rows["Flagged unread"]["flagged"]),
                         (1, 0, 1))
        raw = self.store.body(localmail.LOCAL, inbox.name, rows["Read one"]["uid"])
        self.assertIn("שלום", parse_body(raw).text)  # the whole message is kept, body and all
        again = localmail.import_source(self.store, inbox)
        self.assertEqual((again.added, again.skipped), (0, 3))  # nothing twice
        for source in sources:
            localmail.import_source(self.store, source)
        evolution = {r["subject"]: r["seen"] for r in self.store.listing([localmail.LOCAL], folder="Evolution/Inbox")}
        self.assertEqual(evolution, {"Evolution seen": 1})
        self.assertEqual(digest(self.home), before)  # the other apps' files are only read
        self.assertEqual(oct(os.stat(self.store.path).st_mode & 0o777), "0o600")

    def test_a_picked_file_or_folder(self):
        source = localmail.source_for_path(self.home / ".thunderbird/abc.default/Mail/Local Folders/Inbox.sbd/Work")
        self.assertEqual((source.kind, source.name), ("mbox", "Imported/Work"))
        self.assertIsNone(localmail.source_for_path(self.home / ".thunderbird/abc.default/prefs.js"))
        self.assertEqual(localmail.source_for_path(self.home / ".local/share/evolution/mail/local").kind, "maildir")

    def test_too_big_and_hidden_names(self):
        self.assertEqual(localmail._clean_name("Inbox‮/evil\n"), "Inbox/evil")
        path = Path(self.tmp.name) / "big.mbox"
        box = mailbox.mbox(path)
        box.add(mailbox.mboxMessage(message("Huge", body="x" * 100)))
        box.flush()
        box.close()
        original = localmail.MAX_MESSAGE
        localmail.MAX_MESSAGE = 50
        self.addCleanup(setattr, localmail, "MAX_MESSAGE", original)
        result = localmail.import_source(self.store, localmail.source_for_path(path))
        self.assertEqual((result.added, result.skipped), (0, 1))


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PyQt6.QtWidgets import QApplication
        except ImportError:
            raise unittest.SkipTest("PyQt6 is missing")
        cls.app = QApplication.instance() or QApplication([])

    def test_local_folders_open_without_any_account(self):
        from dai_j import accounts, gui

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            path = directory / "old.mbox"
            box = mailbox.mbox(path)
            box.add(mailbox.mboxMessage(message("Old letter", body="מכתב ישן")))
            box.flush()
            box.close()
            window = gui.MainWindow("he", directory, accounts.Keyring(which=lambda name: None), gui.Runner(inline=True),
                                    ask_password=lambda a: None, sync_on_start=False)
            self.addCleanup(window.close)
            self.assertEqual(window.stack.currentIndex(), 0)  # nothing yet: the welcome page
            window.import_mail([localmail.source_for_path(path)])
            self.assertEqual(window.stack.currentIndex(), 1)
            local = window._find_folder(("folder", "Imported/old", localmail.LOCAL))
            self.assertIsNotNone(local)
            window.folders.setCurrentItem(local)
            window.show_folder()
            window.list.setCurrentItem(window.list.topLevelItem(0))
            window.open_current()
            self.assertIn("מכתב ישן", window.reader.toPlainText())
            window.mark_unread()
            self.assertEqual(window.current["seen"], 0)
            window.delete()
            self.assertEqual(window.store.listing([localmail.LOCAL], folder="Imported/old"), [])


if __name__ == "__main__":
    unittest.main()
