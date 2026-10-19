# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The background service and the command line (dai_chat/service.py, cli.py): two people swap codes,
pair, write and read, with the service delivering on its own; waiting longer after failures; the control
socket; and the command line's answers."""
import asyncio
import importlib.util
import io
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

if importlib.util.find_spec("nacl") is None:  # python3-nacl, in Debian
    raise unittest.SkipTest("PyNaCl is missing")

from dai_chat import cli, discovery, invite, keys, message, service, store


class FakeDiscovery:
    """Stands in for mDNS: everyone in `book` is "seen" on 127.0.0.1 at their port."""

    def __init__(self, book):
        self.book = book

    def start(self, address):
        pass

    def refresh(self, address):
        pass

    def stop(self):
        pass

    def find(self, fpr):
        return [discovery.Seen("", "127.0.0.1", port) for key, port in self.book.items() if key == fpr]


class Person:
    def __init__(self, folder: Path, name: str, book: dict) -> None:
        self.name, self.identity, self.onion_seed = name, keys.Identity.generate(), os.urandom(32)
        self.store = store.Store(folder / name)
        self.arrived = []
        self.service = service.Service(self.identity, self.onion_seed, self.store, service.Settings(lan=True, tor=False),
                                       discovery=FakeDiscovery(book), on_message=self.arrived.append, port=0)
        self.code = service.invite_code(self.onion_seed, self.identity)
        self.control = folder / f"{name}-run" / "app.sock"


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir="/tmp")  # Unix socket paths must stay short
        self.addCleanup(self.tmp.cleanup)
        self.book = {}
        self.alice = Person(Path(self.tmp.name), "Alice", self.book)
        self.bob = Person(Path(self.tmp.name), "Bob", self.book)
        for person in (self.alice, self.bob):
            await person.service.start(person.control)
            self.addCleanup(person.store.close)
            self.addCleanup(person.service.stop)
            self.book[discovery.short(person.identity.public)] = person.service.servers[0].sockets[0].getsockname()[1]

    async def test_swap_codes_pair_and_talk(self):
        self.alice.store.wait_for(invite.parse(self.bob.code), "Bob")
        await self.alice.service.round()  # Bob has not typed Alice's code yet
        self.assertEqual(self.alice.store.contacts(), [])
        self.bob.store.wait_for(invite.parse(self.alice.code), "Alice")
        self.alice.service.backoff.reset()
        await self.alice.service.round()
        await asyncio.sleep(0.05)
        bob = self.alice.store.contacts()[0]
        self.assertEqual((bob.name, bob.public, bob.verified), ("Bob", self.bob.identity.public, False))
        self.assertEqual(self.bob.store.contacts()[0].public, self.alice.identity.public)
        self.assertEqual(self.bob.store.waiting(), [])
        hello = message.Message.text("שלום בוב")
        self.alice.store.add_message(bob.public, hello, outgoing=True, state="queued")
        await self.alice.service.round()
        await asyncio.sleep(0.05)
        self.assertEqual([c.name for c in self.bob.arrived], ["Alice"])  # the notification names, never shows
        self.assertEqual(self.alice.store.queued(bob.public), [])
        self.assertEqual(self.bob.store.conversation(self.alice.identity.public)[0]["text"], "שלום בוב")

    async def test_control_socket(self):
        self.assertEqual(stat.S_IMODE(self.alice.control.stat().st_mode), 0o600)
        reply = await asyncio.to_thread(service.poke, self.alice.control, "status")
        self.assertEqual((reply["ok"], reply["lan"], reply["tor"]), (True, True, "off"))
        self.assertEqual(await asyncio.to_thread(service.poke, self.alice.control), {"ok": True})
        self.assertTrue(self.alice.service.poked.is_set())
        self.assertIsNone(service.poke(Path(self.tmp.name) / "nobody.sock"))

    def test_waiting_longer_after_each_failure(self):
        backoff, key = service.Backoff(), "Dana"
        waits = []
        for _ in range(8):
            backoff.failed(key, 0)
            waits.append(backoff.due[key])
        self.assertEqual(waits[:4], [30, 60, 120, 240])
        self.assertEqual(waits[-1], service.MAX_WAIT)
        self.assertFalse(backoff.ready(key, 100))
        backoff.reset()
        self.assertTrue(backoff.ready(key, 0))

    def test_settings(self):
        path = Path(self.tmp.name) / "chat.json"
        self.assertEqual(service.Settings.load(path), service.Settings(lan=False, tor=True))  # the defaults
        service.Settings(lan=True, tor=True).save(path)
        self.assertTrue(service.Settings.load(path).lan)
        path.write_text('{"lan": "yes"}')
        self.assertFalse(service.Settings.load(path).lan)  # only a real true turns it on


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(self.tmp.cleanup)
        env = {"XDG_DATA_HOME": f"{self.tmp.name}/data", "XDG_CONFIG_HOME": f"{self.tmp.name}/config",
               "XDG_RUNTIME_DIR": f"{self.tmp.name}/run", "LANG": "en_US.UTF-8", "LANGUAGE": "en"}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_cli(self, *args):
        out = io.StringIO()
        files = lambda folder: ([keys.FileStore(folder / "identity")], [keys.FileStore(folder / "onion")])  # noqa: E731
        code = cli.main(["dai-chat", *args], stores=files, out=out)
        return code, out.getvalue()

    def test_a_conversation_from_the_command_line(self):
        code, mine = self.run_cli("code")
        self.assertEqual(code, 0)
        self.assertEqual(self.run_cli("code")[1], mine)  # the same code every time
        identity_file = Path(self.tmp.name) / "data" / "dai" / "chat" / "identity"
        self.assertEqual(stat.S_IMODE(identity_file.stat().st_mode), 0o600)
        dana = keys.Identity.generate()
        danas = invite.make(keys.Identity.generate().public, dana.public)
        self.assertEqual(self.run_cli("add", "Dana", danas[:-1] + ("a" if danas[-1] != "a" else "b"))[0], 2)  # typo
        self.assertEqual(self.run_cli("add", "Me", mine.strip())[0], 2)  # your own code
        self.assertEqual(self.run_cli("add", "Dana", danas)[0], 0)
        self.assertIn("Dana", self.run_cli("contacts")[1])
        # as if pairing finished, then talk
        db = store.Store(Path(self.tmp.name) / "data" / "dai" / "chat")
        db.paired(invite.parse(danas).fingerprint, dana.public)
        db.close()
        self.assertIn("not verified", self.run_cli("contacts")[1])
        code, symbols = self.run_cli("symbols", "dan")  # the start of a name is enough
        self.assertEqual((code, symbols.count(" · ")), (0, 5))
        self.run_cli("verify", "Dana")
        self.assertIn("(verified)", self.run_cli("contacts")[1])
        code, said = self.run_cli("send", "Dana", "see", "you", "at", "six")
        self.assertIn("Turn Diamond Chat on", said)  # the service is not running here: it waits
        self.assertIn("me: see you at six", self.run_cli("read", "Dana")[1])
        self.assertIn("Deleted 1 messages", self.run_cli("delete", "Dana")[1])

    def test_unknown_contact_and_help(self):
        self.assertEqual(self.run_cli("send", "Nobody", "hi")[0], 2)
        self.assertEqual(self.run_cli()[0], 0)
        self.assertEqual(self.run_cli("status")[0], 1)  # the service is not running


if __name__ == "__main__":
    unittest.main()
