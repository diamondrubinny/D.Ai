# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
import imaplib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from dai_j import accounts, compose, discover, engine, mail, sanitize
from dai_j.store import Store

from .fake_imap import FakeImapServer, message

ISPDB = b"""<?xml version="1.0"?>
<clientConfig version="1.1"><emailProvider id="example.org">
  <incomingServer type="pop3"><hostname>pop.example.org</hostname><port>995</port><socketType>SSL</socketType></incomingServer>
  <incomingServer type="imap"><hostname>plain.example.org</hostname><port>143</port><socketType>plain</socketType></incomingServer>
  <incomingServer type="imap"><hostname>IMAP.example.org</hostname><port>993</port><socketType>SSL</socketType>
    <username>%EMAILLOCALPART%</username><authentication>password-cleartext</authentication></incomingServer>
  <outgoingServer type="smtp"><hostname>smtp.example.org</hostname><port>587</port><socketType>STARTTLS</socketType>
    <username>%EMAILADDRESS%</username></outgoingServer>
</emailProvider></clientConfig>"""


class DiscoverTests(unittest.TestCase):
    def test_known_providers_need_no_network(self):
        settings = discover.discover("someone@gmail.com", fetch=self.fail, resolve=self.fail)
        self.assertEqual((settings.incoming.host, settings.incoming.port, settings.incoming.security),
                         ("imap.gmail.com", 993, "ssl"))
        self.assertIn("app_password", settings.notes)
        self.assertIn("oauth", discover.discover("x@outlook.com", fetch=self.fail, resolve=self.fail).notes)

    def test_autoconfig_skips_unencrypted_servers(self):
        asked = []

        def fetch(url):
            asked.append(url)
            return ISPDB if "thunderbird.net" in url else None

        settings = discover.discover("dana@example.org", fetch=fetch, resolve=lambda *_: [])
        self.assertEqual(settings.source, "ispdb")
        self.assertEqual(settings.incoming.host, "imap.example.org")
        self.assertEqual(settings.incoming.username, "dana")
        self.assertEqual((settings.outgoing.port, settings.outgoing.security), (587, "starttls"))
        self.assertTrue(all(u.startswith("https://") for u in asked))  # never plain http

    def test_dns_and_mx_and_guess(self):
        def resolve(name, kind):
            return {"_imaps._tcp.srv.org": [(0, "mail.srv.org", 993)],
                    "_submissions._tcp.srv.org": [(0, "out.srv.org", 465)],
                    "corp.co.il": [(1, "aspmx.l.google.com", 0)]}.get(name, [])

        srv = discover.discover("a@srv.org", fetch=lambda u: None, resolve=resolve)
        self.assertEqual((srv.source, srv.incoming.host, srv.outgoing.host), ("dns", "mail.srv.org", "out.srv.org"))
        corp = discover.discover("a@corp.co.il", fetch=lambda u: None, resolve=resolve)
        self.assertEqual((corp.source, corp.incoming.host), ("mx-google", "imap.gmail.com"))
        guess = discover.discover("a@unknown.example", fetch=lambda u: None, resolve=resolve)
        self.assertEqual((guess.source, guess.incoming.host, guess.incoming.security), ("guess", "imap.unknown.example", "ssl"))

    def test_bad_input(self):
        self.assertIsNone(discover.discover("not an address"))
        bad = ISPDB.replace(b"IMAP.example.org", b"evil host;rm")
        self.assertIsNone(discover.parse_autoconfig(bad, "a@example.org"))
        self.assertIsNone(discover.parse_autoconfig(b"<oops", "a@example.org"))


