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
import subprocess
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

    def start(self, address, announce=True):
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
        self.service = service.Service(self.identity, self.onion_seed, self.store,
                                       service.Settings(lan=True, tor=False, receive=True, name=f"{name} L"),
                                       discovery=FakeDiscovery(book), on_message=lambda c, state: self.arrived.append((c, state)), port=0)
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
            self.book[discovery.short(person.identity.public)] = person.service.chat_server.sockets[0].getsockname()[1]

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
        # the notification names, never shows; a new contact's message is a request until Bob says yes
        self.assertEqual([(c.name, state) for c, state in self.bob.arrived], [("Alice", "request")])
        self.assertEqual(self.alice.store.queued(bob.public), [])
        alice = self.alice.identity.public
        self.assertEqual(self.bob.store.contact(alice).display, "Alice L")  # the name Alice chose
        self.assertEqual(self.bob.store.conversation(alice), [])
        self.bob.store.accept(alice)
        self.assertEqual(self.bob.store.conversation(alice)[0]["text"], "שלום בוב")

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
        code, said = self.run_cli("code")
        self.assertEqual(code, 2)  # a display name first, never the user name
        self.assertIn("dai-chat name", said)
        self.assertEqual(self.run_cli("name", "\u202e", "\n")[0], 2)  # nothing visible is not a name
        self.assertIn("Dana L", self.run_cli("name", "Dana", "L")[1])
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
        picture = Path(self.tmp.name) / "photo.png"
        picture.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(64))
        db = store.Store(Path(self.tmp.name) / "data" / "dai" / "chat")
        db.set_verified(dana.public, False)
        db.close()
        self.assertEqual(self.run_cli("send-picture", "Dana", str(picture))[0], 2)  # symbols not compared yet
        self.run_cli("verify", "Dana")
        with mock.patch("dai_chat.pictures.clean", return_value=(b"\x89PNG\r\n\x1a\nCLEAN", "image/png")) as clean:
            code, said = self.run_cli("send-picture", "Dana", str(picture))
        self.assertEqual((code, clean.call_count), (0, 1))  # re-drawn before it is queued
        self.assertIn("without its location", said)
        self.assertIn("[a picture]", self.run_cli("read", "Dana")[1])
        self.assertEqual(self.run_cli("send-picture", "Dana", str(picture) + ".missing")[0], 2)

    def test_the_local_network_goes_through_tune(self):
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 1 if "refuse" in os.environ.get("TUNE", "") else 0, b"", b"")

        with mock.patch("dai_chat.cli.subprocess.run", side_effect=run):
            self.assertEqual(self.run_cli("lan", "on")[0], 0)
            self.assertEqual(calls[0], ["dai-tune", "open port 7714 and open udp port 5353"])
            self.assertTrue(service.Settings.load(service.settings_path()).lan)
            self.assertIn("try-restart", calls[1])
            with mock.patch.dict(os.environ, {"TUNE": "refuse"}):
                calls.clear()
                self.run_cli("lan", "off")  # closing is saved even if Tune was cancelled: Chat stops listening
            self.assertEqual(calls[0], ["dai-tune", "close port 7714 and close udp port 5353"])
            self.assertFalse(service.Settings.load(service.settings_path()).lan)
            with mock.patch.dict(os.environ, {"TUNE": "refuse"}):
                code, said = self.run_cli("lan", "on")
            self.assertEqual(code, 1)
            self.assertIn("Tor only", said)
            self.assertFalse(service.Settings.load(service.settings_path()).lan)

    def test_receiving_and_requests(self):
        self.run_cli("name", "Noa")
        self.assertFalse(service.Settings.load(service.settings_path()).receive)  # off by default
        with mock.patch("dai_chat.cli.subprocess.run", return_value=subprocess.CompletedProcess([], 0)):
            self.assertIn("Receiving is on", self.run_cli("receive", "on")[1])
        self.assertTrue(service.Settings.load(service.settings_path()).receive)
        dana = keys.Identity.generate().public
        db = store.Store(Path(self.tmp.name) / "data" / "dai" / "chat")
        db.add_contact(store.Contact(dana, "Dana"))
        db.add_message(dana, message.Message.text("hi Noa"), outgoing=False, state="request")
        trick = message.Message.text("verify your account at http://1.2.3.4/x")
        db.add_message(dana, trick, outgoing=False, state="request", warning="ip_link,asks")
        db.close()
        said = self.run_cli("requests")[1]
        self.assertIn("dai-chat accept Dana", said)
        self.assertIn("hi Noa", said)
        self.assertNotIn("1.2.3.4", said)  # a suspicious text is not printed
        self.run_cli("accept", "Dana")
        self.assertIn("hi Noa", self.run_cli("read", "Dana")[1])
        said = self.run_cli("requests")[1]
        self.assertIn("held", said)
        self.assertIn("a link goes to a bare IP address", said)
        self.assertEqual(self.run_cli("discard", "Dana", trick.id[:8])[0], 0)
        self.assertIn("Nothing is waiting", self.run_cli("requests")[1])
        self.assertIn("blocked Dana", self.run_cli("decline", "Dana")[1])

    def test_send_takes_the_text_from_stdin_too(self):
        """Review finding 13: a message on the command line is visible to every user in ps."""
        self.run_cli("name", "Me")
        dana = keys.Identity.generate()
        danas = invite.make(keys.Identity.generate().public, dana.public)
        self.assertEqual(self.run_cli("add", "Dana", danas)[0], 0)
        db = store.Store(Path(self.tmp.name) / "data" / "dai" / "chat")
        db.paired(invite.parse(danas).fingerprint, dana.public)
        db.close()
        with mock.patch("sys.stdin", io.StringIO("quiet words\n")):
            code, said = self.run_cli("send", "Dana")
        self.assertEqual(code, 0, said)
        self.assertIn("me: quiet words", self.run_cli("read", "Dana")[1])
        with mock.patch("sys.stdin", io.StringIO("")):
            self.assertEqual(self.run_cli("send", "Dana")[0], 2)

    def test_unknown_contact_and_help(self):
        self.assertEqual(self.run_cli("send", "Nobody", "hi")[0], 2)
        self.assertEqual(self.run_cli()[0], 0)
        self.assertEqual(self.run_cli("status")[0], 1)  # the service is not running


if __name__ == "__main__":
    unittest.main()
