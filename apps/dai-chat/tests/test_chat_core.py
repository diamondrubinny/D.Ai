# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Diamond Chat's core (docs/SEND.md): keys, the handshake, the session, symbols, invitations, messages, storage.

The attacks tried here: an impostor, a replayed or altered message, a message out of order, a HELLO sent to
someone else, a weak ephemeral key, a forged picture, a path in a message id.
"""
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

import importlib.util

if importlib.util.find_spec("nacl") is None:  # python3-nacl, in Debian
    raise unittest.SkipTest("PyNaCl is missing")

from dai_chat import invite, keys, message, sas, session, store

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def pair():
    alice, bob = keys.Identity.generate(), keys.Identity.generate()
    return alice, bob


def connect(alice, bob, known=None):
    initiator = session.Initiator(alice, bob.public)
    responder = session.Responder(bob, known or (lambda public: public == alice.public))
    reply, bob_side = responder.answer(initiator.hello())
    return initiator.finish(reply), bob_side


class HandshakeTests(unittest.TestCase):
    def test_both_sides_talk(self):
        alice, bob = pair()
        a, b = connect(alice, bob)
        self.assertEqual(b.open(a.seal(b"hello Bob")), b"hello Bob")
        self.assertEqual(a.open(b.seal("שלום אליס".encode())), "שלום אליס".encode())
        self.assertEqual((a.peer, b.peer), (bob.public, alice.public))
        for _ in range(5):
            self.assertEqual(b.open(a.seal(b"x")), b"x")

    def test_each_session_has_new_keys(self):
        alice, bob = pair()
        first, _ = connect(alice, bob)
        second, _ = connect(alice, bob)
        self.assertNotEqual(first.send_key, second.send_key)  # fresh ephemerals: forward secrecy

    def test_strangers_are_refused(self):
        alice, bob = pair()
        with self.assertRaises(session.HandshakeError):
            connect(alice, bob, known=lambda public: False)

    def test_an_impostor_cannot_answer_for_bob(self):
        alice, bob = pair()
        mallory = keys.Identity.generate()
        initiator = session.Initiator(alice, bob.public)
        hello = initiator.hello()
        # Mallory sits in the middle and answers with her own key (she does not have Bob's)
        with self.assertRaises(session.HandshakeError):
            session.Responder(mallory, lambda p: True).answer(hello)  # the HELLO names Bob, not Mallory
        reply, _ = session.Responder(bob, lambda p: True).answer(hello)
        forged = reply[:32] + mallory.sign(b"anything")
        with self.assertRaises(session.HandshakeError):
            initiator.finish(forged)

    def test_hello_cannot_be_replayed_to_someone_else(self):
        alice, bob = pair()
        carol = keys.Identity.generate()
        hello = session.Initiator(alice, bob.public).hello()
        with self.assertRaises(session.HandshakeError):
            session.Responder(carol, lambda p: True).answer(hello)

    def test_a_reply_belongs_to_one_hello(self):
        alice, bob = pair()
        old = session.Initiator(alice, bob.public)
        old_reply, _ = session.Responder(bob, lambda p: True).answer(old.hello())
        fresh = session.Initiator(alice, bob.public)
        fresh.hello()
        with self.assertRaises(session.HandshakeError):
            fresh.finish(old_reply)

    def test_garbage_and_other_versions(self):
        alice, bob = pair()
        responder = session.Responder(bob, lambda p: True)
        hello = session.Initiator(alice, bob.public).hello()
        for bad in (b"", b"x" * 10, bytes([2]) + hello[1:], hello[:-1]):
            with self.assertRaises(session.HandshakeError):
                responder.answer(bad)

    def test_a_weak_ephemeral_key_is_refused(self):
        alice, bob = pair()
        initiator = session.Initiator(alice, bob.public)
        initiator.hello()
        zero = bytes(32)  # a low-order point: X25519 would give an all-zero, publicly known secret
        reply = zero + bob.sign(b"dai-chat/1" + b"reply" + zero + bytes(initiator._ephemeral.public_key) + alice.public)
        with self.assertRaises(session.HandshakeError):
            initiator.finish(reply)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.a, self.b = connect(*pair())

    def test_altered_messages_fail(self):
        frame = bytearray(self.a.seal(b"meet at 6"))
        frame[3] ^= 1
        with self.assertRaises(session.SessionError):
            self.b.open(bytes(frame))

    def test_replay_and_reordering_fail(self):
        self.a.seal(b"one")
        second = self.a.seal(b"two")
        with self.assertRaises(session.SessionError):
            self.b.open(second)  # out of order
        a, b = connect(*pair())
        frame = a.seal(b"once")
        b.open(frame)
        with self.assertRaises(session.SessionError):
            b.open(frame)  # the same message again

    def test_directions_are_separate(self):
        frame = self.a.seal(b"to bob")
        with self.assertRaises(session.SessionError):
            self.a.open(frame)  # reflected back to Alice

    def test_closed_session_forgets_its_keys(self):
        self.a.close()
        self.assertEqual((self.a.send_key, self.a.receive_key), (b"", b""))


class SymbolTests(unittest.TestCase):
    def test_same_symbols_on_both_sides_and_different_for_others(self):
        alice, bob = pair()
        mallory = keys.Identity.generate()
        self.assertEqual(sas.symbols(alice.public, bob.public), sas.symbols(bob.public, alice.public))
        self.assertNotEqual(sas.symbols(alice.public, bob.public), sas.symbols(alice.public, mallory.public))
        self.assertEqual(len(sas.symbols(alice.public, bob.public)), 6)
        self.assertEqual(len({s[0] for s in sas.SYMBOLS}), 64)  # no two alike
        self.assertIn("יהלום", sas.describe([0], "he"))
        self.assertIn("diamond", sas.describe([0], "ru"))  # no Russian names yet: English


class InviteTests(unittest.TestCase):
    def test_round_trip_and_typos(self):
        alice = keys.Identity.generate()
        service = keys.Identity.generate().public
        code = invite.make(service, alice.public)
        self.assertTrue(code.startswith("dai1-"))
        parsed = invite.parse(code.upper().replace("-", " - "))
        self.assertTrue(parsed.matches(alice.public))
        self.assertFalse(parsed.matches(keys.Identity.generate().public))
        self.assertTrue(parsed.onion.endswith(".onion") and len(parsed.onion) == 62)
        typos = [code[:i] + ("a" if code[i] != "a" else "b") + code[i + 1:] for i in range(5, len(code)) if code[i] != "-"]
        for bad in (*typos, "hello", "dai1-", code[:-4]):
            with self.assertRaises(invite.InviteError):
                invite.parse(bad)

    def test_onion_address_of_a_known_key(self):
        # Tor's own example key from rend-spec-v3 test vectors would be ideal; this checks the shape and checksum
        address = invite.onion_address(bytes(range(32)))
        self.assertRegex(address, r"^[a-z2-7]{56}\.onion$")
        self.assertTrue(address[:-6].endswith("d"))  # version 3 ends the encoded form


class MessageTests(unittest.TestCase):
    def test_round_trips(self):
        for original in (message.Message.text("שלום 👋"), message.Message.picture(PNG, "image/png"),
                         message.Message.receipt("a" * 32, "seen")):
            again = message.decode(original.encode())
            self.assertEqual((again.kind, again.body, again.id, again.mime, again.state),
                             (original.kind, original.body, original.id, original.mime, original.state))

    def test_lies_and_limits(self):
        with self.assertRaises(message.MessageError):
            message.Message.picture(b"MZ\x90\x00 an exe", "image/png").encode()  # says PNG, is not
        with self.assertRaises(message.MessageError):
            message.Message.picture(PNG, "image/svg+xml").encode()  # SVG can carry scripts: not allowed
        with self.assertRaises(message.MessageError):
            message.Message.text("x" * (message.MAX_TEXT + 1)).encode()
        bad_id = message.Message.text("hi")
        bad_id.id = "../../etc/passwd"
        with self.assertRaises(message.MessageError):
            bad_id.encode()
        for junk in (b"", b"\x01\xff\xff\xff\xff", b"\x09\x00\x00\x00\x02{}"):
            with self.assertRaises(message.MessageError):
                message.decode(junk)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = store.Store(Path(self.tmp.name) / "chat")
        self.addCleanup(self.store.close)
        self.dana = keys.Identity.generate().public
        self.store.add_contact(store.Contact(self.dana, "Dana"))

    def test_private_files(self):
        folder = Path(self.tmp.name) / "chat"
        self.assertEqual(stat.S_IMODE(folder.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((folder / "chat.db").stat().st_mode), 0o600)
        picture = message.Message.picture(PNG, "image/png")
        self.store.add_message(self.dana, picture, outgoing=False, state="delivered")
        saved = folder / "pictures" / f"{self.dana.hex()[:16]}-{picture.id}.png"
        self.assertEqual(stat.S_IMODE(saved.stat().st_mode), 0o600)

    def test_history_queue_and_delete(self):
        hello = message.Message.text("hi")
        self.store.add_message(self.dana, hello, outgoing=True, state="queued")
        self.store.add_message(self.dana, hello, outgoing=True, state="queued")  # a retry: kept once
        self.assertEqual(self.store.queued(self.dana), [hello.id])
        self.store.set_state(self.dana, hello.id, "delivered")
        self.assertEqual(self.store.queued(self.dana), [])
        self.store.add_message(self.dana, message.Message.picture(PNG, "image/png"), outgoing=False, state="seen")
        self.assertEqual(len(self.store.conversation(self.dana)), 2)
        self.assertEqual(self.store.delete_conversation(self.dana), 2)
        self.assertEqual(list((Path(self.tmp.name) / "chat" / "pictures").iterdir()), [])

    def test_only_known_unblocked_contacts(self):
        self.assertTrue(self.store.may_talk(self.dana))
        self.assertFalse(self.store.may_talk(keys.Identity.generate().public))
        self.store.set_blocked(self.dana)
        self.assertFalse(self.store.may_talk(self.dana))


class KeyStorageTests(unittest.TestCase):
    def test_file_fallback_is_private_and_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chat" / "identity"
            first, where = keys.load_or_create([keys.FileStore(path)])
            again, _ = keys.load_or_create([keys.FileStore(path)])
            self.assertEqual((first.public, where), (again.public, "file"))
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_keyring_first_and_the_seed_never_on_a_command_line(self):
        kept, calls = {}, []

        def secret_tool(argv, **kwargs):
            calls.append(argv)
            if argv[1] == "store":
                kept["seed"] = kwargs["input"]
                return subprocess.CompletedProcess(argv, 0, "", "")
            if argv[1] == "lookup" and "seed" in kept:
                return subprocess.CompletedProcess(argv, 0, kept["seed"], "")
            return subprocess.CompletedProcess(argv, 1, "", "")

        with tempfile.TemporaryDirectory() as tmp:
            file_store = keys.FileStore(Path(tmp) / "identity")
            identity, where = keys.load_or_create([keys.KeyringStore(secret_tool), file_store])
            self.assertEqual(where, "keyring")
            self.assertFalse(file_store.path.exists())
            again, _ = keys.load_or_create([keys.KeyringStore(secret_tool), file_store])
            self.assertEqual(identity.public, again.public)
        self.assertTrue(all(kept["seed"] not in " ".join(argv) for argv in calls))

    def test_signatures(self):
        alice = keys.Identity.generate()
        signature = alice.sign(b"x")
        self.assertTrue(keys.verify(alice.public, b"x", signature))
        self.assertFalse(keys.verify(alice.public, b"y", signature))
        self.assertFalse(keys.verify(b"short", b"x", signature))


if __name__ == "__main__":
    unittest.main()