class KeyringTests(unittest.TestCase):
    def test_the_password_goes_through_stdin_and_never_argv(self):
        calls = []

        def runner(argv, input=None, **kwargs):
            calls.append((argv, input))
            return subprocess.CompletedProcess(argv, 0, "secret\n" if argv[1] == "lookup" else "", "")

        keyring = accounts.Keyring(runner=runner, which=lambda name: "/usr/bin/" + name)
        self.assertTrue(keyring.store("dana@example.com", "correct horse"))
        argv, stdin = calls[0]
        self.assertEqual(stdin, "correct horse")
        self.assertNotIn("correct horse", " ".join(argv))
        keyring.memory.clear()
        self.assertEqual(keyring.get("dana@example.com"), "secret")

    def test_without_a_keyring_only_memory(self):
        keyring = accounts.Keyring(which=lambda name: None)
        self.assertFalse(keyring.store("a@b.co", "pw"))
        self.assertEqual(keyring.get("a@b.co"), "pw")
        keyring.forget("a@b.co")
        self.assertIsNone(keyring.get("a@b.co"))

    def test_accounts_file_is_private_and_has_no_passwords(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            account = accounts.Account("dana@example.com", "Dana", discover.Server("imap.x.org", 993, "ssl", "dana"),
                                       discover.Server("smtp.x.org", 465, "ssl", "dana"))
            accounts.save([account], directory)
            path = directory / "accounts.json"
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn("password", path.read_text())
            self.assertEqual(accounts.load(directory)[0].incoming.host, "imap.x.org")
            path.write_text("[{\"broken\": 1}]")
            self.assertEqual(accounts.load(directory), [])


class SanitizeTests(unittest.TestCase):
    def test_nothing_runs_and_nothing_loads(self):
        dirty = ('<html><head><style>p{display:none}</style><script>alert(1)</script></head><body>'
                 '<p onclick="x()">שלום <b>Dana</b></p><img src="https://tracker.example/p.gif" width=1>'
                 '<a href="javascript:alert(1)">bad</a> <a href="https://good.example/x?a=1&b=2">good</a>'
                 '<iframe src="https://x"></iframe><form><input name=pw></form><font color=white>hidden</font></body></html>')
        safe, blocked = sanitize.clean_html(dirty)
        for gone in ("script", "alert", "onclick", "style", "tracker.example", "iframe", "input", "javascript", "color"):
            self.assertNotIn(gone, safe)
        self.assertEqual(blocked, 1)
        self.assertIn('<p dir="auto">שלום <b>Dana</b></p>', safe)
        self.assertIn('href="https://good.example/x?a=1&amp;b=2"', safe)
        self.assertIn("hidden", safe)  # the text stays, only the colour that hid it is gone

    def test_plain_text_paragraphs_find_their_direction(self):
        html = sanitize.text_to_html("שלום Dana\nHello <you>\n> quoted https://x.example/a")
        self.assertEqual(html.count('dir="auto"'), 3)
        self.assertIn("&lt;you&gt;", html)
        self.assertIn('<a href="https://x.example/a"', html)
        self.assertEqual(sanitize.html_to_text("<p>a</p><p>b<br>c</p>"), "a\nb\nc")


class ComposeTests(unittest.TestCase):
    def test_each_paragraph_keeps_its_direction(self):
        draft = compose.Draft("Dana", "dana@example.com", "Avi <avi@example.org>, x@y.co", subject="שלום",
                              paragraphs=[("שלום אבי, the report is ready.", "rtl"), ("Thanks!", "ltr"), ("", "auto")])
        built = compose.build(draft)
        html = built.get_body(("html",)).get_content()
        self.assertIn('<div dir="rtl">שלום אבי, the report is ready.</div>', html)
        self.assertIn('<div dir="ltr">Thanks!</div>', html)
        self.assertIn("שלום אבי", built.get_body(("plain",)).get_content())
        self.assertEqual(str(built["Subject"]), "שלום")
        self.assertTrue(str(built["Message-ID"]).endswith("@example.com>"))

    def test_bad_recipients_are_refused(self):
        with self.assertRaises(ValueError):
            compose.build(compose.Draft("", "a@b.co", "not-an-address"))
        good, bad = compose.recipients("a@b.co; Dana <d@e.org>, oops")
        self.assertEqual([a for _, a in good], ["a@b.co", "d@e.org"])
        self.assertEqual(bad, ["oops"])

    def test_reply_and_forward(self):
        original = {"sender": "Avi", "sender_address": "avi@example.org", "recipients": "dana@example.com, x@y.co",
                    "subject": "Re: RE: plan", "date": 0, "message_id": "<1@x>", "refs": "<0@x>"}
        draft = compose.reply(original, "line one\nline two", "dana@example.com", True, "he")
        self.assertEqual(draft.subject, "Re: plan")
        self.assertEqual(draft.to, "avi@example.org")
        self.assertEqual(draft.cc, "x@y.co")  # not me
        self.assertIn(("> line two", "auto"), draft.paragraphs)
        self.assertTrue(any("כתב/ה" in p for p, _ in draft.paragraphs))
        self.assertEqual(compose.forward(original, "x", "d@e.org", "en").subject, "Fwd: plan")


class ImapTests(unittest.TestCase):
    """Real imaplib against the fake server (plain TCP on localhost; the real code refuses that)."""

    def setUp(self):
        self.server = FakeImapServer()
        self.addCleanup(self.server.stop)
        box = self.server.mailbox
        box.add("INBOX", message(1, "Avi <avi@example.org>", "שלום דנה", "גוף ההודעה", "<p>שלום <img src=http://t/p></p>"))
        box.add("INBOX", message(2, "=?utf-8?b?15HXldeR?= <bob@example.org>", "Second", "two", day=2), "\\Seen")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "mail.sqlite"
        port = self.server.port
        self.factory = lambda server: imaplib.IMAP4("127.0.0.1", port, timeout=5)
        self.account = accounts.Account("dana@example.com", "Dana",
                                        discover.Server("127.0.0.1", port, "ssl", "dana@example.com"),
                                        discover.Server("127.0.0.1", 1, "ssl", "dana@example.com"))

    def sync(self):
        return engine.sync(self.account, "correct horse", self.db, factory=self.factory)

    def test_sync_reads_folders_roles_and_headers(self):
        result = self.sync()
        self.assertEqual(result["arrived"]["INBOX"], 2)
        self.assertEqual(self.account.folders, {"sent": "Sent", "trash": "Trash", "archive": "ארכיון"})
        store = Store(self.db)
        rows = store.listing([self.account.id], role="inbox")
        self.assertEqual([r["subject"] for r in rows], ["Second", "שלום דנה"])  # newest first
        self.assertEqual(rows[0]["sender"], "בוב")  # encoded words decoded
        self.assertEqual(store.unread([self.account.id]), 1)
        store.close()
        self.assertEqual(os.stat(self.db).st_mode & 0o777, 0o600)
        self.assertEqual(self.sync()["arrived"]["INBOX"], 0)  # only new mail the second time

    def test_open_marks_read_and_delete_moves_to_trash(self):
        self.sync()
        body = engine.open_message(self.account, "correct horse", self.db, "INBOX", 1, self.factory)
        self.assertIn("גוף ההודעה", body.text)
        self.assertIn("<img", body.html)
        self.assertIn("\\Seen", self.server.mailbox.messages["INBOX"][1][0])
        engine.delete(self.account, "correct horse", self.db, "INBOX", 1, self.factory)
        self.assertNotIn(1, self.server.mailbox.messages["INBOX"])
        self.assertEqual(len(self.server.mailbox.messages["Trash"]), 1)

    def test_server_side_changes_reach_the_copy(self):
        self.sync()
        self.server.mailbox.messages["INBOX"][1][0].add("\\Seen")
        del self.server.mailbox.messages["INBOX"][2]
        self.sync()
        store = Store(self.db)
        rows = store.listing([self.account.id], role="inbox")
        self.assertEqual([(r["uid"], r["seen"]) for r in rows], [(1, 1)])
        store.close()

    def test_a_new_uidvalidity_empties_the_folder(self):
        self.sync()
        self.server.mailbox.validity["INBOX"] = 99
        self.sync()
        store = Store(self.db)
        self.assertEqual(len(store.listing([self.account.id], role="inbox")), 2)  # fetched again, not doubled
        store.close()

    def test_wrong_password(self):
        with self.assertRaisesRegex(mail.MailError, "login"):
            engine.sync(self.account, "wrong", self.db, factory=self.factory)

    def test_send_and_keep_a_copy(self):
        self.sync()
        sent = []

        class FakeSmtp:
            def login(self, user, password):
                sent.append(("login", user))

            def send_message(self, msg):
                sent.append(("send", msg))

            def quit(self):
                pass

        draft = compose.Draft("", "", "avi@example.org", subject="Hi", paragraphs=[("שלום", "auto")])
        engine.send(self.account, "correct horse", draft, smtp_factory=lambda s: FakeSmtp(), imap_factory=self.factory)
        self.assertEqual(sent[0], ("login", "dana@example.com"))
        self.assertEqual(str(sent[1][1]["From"]), "Dana <dana@example.com>")
        self.assertEqual(len(self.server.mailbox.messages["Sent"]), 1)

    def test_only_encrypted_connections(self):
        insecure = discover.Server("127.0.0.1", self.server.port, "plain", "x")
        with self.assertRaisesRegex(mail.MailError, "insecure"):
            with mail.Imap(insecure, "pw"):
                pass
        with self.assertRaisesRegex(mail.MailError, "insecure"):
            mail.send(insecure, "pw", compose.build(compose.Draft("", "a@b.co", "c@d.co")))

    def test_tls_is_verified(self):
        # The fake server speaks no TLS: a real TLS connection to it must fail, never fall back.
        server = discover.Server("127.0.0.1", self.server.port, "ssl", "x")
        with self.assertRaises(mail.MailError):
            with mail.Imap(server, "pw"):
                pass


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PyQt6.QtWidgets import QApplication
        except ImportError:
            raise unittest.SkipTest("PyQt6 is missing")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)

    def window(self, lang="en"):
        from dai_j import gui

        keyring = accounts.Keyring(which=lambda name: None)
        return gui.MainWindow(lang, self.directory, keyring, gui.Runner(inline=True), ask_password=lambda a: None,
                              sync_on_start=False)

    def test_first_start_invites_to_add_an_account(self):
        window = self.window()
        self.assertEqual(window.stack.currentIndex(), 0)
        self.assertIn("Add account", window.empty_button.text())

    def test_hebrew_mirrors(self):
        from PyQt6.QtCore import Qt

        window = self.window("he")
        self.assertEqual(window.layoutDirection(), Qt.LayoutDirection.RightToLeft)
        self.assertEqual(window.windowTitle(), "J – דואר")

    def test_setup_finds_and_signs_in(self):
        from dai_j import gui

        keyring = accounts.Keyring(which=lambda name: None)
        checked = []
        dialog = gui.SetupDialog("en", keyring, gui.Runner(inline=True),
                                 finder=lambda a: discover.discover(a, fetch=lambda u: None, resolve=lambda *x: []),
                                 checker=lambda account, pw: checked.append(pw) or [mail.Folder("Sent", "sent")])
        dialog.address.setText("dana@gmail.com")
        dialog.secret.setText("app password")
        dialog.find()
        self.assertIn("imap.gmail.com", dialog.status.text())
        self.assertFalse(dialog.note.isHidden())  # the Gmail app-password hint
        dialog.sign_in()
        self.assertEqual(checked, ["app password"])
        self.assertEqual(dialog.account.folders, {"sent": "Sent"})
        self.assertEqual(keyring.get("dana@gmail.com"), "app password")

    def test_reading_shows_rows_and_blocks_images(self):
        from PyQt6.QtCore import Qt

        server = FakeImapServer()
        self.addCleanup(server.stop)
        server.mailbox.add("INBOX", message(1, "Avi <avi@example.org>", "שלום", "x", "<p>hi <img src=http://t/p></p>"))
        account = accounts.Account("dana@example.com", "Dana",
                                   discover.Server("127.0.0.1", server.port, "ssl", "dana@example.com"),
                                   discover.Server("127.0.0.1", 1, "ssl", "dana@example.com"))
        engine.sync(account, "correct horse", self.directory / "mail.sqlite",
                    factory=lambda s: imaplib.IMAP4("127.0.0.1", server.port, timeout=5))
        accounts.save([account], self.directory)
        window = self.window()
        self.assertEqual(window.stack.currentIndex(), 1)
        self.assertEqual(window.list.topLevelItemCount(), 1)
        item = window.list.topLevelItem(0)
        self.assertIn("Avi, שלום", item.data(0, Qt.ItemDataRole.AccessibleTextRole))
        self.assertIn("unread", item.data(0, Qt.ItemDataRole.AccessibleTextRole))
        window.show_body(mail.Body(text="", html="<p>hi <img src=http://t/p></p>"))
        self.assertIn("1 image(s) blocked", window.notice.text())

    def test_compose_directions_and_double_send(self):
        from PyQt6.QtCore import Qt

        from dai_j import gui

        account = accounts.Account("dana@example.com", "Dana", discover.Server("h.example", 993, "ssl", "d"),
                                   discover.Server("h.example", 465, "ssl", "d"))
        calls = []
        window = gui.ComposeWindow("he", [account], lambda a: "pw", gui.Runner(inline=True),
                                   sender=lambda a, p, d: calls.append(d))
        window.to.setText("avi@example.org")
        window.body.setPlainText("שלום\nHello")
        from PyQt6.QtGui import QTextCursor

        window.body.moveCursor(QTextCursor.MoveOperation.End)
        window.set_direction(Qt.LayoutDirection.RightToLeft)  # the cursor is in the last paragraph
        self.assertEqual(window.paragraphs(), [("שלום", "auto"), ("Hello", "rtl")])
        window.to.setText("nope")
        window.send()
        self.assertEqual(calls, [])
        self.assertIn("nope", window.status.text())
        window.to.setText("avi@example.org")
        window.send()
        window.send()  # a second press while sending does nothing
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
