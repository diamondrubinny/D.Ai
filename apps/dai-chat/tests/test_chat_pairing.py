# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Becoming contacts (dai_chat/pairing.py) over real sockets: both codes typed, one code missing, someone else
answering at the address, a forged request, and a first message right after pairing."""
import asyncio
import importlib.util
import tempfile
import unittest
from pathlib import Path

if importlib.util.find_spec("nacl") is None:  # python3-nacl, in Debian
    raise unittest.SkipTest("PyNaCl is missing")

from dai_chat import invite, keys, message, pairing, sas, store, transport


class Person:
    def __init__(self, folder: Path, name: str) -> None:
        self.name, self.identity = name, keys.Identity.generate()
        self.service = keys.Identity.generate().public  # the onion service key
        self.store = store.Store(folder / name)
        self.paired = []
        self.node = transport.Node(self.identity, self.store, service=self.service, idle_timeout=5,
                                   on_paired=self.paired.append)
        self.code = invite.make(self.service, self.identity.public)

    def types(self, other: "Person") -> invite.Invite:
        theirs = invite.parse(other.code)
        self.store.wait_for(theirs, other.name)
        return theirs


class PairingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.alice, self.bob = Person(Path(self.tmp.name), "Alice"), Person(Path(self.tmp.name), "Bob")
        for person in (self.alice, self.bob):
            self.addCleanup(person.store.close)
        self.server = await asyncio.start_server(self.bob.node.handle, "127.0.0.1", 0)
        self.addAsyncCleanup(self.server.wait_closed)
        self.addCleanup(self.server.close)
        self.at = transport.tcp("127.0.0.1", self.server.sockets[0].getsockname()[1])

    async def test_both_typed_the_codes(self):
        bobs = self.alice.types(self.bob)
        self.bob.types(self.alice)
        contact = await self.alice.node.pair(bobs, self.at)
        self.assertEqual(contact.public, self.bob.identity.public)
        self.assertFalse(contact.verified)  # until the six symbols are compared
        self.assertEqual(contact.onion, invite.onion_address(self.bob.service))
        await asyncio.sleep(0.05)
        theirs = self.bob.store.contact(self.alice.identity.public)
        self.assertEqual((theirs.name, theirs.verified), ("Alice", False))
        self.assertEqual(self.bob.paired[0].public, self.alice.identity.public)
        self.assertEqual((self.alice.store.waiting(), self.bob.store.waiting()), ([], []))
        self.assertEqual(sas.symbols(self.alice.identity.public, contact.public),
                         sas.symbols(theirs.public, self.bob.identity.public))
        # and now they can talk
        hello = message.Message.text("שלום")
        self.alice.store.add_message(contact.public, hello, outgoing=True, state="queued")
        self.assertEqual((await self.alice.node.deliver(contact.public, self.at)).sent, [hello.id])

    async def test_bob_has_not_typed_alices_code_yet(self):
        bobs = self.alice.types(self.bob)
        with self.assertRaises(transport.TransportError):
            await self.alice.node.pair(bobs, self.at)
        self.assertEqual(self.bob.store.contacts(), [])
        self.assertEqual(len(self.alice.store.waiting()), 1)  # still waiting: try again later

    async def test_someone_else_at_the_address(self):
        carol = Person(Path(self.tmp.name), "Carol")
        self.addCleanup(carol.store.close)
        carol.store.wait_for(invite.parse(self.alice.code), "Alice")
        server = await asyncio.start_server(carol.node.handle, "127.0.0.1", 0)
        self.addAsyncCleanup(server.wait_closed)
        self.addCleanup(server.close)
        bobs = self.alice.types(self.bob)
        with self.assertRaises(transport.TransportError):
            await self.alice.node.pair(bobs, transport.tcp("127.0.0.1", server.sockets[0].getsockname()[1]))
        self.assertEqual(self.alice.store.contacts(), [])

    def test_a_forged_request(self):
        alice, bob, mallory = keys.Identity.generate(), keys.Identity.generate(), keys.Identity.generate()
        service = keys.Identity.generate().public
        alices = invite.parse(invite.make(service, alice.public))
        bobs = invite.parse(invite.make(service, bob.public))
        good = pairing.request(alice, service, bobs)
        waiting = {alices.fingerprint: alices}.get
        forged = good[:65] + mallory.sign(b"x")  # Alice's keys, someone else's signature
        with self.assertRaises(pairing.PairingError):
            pairing.answer(bob, service, forged, waiting)
        other_service = good[:33] + keys.Identity.generate().public + good[65:]  # a different onion address
        with self.assertRaises(pairing.PairingError):
            pairing.answer(bob, service, other_service, waiting)
        meant_for_carol = pairing.request(alice, service, invite.parse(invite.make(service, mallory.public)))
        with self.assertRaises(pairing.PairingError):
            pairing.answer(bob, service, meant_for_carol, waiting)  # signed for someone else's code
        ack, public, _ = pairing.answer(bob, service, good, waiting)
        self.assertEqual(public, alice.public)
        self.assertEqual(pairing.finish(alice, bobs, ack), bob.public)
        with self.assertRaises(pairing.PairingError):
            pairing.finish(mallory, bobs, ack)  # an answer to Alice is not an answer to Mallory


if __name__ == "__main__":
    unittest.main()
