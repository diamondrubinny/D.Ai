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


class SearchTests(unittest.TestCase):
    def test_every_word_literally_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "mail.sqlite")
            self.addCleanup(store.close)
            path = Path(tmp) / "a.mbox"
            box = mailbox.mbox(path)
            for subject, body in (("דוח רבעוני 100%", "plain body about budgets"), ("Lunch", "see you at noon"),
                                  ("Report_final", "attached")):
                box.add(mailbox.mboxMessage(message(subject, body=body)))
            box.flush()
            box.close()
            localmail.import_source(store, localmail.source_for_path(path))
            subjects = lambda q: [r["subject"] for r in store.search([localmail.LOCAL], q)]  # noqa: E731
            self.assertEqual(subjects("דוח"), ["דוח רבעוני 100%"])
            self.assertEqual(subjects("budgets"), ["דוח רבעוני 100%"])  # the body, when kept as plain text
            self.assertEqual(subjects("dana noon"), ["Lunch"])  # every word, anywhere
            self.assertEqual(subjects("100%"), ["דוח רבעוני 100%"])
            self.assertEqual(subjects("%"), ["דוח רבעוני 100%"])  # % is a character, not "anything"
            self.assertEqual(subjects("t_f"), ["Report_final"])
            self.assertEqual(subjects("x_y"), [])  # _ is not "any one character"
            self.assertEqual(store.search([], "dana"), [])


class SnoozeTests(unittest.TestCase):
    def test_out_of_sight_until_its_time_then_back_unread(self):
        import time
        from dai_j.store import snooze_time

        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "mail.sqlite")
            self.addCleanup(store.close)
            path = Path(tmp) / "a.mbox"
            box = mailbox.mbox(path)
            m = mailbox.mboxMessage(message("Pay the bill"))
            m.set_flags("RO")
            box.add(m)
            box.flush()
            box.close()
            folder = localmail.import_source(store, localmail.source_for_path(path)).folders[0]
            uid = store.listing([localmail.LOCAL], folder=folder)[0]["uid"]
            store.snooze(localmail.LOCAL, folder, uid, time.time() + 3600)
            self.assertEqual(store.listing([localmail.LOCAL], folder=folder), [])
            self.assertEqual(store.search([localmail.LOCAL], "bill"), [])
            self.assertAlmostEqual(store.next_wake(), time.time() + 3600, delta=5)
            store.snooze(localmail.LOCAL, folder, uid, time.time() - 1)  # its time came
            rows = store.listing([localmail.LOCAL], folder=folder)
            self.assertEqual([(r["subject"], r["seen"]) for r in rows], [("Pay the bill", 0)])
            store.remove(localmail.LOCAL, folder, uid)
            self.assertIsNone(store.next_wake())

    def test_the_three_choices(self):
        import time
        from dai_j.store import snooze_time

        friday = time.mktime((2026, 10, 16, 15, 30, 0, 0, 0, -1))  # a Friday afternoon
        self.assertEqual(snooze_time("later", friday), friday + 3 * 3600)
        self.assertEqual(time.localtime(snooze_time("tomorrow", friday))[:5], (2026, 10, 17, 8, 0))
        self.assertEqual(time.localtime(snooze_time("week", friday))[:5], (2026, 10, 19, 8, 0))  # Monday
        monday = time.mktime((2026, 10, 19, 9, 0, 0, 0, 0, -1))
        self.assertEqual(time.localtime(snooze_time("week", monday))[:3], (2026, 10, 26))  # the next one


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
            window.search.setText("ישן")  # the search field finds it across every folder
            self.assertEqual(window.list.topLevelItemCount(), 1)
            window.search.setText("nothing like this")
            self.assertEqual(window.list.topLevelItemCount(), 0)
            window.search.clear()
            window.list.setCurrentItem(window.list.topLevelItem(0))
            window.delete()
            self.assertEqual(window.store.listing([localmail.LOCAL], folder="Imported/old"), [])


if __name__ == "__main__":
    unittest.main()
