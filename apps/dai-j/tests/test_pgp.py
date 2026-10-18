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
class GnuPGTests(unittest.TestCase):
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
            with mock.patch.object(pgp, "decrypt", return_value=INNER):
                window.decrypt_current()
            self.assertIn("this is signed", window.reader.toPlainText())
            self.assertFalse(window.decrypt_button.isVisibleTo(window))
            row = window.current
            kept = window.store.body(localmail.LOCAL, row["folder"], row["uid"])
            self.assertIn(b"BEGIN PGP MESSAGE", kept)
            self.assertNotIn("this is signed".encode(), kept)


if __name__ == "__main__":
    unittest.main()
