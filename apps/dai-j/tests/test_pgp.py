# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Signed and encrypted mail (docs/MAIL.md §14), against the real GnuPG with a throwaway key."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dai_j import pgp

INNER = (b"Content-Type: text/plain; charset=utf-8\r\nContent-Transfer-Encoding: 8bit\r\n\r\n"
         + "שלום, this is signed.\r\n".encode("utf-8"))


def signed_mail(inner: bytes, signature: bytes) -> bytes:
    return (b"From: Dana <dana@example.org>\r\nSubject: signed\r\nMIME-Version: 1.0\r\n"
            b'Content-Type: multipart/signed; micalg=pgp-sha256; protocol="application/pgp-signature"; boundary="XyZ"\r\n'
            b"\r\n--XyZ\r\n" + inner + b"\r\n--XyZ\r\nContent-Type: application/pgp-signature\r\n\r\n" + signature
            + b"\r\n--XyZ--\r\n")


@unittest.skipUnless(shutil.which("gpg"), "gpg is not installed")
class KeyHome(unittest.TestCase):
    """A throwaway GnuPG home with one key, Dana's."""

    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp()
        os.chmod(cls.home, 0o700)
        cls.env = mock.patch.dict(os.environ, {"GNUPGHOME": cls.home})
        cls.env.start()
        subprocess.run(["gpg", "--batch", "--pinentry-mode", "loopback", "--passphrase", "", "--quick-gen-key",
                        "Dana Test <dana@example.org>", "default", "default", "1d"], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        subprocess.run(["gpgconf", "--homedir", cls.home, "--kill", "all"], capture_output=True)
        shutil.rmtree(cls.home, ignore_errors=True)

    def sign(self, data: bytes) -> bytes:
        return subprocess.run(["gpg", "--batch", "--pinentry-mode", "loopback", "--passphrase", "", "--armor",
                               "--detach-sign", "--digest-algo", "SHA256"], input=data, capture_output=True,
                              check=True).stdout



@unittest.skipUnless(shutil.which("gpg"), "gpg is not installed")
class GnuPGTests(KeyHome):
    def test_a_good_signature(self):
        raw = signed_mail(INNER, self.sign(INNER))
        self.assertEqual(pgp.kind(raw), "signed")
        result = pgp.verify(raw)
        self.assertEqual(result.state, "good")
        self.assertIn("Dana Test", result.who)
        self.assertEqual(len(result.fingerprint), 40)
        self.assertTrue(result.trusted)  # our own key: ultimately trusted

    def test_a_changed_message_is_caught(self):
        signature = self.sign(INNER)
        changed = INNER.replace("signed".encode(), b"forged")
        self.assertEqual(pgp.verify(signed_mail(changed, signature)).state, "bad")

    def test_lf_and_crlf_are_the_same_message(self):
        raw = signed_mail(INNER, self.sign(INNER)).replace(b"\r\n", b"\n")  # stored with Unix line ends
        self.assertEqual(pgp.verify(raw).state, "good")

    def test_a_key_we_do_not_have(self):
        other = tempfile.mkdtemp()
        os.chmod(other, 0o700)
        self.addCleanup(shutil.rmtree, other, True)
        env = {**os.environ, "GNUPGHOME": other}
        subprocess.run(["gpg", "--batch", "--pinentry-mode", "loopback", "--passphrase", "", "--quick-gen-key",
                        "Mallory <m@example.org>", "default", "default", "1d"], check=True, capture_output=True, env=env)
        signature = subprocess.run(["gpg", "--batch", "--pinentry-mode", "loopback", "--passphrase", "", "--armor",
                                    "--detach-sign"], input=INNER, capture_output=True, check=True, env=env).stdout
        subprocess.run(["gpgconf", "--homedir", other, "--kill", "all"], capture_output=True)
        self.assertEqual(pgp.verify(signed_mail(INNER, signature)).state, "unknown_key")

    def test_decrypt_shows_and_never_saves(self):
        armored = subprocess.run(["gpg", "--batch", "--armor", "--trust-model", "always", "--encrypt", "-r",
                                  "dana@example.org"], input=INNER, capture_output=True, check=True).stdout
        raw = (b"From: Dana <dana@example.org>\r\nSubject: secret\r\nMIME-Version: 1.0\r\n"
               b'Content-Type: multipart/encrypted; protocol="application/pgp-encrypted"; boundary="AbC"\r\n\r\n'
               b"--AbC\r\nContent-Type: application/pgp-encrypted\r\n\r\nVersion: 1\r\n"
               b"--AbC\r\nContent-Type: application/octet-stream\r\n\r\n" + armored + b"\r\n--AbC--\r\n")
        self.assertEqual(pgp.kind(raw), "encrypted")
        before = set(Path(tempfile.gettempdir()).iterdir())
        inner = pgp.decrypt(raw)
        self.assertIn("שלום, this is signed.".encode(), inner)
        self.assertEqual(set(Path(tempfile.gettempdir()).iterdir()) - before, set())  # nothing left on disk
        lines = armored.split(b"\n")
        body = next(i for i, line in enumerate(lines) if len(line) > 40)  # the first full line of the data
        lines[body] = bytes(reversed(lines[body]))
        damaged = raw.replace(armored, b"\n".join(lines))
        self.assertNotEqual(damaged, raw)
        self.assertIsNone(pgp.decrypt(damaged))  # damaged: nothing, no crash


class WithoutGnuPGTests(unittest.TestCase):
    def test_no_signature_no_check(self):
        self.assertIsNone(pgp.verify(b"From: a@b\r\nSubject: plain\r\n\r\nhello"))
        self.assertEqual(pgp.kind(b"Subject: x\r\n\r\n-----BEGIN PGP SIGNED MESSAGE-----\r\n"), "inline_signed")

    def test_gpg_missing_is_an_error_not_a_crash(self):
        def missing(argv, **kwargs):
            raise FileNotFoundError(argv[0])
        raw = signed_mail(INNER, b"-----BEGIN PGP SIGNATURE-----\r\n...\r\n")
        self.assertEqual(pgp.verify(raw, run=missing).state, "error")

    def test_status_lines_from_a_hostile_signer(self):
        out = "[GNUPG:] GOODSIG ABCD Dana‮ <evil>\n[GNUPG:] VALIDSIG " + "A" * 40 + " x\n"
        result = pgp._status(out, smime=False)
        self.assertEqual((result.state, result.who), ("good", "Dana <evil>"))
        self.assertFalse(result.trusted)  # a good signature from a key nobody vouched for


@unittest.skipUnless(shutil.which("gpg"), "gpg is not installed")
class SendingTests(KeyHome):
    """Signing and encrypting what is sent (docs/MAIL.md §15), checked with J's own reading side."""

    def draft(self, to="Dana Test <dana@example.org>", **flags):
        from dai_j import compose

        return compose.Draft("Dana Test", "dana@example.org", to, subject="Plan",
                             paragraphs=[("שלום, this is the plan.", "rtl"), ("Second line", "ltr")], **flags)

    def test_signed_is_good_and_still_reads(self):
        from dai_j import compose, mail

        raw = pgp.protect(compose.build(self.draft()), sign=True, encrypt=False)
        self.assertEqual(pgp.kind(raw), "signed")
        self.assertNotRegex(raw, rb"[^\x00-\x7f]")  # 7-bit safe, so no server re-encodes what was signed
        self.assertNotRegex(raw, rb"(?<!\r)\n")    # canonical CRLF
        check = pgp.verify(raw)
        self.assertEqual((check.state, check.trusted), ("good", True))
        self.assertIn("this is the plan", mail.parse_body(raw).text)
        self.assertIn(b"Subject: Plan", raw)
        tampered = raw.replace(b"Second line", b"Second lime")
        self.assertEqual(pgp.verify(tampered).state, "bad")

    def test_encrypted_and_signed_decrypt_to_the_message(self):
        from dai_j import compose, mail

        for sign in (False, True):
            raw = pgp.protect(compose.build(self.draft()), sign=sign, encrypt=True)
            self.assertEqual(pgp.kind(raw), "encrypted")
            self.assertNotIn(b"this is the plan", raw)
            self.assertIn(b"\r\nSubject: ...\r\n", raw)  # protected headers: the real subject only inside
            self.assertNotIn(b"Plan", raw)
            inner = pgp.decrypt(raw)
            self.assertIn("this is the plan", mail.parse_body(inner).text)
            self.assertEqual(pgp.protected_subject(inner), "Plan")
        self.assertEqual(pgp.protected_subject(b"Content-Type: text/plain\r\nSubject: forged\r\n\r\nx"), "")

    def test_a_recipient_without_a_key_stops_it(self):
        from dai_j import compose

        with self.assertRaises(pgp.ProtectError) as caught:
            pgp.protect(compose.build(self.draft(to="nobody@example.net")), sign=False, encrypt=True)
        self.assertEqual(str(caught.exception), "recipient_key")
        message = compose.build(compose.Draft("X", "x@example.net", "dana@example.org", paragraphs=[("hi", "auto")]))
        with self.assertRaises(pgp.ProtectError) as caught:
            pgp.protect(message, sign=True, encrypt=False)
        self.assertEqual(str(caught.exception), "own_key")

    def test_engine_sends_exactly_those_bytes(self):
        from dai_j import accounts, discover, engine

        sent = []

        class FakeSmtp:
            def login(self, user, password):
                pass

            def sendmail(self, sender, rcpt, raw):
                sent.append((sender, rcpt, raw))

            def quit(self):
                pass

        server = discover.Server("smtp.example.org", 465, "ssl", "dana@example.org")
        account = accounts.Account(address="dana@example.org", name="Dana Test", incoming=server, outgoing=server)
        engine.send(account, "pw", self.draft(sign=True), smtp_factory=lambda s: FakeSmtp())
        sender, rcpt, raw = sent[0]
        self.assertEqual((sender, rcpt), ("dana@example.org", ["dana@example.org"]))
        self.assertEqual(pgp.verify(raw).state, "good")
        with self.assertRaisesRegex(Exception, "pgp_recipient_key"):
            engine.send(account, "pw", self.draft(to="nobody@example.net", encrypt=True),
                        smtp_factory=lambda s: FakeSmtp())
        self.assertEqual(len(sent), 1)  # nothing left the computer


@unittest.skipUnless(shutil.which("gpgsm"), "gpgsm is not installed")
class SmimeSendingTests(unittest.TestCase):
    """Signing with an S/MIME certificate (docs/MAIL.md §15), a throwaway self-signed one trusted only here."""

    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp()
        os.chmod(cls.home, 0o700)
        cls.env = mock.patch.dict(os.environ, {"GNUPGHOME": cls.home})
        cls.env.start()
        params = Path(cls.home) / "params"
        params.write_text("Key-Type: RSA\nKey-Length: 2048\nKey-Usage: sign, encrypt\nSerial: random\n"
                          "Name-DN: CN=Dana Test\nName-Email: dana@example.org\n")
        loop = ["--batch", "--pinentry-mode", "loopback", "--passphrase", ""]
        # Never waits for a passphrase: loopback with an empty one, and stdin closed (an inherited open stdin is
        # where gpgsm would otherwise wait for it).
        made = subprocess.run(["gpgsm", *loop, "--generate-key", str(params)], capture_output=True,
                              stdin=subprocess.DEVNULL, timeout=180)
        if made.returncode != 0 or not made.stdout:
            raise AssertionError("gpgsm could not make the test certificate: " + made.stderr.decode(errors="replace"))
        cert = made.stdout
        subprocess.run(["gpgsm", "--batch", "--import"], input=cert, capture_output=True, check=True, timeout=60)
        listing = subprocess.run(["gpgsm", "--with-colons", "--list-secret-keys"], capture_output=True, text=True,
                                 stdin=subprocess.DEVNULL, timeout=60).stdout
        fingerprint = next(line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr"))
        (Path(cls.home) / "trustlist.txt").write_text(f"{fingerprint} S relax\n")
        (Path(cls.home) / "gpgsm.conf").write_text("disable-crl-checks\npinentry-mode loopback\n")
        (Path(cls.home) / "gpg-agent.conf").write_text("allow-loopback-pinentry\n")
        subprocess.run(["gpgconf", "--homedir", cls.home, "--kill", "gpg-agent"], capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        subprocess.run(["gpgconf", "--homedir", cls.home, "--kill", "all"], capture_output=True)
        shutil.rmtree(cls.home, ignore_errors=True)

    def test_signed_with_the_certificate_and_checked(self):
        from dai_j import compose, mail

        draft = compose.Draft("Dana Test", "dana@example.org", "avi@example.net", subject="Plan",
                              paragraphs=[("שלום, signed with S/MIME.", "rtl")])
        self.assertEqual(pgp.signing_method("dana@example.org"), "smime")  # no OpenPGP key here, a certificate
        self.assertEqual(pgp.signing_method("nobody@example.net"), "")
        raw = pgp.protect(compose.build(draft), sign=True, encrypt=False)
        self.assertEqual(pgp.kind(raw), "smime_signed")
        self.assertRegex(raw, rb'micalg="?sha-256')
        check = pgp.verify(raw)
        self.assertEqual((check.state, check.kind), ("good", "smime"))
        self.assertIn("signed with S/MIME", mail.parse_body(raw).text)
        self.assertEqual(pgp.verify(raw.replace(b"S/MIME.", b"S/MIME!")).state, "bad")

    def test_encrypted_with_certificates_and_decrypted(self):
        from dai_j import compose, mail

        draft = compose.Draft("Dana Test", "dana@example.org", "dana@example.org", subject="Plan",
                              paragraphs=[("סוד, encrypted with S/MIME.", "rtl")])
        for sign in (False, True):
            raw = pgp.protect(compose.build(draft), sign=sign, encrypt=True)  # no OpenPGP key: S/MIME by itself
            self.assertEqual(pgp.kind(raw), "smime_encrypted")
            self.assertNotIn(b"encrypted with S/MIME", raw)
            self.assertNotIn(b"Plan", raw)  # the subject only inside
            inner = pgp.decrypt(raw)
            self.assertIn("encrypted with S/MIME", mail.parse_body(inner).text)
            self.assertEqual(pgp.protected_subject(inner), "Plan")
            if sign:
                self.assertEqual(pgp.kind(inner), "smime_signed")
                self.assertEqual(pgp.verify(inner).state, "good")
        with self.assertRaises(pgp.ProtectError):
            pgp.protect(compose.build(compose.Draft("Dana Test", "dana@example.org", "nobody@example.net",
                                                    paragraphs=[("x", "auto")])), sign=False, encrypt=True)


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PyQt6.QtWidgets import QApplication
        except ImportError:
            raise unittest.SkipTest("PyQt6 is missing")
        cls.app = QApplication.instance() or QApplication([])

    def window(self, directory, raw):
        import mailbox
        from dai_j import accounts, gui, localmail

        path = Path(directory) / "box.mbox"
        box = mailbox.mbox(path)
        box.add(mailbox.mboxMessage(raw))
        box.flush()
        box.close()
        window = gui.MainWindow("en", Path(directory), accounts.Keyring(which=lambda name: None),
                                gui.Runner(inline=True), ask_password=lambda a: None, sync_on_start=False)
        self.addCleanup(window.close)
        window.import_mail([localmail.source_for_path(path)])
        window.folders.setCurrentItem(window._find_folder(("folder", "Imported/box", localmail.LOCAL)))
        window.show_folder()
        window.list.setCurrentItem(window.list.topLevelItem(0))
        return window

    def test_the_signature_in_plain_words(self):
        raw = signed_mail(INNER, b"-----BEGIN PGP SIGNATURE-----\r\nAA==\r\n-----END PGP SIGNATURE-----\r\n")
        cases = [(pgp.Signature("good", "Dana <dana@example.org>", "A" * 40, trusted=True), "Signed by"),
                 (pgp.Signature("good", "<b>Dana</b>", "A" * 40), "not confirmed"),
                 (pgp.Signature("bad", "Dana"), "does not match"),
                 (pgp.Signature("unknown_key"), "not on this computer")]
        with tempfile.TemporaryDirectory() as tmp:
            window = self.window(tmp, raw)
            for signature, words in cases:
                with mock.patch.object(pgp, "verify", return_value=signature):
                    window.open_current()
                self.assertIn(words, window.security.text())
                self.assertTrue(window.security.isVisibleTo(window))
                if "<b>" in signature.who:
                    self.assertIn("<b>Dana</b>", window.security.text())  # a plain-text label: never markup
            self.assertFalse(window.decrypt_button.isVisibleTo(window))

    def test_decrypted_is_shown_and_the_store_keeps_it_encrypted(self):
        from dai_j import localmail

        raw = (b"From: Dana <dana@example.org>\r\nSubject: secret\r\nMIME-Version: 1.0\r\n"
               b'Content-Type: multipart/encrypted; protocol="application/pgp-encrypted"; boundary="B"\r\n\r\n'
               b"--B\r\nContent-Type: application/pgp-encrypted\r\n\r\nVersion: 1\r\n"
               b"--B\r\nContent-Type: application/octet-stream\r\n\r\n-----BEGIN PGP MESSAGE-----\r\nAA==\r\n"
               b"-----END PGP MESSAGE-----\r\n--B--\r\n")
        with tempfile.TemporaryDirectory() as tmp:
            window = self.window(tmp, raw)
            window.open_current()
            self.assertIn("encrypted", window.security.text())
            self.assertTrue(window.decrypt_button.isVisibleTo(window))
            with mock.patch.object(pgp, "decrypt", return_value=None):
                window.decrypt_current()
            self.assertIn("Could not decrypt", window.security.text())
            protected = (b'Content-Type: text/plain; charset=utf-8; protected-headers="v1"\r\nSubject: The real one\r\n\r\n'
                         b"this is signed\r\n")
            with mock.patch.object(pgp, "decrypt", return_value=protected):
                window.decrypt_current()
            self.assertIn("this is signed", window.reader.toPlainText())
            self.assertEqual(window.header.text().split("\n")[-1], "The real one")
            self.assertFalse(window.decrypt_button.isVisibleTo(window))
            row = window.current
            kept = window.store.body(localmail.LOCAL, row["folder"], row["uid"])
            self.assertIn(b"BEGIN PGP MESSAGE", kept)
            self.assertNotIn("this is signed".encode(), kept)


if __name__ == "__main__":
    unittest.main()
