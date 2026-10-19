# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Diamond Chat over real sockets (docs/SEND.md §0): two people, each with their own keys and store.

Tried here: delivery both ways with receipts, a resend kept once, a picture from an unverified contact,
a stranger, an offline contact, a byte changed on the way, two big pictures crossing, a receipt from the
wrong person, too many attempts, and Tor's SOCKS5 handshake.
"""
import asyncio
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

if importlib.util.find_spec("nacl") is None:  # python3-nacl, in Debian
    raise unittest.SkipTest("PyNaCl is missing")

from dai_chat import keys, message, pictures, store, transport

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class Person:
    def __init__(self, folder: Path, name: str) -> None:
        self.name, self.identity = name, keys.Identity.generate()
        self.store = store.Store(folder / name)
        self.arrived = []
        self.cleaned = []
        self.receiving = True
        self.node = transport.Node(self.identity, self.store, lambda peer, m, state: self.arrived.append(m),
                                   idle_timeout=5, clean=self.clean, accepting=lambda: self.receiving)

    def clean(self, data: bytes):  # stands in for the sandbox (pictures.py has its own tests)
        self.cleaned.append(len(data))
        if b"EVIL" in data:
            raise pictures.PictureError("could not be read")
        return data, "image/png"

    def knows(self, other: "Person", verified: bool = True, accepted: bool = True) -> None:
        self.store.add_contact(store.Contact(other.identity.public, other.name, verified=verified, accepted=accepted))

    def write(self, other: "Person", item: message.Message) -> message.Message:
        self.store.add_message(other.identity.public, item, outgoing=True, state="queued")
        return item


class Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.alice, self.bob = Person(Path(self.tmp.name), "Alice"), Person(Path(self.tmp.name), "Bob")
        for person in (self.alice, self.bob):
            self.addCleanup(person.store.close)
        self.alice.knows(self.bob)
        self.bob.knows(self.alice)
        self.server = await asyncio.start_server(self.bob.node.handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()

    async def send(self, port=None):
        return await asyncio.wait_for(
            self.alice.node.deliver(self.bob.identity.public, transport.tcp("127.0.0.1", port or self.port)), 20)


class DeliveryTests(Base):
    async def test_both_ways_with_receipts(self):
        hello = self.alice.write(self.bob, message.Message.text("שלום בוב"))
        answer = self.bob.write(self.alice, message.Message.text("hi Alice"))
        result = await self.send()
        self.assertEqual(result.sent, [hello.id])
        self.assertEqual([m.body for m in result.received], [b"hi Alice"])
        self.assertEqual([m.body.decode() for m in self.bob.arrived], ["שלום בוב"])
        self.assertEqual(self.alice.store.queued(self.bob.identity.public), [])
        await asyncio.sleep(0.1)  # Bob's side finishes after Alice's
        self.assertEqual(self.bob.store.queued(self.alice.identity.public), [])
        states = {m["id"]: m["state"] for m in self.bob.store.conversation(self.alice.identity.public)}
        self.assertEqual(states, {hello.id: "delivered", answer.id: "delivered"})

    async def test_nothing_to_say_is_fine_and_a_resend_is_kept_once(self):
        self.assertEqual((await self.send()).sent, [])
        hello = self.alice.write(self.bob, message.Message.text("once"))
        await self.send()
        self.alice.store.set_state(self.bob.identity.public, hello.id, "queued")  # as if the receipt was lost
        await self.send()
        self.assertEqual(len(self.bob.store.conversation(self.alice.identity.public)), 1)
        self.assertEqual(len(self.bob.arrived), 1)

    async def test_pictures_only_after_the_symbols_were_compared(self):
        self.bob.store.set_verified(self.alice.identity.public, False)
        picture = self.alice.write(self.bob, message.Message.picture(PNG, "image/png"))
        result = await self.send()
        self.assertEqual(result.refused, [picture.id])
        self.assertEqual(self.bob.store.conversation(self.alice.identity.public), [])
        self.assertEqual(list(self.bob.store.pictures.iterdir()), [])
        self.assertEqual(self.alice.store.queued(self.bob.identity.public), [])  # not retried forever
        self.bob.store.set_verified(self.alice.identity.public)
        again = self.alice.write(self.bob, message.Message.picture(PNG, "image/png"))
        self.assertEqual((await self.send()).sent, [again.id])
        self.assertEqual(len(list(self.bob.store.pictures.iterdir())), 1)

    async def test_a_picture_the_sandbox_refuses_is_not_kept(self):
        evil = self.alice.write(self.bob, message.Message.picture(PNG + b"EVIL", "image/png"))
        result = await self.send()
        self.assertEqual(result.refused, [evil.id])
        self.assertEqual(self.bob.store.conversation(self.alice.identity.public), [])
        self.assertEqual(self.bob.cleaned, [len(PNG) + 4])  # it went through the cleaner, on Bob's side

    async def test_receiving_off_keeps_messages_with_the_sender(self):
        self.bob.receiving = False
        hello = self.alice.write(self.bob, message.Message.text("are you there?"))
        result = await self.send()
        self.assertEqual((result.sent, result.deferred), ([], [hello.id]))
        self.assertEqual(self.alice.store.queued(self.bob.identity.public), [hello.id])  # still waiting here
        self.assertEqual(self.bob.store.conversation(self.alice.identity.public, waiting=True), [])
        self.bob.receiving = True
        self.assertEqual((await self.send()).sent, [hello.id])

    async def test_new_contacts_wait_for_a_yes_and_tricks_are_held(self):
        self.bob.knows(self.alice, accepted=False)
        first = self.alice.write(self.bob, message.Message.text("hi, it's Alice"))
        trick = self.alice.write(self.bob, message.Message.text("Your account will be suspended, log in at "
                                                                 "http://paypal-secure.example.com/login"))
        await self.send()
        await asyncio.sleep(0.05)
        alice = self.alice.identity.public
        self.assertEqual(self.bob.store.conversation(alice), [])  # nothing shown before Bob decides
        self.assertEqual({m["state"] for m in self.bob.store.conversation(alice, waiting=True)}, {"request"})
        self.bob.store.accept(alice)
        shown = {m["id"]: m for m in self.bob.store.conversation(alice)}
        held = {m["id"]: m for m in self.bob.store.conversation(alice, waiting=True)}
        self.assertEqual((list(shown), list(held)), ([first.id], [trick.id]))
        self.assertIn("lookalike", held[trick.id]["warning"])
        self.bob.store.delete_waiting(alice, trick.id)
        self.assertEqual(self.bob.store.conversation(alice, waiting=True), [])
        # an accepted contact's next suspicious message is held too
        again = self.alice.write(self.bob, message.Message.text("urgent: send me the verification code"))
        await self.send()
        await asyncio.sleep(0.05)
        self.assertEqual([m["id"] for m in self.bob.store.conversation(alice, waiting=True)], [again.id])
        self.bob.store.show(alice, again.id)
        self.assertIn(again.id, [m["id"] for m in self.bob.store.conversation(alice)])

    async def test_two_big_pictures_cross_without_waiting_on_each_other(self):
        big = b"\x89PNG\r\n\x1a\n" + os.urandom(6 * 1024 * 1024)
        for _ in range(2):
            self.alice.write(self.bob, message.Message.picture(big, "image/png"))
            self.bob.write(self.alice, message.Message.picture(big, "image/png"))
        result = await self.send()
        self.assertEqual((len(result.sent), len(result.received)), (2, 2))


class RefusalTests(Base):
    async def test_a_stranger_gets_nothing(self):
        stranger = Person(Path(self.tmp.name), "Mallory")
        self.addCleanup(stranger.store.close)
        stranger.knows(self.bob)
        stranger.write(self.bob, message.Message.text("let me in"))
        with self.assertRaises(transport.TransportError):
            await stranger.node.deliver(self.bob.identity.public, transport.tcp("127.0.0.1", self.port))
        self.assertEqual(self.bob.arrived, [])

    async def test_someone_else_at_the_address(self):
        carol = Person(Path(self.tmp.name), "Carol")
        self.addCleanup(carol.store.close)
        carol.knows(self.alice)
        server = await asyncio.start_server(carol.node.handle, "127.0.0.1", 0)
        self.addAsyncCleanup(server.wait_closed)
        self.addCleanup(server.close)
        hello = self.alice.write(self.bob, message.Message.text("for Bob only"))
        with self.assertRaises(transport.TransportError):
            await self.send(server.sockets[0].getsockname()[1])
        self.assertEqual(self.alice.store.queued(self.bob.identity.public), [hello.id])  # still waiting for Bob
        self.assertEqual(carol.arrived, [])

    async def test_an_offline_contact_keeps_the_queue(self):
        hello = self.alice.write(self.bob, message.Message.text("later"))
        self.server.close()
        await self.server.wait_closed()
        with self.assertRaises(transport.TransportError):
            await self.send()
        self.assertEqual(self.alice.store.queued(self.bob.identity.public), [hello.id])

    async def test_a_changed_byte_ends_the_connection_and_nothing_is_kept(self):
        async def flip(reader, writer):  # a relay that changes one byte after the handshake
            up_r, up_w = await asyncio.open_connection("127.0.0.1", self.port)
            seen = 0

            async def copy(src, dst, tamper):
                nonlocal seen
                try:
                    while data := await src.read(65536):
                        if tamper and seen + len(data) > 200 and seen <= 200:
                            data = bytearray(data)
                            data[200 - seen] ^= 1
                            data = bytes(data)
                        if tamper:
                            seen += len(data)
                        dst.write(data)
                        await dst.drain()
                except ConnectionError:
                    pass
                finally:
                    dst.close()

            await asyncio.gather(copy(reader, up_w, True), copy(up_r, writer, False))

        relay = await asyncio.start_server(flip, "127.0.0.1", 0)
        self.addAsyncCleanup(relay.wait_closed)
        self.addCleanup(relay.close)
        self.alice.write(self.bob, message.Message.text("x" * 500))
        with self.assertRaises(transport.TransportError):
            await self.send(relay.sockets[0].getsockname()[1])
        await asyncio.sleep(0.1)
        self.assertEqual(self.bob.arrived, [])
        self.assertEqual(self.alice.store.queued(self.bob.identity.public).__len__(), 1)

    async def test_a_receipt_only_counts_from_the_person_it_was_sent_to(self):
        dana = keys.Identity.generate().public
        self.alice.store.add_contact(store.Contact(dana, "Dana"))
        hello = self.alice.write(self.bob, message.Message.text("for Bob"))
        self.alice.store.set_state(dana, hello.id, "seen")  # Dana claims to have seen Bob's message
        self.assertEqual(self.alice.store.queued(self.bob.identity.public), [hello.id])

    def test_too_many_attempts(self):
        clock = [0.0]
        limit = transport.RateLimit(3, clock=lambda: clock[0])
        self.assertEqual([limit.allow("10.0.0.5") for _ in range(4)], [True, True, True, False])
        self.assertTrue(limit.allow("10.0.0.6"))
        clock[0] = 61
        self.assertTrue(limit.allow("10.0.0.5"))


class SocksTests(unittest.IsolatedAsyncioTestCase):
    async def test_onion_names_through_tor(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, asked = str(Path(tmp) / "socks"), []

            async def fake_tor(reader, writer):
                assert await reader.readexactly(3) == b"\x05\x01\x00"
                writer.write(b"\x05\x00")
                head = await reader.readexactly(5)
                asked.append((await reader.readexactly(head[4])).decode())
                asked.append(int.from_bytes(await reader.readexactly(2), "big"))
                writer.write(b"\x05\x00\x00\x01" + bytes(6) + b"ready")
                await writer.drain()
                writer.close()  # Python 3.12's Server.wait_closed waits for every connection

            server = await asyncio.start_unix_server(fake_tor, path)
            async with server:
                reader, writer = await transport.tor("a" * 56 + ".onion", path)()
                self.assertEqual(await reader.readexactly(5), b"ready")
                writer.close()
            self.assertEqual(asked, ["a" * 56 + ".onion", transport.PORT])

    async def test_offline_and_wrong_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "socks")

            async def unreachable(reader, writer):
                await reader.readexactly(3)
                writer.write(b"\x05\x00")
                await reader.read(300)
                writer.write(b"\x05\x04\x00\x01" + bytes(6))  # host unreachable
                await writer.drain()
                writer.close()

            server = await asyncio.start_unix_server(unreachable, path)
            async with server:
                with self.assertRaises(transport.TransportError):
                    await transport.tor("b" * 56 + ".onion", path)()
                with self.assertRaises(transport.TransportError):
                    await transport.tor("example.com", path)()  # never a clear-web name through here


if __name__ == "__main__":
    unittest.main()
